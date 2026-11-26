"""
Automation & Security API routes.

Endpoints:
  POST   /run                        – Start a new browser automation task
  GET    /runs                        – List the last 30 runs for the current user
  GET    /runs/{run_id}              – Get a single run (used for live polling)
  POST   /runs/{run_id}/approve      – Approve or reject a paused (sensitive) action
  GET    /runs/{run_id}/export       – Download extracted data as JSON or CSV
  POST   /vault/credentials          – Save an encrypted credential
  GET    /vault/credentials          – List saved credentials (labels only, no passwords)
  POST   /transcribe                 – Transcribe a voice recording to text (Groq Whisper)
"""

import asyncio
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from groq import AsyncGroq
from sqlalchemy.orm import Session

from app.config import settings
from app.core.firebase import get_current_user
from app.database.database import SessionLocal, get_db
from app.database.models import ExecutionRun, UserCredential
from app.schemas.automation import (
    ApprovalDecisionRequest,
    CredentialCreateRequest,
    CredentialUpdateRequest,
    RunResponse,
    RunTaskRequest,
)
from app.security.approval_manager import approval_manager
from app.services.automation_service import automation_service

router = APIRouter(tags=["Automation & Security"])
_active_run_tasks: Dict[str, asyncio.Task] = {}


def _track_run_task(run_id: str, coroutine) -> asyncio.Task:
    task = asyncio.create_task(coroutine)
    _active_run_tasks[run_id] = task
    task.add_done_callback(lambda done: _active_run_tasks.pop(run_id, None) if _active_run_tasks.get(run_id) is done else None)
    return task


# ── Helpers ───────────────────────────────────────────────────────────────────

def _serialize_run(run: ExecutionRun) -> Dict[str, Any]:
    """Converts an ExecutionRun DB row to the standard API response dict."""
    return {
        "run_id":                  run.id,
        "task":                    run.task,
        "status":                  run.status,
        "steps_history":           run.steps_log or [],
        "extracted_data":          run.extracted_data or [],
        "final_summary":           getattr(run, "final_summary", None) or getattr(run, "summary", None),
        "pending_approval_reason": getattr(run, "pending_approval_reason", None),
        "pending_approval":          approval_manager.get_pending(run.id),
        "error":                   run.error_message,
        "created_at":              run.created_at.isoformat() if run.created_at else None,
    }


async def _run_in_background(run_id: str, user_id: str, task: str, max_steps: int, timeout_seconds: int):
    """
    Background coroutine that runs the agent task.

    Uses its own DB session because FastAPI's request-scoped session closes
    when the POST /run response is returned to the client.
    """
    bg_db = SessionLocal()
    try:
        await automation_service.start_task(
            db=bg_db,
            user_id=user_id,
            task=task,
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
            run_id=run_id,
        )
    except Exception as exc:
        # Mark the run as failed if the background task crashes unexpectedly
        try:
            failed_run = bg_db.query(ExecutionRun).filter(ExecutionRun.id == run_id).first()
            if failed_run and failed_run.status == "running":
                failed_run.status = "failed"
                failed_run.error_message = str(exc)
                bg_db.commit()
        except Exception:
            bg_db.rollback()
    except asyncio.CancelledError:
        try:
            cancelled_run = bg_db.query(ExecutionRun).filter(ExecutionRun.id == run_id).first()
            if cancelled_run and cancelled_run.status in {"running", "awaiting_approval"}:
                cancelled_run.status = "cancelled"
                cancelled_run.error_message = "Stopped by user."
                cancelled_run.final_summary = "Run stopped by user."
                bg_db.commit()
        except Exception:
            bg_db.rollback()
        raise
    finally:
        bg_db.close()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/run")
async def run_automation_task(
    payload: RunTaskRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Creates a new run record immediately (so the frontend can start polling),
    then kicks off the agent in the background without blocking the HTTP response.
    """
    run_id = str(uuid.uuid4())

    # Create the DB record right away so GET /runs/{run_id} works immediately
    new_run = ExecutionRun(
        id=run_id,
        user_id=user["uid"],
        task=payload.task,
        status="running",
        steps_log=[],
        extracted_data=[],
    )
    db.add(new_run)
    db.commit()
    db.refresh(new_run)

    # Fire-and-forget: the agent runs in the background
    _track_run_task(
        run_id,
        _run_in_background(
            run_id=run_id,
            user_id=user["uid"],
            task=payload.task,
            max_steps=payload.max_steps,
            timeout_seconds=payload.timeout_seconds,
        )
    )

    return _serialize_run(new_run)


@router.get("/runs/{run_id}")
async def get_single_run(
    run_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns the current state of one run.
    The frontend polls this endpoint every few seconds to show live progress.
    """
    run = (
        db.query(ExecutionRun)
        .filter(ExecutionRun.id == run_id, ExecutionRun.user_id == user["uid"])
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Execution run not found.")
    return _serialize_run(run)


@router.post("/runs/{run_id}/approve", response_model=RunResponse)
async def approve_or_reject_step(
    run_id: str,
    payload: ApprovalDecisionRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Human approval endpoint.

    When the agent pauses at the safety gate, the frontend shows the proposed
    action and two buttons: Approve and Reject. Clicking either calls this endpoint.

    payload.approved = True  → agent resumes and executes the action
    payload.approved = False → agent stops and marks the run as rejected
    """
    try:
        task = _track_run_task(
            run_id,
            automation_service.resume_after_approval(
                db=db,
                user_id=user["uid"],
                run_id=run_id,
                approved=payload.approved,
            ),
        )
        return await task
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/runs/{run_id}/stop")
async def stop_execution_run(
    run_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.query(ExecutionRun).filter(
        ExecutionRun.id == run_id,
        ExecutionRun.user_id == user["uid"],
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Execution run not found.")
    if run.status not in {"running", "awaiting_approval"}:
        raise HTTPException(status_code=409, detail="This run is no longer active.")

    task = _active_run_tasks.get(run_id)
    if task and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    else:
        await automation_service.cancel_paused_run(db, run_id)

    db.expire_all()
    run = db.query(ExecutionRun).filter(ExecutionRun.id == run_id).first()
    if run and run.status in {"running", "awaiting_approval"}:
        run.status = "cancelled"
        run.error_message = "Stopped by user."
        run.final_summary = "Run stopped by user."
        db.commit()
        db.refresh(run)
    return _serialize_run(run)


@router.get("/runs", response_model=List[Dict[str, Any]])
async def list_execution_history(
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Returns the 30 most recent runs for the current user, newest first."""
    runs = (
        db.query(ExecutionRun)
        .filter(ExecutionRun.user_id == user["uid"])
        .order_by(ExecutionRun.created_at.desc())
        .limit(30)
        .all()
    )
    return [_serialize_run(r) for r in runs]


@router.delete("/runs/{run_id}")
async def delete_execution_run(
    run_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deletes one run from the current user's execution history."""
    run = (
        db.query(ExecutionRun)
        .filter(ExecutionRun.id == run_id, ExecutionRun.user_id == user["uid"])
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Execution run not found.")
    if run.status in {"running", "awaiting_approval"}:
        raise HTTPException(status_code=409, detail="Active runs cannot be deleted.")

    db.delete(run)
    db.commit()
    return {"deleted": True, "run_id": run_id}


@router.get("/runs/{run_id}/export")
async def export_run_results(
    run_id: str,
    format: str = "json",
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Downloads the extracted data for a completed run as JSON or CSV."""
    run = (
        db.query(ExecutionRun)
        .filter(ExecutionRun.id == run_id, ExecutionRun.user_id == user["uid"])
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Execution run not found.")

    content    = automation_service.export_data(run.extracted_data or [], fmt=format)
    media_type = "text/csv" if format.lower() == "csv" else "application/json"
    filename   = f"run_{run_id}.{format.lower()}"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Vault endpoints ───────────────────────────────────────────────────────────

@router.post("/vault/credentials")
async def save_vault_credential(
    payload: CredentialCreateRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Encrypts and stores a credential so the agent can use it without seeing the raw password."""
    try:
        cred = automation_service.vault.store_credential(
            db=db,
            user_id=user["uid"],
            label=payload.label,
            domain=payload.domain,
            username=payload.username,
            password=payload.password,
            fields=payload.fields,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": cred.id, "label": cred.label, "domain": cred.domain, "username": cred.username}


@router.get("/vault/credentials")
async def list_vault_credentials(
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Returns profile metadata and field names, never field or password values."""
    return automation_service.vault.list_credentials(db=db, user_id=user["uid"])


def _get_owned_credential(db: Session, credential_id: int, user_id: str) -> UserCredential:
    credential = db.query(UserCredential).filter(
        UserCredential.id == credential_id,
        UserCredential.user_id == user_id,
    ).first()
    if not credential:
        raise HTTPException(status_code=404, detail="Vault profile not found.")
    return credential


@router.get("/vault/credentials/{credential_id}")
async def get_vault_credential(
    credential_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    credential = _get_owned_credential(db, credential_id, user["uid"])
    return automation_service.vault.get_credential_detail(db, credential)


@router.put("/vault/credentials/{credential_id}")
async def update_vault_credential(
    credential_id: int,
    payload: CredentialUpdateRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    credential = _get_owned_credential(db, credential_id, user["uid"])
    try:
        updated = automation_service.vault.update_credential(
            db, credential, payload.label, payload.domain,
            payload.username, payload.password, payload.fields,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": updated.id, "label": updated.label, "domain": updated.domain, "username": updated.username}


@router.delete("/vault/credentials/{credential_id}")
async def delete_vault_credential(
    credential_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    credential = _get_owned_credential(db, credential_id, user["uid"])
    automation_service.vault.delete_credential(db, credential)
    return {"deleted": True}


# ── Voice transcription ───────────────────────────────────────────────────────

@router.post("/transcribe")
async def transcribe_voice_prompt(
    audio: UploadFile = File(...),
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Accepts a WebM audio recording and returns transcribed text using Groq Whisper.
    Falls back gracefully if the GROQ_API_KEY is not configured.
    """
    if not settings.GROQ_API_KEY:
        raise HTTPException(
            status_code=400,
            detail="GROQ_API_KEY is not configured. Voice transcription is unavailable.",
        )

    client     = AsyncGroq(api_key=settings.GROQ_API_KEY)
    audio_data = await audio.read()

    transcription = await client.audio.transcriptions.create(
        file=(audio.filename or "prompt.webm", audio_data),
        model="whisper-large-v3-turbo",
        prompt="Browser automation task, URLs, websites, extract data, click, login, scrape.",
        response_format="json",
    )

    return {"text": transcription.text.strip()}
