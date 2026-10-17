"""Artifact manager for local filesystem persistence."""

import json
import mimetypes
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from personal_ai.config import settings
from personal_ai.storage.database import Database, get_db
from personal_ai.logging.setup import get_logger

logger = get_logger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArtifactManager:
    """Manages file storage and metadata tracking for generated artifacts."""

    def __init__(self, base_dir: Optional[Path] = None, db: Optional[Database] = None):
        self.base_dir = base_dir or settings.artifacts_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db = db or get_db()

    def save_text(
        self,
        file_name: str,
        content: str,
        task_id: Optional[str] = None,
        mime_type: str = "text/plain",
    ) -> Dict[str, Any]:
        """Save a text artifact to disk and record its metadata."""
        return self._save_data(file_name, content.encode("utf-8"), task_id, mime_type)

    def save_json(
        self,
        file_name: str,
        data: Any,
        task_id: Optional[str] = None,
        indent: int = 2,
    ) -> Dict[str, Any]:
        """Save structured JSON artifact to disk and record its metadata."""
        content = json.dumps(data, indent=indent).encode("utf-8")
        return self._save_data(file_name, content, task_id, "application/json")

    def save_bytes(
        self,
        file_name: str,
        data: bytes,
        task_id: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Save binary artifact to disk and record its metadata."""
        guessed_type, _ = mimetypes.guess_type(file_name)
        resolved_mime = mime_type or guessed_type or "application/octet-stream"
        return self._save_data(file_name, data, task_id, resolved_mime)

    def _save_data(
        self,
        file_name: str,
        data: bytes,
        task_id: Optional[str],
        mime_type: str,
    ) -> Dict[str, Any]:
        """Internal helper to write bytes and persist artifact row."""
        if task_id:
            target_dir = self.base_dir / task_id
        else:
            target_dir = self.base_dir / "general"

        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / file_name
        file_path.write_bytes(data)

        artifact_id = str(uuid.uuid4())
        size_bytes = len(data)
        now = _utc_now_iso()

        with self.db.transaction() as conn:
            actual_task_id = None
            if task_id:
                row = conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone()
                if row:
                    actual_task_id = task_id
                else:
                    logger.warning("Task ID '%s' not found in database; saving artifact as general.", task_id)

            conn.execute(
                """
                INSERT INTO artifacts (id, task_id, file_name, file_path, mime_type, size_bytes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (artifact_id, actual_task_id, file_name, str(file_path.resolve()), mime_type, size_bytes, now),
            )

        return {
            "id": artifact_id,
            "task_id": task_id,
            "file_name": file_name,
            "file_path": str(file_path.resolve()),
            "mime_type": mime_type,
            "size_bytes": size_bytes,
            "created_at": now,
        }

    def get_artifact(self, artifact_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve artifact metadata by ID."""
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
            return dict(row) if row else None

    def list_artifacts_for_task(self, task_id: str) -> List[Dict[str, Any]]:
        """List all artifacts generated during a specific task."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM artifacts WHERE task_id = ? ORDER BY created_at ASC",
                (task_id,),
            ).fetchall()
            return [dict(r) for r in rows]
