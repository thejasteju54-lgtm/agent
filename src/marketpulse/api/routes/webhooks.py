"""Webhook endpoints providing bidirectional integration between MarketPulse and n8n."""

from datetime import datetime, timezone
import json
import threading
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from marketpulse.api.deps import get_db, get_n8n_client, verify_api_key
from marketpulse.api.schemas import (
    NotificationRequest,
    StatusCallbackPayload,
    TaskWebhookRequest,
    TaskWebhookResponse,
)
from marketpulse.config import mp_settings
from marketpulse.logging.setup import get_logger
from marketpulse.n8n.client import N8nClient
from marketpulse.storage.models import (
    ApprovalRecord,
    ArtifactRecord,
    AuditEvent,
    AutomationTask,
    TaskStatus,
)

logger = get_logger(__name__)

router = APIRouter(tags=["Webhook Integration"])


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/task", response_model=TaskWebhookResponse)
def handle_task_webhook(
    payload: TaskWebhookRequest,
    db: Session = Depends(get_db),
    n8n: N8nClient = Depends(get_n8n_client),
    _auth: str = Depends(verify_api_key),
) -> TaskWebhookResponse:
    """Trigger or enqueue a task from n8n or an external workflow webhook.

    Returns task ID promptly for long-running workflows, or executes synchronously
    if sync_execute=True. Dispatches completion callback to callback_url if configured.
    """
    logger.info("Received task webhook: '%s' [auto_approve=%s, sync=%s]", payload.prompt[:60], payload.auto_approve, payload.sync_execute)

    task_id = str(uuid.uuid4())
    now_utc = datetime.now(timezone.utc)
    step_limit = 25
    requires_approval = not payload.auto_approve

    recovery_metadata = {
        "created_at": now_utc.isoformat(),
        "priority": payload.priority,
        "callback_url": payload.callback_url,
        "metadata": payload.metadata or {},
        "auto_approve": payload.auto_approve,
        "sync_execute": payload.sync_execute,
    }

    task = AutomationTask(
        id=task_id,
        task_type=payload.task_type.upper(),
        prompt=payload.prompt,
        status=TaskStatus.PENDING.value,
        step_limit=step_limit,
        current_step=0,
        requires_approval=requires_approval,
        recovery_metadata_json=json.dumps(recovery_metadata),
        started_at=now_utc,
    )
    db.add(task)

    audit = AuditEvent(
        event_type="WEBHOOK_TASK_CREATED",
        entity_type="AutomationTask",
        entity_id=task_id,
        actor=payload.metadata.get("workflow_id", "n8n_webhook") if payload.metadata else "n8n",
        details_json=json.dumps({"prompt": payload.prompt[:100], "priority": payload.priority}),
    )
    db.add(audit)
    db.commit()
    db.refresh(task)

    # If sync execution requested (e.g. for short, blocking n8n calls)
    if payload.sync_execute:
        from marketpulse.agent.orchestrator import TaskOrchestrator
        orchestrator = TaskOrchestrator(session=db)
        try:
            task.status = TaskStatus.RUNNING.value
            db.commit()

            # Execute single or direct tool based on prompt keywords
            tool_name = "generate_market_brief"
            params: Dict[str, Any] = {}
            if "research" in payload.prompt.lower():
                tool_name = "execute_research_pipeline"
                params = {"prompt": payload.prompt}
            elif "news" in payload.prompt.lower() or "rss" in payload.prompt.lower():
                tool_name = "fetch_permitted_rss_feeds"

            res = orchestrator.execute_step(
                task_id=task_id,
                tool_name=tool_name,
                params=params,
                auto_approve=payload.auto_approve,
            )
            db.commit()
            db.refresh(task)

            # Query generated artifacts
            artifacts = db.query(ArtifactRecord).filter(ArtifactRecord.task_id == task_id).all()
            artifacts_list = [
                {"id": a.id, "name": a.name, "file_path": a.file_path, "content_hash": a.content_hash}
                for a in artifacts
            ]

            # Dispatch callback if requested
            if payload.callback_url:
                callback_payload = {
                    "task_id": task_id,
                    "status": task.status,
                    "summary": task.result_summary or "Completed",
                    "completed_steps": task.current_step,
                    "total_steps": task.step_limit,
                    "artifacts": artifacts_list,
                    "error": task.error_message,
                    "metadata": payload.metadata,
                }
                threading.Thread(
                    target=n8n.send_callback,
                    args=(payload.callback_url, callback_payload),
                    daemon=True,
                ).start()

            return TaskWebhookResponse(
                task_id=task_id,
                status=task.status,
                summary=task.result_summary or "Execution finished",
                plan={"steps": [{"tool": tool_name, "params": params}]},
                report={"status": res.get("status"), "result": res},
                check_url=f"/webhook/task/{task_id}",
                created_at=task.started_at.isoformat(),
            )
        except Exception as e:
            task.status = TaskStatus.FAILED.value
            task.error_message = str(e)[:300]
            db.commit()
            return TaskWebhookResponse(
                task_id=task_id,
                status=TaskStatus.FAILED.value,
                summary=f"Failed: {str(e)[:150]}",
                check_url=f"/webhook/task/{task_id}",
                created_at=task.started_at.isoformat(),
            )

    # Asynchronous return: return task_id promptly
    return TaskWebhookResponse(
        task_id=task.id,
        status=task.status,
        summary=f"Task queued. Poll /webhook/task/{task.id} for status updates.",
        check_url=f"/webhook/task/{task.id}",
        created_at=task.started_at.isoformat(),
    )


@router.get("/task/{task_id}")
def get_task_webhook_status(
    task_id: str,
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Retrieve full status, steps, approvals, and artifacts for a task (polled by n8n)."""
    task = db.query(AutomationTask).filter(AutomationTask.id == task_id).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found",
        )

    artifacts = db.query(ArtifactRecord).filter(ArtifactRecord.task_id == task_id).all()
    approvals = db.query(ApprovalRecord).filter(ApprovalRecord.task_id == task_id).all()

    return {
        "task": {
            "id": task.id,
            "task_type": task.task_type,
            "prompt": task.prompt,
            "status": task.status,
            "current_step": task.current_step,
            "step_limit": task.step_limit,
            "requires_approval": task.requires_approval,
            "result_summary": task.result_summary,
            "error_message": task.error_message,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        },
        "steps_completed": task.current_step,
        "total_steps": task.step_limit,
        "approvals": [
            {
                "id": app.id,
                "action_type": app.action_type,
                "risk_level": app.risk_level,
                "status": app.status,
            }
            for app in approvals
        ],
        "artifacts": [
            {
                "id": a.id,
                "name": a.name,
                "file_path": a.file_path,
                "content_hash": a.content_hash,
                "size_bytes": a.size_bytes,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in artifacts
        ],
    }


@router.post("/notify")
def receive_webhook_notification(
    payload: NotificationRequest,
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Handle generic notifications from n8n or external triggers with persistent audit logging."""
    logger.info("Received notification from source '%s': event='%s'", payload.source, payload.event)

    audit = AuditEvent(
        event_type=f"WEBHOOK_NOTIFY:{payload.event}",
        entity_type="SystemNotification",
        entity_id=payload.event,
        actor=payload.source,
        details_json=json.dumps(payload.data),
    )
    db.add(audit)
    db.commit()

    return {
        "status": "RECEIVED",
        "event": payload.event,
        "source": payload.source,
        "timestamp": _utc_now_iso(),
    }
