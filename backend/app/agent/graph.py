from typing import Any, Dict, Optional
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


def _get_langfuse_callbacks(run_id: str, user_id: str) -> list:
    if not (settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY):
        return []
    try:
        from langfuse.callback import CallbackHandler

        handler = CallbackHandler(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
            session_id=run_id,
            user_id=user_id,
        )
        return [handler]
    except Exception:
        return []


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
        self.vision = vision_analyzer
        self.memory = workflow_memory
        self.vault = vault
        self.db = db
        self.executor = StepExecutor(self.actions, vault=vault, db=db)

        self.default_max_steps = agent_yaml_config.get("agent", {}).get("max_steps", 15)
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(AgentState)

        workflow.add_node("retrieve_memory", self._node_retrieve_memory)
        workflow.add_node("perceive", self._node_perceive)
        workflow.add_node("plan", self._node_plan)
        workflow.add_node("safety_gate", self._node_safety_gate)
        workflow.add_node("execute", self._node_execute)
        workflow.add_node("self_heal", self._node_self_heal)
        workflow.add_node("finalize", self._node_finalize)

        workflow.set_entry_point("retrieve_memory")
        workflow.add_edge("retrieve_memory", "perceive")
        workflow.add_edge("perceive", "plan")

        workflow.add_conditional_edges(
            "plan",
            self._route_after_plan,
            {
                "finish": "finalize",
                "safety_gate": "safety_gate",
            },
        )

        workflow.add_conditional_edges(
            "safety_gate",
            self._route_after_safety,
            {
                "execute": "execute",
                "pause": END,
            },
        )

        workflow.add_conditional_edges(
            "execute",
            self._route_after_execute,
            {
                "perceive": "perceive",
                "self_heal": "self_heal",
                "finalize": "finalize",
            },
        )

        workflow.add_edge("self_heal", "perceive")
        workflow.add_edge("finalize", END)

        return workflow.compile()

    async def _node_retrieve_memory(self, state: AgentState) -> Dict[str, Any]:
        rag_text = "No prior similar workflows found in memory."
        if self.memory:
            matches = self.memory.retrieve_relevant_workflows(
                task=state["task"], user_id=state["user_id"], top_k=3
            )
            rag_text = self.memory.format_for_planner_prompt(matches)

        creds = []
        if self.vault and self.db:
            creds = self.vault.list_credentials_for_prompt(self.db, state["user_id"])

        return {"rag_context": rag_text, "available_credentials": creds}

    async def _node_perceive(self, state: AgentState) -> Dict[str, Any]:
        page = self.browser.active_page
        snapshot = await self.dom.inspect(page)
        formatted = self.dom.format_for_prompt(snapshot)
        return {"dom_snapshot": snapshot, "formatted_dom": formatted}

    async def _node_plan(self, state: AgentState) -> Dict[str, Any]:
        if state["step_count"] >= state["max_steps"]:
            return {
                "status": "failed",
                "last_error": f"Maximum step limit ({state['max_steps']}) reached.",
                "next_action": {"action": "finish", "final_answer": "Stopped: maximum step limit reached."},
            }

        callbacks = _get_langfuse_callbacks(state["run_id"], state["user_id"])
        decision = await self.planner.decide_next_action(state, callbacks=callbacks)
        return {"next_action": decision}

    def _route_after_plan(self, state: AgentState) -> str:
        decision = state.get("next_action") or {}
        if decision.get("action") == "finish" or state.get("status") == "failed":
            return "finish"
        return "safety_gate"

    async def _node_safety_gate(self, state: AgentState) -> Dict[str, Any]:
        decision = state["next_action"] or {}
        action = decision.get("action", "")
        params = decision.get("params", {})
        is_sensitive = bool(decision.get("is_sensitive", False))

        # Check if human approval was already granted for this paused step
        if state.get("approval_approved") is True:
            return {"approval_approved": None, "status": "running"}
        if state.get("approval_approved") is False:
            return {"status": "rejected", "final_summary": "Execution rejected by user at safety gate."}

        if approval_manager.requires_approval(action, params, is_sensitive=is_sensitive):
            reason = f"Action '{action}' requires human approval before execution."
            approval_manager.request_approval(
                run_id=state["run_id"],
                step_number=state["step_count"] + 1,
                proposed_action={"action": action, "params": params, "thought": decision.get("thought", "")},
                reason=reason,
            )
            return {
                "status": "awaiting_approval",
                "pending_approval_reason": reason,
            }

        return {"status": "running"}

    def _route_after_safety(self, state: AgentState) -> str:
        if state.get("status") in ("awaiting_approval", "rejected"):
            return "pause"
        return "execute"

    async def _node_execute(self, state: AgentState) -> Dict[str, Any]:
        decision = state["next_action"] or {}
        action = decision.get("action", "")
        params = decision.get("params", {})
        step_num = state["step_count"] + 1

        res = await self.executor.run_step(
            user_id=state["user_id"],
            run_id=state["run_id"],
            step_number=step_num,
            action=action,
            params=params,
        )

        history = list(state.get("steps_history", []))
        extracted = list(state.get("extracted_data", []))

        step_record = {
            "step": step_num,
            "thought": decision.get("thought", ""),
            "action": action,
            "params": res.get("logged_params", params),
            "success": res["success"],
            "data": res.get("data"),
            "error": res.get("error"),
            "url": self.browser.active_page.url,
            "screenshot_path": (res.get("screenshot") or {}).get("file_path"),
        }
        history.append(step_record)

        if res["success"]:
            if action == "extract_text" and res.get("data"):
                extracted.extend(res["data"].get("extracted", []))
            return {
                "step_count": step_num,
                "retry_count": 0,
                "last_error": None,
                "steps_history": history,
                "extracted_data": extracted,
                "latest_screenshot": res.get("screenshot"),
            }

        return {
            "step_count": step_num,
            "retry_count": state.get("retry_count", 0) + 1,
            "last_error": res.get("error", "Unknown execution error"),
            "steps_history": history,
            "latest_screenshot": res.get("screenshot"),
        }

    def _route_after_execute(self, state: AgentState) -> str:
        if state.get("last_error"):
            if state.get("retry_count", 0) <= state.get("max_retries_per_step", 2):
                return "self_heal"
            return "finalize"
        if state["step_count"] >= state["max_steps"]:
            return "finalize"
        return "perceive"

    async def _node_self_heal(self, state: AgentState) -> Dict[str, Any]:
        """Captures fresh screenshot and invokes VisionAnalyzer to diagnose selector/popup failures."""
        shot = await self.actions.screenshots.capture(
            self.browser.active_page, state["run_id"], state["step_count"]
        )
        error_msg = state.get("last_error", "")

        if self.vision and shot.get("base64"):
            try:
                obs = await self.vision.analyze_screenshot(
                    base64_image=shot["base64"],
                    user_goal=state["task"],
                    context_note=f"Previous step failed: {error_msg}",
                )
                hint = obs.get("suggested_recovery_hint", "")
                summary = obs.get("page_summary", "")
                enriched_error = f"{error_msg} | Visual Diagnosis: {summary}. Recovery Hint: {hint}"
                return {"last_error": enriched_error, "latest_screenshot": shot}
            except Exception:
                pass

        return {"latest_screenshot": shot}

    async def _node_finalize(self, state: AgentState) -> Dict[str, Any]:
        decision = state.get("next_action") or {}
        if state.get("status") == "failed" or (
            state.get("last_error") and state.get("retry_count", 0) > state.get("max_retries_per_step", 2)
        ):
            return {
                "status": "failed",
                "final_summary": state.get("last_error") or "Task failed.",
            }

        summary = decision.get("final_answer") or "Task completed successfully."
        successful_steps = [s for s in state.get("steps_history", []) if s.get("success")]

        if self.memory and successful_steps:
            self.memory.save_successful_run(
                run_id=state["run_id"],
                user_id=state["user_id"],
                task=state["task"],
                steps=successful_steps,
            )

        return {
            "status": "completed",
            "final_summary": summary,
        }