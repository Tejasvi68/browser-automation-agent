from typing import Any, Dict
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from app.core.llm_factory import get_vision_llm


class VisualObservation(BaseModel):
    page_summary: str = Field(description="Brief visual summary of what is currently shown on screen.")
    has_popup_or_modal: bool = Field(description="True if a cookie banner, modal, or pop-up is blocking the page.")
    has_captcha: bool = Field(description="True if a CAPTCHA or bot verification challenge is visible.")
    suggested_recovery_hint: str = Field(
        default="",
        description="Visual guidance on what to click or dismiss if an action failed or a blocker is present.",
    )


class VisionAnalyzer:
    def __init__(self):
        self.llm = get_vision_llm(temperature=0.0).with_structured_output(VisualObservation)

    async def analyze_screenshot(self, base64_image: str, user_goal: str, context_note: str = "") -> Dict[str, Any]:
        """Analyzes a Playwright Base64 screenshot using the multimodal Vision LLM."""
        prompt = (
            f"Analyze this browser screenshot in the context of the user's goal: '{user_goal}'.\n"
            f"{f'Context: {context_note}' if context_note else ''}\n"
            "Identify what is visually on screen, whether any modal/pop-up or CAPTCHA is blocking progress, "
            "and provide a concise recovery hint if something needs to be dismissed or clicked."
        )

        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{base64_image}"},
                },
            ]
        )

        result: VisualObservation = await self.llm.ainvoke([message])
        return result.model_dump()
    