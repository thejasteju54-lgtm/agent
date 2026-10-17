"""Unit tests for production-grade n8n REST API and Webhook client."""

import pytest
import httpx
from marketpulse.n8n.client import N8nClient, _sanitize_error
from marketpulse.n8n.models import ConnectionState


def test_sanitize_error_redacts_keys():
    """Verify long high-entropy tokens and keys are redacted from error traces."""
    raw = "Failed with token secret_n8n_api_key_1234567890abcdef and basic auth"
    clean = _sanitize_error(raw)
    assert "secret_n8n_api_key_1234567890abcdef" not in clean
    assert "***REDACTED***" in clean


def test_n8n_client_misconfigured_url():
    """Verify invalid base URL is classified as MISCONFIGURED."""
    client = N8nClient(base_url="not_a_valid_url", api_key="test-key")
    result = client.test_connection()
    assert result.state == ConnectionState.MISCONFIGURED
    assert "Invalid n8n base URL" in result.message


def test_n8n_client_missing_api_key():
    """Verify missing API key produces UNAUTHORIZED or DISCONNECTED status."""
    client = N8nClient(base_url="http://127.0.0.1:5678", api_key=None, timeout_seconds=0.5)
    # When server is down, it reports DISCONNECTED with missing key note
    result = client.test_connection()
    assert result.state in (ConnectionState.UNAUTHORIZED, ConnectionState.DISCONNECTED)


def test_n8n_client_offline_server_returns_disconnected():
    """Verify offline port reports DISCONNECTED cleanly without uncaught crash."""
    # Use non-existent port
    client = N8nClient(base_url="http://127.0.0.1:59999", api_key="test-key", timeout_seconds=0.5, max_retries=1)
    result = client.test_connection()
    assert result.state == ConnectionState.DISCONNECTED
    assert (
        "Connection refused" in result.message
        or "Connection timed out" in result.message
        or "Failed to communicate" in result.message
    )


def test_n8n_client_authenticated_mock(monkeypatch):
    """Verify mock 200 response yields CONNECTED state with workflow count."""
    def mock_get(self, url, headers=None, **kwargs):
        if "/api/v1/workflows" in str(url):
            return httpx.Response(
                200,
                json={"data": [{"id": "wf-1", "name": "MP-01 Daily Brief", "active": True}]},
                request=httpx.Request("GET", url),
            )
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    client = N8nClient(base_url="http://localhost:5678", api_key="valid-key")
    result = client.test_connection()

    assert result.state == ConnectionState.CONNECTED
    assert result.status_code == 200
    assert result.workflow_count == 1
    assert "Successfully authenticated" in result.message


def test_n8n_client_unauthorized_mock(monkeypatch):
    """Verify mock 401 response yields UNAUTHORIZED state."""
    def mock_get(self, url, headers=None, **kwargs):
        return httpx.Response(401, text="Unauthorized: Invalid API key", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    client = N8nClient(base_url="http://localhost:5678", api_key="invalid-key")
    result = client.test_connection()

    assert result.state == ConnectionState.UNAUTHORIZED
    assert result.status_code == 401
    assert "Authentication failed" in result.message


def test_n8n_list_workflows_parsing(monkeypatch):
    """Verify list_workflows parses data array into WorkflowSummary models."""
    def mock_get(self, url, headers=None, **kwargs):
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "1", "name": "MP-01", "active": True, "tags": [{"name": "finance"}]},
                    {"id": "2", "name": "MP-02", "active": False, "tags": ["news"]},
                ]
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    client = N8nClient(base_url="http://localhost:5678", api_key="key")
    workflows = client.list_workflows()

    assert len(workflows) == 2
    assert workflows[0].id == "1"
    assert workflows[0].name == "MP-01"
    assert workflows[0].active is True
    assert workflows[0].tags == ["finance"]
    assert workflows[1].active is False
    assert workflows[1].tags == ["news"]


def test_n8n_get_execution_parsing(monkeypatch):
    """Verify get_execution parses ExecutionSummary."""
    def mock_get(self, url, headers=None, **kwargs):
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "exec-101",
                    "workflowId": "wf-1",
                    "status": "success",
                    "startedAt": "2026-10-17T12:00:00Z",
                    "finished": True,
                    "mode": "webhook",
                }
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    client = N8nClient(base_url="http://localhost:5678", api_key="key")
    execution = client.get_execution("exec-101")

    assert execution is not None
    assert execution.id == "exec-101"
    assert execution.workflow_id == "wf-1"
    assert execution.status == "success"
    assert execution.finished is True


def test_n8n_trigger_webhook_success(monkeypatch):
    """Verify trigger_webhook attaches correlation ID and returns WebhookTriggerResult."""
    def mock_post(self, url, headers=None, json=None, **kwargs):
        assert json is not None
        assert json.get("correlation_id") == "test-corr-123"
        return httpx.Response(
            200,
            json={"status": "success", "echo": json},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    client = N8nClient(base_url="http://localhost:5678", api_key="key")
    res = client.trigger_webhook(
        webhook_path="/webhook/marketpulse-test",
        payload={"ticker": "RELIANCE"},
        correlation_id="test-corr-123",
    )

    assert res.success is True
    assert res.status_code == 200
    assert res.correlation_id == "test-corr-123"
    assert res.data["status"] == "success"


def test_n8n_auth_failure_does_not_retry_indefinitely(monkeypatch):
    """Verify 401 client error immediately returns without burning retry attempts."""
    call_count = 0

    def mock_get(self, url, headers=None, **kwargs):
        nonlocal call_count
        call_count += 1
        return httpx.Response(401, text="Unauthorized", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    client = N8nClient(base_url="http://localhost:5678", api_key="bad-key", max_retries=3)
    with pytest.raises(PermissionError, match="Unauthorized"):
        client.list_workflows()

    # Must only have called once (no retries on 401)
    assert call_count == 1
