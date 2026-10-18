"""Unit tests for Phase 6: Desktop & Cloud Operation, Emergency Stop, and Mode Isolation."""

import pytest
from unittest.mock import MagicMock, patch
from click.testing import CliRunner

from marketpulse.config import MarketPulseSettings, mp_settings
from marketpulse.agent.security import (
    EmergencyStopManager,
    EmergencyStopActiveError,
    OperatingModeError,
    check_operating_mode_capability,
    emergency_stop,
)
from marketpulse.agent.tools import (
    MarketPulseToolRegistry,
    DesktopScreenshotTool,
    DesktopActiveWindowTool,
    CollectSourceEvidenceTool,
)
from marketpulse.agent.orchestrator import TaskOrchestrator
from marketpulse.storage.database import get_session, init_db
from marketpulse.storage.models import AutomationTask, AuditEvent, TaskStatus
from marketpulse.cli import cli


@pytest.fixture(autouse=True)
def clean_emergency_stop():
    """Ensure emergency stop is reset before and after every test."""
    emergency_stop.reset()
    yield
    emergency_stop.reset()


def test_emergency_stop_trigger_and_reset(tmp_path):
    """Test emergency stop trigger and reset lifecycle."""
    mgr = EmergencyStopManager()
    mgr.reset()
    assert not mgr.is_stopped

    mgr.trigger("Test security halt")
    assert mgr.is_stopped
    assert "Test security halt" in mgr.stop_reason

    mgr.reset()
    assert not mgr.is_stopped


def test_operating_mode_capability_enforcement():
    """Test that cloud mode forbids desktop tools while desktop mode allows them."""
    # Desktop mode allows both desktop and general tools
    check_operating_mode_capability("desktop_screenshot", active_mode="desktop", supported_modes=["desktop"])
    check_operating_mode_capability("collect_source_evidence", active_mode="desktop", supported_modes=["desktop", "cloud"])

    # Cloud mode allows general tools
    check_operating_mode_capability("collect_source_evidence", active_mode="cloud", supported_modes=["desktop", "cloud"])

    # Cloud mode rejects desktop-only tools
    with pytest.raises(OperatingModeError) as exc_info:
        check_operating_mode_capability("desktop_screenshot", active_mode="cloud", supported_modes=["desktop"])
    assert "not supported in 'cloud' mode" in str(exc_info.value)


def test_orchestrator_halts_on_emergency_stop():
    """Test that the orchestrator rejects step execution when emergency stop is active."""
    init_db()
    with get_session() as session:
        orchestrator = TaskOrchestrator(session=session)
        task = orchestrator.submit_task("Analyze NIFTY index movements")
        session.commit()

        # Trigger emergency stop
        emergency_stop.trigger("Operator panic button pressed")

        with pytest.raises(EmergencyStopActiveError) as exc_info:
            orchestrator.execute_step(
                task_id=task.id,
                tool_name="collect_source_evidence",
                params={"source_id": "permitted_financial_rss"},
            )
        assert "halted by Emergency Stop" in str(exc_info.value)

        # Verify task transitioned to CANCELLED and audit event logged
        updated_task = session.query(AutomationTask).filter_by(id=task.id).first()
        assert updated_task.status == TaskStatus.CANCELLED.value
        assert "Emergency stop" in updated_task.cancellation_reason

        audit_entry = (
            session.query(AuditEvent)
            .filter_by(entity_id=task.id, event_type="TASK_EMERGENCY_STOPPED")
            .first()
        )
        assert audit_entry is not None
        assert "Operator panic button pressed" in audit_entry.details_json


def test_orchestrator_enforces_operating_mode_in_cloud():
    """Test that running a desktop tool in cloud mode triggers audit event and fails task."""
    init_db()
    with get_session() as session:
        orchestrator = TaskOrchestrator(session=session)
        task = orchestrator.submit_task("Take desktop screenshot")
        session.commit()

        # Simulate cloud operating mode
        with patch.object(mp_settings, "operating_mode", "cloud"):
            with pytest.raises(OperatingModeError):
                orchestrator.execute_step(
                    task_id=task.id,
                    tool_name="desktop_screenshot",
                    params={},
                )

        updated_task = session.query(AutomationTask).filter_by(id=task.id).first()
        assert updated_task.status == TaskStatus.FAILED.value
        assert "not supported in 'cloud' mode" in updated_task.error_message

        audit = (
            session.query(AuditEvent)
            .filter_by(entity_id=task.id, event_type="OPERATING_MODE_VIOLATION")
            .first()
        )
        assert audit is not None


def test_desktop_screenshot_tool_execution(tmp_path):
    """Test DesktopScreenshotTool executes and returns artifact path."""
    import personal_ai.tools.desktop
    tool = DesktopScreenshotTool()
    assert tool.supported_modes == ["desktop"]

    mock_path = tmp_path / "screenshot.png"
    mock_path.write_text("fake image content")
    mock_res = {"file_path": str(mock_path), "artifact_id": "art-123"}

    with patch("personal_ai.tools.desktop.capture_desktop_screenshot", return_value=mock_res):
        res = tool.execute(artifact_name="test_screen.png")
        assert res["status"] == "SUCCESS"
        assert res["artifact_path"] == str(mock_path)


def test_desktop_active_window_tool_execution():
    """Test DesktopActiveWindowTool inspects active window information."""
    import personal_ai.tools.desktop
    tool = DesktopActiveWindowTool()
    assert tool.supported_modes == ["desktop"]

    mock_info = {
        "title": "MarketPulse AI - Visual Studio Code",
        "process_name": "Code.exe",
        "rect": {"left": 0, "top": 0, "right": 1920, "bottom": 1080},
    }

    with patch("personal_ai.tools.desktop.get_active_window_info", return_value=mock_info):
        res = tool.execute()
        assert res["status"] == "SUCCESS"
        assert res["window_info"]["title"] == "MarketPulse AI - Visual Studio Code"


def test_cli_emergency_stop_and_reset_commands():
    """Test CLI emergency-stop and reset-stop execution."""
    runner = CliRunner()

    # Trigger via CLI
    res = runner.invoke(cli, ["emergency-stop", "--reason", "Automated test pause"])
    assert res.exit_code == 0
    assert "EMERGENCY STOP ACTIVATED" in res.output
    assert emergency_stop.is_stopped

    # Reset via CLI
    res2 = runner.invoke(cli, ["reset-stop"])
    assert res2.exit_code == 0
    assert "Emergency stop has been CLEARED" in res2.output
    assert not emergency_stop.is_stopped


def test_cloud_database_configuration_parsing():
    """Test that MarketPulseSettings handles PostgreSQL connection strings."""
    settings = MarketPulseSettings(
        operating_mode="cloud",
        database_url="postgresql://mp_user:mp_pass@db.example.com:5432/marketpulse_prod",
    )
    assert settings.operating_mode == "cloud"
    assert "postgresql" in settings.database_url
    summary = settings.get_sanitized_summary()
    assert summary["database_url_type"] == "postgresql"
    assert summary["operating_mode"] == "cloud"
