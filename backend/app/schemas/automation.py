from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RunTaskRequest(BaseModel):
    task: str = Field(..., min_length=3, description="Plain-English instruction for the browser agent.")
    max_steps: Optional[int] = Field(default=None, ge=1, le=50)
    timeout_seconds: Optional[int] = Field(default=None, ge=10, le=900)


class ApprovalDecisionRequest(BaseModel):
    approved: bool = Field(..., description="True to approve the sensitive action, False to reject.")


class CredentialCreateRequest(BaseModel):
    label: str = Field(..., min_length=2, max_length=100, description="Unique identifier e.g. 'amazon_login'")
    domain: str = Field(..., min_length=3, max_length=255)
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1)


class RunResponse(BaseModel):
    run_id: str
    status: str
    task: str
    final_summary: str = ""
    extracted_data: List[Any] = []
    steps_history: List[Dict[str, Any]] = []
    pending_approval: Optional[Dict[str, Any]] = None
    error: Optional[str] = None