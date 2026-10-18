"""Schema migration manager for MarketPulse AI database.

Enforces versioned, idempotent migrations across SQLite and PostgreSQL databases.
"""

from datetime import datetime, timezone
from typing import List, Tuple
from sqlalchemy import Column, DateTime, Integer, String, Table, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from marketpulse.logging.setup import get_logger
from marketpulse.storage.models import Base

logger = get_logger(__name__)

# Schema migration history tracking table
MIGRATIONS_TABLE_NAME = "mp_schema_migrations"


def get_current_schema_version(engine: Engine) -> int:
    """Query the highest migration version applied to the database."""
    inspector = inspect(engine)
    if MIGRATIONS_TABLE_NAME not in inspector.get_table_names():
        return 0

    with engine.connect() as conn:
        result = conn.execute(
            text(f"SELECT COALESCE(MAX(version), 0) FROM {MIGRATIONS_TABLE_NAME}")
        ).scalar()
        return int(result or 0)


def apply_migrations(engine: Engine) -> int:
    """Apply all pending migrations idempotently.

    Returns:
        The updated schema version after migrations.
    """
    with engine.connect() as conn:
        # 1. Ensure migrations tracking table exists
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE_NAME} (
                    version INTEGER PRIMARY KEY,
                    name VARCHAR(150) NOT NULL,
                    applied_at TIMESTAMP NOT NULL
                )
                """
            )
        )
        conn.commit()

    current_ver = get_current_schema_version(engine)
    logger.info("Current MarketPulse database schema version: %d", current_ver)

    # 2. Migration 1: Base metadata creation
    if current_ver < 1:
        logger.info("Applying Migration 1: Initial Core MarketPulse Tables...")
        Base.metadata.create_all(bind=engine)
        _record_migration(engine, 1, "001_initial_core_tables")
        current_ver = 1

    # 3. Migration 2: Unified automation tasks, artifact tracking, and research job column additions
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    if "mp_research_jobs" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("mp_research_jobs")}
        with engine.connect() as conn:
            if "step_limit" not in existing_cols:
                logger.info("Migration 2: Adding 'step_limit' column to mp_research_jobs")
                conn.execute(text("ALTER TABLE mp_research_jobs ADD COLUMN step_limit INTEGER DEFAULT 20 NOT NULL"))
            if "current_step" not in existing_cols:
                logger.info("Migration 2: Adding 'current_step' column to mp_research_jobs")
                conn.execute(text("ALTER TABLE mp_research_jobs ADD COLUMN current_step INTEGER DEFAULT 0 NOT NULL"))
            if "cancellation_reason" not in existing_cols:
                logger.info("Migration 2: Adding 'cancellation_reason' column to mp_research_jobs")
                conn.execute(text("ALTER TABLE mp_research_jobs ADD COLUMN cancellation_reason TEXT"))
            if "retry_count" not in existing_cols:
                logger.info("Migration 2: Adding 'retry_count' column to mp_research_jobs")
                conn.execute(text("ALTER TABLE mp_research_jobs ADD COLUMN retry_count INTEGER DEFAULT 0 NOT NULL"))
            if "recovery_metadata_json" not in existing_cols:
                logger.info("Migration 2: Adding 'recovery_metadata_json' column to mp_research_jobs")
                conn.execute(text("ALTER TABLE mp_research_jobs ADD COLUMN recovery_metadata_json TEXT"))
            conn.commit()

    if current_ver < 2:
        logger.info("Applying Migration 2: Automation tasks and artifact tracking...")
        Base.metadata.create_all(bind=engine)
        _record_migration(engine, 2, "002_automation_tasks_and_artifacts")
        current_ver = 2

    # 4. Migration 3: Source Registry enrichment and Normalized Evidence Records table
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    if "mp_sources" in existing_tables:
        source_cols = {c["name"] for c in inspector.get_columns("mp_sources")}
        with engine.connect() as conn:
            if "retrieval_method" not in source_cols:
                logger.info("Migration 3: Adding 'retrieval_method' to mp_sources")
                conn.execute(text("ALTER TABLE mp_sources ADD COLUMN retrieval_method VARCHAR(50) DEFAULT 'HTTP_GET' NOT NULL"))
            if "auth_required" not in source_cols:
                logger.info("Migration 3: Adding 'auth_required' to mp_sources")
                conn.execute(text("ALTER TABLE mp_sources ADD COLUMN auth_required VARCHAR(50) DEFAULT 'NONE' NOT NULL"))
            if "rate_limit_per_minute" not in source_cols:
                logger.info("Migration 3: Adding 'rate_limit_per_minute' to mp_sources")
                conn.execute(text("ALTER TABLE mp_sources ADD COLUMN rate_limit_per_minute INTEGER DEFAULT 30 NOT NULL"))
            if "parser_name" not in source_cols:
                logger.info("Migration 3: Adding 'parser_name' to mp_sources")
                conn.execute(text("ALTER TABLE mp_sources ADD COLUMN parser_name VARCHAR(100) DEFAULT 'generic_rss' NOT NULL"))
            if "last_retrieved_at" not in source_cols:
                logger.info("Migration 3: Adding 'last_retrieved_at' to mp_sources")
                conn.execute(text("ALTER TABLE mp_sources ADD COLUMN last_retrieved_at TIMESTAMP"))
            if "freshness_max_age_hours" not in source_cols:
                logger.info("Migration 3: Adding 'freshness_max_age_hours' to mp_sources")
                conn.execute(text("ALTER TABLE mp_sources ADD COLUMN freshness_max_age_hours INTEGER DEFAULT 24 NOT NULL"))
            conn.commit()

    # Create mp_evidence_records table
    Base.metadata.create_all(bind=engine)

    if current_ver < 3:
        logger.info("Applying Migration 3: Source registry metadata & evidence records...")
        _record_migration(engine, 3, "003_evidence_records_and_source_metadata")
        current_ver = 3

    # 5. Migration 4: Watchlist Alerts & Persistent Event Records
    Base.metadata.create_all(bind=engine)

    if current_ver < 4:
        logger.info("Applying Migration 4: Watchlist alerts and persistent event tracking...")
        _record_migration(engine, 4, "004_watchlist_alerts_and_events")
        current_ver = 4

    # 6. Migration 5: Human Approval Records for Task Orchestration
    Base.metadata.create_all(bind=engine)

    if current_ver < 5:
        logger.info("Applying Migration 5: Human approval records for task orchestration...")
        _record_migration(engine, 5, "005_task_approvals_and_orchestration")
        current_ver = 5

    # 7. Migration 6: Permitted Scheduled Automation
    Base.metadata.create_all(bind=engine)

    if current_ver < 6:
        logger.info("Applying Migration 6: Permitted scheduled automation...")
        _record_migration(engine, 6, "006_schedules_and_automation")
        current_ver = 6

    logger.info("MarketPulse database schema is up-to-date at version %d", current_ver)
    return current_ver


def _record_migration(engine: Engine, version: int, name: str) -> None:
    """Record an applied migration in the schema migrations table."""
    now_utc = datetime.now(timezone.utc)
    with engine.connect() as conn:
        conn.execute(
            text(
                f"INSERT INTO {MIGRATIONS_TABLE_NAME} (version, name, applied_at) VALUES (:version, :name, :applied_at)"
            ),
            {"version": version, "name": name, "applied_at": now_utc},
        )
        conn.commit()
