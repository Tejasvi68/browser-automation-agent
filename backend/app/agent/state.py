from typing import Any, Dict, List, Optional, TypedDict


class AgentState(TypedDict):
    # ── Identity ──────────────────────────────────────────────────────────────
    run_id: str    # Unique ID for this execution run
    user_id: str   # Firebase UID of the user who started the task
    task: str      # Plain-English task description given by the user

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    # Possible values: "running" | "awaiting_approval" | "completed" | "failed" | "rejected"
    status: str

    # ── Step budgets ──────────────────────────────────────────────────────────
    step_count: int           # How many steps have been executed so far
    max_steps: int            # Hard cap – agent stops if this is reached
    retry_count: int          # Consecutive failures on the current step
    max_retries_per_step: int # Agent gives up on a step after this many retries

    # ── Page context (updated each perceive cycle) ────────────────────────────
    dom_snapshot: Dict[str, Any]  # Raw JSON from DOMAnalyzer.inspect()
    formatted_dom: str            # Human-readable string sent to the planner LLM

    # ── Memory / credentials (loaded once at the start) ───────────────────────
    rag_context: str                       # Past similar workflows from vector memory
    available_credentials: List[Dict[str, str]]  # Vault labels the LLM can reference

    # ── Screenshot (overwritten after every step) ─────────────────────────────
    latest_screenshot: Optional[Dict[str, str]]  # {step, file_path, base64, url}

    # ── Planner output ────────────────────────────────────────────────────────
    next_action: Optional[Dict[str, Any]]  # What the LLM decided to do next

    # ── Human approval ────────────────────────────────────────────────────────
    # Set to True/False by the /approve endpoint; None while no decision is pending
    approval_approved: Optional[bool]
    pending_approval_reason: Optional[str]  # Why approval was requested
    login_approval_granted: bool  # One approval authorizes the current login form through submission

    # ── Results ───────────────────────────────────────────────────────────────
    steps_history: List[Dict[str, Any]]  # Log of every executed step
    extracted_data: List[Any]            # Data collected by extract_text actions
    final_summary: str                   # Agent's closing answer or error message
    last_error: Optional[str]            # Most recent step error (cleared on success)
