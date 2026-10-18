"""Unit and contract tests for Phase 1 — Real Connectivity and Production Health."""

from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import pytest

from marketpulse.api.app import app
from marketpulse.config import mp_settings
from marketpulse.n8n.client import N8nClient
from marketpulse.n8n.models import ConnectionState, ConnectionTestResult


@pytest.fixture
def client():
    return TestClient(app)


def test_health_endpoint_truthful_n8n_and_db_states(client):
    """Verify /health reflects real underlying states instead of hardcoded or optimistic labels."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] in ("HEALTHY", "DEGRADED")
    assert "database" in data
    assert "n8n_status" in data
    assert "desktop_agent_online" in data
    assert "timestamp" in data

    # When operating mode is desktop, desktop_agent_online is True; in cloud mode it is False
    if data["mode"] == "cloud":
        assert data["desktop_agent_online"] is False
    elif data["mode"] == "desktop":
        assert data["desktop_agent_online"] is True


def test_health_endpoint_reports_n8n_latency_and_message(client):
    """Verify /health includes n8n latency and diagnostic message when available."""
    mock_result = ConnectionTestResult(
        state=ConnectionState.CONNECTED,
        status_code=200,
        message="n8n REST API authenticated successfully",
        latency_ms=18.5,
        checked_at="2026-10-18T12:00:00Z",
    )
    with patch.object(N8nClient, "test_connection", return_value=mock_result):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["n8n_status"] == "CONNECTED"
        assert data["n8n_latency_ms"] == 18.5
        assert "authenticated" in data["n8n_message"]


def test_readiness_probe_contract(client):
    """Verify /ready verifies critical dependencies and returns boolean checklist."""
    resp = client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is True
    assert data["checks"]["database"] is True
    assert data["checks"]["artifacts_store"] is True


def test_cors_origins_includes_production_domain():
    """Verify CORS configuration includes production Vercel domain and env additions."""
    origins = mp_settings.allowed_cors_origins
    assert "https://agent-pi-silk.vercel.app" in origins
    assert "http://localhost:8001" in origins

    # Test custom CORS_ORIGINS override
    with patch.dict("os.environ", {"CORS_ORIGINS": "https://custom-partner.com,https://api.partner.com"}):
        custom_origins = mp_settings.allowed_cors_origins
        assert "https://custom-partner.com" in custom_origins
        assert "https://api.partner.com" in custom_origins


def test_production_auth_rejection_for_external_callers(client):
    """Verify external callers without valid credentials in production are rejected with 401."""
    with patch.object(mp_settings, "environment", "production"):
        resp = client.post("/api/v1/webhook/task", json={"prompt": "Analyze Reliance"})
        assert resp.status_code == 401
        assert "Missing required X-API-Key header" in resp.json()["detail"]


def test_same_origin_browser_access_permitted(client):
    """Verify same-origin browser requests with sec-fetch-site are admitted."""
    with patch.object(mp_settings, "environment", "production"):
        resp = client.get("/api/v1/health", headers={"sec-fetch-site": "same-origin"})
        assert resp.status_code == 200


def test_cloud_mode_prohibits_desktop_inspection():
    """Verify desktop window inspection and screenshots are prohibited in cloud mode."""
    from marketpulse.agent.tools import DesktopScreenshotTool, DesktopActiveWindowTool
    from marketpulse.agent.security import check_operating_mode_capability, OperatingModeError

    with patch.object(mp_settings, "operating_mode", "cloud"):
        with pytest.raises(OperatingModeError) as exc_info:
            check_operating_mode_capability("desktop_screenshot", supported_modes=DesktopScreenshotTool.supported_modes)
        assert "is not supported in 'cloud' mode" in str(exc_info.value)

        with pytest.raises(OperatingModeError) as exc_info:
            check_operating_mode_capability("desktop_active_window", supported_modes=DesktopActiveWindowTool.supported_modes)
        assert "is not supported in 'cloud' mode" in str(exc_info.value)
