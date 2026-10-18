"""Unit tests for Phase 7: Web Dashboard, Permitted Schedules, and Dry-Run Automation."""

import pytest
from fastapi.testclient import TestClient
from click.testing import CliRunner

from marketpulse.api.app import app
from marketpulse.storage.database import get_session, init_db, seed_initial_registry
from marketpulse.storage.models import (
    AuditEvent,
    AutomationTask,
    ScheduleDefinition,
)
from marketpulse.cli import cli


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    """Ensure database tables and seeded schedules are ready."""
    init_db()
    with get_session() as session:
        seed_initial_registry(session)


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app)


def test_dashboard_root_and_routes_served(client: TestClient):
    """Verify that root / and /dashboard return the responsive HTML dashboard."""
    # Test root /
    resp_root = client.get("/")
    assert resp_root.status_code == 200
    assert "text/html" in resp_root.headers["content-type"]
    assert "MarketPulse AI" in resp_root.text
    assert "id=\"nav-tasks\"" in resp_root.text
    assert "id=\"nav-schedules\"" in resp_root.text
    assert "id=\"nav-approvals\"" in resp_root.text

    # Test /dashboard alias
    resp_dash = client.get("/dashboard")
    assert resp_dash.status_code == 200
    assert "MarketPulse AI" in resp_dash.text


def test_dashboard_static_assets_served(client: TestClient):
    """Verify that style.css and app.js are correctly mounted and served."""
    # CSS
    resp_css = client.get("/static/style.css")
    assert resp_css.status_code == 200
    assert "text/css" in resp_css.headers["content-type"]
    assert "--bg-deep" in resp_css.text
    assert "--accent-cyan" in resp_css.text

    # JS
    resp_js = client.get("/static/app.js")
    assert resp_js.status_code == 200
    assert "javascript" in resp_js.headers["content-type"]
    assert "MarketPulse AI" in resp_js.text


def test_list_schedules_endpoint(client: TestClient):
    """Verify listing seeded schedules via API."""
    resp = client.get("/api/v1/schedules")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 4

    schedule_ids = {s["id"] for s in data}
    assert "daily_market_brief" in schedule_ids
    assert "news_polling" in schedule_ids
    assert "watchlist_evaluation" in schedule_ids


def test_create_and_update_schedule_api(client: TestClient):
    """Verify creating a custom schedule and updating its properties."""
    import uuid
    sch_id = f"closing_bell_{uuid.uuid4().hex[:6]}"
    new_sch = {
        "id": sch_id,
        "name": "Indian Market Closing Bell Analysis",
        "schedule_type": "CRON",
        "cron_expression": "30 15 * * 1-5",
        "timezone": "Asia/Kolkata",
        "task_type": "MARKET_BRIEF",
        "prompt": "Analyze market closing breadth and post-session disclosures",
        "is_active": True,
        "dry_run": False,
    }

    # Create
    create_resp = client.post("/api/v1/schedules", json=new_sch)
    assert create_resp.status_code == 201
    created_data = create_resp.json()
    assert created_data["id"] == sch_id
    assert created_data["is_active"] is True

    # Update (PATCH)
    patch_resp = client.patch(
        f"/api/v1/schedules/{sch_id}",
        json={"is_active": False, "dry_run": True},
    )
    assert patch_resp.status_code == 200
    patched_data = patch_resp.json()
    assert patched_data["is_active"] is False
    assert patched_data["dry_run"] is True


def test_schedule_trigger_dry_run_mode(client: TestClient):
    """Verify that dry-run mode returns a plan simulation without persisting a live task."""
    resp = client.post("/api/v1/schedules/daily_market_brief/trigger?force_dry_run=true")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_dry_run"] is True
    assert data["status"] == "DRY_RUN_COMPLETED"
    assert data["task_id"] is None
    assert data["details"]["mode"] == "DRY_RUN"
    assert "Simulation completed" in data["details"]["message"]

    # Verify AuditEvent was recorded
    with get_session() as session:
        audit = (
            session.query(AuditEvent)
            .filter_by(entity_id="daily_market_brief", event_type="SCHEDULE_DRY_RUN")
            .first()
        )
        assert audit is not None


def test_schedule_trigger_live_execution(client: TestClient):
    """Verify triggering a schedule in live execution mode submits an AutomationTask."""
    resp = client.post("/api/v1/schedules/news_polling/trigger?force_dry_run=false")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_dry_run"] is False
    assert data["status"] == "TASK_DISPATCHED"
    assert data["task_id"] is not None

    task_id = data["task_id"]
    with get_session() as session:
        task = session.query(AutomationTask).filter_by(id=task_id).first()
        assert task is not None
        assert task.task_type == "NEWS_POLLING"
        assert task.status in ["PENDING", "RUNNING"]


def test_cli_schedule_list_and_trigger():
    """Verify CLI schedule management commands."""
    runner = CliRunner()

    # 1. List
    list_res = runner.invoke(cli, ["schedule", "list"])
    assert list_res.exit_code == 0
    assert "daily_market_brief" in list_res.output
    assert "news_polling" in list_res.output

    # 2. Dry run trigger
    dry_res = runner.invoke(cli, ["schedule", "trigger", "daily_market_brief", "--dry-run"])
    assert dry_res.exit_code == 0
    assert "Triggered DRY RUN" in dry_res.output

    # 3. Live trigger
    live_res = runner.invoke(cli, ["schedule", "trigger", "watchlist_evaluation"])
    assert live_res.exit_code == 0
    assert "Dispatched task" in live_res.output
