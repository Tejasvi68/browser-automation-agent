from typing import Any, Dict, Optional
from app.config import agent_yaml_config


class ApprovalManager:
    def __init__(self):
        self.restricted_actions = set(
            agent_yaml_config.get("safety", {}).get(
                "require_approval_actions",
                ["submit_form", "login", "payment", "delete"],
            )
        )
        # In-memory store of active approval decisions keyed by run_id
        self._pending: Dict[str, Dict[str, Any]] = {}

    def requires_approval(self, action: str, params: Dict[str, Any], is_sensitive: bool = False) -> bool:
        """Determines if an action must stop for human approval before execution."""
        if is_sensitive or action in self.restricted_actions:
            return True

        # Typing into password fields or using vault credentials always requires approval
        selector = str(params.get("selector", "")).lower()
        text = str(params.get("text", ""))
        if "password" in selector or "{{VAULT:" in text:
            return True

        # Clicking submit/pay/delete buttons requires approval
        if action == "click" and any(
            kw in selector for kw in ("submit", "pay", "checkout", "purchase", "delete", "login", "sign-in")
        ):
            return True

        return False

    def request_approval(self, run_id: str, step_number: int, proposed_action: Dict[str, Any], reason: str) -> Dict[str, Any]:
        entry = {
            "run_id": run_id,
            "step": step_number,
            "proposed_action": proposed_action,
            "reason": reason,
            "status": "pending",  # pending | approved | rejected
        }
        self._pending[run_id] = entry
        return entry

    def get_pending(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self._pending.get(run_id)

    def resolve(self, run_id: str, approved: bool) -> Dict[str, Any]:
        if run_id not in self._pending:
            raise KeyError(f"No pending approval found for run '{run_id}'.")
        self._pending[run_id]["status"] = "approved" if approved else "rejected"
        return self._pending[run_id]


approval_manager = ApprovalManager()