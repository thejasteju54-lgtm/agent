"""Unit tests for task data models and serializations."""

import uuid
from personal_ai.agent.task_models import (
    ExecutionPlan,
    PlanStep,
    RiskLevel,
    StepResult,
    StepStatus,
    TaskReport,
    TaskStatus,
)


def test_plan_step_model() -> None:
    step = PlanStep(
        step_id=str(uuid.uuid4()),
        step_number=1,
        tool_name="read_file",
        description="Read target file",
        input_params={"path": "test.txt"},
        risk_level=RiskLevel.LOW,
        requires_approval=False,
    )
    assert step.step_number == 1
    assert step.risk_level == RiskLevel.LOW
    assert step.input_params["path"] == "test.txt"


def test_execution_plan_serialization() -> None:
    plan = ExecutionPlan(
        task_id="task-123",
        prompt="List files in directory",
        steps=[
            PlanStep(
                step_id="step-1",
                step_number=1,
                tool_name="list_directory",
                description="List directory",
                input_params={"path": "."},
            )
        ],
        assumptions=["Using current working directory"],
    )
    json_data = plan.model_dump_json()
    assert "task-123" in json_data
    assert "list_directory" in json_data

    loaded = ExecutionPlan.model_validate_json(json_data)
    assert loaded.task_id == "task-123"
    assert len(loaded.steps) == 1


def test_step_result_model() -> None:
    res = StepResult(
        step_id="step-01",
        status=StepStatus.COMPLETED,
        output={"size": 1024},
        duration_ms=42.5,
        verified=True,
    )
    assert res.status == StepStatus.COMPLETED
    assert res.verified is True
    assert res.output["size"] == 1024
