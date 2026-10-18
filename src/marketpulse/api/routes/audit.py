"""Audit trail inspection endpoints."""

import json
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from marketpulse.api.deps import get_db, verify_api_key
from marketpulse.api.schemas import AuditEventResponse
from marketpulse.storage.models import AuditEvent

router = APIRouter(tags=["Audit Trail"])


@router.get("/audit", response_model=List[AuditEventResponse])
def list_audit_events(
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> List[AuditEventResponse]:
    """Inspect immutable audit events for provenance, security, and execution tracking."""
    query = db.query(AuditEvent)
    if event_type:
        query = query.filter(AuditEvent.event_type == event_type.upper())

    events = query.order_by(AuditEvent.timestamp.desc()).limit(limit).all()
    results = []
    for ev in events:
        details = None
        correlation_id = None
        if ev.details_json:
            try:
                details = json.loads(ev.details_json)
                correlation_id = details.get("correlation_id")
            except Exception:
                details = {"raw": ev.details_json}

        results.append(
            AuditEventResponse(
                id=ev.id,
                event_type=ev.event_type,
                entity_type=ev.entity_type or "SYSTEM",
                entity_id=ev.entity_id,
                actor=ev.actor,
                details=details,
                created_at=ev.timestamp,
                correlation_id=correlation_id,
            )
        )
    return results
