

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.config import agent_yaml_config


# ── Structured LLM Output ─────────────────────────────────────────────────────

class PlannedAction(BaseModel):
    """
    The agent's decision at each step. The LLM must return exactly this schema.

    Fields:
      thought      – the LLM's step-by-step reasoning (shown in the UI)
      action       – which browser action to perform
      params       – parameters for the action (selector, url, text, key, etc.)
      is_sensitive – set True if the action involves login, payment, or deleting data
      final_answer – required when action='finish'; must list all results collected
    """

    thought: str = Field(
        description="Step-by-step reasoning based on the goal, page state, and history."
    )

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
    ] = Field(
        description="The single browser action to execute, or 'finish' when the goal is done."
    )

    params: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Action parameters. Examples:\n"
            "  navigate / new_tab: {'url': 'https://...'}\n"
            "  click / extract_text: {'element_id': 3}  or  {'selector': '#id'}\n"
            "  type: {'element_id': 2, 'text': '...', 'press_enter': true}\n"
            "  scroll: {'direction': 'down', 'amount': 600}\n"
            "  press_key: {'key': 'Enter'}\n"
            "  switch_tab: {'tab_index': 0}"
        ),
    )

    is_sensitive: bool = Field(
        default=False,
        description="Set True if this action submits a form, logs in, makes a payment, or deletes data.",
    )

    final_answer: Optional[str] = Field(
        default=None,
        description=(
            "REQUIRED when action='finish'. "
            "Must contain a complete, well-formatted list or table of ALL extracted items. "
            "Never leave this null when finishing."
        ),
    )

    @field_validator("action", mode="before")
    @classmethod
    def normalize_action(cls, value: Any) -> str:
        """Accepts common action aliases so the LLM has some flexibility."""
        if not isinstance(value, str):
            return value

        aliases = {
            "extract":  "extract_text",
            "scrape":   "extract_text",
            "goto":     "navigate",
            "open":     "navigate",
            "done":     "finish",
            "complete": "finish",
        }

        cleaned = value.strip().lower()
        return aliases.get(cleaned, cleaned)


# ── Prompt Builder ────────────────────────────────────────────────────────────

def build_planner_prompt(
    task: str,
    step_count: int,
    max_steps: int,
    rag_context: str,
    available_credentials: list,
    formatted_dom: str,
    steps_history: list,
    last_error: Optional[str] = None,
    extracted_data: Optional[List[Any]] = None,
) -> str:
    """
    Builds the full prompt sent to the planner LLM at each step.

    Sections (in order):
      1. System instruction (from agent_config.yaml or a sensible default)
      2. User goal + step budget
      3. RAG memory (past similar runs)
      4. Available vault credentials
      5. Recent execution history
      6. Error from the previous step (if any)
      7. Extracted data collected so far
      8. Current page DOM state
      9. Rules and output format instructions
    """
    # System instruction – loaded from YAML so it can be customised without code changes
    system_instruction = agent_yaml_config.get("prompts", {}).get(
        "system_planner",
        "You are an autonomous Browser Automation Agent.",
    )

    # Only show the last 6 steps to keep the prompt short
    recent_steps = steps_history[-6:] if steps_history else []
    history_text = (
        "\n".join(
            f"  Step {s.get('step')}: {s.get('action')} {s.get('params')} → success={s.get('success')}"
            for s in recent_steps
        )
        or "  None yet."
    )

    # Credential placeholders for the LLM (never raw passwords)
    credentials_text = (
        "\n".join(
            f"  Profile: {c['label']}  |  Domain: {c['domain']}  |  Username: {c['username']}  |  Password token: {c['password_placeholder']}"
            + "\n    Reusable profile fields (match by page field label; use token as the type text): "
            + ", ".join(f"{field['name']}={field['token']}" for field in c.get("fields", []))
            for c in available_credentials
        )
        or "  No saved credentials."
    )

    # Extracted data collected so far (capped to avoid huge prompts)
    extracted_text = (
        "\n".join(str(item) for item in (extracted_data or [])[:15])[:2500]
        or "  None yet."
    )

    # Error block – shown only when the previous step failed
    error_block = (
        f"\n⚠ PREVIOUS STEP FAILED:\n  {last_error}\n"
        "  Try a different selector, scroll to reveal the element, or dismiss a popup first.\n"
        if last_error
        else ""
    )

    return (
        f"{system_instruction}\n\n"
        f"USER GOAL: {task}\n"
        f"BUDGET: Step {step_count + 1} of {max_steps}\n\n"
        f"{rag_context}\n\n"
        f"VAULT CREDENTIALS (use the exact {{VAULT:...}} token for passwords – never guess):\n"
        f"{credentials_text}\n\n"
        f"RECENT EXECUTION HISTORY:\n{history_text}\n"
        f"{error_block}\n"
        f"EXTRACTED DATA SO FAR:\n{extracted_text}\n\n"
        f"CURRENT PAGE STATE:\n{formatted_dom}\n\n"
        "Decide the single best next browser action.\n"
        "If you have all the data needed or the task is complete, return action='finish'.\n\n"
        "RULES:\n"
        "1. To collect data, call 'extract_text' first (selector='body' or a specific container), "
        "then on the NEXT step return action='finish' with ALL items listed in final_answer.\n"
        "2. NEVER return action='finish' with an empty final_answer.\n"
        "3. Base final_answer ONLY on data in EXTRACTED DATA or CURRENT PAGE STATE – never invent items.\n"
        "4. Use only standard CSS selectors. Do NOT use Scrapy ::text or ::attr() syntax.\n"
        "5. NEVER repeat an action+selector that already succeeded or failed in the previous step.\n\n"
        "6. For navigation, prefer clicking the actual link/button shown in CURRENT PAGE STATE; do not guess URL paths.\n"
        "7. If navigation reports HTTP 4xx/5xx, treat the destination as failed, do not retry that URL or invent similar paths; return to the prior page or finish with a clear failure.\n\n"
        "8. If the task requests login or the page says login/sign-in is required, do NOT finish or claim completion. Find the visible Login/Sign In control and plan that action with is_sensitive=true. The safety gate must pause for human approval before login actions. Use only a matching saved credential token for the site's domain.\n"
        "9. If a requested result is missing because the site requires authentication, do not keep clicking Generate or report an invented result; handle the login flow first and wait for human approval.\n\n"
        "10. Navigate only to URLs stated in the user task, domains named by the task or a matching saved credential for the initial page, or links observed in CURRENT PAGE STATE. Click observed links instead of constructing paths. If no URL or link is available, stop with a clear error; never guess an address.\n\n"
        "11. For a task that fills a form, use the listed interactive element IDs for the actual input/textarea/select controls and issue a type action for each requested field. Do not just extract the field labels and finish. Once fields are filled, request human approval for the submit action when the safety gate requires it; only report success after the site confirms submission.\n"
        "12. When the user asks to use saved vault/profile details, match each form field's label, name, placeholder, or autocomplete value to the reusable profile fields above. Type the matching {{VAULT_FIELD:...}} token instead of exposing or inventing a value. The 'Login username / email' field is only for form controls labeled email or username; NEVER put it in a Name field. Use an explicitly named Name/Full Name profile field for a Name control, and ask if it is missing. Do not fill unrelated fields.\n"
        "13. The DOM marks input controls with value_present=true when they already contain text. Do not type into that field again unless the user explicitly requested replacing/correcting its existing value. After a successful type action, move to another unfilled requested field; never repeat a successful type action on the same element_id.\n"
        "Respond with a single valid JSON object matching the PlannedAction schema.\n"
        "Allowed action values: navigate, click, type, scroll, press_key, "
        "extract_text, new_tab, switch_tab, close_tab, finish.\n\n"
        "Examples:\n"
        '  click:  {"action": "click",  "params": {"element_id": 4}, "thought": "..."}\n'
        '  type:   {"action": "type",   "params": {"element_id": 2, "text": "...", "press_enter": true}, "thought": "..."}\n'
        '  finish: {"action": "finish", "params": {}, "final_answer": "1. Item A ...", "thought": "..."}\n'
    )
