"""Unit tests for Phase 8 Web Dashboard and Control Center."""

import socket
import time
from typing import Generator
import httpx
import pytest

from personal_ai.workflows.server import PersonalAIWebhookServer


def get_free_port() -> int:
    """Find a dynamically available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def dashboard_server() -> Generator[str, None, None]:
    """Start test dashboard server on a free port in a background thread."""
    port = get_free_port()
    host = "127.0.0.1"
    server = PersonalAIWebhookServer(host=host, port=port)
    server.start(block=False)

    base_url = f"http://{host}:{port}"

    healthy = False
    for _ in range(20):
        try:
            r = httpx.get(f"{base_url}/health", timeout=1.0)
            if r.status_code == 200:
                healthy = True
                break
        except Exception:
            time.sleep(0.05)

    assert healthy, "Dashboard server failed to start"
    yield base_url

    server.stop()


def test_dashboard_index_served(dashboard_server: str):
    """Verify that root / serves the dashboard HTML with correct title and elements."""
    resp = httpx.get(f"{dashboard_server}/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Personal AI Automation Dashboard" in resp.text
    assert "id=\"nav-tasks\"" in resp.text
    assert "id=\"nav-approvals\"" in resp.text
    assert "id=\"nav-artifacts\"" in resp.text
    assert "id=\"nav-clipboard\"" in resp.text
    assert "id=\"nav-desktop\"" in resp.text


def test_dashboard_static_css_and_js(dashboard_server: str):
    """Verify that CSS and JavaScript static assets are served properly."""
    # CSS
    css_resp = httpx.get(f"{dashboard_server}/static/style.css")
    assert css_resp.status_code == 200
    assert "text/css" in css_resp.headers["content-type"]
    assert "--bg-deep" in css_resp.text

    # JS
    js_resp = httpx.get(f"{dashboard_server}/static/app.js")
    assert js_resp.status_code == 200
    assert "javascript" in js_resp.headers["content-type"]
    assert "Personal AI" in js_resp.text


def test_dashboard_api_tasks(dashboard_server: str):
    """Verify tasks API list endpoint returns tasks."""
    resp = httpx.get(f"{dashboard_server}/api/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_dashboard_api_run_task(dashboard_server: str):
    """Verify triggering a task from the dashboard runner API."""
    payload = {
        "prompt": "read file 'README.md'",
        "auto_approve": True,
    }
    resp = httpx.post(f"{dashboard_server}/api/tasks/run", json=payload, timeout=15.0)
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data
    assert data["status"].upper() == "COMPLETED"


def test_dashboard_api_approvals(dashboard_server: str):
    """Verify approvals API endpoint returns list."""
    resp = httpx.get(f"{dashboard_server}/api/approvals")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_dashboard_api_artifacts(dashboard_server: str):
    """Verify artifacts API endpoint returns list."""
    resp = httpx.get(f"{dashboard_server}/api/artifacts")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_dashboard_api_clipboard(dashboard_server: str):
    """Verify clipboard API endpoint returns history."""
    resp = httpx.get(f"{dashboard_server}/api/clipboard")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_dashboard_api_desktop_screen(dashboard_server: str):
    """Verify desktop screen API endpoint returns resolution and active window."""
    resp = httpx.get(f"{dashboard_server}/api/desktop/screen")
    assert resp.status_code == 200
    data = resp.json()
    assert "screen_width" in data
    assert "screen_height" in data
    assert data["screen_width"] > 0
    assert data["screen_height"] > 0


def test_dashboard_api_desktop_windows(dashboard_server: str):
    """Verify desktop windows API endpoint lists visible windows."""
    resp = httpx.get(f"{dashboard_server}/api/desktop/windows")
    assert resp.status_code == 200
    windows = resp.json()
    assert isinstance(windows, list)


def test_dashboard_api_settings_and_logs(dashboard_server: str):
    """Verify settings and logs API endpoints."""
    # Settings
    set_resp = httpx.get(f"{dashboard_server}/api/settings")
    assert set_resp.status_code == 200
    settings_data = set_resp.json()
    assert "approval_mode" in settings_data
    assert "database_path" in settings_data

    # Logs
    log_resp = httpx.get(f"{dashboard_server}/api/logs")
    assert log_resp.status_code == 200
    assert "logs" in log_resp.json()
