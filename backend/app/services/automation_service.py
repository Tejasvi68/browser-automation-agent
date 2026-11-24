import asyncio
import csv
import io
import json
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.agent.graph import BrowserAgentOrchestrator
from app.agent.state import AgentState
from app.browser.browser_manager import BrowserManager
from app.config import agent_yaml_config
from app.database.models import ExecutionRun
from app.memory.workflow_memory import WorkflowMemory
from app.perception.vision_analyzer import VisionAnalyzer
from app.security.approval_manager import approval_manager
from app.security.credential_vault import CredentialVault


class AutomationService:
    def __init__(self):
        # Holds paused browser + state sessions awaiting human approval
        self._paused_sessions: Dict[str, Dict[str, Any]] = {}
        self.memory = WorkflowMemory()
        self.vault = CredentialVault()

    async def start_task(
        self,
        db: Session,
        user_id: str,
        task: str,
        max_steps: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        run_id = str(uuid.uuid4())[:12]
        agent_cfg = agent_yaml_config.get("agent", {})
        effective_max_steps = max_steps or agent_cfg.get("max_steps", 15)
        effective_timeout = timeout_seconds or agent_cfg.get("execution_timeout_seconds", 300)

        db_run = ExecutionRun(id=run_id, user_id=user_id, task=task, status="running")
        db.add(db_run)
        db.commit()

        browser = BrowserManager()
        await browser.start()

        vision = VisionAnalyzer()
        orchestrator = BrowserAgentOrchestrator(
            browser_manager=browser,
            vision_analyzer=vision,
            workflow_memory=self.memory,
            vault=self.vault,
            db=db,
        )

        initial_state: AgentState = {
            "run_id": run_id,
            "user_id": user_id,
            "task": task,
            "status": "running",
            "step_count": 0,
            "max_steps": effective_max_steps,
            "retry_count": 0,
            "max_retries_per_step": 2,
            "rag_context": "",
            "available_credentials": [],
            "dom_snapshot": {},
            "formatted_dom": "",
            "latest_screenshot": None,
            "next_action": None,
            "approval_approved": None,
            "pending_approval_reason": None,
            "steps_history": [],
            "extracted_data": [],
            "final_summary": "",
            "last_error": None,
        }

        return await self._execute_until_pause_or_end(
            db=db,
            run_id=run_id,
            browser=browser,
            orchestrator=orchestrator,
            state=initial_state,
            timeout_seconds=effective_timeout,
        )

    async def resume_after_approval(self, db: Session, user_id: str, run_id: str, approved: bool) -> Dict[str, Any]:
        session_bundle = self._paused_sessions.pop(run_id, None)
        if not session_bundle:
            raise KeyError(f"No active paused session found for run '{run_id}'.")

        approval_manager.resolve(run_id, approved=approved)
        browser: BrowserManager = session_bundle["browser"]
        orchestrator: BrowserAgentOrchestrator = session_bundle["orchestrator"]
        state: AgentState = session_bundle["state"]
        timeout_seconds: int = session_bundle["timeout_seconds"]

        # Refresh DB session reference for credential resolution
        orchestrator.db = db
        orchestrator.executor.db = db
        state["approval_approved"] = approved

        return await self._execute_until_pause_or_end(
            db=db,
            run_id=run_id,
            browser=browser,
            orchestrator=orchestrator,
            state=state,
            timeout_seconds=timeout_seconds,
        )

    async def _execute_until_pause_or_end(
        self,
        db: Session,
        run_id: str,
        browser: BrowserManager,
        orchestrator: BrowserAgentOrchestrator,
        state: AgentState,
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        try:
            final_state = await asyncio.wait_for(orchestrator.graph.ainvoke(state), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            await browser.close()
            self._persist_run(db, run_id, "failed", [], [], f"Execution timed out after {timeout_seconds}s.")
            return {
                "run_id": run_id,
                "status": "failed",
                "task": state["task"],
                "final_summary": f"Execution timed out after {timeout_seconds} seconds.",
                "extracted_data": state.get("extracted_data", []),
                "steps_history": state.get("steps_history", []),
                "error": "TimeoutError",
            }
        except Exception as e:
            await browser.close()
            self._persist_run(db, run_id, "failed", state.get("steps_history", []), [], str(e))
            return {
                "run_id": run_id,
                "status": "failed",
                "task": state["task"],
                "final_summary": f"Execution error: {str(e)}",
                "extracted_data": state.get("extracted_data", []),
                "steps_history": state.get("steps_history", []),
                "error": str(e),
            }

        status = final_state.get("status", "completed")
        if status == "awaiting_approval":
            # Keep browser open so user can approve and continue seamlessly
            self._paused_sessions[run_id] = {
                "browser": browser,
                "orchestrator": orchestrator,
                "state": final_state,
                "timeout_seconds": timeout_seconds,
            }
            self._persist_run(
                db,
                run_id,
                "awaiting_approval",
                final_state.get("steps_history", []),
                final_state.get("extracted_data", []),
            )
            return {
                "run_id": run_id,
                "status": "awaiting_approval",
                "task": state["task"],
                "final_summary": final_state.get("pending_approval_reason", "Awaiting human approval."),
                "extracted_data": final_state.get("extracted_data", []),
                "steps_history": final_state.get("steps_history", []),
                "pending_approval": approval_manager.get_pending(run_id),
            }

        await browser.close()
        self._persist_run(
            db,
            run_id,
            status,
            final_state.get("steps_history", []),
            final_state.get("extracted_data", []),
            final_state.get("last_error"),
        )
        return {
            "run_id": run_id,
            "status": status,
            "task": state["task"],
            "final_summary": final_state.get("final_summary", ""),
            "extracted_data": final_state.get("extracted_data", []),
            "steps_history": final_state.get("steps_history", []),
            "error": final_state.get("last_error"),
        }

    def _persist_run(
        self,
        db: Session,
        run_id: str,
        status: str,
        steps_log: List[Dict[str, Any]],
        extracted_data: List[Any],
        error_msg: Optional[str] = None,
    ) -> None:
        record = db.query(ExecutionRun).filter(ExecutionRun.id == run_id).first()
        if record:
            record.status = status
            record.steps_log = steps_log
            record.extracted_data = extracted_data
            record.error_message = error_msg
            db.commit()

    @staticmethod
    def export_data(extracted_data: List[Any], fmt: str = "json") -> str:
        """Exports extracted items to formatted JSON or CSV string."""
        if fmt.lower() == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["index", "extracted_value"])
            for idx, item in enumerate(extracted_data, start=1):
                val = json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item)
                writer.writerow([idx, val])
            return output.getvalue()

        return json.dumps(extracted_data, indent=2, ensure_ascii=False)


automation_service = AutomationService()