"""Application configuration management using Pydantic Settings."""

from pathlib import Path
from typing import Literal, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Root directory of the repository/project
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Core settings for Personal AI Automation System."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General
    environment: Literal["development", "production", "testing"] = "development"
    project_root: Path = PROJECT_ROOT

    # Logging
    log_level: str = "INFO"
    log_dir: Path = Field(default_factory=lambda: PROJECT_ROOT / "logs")

    # Storage Paths
    database_path: Path = Field(default_factory=lambda: PROJECT_ROOT / "data" / "personal_ai.db")
    artifacts_dir: Path = Field(default_factory=lambda: PROJECT_ROOT / "artifacts")

    # Security & Approval
    approval_mode: Literal["safe", "strict", "auto"] = "safe"

    # AI Model Configuration
    default_provider: Literal["ollama", "cloud", "mock"] = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"

    # Cloud AI Provider (Optional)
    cloud_api_provider: Optional[str] = None
    cloud_api_key: Optional[str] = None
    cloud_api_base: Optional[str] = None
    cloud_model: Optional[str] = None

    # Browser Automation
    playwright_headless: bool = True
    playwright_timeout_ms: int = 30000

    # Clipboard Settings
    clipboard_monitoring_enabled: bool = False
    clipboard_poll_interval_sec: float = 1.0

    # API / Integrations
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_auth_token: Optional[str] = None
    webhook_api_key: str = "personal-ai-secret-key"
    n8n_base_url: str = "http://localhost:5678"
    n8n_webhook_path: str = "/webhook/personal-ai"

    def ensure_directories(self) -> None:
        """Create necessary directories if they do not exist."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)


# Global singleton settings instance
settings = Settings()
