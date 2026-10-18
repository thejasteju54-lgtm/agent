"""Unit and contract tests for Phase 2 — Research Execution Lifecycle and Persistence."""

import time
import pytest
from fastapi.testclient import TestClient

from marketpulse.api.app import app
from marketpulse.config import mp_settings
from marketpulse.storage.database import get_session_factory
from marketpulse.storage.models import AutomationTask, TaskStatus, ResearchReport


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {
        "X-API-Key": mp_settings.api_secret_key,
        "Content-Type": "application/json",
    }


def test_async_task_execution_lifecycle_and_polling(client, auth_headers):
    """Verify asynchronous task submission executes in the background and reaches terminal state."""
    payload = {
        "prompt": "Evaluate daily market brief for post-market closing session",
        "task_type": "MARKET_BRIEF",
        "sync_execute": False,
        "auto_approve": True,
    }

    resp = client.post("/api/v1/webhook/task", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    task_id = data["task_id"]
    assert task_id is not None
    assert "/webhook/task/" in data["check_url"]

    # Poll until background thread transitions task to COMPLETED
    max_wait = 15.0
    start = time.time()
    terminal_reached = False
    last_status = None

    while time.time() - start < max_wait:
        poll_resp = client.get(f"/api/v1/webhook/task/{task_id}", headers=auth_headers)
        assert poll_resp.status_code == 200
        poll_data = poll_resp.json()

        # Verify contract compatibility: both root status and task.status exist
        assert "status" in poll_data
        assert "task" in poll_data
        assert poll_data["task"]["id"] == task_id
        assert poll_data["status"] == poll_data["task"]["status"]

        last_status = poll_data["status"]
        if last_status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value):
            terminal_reached = True
            break
        time.sleep(0.4)

    assert terminal_reached is True, f"Task did not reach terminal state within {max_wait}s; last status: {last_status}"
    assert last_status == TaskStatus.COMPLETED.value
    assert poll_data["result_summary"] is not None
    assert "Executed generate_market_brief successfully" in poll_data["result_summary"]


def test_sync_task_execution_reaches_completed_status(client, auth_headers):
    """Verify sync execution transitions task to COMPLETED status upon return."""
    payload = {
        "prompt": "generate daily market brief for morning session",
        "task_type": "MARKET_BRIEF",
        "sync_execute": True,
        "auto_approve": True,
    }

    resp = client.post("/api/v1/webhook/task", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "COMPLETED"
    assert "Executed generate_market_brief successfully" in data["summary"]

    # Verify task in database has completed_at timestamp
    factory = get_session_factory()
    with factory() as session:
        task = session.query(AutomationTask).filter_by(id=data["task_id"]).first()
        assert task is not None
        assert task.status == TaskStatus.COMPLETED.value
        assert task.completed_at is not None


def test_research_pipeline_generates_and_persists_report(client, auth_headers):
    """Verify research pipeline execution creates persistent report and evidence records."""
    payload = {
        "prompt": "Analyze Reliance Industries Q2 earnings and petroleum sector outlook",
        "task_type": "RESEARCH",
        "company_symbol": "RELIANCE",
        "sync_execute": True,
        "auto_approve": True,
    }

    resp = client.post("/api/v1/webhook/task", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "COMPLETED"

    # Verify report is retrievable via reports list
    reports_resp = client.get("/api/v1/research/reports?limit=10")
    assert reports_resp.status_code == 200
    reports = reports_resp.json()
    assert len(reports) > 0

    # Ensure report metadata has verified company and structure
    rep = reports[0]
    assert rep["ticker"] == "RELIANCE"
    assert "executive_summary" in rep
    assert len(rep["verified_facts"]) > 0
