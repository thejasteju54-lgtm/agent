"""Alert rule management and watchlist alert evaluation endpoints."""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from marketpulse.api.deps import get_db, verify_api_key
from marketpulse.api.schemas import AlertResponse, AlertRuleCreateRequest
from marketpulse.storage.models import AlertEventRecord, AlertRule, Article, AuditEvent, Company, Watchlist, WatchlistItem

router = APIRouter(tags=["Alerts"])


@router.get("/alerts/events")
def list_alert_events(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Retrieve recent alert events for dashboard display."""
    events = (
        db.query(AlertEventRecord)
        .order_by(AlertEventRecord.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": ev.id,
            "company_symbol": ev.company_symbol,
            "severity": ev.severity,
            "event_category": ev.event_category,
            "title": ev.title,
            "trigger_rationale": ev.trigger_rationale,
            "source_url": ev.source_url,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
        }
        for ev in events
    ]


@router.get("/alerts", response_model=List[AlertResponse])
def list_alerts(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> List[AlertResponse]:
    """Retrieve recent triggered alerts from audit records."""
    audit_events = (
        db.query(AuditEvent)
        .filter(AuditEvent.event_type == "ALERT_TRIGGERED")
        .order_by(AuditEvent.timestamp.desc())
        .limit(limit)
        .all()
    )

    alerts = []
    for ev in audit_events:
        details = {}
        if ev.details_json:
            try:
                details = json.loads(ev.details_json)
            except Exception:
                pass
        alerts.append(
            AlertResponse(
                id=ev.id,
                alert_type=details.get("alert_type", "MATERIAL_DISCLOSURE"),
                ticker=details.get("ticker"),
                message=details.get("message", "Watchlist condition matched"),
                triggered_at=ev.timestamp,
                deduplication_hash=details.get("dedup_hash", ev.id),
            )
        )
    return alerts


@router.post("/alerts/evaluate")
def evaluate_watchlist_alerts(
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """Evaluate active watchlist alert rules against recent articles and disclosures."""
    now_utc = datetime.now(timezone.utc)
    rules = db.query(AlertRule).filter(AlertRule.is_active == True).all()

    triggered_count = 0
    suppressed_count = 0

    # Get recent articles
    recent_articles = db.query(Article).order_by(Article.retrieved_at.desc()).limit(15).all()

    for rule in rules:
        target_ticker = None
        if rule.company_id:
            comp = db.query(Company).filter(Company.id == rule.company_id).first()
            target_ticker = comp.symbol if comp else None

        # Check recent articles for company
        for art in recent_articles:
            if target_ticker and (target_ticker in art.content_normalized or target_ticker in art.title):
                # Deduplication key based on rule_id + article_id
                raw_hash = f"{rule.id}:{art.id}"
                dedup_hash = hashlib.sha256(raw_hash.encode()).hexdigest()

                # Check if already triggered recently
                existing = (
                    db.query(AuditEvent)
                    .filter(
                        AuditEvent.event_type == "ALERT_TRIGGERED",
                        AuditEvent.entity_id == dedup_hash,
                    )
                    .first()
                )

                if existing:
                    suppressed_count += 1
                    continue

                # Trigger alert
                audit = AuditEvent(
                    event_type="ALERT_TRIGGERED",
                    entity_type="ALERT",
                    entity_id=dedup_hash,
                    actor="alert_engine",
                    details_json=json.dumps({
                        "rule_id": rule.id,
                        "ticker": target_ticker,
                        "alert_type": rule.rule_type,
                        "message": f"Material event detected for {target_ticker} in '{art.title}'",
                        "article_id": art.id,
                        "dedup_hash": dedup_hash,
                    }),
                    timestamp=now_utc,
                )
                db.add(audit)
                rule.last_triggered_at = now_utc
                triggered_count += 1

    db.commit()
    return {
        "status": "EVALUATED",
        "rules_checked": len(rules),
        "alerts_triggered": triggered_count,
        "suppressed_by_cooldown": suppressed_count,
        "timestamp": now_utc.isoformat(),
    }


@router.get("/alert-rules")
def list_alert_rules(
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """List all configured watchlist alert rules."""
    rules = db.query(AlertRule).all()
    return [
        {
            "id": r.id,
            "watchlist_id": r.watchlist_id,
            "company_id": r.company_id,
            "rule_type": r.rule_type,
            "is_active": r.is_active,
            "cooldown_minutes": r.cooldown_minutes,
            "last_triggered_at": r.last_triggered_at,
        }
        for r in rules
    ]


@router.post("/alert-rules", status_code=201)
def create_alert_rule(
    payload: AlertRuleCreateRequest,
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """Create a new alert rule for a watchlist."""
    wl = db.query(Watchlist).filter(Watchlist.id == payload.watchlist_id).first()
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    rule = AlertRule(
        watchlist_id=payload.watchlist_id,
        rule_type=payload.rule_type,
        threshold_config_json=json.dumps({
            "condition": payload.condition_expr,
            "threshold": payload.threshold_value,
        }),
        is_active=True,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return {"id": rule.id, "status": "CREATED", "rule_type": rule.rule_type}
