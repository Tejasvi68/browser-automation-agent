from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings, agent_yaml_config

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Autonomous Browser Automation Agent with LangGraph, Playwright, and MCP",
)

# Allow React (Vite) frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "primary_provider": settings.PRIMARY_PROVIDER,
        "primary_model": settings.PRIMARY_MODEL,
        "fallback_provider": settings.FALLBACK_PROVIDER,
        "max_steps": agent_yaml_config.get("agent", {}).get("max_steps", 15),
    }