"""Unit tests for Phase 6 Windows Desktop Automation."""

from pathlib import Path
import pytest

from personal_ai.agent.task_models import RiskLevel
from personal_ai.agent.verification import StepVerifier
from personal_ai.agent.planner import TaskPlanner
from personal_ai.tools.registry import default_registry
from personal_ai.tools.desktop import (
    get_screen_resolution,
    validate_screen_coordinates,
    get_active_window_info,
    list_open_windows,
    capture_desktop_screenshot,
    desktop_mouse_click,
    desktop_press_hotkey,
)


def test_screen_resolution():
    """Verify that screen resolution returns positive integers."""
    width, height = get_screen_resolution()
    assert isinstance(width, int) and width > 0
    assert isinstance(height, int) and height > 0


def test_validate_screen_coordinates():
    """Verify boundary checking prevents out-of-bounds clicks."""
    width, height = get_screen_resolution()
    
    # Valid coordinates
    x, y = validate_screen_coordinates(0, 0)
    assert (x, y) == (0, 0)
    
    x, y = validate_screen_coordinates(width - 1, height - 1)
    assert (x, y) == (width - 1, height - 1)

    # Invalid coordinates
    with pytest.raises(ValueError, match="outside screen bounds"):
        validate_screen_coordinates(-1, 50)

    with pytest.raises(ValueError, match="outside screen bounds"):
        validate_screen_coordinates(50, -1)

    with pytest.raises(ValueError, match="outside screen bounds"):
        validate_screen_coordinates(width + 100, 50)

    with pytest.raises(ValueError, match="outside screen bounds"):
        validate_screen_coordinates(50, height + 100)


def test_get_active_window_info():
    """Verify active foreground window information structure."""
    info = get_active_window_info()
    assert isinstance(info, dict)
    assert "hwnd" in info
    assert "title" in info
    assert "left" in info
    assert "top" in info
    assert "width" in info
    assert "height" in info


def test_list_open_windows():
    """Verify that open application windows can be enumerated."""
    windows = list_open_windows(include_empty_titles=False)
    assert isinstance(windows, list)
    assert len(windows) > 0

    first = windows[0]
    assert "title" in first
    assert "left" in first
    assert "top" in first
    assert "width" in first
    assert "height" in first
    assert "is_active" in first


def test_capture_desktop_screenshot(tmp_path):
    """Verify desktop screenshot saves an image file with valid dimensions and size."""
    res = capture_desktop_screenshot(file_name="test_screenshot_artifact.png")
    assert "file_path" in res
    assert "artifact_id" in res
    assert res["width"] > 0
    assert res["height"] > 0
    assert res["size_bytes"] > 500

    img_path = Path(res["file_path"])
    assert img_path.exists()
    assert img_path.stat().st_size == res["size_bytes"]


def test_mouse_click_validation():
    """Verify parameter validation for desktop mouse clicks."""
    with pytest.raises(ValueError, match="Unsupported mouse button"):
        desktop_mouse_click(x=10, y=10, button="invalid")

    with pytest.raises(ValueError, match="Invalid clicks count"):
        desktop_mouse_click(x=10, y=10, clicks=99)

    with pytest.raises(ValueError, match="outside screen bounds"):
        desktop_mouse_click(x=-500, y=-500)


def test_desktop_hotkey_validation():
    """Verify hotkey validation parses combinations and rejects empty strings."""
    with pytest.raises(ValueError, match="keys list cannot be empty"):
        desktop_press_hotkey(keys="")

    with pytest.raises(ValueError, match="keys list cannot be empty"):
        desktop_press_hotkey(keys=[])


def test_desktop_tools_registered():
    """Verify all desktop tools are registered in default_registry."""
    expected_tools = [
        "desktop_get_screen_info",
        "desktop_get_active_window",
        "desktop_list_windows",
        "desktop_focus_window",
        "desktop_screenshot",
        "desktop_click",
        "desktop_move_mouse",
        "desktop_type_text",
        "desktop_press_hotkey",
    ]
    for tool_name in expected_tools:
        tool = default_registry.get(tool_name)
        assert tool is not None, f"Tool '{tool_name}' not found in registry"
        defn = tool.get_definition()
        assert defn.name == tool_name


def test_step_verifier_desktop_screenshot(tmp_path):
    """Verify StepVerifier checks desktop screenshots."""
    dummy_file = tmp_path / "dummy.png"
    dummy_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 200)

    # Valid screenshot output
    valid_output = {"file_path": str(dummy_file), "width": 800, "height": 600}
    res = StepVerifier.verify_step("desktop_screenshot", {}, valid_output)
    assert res.passed is True

    # Missing file
    invalid_output = {"file_path": str(tmp_path / "nonexistent.png")}
    res = StepVerifier.verify_step("desktop_screenshot", {}, invalid_output)
    assert res.passed is False

    # Invalid screen resolution
    res = StepVerifier.verify_step("desktop_get_screen_info", {}, {"screen_width": 0})
    assert res.passed is False

    res = StepVerifier.verify_step("desktop_get_screen_info", {}, {"screen_width": 1920, "screen_height": 1080})
    assert res.passed is True


def test_task_planner_desktop_queries():
    """Verify TaskPlanner decomposes natural language desktop queries."""
    planner = TaskPlanner()

    # Screenshot
    plan = planner.plan("take desktop screenshot")
    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "desktop_screenshot"

    # Screen info
    plan = planner.plan("desktop screen info")
    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "desktop_get_screen_info"

    # List windows
    plan = planner.plan("list open windows on desktop")
    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "desktop_list_windows"

    # Click
    plan = planner.plan("desktop click at (500, 300)")
    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "desktop_click"
    assert plan.steps[0].input_params["x"] == 500
    assert plan.steps[0].input_params["y"] == 300
    assert plan.steps[0].risk_level == RiskLevel.MEDIUM
