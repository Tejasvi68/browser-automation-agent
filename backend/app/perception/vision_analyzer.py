"""
VisionAnalyzer – uses a multimodal LLM to interpret browser screenshots.

This is an optional module. When enabled, it helps the agent:
  - Understand what is visually on screen (useful when DOM is sparse)
  - Detect blocking overlays like cookie banners, modals, or CAPTCHAs
  - Get a recovery hint when an action fails (e.g. "click the Accept button first")

It is NOT called on every step by default. The self_heal node in graph.py
can enable it for failure recovery.
"""

from typing import Any, Dict

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app.core.llm_factory import get_vision_llm


class VisualObservation(BaseModel):
    """Structured output from the vision LLM describing the current page screenshot."""
    page_summary:            str  = Field(description="Brief visual description of what is on screen.")
    has_popup_or_modal:      bool = Field(description="True if a cookie banner, modal, or overlay is blocking the page.")
    has_captcha:             bool = Field(description="True if a CAPTCHA or bot verification is visible.")
    suggested_recovery_hint: str  = Field(
        default="",
        description="What to click or dismiss if the page is blocked or an action just failed.",
    )


class VisionAnalyzer:
    def __init__(self):
        # Bind the vision LLM to always return a VisualObservation
        self.llm = get_vision_llm(temperature=0.0).with_structured_output(VisualObservation)

    async def analyze_screenshot(self, base64_image: str, user_goal: str, context_note: str = "") -> Dict[str, Any]:
        """
        Sends a base64-encoded screenshot to the vision LLM and returns a
        structured observation with a page summary and any blocking elements detected.
        """
        prompt = (
            f"Analyze this browser screenshot in the context of the user's goal: '{user_goal}'.\n"
            f"{f'Additional context: {context_note}' if context_note else ''}\n"
            "Tell me: (1) what is visually on screen, "
            "(2) whether any modal, pop-up, cookie banner, or CAPTCHA is blocking progress, "
            "(3) a concise recovery hint if something needs to be dismissed or clicked."
        )

        message = HumanMessage(content=[
            {"type": "text",      "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}},
        ])

        result: VisualObservation = await self.llm.ainvoke([message])
        return result.model_dump()
