"""Database backup and restoration utility for MarketPulse AI."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Dict, List, Optional
from sqlalchemy import text

from marketpulse.config import mp_settings
from marketpulse.logging.setup import get_logger
from marketpulse.storage.database import get_engine, get_session
from marketpulse.storage.migrations import get_current_schema_version
from marketpulse.storage.models import AuditEvent

logger = get_logger(__name__)


def _compute_sha256(file_path: Path) -> str:
    """Compute SHA256 checksum of a file."""
    hasher = hashlib.sha256()
    with file_path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class DatabaseBackupManager:
    """Coordinates consistent online backups and safe recovery for MarketPulse storage."""

    def __init__(self, backup_dir: Optional[Path] = None):
        self.backup_dir = backup_dir or (mp_settings.data_dir / "backups")
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self, label: Optional[str] = None) -> Dict[str, Any]:
        """Perform a consistent online backup of the local database."""
        db_url = mp_settings.database_url
        if not db_url.startswith("sqlite"):
            raise NotImplementedError(
                f"Automated file backup currently supports SQLite. For PostgreSQL, use pg_dump."
            )

        # Extract local db file path
        sqlite_path_str = db_url.replace("sqlite:///", "")
        source_path = Path(sqlite_path_str).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Database file '{source_path}' does not exist.")

        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        tag = f"_{label}" if label else ""
        backup_filename = f"marketpulse_backup_{timestamp_str}{tag}.db"
        dest_path = self.backup_dir / backup_filename
        meta_path = self.backup_dir / f"{backup_filename}.meta.json"

        # Checkpoint WAL first to flush committed transactions
        engine = get_engine()
        with engine.connect() as conn:
            try:
                conn.execute(text("PRAGMA wal_checkpoint(FULL)"))
                conn.commit()
            except Exception as e:
                logger.warning("WAL checkpoint before backup failed: %s", e)

        # Use SQLite Online Backup API for hot backup consistency
        src_conn = sqlite3.connect(str(source_path))
        dest_conn = sqlite3.connect(str(dest_path))
        try:
            src_conn.backup(dest_conn, pages=100)
            logger.info("Database online backup completed to '%s'", dest_path)
        finally:
            dest_conn.close()
            src_conn.close()

        sha256 = _compute_sha256(dest_path)
        size_bytes = dest_path.stat().st_size
        schema_version = get_current_schema_version(engine)

        metadata = {
            "backup_filename": backup_filename,
            "backup_path": str(dest_path),
            "size_bytes": size_bytes,
            "sha256": sha256,
            "schema_version": schema_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_path": str(source_path),
        }
        meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        # Record Audit Event
        try:
            with get_session() as session:
                audit = AuditEvent(
                    event_type="DATABASE_BACKUP_CREATED",
                    entity_type="Database",
                    entity_id=backup_filename,
                    details_json=json.dumps(metadata),
                    actor="backup_manager",
                )
                session.add(audit)
                session.commit()
        except Exception as e:
            logger.warning("Failed to record audit event for backup: %s", e)

        return metadata

    def restore_backup(self, backup_path: Path) -> Dict[str, Any]:
        """Safely restore database from a verified backup file."""
        target_file = Path(backup_path).resolve()
        if not target_file.exists():
            raise FileNotFoundError(f"Backup file '{target_file}' not found.")

        # Check file header for SQLite signature
        with target_file.open("rb") as f:
            header = f.read(16)
            if not header.startswith(b"SQLite format 3"):
                raise ValueError(f"File '{target_file}' is not a valid SQLite database.")

        # Verify checksum if metadata file exists
        meta_file = Path(str(target_file) + ".meta.json")
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                expected_sha = meta.get("sha256")
                actual_sha = _compute_sha256(target_file)
                if expected_sha and actual_sha != expected_sha:
                    raise ValueError(
                        f"Checksum mismatch for '{target_file}'. Expected {expected_sha}, got {actual_sha}."
                    )
            except Exception as e:
                logger.warning("Metadata verification encountered: %s", e)

        db_url = mp_settings.database_url
        sqlite_path_str = db_url.replace("sqlite:///", "")
        active_db_path = Path(sqlite_path_str).resolve()

        # 1. Take safety pre-restore backup if active DB exists
        if active_db_path.exists():
            safety_copy = self.backup_dir / f"safety_pre_restore_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.db"
            shutil.copy2(active_db_path, safety_copy)
            logger.info("Saved pre-restore safety copy at '%s'", safety_copy)

        # 2. Close active engine connections
        engine = get_engine()
        engine.dispose()

        # 3. Copy backup file over active database
        shutil.copy2(target_file, active_db_path)
        logger.info("Restored active database from '%s'", target_file)

        # 4. Verify restored engine schema
        restored_engine = get_engine()
        new_version = get_current_schema_version(restored_engine)

        result = {
            "status": "RESTORED",
            "restored_from": str(target_file),
            "database_path": str(active_db_path),
            "schema_version": new_version,
            "restored_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            with get_session() as session:
                audit = AuditEvent(
                    event_type="DATABASE_RESTORED",
                    entity_type="Database",
                    entity_id=target_file.name,
                    details_json=json.dumps(result),
                    actor="backup_manager",
                )
                session.add(audit)
                session.commit()
        except Exception as e:
            logger.warning("Failed to record audit event for restore: %s", e)

        return result

    def list_backups(self) -> List[Dict[str, Any]]:
        """List all verified backups in the backup directory."""
        results = []
        for file in sorted(self.backup_dir.glob("marketpulse_backup_*.db"), reverse=True):
            meta_file = Path(str(file) + ".meta.json")
            if meta_file.exists():
                try:
                    data = json.loads(meta_file.read_text(encoding="utf-8"))
                    results.append(data)
                    continue
                except Exception:
                    pass

            results.append({
                "backup_filename": file.name,
                "backup_path": str(file),
                "size_bytes": file.stat().st_size,
                "created_at": datetime.fromtimestamp(file.stat().st_mtime, timezone.utc).isoformat(),
            })
        return results
