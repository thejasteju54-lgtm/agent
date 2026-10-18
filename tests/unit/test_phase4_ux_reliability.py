"""Phase 4 Test Suite: UX Redesign & Institutional Frontend Reliability.

Validates:
1. Static web asset serving (index.html, style.css, app.js) via FastAPI.
2. Complete elimination of blocking browser alert(), confirm(), and prompt() dialogs.
3. DOM presence of institutional components: Toast container, Confirmation modal, Diagnostics card.
4. Health endpoint payload contract alignment with frontend diagnostics engine.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from marketpulse.api.app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_dashboard_static_assets_served(client):
    """Verify that root HTML, CSS, and JS assets are served with HTTP 200."""
    html_resp = client.get("/")
    assert html_resp.status_code == 200
    assert "MarketPulse AI" in html_resp.text
    assert "text/html" in html_resp.headers["content-type"]

    css_resp = client.get("/static/style.css")
    assert css_resp.status_code == 200
    assert "--bg-deep" in css_resp.text
    assert "#toast-container" in css_resp.text

    js_resp = client.get("/static/app.js")
    assert js_resp.status_code == 200
    assert "showToast" in js_resp.text
    assert "showConfirmModal" in js_resp.text


def test_no_blocking_browser_dialogs_in_frontend_code():
    """Verify app.js does not contain blocking alert(), confirm(), or prompt() calls."""
    js_path = Path("src/marketpulse/dashboard/static/app.js")
    assert js_path.exists()
    content = js_path.read_text(encoding="utf-8")

    # Ensure no window/browser blocking dialogs
    assert "alert(" not in content, "Found blocking alert() in app.js"
    assert "confirm(" not in content, "Found blocking confirm() in app.js"
    assert "prompt(" not in content, "Found blocking prompt() in app.js"


def test_dom_markup_has_institutional_ux_elements(client):
    """Verify index.html contains essential institutional components."""
    html_resp = client.get("/")
    html = html_resp.text

    assert 'id="toast-container"' in html
    assert 'id="confirm-modal"' in html
    assert 'id="system-diagnostics-card"' in html
    assert 'id="diagnostics-guidance-content"' in html
    assert 'id="header-ist-time"' in html
    assert 'id="btn-emergency-stop"' in html


def test_health_response_contract_for_diagnostics_panel(client):
    """Verify /health supplies all fields required for the live diagnostics panel."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()

    assert "status" in data
    assert "database_connected" in data
    assert "n8n_status" in data
    assert "mode" in data
    assert "desktop_agent_online" in data
    assert "timestamp" in data
