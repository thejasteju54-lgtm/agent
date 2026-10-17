"""Database Backup, Restore, and Artifact Verification."""

import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from personal_ai.config import settings
from personal_ai.logging.setup import get_logger
from personal_ai.storage.database import Database, get_db

logger = get_logger(__name__)


def _utc_now_formatted() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def get_default_backup_dir() -> Path:
    """Return default backup directory path."""
    backup_dir = settings.data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def create_database_backup(
    db: Optional[Database] = None,
    backup_dir: Optional[Path] = None,
    custom_name: Optional[str] = None,
) -> Path:
    """Create a consistent, online backup of the SQLite database using SQLite's backup API.

    This handles WAL pages safely and guarantees database file consistency.
    """
    database = db or get_db()
    dest_dir = backup_dir or get_default_backup_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)

    timestamp = _utc_now_formatted()
    filename = custom_name or f"personal_ai_backup_{timestamp}.db"
    dest_path = dest_dir / filename

    logger.info("Starting online backup from %s to %s", database.db_path, dest_path)

    # Use SQLite online backup API
    with database.connection() as src_conn:
        dest_conn = sqlite3.connect(str(dest_path))
        try:
            src_conn.backup(dest_conn)
            dest_conn.commit()
        finally:
            dest_conn.close()

    logger.info("Database backup created successfully at: %s (size: %d bytes)", dest_path, dest_path.stat().st_size)
    return dest_path


def restore_database_backup(
    backup_file: Path,
    db: Optional[Database] = None,
    create_safety_backup: bool = True,
) -> bool:
    """Safely restore the SQLite database from a backup file.

    Performs validation and creates a pre-restore safety copy of the active database.
    """
    database = db or get_db()
    backup_path = Path(backup_file).resolve()

    if not backup_path.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_path}")

    # Validate that the backup file is a readable SQLite database
    try:
        test_conn = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
        cur = test_conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cur.fetchall()]
        test_conn.close()
        if "tasks" not in tables:
            raise ValueError(f"Backup file does not contain expected Personal AI tables. Found: {tables}")
    except Exception as e:
        logger.error("Failed backup validation for %s: %s", backup_path, e)
        raise ValueError(f"Invalid SQLite backup file: {e}") from e

    # Create safety backup of the existing active database if it exists
    if create_safety_backup and database.db_path.exists():
        safety_path = get_default_backup_dir() / f"pre_restore_safety_{_utc_now_formatted()}.db"
        logger.info("Creating pre-restore safety backup at: %s", safety_path)
        create_database_backup(db=database, custom_name=safety_path.name)

    # Restore from backup using SQLite backup API
    logger.info("Restoring database from %s into %s", backup_path, database.db_path)
    src_conn = sqlite3.connect(str(backup_path))
    try:
        with database.connection() as dest_conn:
            src_conn.backup(dest_conn)
            dest_conn.commit()
    finally:
        src_conn.close()

    logger.info("Database restored successfully from %s", backup_path)
    return True


def list_backups(backup_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """List all available SQLite backups with file metadata."""
    dir_path = backup_dir or get_default_backup_dir()
    if not dir_path.exists():
        return []

    backups = []
    for file in sorted(dir_path.glob("*.db"), key=lambda f: f.stat().st_mtime, reverse=True):
        stat = file.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        backups.append({
            "filename": file.name,
            "path": str(file),
            "size_bytes": stat.st_size,
            "modified_at": mtime,
        })
    return backups


def verify_artifacts(db: Optional[Database] = None) -> Dict[str, Any]:
    """Verify that all artifacts recorded in SQLite actually exist on the filesystem.

    Detects missing or corrupt files and reports diagnostic statistics.
    """
    database = db or get_db()
    with database.connection() as conn:
        rows = conn.execute("SELECT * FROM artifacts ORDER BY created_at DESC").fetchall()

    total = len(rows)
    valid_count = 0
    missing = []
    corrupted = []

    for row in rows:
        row_dict = dict(row)
        file_path = Path(row_dict["file_path"])
        expected_size = row_dict.get("size_bytes")

        if not file_path.exists():
            missing.append({
                "id": row_dict["id"],
                "file_name": row_dict["file_name"],
                "file_path": str(file_path),
                "task_id": row_dict["task_id"],
                "error": "File does not exist on filesystem",
            })
        elif file_path.is_file():
            actual_size = file_path.stat().st_size
            if expected_size is not None and expected_size > 0 and actual_size == 0:
                corrupted.append({
                    "id": row_dict["id"],
                    "file_name": row_dict["file_name"],
                    "file_path": str(file_path),
                    "expected_size": expected_size,
                    "actual_size": actual_size,
                    "error": "File is empty on filesystem but recorded with non-zero size",
                })
            else:
                valid_count += 1
        else:
            missing.append({
                "id": row_dict["id"],
                "file_name": row_dict["file_name"],
                "file_path": str(file_path),
                "task_id": row_dict["task_id"],
                "error": "Path is not a regular file",
            })

    report = {
        "total_records": total,
        "valid_files": valid_count,
        "missing_files_count": len(missing),
        "corrupted_files_count": len(corrupted),
        "missing": missing,
        "corrupted": corrupted,
        "healthy": (len(missing) == 0 and len(corrupted) == 0),
    }

    if not report["healthy"]:
        logger.warning(
            "Artifact verification found issues: %d missing, %d corrupted out of %d total",
            len(missing),
            len(corrupted),
            total,
        )
    else:
        logger.info("Artifact verification completed successfully: %d/%d valid.", valid_count, total)

    return report
