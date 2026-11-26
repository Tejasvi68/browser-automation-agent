"""
LLM Factory – creates the Groq language model instances used by the agent.

Two model slots:
  - Planner LLM: decides the next browser action (called at every step)
  - Vision LLM:  analyzes screenshots (optional; uses the same Groq endpoint)

If a FALLBACK_GROQ_API_KEY is configured, each LLM automatically retries on
the secondary Groq account when the primary account hits rate limits.
"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_groq import ChatGroq

from app.config import settings


def _make_groq_llm(model: str, api_key: str, temperature: float) -> ChatGroq:
    """Creates a ChatGroq instance with shared settings."""
    return ChatGroq(
        model=model,
        groq_api_key=api_key,
        temperature=temperature,
        reasoning_effort="low",    # Faster, cheaper reasoning tier
        request_timeout=25,
    )


def get_planner_llm(temperature: float = 0.0) -> BaseChatModel:
    """
    Returns the LLM used by AgentPlanner to decide the next browser action.
    If a fallback Groq key is set, the LLM will automatically retry on it.
    """
    primary = _make_groq_llm(settings.PRIMARY_MODEL, settings.GROQ_API_KEY, temperature)

    if settings.FALLBACK_GROQ_API_KEY:
        fallback = _make_groq_llm(settings.GROQ_PLANNER_MODEL, settings.FALLBACK_GROQ_API_KEY, temperature)
        return primary.with_fallbacks([fallback])

    return primary


def get_vision_llm(temperature: float = 0.0) -> BaseChatModel:
    """
    Returns the multimodal LLM used by VisionAnalyzer to interpret screenshots.
    Falls back to the secondary Groq account if the primary is rate-limited.
    """
    primary = _make_groq_llm(settings.PRIMARY_MODEL, settings.GROQ_API_KEY, temperature)

    if settings.FALLBACK_GROQ_API_KEY:
        fallback = _make_groq_llm(settings.GROQ_VISION_MODEL, settings.FALLBACK_GROQ_API_KEY, temperature)
        return primary.with_fallbacks([fallback])

    return primary
