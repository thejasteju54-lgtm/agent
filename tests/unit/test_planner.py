"""Unit tests for TaskPlanner."""

from personal_ai.agent.planner import TaskPlanner
from personal_ai.agent.task_models import RiskLevel


def test_planner_empty_prompt_requires_clarification() -> None:
    planner = TaskPlanner()
    plan = planner.plan("")
    assert plan.requires_clarification is True
    assert plan.clarification_question is not None


def test_planner_read_file() -> None:
    planner = TaskPlanner()
    plan = planner.plan("read file 'data/report.txt'")
    assert plan.requires_clarification is False
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.tool_name == "read_file"
    assert step.input_params["path"] == "data/report.txt"
    assert step.risk_level == RiskLevel.LOW


def test_planner_delete_file_high_risk() -> None:
    planner = TaskPlanner()
    plan = planner.plan("delete file 'temp.log'")
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.tool_name == "delete_file"
    assert step.risk_level == RiskLevel.HIGH
    assert step.requires_approval is True
