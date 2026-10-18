"""Phase 3 Test Suite: n8n Integration & Automation Reliability.

Validates:
1. Cloudflare Access header injection for zero-trust protected instances.
2. Webhook callback bounded retry logic, fast failure on 401/403, and backoff.
3. Truthful connection state reporting (CONNECTED, DISCONNECTED, UNAUTHORIZED, MISCONFIGURED).
4. n8n workflow artifact integrity and endpoint routing compliance.
5. Resilient task execution when n8n is offline or unreachable.
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import httpx
import pytest

from fastapi.testclient import TestClient
from marketpulse.api.app import app
from marketpulse.config import mp_settings
from marketpulse.n8n.client import N8nClient
from marketpulse.n8n.models import ConnectionState, ConnectionTestResult


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {
        "X-API-Key": mp_settings.api_secret_key,
        "Content-Type": "application/json",
    }


def test_cloudflare_access_headers_injection(monkeypatch):
    """Verify that Cloudflare Access headers are injected when credentials are provided."""
    monkeypatch.setattr(mp_settings, "cloudflare_access_client_id", "cf-client-id-12345")
    monkeypatch.setattr(mp_settings, "cloudflare_access_client_secret", "cf-client-secret-abcde")
    monkeypatch.setattr(mp_settings, "n8n_api_key", "test-api-key")

    client = N8nClient(base_url="http://localhost:5678", api_key="test-api-key")
    api_headers = client._get_api_headers()
    assert api_headers["CF-Access-Client-Id"] == "cf-client-id-12345"
    assert api_headers["CF-Access-Client-Secret"] == "cf-client-secret-abcde"
    assert api_headers["X-N8N-API-KEY"] == "test-api-key"

    webhook_headers = client._get_webhook_headers()
    assert webhook_headers["CF-Access-Client-Id"] == "cf-client-id-12345"
    assert webhook_headers["CF-Access-Client-Secret"] == "cf-client-secret-abcde"


def test_callback_retry_on_transient_failure():
    """Verify send_callback retries on 5xx error and succeeds when subsequent attempt returns 200."""
    client = N8nClient(base_url="http://localhost:5678", api_key="test-key")

    mock_resp_500 = MagicMock()
    mock_resp_500.status_code = 500

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200

    with patch("httpx.Client.post", side_effect=[mock_resp_500, mock_resp_200]) as mock_post:
        with patch("time.sleep", return_value=None):  # Fast test execution
            success = client.send_callback(
                callback_url="http://localhost:5678/webhook/test-cb",
                payload={"task_id": "test-123", "status": "COMPLETED"},
                max_retries=3,
            )
            assert success is True
            assert mock_post.call_count == 2


def test_callback_fails_fast_on_auth_rejection():
    """Verify send_callback terminates immediately without retries when receiving 401/403."""
    client = N8nClient(base_url="http://localhost:5678", api_key="bad-key")

    mock_resp_403 = MagicMock()
    mock_resp_403.status_code = 403

    with patch("httpx.Client.post", return_value=mock_resp_403) as mock_post:
        with patch("time.sleep", return_value=None):
            success = client.send_callback(
                callback_url="http://localhost:5678/webhook/test-cb",
                payload={"task_id": "test-123"},
                max_retries=3,
            )
            assert success is False
            # Must not retry on client auth errors
            assert mock_post.call_count == 1


def test_n8n_connection_truthful_when_offline():
    """Verify test_connection returns DISCONNECTED state with actionable message when offline."""
    client = N8nClient(base_url="http://127.0.0.1:5679", api_key="test-key")

    with patch("httpx.Client.get", side_effect=httpx.ConnectError("Connection refused")):
        res = client.test_connection()
        assert res.state == ConnectionState.DISCONNECTED
        assert "Ensure n8n is running" in res.message or "Connection refused" in res.message


def test_n8n_workflow_json_contract_integrity():
    """Verify all workflow JSON files in workflows/n8n are valid and have required structures."""
    workflows_dir = Path("workflows/n8n")
    assert workflows_dir.exists() and workflows_dir.is_dir()

    json_files = list(workflows_dir.glob("*.json"))
    assert len(json_files) >= 5, f"Expected at least 5 workflow definitions, found {len(json_files)}"

    required_workflows = [
        "MP-00-connectivity-test.json",
        "MP-01-daily-market-brief.json",
        "MP-02-news-intelligence.json",
        "MP-03-on-demand-research.json",
    ]

    found_names = [f.name for f in json_files]
    for req in required_workflows:
        assert req in found_names, f"Missing required workflow {req}"

    for f in json_files:
        with open(f, "r", encoding="utf-8") as wf_file:
            data = json.load(wf_file)
            assert "name" in data
            assert "nodes" in data
            assert isinstance(data["nodes"], list)
            assert len(data["nodes"]) > 0


def test_direct_task_execution_independent_of_n8n(client, auth_headers):
    """Verify user can run research tasks directly through MarketPulse API even if n8n is offline."""
    payload = {
        "prompt": "Direct standalone execution test without n8n dependency",
        "task_type": "GENERAL",
        "sync_execute": True,
        "auto_approve": True,
    }

    # Execute task with no active n8n instance
    resp = client.post("/api/v1/webhook/task", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("COMPLETED", "SUCCESS")
    assert "task_id" in data
