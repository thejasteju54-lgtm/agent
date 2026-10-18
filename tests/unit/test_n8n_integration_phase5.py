"""Unit and contract tests for Phase 5 — Real n8n Integration."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from marketpulse.api.app import app
from marketpulse.config import mp_settings
from marketpulse.n8n.client import N8nClient
from marketpulse.n8n.models import ConnectionState
import uuid
from marketpulse.storage.database import get_session_factory
from marketpulse.storage.models import AuditEvent, AutomationTask, TaskStatus


@pytest.fixture
def client():
    """Test client for MarketPulse FastAPI application."""
    return TestClient(app)


@pytest.fixture
def session():
    """Database session fixture for tests."""
    factory = get_session_factory()
    sess = factory()
    try:
        yield sess
    finally:
        sess.close()


@pytest.fixture
def auth_headers():
    return {
        "X-API-Key": mp_settings.api_secret_key,
        "Content-Type": "application/json",
    }


def test_n8n_client_cloudflare_access_headers():
    """Verify CF-Access-Client-Id and CF-Access-Client-Secret are attached when configured."""
    with patch.object(mp_settings, "cloudflare_access_client_id", "test-cf-id"), \
         patch.object(mp_settings, "cloudflare_access_client_secret", "test-cf-secret"), \
         patch.object(mp_settings, "n8n_webhook_secret", "custom-wh-secret"):

        client = N8nClient(base_url="http://localhost:5678", api_key="test-api-key")
        api_headers = client._get_api_headers()
        assert api_headers["CF-Access-Client-Id"] == "test-cf-id"
        assert api_headers["CF-Access-Client-Secret"] == "test-cf-secret"
        assert api_headers["X-N8N-API-KEY"] == "test-api-key"

        wh_headers = client._get_webhook_headers()
        assert wh_headers["CF-Access-Client-Id"] == "test-cf-id"
        assert wh_headers["CF-Access-Client-Secret"] == "test-cf-secret"
        assert wh_headers["X-API-Key"] == "custom-wh-secret"
        assert wh_headers["X-Webhook-Secret"] == "custom-wh-secret"


def test_n8n_client_send_callback_success_and_retry():
    """Verify send_callback handles retries and returns True on 200 OK."""
    client = N8nClient(base_url="http://localhost:5678")
    payload = {"task_id": "test-task", "status": "COMPLETED", "summary": "Done"}

    # Mock successful response
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        success = client.send_callback(
            callback_url="http://localhost:5678/webhook/test-callback",
            payload=payload,
            max_retries=2,
        )
        assert success is True
        assert mock_post.call_count == 1

    # Mock fail-fast on 401 Unauthorized
    mock_unauth = MagicMock()
    mock_unauth.status_code = 401
    with patch("httpx.Client.post", return_value=mock_unauth) as mock_post:
        success = client.send_callback(
            callback_url="http://localhost:5678/webhook/test-callback",
            payload=payload,
            max_retries=3,
        )
        assert success is False
        assert mock_post.call_count == 1  # Should not retry bad credentials


def test_root_health_and_version_endpoints(client):
    """Verify /health and /ready operate directly at root without /api/v1 prefix."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("HEALTHY", "DEGRADED")
    assert "database" in data
    assert "n8n_status" in data

    ready_resp = client.get("/ready")
    assert ready_resp.status_code == 200
    assert ready_resp.json()["ready"] is True


def test_webhook_task_auth_enforcement(client):
    """Verify /webhook/task rejects invalid API keys and rejects missing key in production."""
    # Invalid key rejection
    resp = client.post(
        "/webhook/task",
        json={"prompt": "Generate report"},
        headers={"X-API-Key": "invalid-secret-key"},
    )
    assert resp.status_code == 403

    # Production missing key rejection
    with patch.object(mp_settings, "environment", "production"):
        prod_resp = client.post("/webhook/task", json={"prompt": "Generate report"})
        assert prod_resp.status_code == 401


def test_webhook_task_async_submission(client, auth_headers, session):
    """Verify asynchronous task submission returns task ID promptly with PENDING status."""
    payload = {
        "prompt": "Evaluate quarterly performance of Tata Motors",
        "priority": "high",
        "auto_approve": False,
        "sync_execute": False,
        "metadata": {"source": "n8n", "workflow_id": "MP-03"},
    }
    resp = client.post("/webhook/task", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data
    assert data["status"] == "PENDING"
    assert "/webhook/task/" in data["check_url"]

    # Verify task persisted in database
    task = session.query(AutomationTask).filter(AutomationTask.id == data["task_id"]).first()
    assert task is not None
    assert task.status == TaskStatus.PENDING.value
    assert task.requires_approval is True


def test_webhook_task_status_polling(client, auth_headers):
    """Verify n8n can poll /webhook/task/{task_id} to track execution and artifacts."""
    test_id = f"poll-test-{uuid.uuid4()}"
    factory = get_session_factory()
    with factory() as sess:
        task = AutomationTask(
            id=test_id,
            task_type="RESEARCH",
            prompt="Poll test task",
            status=TaskStatus.COMPLETED.value,
            step_limit=10,
            current_step=1,
            requires_approval=False,
            result_summary="Report successfully generated",
        )
        sess.add(task)
        sess.commit()

    resp = client.get(f"/webhook/task/{test_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["task"]["id"] == test_id
    assert data["task"]["status"] == "COMPLETED"
    assert data["task"]["result_summary"] == "Report successfully generated"
    assert "artifacts" in data
    assert "steps_completed" in data


def test_webhook_task_sync_execution_and_callback(client, auth_headers):
    """Verify synchronous execution runs step, creates artifact, and invokes callback."""
    payload = {
        "prompt": "generate daily market brief for pre-market",
        "priority": "normal",
        "auto_approve": True,
        "sync_execute": True,
        "callback_url": "http://localhost:5678/webhook/test-callback",
    }

    with patch.object(N8nClient, "send_callback", return_value=True) as mock_callback:
        resp = client.post("/webhook/task", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("COMPLETED", "RUNNING", "VERIFYING")
        assert data["task_id"] is not None

        # Give background thread a moment to trigger callback
        mock_callback.assert_called_once()
        call_url, call_payload = mock_callback.call_args[0]
        assert call_url == "http://localhost:5678/webhook/test-callback"
        assert call_payload["task_id"] == data["task_id"]


def test_webhook_notify_persists_audit_log(client, auth_headers):
    """Verify /webhook/notify persists structured audit event."""
    notify_payload = {
        "event": "cron.daily_brief.fired",
        "source": "n8n_production",
        "data": {"run_id": "exec-999", "scheduled_ist": "08:30"},
    }
    resp = client.post("/webhook/notify", json=notify_payload, headers=auth_headers)
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["status"] == "RECEIVED"
    assert res_data["event"] == "cron.daily_brief.fired"

    factory = get_session_factory()
    with factory() as sess:
        audit = (
            sess.query(AuditEvent)
            .filter(AuditEvent.event_type == "WEBHOOK_NOTIFY:cron.daily_brief.fired")
            .first()
        )
        assert audit is not None
        assert audit.actor == "n8n_production"
        assert "exec-999" in audit.details_json


def test_n8n_workflow_json_files_contract():
    """Verify all 3 mandatory workflows exist, parse as valid JSON, and have proper structure."""
    workflow_dir = mp_settings.project_root / "workflows" / "n8n"
    required_workflows = [
        "MP-01-daily-market-brief.json",
        "MP-02-news-intelligence.json",
        "MP-03-on-demand-research.json",
    ]

    for fname in required_workflows:
        fpath = workflow_dir / fname
        assert fpath.exists(), f"Workflow file {fname} is missing"
        data = json.loads(fpath.read_text(encoding="utf-8"))
        assert "nodes" in data and len(data["nodes"]) >= 3
        assert "connections" in data

        # Check for presence of error handling or response nodes
        node_names = [n.get("name") for n in data["nodes"]]
        assert any("error" in n.lower() or "failure" in n.lower() or "respond" in n.lower() for n in node_names)

        # Ensure no hardcoded raw secret keys in the JSON
        raw_text = fpath.read_text(encoding="utf-8")
        assert "sk-" not in raw_text
        assert "personal-ai-secret-key" not in raw_text or fname == "example_workflow.json"


def test_schema_alias_flexibility(client, auth_headers):
    """Verify schemas accept both prompt/query and company_symbol/ticker seamlessly."""
    # ResearchJobSubmitRequest with prompt & company_symbol
    resp = client.post(
        "/api/v1/research/jobs",
        json={"prompt": "Deep dive research on Reliance Industries", "company_symbol": "RELIANCE"},
        headers=auth_headers,
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["query"] == "Deep dive research on Reliance Industries"
    assert data["ticker"] == "RELIANCE"

    # ArticleIngestRequest with single article payload directly
    unique_url = f"https://www.bseindia.com/ann/direct/{uuid.uuid4()}"
    single_art_resp = client.post(
        "/api/v1/articles/ingest",
        json={
            "title": f"Quarterly Performance {uuid.uuid4()}",
            "content": "The company reported 12% revenue growth YoY.",
            "url": unique_url,
            "source_id": "bse_disclosures",
        },
        headers=auth_headers,
    )
    assert single_art_resp.status_code == 200
    art_data = single_art_resp.json()
    assert (art_data["ingested_count"] + art_data["duplicates_skipped"]) >= 1
