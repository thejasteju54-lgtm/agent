"""Human-in-the-loop approval endpoints for high-risk actions."""

import json
import uuid
from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from marketpulse.api.deps import get_db, verify_api_key
from marketpulse.api.schemas import ApprovalDecisionRequest, ApprovalItemResponse
from marketpulse.storage.models import AuditEvent

router = APIRouter(prefix="/approvals", tags=["Human Approvals"])


@router.get("", response_model=List[ApprovalItemResponse])
def list_approvals(
    status: str = Query("PENDING", description="Filter by approval status: PENDING, APPROVED, REJECTED, ALL"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> List[ApprovalItemResponse]:
    """Retrieve human-in-the-loop approval requests for high-risk actions."""
    query = db.query(AuditEvent).filter(AuditEvent.event_type.in_(["APPROVAL_REQUEST", "APPROVAL_DECISION"]))
    events = query.order_by(AuditEvent.timestamp.desc()).limit(limit * 2).all()

    # Track decision status by item ID
    decisions = {}
    for ev in events:
        if ev.event_type == "APPROVAL_DECISION" and ev.entity_id:
            try:
                data = json.loads(ev.details_json or "{}")
                decisions[ev.entity_id] = {
                    "status": data.get("decision", "APPROVED"),
                    "decided_at": ev.timestamp,
                }
            except Exception:
                pass

    items = []
    for ev in events:
        if ev.event_type == "APPROVAL_REQUEST":
            approval_id = ev.entity_id or ev.id
            dec = decisions.get(approval_id)
            item_status = dec["status"] if dec else "PENDING"
            decided_at = dec["decided_at"] if dec else None

            if status != "ALL" and item_status != status:
                continue

            details = {}
            if ev.details_json:
                try:
                    details = json.loads(ev.details_json)
                except Exception:
                    pass

            items.append(
                ApprovalItemResponse(
                    id=approval_id,
                    action_type=details.get("action_type", "EXTERNAL_DISPATCH"),
                    description=details.get("description", "Requires manual confirmation"),
                    status=item_status,
                    requested_by=ev.actor,
                    payload=details.get("payload"),
                    created_at=ev.timestamp,
                    decided_at=decided_at,
                )
            )

    return items[:limit]


@router.post("/{approval_id}/decide", response_model=ApprovalItemResponse)
def decide_approval(
    approval_id: str,
    payload: ApprovalDecisionRequest,
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> ApprovalItemResponse:
    """Approve or reject a pending human-in-the-loop action."""
    now_utc = datetime.now(timezone.utc)

    # Check if request exists
    request_event = (
        db.query(AuditEvent)
        .filter(AuditEvent.event_type == "APPROVAL_REQUEST", AuditEvent.entity_id == approval_id)
        .first()
    )
    if not request_event:
        raise HTTPException(status_code=404, detail="Approval request not found")

    decision_event = AuditEvent(
        id=str(uuid.uuid4()),
        event_type="APPROVAL_DECISION",
        entity_type="APPROVAL",
        entity_id=approval_id,
        actor="human_operator",
        details_json=json.dumps({
            "decision": payload.decision,
            "rationale": payload.rationale,
            "decided_at": now_utc.isoformat(),
        }),
        timestamp=now_utc,
    )
    db.add(decision_event)
    db.commit()

    req_details = {}
    if request_event.details_json:
        try:
            req_details = json.loads(request_event.details_json)
        except Exception:
            pass

    return ApprovalItemResponse(
        id=approval_id,
        action_type=req_details.get("action_type", "EXTERNAL_ACTION"),
        description=req_details.get("description", "Manual approval action"),
        status=payload.decision,
        requested_by=request_event.actor,
        payload=req_details.get("payload"),
        created_at=request_event.timestamp,
        decided_at=now_utc,
    )
