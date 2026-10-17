"""Unit tests for task interruption detection, conservative recovery, and reporting."""

import pytest
from pathlib import Path
from click.testing import CliRunner
from personal_ai.agent.recovery import TaskRecoveryManager
from personal_ai.agent.task_models import StepStatus, TaskStatus
from personal_ai.storage.database import Database
from personal_ai.storage.repositories import StepRepository, TaskRepository
from personal_ai.cli import cli


@pytest.fixture
def temp_db(tmp_path: Path):
    """Create a temporary initialized SQLite database."""
    db_file = tmp_path / "test_recovery.db"
    db = Database(db_path=db_file)
    db.initialize_schema()
    return db


def test_no_interrupted_tasks(temp_db: Database):
    """Verify clean state detection when all tasks are completed."""
    task_repo = TaskRepository(temp_db)
    task_repo.create_task("t-done", "Read file", TaskStatus.COMPLETED.value)

    mgr = TaskRecoveryManager(db=temp_db)
    diagnoses = mgr.detect_interrupted_tasks()
    assert len(diagnoses) == 0

    report = mgr.generate_recovery_report()
    assert "No interrupted or stuck tasks found" in report


def test_interrupted_read_only_task(temp_db: Database):
    """Verify that an interrupted read-only/idempotent task allows auto-resume."""
    task_repo = TaskRepository(temp_db)
    step_repo = StepRepository(temp_db)

    task_repo.create_task("t-read", "Inspect readme file", TaskStatus.RUNNING.value)
    step_repo.create_step(
        step_id="step-read-1",
        task_id="t-read",
        step_number=1,
        tool_name="read_file",
        input_params={"path": "README.md"},
        risk_level="low",
    )
    step_repo.update_step("step-read-1", StepStatus.RUNNING.value)

    mgr = TaskRecoveryManager(db=temp_db)
    diagnoses = mgr.detect_interrupted_tasks()

    assert len(diagnoses) == 1
    d = diagnoses[0]
    assert d.task_id == "t-read"
    assert d.is_irreversible is False
    assert d.can_auto_resume is True
    assert "Safe to retry step" in d.recommendation


def test_interrupted_irreversible_task(temp_db: Database):
    """Verify that an interrupted irreversible task is conservatively blocked from auto-retry."""
    task_repo = TaskRepository(temp_db)
    step_repo = StepRepository(temp_db)

    task_repo.create_task("t-delete", "Clean temp files", TaskStatus.RUNNING.value)
    # Step 1: Completed read
    step_repo.create_step(
        step_id="step-1",
        task_id="t-delete",
        step_number=1,
        tool_name="read_file",
        input_params={"path": "temp.txt"},
        risk_level="low",
    )
    step_repo.update_step("step-1", StepStatus.COMPLETED.value)

    # Step 2: In-flight irreversible deletion
    step_repo.create_step(
        step_id="step-2",
        task_id="t-delete",
        step_number=2,
        tool_name="delete_file",
        input_params={"path": "temp.txt"},
        risk_level="high",
    )
    step_repo.update_step("step-2", StepStatus.RUNNING.value)

    mgr = TaskRecoveryManager(db=temp_db)
    diagnoses = mgr.detect_interrupted_tasks()

    assert len(diagnoses) == 1
    d = diagnoses[0]
    assert d.task_id == "t-delete"
    assert d.is_irreversible is True
    assert d.can_auto_resume is False
    assert "DO NOT AUTO-REPEAT" in d.recommendation
    assert "delete_file" in d.recommendation

    # Check generated recovery report formatting
    report = mgr.generate_recovery_report(task_id="t-delete")
    assert "Personal AI Interrupted Execution Recovery Report" in report
    assert "IRREVERSIBLE / UNCERTAIN" in report
    assert "delete_file" in report


def test_mark_interrupted_tasks_failed(temp_db: Database):
    """Verify that mark_interrupted_tasks_failed transitions tasks and steps safely to FAILED."""
    task_repo = TaskRepository(temp_db)
    step_repo = StepRepository(temp_db)

    task_repo.create_task("t-stuck", "Unfinished action", TaskStatus.RUNNING.value)
    step_repo.create_step(
        step_id="step-s-1",
        task_id="t-stuck",
        step_number=1,
        tool_name="write_file",
        input_params={"path": "out.txt", "content": "test"},
        risk_level="medium",
    )
    step_repo.update_step("step-s-1", StepStatus.RUNNING.value)

    mgr = TaskRecoveryManager(db=temp_db)
    count = mgr.mark_interrupted_tasks_failed(task_id="t-stuck", reason="Abrupt reboot")
    assert count == 1

    t = task_repo.get_task("t-stuck")
    assert t["status"] == TaskStatus.FAILED.value
    assert "Abrupt reboot" in t["error_message"]

    s = step_repo.get_step("step-s-1")
    assert s["status"] == StepStatus.FAILED.value
    assert "Abrupt reboot" in s["error_message"]

    # Verify no more interrupted tasks remain
    assert len(mgr.detect_interrupted_tasks()) == 0


def test_cli_task_recover():
    """Verify CLI task recover command executes cleanly."""
    runner = CliRunner()
    res = runner.invoke(cli, ["task", "recover"])
    assert res.exit_code == 0
