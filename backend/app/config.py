from pathlib import Path
from typing import Any, Dict, Optional
import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Browser Automation Agent"
    ENVIRONMENT: str = "development"

    # Primary & Fallback LLM Configuration (loaded from .env)
    PRIMARY_PROVIDER: str = "groq"
    PRIMARY_MODEL: str = "qwen/qwen3.8-27b"
    GOOGLE_API_KEY: str = ""

    FALLBACK_PROVIDER: str = "groq"
    GROQ_API_KEY: str = ""
    FALLBACK_GROQ_API_KEY: Optional[str] = None
    GROQ_PLANNER_MODEL: str = "qwen/qwen3.8-27b"
    GROQ_VISION_MODEL: str = "qwen/qwen3.8-27b"

    # Firebase Admin SDK
    FIREBASE_CREDENTIALS_PATH: str = "firebase-service-account.json"

    # Security (Fernet encryption key for Credential Vault)
    VAULT_ENCRYPTION_KEY: str = ""

    # Observability (Langfuse)
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # Database
    DATABASE_URL: str = "sqlite:///./browser_agent.db"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


def load_yaml_config(config_path: str = "configs/agent_config.yaml") -> Dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


settings = Settings()
agent_yaml_config = load_yaml_config()
