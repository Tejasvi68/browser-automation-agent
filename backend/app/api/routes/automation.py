from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.firebase import get_current_user
from app.database.database import get_db
from app.database.models import ExecutionRun
from app.schemas.automation import (
    ApprovalDecisionRequest,
    CredentialCreateRequest,
    RunResponse,
    RunTaskRequest,
)
from app.services.automation_service import automation_service

router = APIRouter(tags=["Automation & Security"])


@router.post("/run", response_model=RunResponse)
async def run_automation_task(
    payload: RunTaskRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = await automation_service.start_task(
        db=db,
        user_id=user["uid"],
        task=payload.task,
        max_steps=payload.max_steps,
        timeout_seconds=payload.timeout_seconds,
    )
    return result


@router.post("/runs/{run_id}/approve", response_model=RunResponse)
async def approve_or_reject_step(
    run_id: str,
    payload: ApprovalDecisionRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return await automation_service.resume_after_approval(
            db=db, user_id=user["uid"], run_id=run_id, approved=payload.approved
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/runs", response_model=List[Dict[str, Any]])
async def list_execution_history(
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    runs = (
        db.query(ExecutionRun)
        .filter(ExecutionRun.user_id == user["uid"])
        .order_by(ExecutionRun.created_at.desc())
        .limit(30)
        .all()
    )
    return [
        {
            "run_id": r.id,
            "task": r.task,
            "status": r.status,
            "steps_history": r.steps_log or [],
            "extracted_data": r.extracted_data or [],
            "error": r.error_message,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in runs
    ]


@router.get("/runs/{run_id}/export")
async def export_run_results(
    run_id: str,
    format: str = "json",
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = (
        db.query(ExecutionRun)
        .filter(ExecutionRun.id == run_id, ExecutionRun.user_id == user["uid"])
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Execution run not found.")

    content = automation_service.export_data(run.extracted_data or [], fmt=format)
    media_type = "text/csv" if format.lower() == "csv" else "application/json"
    filename = f"run_{run_id}.{format.lower()}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/vault/credentials")
async def save_vault_credential(
    payload: CredentialCreateRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cred = automation_service.vault.store_credential(
        db=db,
        user_id=user["uid"],
        label=payload.label,
        domain=payload.domain,
        username=payload.username,
        password=payload.password,
    )
    return {"id": cred.id, "label": cred.label, "domain": cred.domain, "username": cred.username}


@router.get("/vault/credentials")
async def list_vault_credentials(
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return automation_service.vault.list_credentials_for_prompt(db=db, user_id=user["uid"])