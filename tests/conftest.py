"""Pytest fixtures for Personal AI test suite."""

import tempfile
from pathlib import Path
from typing import Generator
import pytest
from personal_ai.config import Settings
from personal_ai.storage.database import Database
from personal_ai.storage.repositories import (
    TaskRepository,
    StepRepository,
    ApprovalRepository,
    ClipboardRepository,
)
from personal_ai.storage.artifacts import ArtifactManager


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def test_settings(temp_dir: Path) -> Settings:
    """Provide isolated test settings with temporary storage directories."""
    return Settings(
        environment="testing",
        project_root=temp_dir,
        log_dir=temp_dir / "logs",
        database_path=temp_dir / "data" / "test.db",
        artifacts_dir=temp_dir / "artifacts",
        approval_mode="safe",
        default_provider="mock",
    )


@pytest.fixture
def test_db(test_settings: Settings) -> Database:
    """Provide an initialized SQLite database in a temporary location."""
    db = Database(db_path=test_settings.database_path)
    db.initialize_schema()
    return db


@pytest.fixture
def task_repo(test_db: Database) -> TaskRepository:
    return TaskRepository(db=test_db)


@pytest.fixture
def step_repo(test_db: Database) -> StepRepository:
    return StepRepository(db=test_db)


@pytest.fixture
def approval_repo(test_db: Database) -> ApprovalRepository:
    return ApprovalRepository(db=test_db)


@pytest.fixture
def clipboard_repo(test_db: Database) -> ClipboardRepository:
    return ClipboardRepository(db=test_db)


@pytest.fixture
def artifact_manager(test_settings: Settings, test_db: Database) -> ArtifactManager:
    return ArtifactManager(base_dir=test_settings.artifacts_dir, db=test_db)
