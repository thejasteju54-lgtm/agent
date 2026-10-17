"""Unit tests for Windows clipboard capture, classification, and tools."""

import sys
import uuid
import pytest
from personal_ai.agent.planner import TaskPlanner
from personal_ai.agent.executor import TaskExecutor
from personal_ai.agent.task_models import TaskStatus
from personal_ai.storage.database import Database
from personal_ai.storage.repositories import ClipboardRepository
from personal_ai.tools.clipboard import (
    ClipboardDeleteTool,
    ClipboardGetLatestTool,
    ClipboardMonitor,
    ClipboardSearchTool,
    ClipboardSetTool,
    WindowsClipboard,
)


def test_classify_content() -> None:
    assert WindowsClipboard.classify_content("https://github.com/microsoft/playwright") == "url"
    assert WindowsClipboard.classify_content("http://example.com/api/v1?query=1") == "url"

    code_sample = "def calculate_total(items):\n    return sum(x.price for x in items)"
    assert WindowsClipboard.classify_content(code_sample) == "code"

    prompt_sample = "Explain how transformer neural networks work"
    assert WindowsClipboard.classify_content(prompt_sample) == "prompt"

    text_sample = "Remember to buy groceries and call Alice tomorrow afternoon."
    assert WindowsClipboard.classify_content(text_sample) == "text"


def test_sensitive_detection() -> None:
    assert WindowsClipboard.is_sensitive("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...")
    assert WindowsClipboard.is_sensitive("api_key = 'abcdef1234567890abcdef1234567890'")
    assert not WindowsClipboard.is_sensitive("https://google.com")
    assert not WindowsClipboard.is_sensitive("Just normal everyday notes")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows clipboard tests require Windows OS")
def test_windows_clipboard_get_set() -> None:
    test_str = f"PersonalAI-Test-{uuid.uuid4().hex}"
    success = WindowsClipboard.set_text(test_str)
    assert success is True

    read_back = WindowsClipboard.get_text()
    assert read_back == test_str


@pytest.mark.skipif(sys.platform != "win32", reason="Windows clipboard tests require Windows OS")
def test_clipboard_monitor(test_db: Database) -> None:
    monitor = ClipboardMonitor(db=test_db, poll_interval_sec=0.1)

    # 1. Set text on clipboard
    test_msg = f"Monitor test message {uuid.uuid4().hex}"
    WindowsClipboard.set_text(test_msg)

    # 2. Check once
    captured = monitor.check_once()
    assert captured is not None
    assert captured["content_text"] == test_msg
    assert captured["content_type"] == "text"

    # 3. Identical content again should be ignored
    assert monitor.check_once() is None

    # 4. New content
    new_url = "https://example.org/test-url"
    WindowsClipboard.set_text(new_url)
    captured2 = monitor.check_once()
    assert captured2 is not None
    assert captured2["content_type"] == "url"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows clipboard tests require Windows OS")
def test_clipboard_tools(test_db: Database) -> None:
    repo = ClipboardRepository(test_db)
    sample_text = "Important architecture meeting notes"
    repo.save_entry(
        entry_id="clip-001",
        content_hash=WindowsClipboard.hash_content(sample_text),
        content_type="text",
        content_text=sample_text,
    )

    # Search tool
    search_tool = ClipboardSearchTool()
    res = search_tool.execute(query="meeting")
    assert res["total_found"] >= 1
    assert any(e["id"] == "clip-001" for e in res["entries"])

    # Set tool
    set_tool = ClipboardSetTool()
    set_res = set_tool.execute(text="Placed by ClipboardSetTool")
    assert set_res["status"] == "success"
    assert WindowsClipboard.get_text() == "Placed by ClipboardSetTool"

    # Delete tool
    del_tool = ClipboardDeleteTool()
    del_res = del_tool.execute(entry_id="clip-001")
    assert del_res["deleted"] is True


def test_task_planner_clipboard_query(test_db: Database) -> None:
    planner = TaskPlanner()
    plan = planner.plan("search clipboard for 'architecture'")
    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "clipboard_search"
    assert plan.steps[0].input_params["query"] == "architecture"
