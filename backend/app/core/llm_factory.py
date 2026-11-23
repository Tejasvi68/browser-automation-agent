from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from app.config import settings


def get_planner_llm(temperature: float = 0.0) -> BaseChatModel:
    """Returns the Primary LLM with automatic Groq fallback for DOM reasoning & planning."""
    primary = ChatGoogleGenerativeAI(
        model=settings.PRIMARY_MODEL,
        google_api_key=settings.GOOGLE_API_KEY,
        temperature=temperature,
    )

    if settings.GROQ_API_KEY:
        fallback = ChatGroq(
            model=settings.GROQ_PLANNER_MODEL,
            groq_api_key=settings.GROQ_API_KEY,
            temperature=temperature,
        )
        return primary.with_fallbacks([fallback])

    return primary


def get_vision_llm(temperature: float = 0.0) -> BaseChatModel:
    """Returns the Multimodal Vision LLM with automatic Groq Vision fallback."""
    primary = ChatGoogleGenerativeAI(
        model=settings.PRIMARY_MODEL,
        google_api_key=settings.GOOGLE_API_KEY,
        temperature=temperature,
    )

    if settings.GROQ_API_KEY:
        fallback = ChatGroq(
            model=settings.GROQ_VISION_MODEL,
            groq_api_key=settings.GROQ_API_KEY,
            temperature=temperature,
        )
        return primary.with_fallbacks([fallback])

    return primary