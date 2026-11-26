"""
AutomationService – the main service layer that orchestrates agent runs.

Responsibilities:
  - Start a new browser automation task
  - Pause the agent when it hits the safety gate (human approval needed)
  - Resume the agent after the human approves or rejects
  - Persist results to the database
  - Export extracted data to JSON or CSV
"""

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
from app.security.approval_manager import approval_manager
from app.security.credential_vault import CredentialVault


class AutomationService:
    def __init__(self):
        # Keeps browser + orchestrator + state alive while waiting for human approval
        # Key: run_id, Value: {"browser", "orchestrator", "state", "timeout_seconds"}
        self._paused_sessions: Dict[str, Dict[str, Any]] = {}

        self.memory = WorkflowMemory()
        self.vault = CredentialVault()

    # ── Public API ────────────────────────────────────────────────────────────

    async def start_task(
        self,
        db: Session,
        user_id: str,
        task: str,
        max_steps: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Starts a new browser automation run.

        1. Creates (or reuses) a DB row for this run
        2. Launches a Playwright browser
        3. Builds the LangGraph orchestrator
        4. Runs the graph until it finishes or pauses for human approval
        """
        agent_cfg = agent_yaml_config.get("agent", {})
        effective_max_steps = max_steps or agent_cfg.get("max_steps", 15)
        effective_timeout   = timeout_seconds or agent_cfg.get("execution_timeout_seconds", 300)

        # Create or reuse the DB run record
        db_run = self._get_or_create_run(db, run_id, user_id, task)
        run_id = db_run.id

        # Launch the browser
        browser = BrowserManager()
        await browser.start()

        # Build the agent
        orchestrator = BrowserAgentOrchestrator(
            browser_manager=browser,
            vision_analyzer=None,   # Vision is optional; set to VisionAnalyzer() to enable
            workflow_memory=self.memory,
            vault=self.vault,
            db=db,
        )

        # Initial empty state
        initial_state: AgentState = {
            "run_id":                run_id,
            "user_id":               user_id,
            "task":                  task,
            "status":                "running",
            "step_count":            0,
            "max_steps":             effective_max_steps,
            "retry_count":           0,
            "max_retries_per_step":  2,
            "rag_context":           "",
            "available_credentials": [],
            "dom_snapshot":          {},
            "formatted_dom":         "",
            "latest_screenshot":     None,
            "next_action":           None,
            "approval_approved":     None,
            "pending_approval_reason": None,
            "login_approval_granted": False,
            "steps_history":         [],
            "extracted_data":        [],
            "final_summary":         "",
            "last_error":            None,
        }

        return await self._run_until_pause_or_end(
            db=db,
            run_id=run_id,
            browser=browser,
            orchestrator=orchestrator,
            state=initial_state,
            timeout_seconds=effective_timeout,
        )

    async def resume_after_approval(
        self,
        db: Session,
        user_id: str,
        run_id: str,
        approved: bool,
    ) -> Dict[str, Any]:
        """
        Called by the /approve endpoint after the human clicks Approve or Reject.

        Resumes the paused browser session with the user's decision.
        """
        # Pop the paused session so we can resume it
        paused = self._paused_sessions.pop(run_id, None)
        if not paused:
            raise KeyError(f"No paused session found for run '{run_id}'.")

        # Record the human's decision in the approval manager
        approval_manager.resolve(run_id, approved=approved)

        # Restore objects from the paused session
        browser:      BrowserManager           = paused["browser"]
        orchestrator: BrowserAgentOrchestrator = paused["orchestrator"]
        state:        AgentState               = paused["state"]
        timeout:      int                      = paused["timeout_seconds"]

        # Refresh the DB session reference so queries work in the new request context
        orchestrator.db = db
        orchestrator.executor.db = db

        # Inject the approval decision into state so the safety gate can read it
        state["approval_approved"] = approved

        # Publish the decision before the graph starts planning/executing again.
        # Otherwise polling clients keep seeing `awaiting_approval` until the
        # first browser action eventually writes progress.
        if approved:
            self._persist_run(
                db,
                run_id,
                "running",
                state.get("steps_history", []),
                state.get("extracted_data", []),
                final_summary="Approval received. Automation is continuing.",
            )

        return await self._run_until_pause_or_end(
            db=db,
            run_id=run_id,
            browser=browser,
            orchestrator=orchestrator,
            state=state,
            timeout_seconds=timeout,
        )

    async def cancel_paused_run(self, db: Session, run_id: str) -> None:
        """Closes a browser session that is paused while waiting for approval."""
        paused = self._paused_sessions.pop(run_id, None)
        if not paused:
            return
        await paused["browser"].close()
        state = paused["state"]
        approval_manager.discard(run_id)
        self._persist_run(
            db,
            run_id,
            "cancelled",
            state.get("steps_history", []),
            state.get("extracted_data", []),
            "Stopped by user.",
            final_summary="Run stopped by user.",
        )

    # ── Internal runner ───────────────────────────────────────────────────────

    async def _run_until_pause_or_end(
        self,
        db: Session,
        run_id: str,
        browser: BrowserManager,
        orchestrator: BrowserAgentOrchestrator,
        state: AgentState,
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        """
        Invokes the LangGraph workflow and handles all three outcomes:
          1. Awaiting approval → keep browser alive, return paused status to caller
          2. Completed / Failed → close browser, persist final state, return result
          3. Timeout / Exception → close browser, persist error, return failure result
        """
        try:
            final_state = await asyncio.wait_for(
                orchestrator.graph.ainvoke(state),
                timeout=timeout_seconds,
            )

        except asyncio.TimeoutError:
            await browser.close()
            error_msg = f"Execution timed out after {timeout_seconds} seconds."

            # Recover whatever progress was saved to DB during execution
            db_run = db.query(ExecutionRun).filter(ExecutionRun.id == run_id).first()
            saved_steps    = (db_run.steps_log       if db_run else None) or state.get("steps_history", [])
            saved_data     = (db_run.extracted_data  if db_run else None) or state.get("extracted_data", [])

            self._persist_run(db, run_id, "failed", saved_steps, saved_data, error_msg, final_summary=error_msg)
            return self._build_result(run_id, "failed", state["task"], error_msg, saved_data, saved_steps, error=error_msg)

        except asyncio.CancelledError:
            await browser.close()
            self._persist_run(
                db,
                run_id,
                "cancelled",
                state.get("steps_history", []),
                state.get("extracted_data", []),
                "Stopped by user.",
                final_summary="Run stopped by user.",
            )
            approval_manager.discard(run_id)
            raise

        except Exception as exc:
            await browser.close()
            error_msg = f"Unexpected error: {str(exc)}"
            self._persist_run(
                db, run_id, "failed",
                state.get("steps_history", []),
                state.get("extracted_data", []),
                str(exc), final_summary=error_msg,
            )
            return self._build_result(
                run_id, "failed", state["task"], error_msg,
                state.get("extracted_data", []),
                state.get("steps_history", []),
                error=str(exc),
            )

        status = final_state.get("status", "completed")

        # ── Paused: waiting for human approval ───────────────────────────────
        if status == "awaiting_approval":
            reason = final_state.get("pending_approval_reason", "Awaiting human approval.")

            # Keep everything alive so we can resume later
            self._paused_sessions[run_id] = {
                "browser":         browser,
                "orchestrator":    orchestrator,
                "state":           final_state,
                "timeout_seconds": timeout_seconds,
            }

            self._persist_run(
                db, run_id, "awaiting_approval",
                final_state.get("steps_history", []),
                final_state.get("extracted_data", []),
                final_summary=reason,
                pending_approval_reason=reason,
            )

            return {
                "run_id":          run_id,
                "status":          "awaiting_approval",
                "task":            state["task"],
                "final_summary":   reason,
                "extracted_data":  final_state.get("extracted_data", []),
                "steps_history":   final_state.get("steps_history", []),
                # Include the full pending approval details so the frontend can display them
                "pending_approval": approval_manager.get_pending(run_id),
            }

        # ── Finished (completed or failed) ────────────────────────────────────
        await browser.close()
        summary = final_state.get("final_summary", "")
        self._persist_run(
            db, run_id, status,
            final_state.get("steps_history", []),
            final_state.get("extracted_data", []),
            final_state.get("last_error"),
            final_summary=summary,
        )
        return self._build_result(
            run_id, status, state["task"], summary,
            final_state.get("extracted_data", []),
            final_state.get("steps_history", []),
            error=final_state.get("last_error"),
        )

    # ── Database helpers ──────────────────────────────────────────────────────

    def _get_or_create_run(self, db: Session, run_id: Optional[str], user_id: str, task: str) -> ExecutionRun:
        """Returns an existing DB run or creates a new one."""
        if run_id:
            existing = db.query(ExecutionRun).filter(ExecutionRun.id == run_id).first()
            if existing:
                return existing

        new_id = run_id or str(uuid.uuid4())[:12]
        run = ExecutionRun(id=new_id, user_id=user_id, task=task, status="running")
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    def _persist_run(
        self,
        db: Session,
        run_id: str,
        status: str,
        steps_log: List[Dict[str, Any]],
        extracted_data: List[Any],
        error_msg: Optional[str] = None,
        final_summary: Optional[str] = None,
        pending_approval_reason: Optional[str] = None,
    ) -> None:
        """Updates the DB record with the latest run state."""
        record = db.query(ExecutionRun).filter(ExecutionRun.id == run_id).first()
        if not record:
            return

        record.status         = status
        record.steps_log      = steps_log
        record.extracted_data = extracted_data
        record.error_message  = error_msg

        if final_summary is not None:
            record.final_summary = final_summary

        if pending_approval_reason is not None and hasattr(record, "pending_approval_reason"):
            record.pending_approval_reason = pending_approval_reason

        db.commit()

    @staticmethod
    def _build_result(
        run_id: str,
        status: str,
        task: str,
        final_summary: str,
        extracted_data: list,
        steps_history: list,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Builds the standard API response dict returned from every run outcome."""
        return {
            "run_id":        run_id,
            "status":        status,
            "task":          task,
            "final_summary": final_summary,
            "extracted_data":extracted_data,
            "steps_history": steps_history,
            "error":         error,
        }

    # ── Export ────────────────────────────────────────────────────────────────

    @staticmethod
    def export_data(extracted_data: List[Any], fmt: str = "json") -> str:
        """
        Converts extracted data to a downloadable string.
        fmt="json"  → pretty-printed JSON
        fmt="csv"   → index + value rows
        """
        if fmt.lower() == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["index", "extracted_value"])
            for idx, item in enumerate(extracted_data, start=1):
                value = json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item)
                writer.writerow([idx, value])
            return output.getvalue()

        return json.dumps(extracted_data, indent=2, ensure_ascii=False)


# Single shared instance used by the FastAPI routes
automation_service = AutomationService()
