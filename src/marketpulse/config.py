import os
from pathlib import Path
import tempfile
from typing import Literal, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
IS_SERVERLESS = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
TMP_ROOT = Path(tempfile.gettempdir()) / "marketpulse"


class MarketPulseSettings(BaseSettings):
    """Configuration settings for MarketPulse AI platform."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General & Operating Mode
    environment: Literal["development", "production", "testing"] = "development"
    operating_mode: Literal["desktop", "cloud"] = "cloud" if IS_SERVERLESS else "desktop"
    project_root: Path = PROJECT_ROOT

    # Logging
    log_level: str = "INFO"
    log_dir: Path = Field(
        default_factory=lambda: TMP_ROOT / "logs" if IS_SERVERLESS else PROJECT_ROOT / "logs"
    )

    # Storage Paths & Database
    data_dir: Path = Field(
        default_factory=lambda: TMP_ROOT / "data" if IS_SERVERLESS else PROJECT_ROOT / "data"
    )
    database_url: str = Field(
        default_factory=lambda: (
            os.environ.get("DATABASE_URL")
            or (f"sqlite:///{TMP_ROOT / 'data' / 'marketpulse.db'}" if IS_SERVERLESS else f"sqlite:///{PROJECT_ROOT / 'data' / 'marketpulse.db'}")
        )
    )
    artifacts_dir: Path = Field(
        default_factory=lambda: TMP_ROOT / "artifacts" if IS_SERVERLESS else PROJECT_ROOT / "artifacts"
    )

    # API Server
    api_host: str = "127.0.0.1"
    api_port: int = 8001
    api_secret_key: str = "marketpulse-default-dev-secret-change-me"

    # n8n Automation Engine
    n8n_enabled: bool = True
    n8n_base_url: str = "http://localhost:5678"
    n8n_webhook_url: Optional[str] = None
    n8n_api_key: Optional[str] = None
    n8n_webhook_secret: Optional[str] = None
    n8n_timeout_seconds: float = 10.0
    n8n_max_retries: int = 3
    n8n_webhook_path_prefix: str = "webhook"

    # Cloudflare Access Service Token (Optional for Tunnels / Cloud)
    cloudflare_access_client_id: Optional[str] = None
    cloudflare_access_client_secret: Optional[str] = None
    marketpulse_base_url: str = "http://127.0.0.1:8001"
    personal_ai_base_url: Optional[str] = None

    # AI Model Configuration
    default_model_provider: Literal["ollama", "cloud", "mock"] = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    cloud_api_key: Optional[str] = None
    cloud_api_base: Optional[str] = None
    cloud_model: Optional[str] = None

    def ensure_directories(self) -> None:
        """Create necessary directories if they do not exist."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def get_sanitized_summary(self) -> dict:
        """Return safe configuration dictionary with credentials masked."""
        return {
            "environment": self.environment,
            "operating_mode": self.operating_mode,
            "database_url_type": self.database_url.split("://")[0] if "://" in self.database_url else "unknown",
            "api_host": self.api_host,
            "api_port": self.api_port,
            "n8n_enabled": self.n8n_enabled,
            "n8n_base_url": self.n8n_base_url,
            "n8n_api_key_configured": bool(self.n8n_api_key),
            "n8n_webhook_url_configured": bool(self.n8n_webhook_url),
            "n8n_webhook_secret_configured": bool(self.n8n_webhook_secret),
            "cloudflare_access_configured": bool(self.cloudflare_access_client_id and self.cloudflare_access_client_secret),
            "n8n_timeout_seconds": self.n8n_timeout_seconds,
            "default_model_provider": self.default_model_provider,
            "artifacts_dir": str(self.artifacts_dir),
            "log_dir": str(self.log_dir),
        }


mp_settings = MarketPulseSettings()
mp_settings.ensure_directories()
