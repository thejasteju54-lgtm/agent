"""Task Executor: Coordinates sequential tool execution, verification, and persistence."""

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from personal_ai.agent.task_models import (
    ExecutionPlan,
    PlanStep,
    RiskLevel,
    StepResult,
    StepStatus,
    TaskReport,
    TaskStatus,
)
from personal_ai.agent.verification import StepVerifier
from personal_ai.storage.database import Database, get_db
from personal_ai.storage.repositories import (
    ApprovalRepository,
    StepRepository,
    TaskRepository,
)
from personal_ai.storage.artifacts import ArtifactManager
from personal_ai.tools.registry import ToolRegistry, default_registry
from personal_ai.logging.setup import get_logger

logger = get_logger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskExecutor:
    """Executes validated execution plans with verification and audit persistence."""

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        db: Optional[Database] = None,
        artifact_manager: Optional[ArtifactManager] = None,
    ):
        self.registry = registry or default_registry
        self.db = db or get_db()
        self.task_repo = TaskRepository(self.db)
        self.step_repo = StepRepository(self.db)
        self.approval_repo = ApprovalRepository(self.db)
        self.artifact_manager = artifact_manager or ArtifactManager(db=self.db)

    def execute(
        self,
        plan: ExecutionPlan,
        auto_approve: bool = False,
        approval_callback: Optional[Callable[[PlanStep], bool]] = None,
    ) -> TaskReport:
        """Run the execution plan to completion or approval stop.

        Args:
            plan: The planned steps to execute.
            auto_approve: If True, bypass interactive approval (e.g. for tested batch operations).
            approval_callback: Optional callable `(PlanStep) -> bool` to request user confirmation.
        """
        task_id = plan.task_id
        start_time = _utc_now_iso()
        logger.info("Starting execution for task: %s ('%s')", task_id, plan.prompt)

        # 1. Ensure task record exists in database
        existing = self.task_repo.get_task(task_id)
        if not existing:
            self.task_repo.create_task(
                task_id=task_id,
                prompt=plan.prompt,
                status=TaskStatus.RUNNING.value,
                plan_json=plan.model_dump_json(),
            )
        else:
            if existing["status"] == TaskStatus.CANCELLED.value:
                logger.warning("Task %s is already marked as CANCELLED", task_id)
                return self._build_report(
                    task_id=task_id,
                    prompt=plan.prompt,
                    status=TaskStatus.CANCELLED,
                    summary="Execution cancelled by user request.",
                    total_steps=len(plan.steps),
                    completed_steps=0,
                    failed_steps=0,
                    start_time=start_time,
                )
            self.task_repo.update_status(task_id, TaskStatus.RUNNING.value)
            self.task_repo.update_plan(task_id, plan.model_dump_json())

        completed_steps = 0
        failed_steps = 0
        step_results: List[StepResult] = []

        for step in plan.steps:
            # Check for external cancellation before each step
            task_state = self.task_repo.get_task(task_id)
            if task_state and task_state["status"] == TaskStatus.CANCELLED.value:
                logger.warning("Task %s was cancelled before step %d", task_id, step.step_number)
                return self._build_report(
                    task_id=task_id,
                    prompt=plan.prompt,
                    status=TaskStatus.CANCELLED,
                    summary="Execution cancelled by user request.",
                    total_steps=len(plan.steps),
                    completed_steps=completed_steps,
                    failed_steps=failed_steps,
                    start_time=start_time,
                )

            # Record or reuse step in database
            existing_step = self.step_repo.get_step(step.step_id)
            if not existing_step:
                self.step_repo.create_step(
                    step_id=step.step_id,
                    task_id=task_id,
                    step_number=step.step_number,
                    tool_name=step.tool_name,
                    input_params=step.input_params,
                    risk_level=step.risk_level.value,
                    requires_approval=step.requires_approval,
                )

            # Human Approval Gate
            if step.requires_approval and not auto_approve:
                is_approved = False
                approval_id = str(uuid.uuid4())
                self.approval_repo.create_approval(
                    approval_id=approval_id,
                    task_id=task_id,
                    step_id=step.step_id,
                    action_description=step.description,
                    risk_level=step.risk_level.value,
                )

                if approval_callback:
                    logger.info("Requesting approval for step %s: %s", step.step_id, step.description)
                    is_approved = approval_callback(step)

                if not is_approved:
                    logger.warning("Step %s requires approval but was not approved", step.step_id)
                    self.task_repo.update_status(task_id, TaskStatus.AWAITING_APPROVAL.value)
                    self.step_repo.update_step(step.step_id, StepStatus.AWAITING_APPROVAL.value, approved=False)
                    return self._build_report(
                        task_id=task_id,
                        prompt=plan.prompt,
                        status=TaskStatus.AWAITING_APPROVAL,
                        summary=f"Task paused awaiting human approval for: {step.description}",
                        total_steps=len(plan.steps),
                        completed_steps=completed_steps,
                        failed_steps=failed_steps,
                        start_time=start_time,
                    )
                else:
                    self.approval_repo.resolve_approval(approval_id, "approved", "Approved by user")
                    self.step_repo.update_step(step.step_id, StepStatus.RUNNING.value, approved=True)

            # Execute Step
            step_result = self._execute_step(task_id, step)
            step_results.append(step_result)

            if step_result.status == StepStatus.COMPLETED:
                completed_steps += 1
            else:
                failed_steps += 1
                logger.error("Step %d (%s) failed: %s", step.step_number, step.tool_name, step_result.error)
                self.task_repo.update_status(
                    task_id,
                    TaskStatus.FAILED.value,
                    error_message=step_result.error,
                    result_summary=f"Failed at step {step.step_number} ({step.tool_name})",
                )
                return self._build_report(
                    task_id=task_id,
                    prompt=plan.prompt,
                    status=TaskStatus.FAILED,
                    summary=f"Task execution failed at step {step.step_number}: {step_result.error}",
                    total_steps=len(plan.steps),
                    completed_steps=completed_steps,
                    failed_steps=failed_steps,
                    start_time=start_time,
                    error_message=step_result.error,
                )

        # All steps completed successfully
        summary = f"All {completed_steps} steps executed and verified successfully."
        self.task_repo.update_status(
            task_id,
            TaskStatus.COMPLETED.value,
            result_summary=summary,
        )

        return self._build_report(
            task_id=task_id,
            prompt=plan.prompt,
            status=TaskStatus.COMPLETED,
            summary=summary,
            total_steps=len(plan.steps),
            completed_steps=completed_steps,
            failed_steps=failed_steps,
            start_time=start_time,
        )

    def _execute_step(self, task_id: str, step: PlanStep) -> StepResult:
        """Execute a single step with error capture, timing, and verification."""
        t0 = time.perf_counter()
        self.step_repo.update_step(step.step_id, StepStatus.RUNNING.value)

        last_error = None
        for attempt in range(step.max_retries + 1):
            try:
                logger.info("Executing step %d (%s), attempt %d", step.step_number, step.tool_name, attempt + 1)
                output = self.registry.execute_tool(step.tool_name, step.input_params)

                # Verification check
                v_res = StepVerifier.verify_step(step.tool_name, step.input_params, output)
                duration_ms = (time.perf_counter() - t0) * 1000

                if not v_res.passed:
                    logger.warning("Step verification failed: %s", v_res.message)
                    last_error = f"Verification failed: {v_res.message}"
                    continue

                output_str = json.dumps(output) if isinstance(output, (dict, list)) else str(output)
                self.step_repo.update_step(
                    step_id=step.step_id,
                    status=StepStatus.COMPLETED.value,
                    output_result=output_str,
                )
                return StepResult(
                    step_id=step.step_id,
                    status=StepStatus.COMPLETED,
                    output=output,
                    duration_ms=duration_ms,
                    verified=True,
                    verification_details=v_res.message,
                )
            except Exception as e:
                logger.warning("Step %s execution error on attempt %d: %s", step.step_id, attempt + 1, e)
                last_error = str(e)

        duration_ms = (time.perf_counter() - t0) * 1000
        self.step_repo.update_step(
            step_id=step.step_id,
            status=StepStatus.FAILED.value,
            error_message=last_error,
        )
        return StepResult(
            step_id=step.step_id,
            status=StepStatus.FAILED,
            error=last_error,
            duration_ms=duration_ms,
            verified=False,
        )

    def _build_report(
        self,
        task_id: str,
        prompt: str,
        status: TaskStatus,
        summary: str,
        total_steps: int,
        completed_steps: int,
        failed_steps: int,
        start_time: str,
        error_message: Optional[str] = None,
    ) -> TaskReport:
        artifacts = self.artifact_manager.list_artifacts_for_task(task_id)
        return TaskReport(
            task_id=task_id,
            prompt=prompt,
            status=status,
            summary=summary,
            steps_total=total_steps,
            steps_completed=completed_steps,
            steps_failed=failed_steps,
            artifacts=artifacts,
            error_message=error_message,
            started_at=start_time,
            completed_at=_utc_now_iso(),
        )
