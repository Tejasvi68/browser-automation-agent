from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, Field
from app.config import agent_yaml_config


class PlannedAction(BaseModel):
    thought: str = Field(description="Step-by-step reasoning based on the goal, DOM, and past history.")
    action: Literal[
        "navigate",
        "click",
        "type",
        "scroll",
        "press_key",
        "extract_text",
        "new_tab",
        "switch_tab",
        "close_tab",
        "finish",
    ] = Field(description="The atomic browser action to execute next, or 'finish' when the goal is achieved.")
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Parameters for the action. Examples: "
            "{'url': 'https://...'} for navigate/new_tab; "
            "{'selector': '#id'} for click/extract_text; "
            "{'selector': '#id', 'text': '...', 'press_enter': true} for type; "
            "{'direction': 'down', 'amount': 600} for scroll; "
            "{'tab_index': 0} for switch_tab."
        ),
    )
    is_sensitive: bool = Field(
        default=False,
        description="Set true if this step submits a form, logs in, makes a payment, or deletes data.",
    )
    final_answer: Optional[str] = Field(
        default=None,
        description="Required when action == 'finish': concise summary of findings/results for the user.",
    )


def build_planner_prompt(
    task: str,
    step_count: int,
    max_steps: int,
    rag_context: str,
    available_credentials: list,
    formatted_dom: str,
    steps_history: list,
    last_error: Optional[str] = None,
) -> str:
    base_system = agent_yaml_config.get("prompts", {}).get(
        "system_planner",
        "You are an autonomous Browser Automation Agent.",
    )

    recent_steps = steps_history[-6:] if steps_history else []
    history_text = (
        "\n".join(
            f"- Step {s.get('step')}: {s.get('action')} {s.get('params')} -> success={s.get('success')}"
            for s in recent_steps
        )
        or "None yet."
    )

    creds_text = (
        "\n".join(
            f"- Domain: {c['domain']} | Username: {c['username']} | Password Token: {c['password_placeholder']}"
            for c in available_credentials
        )
        or "No saved vault credentials."
    )

    error_block = (
        f"\nPREVIOUS STEP FAILED WITH ERROR:\n{last_error}\n"
        "Choose a different selector or recovery action (e.g., scroll, dismiss popup, or alternative element).\n"
        if last_error
        else ""
    )

    return (
        f"{base_system}\n\n"
        f"USER GOAL: {task}\n"
        f"BUDGET: Step {step_count + 1} of {max_steps}\n\n"
        f"{rag_context}\n\n"
        f"AVAILABLE VAULT CREDENTIALS (Use the exact {{VAULT:...}} token for passwords, NEVER guess passwords):\n"
        f"{creds_text}\n\n"
        f"RECENT EXECUTION HISTORY:\n{history_text}\n"
        f"{error_block}\n"
        f"CURRENT PAGE STATE:\n{formatted_dom}\n\n"
        "Decide the single best next atomic action. If you have collected all requested data or completed the task, "
        "return action='finish' with final_answer populated."
    )