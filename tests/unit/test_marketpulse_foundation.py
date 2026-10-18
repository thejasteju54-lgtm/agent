"""Unit tests for Phase 1: MarketPulse AI Foundation.

Tests:
1. Central configuration management & environment validation.
2. Structured logging & secret redaction.
3. Database initialization, schema migrations, and idempotent version tracking.
4. Artifact store for research reports & source documents with path containment and SHA-256 integrity.
5. Task states, bounded execution, cancellation, and idempotency.
6. Health and readiness endpoints.
7. Click-based CLI commands.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from marketpulse import __version__
from marketpulse.api.app import app
from marketpulse.cli import cli
from marketpulse.config import MarketPulseSettings, mp_settings
from marketpulse.logging.setup import RedactingFormatter, get_logger, setup_logging
from marketpulse.storage.artifacts import MarketPulseArtifactStore
from marketpulse.storage.database import get_engine, get_session, init_db, seed_initial_registry
from marketpulse.storage.migrations import apply_migrations, get_current_schema_version
from marketpulse.storage.models import ArtifactRecord, AutomationTask, TaskStatus


# ---------------------------------------------------------------------------
# 1. Config & Environment Validation Tests
# ---------------------------------------------------------------------------
def test_config_defaults_and_sanitized_summary(tmp_path: Path):
    """Verify settings defaults, directory creation, and secret redaction."""
    settings = MarketPulseSettings(
        environment="testing",
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        artifacts_dir=tmp_path / "artifacts",
        log_dir=tmp_path / "logs",
        api_secret_key="top-secret-key-12345",
        n8n_api_key="n8n-secret-token-xyz",
    )
    settings.ensure_directories()

    assert settings.data_dir.exists()
    assert settings.artifacts_dir.exists()
    assert settings.log_dir.exists()

    summary = settings.get_sanitized_summary()
    assert summary["environment"] == "testing"
    assert summary["n8n_api_key_configured"] is True
    # Verify raw secret strings are NOT present anywhere in the summary
    summary_str = json.dumps(summary)
    assert "top-secret-key-12345" not in summary_str
    assert "n8n-secret-token-xyz" not in summary_str


# ---------------------------------------------------------------------------
# 2. Structured Logging & Secret Redaction Tests
# ---------------------------------------------------------------------------
def test_logging_secret_redaction(monkeypatch):
    """Verify active API keys, Bearer tokens, and secrets are redacted from logs."""
    formatter = RedactingFormatter()

    record1 = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Request authorized with Bearer abcdef1234567890xyz",
        args=(),
        exc_info=None,
    )
    formatted1 = formatter.format(record1)
    assert "Bearer [REDACTED_TOKEN]" in formatted1
    assert "abcdef1234567890xyz" not in formatted1

    # Redact configured api_secret_key
    secret_val = mp_settings.api_secret_key
    record2 = logging.LogRecord(
        name="test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=20,
        msg=f"Failed connection using secret {secret_val}",
        args=(),
        exc_info=None,
    )
    formatted2 = formatter.format(record2)
    assert "[REDACTED_SECRET]" in formatted2
    assert secret_val not in formatted2


# ---------------------------------------------------------------------------
# 3. Database Initialization & Migration Strategy Tests
# ---------------------------------------------------------------------------
def test_database_migrations_idempotency(tmp_path: Path):
    """Verify schema migrations apply cleanly and track version idempotently."""
    db_file = tmp_path / "test_migration.db"
    engine = create_engine(f"sqlite:///{db_file}")

    # Step 1: Check initial version
    ver0 = get_current_schema_version(engine)
    assert ver0 == 0

    # Step 2: Apply migrations
    ver1 = apply_migrations(engine)
    assert ver1 == 6
    assert get_current_schema_version(engine) == 6

    # Step 3: Re-apply migrations (must be idempotent and no-op)
    ver2 = apply_migrations(engine)
    assert ver2 == 6

    # Verify tables created
    with engine.connect() as conn:
        tables = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).fetchall()
        table_names = {t[0] for t in tables}
        assert "mp_schema_migrations" in table_names
        assert "mp_automation_tasks" in table_names
        assert "mp_artifacts" in table_names
        assert "mp_companies" in table_names
        assert "mp_research_jobs" in table_names
        assert "mp_evidence_records" in table_names
        assert "mp_alert_events" in table_names
        assert "mp_approvals" in table_names


# ---------------------------------------------------------------------------
# 4. Artifact Store Lifecycle & Path Containment Tests
# ---------------------------------------------------------------------------
def test_artifact_store_lifecycle(tmp_path: Path):
    """Verify storing, retrieving, and verifying artifacts with hash checks."""
    store = MarketPulseArtifactStore(base_dir=tmp_path / "artifacts")
    engine = create_engine(f"sqlite:///{tmp_path / 'artifacts_test.db'}")
    init_db(engine)

    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    try:
        report_text = "# Market Report: Reliance Industries\n\nExecutive Summary: Solid Q2 performance."
        record = store.save_artifact(
            session=session,
            name="reliance_q2.md",
            content=report_text,
            artifact_type="REPORT",
            task_id="task-001",
        )
        session.commit()

        assert record.id is not None
        assert record.name == "reliance_q2.md"
        assert record.size_bytes == len(report_text.encode("utf-8"))
        assert len(record.content_hash) == 64

        # Read back
        data = store.read_artifact_content(record)
        assert data.decode("utf-8") == report_text

        # Verify integrity
        assert store.verify_artifact_integrity(record) is True

        # Query via store
        found = store.list_artifacts(session, task_id="task-001")
        assert len(found) == 1
        assert found[0].id == record.id
    finally:
        session.close()


def test_artifact_store_path_traversal_defense(tmp_path: Path):
    """Verify that attempting to escape the artifacts root directory is blocked."""
    store = MarketPulseArtifactStore(base_dir=tmp_path / "artifacts")
    engine = create_engine(f"sqlite:///{tmp_path / 'traversal_test.db'}")
    init_db(engine)

    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    try:
        with pytest.raises(ValueError, match="Path traversal blocked"):
            store.save_artifact(
                session=session,
                name="test.txt",
                content="test",
                subfolder="../../escaped_dir",
            )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 5. Task States, Bounded Execution & Cancellation Tests
# ---------------------------------------------------------------------------
def test_task_lifecycle_and_cancellation(tmp_path: Path):
    """Verify task state transitions: PENDING -> PLANNING -> RUNNING -> CANCELLED."""
    engine = create_engine(f"sqlite:///{tmp_path / 'tasks_test.db'}")
    init_db(engine)

    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    try:
        # 1. Create Task in PENDING
        task = AutomationTask(
            id="task-cycle-01",
            task_type="RESEARCH",
            prompt="Analyze TCS BFSI deals",
            status=TaskStatus.PENDING.value,
            step_limit=15,
            current_step=0,
            idempotency_key="idemp-key-001",
            started_at=datetime.now(timezone.utc),
        )
        session.add(task)
        session.commit()

        assert task.status == TaskStatus.PENDING.value
        assert task.step_limit == 15

        # 2. Transition to RUNNING
        task.status = TaskStatus.RUNNING.value
        task.current_step = 1
        session.commit()
        assert task.status == TaskStatus.RUNNING.value

        # 3. Cancel Task
        task.status = TaskStatus.CANCELLED.value
        task.cancellation_reason = "Operator manual override"
        task.completed_at = datetime.now(timezone.utc)
        session.commit()

        reloaded = session.query(AutomationTask).filter_by(id="task-cycle-01").first()
        assert reloaded.status == TaskStatus.CANCELLED.value
        assert reloaded.cancellation_reason == "Operator manual override"
        assert reloaded.completed_at is not None
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 6. FastAPI Endpoints Tests
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def api_client():
    init_db()
    with get_session() as session:
        seed_initial_registry(session)
    with TestClient(app) as client:
        yield client


def test_api_health_readiness_and_tasks(api_client: TestClient):
    """Verify /health, /ready, and /tasks lifecycle via HTTP API."""
    # 1. Health
    res_health = api_client.get("/api/v1/health")
    assert res_health.status_code == 200
    h_data = res_health.json()
    assert h_data["database"] == "CONNECTED"
    assert h_data["status"] in ("HEALTHY", "DEGRADED")

    # 2. Readiness
    res_ready = api_client.get("/api/v1/ready")
    assert res_ready.status_code == 200
    r_data = res_ready.json()
    assert r_data["ready"] is True
    assert r_data["checks"]["database"] is True
    assert r_data["checks"]["artifacts_store"] is True

    # 3. Create Task
    import uuid
    idemp = f"key-{uuid.uuid4().hex[:8]}"
    res_create = api_client.post(
        "/api/v1/tasks",
        json={
            "prompt": "Investigate Indian IT quarterly margin pressures",
            "task_type": "RESEARCH",
            "idempotency_key": idemp,
            "step_limit": 25,
            "auto_approve": True,
        },
    )
    assert res_create.status_code == 201
    task_data = res_create.json()
    task_id = task_data["id"]
    assert task_data["status"] == "PENDING"
    assert task_data["step_limit"] == 25
    assert task_data["idempotency_key"] == idemp

    # 4. Idempotency test (same key returns existing task)
    res_dup = api_client.post(
        "/api/v1/tasks",
        json={
            "prompt": "Different prompt but same key",
            "idempotency_key": idemp,
        },
    )
    assert res_dup.status_code == 201
    assert res_dup.json()["id"] == task_id

    # 5. Get Task Details
    res_get = api_client.get(f"/api/v1/tasks/{task_id}")
    assert res_get.status_code == 200
    assert res_get.json()["id"] == task_id

    # 6. List Tasks
    res_list = api_client.get("/api/v1/tasks?limit=10")
    assert res_list.status_code == 200
    task_ids = [t["id"] for t in res_list.json()]
    assert task_id in task_ids

    # 7. Cancel Task
    res_cancel = api_client.post(
        f"/api/v1/tasks/{task_id}/cancel",
        json={"reason": "Test-initiated cancellation"},
    )
    assert res_cancel.status_code == 200
    assert res_cancel.json()["status"] == "CANCELLED"
    assert res_cancel.json()["cancellation_reason"] == "Test-initiated cancellation"

    # 8. Query Task Artifacts (initially empty)
    res_artifacts = api_client.get(f"/api/v1/tasks/{task_id}/artifacts")
    assert res_artifacts.status_code == 200
    assert isinstance(res_artifacts.json(), list)


# ---------------------------------------------------------------------------
# 7. CLI Command Tests
# ---------------------------------------------------------------------------
def test_marketpulse_cli_commands():
    """Verify MarketPulse Click CLI commands."""
    runner = CliRunner()

    # Test --version
    res_ver = runner.invoke(cli, ["--version"])
    assert res_ver.exit_code == 0
    assert __version__ in res_ver.output

    # Test init-db
    res_init = runner.invoke(cli, ["init-db"])
    assert res_init.exit_code == 0
    assert "Database initialization complete" in res_init.output

    # Test status
    res_status = runner.invoke(cli, ["status"])
    assert res_status.exit_code == 0
    assert "Database Connection: CONNECTED" in res_status.output
    assert "MarketPulse AI Platform" in res_status.output

    # Test test-env
    res_env = runner.invoke(cli, ["test-env"])
    assert res_env.exit_code == 0
    assert "Environment is fully valid" in res_env.output

    # Test task list
    res_tasks = runner.invoke(cli, ["task", "list"])
    assert res_tasks.exit_code == 0
