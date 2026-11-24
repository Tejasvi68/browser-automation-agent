from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SaveWorkflowRequest(BaseModel):
    run_id: str = Field(..., description="Completed run ID to save as a reusable workflow.")
    name: str = Field(..., min_length=2, max_length=150)
    description: Optional[str] = ""
    schedule_cron: Optional[str] = Field(
        default=None,
        description="Optional 5-field cron expression e.g. '0 9 * * *' for daily 9 AM runs.",
    )


class WorkflowResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = ""
    task_prompt: str
    steps: List[Dict[str, Any]] = []
    schedule_cron: Optional[str] = None