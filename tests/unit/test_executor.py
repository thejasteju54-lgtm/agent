"""Unit tests for TaskExecutor."""

from pathlib import Path
import uuid
from personal_ai.agent.executor import TaskExecutor
from personal_ai.agent.task_models import ExecutionPlan, PlanStep, RiskLevel, TaskStatus
from personal_ai.storage.database import Database
from personal_ai.storage.repositories import TaskRepository


def test_executor_successful_run(test_db: Database, temp_dir: Path) -> None:
    executor = TaskExecutor(db=test_db)
    target_file = str(temp_dir / "notes.txt")

    plan = ExecutionPlan(
        task_id=str(uuid.uuid4()),
        prompt="Write a note",
        steps=[
            PlanStep(
                step_id=str(uuid.uuid4()),
                step_number=1,
                tool_name="write_file",
                description="Write note to disk",
                input_params={"path": target_file, "content": "Hello World", "overwrite": True},
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            )
        ],
    )

    report = executor.execute(plan)
    assert report.status == TaskStatus.COMPLETED
    assert report.steps_completed == 1
    assert Path(target_file).read_text(encoding="utf-8") == "Hello World"

    # Verify task persisted in database
    task_repo = TaskRepository(test_db)
    persisted = task_repo.get_task(plan.task_id)
    assert persisted["status"] == TaskStatus.COMPLETED.value


def test_executor_approval_paused(test_db: Database, temp_dir: Path) -> None:
    executor = TaskExecutor(db=test_db)
    target_file = str(temp_dir / "protected.txt")
    Path(target_file).write_text("critical data")

    plan = ExecutionPlan(
        task_id=str(uuid.uuid4()),
        prompt="Delete protected file",
        steps=[
            PlanStep(
                step_id=str(uuid.uuid4()),
                step_number=1,
                tool_name="delete_file",
                description="Delete protected file",
                input_params={"path": target_file},
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
            )
        ],
    )

    # Without approval callback or auto_approve, task must pause
    report = executor.execute(plan, auto_approve=False)
    assert report.status == TaskStatus.AWAITING_APPROVAL
    assert Path(target_file).exists()  # Did not delete!

    # Now execute with approval callback = True
    report_approved = executor.execute(plan, auto_approve=False, approval_callback=lambda s: True)
    assert report_approved.status == TaskStatus.COMPLETED
    assert not Path(target_file).exists()  # Deleted after approval!


def test_executor_cancellation(test_db: Database) -> None:
    executor = TaskExecutor(db=test_db)
    task_repo = TaskRepository(test_db)
    task_id = str(uuid.uuid4())

    task_repo.create_task(task_id, "Long running task", status=TaskStatus.CANCELLED.value)

    plan = ExecutionPlan(
        task_id=task_id,
        prompt="Long running task",
        steps=[
            PlanStep(
                step_id=str(uuid.uuid4()),
                step_number=1,
                tool_name="list_directory",
                description="List files",
                input_params={"path": "."},
            )
        ],
    )

    report = executor.execute(plan)
    assert report.status == TaskStatus.CANCELLED
    assert report.steps_completed == 0
