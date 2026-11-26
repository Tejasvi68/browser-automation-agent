from typing import Any, Dict, Optional
import re
from urllib.parse import urljoin, urlparse

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from app.agent.executor import StepExecutor
from app.agent.planner import AgentPlanner
from app.agent.state import AgentState
from app.browser.browser_actions import BrowserActions
from app.browser.browser_manager import BrowserManager
from app.config import agent_yaml_config, settings
from app.memory.workflow_memory import WorkflowMemory
from app.perception.dom_analyzer import DOMAnalyzer
from app.perception.vision_analyzer import VisionAnalyzer
from app.security.approval_manager import approval_manager
from app.security.credential_vault import CredentialVault


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_langfuse_callbacks(run_id: str, user_id: str) -> list:
    """Returns a Langfuse tracing callback if credentials are configured, else []."""
    if not (settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY):
        return []
    try:
        from langfuse.callback import CallbackHandler
        return [CallbackHandler(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
            session_id=run_id,
            user_id=user_id,
        )]
    except Exception:
        return []


# ── Orchestrator ──────────────────────────────────────────────────────────────

class BrowserAgentOrchestrator:
    def __init__(
        self,
        browser_manager: BrowserManager,
        planner: Optional[AgentPlanner] = None,
        dom_analyzer: Optional[DOMAnalyzer] = None,
        vision_analyzer: Optional[VisionAnalyzer] = None,
        workflow_memory: Optional[WorkflowMemory] = None,
        vault: Optional[CredentialVault] = None,
        db: Optional[Session] = None,
    ):
        self.browser = browser_manager
        self.actions = BrowserActions(browser_manager)
        self.planner = planner or AgentPlanner()
        self.dom = dom_analyzer or DOMAnalyzer()
        self.vision = vision_analyzer   # Optional multimodal fallback
        self.memory = workflow_memory   # RAG vector store
        self.vault = vault              # Encrypted credential store
        self.db = db

        self.executor = StepExecutor(self.actions, vault=vault, db=db)
        self.max_steps = agent_yaml_config.get("agent", {}).get("max_steps", 15)

        # Build the LangGraph workflow once at construction time
        self.graph = self._build_graph()

    # ── Graph construction ────────────────────────────────────────────────────

    def _build_graph(self):
        """Wires up all nodes and conditional edges into a compiled LangGraph."""
        workflow = StateGraph(AgentState)

        # Register every node
        workflow.add_node("retrieve_memory", self._node_retrieve_memory)
        workflow.add_node("perceive",        self._node_perceive)
        workflow.add_node("plan",            self._node_plan)
        workflow.add_node("safety_gate",     self._node_safety_gate)
        workflow.add_node("execute",         self._node_execute)
        workflow.add_node("self_heal",       self._node_self_heal)
        workflow.add_node("finalize",        self._node_finalize)

        # Fixed edges
        workflow.set_entry_point("retrieve_memory")
        workflow.add_edge("retrieve_memory", "perceive")
        workflow.add_edge("perceive",        "plan")
        workflow.add_edge("self_heal",       "perceive")  # Retry loop
        workflow.add_edge("finalize",        END)

        # Conditional: after plan → either stop (finish/failed) or check safety
        workflow.add_conditional_edges(
            "plan",
            self._route_after_plan,
            {"finish": "finalize", "safety_gate": "safety_gate"},
        )

        # Conditional: after safety gate → either pause for human or execute
        workflow.add_conditional_edges(
            "safety_gate",
            self._route_after_safety,
            {"execute": "execute", "pause": END},
        )

        # Conditional: after execute → retry on error, loop, or finish
        workflow.add_conditional_edges(
            "execute",
            self._route_after_execute,
            {"perceive": "perceive", "self_heal": "self_heal", "finalize": "finalize"},
        )

        return workflow.compile()

    # ── Node 1: Retrieve memory ───────────────────────────────────────────────

    async def _node_retrieve_memory(self, state: AgentState) -> Dict[str, Any]:
        """
        Loads two things from persistent storage:
          - RAG context: past similar workflows that might guide the planner
          - Vault credentials: safe placeholders the LLM can use in type actions
        """
        # Retrieve similar past runs from vector memory
        rag_text = "No prior similar workflows found in memory."
        if self.memory:
            matches = self.memory.retrieve_relevant_workflows(
                task=state["task"], user_id=state["user_id"], top_k=3
            )
            rag_text = self.memory.format_for_planner_prompt(matches)

        # Retrieve credential labels (never raw passwords) from vault
        credentials = []
        if self.vault and self.db:
            credentials = self.vault.list_credentials_for_prompt(self.db, state["user_id"])

        return {"rag_context": rag_text, "available_credentials": credentials}

    # ── Node 2: Perceive ──────────────────────────────────────────────────────

    async def _node_perceive(self, state: AgentState) -> Dict[str, Any]:
        """
        Takes a DOM snapshot of the current page and formats it into text
        that the planner LLM can read (element IDs, labels, visible text).
        """
        page = self.browser.active_page
        snapshot = await self.dom.inspect(page)
        formatted = self.dom.format_for_prompt(snapshot)
        return {"dom_snapshot": snapshot, "formatted_dom": formatted}

    # ── Node 3: Plan ──────────────────────────────────────────────────────────

    async def _node_plan(self, state: AgentState) -> Dict[str, Any]:
        """
        Asks the LLM to decide the next browser action based on the current
        page state, task goal, step history, and any prior errors.
        Returns early with a 'failed' status if the step budget is exhausted.
        """
        prior_submission = next((
            step for step in reversed(state.get("steps_history", []))
            if step.get("form_submission")
        ), None)
        if prior_submission:
            if prior_submission.get("success") and prior_submission.get("submission_confirmed"):
                answer = "The website confirmed that the form was submitted successfully."
                return {"next_action": {"action": "finish", "params": {}, "final_answer": answer}}
            submission_data = prior_submission.get("data") or {}
            detail = submission_data.get("submission_error") or (
                "The site was still showing a sending state after the wait limit."
                if submission_data.get("submission_still_sending") else "Check the page for validation errors or a failed submit action."
            )
            message = f"The form submission was not confirmed. {detail} The agent stopped without refilling or resubmitting the form."
            return {
                "status": "failed",
                "last_error": message,
                "next_action": {"action": "finish", "params": {}, "final_answer": message},
            }

        # Hard stop if we've hit the maximum number of allowed steps
        if state["step_count"] >= state["max_steps"]:
            return {
                "status": "failed",
                "last_error": f"Reached the maximum step limit of {state['max_steps']}.",
                "next_action": {
                    "action": "finish",
                    "final_answer": "Stopped: maximum step limit reached.",
                },
            }

        step_num = state["step_count"] + 1
        print(f"[STEP {step_num}] Planning next action...", flush=True)

        callbacks = _get_langfuse_callbacks(state["run_id"], state["user_id"])
        decision = await self.planner.decide_next_action(state, callbacks=callbacks)

        snapshot = state.get("dom_snapshot", {})
        # A filled form field must not consume the run's step budget repeatedly.
        # Re-prompt once with explicit feedback; if the model still selects that
        # field, fail clearly instead of typing the same value until timeout.
        planned_params = decision.get("params") or {}
        planned_id = planned_params.get("element_id")
        planned_element = next((
            item for item in snapshot.get("interactive_elements", [])
            if str(item.get("element_id")) == str(planned_id)
        ), None)
        replace_requested = bool(re.search(
            r"\b(replace|overwrite|correct|change|update|edit)\b",
            str(state.get("task", "")), re.I,
        ))
        if (
            decision.get("action") == "type"
            and planned_element
            and planned_element.get("value_present")
            and not replace_requested
        ):
            field_label = (
                planned_element.get("label")
                or planned_element.get("placeholder")
                or planned_element.get("name")
                or f"element {planned_id}"
            )
            warning = (
                f"The '{field_label}' field already contains a value. Do not type into it again; "
                "continue with another empty requested field or submit only after all required fields are handled."
            )
            corrected_state = dict(state)
            corrected_state["last_error"] = warning
            corrected = await self.planner.decide_next_action(corrected_state, callbacks=callbacks)
            corrected_id = (corrected.get("params") or {}).get("element_id")
            corrected_element = next((
                item for item in snapshot.get("interactive_elements", [])
                if str(item.get("element_id")) == str(corrected_id)
            ), None)
            if (
                corrected.get("action") == "type"
                and corrected_element
                and corrected_element.get("value_present")
                and not replace_requested
            ):
                message = (
                    f"Stopped safely because the agent kept retrying the already-filled '{field_label}' field. "
                    "No more values were typed and the form was not submitted."
                )
                return {
                    "status": "failed",
                    "last_error": message,
                    "next_action": {"action": "finish", "params": {}, "final_answer": message},
                }
            decision = corrected

        page_text = str(snapshot.get("visible_text_snippet", "")).lower()
        task_requests_login = bool(re.search(r"\b(log\s*in|sign\s*in|authenticate)\b", state.get("task", ""), re.I))
        login_required = self._login_required(page_text)
        login_rejected = self._login_rejected(page_text)
        login_submission_attempted = any(
            step.get("login_submission")
            for step in state.get("steps_history", [])
        )
        password_field = next((
            item for item in snapshot.get("interactive_elements", [])
            if str(item.get("type", "")).lower() == "password"
        ), None)
        auth_form_visible = bool(password_field)

        if login_rejected or (login_submission_attempted and (login_required or auth_form_visible)):
            message = (
                "The website rejected the login details. No output was generated; verify the saved credential and try again."
                if login_rejected
                else "The login form remained open after submission. The site did not accept the login, so the task stopped without generating output."
            )
            return {
                "status": "failed",
                "last_error": message,
                "next_action": {"action": "finish", "params": {}, "final_answer": message},
            }

        auth_flow = task_requests_login or login_required or state.get("login_approval_granted", False)
        if auth_form_visible and auth_flow:
            credentials = state.get("available_credentials", [])
            matching_credentials = self._credentials_for_url(credentials, snapshot.get("url", ""))
            credential = self._credential_for_url(
                matching_credentials,
                state.get("task", ""),
            )
            fields = snapshot.get("interactive_elements", [])
            username_field = next((
                item for item in fields
                if item.get("tag") == "input"
                and str(item.get("type", "")).lower() != "password"
                and re.search(r"email|user(name)?|account|login", " ".join(
                    str(item.get(key, "")) for key in ("placeholder", "aria_label", "name", "autocomplete")
                ), re.I)
            ), None)
            if not credential:
                message = (
                    "More than one saved credential matches this website. Include the exact vault label in the task so the agent can choose safely."
                    if matching_credentials
                    else "Login is required, but the vault has no credential whose domain matches this website. Add the correct site credential and retry."
                )
                return {"status": "failed", "last_error": message, "next_action": {"action": "finish", "final_answer": message}}
            if not username_field:
                message = "A login form is open, but no email or username field was found. The agent stopped without submitting credentials."
                return {"status": "failed", "last_error": message, "next_action": {"action": "finish", "final_answer": message}}

            history = state.get("steps_history", [])
            username_entered = any(step.get("success") and step.get("field_role") == "username" for step in history)
            password_entered = any(step.get("success") and step.get("field_role") == "password" for step in history)
            if not username_entered:
                decision = {
                    "action": "type",
                    "params": {"element_id": username_field["element_id"], "text": credential["username"], "clear": True},
                    "thought": "Fill the matching saved username in the open login form.",
                    "is_sensitive": True,
                }
            elif not password_entered:
                decision = {
                    "action": "type",
                    "params": {"element_id": password_field["element_id"], "text": credential["password_placeholder"], "clear": True},
                    "thought": "Fill the matching saved password in the open login form.",
                    "is_sensitive": True,
                }
            else:
                submit_button = next((
                    item for item in fields
                    if re.search(r"\b(login|log\s*in|sign\s*in|signin|submit)\b", " ".join(
                        str(item.get(key, "")) for key in ("text", "aria_label", "name")
                    ), re.I)
                ), None)
                if submit_button:
                    label = submit_button.get("text") or submit_button.get("aria_label") or "Login"
                    decision = {
                        "action": "click",
                        "params": {"element_id": submit_button["element_id"], "target_label": label},
                        "thought": "Submit the login form after both saved credential fields were filled.",
                        "is_sensitive": True,
                    }
                else:
                    decision = {
                        "action": "press_key",
                        "params": {"key": "Enter"},
                        "thought": "Submit the completed login form with Enter.",
                        "is_sensitive": True,
                    }
        elif (login_required or task_requests_login) and not login_submission_attempted:
            login_control = next((
                element for element in snapshot.get("interactive_elements", [])
                if re.search(
                    r"\b(login|log\s*in|sign\s*in|authenticate)\b",
                    " ".join(str(element.get(key, "")) for key in ("text", "aria_label", "url")),
                    re.I,
                )
            ), None)
            decision_element = next((
                element for element in snapshot.get("interactive_elements", [])
                if str(element.get("element_id")) == str((decision.get("params") or {}).get("element_id"))
            ), None)
            decision_is_login = approval_manager.is_login_related(
                decision.get("action", ""), decision.get("params", {}),
                element=decision_element, dom_snapshot=snapshot,
            )
            if login_control and not decision_is_login:
                label = login_control.get("text") or login_control.get("aria_label") or "Login"
                decision = {
                    "action": "click",
                    "params": {"element_id": login_control["element_id"], "target_label": label},
                    "thought": "The task or page requires authentication. Request human approval before opening login.",
                    "is_sensitive": True,
                }

        # A route the user did not provide and the page did not expose is an
        # unverified URL. Prefer the visible link, or stop instead of guessing.
        if decision.get("action") == "navigate":
            proposed_url = str((decision.get("params") or {}).get("url", ""))
            current_url = str(snapshot.get("url", ""))
            if proposed_url.startswith(("http://", "https://", "data:")):
                absolute_proposal = proposed_url
            elif current_url and urlparse(current_url).hostname and proposed_url.startswith(("/", "#", "?")):
                absolute_proposal = urljoin(current_url, proposed_url)
            elif current_url and urlparse(current_url).hostname and "." not in proposed_url.split("/", 1)[0]:
                absolute_proposal = urljoin(current_url, proposed_url)
            else:
                absolute_proposal = f"https://{proposed_url.lstrip('/')}"
            proposed_host = (urlparse(absolute_proposal).hostname or "").lower()
            observed_urls = {
                urljoin(current_url, str(item.get("url", ""))).rstrip("/").lower()
                for item in snapshot.get("interactive_elements", []) if item.get("url")
            }
            explicit_task_urls = set(re.findall(r"https?://[^\s'\"<>]+", state.get("task", ""), re.I))
            proposal_is_explicit = absolute_proposal.rstrip("/").lower() in {
                urljoin(current_url, item.rstrip(".,;)")).rstrip("/").lower()
                for item in explicit_task_urls
            }
            observed_link = next((
                item for item in snapshot.get("interactive_elements", [])
                if item.get("url")
                and urljoin(current_url, str(item["url"])).rstrip("/").lower() == absolute_proposal.rstrip("/").lower()
            ), None)
            if observed_link:
                target_label = observed_link.get("text") or observed_link.get("aria_label") or "visible link"
                decision = {
                    "action": "click",
                    "params": {"element_id": observed_link["element_id"], "target_label": target_label},
                    "thought": f"Click the observed '{target_label}' link rather than navigating to its URL directly.",
                    "is_sensitive": bool(decision.get("is_sensitive", False)),
                }
            else:
                initial_target_is_named = bool(
                    state.get("step_count", 0) == 0
                    and proposed_host
                    and (
                        proposed_host in state.get("task", "").lower()
                        or any(
                            proposed_host == (urlparse(
                                str(item.get("domain", ""))
                                if "://" in str(item.get("domain", ""))
                                else f"https://{item.get('domain', '')}"
                            ).hostname or "").lower()
                            for item in state.get("available_credentials", [])
                        )
                    )
                )
                url_is_observed = absolute_proposal.rstrip("/").lower() in observed_urls
                if not (proposal_is_explicit or url_is_observed or initial_target_is_named):
                    route_terms = [
                        term for term in re.findall(r"[a-z0-9]+", urlparse(absolute_proposal).path.lower())
                        if len(term) > 2 and term not in {"html", "page", "index"}
                    ]
                    matching_link = next((
                        item for item in snapshot.get("interactive_elements", [])
                        if any(term in " ".join(str(item.get(key, "")) for key in ("text", "aria_label", "url")).lower() for term in route_terms)
                    ), None) if route_terms else None
                    if matching_link:
                        target_label = matching_link.get("text") or matching_link.get("aria_label") or route_terms[-1].title()
                        decision = {
                            "action": "click",
                            "params": {"element_id": matching_link["element_id"], "target_label": target_label},
                            "thought": f"Use the observed '{target_label}' link instead of guessing a URL.",
                            "is_sensitive": bool(decision.get("is_sensitive", False)),
                        }
                    else:
                        message = "The agent proposed a URL that was not provided in the task or observed on the page. It stopped rather than opening a guessed address."
                        return {"status": "failed", "last_error": message, "next_action": {"action": "finish", "final_answer": message}}

        # Carry DOM-observed labels and hrefs with click actions so Playwright
        # can recover by semantic text if the stamped element id goes stale.
        if decision.get("action") == "click":
            params = dict(decision.get("params") or {})
            element = next((
                item for item in snapshot.get("interactive_elements", [])
                if str(item.get("element_id")) == str(params.get("element_id"))
            ), None)
            if element:
                params["target_label"] = params.get("target_label") or element.get("text") or element.get("aria_label") or element.get("placeholder")
                params["target_tag"] = params.get("target_tag") or element.get("tag")
                params["target_url"] = params.get("target_url") or element.get("url")
                decision = {**decision, "params": params}

        print(
            f"[STEP {step_num}] Planned → action={decision.get('action')}  "
            f"params={decision.get('params')}",
            flush=True,
        )
        return {"next_action": decision}

    def _route_after_plan(self, state: AgentState) -> str:
        """Go to 'finalize' if the agent is done or failed; otherwise check safety."""
        decision = state.get("next_action") or {}
        if decision.get("action") == "finish" or state.get("status") == "failed":
            return "finish"
        return "safety_gate"

    @staticmethod
    def _login_required(page_text: str) -> bool:
        normalized = " ".join(str(page_text or "").lower().split())
        return bool(re.search(
            r"(login|log\s*in|sign\s*in).{0,50}(required|to continue|to generate|to proceed)|"
            r"(please\s+)?(log\s*in|sign\s*in)\s+to\s+(continue|generate|proceed)",
            normalized,
        ))

    @staticmethod
    def _login_rejected(page_text: str) -> bool:
        normalized = " ".join(str(page_text or "").lower().split())
        return bool(re.search(
            r"invalid credentials?|incorrect (password|username)|wrong (password|username)|"
            r"authentication failed|unable to (log\s*in|sign\s*in)",
            normalized,
        ))

    @staticmethod
    def _credentials_for_url(credentials: list, url: str) -> list:
        """Return vault entries whose domain matches the active site."""
        host = (urlparse(str(url or "")).hostname or "").lower().removeprefix("www.")
        if not host:
            return []

        def credential_host(credential: Dict[str, str]) -> str:
            domain = str(credential.get("domain", "")).strip()
            parsed = urlparse(domain if "://" in domain else f"https://{domain}")
            return (parsed.hostname or "").lower().removeprefix("www.")

        entries = [(item, credential_host(item)) for item in credentials]
        exact = [item for item, item_host in entries if item_host == host]
        return exact or [
            item for item, item_host in entries
            if item_host and host.endswith(f".{item_host}")
        ]

    @staticmethod
    def _credential_for_url(credentials: list, task: str) -> Optional[Dict[str, str]]:
        """Choose one matching credential only when the task identifies it unambiguously."""
        if len(credentials) == 1:
            return credentials[0]

        task_text = str(task or "").casefold()
        named = [
            item for item in credentials
            if str(item.get("label", "")).strip()
            and str(item.get("label", "")).strip().casefold() in task_text
        ]
        if named:
            longest_label_length = max(len(str(item.get("label", "")).strip()) for item in named)
            most_specific = [
                item for item in named
                if len(str(item.get("label", "")).strip()) == longest_label_length
            ]
            return most_specific[0] if len(most_specific) == 1 else None
        return None

    @staticmethod
    def _field_role(element: Optional[Dict[str, Any]]) -> Optional[str]:
        if not element:
            return None
        field_type = str(element.get("type", "")).lower()
        label = " ".join(str(element.get(key, "")) for key in (
            "label", "placeholder", "aria_label", "name", "autocomplete",
        )).lower()
        if field_type == "password":
            return "password"
        if field_type == "email" or re.search(r"email|user(name)?|account|login", label):
            return "username"
        return None

    # ── Node 4: Safety gate (Human Approval) ──────────────────────────────────

    async def _node_safety_gate(self, state: AgentState) -> Dict[str, Any]:
        """
        Decides whether a human must approve the planned action before it runs.

        Three cases:
          A) Human already approved   → clear the flag and let execution proceed
          B) Human already rejected   → mark as rejected and stop
          C) Action needs approval    → pause graph, store pending decision
        """
        decision = state["next_action"] or {}
        action = decision.get("action", "")
        params = decision.get("params", {})
        is_sensitive = bool(decision.get("is_sensitive", False))
        element_id = params.get("element_id")
        target_element = next((
            item for item in state.get("dom_snapshot", {}).get("interactive_elements", [])
            if str(item.get("element_id")) == str(element_id)
        ), None)

        # Case B: Human explicitly rejected the action
        if state.get("approval_approved") is False:
            return {
                "status": "rejected",
                "final_summary": "Execution was rejected by the user at the safety gate.",
            }

        # Case A: Human approved the pending step. For login, remember that one
        # decision for the credential form through its submit action.
        if state.get("approval_approved") is True:
            login_granted = approval_manager.is_login_related(
                action, params, element=target_element, dom_snapshot=state.get("dom_snapshot")
            )
            return {
                "approval_approved": None,
                "login_approval_granted": bool(state.get("login_approval_granted") or login_granted),
                "status": "running",
            }

        # One human approval authorizes the complete login form through submission.
        if state.get("login_approval_granted") and approval_manager.is_login_related(
            action, params, element=target_element, dom_snapshot=state.get("dom_snapshot")
        ):
            return {"approval_approved": None, "status": "running"}

        # Case C: Check if this action requires approval
        if approval_manager.requires_approval(
            action,
            params,
            is_sensitive=is_sensitive,
            element=target_element,
            dom_snapshot=state.get("dom_snapshot"),
        ):
            target_name = (
                params.get("target_label")
                or (target_element or {}).get("text")
                or (target_element or {}).get("placeholder")
                or ("credential entry" if "{{VAULT:" in str(params.get("text", "")) else action)
            )
            reason = f"Action '{target_name}' requires your approval before it runs."

            # Register the pending approval request so the frontend can show it
            approval_manager.request_approval(
                run_id=state["run_id"],
                step_number=state["step_count"] + 1,
                proposed_action={
                    "action": action,
                    "params": params,
                    "thought": decision.get("thought", ""),
                },
                reason=reason,
            )

            print(
                f"[APPROVAL NEEDED] Step {state['step_count'] + 1}: {reason}",
                flush=True,
            )
            return {
                "status": "awaiting_approval",
                "pending_approval_reason": reason,
            }

        # Action is safe – proceed without asking the human
        return {"status": "running"}

    def _route_after_safety(self, state: AgentState) -> str:
        """Pause graph execution if waiting for or denied by human; otherwise execute."""
        if state.get("status") in ("awaiting_approval", "rejected"):
            return "pause"
        return "execute"

    # ── Node 5: Execute ───────────────────────────────────────────────────────

    async def _node_execute(self, state: AgentState) -> Dict[str, Any]:
        """
        Runs the planned browser action via StepExecutor, records the step in
        history, and immediately persists it to the DB so the frontend can poll
        live progress (screenshots, extracted data) without waiting for the run to end.
        """
        decision = state["next_action"] or {}
        action = decision.get("action", "")
        params = decision.get("params", {})
        step_num = state["step_count"] + 1
        element_id = params.get("element_id")
        target_element = next((
            item for item in state.get("dom_snapshot", {}).get("interactive_elements", [])
            if str(item.get("element_id")) == str(element_id)
        ), None)
        target_label = (
            (target_element or {}).get("label")
            or
            (target_element or {}).get("text")
            or (target_element or {}).get("aria_label")
            or (target_element or {}).get("placeholder")
            or params.get("target_label")
        )
        field_role = self._field_role(target_element)
        login_submission = approval_manager.is_login_submission(
            action, params, element=target_element, dom_snapshot=state.get("dom_snapshot")
        )
        form_submission_candidate = bool(
            action == "click"
            and not login_submission
            and target_element
            and target_element.get("in_form")
            and (target_element.get("is_submit") or re.search(
                r"\b(send|submit)\b", " ".join(str(target_element.get(key, "")) for key in (
                    "label", "text", "aria_label", "name",
                )), re.I,
            ))
            and any(
                item.get("in_form")
                and item.get("form_key") == target_element.get("form_key")
                and (
                    item.get("tag") == "textarea"
                    or re.search(r"\b(message|inquiry|comment)\b", " ".join(str(item.get(key, "")) for key in (
                        "label", "placeholder", "aria_label", "name",
                    )), re.I)
                )
                for item in state.get("dom_snapshot", {}).get("interactive_elements", [])
            )
        )

        print(f"[STEP {step_num}] Executing '{action}'...", flush=True)

        result = await self.executor.run_step(
            user_id=state["user_id"],
            run_id=state["run_id"],
            step_number=step_num,
            action=action,
            params=params,
        )

        print(
            f"[STEP {step_num}] Done → success={result['success']}  "
            f"error={result.get('error')}",
            flush=True,
        )

        # Build the step record for history
        step_record = {
            "step":            step_num,
            "thought":         decision.get("thought", ""),
            "action":          action,
            "target_label":    target_label,
            "field_role":      field_role,
            "login_submission": bool(login_submission),
            "form_submission": bool(form_submission_candidate or (result.get("data") or {}).get("form_submission")),
            "submission_confirmed": bool((result.get("data") or {}).get("submission_confirmed")),
            "params":          result.get("logged_params", params),  # masked if sensitive
            "success":         result["success"],
            "data":            result.get("data"),
            "error":           result.get("error"),
            "url":             self.browser.active_page.url,
            "screenshot_path": (result.get("screenshot") or {}).get("file_path"),
        }

        history = list(state.get("steps_history", [])) + [step_record]

        # Collect any newly extracted text items
        extracted = list(state.get("extracted_data", []))
        if result["success"] and action == "extract_text":
            extracted.extend((result.get("data") or {}).get("extracted", []))

        # Persist progress to DB immediately so frontend polling sees live updates
        self._save_live_progress(state["run_id"], history, extracted)

        form_submission = bool(form_submission_candidate or (result.get("data") or {}).get("form_submission"))
        if form_submission and not (result["success"] and (result.get("data") or {}).get("submission_confirmed")):
            submission_data = result.get("data") or {}
            detail = submission_data.get("submission_error") or (
                "The site was still showing a sending state after the wait limit."
                if submission_data.get("submission_still_sending") else "Check the page for validation errors or a failed submit action."
            )
            message = f"The form submission was not confirmed. {detail} The agent stopped without refilling or resubmitting the form."
            return {
                "status": "failed",
                "step_count": step_num,
                "retry_count": state.get("max_retries_per_step", 2) + 1,
                "last_error": message,
                "steps_history": history,
                "extracted_data": extracted,
                "latest_screenshot": result.get("screenshot"),
            }

        # Return updated state fields
        if result["success"]:
            return {
                "step_count":      step_num,
                "retry_count":     0,       # Reset retry counter on success
                "last_error":      None,
                "steps_history":   history,
                "extracted_data":  extracted,
                "latest_screenshot": result.get("screenshot"),
                "login_approval_granted": False if login_submission else state.get("login_approval_granted", False),
            }

        # On failure – increment retry counter and pass the error forward
        return {
            "step_count":      step_num,
            "retry_count":     state.get("retry_count", 0) + 1,
            "last_error":      result.get("error", "Unknown execution error"),
            "steps_history":   history,
            "latest_screenshot": result.get("screenshot"),
            "login_approval_granted": state.get("login_approval_granted", False),
        }

    def _save_live_progress(self, run_id: str, history: list, extracted: list) -> None:
        """Writes the latest step list and extracted data to the DB in real time."""
        if self.db is None:
            return
        try:
            from app.database.models import ExecutionRun
            db_run = self.db.query(ExecutionRun).filter(ExecutionRun.id == run_id).first()
            if db_run:
                db_run.steps_log = history
                db_run.extracted_data = extracted
                db_run.status = "running"
                self.db.commit()
        except Exception:
            self.db.rollback()

    def _route_after_execute(self, state: AgentState) -> str:
        """
        Decide what to do after executing a step:
          - If it failed but retries remain → self_heal (take screenshot, then retry)
          - If it failed and retries exhausted → finalize (give up)
          - If step budget is reached → finalize
          - Otherwise → perceive (continue the loop)
        """
        if state.get("last_error"):
            if state.get("retry_count", 0) <= state.get("max_retries_per_step", 2):
                return "self_heal"
            return "finalize"

        if state["step_count"] >= state["max_steps"]:
            return "finalize"

        return "perceive"

    # ── Node 6: Self-heal ─────────────────────────────────────────────────────

    async def _node_self_heal(self, state: AgentState) -> Dict[str, Any]:
        """
        Called after a failed step. Takes a fresh screenshot so the planner can
        see the current page state and pick a recovery action.
        """
        print(f"[SELF-HEAL] Recovering from: {state.get('last_error')}", flush=True)

        screenshot = await self.actions.screenshots.capture(
            self.browser.active_page,
            state["run_id"],
            state["step_count"],
        )
        return {"latest_screenshot": screenshot}

    # ── Node 7: Finalize ──────────────────────────────────────────────────────

    async def _node_finalize(self, state: AgentState) -> Dict[str, Any]:
        """
        Wraps up the run:
          - If the task failed → return a failure summary
          - If it succeeded → save the run to vector memory for future RAG retrieval
        """
        # Determine whether the run succeeded or failed
        run_failed = (
            state.get("status") == "failed"
            or (
                state.get("last_error")
                and state.get("retry_count", 0) > state.get("max_retries_per_step", 2)
            )
        )

        if run_failed:
            return {
                "status": "failed",
                "final_summary": state.get("last_error") or "Task failed.",
            }

        prior_submission = next((
            step for step in reversed(state.get("steps_history", []))
            if step.get("form_submission")
        ), None)
        if prior_submission and prior_submission.get("success") and prior_submission.get("submission_confirmed"):
            return {
                "status": "completed",
                "final_summary": "The website confirmed that the form was submitted successfully.",
            }

        page_text = str(state.get("dom_snapshot", {}).get("visible_text_snippet", ""))
        if self._login_rejected(page_text):
            message = "The website rejected the login details. No generated output was produced; verify the saved credential and try again."
            return {"status": "failed", "last_error": message, "final_summary": message}
        if self._login_required(page_text):
            message = "The site still requires login, so the requested action did not complete. No generated output was produced."
            return {"status": "failed", "last_error": message, "final_summary": message}

        task_text = state.get("task", "").lower()
        if (
            "your generated text will appear here" in page_text.lower()
            and re.search(r"\b(generate|generation|generated output|text output)\b", task_text)
        ):
            message = "The generated output field is still empty. The task did not complete successfully."
            return {"status": "failed", "last_error": message, "final_summary": message}

        # Success – build the summary from the LLM's final_answer
        summary = (state.get("next_action") or {}).get("final_answer")
        if not summary or not str(summary).strip():
            message = "The agent stopped without producing a verified result. The task did not complete successfully."
            return {"status": "failed", "last_error": message, "final_summary": message}
        successful_steps = [s for s in state.get("steps_history", []) if s.get("success")]

        # Save the successful run to vector memory so future tasks can learn from it
        if self.memory and successful_steps:
            self.memory.save_successful_run(
                run_id=state["run_id"],
                user_id=state["user_id"],
                task=state["task"],
                steps=successful_steps,
            )

        return {"status": "completed", "final_summary": summary}
