"""MarketPulse AI configuration settings using Pydantic."""

from pathlib import Path
from typing import Literal, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class MarketPulseSettings(BaseSettings):
    """Configuration settings for MarketPulse AI platform."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General
    environment: Literal["development", "production", "testing"] = "development"
    project_root: Path = PROJECT_ROOT

    # n8n Automation Engine
    n8n_base_url: str = "http://localhost:5678"
    n8n_api_key: Optional[str] = None
    n8n_timeout_seconds: float = 10.0
    n8n_max_retries: int = 3
    n8n_webhook_path_prefix: str = "webhook"

    # Database & Storage
    database_url: str = Field(
        default_factory=lambda: f"sqlite:///{PROJECT_ROOT / 'data' / 'marketpulse.db'}"
    )

    # API Server
    api_host: str = "127.0.0.1"
    api_port: int = 8001
    api_secret_key: str = "marketpulse-default-dev-secret-change-me"

    # AI Model Configuration
    default_model_provider: Literal["ollama", "cloud", "mock"] = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    cloud_api_key: Optional[str] = None
    cloud_api_base: Optional[str] = None
    cloud_model: Optional[str] = None

    def get_sanitized_summary(self) -> dict:
        """Return safe configuration dictionary with credentials masked."""
        return {
            "environment": self.environment,
            "n8n_base_url": self.n8n_base_url,
            "n8n_api_key_configured": bool(self.n8n_api_key),
            "n8n_timeout_seconds": self.n8n_timeout_seconds,
            "database_url_type": self.database_url.split("://")[0] if "://" in self.database_url else "unknown",
            "api_host": self.api_host,
            "api_port": self.api_port,
            "default_model_provider": self.default_model_provider,
        }


mp_settings = MarketPulseSettings()
