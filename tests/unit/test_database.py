"""Unit tests for SQLite database manager and migrations."""

from pathlib import Path
from personal_ai.storage.database import Database


def test_database_initialization_and_tables(temp_dir: Path) -> None:
    db_file = temp_dir / "test.db"
    db = Database(db_path=db_file)
    db.initialize_schema()

    assert db_file.exists()

    with db.connection() as conn:
        applied = db.get_applied_migrations(conn)
        assert 1 in applied

        # Verify tables created
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t["name"] for t in tables}

        expected_tables = {
            "schema_migrations",
            "tasks",
            "task_steps",
            "approvals",
            "artifacts",
            "clipboard_entries",
        }
        assert expected_tables.issubset(table_names)


def test_idempotent_migration(temp_dir: Path) -> None:
    db_file = temp_dir / "test_idempotent.db"
    db = Database(db_path=db_file)
    db.initialize_schema()
    # Calling it a second time should not raise an error
    db.initialize_schema()

    with db.connection() as conn:
        count = conn.execute("SELECT COUNT(*) as cnt FROM schema_migrations").fetchone()["cnt"]
        assert count == 1
