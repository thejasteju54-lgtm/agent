"""Integration tests for end-to-end task planning and execution."""

from pathlib import Path
from personal_ai.agent.planner import TaskPlanner
from personal_ai.agent.executor import TaskExecutor
from personal_ai.agent.task_models import TaskStatus
from personal_ai.storage.database import Database
from personal_ai.storage.repositories import TaskRepository, StepRepository


def test_end_to_end_write_and_read(test_db: Database, temp_dir: Path) -> None:
    planner = TaskPlanner()
    executor = TaskExecutor(db=test_db)
    target_file = str(temp_dir / "integration_note.txt")

    # Step 1: Write task
    write_prompt = f"save content: 'integration test payload' to file '{target_file}'"
    plan = planner.plan(write_prompt)
    assert len(plan.steps) == 1

    report = executor.execute(plan, auto_approve=True)
    assert report.status == TaskStatus.COMPLETED
    assert Path(target_file).exists()
    assert "integration test payload" in Path(target_file).read_text(encoding="utf-8")

    # Verify Database state
    task_repo = TaskRepository(test_db)
    step_repo = StepRepository(test_db)

    task_row = task_repo.get_task(plan.task_id)
    assert task_row is not None
    assert task_row["status"] == TaskStatus.COMPLETED.value

    step_rows = step_repo.get_steps_for_task(plan.task_id)
    assert len(step_rows) == 1
    assert step_rows[0]["status"] == "COMPLETED"
    assert step_rows[0]["tool_name"] == "write_file"
