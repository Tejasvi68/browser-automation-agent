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
        # Copy params so raw secrets never mutate the logged state
        execution_params = copy.deepcopy(params)
        logged_params = copy.deepcopy(params)

        if action == "type" and "text" in execution_params:
            raw_text = str(execution_params["text"])
            if "{{VAULT:" in raw_text:
                if not self.vault or not self.db:
                    return {
                        "success": False,
                        "action": action,
                        "error": "Credential vault unavailable to resolve secret placeholder.",
                    }
                execution_params["text"] = self.vault.resolve_text(self.db, user_id, raw_text)
                logged_params["text"] = CredentialVault.mask_sensitive_text(raw_text)

        result = await self.browser_actions.execute(
            action=action,
            params=execution_params,
            run_id=run_id,
            step_number=step_number,
        )
        result["logged_params"] = logged_params
        return result