"""Phase 5 Test Suite: Security Hardening & Financial Safety Verification.

Validates:
1. Permanent Trading Prohibition: ProhibitedActionError strictly raised on trading/order attempts.
2. RiskPolicyEngine interception of prohibited keywords in tool names and parameters.
3. Emergency Stop / Kill-Switch: Immediate task cancellation and persistent audit logging.
4. Credential & secret leak prevention on public endpoint responses.
5. Authentication enforcement for external callers in production mode.
"""

import uuid
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from marketpulse.api.app import app
from marketpulse.agent.permissions import RiskPolicyEngine, ProhibitedActionError
from marketpulse.agent.tools import FinancialOrderPlacementTool
from marketpulse.config import mp_settings
from marketpulse.storage.database import get_session_factory
from marketpulse.storage.models import AutomationTask, TaskStatus, AuditEvent


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {
        "X-API-Key": mp_settings.api_secret_key,
        "Content-Type": "application/json",
    }


def test_trading_prohibition_keywords():
    """Verify RiskPolicyEngine raises ProhibitedActionError on any trading keywords."""
    engine = RiskPolicyEngine()

    prohibited_cases = [
        ("place_order", {}),
        ("buy_shares", {"ticker": "RELIANCE", "qty": 10}),
        ("sell_shares", {"ticker": "TCS", "qty": 5}),
        ("transfer_funds", {"amount": 50000}),
        ("wire_transfer", {}),
        ("custom_tool", {"action": "execute_trade"}),
    ]

    for tool_name, params in prohibited_cases:
        with pytest.raises(ProhibitedActionError) as exc_info:
            engine.check_prohibited(tool_name, params)
        assert "permanently prohibited" in str(exc_info.value).lower()


def test_order_placement_tool_raises_prohibited_error():
    """Verify FinancialOrderPlacementTool unconditionally raises ProhibitedActionError."""
    tool = FinancialOrderPlacementTool()
    assert tool.name == "place_order"

    with pytest.raises(ProhibitedActionError) as exc_info:
        tool.execute(symbol="INFY", quantity=100)
    assert "permanently disabled" in str(exc_info.value).lower()


def test_emergency_stop_halts_active_tasks(client, auth_headers):
    """Verify emergency stop notification halts all active/pending tasks and logs audit event."""
    factory = get_session_factory()
    task_id = f"test-stop-{uuid.uuid4()}"

    with factory() as sess:
        t = AutomationTask(
            id=task_id,
            task_type="RESEARCH",
            prompt="Pre-stop running task",
            status=TaskStatus.RUNNING.value,
            step_limit=10,
            current_step=1,
            requires_approval=False,
            started_at=datetime.now(timezone.utc),
        )
        sess.add(t)
        sess.commit()

    # Trigger emergency stop via webhook/notify
    payload = {
        "event": "EMERGENCY_STOP_TRIGGERED",
        "source": "SecurityTestRunner",
        "data": {"reason": "Automated security test emergency halt"},
    }
    resp = client.post("/webhook/notify", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "RECEIVED"
    assert data["halted_tasks_count"] >= 1

    # Verify task status is now CANCELLED in DB
    with factory() as sess:
        updated_task = sess.query(AutomationTask).filter(AutomationTask.id == task_id).first()
        assert updated_task.status == TaskStatus.CANCELLED.value
        assert "emergency stop" in (updated_task.error_message or "").lower()

        # Verify AuditEvent recorded
        audit = sess.query(AuditEvent).filter(
            AuditEvent.event_type == "WEBHOOK_NOTIFY:EMERGENCY_STOP_TRIGGERED"
        ).first()
        assert audit is not None
        assert audit.actor == "SecurityTestRunner"


def test_no_secrets_leaked_in_health_response(client):
    """Verify public health response does not leak secret keys or passwords."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    text = resp.text

    assert mp_settings.api_secret_key not in text
    if mp_settings.n8n_api_key:
        assert mp_settings.n8n_api_key not in text


def test_auth_enforcement_in_production(client, monkeypatch):
    """Verify unauthenticated external callers receive 401 or 403 in production."""
    monkeypatch.setattr(mp_settings, "environment", "production")

    # Call with missing auth headers
    missing_headers = {"Sec-Fetch-Site": "cross-site"}
    resp_missing = client.post("/api/v1/webhook/task", json={"prompt": "Unauthorized test"}, headers=missing_headers)
    assert resp_missing.status_code == 401
    assert "Missing required X-API-Key" in resp_missing.json()["detail"]

    # Call with invalid key
    bad_headers = {
        "X-API-Key": "completely-invalid-key-token",
        "Sec-Fetch-Site": "cross-site",
    }
    resp_bad = client.post("/api/v1/webhook/task", json={"prompt": "Unauthorized test"}, headers=bad_headers)
    assert resp_bad.status_code == 403
    assert "Invalid API key" in resp_bad.json()["detail"]
