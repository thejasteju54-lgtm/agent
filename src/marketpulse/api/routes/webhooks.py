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


def _resolve_tool_and_params(prompt: str, task_type: str, company_symbol: Optional[str]) -> tuple[str, Dict[str, Any]]:
    prompt_lower = (prompt or "").lower()
    t_type = (task_type or "").upper()
    if t_type == "RESEARCH" or "research" in prompt_lower or "analyze" in prompt_lower or company_symbol:
        return "generate_research_report", {"prompt": prompt, "company_symbol": company_symbol}
    elif "news" in prompt_lower or "rss" in prompt_lower:
        return "collect_source_evidence", {"target_symbol": company_symbol}
    elif t_type == "MARKET_BRIEF" or "brief" in prompt_lower:
        return "generate_market_brief", {}
    elif "alert" in prompt_lower or "watchlist" in prompt_lower:
        return "evaluate_watchlist_alerts", {}
    return "generate_market_brief", {}


def _execute_task_in_background(
    task_id: str,
    prompt: str,
    company_symbol: Optional[str] = None,
    task_type: str = "RESEARCH",
    auto_approve: bool = False,
    callback_url: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Asynchronously execute research or automation task in a background worker."""
    from marketpulse.storage.database import get_session
    from marketpulse.storage.models import AutomationTask, TaskStatus, ArtifactRecord
    from marketpulse.agent.orchestrator import TaskOrchestrator
    from marketpulse.n8n.client import N8nClient

    logger.info("Starting background worker for task '%s' [type=%s]", task_id, task_type)
    with get_session() as session:
        task = session.query(AutomationTask).filter(AutomationTask.id == task_id).first()
        if not task:
            logger.error("Task '%s' not found for background execution", task_id)
            return

        task.status = TaskStatus.RUNNING.value
        session.commit()

        tool_name, params = _resolve_tool_and_params(prompt, task_type, company_symbol)
        orchestrator = TaskOrchestrator(session=session)

        try:
            res = orchestrator.execute_step(
                task_id=task_id,
                tool_name=tool_name,
                params=params,
                auto_approve=auto_approve,
            )
            step_status = res.get("status")
            if step_status == "SUCCESS":
                task.status = TaskStatus.COMPLETED.value
                task.completed_at = datetime.now(timezone.utc)
                task.result_summary = f"Executed {tool_name} successfully."
            elif step_status == "AWAITING_APPROVAL":
                task.status = TaskStatus.AWAITING_APPROVAL.value
            elif step_status == "FAILED":
                task.status = TaskStatus.FAILED.value
                task.error_message = res.get("error") or "Step execution failed"
                task.completed_at = datetime.now(timezone.utc)

            session.commit()
            session.refresh(task)

            # Query generated artifacts
            artifacts = session.query(ArtifactRecord).filter(ArtifactRecord.task_id == task_id).all()
            artifacts_list = [
                {"id": a.id, "name": a.name, "file_path": a.file_path, "content_hash": a.content_hash}
                for a in artifacts
            ]

            if callback_url:
                n8n_client = N8nClient()
                callback_payload = {
                    "task_id": task_id,
                    "status": task.status,
                    "summary": task.result_summary or "Completed",
                    "completed_steps": task.current_step,
                    "total_steps": task.step_limit,
                    "artifacts": artifacts_list,
                    "error": task.error_message,
                    "metadata": metadata or {},
                }
                n8n_client.send_callback(callback_url, callback_payload)

            logger.info("Background task '%s' finished with status '%s'", task_id, task.status)
        except Exception as e:
            logger.error("Background task '%s' encountered error: %s", task_id, e)
            task.status = TaskStatus.FAILED.value
            task.error_message = str(e)[:300]
            task.completed_at = datetime.now(timezone.utc)
            session.commit()

            if callback_url:
                try:
                    n8n_client = N8nClient()
                    n8n_client.send_callback(callback_url, {
                        "task_id": task_id,
                        "status": TaskStatus.FAILED.value,
                        "summary": f"Failed: {str(e)[:150]}",
                        "error": str(e)[:300],
                        "metadata": metadata or {},
                    })
                except Exception:
                    pass


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
            company_sym = getattr(payload, "company_symbol", None)
            tool_name, params = _resolve_tool_and_params(payload.prompt, payload.task_type, company_sym)

            res = orchestrator.execute_step(
                task_id=task_id,
                tool_name=tool_name,
                params=params,
                auto_approve=payload.auto_approve,
            )
            step_status = res.get("status")
            if step_status == "SUCCESS":
                task.status = TaskStatus.COMPLETED.value
                task.completed_at = datetime.now(timezone.utc)
                task.result_summary = f"Executed {tool_name} successfully."
            elif step_status == "AWAITING_APPROVAL":
                task.status = TaskStatus.AWAITING_APPROVAL.value
            elif step_status == "FAILED":
                task.status = TaskStatus.FAILED.value
                task.error_message = res.get("error") or "Execution failed"
                task.completed_at = datetime.now(timezone.utc)

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
            task.completed_at = datetime.now(timezone.utc)
            db.commit()
            return TaskWebhookResponse(
                task_id=task_id,
                status=TaskStatus.FAILED.value,
                summary=f"Failed: {str(e)[:150]}",
                check_url=f"/webhook/task/{task_id}",
                created_at=task.started_at.isoformat(),
            )

    # Asynchronous return: launch background execution thread only if auto_approved,
    # otherwise remain in PENDING status awaiting approval.
    company_sym = getattr(payload, "company_symbol", None)
    if payload.auto_approve:
        threading.Thread(
            target=_execute_task_in_background,
            args=(
                task.id,
                payload.prompt,
                company_sym,
                payload.task_type,
                payload.auto_approve,
                payload.callback_url,
                payload.metadata,
            ),
            daemon=True,
        ).start()
        summary_msg = f"Task queued and executing in background. Poll /webhook/task/{task.id} for status updates."
    else:
        logger.info("Task '%s' queued in PENDING state awaiting human approval", task.id)
        summary_msg = f"Task queued awaiting approval. Poll /webhook/task/{task.id} for status updates."

    return TaskWebhookResponse(
        task_id=task.id,
        status=task.status,
        summary=summary_msg,
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

    task_dict = {
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
    }

    return {
        "task": task_dict,
        "status": task.status,
        "current_step": task.current_step,
        "step_limit": task.step_limit,
        "result_summary": task.result_summary,
        "error_message": task.error_message,
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

    # Immediately halt all active tasks if this is an emergency stop signal
    halted_count = 0
    if "EMERGENCY" in payload.event.upper() or "HALT" in payload.event.upper():
        active_tasks = db.query(AutomationTask).filter(
            AutomationTask.status.in_([TaskStatus.RUNNING.value, TaskStatus.PENDING.value])
        ).all()
        for t in active_tasks:
            t.status = TaskStatus.CANCELLED.value
            t.error_message = f"Halted by global emergency stop ({payload.event})"
            t.completed_at = datetime.now(timezone.utc)
            halted_count += 1
        db.commit()
        logger.warning("EMERGENCY STOP ENFORCED: Cancelled %d active automation tasks", halted_count)

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
        "halted_tasks_count": halted_count,
        "timestamp": _utc_now_iso(),
    }
