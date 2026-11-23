from typing import Any, Dict, List, Optional, TypedDict


class AgentState(TypedDict):
    run_id: str
    user_id: str
    task: str
    status: str  # running | awaiting_approval | completed | failed | rejected

    # Step & safety budgets
    step_count: int
    max_steps: int
    retry_count: int
    max_retries_per_step: int

    # Context gathered from M2 (Perception), M4 (RAG), and M5 (Vault)
    rag_context: str
    available_credentials: List[Dict[str, str]]
    dom_snapshot: Dict[str, Any]
    formatted_dom: str
    latest_screenshot: Optional[Dict[str, str]]

    # Current proposed action & approval state
    next_action: Optional[Dict[str, Any]]
    approval_approved: Optional[bool]
    pending_approval_reason: Optional[str]

    # Execution history & extracted output
    steps_history: List[Dict[str, Any]]
    extracted_data: List[Any]
    final_summary: str
    last_error: Optional[str]