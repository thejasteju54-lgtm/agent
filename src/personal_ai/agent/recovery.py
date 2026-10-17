"""Task Interruption Detection, Conservative Recovery, and Diagnostic Reporting."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from personal_ai.agent.task_models import RiskLevel, StepStatus, TaskStatus
from personal_ai.logging.setup import get_logger
from personal_ai.storage.database import Database, get_db
from personal_ai.storage.repositories import StepRepository, TaskRepository

logger = get_logger(__name__)

# Tools that produce external or irreversible state changes
IRREVERSIBLE_TOOLS = {
    "write_file",
    "delete_file",
    "desktop_mouse_click",
    "desktop_type_text",
    "desktop_press_hotkey",
    "browser_click",
    "browser_fill",
}


@dataclass
class InterruptionDiagnosis:
    """Diagnostic details of an interrupted automation task."""
    task_id: str
    prompt: str
    status: str
    created_at: str
    updated_at: str
    completed_steps: List[Dict[str, Any]] = field(default_factory=list)
    interrupted_step: Optional[Dict[str, Any]] = None
    pending_steps: List[Dict[str, Any]] = field(default_factory=list)
    is_irreversible: bool = False
    can_auto_resume: bool = False
    recommendation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "prompt": self.prompt,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_steps_count": len(self.completed_steps),
            "pending_steps_count": len(self.pending_steps),
            "interrupted_step": self.interrupted_step,
            "is_irreversible": self.is_irreversible,
            "can_auto_resume": self.can_auto_resume,
            "recommendation": self.recommendation,
        }


class TaskRecoveryManager:
    """Manages detection of crashed or interrupted task runs, enforcing conservative recovery policies."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()
        self.task_repo = TaskRepository(self.db)
        self.step_repo = StepRepository(self.db)

    def detect_interrupted_tasks(self, task_id: Optional[str] = None) -> List[InterruptionDiagnosis]:
        """Identify tasks that were left in RUNNING or VERIFYING state without completing.

        Args:
            task_id: Optional specific task ID to diagnose. If None, diagnoses all stuck tasks.
        """
        diagnoses = []
        with self.db.connection() as conn:
            if task_id:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE id = ? AND status IN ('RUNNING', 'VERIFYING', 'PLANNING')",
                    (task_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE status IN ('RUNNING', 'VERIFYING', 'PLANNING') ORDER BY created_at DESC"
                ).fetchall()

        for row in rows:
            t = dict(row)
            tid = t["id"]
            steps = self.step_repo.get_steps_for_task(tid)

            completed = []
            interrupted = None
            pending = []

            for step in steps:
                st = step.get("status")
                if st == StepStatus.COMPLETED.value:
                    completed.append(step)
                elif st in (StepStatus.RUNNING.value, StepStatus.AWAITING_APPROVAL.value):
                    if interrupted is None:
                        interrupted = step
                    else:
                        pending.append(step)
                else:
                    pending.append(step)

            is_irreversible = False
            can_auto_resume = True
            recommendation = "All completed steps verified. Safe to resume from next pending step."

            if interrupted:
                tool_name = interrupted.get("tool_name", "")
                risk = interrupted.get("risk_level", "low")

                if tool_name in IRREVERSIBLE_TOOLS or risk in ("high", "medium"):
                    is_irreversible = True
                    can_auto_resume = False
                    recommendation = (
                        f"DO NOT AUTO-REPEAT: Step {interrupted.get('step_number')} used '{tool_name}' "
                        f"({risk} risk). Completion status is uncertain; manual inspection required."
                    )
                else:
                    recommendation = (
                        f"Step {interrupted.get('step_number')} used read-only/idempotent tool '{tool_name}'. "
                        "Safe to retry step or resume execution."
                    )
            elif pending:
                first_pending = pending[0]
                tool_name = first_pending.get("tool_name", "")
                risk = first_pending.get("risk_level", "low")
                if tool_name in IRREVERSIBLE_TOOLS or risk == "high":
                    is_irreversible = True
                    can_auto_resume = False
                    recommendation = f"Next pending step '{tool_name}' has high/medium impact. Recommend user review before resuming."

            diagnosis = InterruptionDiagnosis(
                task_id=tid,
                prompt=t.get("prompt", ""),
                status=t.get("status", ""),
                created_at=t.get("created_at", ""),
                updated_at=t.get("updated_at", ""),
                completed_steps=completed,
                interrupted_step=interrupted,
                pending_steps=pending,
                is_irreversible=is_irreversible,
                can_auto_resume=can_auto_resume,
                recommendation=recommendation,
            )
            diagnoses.append(diagnosis)

        return diagnoses

    def generate_recovery_report(self, task_id: Optional[str] = None) -> str:
        """Produce a formatted, human-readable recovery report for all or specific interrupted tasks."""
        diagnoses = self.detect_interrupted_tasks(task_id=task_id)

        if not diagnoses:
            return "No interrupted or stuck tasks found. All task states are consistent."

        lines = [
            "# Personal AI Interrupted Execution Recovery Report",
            f"Generated at: {datetime.now(timezone.utc).isoformat()}",
            f"Found {len(diagnoses)} interrupted task(s) requiring attention:\n",
            "=" * 70,
        ]

        for idx, d in enumerate(diagnoses, 1):
            lines.append(f"\n## Interrupted Task #{idx}: {d.task_id}")
            lines.append(f"- **Prompt**: {d.prompt}")
            lines.append(f"- **Status When Interrupted**: {d.status}")
            lines.append(f"- **Started**: {d.created_at}")
            lines.append(f"- **Completed Steps**: {len(d.completed_steps)}")
            lines.append(f"- **Pending Steps**: {len(d.pending_steps)}")

            if d.completed_steps:
                lines.append("\n  **Verified Completed Steps**:")
                for cs in d.completed_steps:
                    lines.append(f"  - Step {cs.get('step_number')}: {cs.get('tool_name')} (completed at {cs.get('completed_at')})")

            if d.interrupted_step:
                s = d.interrupted_step
                lines.append(f"\n  **Interrupted In-Flight Step**:")
                lines.append(f"  - Step Number: {s.get('step_number')}")
                lines.append(f"  - Tool: {s.get('tool_name')}")
                lines.append(f"  - Risk Level: {s.get('risk_level')}")
                lines.append(f"  - Input Parameters: {s.get('input_params')}")

            lines.append(f"\n- **Risk Assessment**: {'IRREVERSIBLE / UNCERTAIN' if d.is_irreversible else 'IDEMPOTENT / SAFE'}")
            lines.append(f"- **Can Auto-Resume**: {'YES' if d.can_auto_resume else 'NO (Requires explicit confirmation)'}")
            lines.append(f"- **Policy Recommendation**: {d.recommendation}")
            lines.append("-" * 70)

        return "\n".join(lines)

    def mark_interrupted_tasks_failed(
        self,
        task_id: Optional[str] = None,
        reason: str = "Execution interrupted due to process restart/shutdown",
    ) -> int:
        """Mark stuck tasks and their in-flight steps as FAILED with an explanatory recovery message."""
        diagnoses = self.detect_interrupted_tasks(task_id=task_id)
        count = 0

        for d in diagnoses:
            summary = f"Interrupted: {d.recommendation}"
            error_msg = f"{reason}. {d.recommendation}"
            self.task_repo.update_status(
                d.task_id,
                TaskStatus.FAILED.value,
                error_message=error_msg,
                result_summary=summary,
            )

            # Also update any in-flight steps
            if d.interrupted_step:
                self.step_repo.update_step(
                    d.interrupted_step["id"],
                    StepStatus.FAILED.value,
                    error_message=reason,
                )
            count += 1
            logger.info("Marked interrupted task %s as FAILED: %s", d.task_id, reason)

        return count
