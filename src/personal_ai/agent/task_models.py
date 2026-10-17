"""Pydantic data models for tasks, execution plans, steps, and reports."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """Operation risk classification."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskStatus(str, Enum):
    """State of an automation task."""
    PENDING = "PENDING"
    PLANNING = "PLANNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StepStatus(str, Enum):
    """State of an individual execution step."""
    PENDING = "PENDING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class PlanStep(BaseModel):
    """An individual action step inside an execution plan."""
    step_id: str
    step_number: int
    tool_name: str
    description: str
    input_params: Dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    expected_outcome: Optional[str] = None
    max_retries: int = 1


class ExecutionPlan(BaseModel):
    """Structured plan generated for a task."""
    task_id: str
    prompt: str
    steps: List[PlanStep] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    requires_clarification: bool = False
    clarification_question: Optional[str] = None


class StepResult(BaseModel):
    """Result of an individual tool step execution."""
    step_id: str
    status: StepStatus
    output: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    verified: bool = False
    verification_details: Optional[str] = None


class TaskReport(BaseModel):
    """Final execution summary report for a task."""
    task_id: str
    prompt: str
    status: TaskStatus
    summary: str
    steps_total: int
    steps_completed: int
    steps_failed: int
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    error_message: Optional[str] = None
    started_at: str
    completed_at: Optional[str] = None
