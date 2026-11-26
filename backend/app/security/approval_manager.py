"""
ApprovalManager – tracks which runs are waiting for a human decision.

The safety gate in the LangGraph workflow calls this module when it encounters
a sensitive action (e.g. login, payment, form submit). The agent pauses, the
frontend polls the run status and shows an Approve / Reject button, and the
/approve API endpoint calls resolve() to record the human's decision.

All state is kept in memory (a plain dict). A production deployment would
persist this in Redis or the database to survive server restarts.
"""

from typing import Any, Dict, Optional

from app.config import agent_yaml_config


class ApprovalManager:
    def __init__(self):
        # Actions that always require human approval (loaded from agent_config.yaml)
        self.restricted_actions: set = set(
            agent_yaml_config.get("safety", {}).get(
                "require_approval_actions",
                ["submit_form", "login", "payment", "delete"],
            )
        )

        # In-memory store: { run_id → approval_entry }
        self._pending: Dict[str, Dict[str, Any]] = {}

    # ── Decision logic ────────────────────────────────────────────────────────

    def requires_approval(
        self,
        action: str,
        params: Dict[str, Any],
        is_sensitive: bool = False,
        element: Optional[Dict[str, Any]] = None,
        dom_snapshot: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Returns True if the action must pause and wait for a human before running.

        Triggers approval when any of the following are true:
          1. The LLM flagged the action as sensitive (is_sensitive=True)
          2. The action name is in the restricted set (from config)
          3. The action types into a password field
          4. The action uses a vault credential ({{VAULT:...}} token)
          5. The action clicks a submit/pay/delete/login button
          6. The action submits a visible credential form with Enter
        """
        # LLM explicitly flagged it, or action is in the restricted list
        if is_sensitive or action in self.restricted_actions:
            return True

        element = element or {}
        selector = str(params.get("selector", "")).lower()
        text = " ".join(str(value or "") for value in (
            params.get("text"), params.get("target_label"), element.get("text"),
            element.get("aria_label"), element.get("placeholder"), element.get("url"),
        )).lower()
        field_type = str(element.get("type", "")).lower()
        field_label = " ".join((selector, text, field_type)).lower()

        if self.is_login_related(action, params, element, dom_snapshot):
            return True

        # Form submissions always require approval, even when the model did not
        # mark the click as sensitive. Also catch custom JavaScript submit
        # buttons whose HTML type is "button" but whose label is explicit.
        dangerous_button_keywords = (
            "submit", "send", "pay", "checkout", "purchase", "delete",
            "login", "log in", "log-in", "sign in", "sign-in", "signin",
        )
        if action == "click" and (
            field_type == "submit"
            or bool(element.get("is_submit"))
            or (bool(element.get("in_form")) and any(kw in field_label for kw in dangerous_button_keywords))
            or any(kw in field_label for kw in dangerous_button_keywords)
        ):
            return True

        # Enter can submit a regular form even when there is no explicit click.
        form_has_submit = any(
            bool(item.get("is_submit"))
            for item in (dom_snapshot or {}).get("interactive_elements", [])
        )
        if action == "press_key" and str(params.get("key", "")).lower() in ("enter", "return") and form_has_submit:
            return True
        if action == "type" and params.get("press_enter") and form_has_submit:
            return True

        return False

    @staticmethod
    def is_login_related(
        action: str,
        params: Dict[str, Any],
        element: Optional[Dict[str, Any]] = None,
        dom_snapshot: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Identifies controls that belong to a login form, including element IDs."""
        element = element or {}
        page_elements = (dom_snapshot or {}).get("interactive_elements", [])
        page_has_password = any(str(item.get("type", "")).lower() == "password" for item in page_elements)
        field_type = str(element.get("type", "")).lower()
        field_label = " ".join(str(value or "") for value in (
            params.get("selector"), params.get("text"), params.get("target_label"),
            params.get("key"), element.get("text"), element.get("aria_label"),
            element.get("placeholder"), element.get("url"), field_type,
        )).lower()

        if "{{vault:" in field_label:
            return True
        if action == "type" and (field_type == "password" or "password" in field_label):
            return True
        if action == "type" and page_has_password and any(
            word in field_label for word in ("email", "username", "user name", "user")
        ):
            return True
        if action == "press_key" and str(params.get("key", "")).lower() in ("enter", "return") and page_has_password:
            return True
        if action == "click":
            login_words = ("login", "log in", "log-in", "sign in", "sign-in", "signin", "authenticate")
            if any(word in field_label for word in login_words):
                return True
            if page_has_password and field_type == "submit":
                return True
        return False

    @classmethod
    def is_login_submission(
        cls,
        action: str,
        params: Dict[str, Any],
        element: Optional[Dict[str, Any]] = None,
        dom_snapshot: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Returns True for the action that submits the login form."""
        element = element or {}
        page_has_password = any(
            str(item.get("type", "")).lower() == "password"
            for item in (dom_snapshot or {}).get("interactive_elements", [])
        )
        label = " ".join(str(value or "") for value in (
            params.get("selector"), params.get("target_label"), element.get("text"), element.get("aria_label"),
        )).lower()
        if action == "press_key" and str(params.get("key", "")).lower() in ("enter", "return") and page_has_password:
            return True
        if action == "type" and params.get("press_enter") and page_has_password:
            return True
        if action == "click" and page_has_password and (
            str(element.get("type", "")).lower() == "submit"
            or "submit" in str(params.get("selector", "")).lower()
            or any(word in label for word in ("login", "log in", "sign in", "signin", "submit"))
        ):
            return True
        return False

    # ── Approval lifecycle ────────────────────────────────────────────────────

    def request_approval(
        self,
        run_id: str,
        step_number: int,
        proposed_action: Dict[str, Any],
        reason: str,
    ) -> Dict[str, Any]:
        """
        Registers a pending approval request.
        The frontend can read this via GET /runs/{run_id} (pending_approval field).
        """
        entry = {
            "run_id":          run_id,
            "step":            step_number,
            "proposed_action": proposed_action,
            "reason":          reason,
            "status":          "pending",   # pending → approved | rejected
        }
        self._pending[run_id] = entry
        return entry

    def get_pending(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Returns the current pending approval entry for a run, or None."""
        return self._pending.get(run_id)

    def discard(self, run_id: str) -> None:
        """Removes pending approval state when a run is stopped."""
        self._pending.pop(run_id, None)

    def resolve(self, run_id: str, approved: bool) -> Dict[str, Any]:
        """
        Records the human's decision (approved=True/False).
        Called by the POST /runs/{run_id}/approve endpoint.
        Raises KeyError if no pending entry exists for the run.
        """
        if run_id not in self._pending:
            raise KeyError(f"No pending approval found for run '{run_id}'.")

        self._pending[run_id]["status"] = "approved" if approved else "rejected"
        return self._pending[run_id]


# Single shared instance used across the application
approval_manager = ApprovalManager()
