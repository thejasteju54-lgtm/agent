"""Unit tests for configuration loading and validation."""

from pathlib import Path
from personal_ai.config import Settings


def test_settings_default_values(temp_dir: Path) -> None:
    settings = Settings(
        project_root=temp_dir,
        log_dir=temp_dir / "logs",
        database_path=temp_dir / "data" / "app.db",
        artifacts_dir=temp_dir / "artifacts",
    )
    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.approval_mode == "safe"
    assert settings.default_provider == "ollama"
    assert settings.playwright_headless is True


def test_ensure_directories(temp_dir: Path) -> None:
    settings = Settings(
        project_root=temp_dir,
        log_dir=temp_dir / "custom_logs",
        database_path=temp_dir / "custom_data" / "app.db",
        artifacts_dir=temp_dir / "custom_artifacts",
    )
    settings.ensure_directories()
    assert (temp_dir / "custom_logs").is_dir()
    assert (temp_dir / "custom_artifacts").is_dir()
    assert (temp_dir / "custom_data").is_dir()
