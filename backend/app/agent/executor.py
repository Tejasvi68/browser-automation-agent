import copy
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.browser.browser_actions import BrowserActions
from app.security.credential_vault import CredentialVault


class StepExecutor:
    def __init__(
        self,
        browser_actions: BrowserActions,
        vault: Optional[CredentialVault] = None,
        db: Optional[Session] = None,
    ):
        self.browser_actions = browser_actions
        self.vault = vault
        self.db = db

    async def run_step(
        self,
        user_id: str,
        run_id: str,
        step_number: int,
        action: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Runs one browser action and returns the result dict.

        Deep-copies params so the original state is never mutated.
        If the action is 'type' and the text contains a {{VAULT:label}} token,
        the token is resolved to the real password for execution but kept masked
        in the logged copy so secrets never appear in the database.
        """
        # Two independent copies: one to execute, one to log
        execution_params = copy.deepcopy(params)
        logged_params = copy.deepcopy(params)

        # Resolve vault credentials if needed
        if action == "type" and (
            "{{VAULT:" in str(execution_params.get("text", ""))
            or "{{VAULT_FIELD:" in str(execution_params.get("text", ""))
        ):
            raw_text = str(execution_params["text"])

            if not self.vault or not self.db:
                return {
                    "success": False,
                    "action": action,
                    "error": "Credential vault is not available to resolve the secret.",
                }

            # Replace the token with the real password (only for browser execution)
            execution_params["text"] = self.vault.resolve_text(self.db, user_id, raw_text)

            # Keep the token masked in what we store in the DB
            logged_params["text"] = CredentialVault.mask_sensitive_text(raw_text)

        # Run the actual browser action
        result = await self.browser_actions.execute(
            action=action,
            params=execution_params,
            run_id=run_id,
            step_number=step_number,
        )

        # Attach the safe (masked) params so the graph can store them in history
        result["logged_params"] = logged_params

        return result
