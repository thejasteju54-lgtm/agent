"""SQLite Database Manager and Schema Migrations."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional
from personal_ai.config import settings
from personal_ai.logging.setup import get_logger

logger = get_logger(__name__)

CURRENT_SCHEMA_VERSION = 1

MIGRATIONS = {
    1: """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        prompt TEXT NOT NULL,
        status TEXT NOT NULL,
        plan_json TEXT,
        result_summary TEXT,
        error_message TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        completed_at TEXT
    );

    CREATE TABLE IF NOT EXISTS task_steps (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        step_number INTEGER NOT NULL,
        tool_name TEXT NOT NULL,
        input_params TEXT,
        output_result TEXT,
        status TEXT NOT NULL,
        risk_level TEXT NOT NULL DEFAULT 'low',
        requires_approval INTEGER NOT NULL DEFAULT 0,
        approved INTEGER NOT NULL DEFAULT 0,
        error_message TEXT,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS approvals (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        step_id TEXT,
        action_description TEXT NOT NULL,
        risk_level TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        requested_at TEXT NOT NULL,
        resolved_at TEXT,
        resolution_reason TEXT,
        FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS artifacts (
        id TEXT PRIMARY KEY,
        task_id TEXT,
        file_name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        mime_type TEXT,
        size_bytes INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS clipboard_entries (
        id TEXT PRIMARY KEY,
        content_hash TEXT UNIQUE NOT NULL,
        content_type TEXT NOT NULL,
        content_text TEXT,
        preview_path TEXT,
        source_app TEXT,
        pinned INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
    CREATE INDEX IF NOT EXISTS idx_task_steps_task ON task_steps(task_id);
    CREATE INDEX IF NOT EXISTS idx_clipboard_hash ON clipboard_entries(content_hash);
    CREATE INDEX IF NOT EXISTS idx_clipboard_type ON clipboard_entries(content_type);
    """
}


class Database:
    """Manages SQLite connections, transactions, and migrations."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.database_path
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def get_connection(self) -> sqlite3.Connection:
        """Create a configured SQLite connection."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA journal_mode = WAL;")
        except Exception:
            pass
        return conn

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for obtaining a database connection with auto-close."""
        conn = self.get_connection()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager executing statements inside a transaction."""
        conn = self.get_connection()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def get_applied_migrations(self, conn: sqlite3.Connection) -> set[int]:
        """Get set of migration versions that have been applied."""
        try:
            rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
            return {row["version"] for row in rows}
        except sqlite3.OperationalError:
            # Table does not exist yet
            return set()

    def initialize_schema(self) -> None:
        """Apply all pending migrations to the database."""
        with self.transaction() as conn:
            applied = self.get_applied_migrations(conn)
            for version in sorted(MIGRATIONS.keys()):
                if version not in applied:
                    logger.info("Applying database migration version %d...", version)
                    conn.executescript(MIGRATIONS[version])
                    conn.execute(
                        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                        (version, datetime.now(timezone.utc).isoformat()),
                    )
                    logger.info("Applied migration version %d successfully.", version)


_DB_INSTANCE: Optional[Database] = None


def get_db(db_path: Optional[Path] = None) -> Database:
    """Get or create singleton Database instance, respecting active settings or path."""
    global _DB_INSTANCE
    target_path = db_path or settings.database_path
    if _DB_INSTANCE is None or _DB_INSTANCE.db_path != target_path:
        _DB_INSTANCE = Database(db_path=target_path)
    return _DB_INSTANCE
