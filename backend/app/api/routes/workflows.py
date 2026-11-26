"""
Workflow routes – save, list, and replay reusable automation workflows.

Endpoints:
  POST   /workflows                    – Save a completed run as a reusable workflow
  GET    /workflows                    – List all saved workflows for the current user
  POST   /workflows/{workflow_id}/replay – Re-run a saved workflow from its task prompt
"""

import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.firebase import get_current_user
from app.database.database import get_db
from app.database.models import ExecutionRun, SavedWorkflow
from app.schemas.automation import RunResponse
from app.schemas.workflow import SaveWorkflowRequest, WorkflowResponse
from app.services.automation_service import automation_service
from app.services.scheduler_service import scheduler_service

router = APIRouter(prefix="/workflows", tags=["Workflows & Scheduling"])


@router.post("", response_model=WorkflowResponse)
async def save_reusable_workflow(
    payload: SaveWorkflowRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Saves a completed run as a named, reusable workflow.

    Optionally accepts a cron schedule so the workflow runs automatically
    (e.g. "0 9 * * *" to run every morning at 9 AM).
    """
    # Verify the source run exists and belongs to this user
    source_run = (
        db.query(ExecutionRun)
        .filter(ExecutionRun.id == payload.run_id, ExecutionRun.user_id == user["uid"])
        .first()
    )
    if not source_run:
        raise HTTPException(status_code=404, detail="Source execution run not found.")

    # Create the workflow record
    workflow = SavedWorkflow(
        id=str(uuid.uuid4())[:10],
        user_id=user["uid"],
        name=payload.name,
        description=payload.description,
        task_prompt=source_run.task,
        steps=source_run.steps_log or [],
        schedule_cron=payload.schedule_cron,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)

    # Schedule the workflow if a cron expression was provided
    if payload.schedule_cron:
        try:
            scheduler_service.schedule_workflow(
                workflow_id=workflow.id,
                user_id=user["uid"],
                task_prompt=workflow.task_prompt,
                cron_expr=payload.schedule_cron,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return WorkflowResponse(
        id=workflow.id,
        name=workflow.name,
        description=workflow.description,
        task_prompt=workflow.task_prompt,
        steps=workflow.steps or [],
        schedule_cron=workflow.schedule_cron,
    )


@router.get("", response_model=List[WorkflowResponse])
async def list_workflows(
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Returns all saved workflows for the current user."""
    rows = db.query(SavedWorkflow).filter(SavedWorkflow.user_id == user["uid"]).all()
    return [
        WorkflowResponse(
            id=w.id,
            name=w.name,
            description=w.description,
            task_prompt=w.task_prompt,
            steps=w.steps or [],
            schedule_cron=w.schedule_cron,
        )
        for w in rows
    ]


@router.post("/{workflow_id}/replay", response_model=RunResponse)
async def replay_saved_workflow(
    workflow_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-runs a saved workflow using its original task prompt."""
    workflow = (
        db.query(SavedWorkflow)
        .filter(SavedWorkflow.id == workflow_id, SavedWorkflow.user_id == user["uid"])
        .first()
    )
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    return await automation_service.start_task(
        db=db,
        user_id=user["uid"],
        task=workflow.task_prompt,
    )
