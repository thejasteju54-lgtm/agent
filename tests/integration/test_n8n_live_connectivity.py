"""Integration tests for live n8n instance connectivity and workflow execution.

These tests attempt real network calls to the configured n8n instance.
If the n8n instance is offline or credentials are not configured, tests skip
with explicit diagnostics detailing the required manual setup steps.
"""

import os
import pytest
from marketpulse.config import mp_settings
from marketpulse.n8n.client import N8nClient
from marketpulse.n8n.models import ConnectionState


@pytest.fixture
def live_client():
    return N8nClient(
        base_url=mp_settings.n8n_base_url,
        api_key=mp_settings.n8n_api_key,
        timeout_seconds=3.0,
    )


def test_live_n8n_connection_check(live_client: N8nClient):
    """Test actual connectivity against configured n8n instance.

    Reports live state or skips with explicit instructions if not running.
    """
    result = live_client.test_connection()

    if result.state == ConnectionState.DISCONNECTED:
        pytest.skip(
            f"Live n8n instance is currently offline at {live_client.base_url}.\n"
            "MANUAL ACTION REQUIRED TO CONNECT:\n"
            "  1. Start Docker Desktop and run: docker compose -f workflows/n8n/docker-compose.yml up -d\n"
            "  2. Or run via npx: npx n8n\n"
            "  3. Open http://localhost:5678, generate an API Key in Settings > n8n API, and set N8N_API_KEY in .env."
        )

    if result.state == ConnectionState.UNAUTHORIZED:
        # If API key is missing, verify that this is accurately reported
        assert result.status_code is not None or "N8N_API_KEY" in result.message
        pytest.skip(
            "n8n instance is reachable, but N8N_API_KEY is missing or invalid.\n"
            "MANUAL ACTION REQUIRED:\n"
            "  1. Open http://localhost:5678 > Settings > n8n API\n"
            "  2. Generate an API Key and set N8N_API_KEY=<your_key> in .env."
        )

    assert result.state == ConnectionState.CONNECTED
    assert result.status_code == 200
    assert result.workflow_count is not None


def test_live_n8n_invalid_api_key_rejection():
    """Verify that an explicitly bogus API key against a live instance produces UNAUTHORIZED."""
    client = N8nClient(
        base_url=mp_settings.n8n_base_url,
        api_key="totally_invalid_bogus_key_12345",
        timeout_seconds=3.0,
        max_retries=1,
    )
    result = client.test_connection()

    if result.state == ConnectionState.DISCONNECTED:
        pytest.skip("Live n8n instance is offline; cannot verify real 401 response against live server.")

    assert result.state == ConnectionState.UNAUTHORIZED
    assert result.status_code in (401, 403)
