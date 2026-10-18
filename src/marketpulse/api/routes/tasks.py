"""Persistent automation task endpoints for MarketPulse AI.

Provides bounded execution, cancellation, recovery metadata, and artifact linkage.
"""

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from marketpulse.api.deps import get_db, verify_api_key
from marketpulse.api.schemas import (
    ArtifactItemResponse,
    TaskCancelRequest,
    TaskCreateRequest,
    TaskResponse,
)
from marketpulse.logging.setup import get_logger
from marketpulse.storage.models import ArtifactRecord, AutomationTask, TaskStatus

logger = get_logger(__name__)

router = APIRouter(prefix="/tasks", tags=["Automation Tasks"])


def _to_task_response(task: AutomationTask, session: Session) -> TaskResponse:
    artifacts_count = (
        session.query(ArtifactRecord).filter(ArtifactRecord.task_id == task.id).count()
    )
    return TaskResponse(
        id=task.id,
        task_type=task.task_type,
        prompt=task.prompt,
        status=task.status,
        idempotency_key=task.idempotency_key,
        step_limit=task.step_limit,
        current_step=task.current_step,
        requires_approval=task.requires_approval,
        approval_status=task.approval_status,
        started_at=task.started_at,
        completed_at=task.completed_at,
        cancellation_reason=task.cancellation_reason,
        retry_count=task.retry_count,
        result_summary=task.result_summary,
        error_message=task.error_message,
        artifacts_count=artifacts_count,
    )


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreateRequest,
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> TaskResponse:
    """Create a new automation or research task with idempotency protection and bounded limits."""
    # Check idempotency key if provided
    if payload.idempotency_key:
        existing = (
            db.query(AutomationTask)
            .filter(AutomationTask.idempotency_key == payload.idempotency_key)
            .first()
        )
        if existing:
            logger.info("Found existing task for idempotency key %s: %s", payload.idempotency_key, existing.id)
            return _to_task_response(existing, db)

    task_id = str(uuid.uuid4())
    now_utc = datetime.now(timezone.utc)
    recovery_metadata = {
        "created_at": now_utc.isoformat(),
        "step_limit": payload.step_limit,
        "auto_approve": payload.auto_approve,
        "metadata": payload.metadata or {},
    }

    task = AutomationTask(
        id=task_id,
        task_type=payload.task_type.upper(),
        prompt=payload.prompt,
        status=TaskStatus.PENDING.value,
        idempotency_key=payload.idempotency_key,
        step_limit=payload.step_limit,
        current_step=0,
        requires_approval=not payload.auto_approve,
        recovery_metadata_json=json.dumps(recovery_metadata),
        started_at=now_utc,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    logger.info("Created new AutomationTask %s [%s]: '%s'", task.id, task.status, task.prompt[:60])
    return _to_task_response(task, db)


@router.get("", response_model=List[TaskResponse])
def list_tasks(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> List[TaskResponse]:
    """List automation tasks with optional status filtering."""
    query = db.query(AutomationTask)
    if status_filter:
        query = query.filter(AutomationTask.status == status_filter.upper())
    tasks = query.order_by(AutomationTask.started_at.desc()).limit(limit).all()
    return [_to_task_response(t, db) for t in tasks]


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> TaskResponse:
    """Retrieve detailed state of a specific automation task."""
    task = db.query(AutomationTask).filter(AutomationTask.id == task_id).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID '{task_id}' not found",
        )
    return _to_task_response(task, db)


@router.post("/{task_id}/cancel", response_model=TaskResponse)
def cancel_task(
    task_id: str,
    payload: TaskCancelRequest,
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> TaskResponse:
    """Safely cancel an in-flight or pending task, recording cancellation metadata."""
    task = db.query(AutomationTask).filter(AutomationTask.id == task_id).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID '{task_id}' not found",
        )

    if task.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel task in terminal state '{task.status}'",
        )

    task.status = TaskStatus.CANCELLED.value
    task.cancellation_reason = payload.reason
    task.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(task)

    logger.warning("Task %s was cancelled: %s", task.id, payload.reason)
    return _to_task_response(task, db)


@router.get("/{task_id}/artifacts", response_model=List[ArtifactItemResponse])
def get_task_artifacts(
    task_id: str,
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> List[ArtifactItemResponse]:
    """List all artifacts generated and registered for a specific task."""
    task = db.query(AutomationTask).filter(AutomationTask.id == task_id).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID '{task_id}' not found",
        )

    artifacts = (
        db.query(ArtifactRecord)
        .filter(ArtifactRecord.task_id == task_id)
        .order_by(ArtifactRecord.created_at.desc())
        .all()
    )
    return [
        ArtifactItemResponse(
            id=a.id,
            task_id=a.task_id,
            job_id=a.job_id,
            name=a.name,
            artifact_type=a.artifact_type,
            file_path=a.file_path,
            content_hash=a.content_hash,
            mime_type=a.mime_type,
            size_bytes=a.size_bytes,
            created_at=a.created_at,
        )
        for a in artifacts
    ]


@router.post("/{task_id}/step", response_model=Dict[str, Any])
def execute_task_step(
    task_id: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Execute a single bounded step under permission controls via TaskOrchestrator."""
    from marketpulse.agent.orchestrator import TaskOrchestrator
    orchestrator = TaskOrchestrator(session=db)
    tool_name = payload.get("tool_name")
    if not tool_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tool_name is required")
    params = payload.get("params", {})
    auto_approve = payload.get("auto_approve", False)
    try:
        result = orchestrator.execute_step(task_id=task_id, tool_name=tool_name, params=params, auto_approve=auto_approve)
        db.commit()
        return result
    except PermissionError as e:
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        db.commit()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{task_id}/approvals", response_model=List[Dict[str, Any]])
def list_task_approvals(
    task_id: str,
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> List[Dict[str, Any]]:
    """List pending and resolved human approvals for a task."""
    from marketpulse.storage.models import ApprovalRecord
    approvals = db.query(ApprovalRecord).filter_by(task_id=task_id).order_by(ApprovalRecord.created_at.desc()).all()
    return [
        {
            "id": a.id,
            "task_id": a.task_id,
            "action_type": a.action_type,
            "action_description": a.action_description,
            "risk_level": a.risk_level,
            "status": a.status,
            "requested_by": a.requested_by,
            "resolved_by": a.resolved_by,
            "resolution_reason": a.resolution_reason,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
        }
        for a in approvals
    ]


@router.post("/approvals/{approval_id}/resolve", response_model=Dict[str, Any])
def resolve_task_approval(
    approval_id: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Approve or reject a pending human approval request."""
    from marketpulse.agent.orchestrator import TaskOrchestrator
    orchestrator = TaskOrchestrator(session=db)
    decision = payload.get("decision", "APPROVED")
    resolved_by = payload.get("resolved_by", "analyst")
    reason = payload.get("reason", "Operator decision via API")
    try:
        appr = orchestrator.resolve_approval(
            approval_id=approval_id,
            decision=decision,
            resolved_by=resolved_by,
            reason=reason,
        )
        db.commit()
        return {
            "approval_id": appr.id,
            "task_id": appr.task_id,
            "status": appr.status,
            "resolved_by": appr.resolved_by,
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
