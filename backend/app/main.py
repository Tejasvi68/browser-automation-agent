from contextlib import asynccontextmanager
import asyncio
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import automation, workflows
from app.config import agent_yaml_config, settings
from app.database.database import init_db
from app.services.scheduler_service import scheduler_service

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler_service.start()
    yield
    scheduler_service.shutdown()


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Autonomous Browser Automation Agent with LangGraph, Playwright, and MCP",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve step screenshots for React replay viewer
Path("screenshots").mkdir(parents=True, exist_ok=True)
app.mount("/screenshots", StaticFiles(directory="screenshots"), name="screenshots")

app.include_router(automation.router)
app.include_router(workflows.router)


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