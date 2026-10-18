"""Task Orchestrator: Bounded execution, permission checks, verification, and audit logging.

Enforces:
1. Unified permission engine (LOW, MEDIUM, HIGH) and rejection of prohibited operations.
2. Step limits (bounded execution), cancellation tokens, and timeouts.
3. Idempotency key deduplication.
4. Human approval gates with persistent ApprovalRecord entries.
5. Independent state verification after every action.
6. Persistent audit logging for security and observability.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from marketpulse.config import mp_settings
from marketpulse.storage.models import (
    ApprovalRecord,
    AuditEvent,
    AutomationTask,
    TaskStatus,
)
from marketpulse.agent.permissions import (
    RiskLevel,
    RiskPolicyEngine,
    ProhibitedActionError,
)
from marketpulse.agent.tools import MarketPulseToolRegistry
from marketpulse.agent.security import (
    emergency_stop,
    EmergencyStopActiveError,
    OperatingModeError,
    check_operating_mode_capability,
)
from marketpulse.logging.setup import get_logger

logger = get_logger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StepVerificationError(Exception):
    """Raised when an action's post-condition cannot be independently verified."""
    pass


class TaskOrchestrator:
    """Orchestrates automation tasks with risk controls and independent verification."""

    def __init__(
        self,
        session: Session,
        policy_engine: Optional[RiskPolicyEngine] = None,
        registry: Optional[MarketPulseToolRegistry] = None,
    ):
        self.session = session
        self.policy = policy_engine or RiskPolicyEngine()
        self.registry = registry or MarketPulseToolRegistry()

    def submit_task(
        self,
        prompt: str,
        task_type: str = "RESEARCH",
        idempotency_key: Optional[str] = None,
        step_limit: int = 20,
    ) -> AutomationTask:
        """Submit a new task or retrieve an existing one via idempotency key."""
        if idempotency_key:
            existing = (
                self.session.query(AutomationTask)
                .filter_by(idempotency_key=idempotency_key)
                .first()
            )
            if existing:
                logger.info(
                    "Idempotency hit for key '%s'; returning existing task '%s' (status: %s)",
                    idempotency_key,
                    existing.id,
                    existing.status,
                )
                return existing

        task = AutomationTask(
            prompt=prompt,
            task_type=task_type,
            status=TaskStatus.PENDING.value,
            idempotency_key=idempotency_key,
            step_limit=step_limit,
            current_step=0,
            started_at=_utc_now(),
        )
        self.session.add(task)
        self.session.flush()

        self._record_audit_event(
            event_type="TASK_SUBMITTED",
            entity_type="AutomationTask",
            entity_id=task.id,
            details={"prompt": prompt, "step_limit": step_limit, "idempotency_key": idempotency_key},
        )
        return task

    def execute_step(
        self,
        task_id: str,
        tool_name: str,
        params: Optional[Dict[str, Any]] = None,
        auto_approve: bool = False,
    ) -> Dict[str, Any]:
        """Execute a single step within a task under permission and bounded execution rules."""
        task = self.session.query(AutomationTask).filter_by(id=task_id).first()
        if not task:
            raise ValueError(f"Task '{task_id}' not found.")

        # 0. Check emergency stop
        if emergency_stop.is_stopped:
            task.status = TaskStatus.CANCELLED.value
            task.cancellation_reason = f"Emergency stop: {emergency_stop.stop_reason}"
            task.completed_at = _utc_now()
            self._record_audit_event(
                event_type="TASK_EMERGENCY_STOPPED",
                entity_type="AutomationTask",
                entity_id=task.id,
                details={"step": task.current_step, "reason": emergency_stop.stop_reason},
            )
            self.session.flush()
            raise EmergencyStopActiveError(f"Task halted by Emergency Stop: {emergency_stop.stop_reason}")

        # Check task cancellation
        if task.status == TaskStatus.CANCELLED.value:
            logger.warning("Task '%s' is CANCELLED; rejecting execution.", task_id)
            return {"status": "CANCELLED", "reason": task.cancellation_reason}

        # 1. Bounded execution check
        if task.current_step >= task.step_limit:
            task.status = TaskStatus.FAILED.value
            task.error_message = f"Step limit of {task.step_limit} exceeded."
            task.completed_at = _utc_now()
            self.session.flush()
            logger.error("Task '%s' exceeded step limit %d", task_id, task.step_limit)
            return {"status": "FAILED", "error": task.error_message}

        # 2. Check tool existence and operating mode compatibility
        tool = self.registry.get(tool_name)
        if not tool:
            task.status = TaskStatus.FAILED.value
            task.error_message = f"Tool '{tool_name}' not registered."
            self.session.flush()
            return {"status": "FAILED", "error": task.error_message}

        try:
            check_operating_mode_capability(tool_name, supported_modes=tool.supported_modes)
        except OperatingModeError as e:
            task.status = TaskStatus.FAILED.value
            task.error_message = str(e)
            task.completed_at = _utc_now()
            self._record_audit_event(
                event_type="OPERATING_MODE_VIOLATION",
                entity_type="AutomationTask",
                entity_id=task.id,
                details={"tool_name": tool_name, "error": str(e), "mode": mp_settings.operating_mode},
                actor="mode_enforcer",
            )
            self.session.flush()
            raise e

        # 3. Assess risk and check prohibited operations
        try:
            risk_level = self.policy.assess_risk_level(tool_name, tool.risk_level, params)
        except ProhibitedActionError as e:
            task.status = TaskStatus.FAILED.value
            task.error_message = str(e)
            task.completed_at = _utc_now()
            self._record_audit_event(
                event_type="SECURITY_VIOLATION",
                entity_type="AutomationTask",
                entity_id=task.id,
                details={"tool_name": tool_name, "error": str(e)},
                actor="security_guardrail",
            )
            self.session.flush()
            raise e

        # 4. Human Approval Gate
        requires_approval = self.policy.requires_approval(tool_name, risk_level, params)
        if requires_approval and not auto_approve:
            approval = ApprovalRecord(
                task_id=task.id,
                action_type=tool_name,
                action_description=f"Tool '{tool_name}' with params: {json.dumps(params or {})}",
                risk_level=risk_level.value,
                status="PENDING",
            )
            self.session.add(approval)
            task.status = TaskStatus.AWAITING_APPROVAL.value
            task.requires_approval = True
            task.approval_status = "PENDING"
            self.session.flush()

            self._record_audit_event(
                event_type="APPROVAL_REQUESTED",
                entity_type="ApprovalRecord",
                entity_id=approval.id,
                details={"task_id": task.id, "tool_name": tool_name, "risk_level": risk_level.value},
            )
            return {
                "status": "AWAITING_APPROVAL",
                "approval_id": approval.id,
                "task_id": task.id,
                "tool_name": tool_name,
                "risk_level": risk_level.value,
            }

        # 5. Execute Action
        task.status = TaskStatus.RUNNING.value
        task.current_step += 1
        self.session.flush()

        try:
            logger.info("Executing tool '%s' for task '%s' (Step %d)", tool_name, task.id, task.current_step)
            import inspect
            sig = inspect.signature(tool.execute)
            if "session" in sig.parameters:
                result = tool.execute(session=self.session, **(params or {}))
            else:
                result = tool.execute(**(params or {}))

            # 6. Verification Layer: Independently verify target state
            task.status = TaskStatus.VERIFYING.value
            self.session.flush()
            self._verify_step_execution(tool_name, params or {}, result)

            # Step verified successfully
            task.status = TaskStatus.RUNNING.value
            checkpoint = {
                "step": task.current_step,
                "tool_name": tool_name,
                "result": result,
                "timestamp": _utc_now().isoformat(),
            }
            task.recovery_metadata_json = json.dumps(checkpoint)
            task.result_summary = f"Executed {tool_name} successfully."
            self.session.flush()

            self._record_audit_event(
                event_type="STEP_EXECUTED",
                entity_type="AutomationTask",
                entity_id=task.id,
                details={"step": task.current_step, "tool": tool_name, "result": result},
            )
            return {"status": "SUCCESS", "result": result, "step": task.current_step}

        except Exception as e:
            task.status = TaskStatus.FAILED.value
            task.error_message = str(e)
            task.completed_at = _utc_now()
            self.session.flush()
            logger.error("Execution error on step %d for task '%s': %s", task.current_step, task.id, e)
            self._record_audit_event(
                event_type="STEP_FAILED",
                entity_type="AutomationTask",
                entity_id=task.id,
                details={"step": task.current_step, "tool": tool_name, "error": str(e)},
            )
            raise e

    def resolve_approval(
        self,
        approval_id: str,
        decision: str,
        resolved_by: str = "analyst",
        reason: Optional[str] = None,
    ) -> ApprovalRecord:
        """Resolve a pending human approval (APPROVED or REJECTED)."""
        approval = self.session.query(ApprovalRecord).filter_by(id=approval_id).first()
        if not approval:
            raise ValueError(f"Approval '{approval_id}' not found.")

        now = _utc_now()
        decision_upper = decision.upper()
        if decision_upper not in ("APPROVED", "REJECTED"):
            raise ValueError(f"Invalid decision '{decision}'. Expected APPROVED or REJECTED.")

        approval.status = decision_upper
        approval.resolved_by = resolved_by
        approval.resolution_reason = reason or f"Decision {decision_upper} by {resolved_by}"
        approval.resolved_at = now

        task = approval.task
        if task:
            task.approval_status = decision_upper
            if decision_upper == "APPROVED":
                task.status = TaskStatus.RUNNING.value
            else:
                task.status = TaskStatus.CANCELLED.value
                task.cancellation_reason = f"Action rejected: {reason or 'Denied by human analyst'}"
                task.completed_at = now

        self.session.flush()

        self._record_audit_event(
            event_type=f"APPROVAL_{decision_upper}",
            entity_type="ApprovalRecord",
            entity_id=approval.id,
            details={"task_id": approval.task_id, "resolved_by": resolved_by, "reason": reason},
            actor=resolved_by,
        )
        return approval

    def cancel_task(self, task_id: str, reason: str = "Cancelled by user") -> AutomationTask:
        """Cancel an in-progress or paused task safely."""
        task = self.session.query(AutomationTask).filter_by(id=task_id).first()
        if not task:
            raise ValueError(f"Task '{task_id}' not found.")

        if task.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value):
            raise ValueError(f"Cannot cancel completed or failed task '{task_id}'.")

        task.status = TaskStatus.CANCELLED.value
        task.cancellation_reason = reason
        task.completed_at = _utc_now()
        self.session.flush()

        self._record_audit_event(
            event_type="TASK_CANCELLED",
            entity_type="AutomationTask",
            entity_id=task.id,
            details={"reason": reason},
        )
        return task

    def mark_task_completed(self, task_id: str, summary: Optional[str] = None) -> AutomationTask:
        """Mark task as successfully completed."""
        task = self.session.query(AutomationTask).filter_by(id=task_id).first()
        if not task:
            raise ValueError(f"Task '{task_id}' not found.")
        task.status = TaskStatus.COMPLETED.value
        if summary:
            task.result_summary = summary
        task.completed_at = _utc_now()
        self.session.flush()

        self._record_audit_event(
            event_type="TASK_COMPLETED",
            entity_type="AutomationTask",
            entity_id=task.id,
            details={"summary": summary, "total_steps": task.current_step},
        )
        return task

    def _verify_step_execution(
        self,
        tool_name: str,
        params: Dict[str, Any],
        result: Dict[str, Any],
    ) -> None:
        """Independently verify target state to satisfy the 'No Blind Execution' rule."""
        if not isinstance(result, dict) or result.get("status") not in (
            "SUCCESS", "MODIFIED", "DELETED", "FILE_NOT_FOUND", "PUBLISHED_EXTERNALLY"
        ):
            raise StepVerificationError(f"Tool '{tool_name}' returned invalid execution status: {result}")

        # If tool created an artifact, verify the file physically exists on disk
        artifact_loc = result.get("artifact_location") or result.get("artifact_path")
        if artifact_loc:
            p = Path(artifact_loc)
            if not p.exists():
                raise StepVerificationError(f"Verification failed: Artifact '{p}' was not written to disk.")

    def _record_audit_event(
        self,
        event_type: str,
        entity_type: str,
        entity_id: Optional[str],
        details: Dict[str, Any],
        actor: str = "orchestrator",
    ) -> None:
        """Write an immutable audit log entry to the database."""
        event = AuditEvent(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            details_json=json.dumps(details),
            actor=actor,
            timestamp=_utc_now(),
        )
        self.session.add(event)
        self.session.flush()
