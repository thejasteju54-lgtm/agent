"""Unit tests for SQLite backup, restore, and artifact verification."""

import os
import sqlite3
import pytest
from pathlib import Path
from click.testing import CliRunner
from personal_ai.storage.database import Database
from personal_ai.storage.repositories import TaskRepository
from personal_ai.storage.backup import (
    create_database_backup,
    restore_database_backup,
    list_backups,
    verify_artifacts,
)
from personal_ai.storage.artifacts import ArtifactManager
from personal_ai.cli import cli


@pytest.fixture
def temp_db(tmp_path: Path):
    """Create a temporary initialized SQLite database."""
    db_file = tmp_path / "test_backup.db"
    db = Database(db_path=db_file)
    db.initialize_schema()
    return db


def test_create_and_list_backup(temp_db: Database, tmp_path: Path):
    """Verify database backup creates a valid SQLite file with identical tables."""
    # Insert dummy task
    task_repo = TaskRepository(temp_db)
    task_repo.create_task("task-backup-1", "Test backup prompt", "COMPLETED")

    backup_dir = tmp_path / "backups"
    backup_path = create_database_backup(db=temp_db, backup_dir=backup_dir, custom_name="test_backup.db")

    assert backup_path.exists()
    assert backup_path.name == "test_backup.db"
    assert backup_path.stat().st_size > 0

    # Verify backup contents
    backup_conn = sqlite3.connect(str(backup_path))
    backup_conn.row_factory = sqlite3.Row
    row = backup_conn.execute("SELECT * FROM tasks WHERE id = 'task-backup-1'").fetchone()
    assert row is not None
    assert row["prompt"] == "Test backup prompt"
    backup_conn.close()

    # List backups
    backups = list_backups(backup_dir=backup_dir)
    assert len(backups) == 1
    assert backups[0]["filename"] == "test_backup.db"


def test_restore_database_backup(temp_db: Database, tmp_path: Path):
    """Verify restoring from a backup overwrites and recovers target state."""
    task_repo = TaskRepository(temp_db)
    task_repo.create_task("task-initial", "Initial prompt", "COMPLETED")

    backup_dir = tmp_path / "backups"
    backup_path = create_database_backup(db=temp_db, backup_dir=backup_dir, custom_name="snapshot.db")

    # Modify active database
    task_repo.create_task("task-mutated", "Mutated prompt", "RUNNING")
    assert task_repo.get_task("task-mutated") is not None

    # Restore from snapshot
    success = restore_database_backup(backup_file=backup_path, db=temp_db, create_safety_backup=False)
    assert success is True

    # Check restored state
    assert task_repo.get_task("task-initial") is not None
    # 'task-mutated' was not present in the snapshot
    assert task_repo.get_task("task-mutated") is None


def test_restore_invalid_file_rejected(temp_db: Database, tmp_path: Path):
    """Verify restoring an invalid or non-sqlite file raises ValueError."""
    fake_backup = tmp_path / "corrupt.db"
    fake_backup.write_text("NOT A DATABASE", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid SQLite backup file"):
        restore_database_backup(backup_file=fake_backup, db=temp_db, create_safety_backup=False)


def test_verify_artifacts_health(temp_db: Database, tmp_path: Path):
    """Verify artifact integrity detector distinguishes valid, missing, and corrupted files."""
    artifact_mgr = ArtifactManager(db=temp_db, base_dir=tmp_path / "artifacts")

    # 1. Valid artifact
    valid_art = artifact_mgr.save_bytes("valid.txt", b"Good content", task_id="task-1")

    # 2. Missing artifact
    missing_art = artifact_mgr.save_bytes("vanished.txt", b"temporary", task_id="task-1")
    # Delete file from disk
    Path(missing_art["file_path"]).unlink()

    # 3. Corrupted artifact (0 bytes on disk when DB expected bytes)
    corrupted_art = artifact_mgr.save_bytes("corrupted.txt", b"Should have content", task_id="task-1")
    Path(corrupted_art["file_path"]).write_bytes(b"")

    report = verify_artifacts(db=temp_db)

    assert report["total_records"] == 3
    assert report["valid_files"] == 1
    assert report["missing_files_count"] == 1
    assert report["corrupted_files_count"] == 1
    assert report["healthy"] is False
    assert len(report["missing"]) == 1
    assert report["missing"][0]["id"] == missing_art["id"]
    assert len(report["corrupted"]) == 1
    assert report["corrupted"][0]["id"] == corrupted_art["id"]


def test_cli_db_commands():
    """Verify CLI db commands operate without errors."""
    runner = CliRunner()

    res_init = runner.invoke(cli, ["db", "init"])
    assert res_init.exit_code == 0

    res_backup = runner.invoke(cli, ["db", "backup"])
    assert res_backup.exit_code == 0
    assert "Backup created successfully" in res_backup.output

    res_list = runner.invoke(cli, ["db", "backups"])
    assert res_list.exit_code == 0
    assert "personal_ai_backup_" in res_list.output

    res_verify = runner.invoke(cli, ["db", "verify-artifacts"])
    assert res_verify.exit_code == 0
    assert "Artifact Filesystem Verification Report" in res_verify.output
