"""Unit tests for Phase 7 Webhook Server and n8n Workflow Integration."""

import socket
import time
from typing import Generator
import httpx
import pytest

from personal_ai.config import settings
from personal_ai.workflows.server import PersonalAIWebhookServer
from personal_ai.workflows.client import N8nWebhookClient
from personal_ai.workflows.models import StatusCallbackPayload


def get_free_port() -> int:
    """Find a dynamically available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def webhook_server() -> Generator[str, None, None]:
    """Start test webhook server on a free port in a background thread."""
    port = get_free_port()
    host = "127.0.0.1"
    server = PersonalAIWebhookServer(host=host, port=port)
    server.start(block=False)

    base_url = f"http://{host}:{port}"

    # Wait for server to become responsive
    healthy = False
    for _ in range(20):
        try:
            r = httpx.get(f"{base_url}/health", timeout=1.0)
            if r.status_code == 200:
                healthy = True
                break
        except Exception:
            time.sleep(0.05)

    assert healthy, "Webhook test server failed to start"
    yield base_url

    server.stop()


def test_health_endpoint(webhook_server: str):
    """Verify /health is accessible without authentication."""
    resp = httpx.get(f"{webhook_server}/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert "version" in data


def test_auth_rejection(webhook_server: str):
    """Verify unauthorized requests are rejected with 401."""
    # No header
    resp = httpx.post(f"{webhook_server}/webhook/task", json={"prompt": "read file 'README.md'"})
    assert resp.status_code == 401

    # Invalid header
    resp = httpx.post(
        f"{webhook_server}/webhook/task",
        headers={"X-API-Key": "wrong-secret-key"},
        json={"prompt": "read file 'README.md'"},
    )
    assert resp.status_code == 401


def test_payload_validation(webhook_server: str):
    """Verify malformed or empty payloads return 400 Bad Request."""
    headers = {"X-API-Key": settings.webhook_api_key}

    # Empty prompt
    resp = httpx.post(f"{webhook_server}/webhook/task", headers=headers, json={"prompt": ""})
    assert resp.status_code == 400

    # Missing prompt
    resp = httpx.post(f"{webhook_server}/webhook/task", headers=headers, json={"auto_approve": True})
    assert resp.status_code == 400


def test_successful_task_execution(webhook_server: str):
    """Verify valid task trigger runs and returns completed execution report."""
    headers = {"X-API-Key": settings.webhook_api_key}
    payload = {
        "prompt": "read file 'README.md'",
        "auto_approve": True,
        "priority": "high",
    }

    resp = httpx.post(f"{webhook_server}/webhook/task", headers=headers, json=payload, timeout=15.0)
    assert resp.status_code == 200
    data = resp.json()

    assert "task_id" in data
    assert data["status"].upper() == "COMPLETED"
    assert "plan" in data
    assert data["report"]["steps_completed"] >= 1

    # Verify task can be retrieved via GET /webhook/task/{task_id}
    task_id = data["task_id"]
    get_resp = httpx.get(f"{webhook_server}/webhook/task/{task_id}", headers=headers)
    assert get_resp.status_code == 200
    task_details = get_resp.json()
    assert task_details["task"]["id"] == task_id
    assert len(task_details["steps"]) >= 1


def test_get_nonexistent_task(webhook_server: str):
    """Verify 404 for unknown task ID."""
    headers = {"X-API-Key": settings.webhook_api_key}
    resp = httpx.get(f"{webhook_server}/webhook/task/nonexistent-uuid-1234", headers=headers)
    assert resp.status_code == 404


def test_notify_endpoint(webhook_server: str):
    """Verify notification webhook accepts events from external engines."""
    headers = {"X-API-Key": settings.webhook_api_key}
    payload = {
        "event": "cron.triggered",
        "source": "n8n",
        "data": {"schedule": "0 9 * * *"},
    }

    resp = httpx.post(f"{webhook_server}/webhook/notify", headers=headers, json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "received"
    assert data["event"] == "cron.triggered"


def test_client_send_callback_retry():
    """Verify N8nWebhookClient handles network retries gracefully."""
    client = N8nWebhookClient(api_key="test-key", timeout=0.5)
    payload = StatusCallbackPayload(
        task_id="test-id",
        status="completed",
        summary="Test summary",
        completed_steps=1,
        total_steps=1,
    )

    # Point to an unreachable address to verify retry behavior without raising unhandled exceptions
    success = client.send_callback(
        callback_url="http://127.0.0.1:59999/unreachable",
        payload=payload,
        max_retries=2,
    )
    assert success is False
