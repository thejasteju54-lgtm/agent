"""Unit tests for Task, Step, Approval, and Clipboard repositories."""

import uuid
from personal_ai.storage.repositories import (
    TaskRepository,
    StepRepository,
    ApprovalRepository,
    ClipboardRepository,
)


def test_task_lifecycle(task_repo: TaskRepository) -> None:
    task_id = str(uuid.uuid4())
    task = task_repo.create_task(
        task_id=task_id,
        prompt="Search for latest AI news",
        status="PENDING",
    )
    assert task["id"] == task_id
    assert task["status"] == "PENDING"
    assert task["prompt"] == "Search for latest AI news"

    # Update plan
    plan_dict = {"steps": ["open browser", "search query"]}
    updated = task_repo.update_plan(task_id, plan_dict)
    assert updated is not None
    assert "open browser" in updated["plan_json"]

    # Update status to RUNNING then COMPLETED
    task_repo.update_status(task_id, "RUNNING")
    assert task_repo.get_task(task_id)["status"] == "RUNNING"

    completed = task_repo.update_status(
        task_id,
        "COMPLETED",
        result_summary="Found 5 articles",
    )
    assert completed["status"] == "COMPLETED"
    assert completed["result_summary"] == "Found 5 articles"
    assert completed["completed_at"] is not None


def test_step_lifecycle(task_repo: TaskRepository, step_repo: StepRepository) -> None:
    task_id = str(uuid.uuid4())
    task_repo.create_task(task_id, "Run test pipeline")

    step_id = str(uuid.uuid4())
    step = step_repo.create_step(
        step_id=step_id,
        task_id=task_id,
        step_number=1,
        tool_name="web_browser",
        input_params={"url": "https://example.com"},
        risk_level="low",
    )
    assert step["id"] == step_id
    assert step["status"] == "PENDING"
    assert step["risk_level"] == "low"

    # Complete step
    updated = step_repo.update_step(
        step_id=step_id,
        status="COMPLETED",
        output_result="Page loaded successfully",
    )
    assert updated["status"] == "COMPLETED"
    assert updated["output_result"] == "Page loaded successfully"

    steps = step_repo.get_steps_for_task(task_id)
    assert len(steps) == 1
    assert steps[0]["id"] == step_id


def test_approval_lifecycle(task_repo: TaskRepository, approval_repo: ApprovalRepository) -> None:
    task_id = str(uuid.uuid4())
    task_repo.create_task(task_id, "Dangerous operation")

    approval_id = str(uuid.uuid4())
    approval = approval_repo.create_approval(
        approval_id=approval_id,
        task_id=task_id,
        step_id=None,
        action_description="Delete old temp folder",
        risk_level="high",
    )
    assert approval["status"] == "pending"
    assert approval["risk_level"] == "high"

    pending = approval_repo.get_pending_approvals(task_id)
    assert len(pending) == 1
    assert pending[0]["id"] == approval_id

    resolved = approval_repo.resolve_approval(approval_id, "approved", "User verified")
    assert resolved["status"] == "approved"
    assert resolved["resolution_reason"] == "User verified"

    pending_after = approval_repo.get_pending_approvals(task_id)
    assert len(pending_after) == 0


def test_clipboard_repository(clipboard_repo: ClipboardRepository) -> None:
    entry_id = str(uuid.uuid4())
    entry = clipboard_repo.save_entry(
        entry_id=entry_id,
        content_hash="abc123hash",
        content_type="text",
        content_text="Hello Antigravity 2.0",
        source_app="notepad.exe",
    )
    assert entry["content_hash"] == "abc123hash"
    assert entry["content_text"] == "Hello Antigravity 2.0"

    # Search
    results = clipboard_repo.search_entries(query="Antigravity")
    assert len(results) == 1
    assert results[0]["id"] == entry_id

    # Duplicate hash upsert
    entry_updated = clipboard_repo.save_entry(
        entry_id=str(uuid.uuid4()),
        content_hash="abc123hash",
        content_type="text",
        content_text="Hello Antigravity 2.0",
        source_app="vscode.exe",
    )
    assert entry_updated["content_hash"] == "abc123hash"
    assert entry_updated["source_app"] == "vscode.exe"

    # Delete
    deleted = clipboard_repo.delete_entry(entry_id)
    assert deleted is True
    assert len(clipboard_repo.search_entries(query="Antigravity")) == 0
