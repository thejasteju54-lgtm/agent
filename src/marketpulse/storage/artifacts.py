"""Artifact storage manager for MarketPulse AI.

Safely stores research reports, raw filings, JSON evidence bundles, and screenshots.
Guarantees path containment within the configured artifacts directory, calculates SHA-256
hashes, and registers metadata in SQLite/PostgreSQL.
"""

from datetime import datetime, timezone
import hashlib
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import uuid

from sqlalchemy.orm import Session

from marketpulse.config import mp_settings
from marketpulse.logging.setup import get_logger
from marketpulse.storage.models import ArtifactRecord

logger = get_logger(__name__)


class MarketPulseArtifactStore:
    """Manages files and persistent metadata for MarketPulse research artifacts."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = (base_dir or mp_settings.artifacts_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _contain_path(self, relative_or_absolute: Union[str, Path]) -> Path:
        """Ensure the target path is strictly contained within the artifacts directory."""
        path = Path(relative_or_absolute)
        if not path.is_absolute():
            resolved = (self.base_dir / path).resolve()
        else:
            resolved = path.resolve()

        if not str(resolved).startswith(str(self.base_dir)):
            raise ValueError(
                f"Path traversal blocked: target path '{resolved}' escapes base directory '{self.base_dir}'"
            )
        return resolved

    def save_artifact(
        self,
        session: Session,
        name: str,
        content: Union[str, bytes],
        artifact_type: str = "REPORT",
        task_id: Optional[str] = None,
        job_id: Optional[str] = None,
        subfolder: Optional[str] = None,
    ) -> ArtifactRecord:
        """Write artifact content to disk and register metadata in database.

        Args:
            session: Active SQLAlchemy session.
            name: Filename (e.g. 'report_TCS_20261018.md').
            content: Text string or binary bytes to store.
            artifact_type: 'REPORT', 'SOURCE_DOCUMENT', 'EVIDENCE_BUNDLE', or 'SCREENSHOT'.
            task_id: Optional linked AutomationTask ID.
            job_id: Optional linked ResearchJob ID.
            subfolder: Optional subdirectory inside artifacts directory.

        Returns:
            The created ArtifactRecord entity.
        """
        # Determine destination folder
        dest_dir = self.base_dir
        if subfolder:
            dest_dir = self._contain_path(self.base_dir / subfolder)
            dest_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize filename
        safe_name = Path(name).name
        file_path = self._contain_path(dest_dir / safe_name)

        # Encode bytes
        if isinstance(content, str):
            data_bytes = content.encode("utf-8")
        else:
            data_bytes = content

        # Compute SHA-256 hash
        content_hash = hashlib.sha256(data_bytes).hexdigest()
        size_bytes = len(data_bytes)

        # Write to disk
        file_path.write_bytes(data_bytes)

        # Infer MIME type
        guessed_type, _ = mimetypes.guess_type(str(file_path))
        mime_type = guessed_type or ("text/markdown" if safe_name.endswith(".md") else "application/octet-stream")

        # Persist record
        record_id = str(uuid.uuid4())
        record = ArtifactRecord(
            id=record_id,
            task_id=task_id,
            job_id=job_id,
            name=safe_name,
            artifact_type=artifact_type,
            file_path=str(file_path),
            content_hash=content_hash,
            mime_type=mime_type,
            size_bytes=size_bytes,
            created_at=datetime.now(timezone.utc),
        )
        session.add(record)
        session.flush()

        logger.info(
            "Saved artifact '%s' (%d bytes, hash=%s) at %s",
            safe_name,
            size_bytes,
            content_hash[:12],
            file_path,
        )
        return record

    def read_artifact_content(self, record: ArtifactRecord) -> bytes:
        """Read artifact binary content from disk, verifying path containment."""
        path = self._contain_path(record.file_path)
        if not path.exists():
            raise FileNotFoundError(f"Artifact file not found on disk at {path}")
        return path.read_bytes()

    def verify_artifact_integrity(self, record: ArtifactRecord) -> bool:
        """Check whether the on-disk file exists and matches the recorded SHA-256 hash."""
        try:
            data = self.read_artifact_content(record)
            actual_hash = hashlib.sha256(data).hexdigest()
            return actual_hash == record.content_hash
        except Exception:
            return False

    def list_artifacts(
        self,
        session: Session,
        task_id: Optional[str] = None,
        job_id: Optional[str] = None,
        artifact_type: Optional[str] = None,
    ) -> List[ArtifactRecord]:
        """Query artifacts filtered by task, job, or type."""
        query = session.query(ArtifactRecord)
        if task_id:
            query = query.filter(ArtifactRecord.task_id == task_id)
        if job_id:
            query = query.filter(ArtifactRecord.job_id == job_id)
        if artifact_type:
            query = query.filter(ArtifactRecord.artifact_type == artifact_type)
        return query.order_by(ArtifactRecord.created_at.desc()).all()
