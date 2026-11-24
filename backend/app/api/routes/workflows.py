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
    run = (
        db.query(ExecutionRun)
        .filter(ExecutionRun.id == payload.run_id, ExecutionRun.user_id == user["uid"])
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Source execution run not found.")

    wf_id = str(uuid.uuid4())[:10]
    wf = SavedWorkflow(
        id=wf_id,
        user_id=user["uid"],
        name=payload.name,
        description=payload.description,
        task_prompt=run.task,
        steps=run.steps_log or [],
        schedule_cron=payload.schedule_cron,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)

    if payload.schedule_cron:
        try:
            scheduler_service.schedule_workflow(
                workflow_id=wf.id,
                user_id=user["uid"],
                task_prompt=wf.task_prompt,
                cron_expr=payload.schedule_cron,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    return WorkflowResponse(
        id=wf.id,
        name=wf.name,
        description=wf.description,
        task_prompt=wf.task_prompt,
        steps=wf.steps or [],
        schedule_cron=wf.schedule_cron,
    )


@router.get("", response_model=List[WorkflowResponse])
async def list_workflows(
    user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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
    wf = (
        db.query(SavedWorkflow)
        .filter(SavedWorkflow.id == workflow_id, SavedWorkflow.user_id == user["uid"])
        .first()
    )
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    return await automation_service.start_task(db=db, user_id=user["uid"], task=wf.task_prompt)