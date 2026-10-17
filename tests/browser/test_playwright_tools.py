"""Browser automation tests using Playwright."""

from pathlib import Path
import pytest
from personal_ai.agent.planner import TaskPlanner
from personal_ai.agent.executor import TaskExecutor
from personal_ai.agent.task_models import TaskStatus
from personal_ai.storage.database import Database
from personal_ai.tools.browser import (
    BrowserSessionManager,
    BrowserOpenUrlTool,
    BrowserExtractContentTool,
    BrowserScreenshotTool,
)


@pytest.fixture(scope="module")
def sample_html_file(tmp_path_factory) -> Path:
    """Create a sample local HTML file for fast, deterministic browser tests."""
    temp_dir = tmp_path_factory.mktemp("html_test")
    html_file = temp_dir / "test_page.html"
    content = """<!DOCTYPE html>
<html>
<head>
    <title>Personal AI Automation Test Page</title>
</head>
<body>
    <h1>Browser Test Header</h1>
    <p id="desc">This is a verified test page for Playwright automation runtime on Windows.</p>
    <button id="action-btn">Click Me</button>
</body>
</html>"""
    html_file.write_text(content, encoding="utf-8")
    return html_file


@pytest.fixture(autouse=True)
def cleanup_browser():
    """Ensure browser session is closed after tests."""
    yield
    BrowserSessionManager.get_instance().close()


def test_browser_open_url_and_extract(sample_html_file: Path) -> None:
    file_url = sample_html_file.as_uri()

    open_tool = BrowserOpenUrlTool()
    res = open_tool.execute(url=file_url)

    assert res["status_code"] == 200
    assert res["title"] == "Personal AI Automation Test Page"
    assert file_url in res["final_url"]

    # Extract content
    extract_tool = BrowserExtractContentTool()
    ext_res = extract_tool.execute(selector="body")

    assert "Browser Test Header" in ext_res["text"]
    assert "verified test page for Playwright" in ext_res["text"]
    assert ext_res["total_chars"] > 0


def test_browser_screenshot(sample_html_file: Path, temp_dir: Path, test_db: Database) -> None:
    file_url = sample_html_file.as_uri()

    open_tool = BrowserOpenUrlTool()
    open_tool.execute(url=file_url)

    screenshot_tool = BrowserScreenshotTool()
    ss_res = screenshot_tool.execute(file_name="diagnostic_test.png", task_id="task-browser-01")

    assert ss_res["file_name"] == "diagnostic_test.png"
    assert Path(ss_res["file_path"]).exists()
    assert ss_res["size_bytes"] > 500  # Real image generated


def test_end_to_end_browser_task(sample_html_file: Path, test_db: Database) -> None:
    file_url = sample_html_file.as_uri()
    planner = TaskPlanner()
    executor = TaskExecutor(db=test_db)

    prompt = f"browse to '{file_url}', take screenshot and extract content"
    plan = planner.plan(prompt)

    assert len(plan.steps) == 3
    assert plan.steps[0].tool_name == "browser_open_url"
    assert plan.steps[1].tool_name == "browser_screenshot"
    assert plan.steps[2].tool_name == "browser_extract_content"

    report = executor.execute(plan, auto_approve=True)
    assert report.status == TaskStatus.COMPLETED
    assert report.steps_completed == 3
    assert len(report.artifacts) >= 1
