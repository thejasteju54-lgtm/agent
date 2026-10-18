"""API routes for managing and triggering permitted automation schedules."""

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from marketpulse.api.deps import get_db
from marketpulse.storage.models import (
    AuditEvent,
    AutomationTask,
    ScheduleDefinition,
    TaskStatus,
)
from marketpulse.agent.orchestrator import TaskOrchestrator
from marketpulse.logging.setup import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/schedules", tags=["Schedules & Automation"])


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------
class ScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    schedule_type: str
    cron_expression: Optional[str] = None
    timezone: str
    task_type: str
    target_symbol: Optional[str] = None
    prompt: str
    is_active: bool
    dry_run: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class CreateScheduleRequest(BaseModel):
    id: str = Field(..., description="Unique schedule identifier (e.g. 'morning_brief')")
    name: str = Field(..., description="Human readable schedule name")
    schedule_type: str = Field(default="CRON", description="CRON, INTERVAL_MINUTES, or ON_DEMAND")
    cron_expression: Optional[str] = Field(default=None, description="Standard cron string (e.g. '30 8 * * 1-5')")
    timezone: str = Field(default="Asia/Kolkata", description="Timezone (default Asia/Kolkata)")
    task_type: str = Field(default="RESEARCH", description="Task category: MARKET_BRIEF, NEWS_POLLING, WATCHLIST_EVALUATION, RESEARCH")
    target_symbol: Optional[str] = Field(default=None, description="Target company ticker if applicable")
    prompt: str = Field(..., description="Instruction or execution prompt")
    is_active: bool = Field(default=True, description="Enable or disable schedule")
    dry_run: bool = Field(default=False, description="Run in simulation mode without state modifications")


class UpdateScheduleRequest(BaseModel):
    name: Optional[str] = None
    schedule_type: Optional[str] = None
    cron_expression: Optional[str] = None
    task_type: Optional[str] = None
    target_symbol: Optional[str] = None
    prompt: Optional[str] = None
    is_active: Optional[bool] = None
    dry_run: Optional[bool] = None


class TriggerScheduleResponse(BaseModel):
    schedule_id: str
    name: str
    is_dry_run: bool
    status: str
    task_id: Optional[str] = None
    details: Dict[str, Any]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("", response_model=List[ScheduleResponse])
def list_schedules(
    active_only: bool = Query(False, description="Filter for active schedules only"),
    session: Session = Depends(get_db),
):
    """List all configured automation schedules."""
    query = session.query(ScheduleDefinition)
    if active_only:
        query = query.filter(ScheduleDefinition.is_active.is_(True))
    schedules = query.order_by(ScheduleDefinition.created_at.asc()).all()
    return schedules


@router.post("", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
def create_schedule(
    req: CreateScheduleRequest,
    session: Session = Depends(get_db),
):
    """Register or replace an automation schedule."""
    existing = session.query(ScheduleDefinition).filter_by(id=req.id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Schedule with id '{req.id}' already exists. Use PATCH to update.",
        )

    sch = ScheduleDefinition(
        id=req.id,
        name=req.name,
        schedule_type=req.schedule_type,
        cron_expression=req.cron_expression,
        timezone=req.timezone,
        task_type=req.task_type,
        target_symbol=req.target_symbol.upper() if req.target_symbol else None,
        prompt=req.prompt,
        is_active=req.is_active,
        dry_run=req.dry_run,
    )
    session.add(sch)
    session.commit()
    session.refresh(sch)
    logger.info("Created schedule '%s' (%s)", sch.id, sch.name)
    return sch


@router.get("/{schedule_id}", response_model=ScheduleResponse)
def get_schedule(
    schedule_id: str,
    session: Session = Depends(get_db),
):
    """Retrieve schedule details by ID."""
    sch = session.query(ScheduleDefinition).filter_by(id=schedule_id).first()
    if not sch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule '{schedule_id}' not found.",
        )
    return sch


@router.patch("/{schedule_id}", response_model=ScheduleResponse)
def update_schedule(
    schedule_id: str,
    req: UpdateScheduleRequest,
    session: Session = Depends(get_db),
):
    """Update active status, dry-run toggle, or cron timing of a schedule."""
    sch = session.query(ScheduleDefinition).filter_by(id=schedule_id).first()
    if not sch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule '{schedule_id}' not found.",
        )

    if req.name is not None:
        sch.name = req.name
    if req.schedule_type is not None:
        sch.schedule_type = req.schedule_type
    if req.cron_expression is not None:
        sch.cron_expression = req.cron_expression
    if req.task_type is not None:
        sch.task_type = req.task_type
    if req.target_symbol is not None:
        sch.target_symbol = req.target_symbol.upper() if req.target_symbol else None
    if req.prompt is not None:
        sch.prompt = req.prompt
    if req.is_active is not None:
        sch.is_active = req.is_active
    if req.dry_run is not None:
        sch.dry_run = req.dry_run

    sch.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(sch)
    return sch


@router.post("/{schedule_id}/trigger", response_model=TriggerScheduleResponse)
def trigger_schedule(
    schedule_id: str,
    force_dry_run: Optional[bool] = Query(None, description="Override dry_run setting for this invocation"),
    session: Session = Depends(get_db),
):
    """Trigger execution of a schedule, supporting simulation/dry-run mode."""
    sch = session.query(ScheduleDefinition).filter_by(id=schedule_id).first()
    if not sch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule '{schedule_id}' not found.",
        )

    is_dry = sch.dry_run if force_dry_run is None else force_dry_run
    now_utc = datetime.now(timezone.utc)
    sch.last_run_at = now_utc

    if is_dry:
        # Simulation / Dry Run Mode: decompose plan without mutating data
        details = {
            "mode": "DRY_RUN",
            "message": f"Simulation completed for schedule '{sch.name}'. No state changes made.",
            "planned_task_type": sch.task_type,
            "target_symbol": sch.target_symbol,
            "prompt": sch.prompt,
            "estimated_steps": 3 if sch.task_type == "RESEARCH" else 1,
            "estimated_risk": "LOW",
        }
        audit = AuditEvent(
            event_type="SCHEDULE_DRY_RUN",
            entity_type="ScheduleDefinition",
            entity_id=sch.id,
            details_json=json.dumps(details),
            actor="schedule_runner",
            timestamp=now_utc,
        )
        session.add(audit)
        session.commit()

        return TriggerScheduleResponse(
            schedule_id=sch.id,
            name=sch.name,
            is_dry_run=True,
            status="DRY_RUN_COMPLETED",
            task_id=None,
            details=details,
        )

    # Real Execution: dispatch AutomationTask
    orchestrator = TaskOrchestrator(session=session)
    task = orchestrator.submit_task(
        prompt=sch.prompt,
        task_type=sch.task_type,
        step_limit=25,
    )
    session.commit()

    details = {
        "mode": "LIVE_EXECUTION",
        "task_id": task.id,
        "task_type": task.task_type,
        "status": task.status,
    }

    audit = AuditEvent(
        event_type="SCHEDULE_TRIGGERED",
        entity_type="ScheduleDefinition",
        entity_id=sch.id,
        details_json=json.dumps(details),
        actor="schedule_runner",
        timestamp=now_utc,
    )
    session.add(audit)
    session.commit()

    return TriggerScheduleResponse(
        schedule_id=sch.id,
        name=sch.name,
        is_dry_run=False,
        status="TASK_DISPATCHED",
        task_id=task.id,
        details=details,
    )
