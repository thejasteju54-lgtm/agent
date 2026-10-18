"""Watchlist Intelligence module for Indian equities.

Enforces:
1. Configurable symbol watchlist management.
2. Announcement and disclosure detection for monitored tickers.
3. Configurable notification thresholds and cooldown logic.
4. Persistent recording of why each alert was generated into mp_alert_events.
"""

from datetime import datetime, timezone, timedelta
import json
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from marketpulse.storage.models import (
    AlertEventRecord,
    AlertRule,
    Company,
    EvidenceRecord,
    Watchlist,
    WatchlistItem,
)
from marketpulse.research.news_intelligence import NewsEventCategory, EVENT_CATEGORY_KEYWORDS


class WatchlistAlertItem(BaseModel):
    """Structured representation of a triggered watchlist alert."""
    alert_id: str
    watchlist_name: str
    company_symbol: str
    company_name: str
    severity: str  # INFO, MEDIUM, HIGH, CRITICAL
    event_category: str
    title: str
    trigger_rationale: str
    source_url: Optional[str] = None
    created_at: str


class WatchlistAlertEvaluation(BaseModel):
    """Summary of watchlist evaluation run across evidence and news."""
    evaluated_watchlist_count: int
    evaluated_symbol_count: int
    alerts_triggered_count: int
    alerts: List[WatchlistAlertItem] = Field(default_factory=list)


class WatchlistIntelligenceManager:
    """Manager module implementing Capability D (Watchlist Intelligence)."""

    def __init__(self, session: Session):
        self.session = session

    def get_or_create_watchlist(self, name: str, description: Optional[str] = None) -> Watchlist:
        """Retrieve existing watchlist or create a new one idempotently."""
        wl = self.session.query(Watchlist).filter_by(name=name).first()
        if not wl:
            wl = Watchlist(name=name, description=description or f"Monitored watchlist: {name}")
            self.session.add(wl)
            self.session.flush()
        return wl

    def add_symbol_to_watchlist(
        self,
        watchlist_name: str,
        symbol: str,
        notes: Optional[str] = None,
    ) -> WatchlistItem:
        """Add an Indian listed company symbol to the specified watchlist."""
        wl = self.get_or_create_watchlist(watchlist_name)
        company = self.session.query(Company).filter_by(symbol=symbol.upper()).first()
        if not company:
            # Create company record if missing from canonical registry
            company = Company(
                symbol=symbol.upper(),
                name=f"{symbol.upper()} India",
                market_cap_tier="MID_CAP",
            )
            self.session.add(company)
            self.session.flush()

        item = (
            self.session.query(WatchlistItem)
            .filter_by(watchlist_id=wl.id, company_id=company.id)
            .first()
        )
        if not item:
            item = WatchlistItem(
                watchlist_id=wl.id,
                company_id=company.id,
                notes=notes,
            )
            self.session.add(item)
            self.session.flush()
        return item

    def remove_symbol_from_watchlist(self, watchlist_name: str, symbol: str) -> bool:
        """Remove a symbol from the specified watchlist."""
        wl = self.session.query(Watchlist).filter_by(name=watchlist_name).first()
        if not wl:
            return False
        company = self.session.query(Company).filter_by(symbol=symbol.upper()).first()
        if not company:
            return False

        item = (
            self.session.query(WatchlistItem)
            .filter_by(watchlist_id=wl.id, company_id=company.id)
            .first()
        )
        if item:
            self.session.delete(item)
            self.session.flush()
            return True
        return False

    def list_watchlist_symbols(self, watchlist_name: str) -> List[str]:
        """List all company symbols enrolled in the watchlist."""
        wl = self.session.query(Watchlist).filter_by(name=watchlist_name).first()
        if not wl:
            return []
        return [item.company.symbol for item in wl.items if item.company]

    def add_alert_rule(
        self,
        watchlist_name: str,
        rule_type: str = "MATERIAL_DISCLOSURE",
        threshold_config: Optional[Dict[str, Any]] = None,
        cooldown_minutes: int = 60,
    ) -> AlertRule:
        """Add an automated alert rule to a watchlist."""
        wl = self.get_or_create_watchlist(watchlist_name)
        config_json = json.dumps(threshold_config or {"min_materiality": 0.8})
        rule = AlertRule(
            watchlist_id=wl.id,
            rule_type=rule_type,
            threshold_config_json=config_json,
            cooldown_minutes=cooldown_minutes,
            is_active=True,
        )
        self.session.add(rule)
        self.session.flush()
        return rule

    def evaluate_evidence_records(
        self,
        evidence_records: List[EvidenceRecord],
    ) -> WatchlistAlertEvaluation:
        """Evaluate incoming evidence records against all active watchlists and alert rules."""
        watchlists = self.session.query(Watchlist).all()
        triggered_alerts: List[WatchlistAlertItem] = []
        monitored_symbols = set()
        now_utc = datetime.now(timezone.utc)

        for wl in watchlists:
            # Map of enrolled symbols in this watchlist
            enrolled = {item.company.symbol: item.company for item in wl.items if item.company}
            monitored_symbols.update(enrolled.keys())

            # Active rules for this watchlist
            rules = [r for r in wl.alert_rules if r.is_active]
            if not rules:
                # Default rule if none defined: alert on materiality >= 0.75
                default_rule = AlertRule(
                    watchlist_id=wl.id,
                    rule_type="MATERIAL_DISCLOSURE",
                    threshold_config_json=json.dumps({"min_materiality": 0.75}),
                    cooldown_minutes=60,
                )
                self.session.add(default_rule)
                self.session.flush()
                rules = [default_rule]

            for ev in evidence_records:
                if not ev.company_symbol:
                    continue

                sym = ev.company_symbol.upper()
                if sym not in enrolled:
                    continue

                company = enrolled[sym]
                passage = ev.extracted_passage.lower()

                # Evaluate against each rule
                for rule in rules:
                    # Check cooldown
                    if rule.last_triggered_at:
                        cooldown_delta = timedelta(minutes=rule.cooldown_minutes)
                        rule_last = rule.last_triggered_at
                        if rule_last.tzinfo is None:
                            rule_last = rule_last.replace(tzinfo=timezone.utc)
                        if (now_utc - rule_last) < cooldown_delta:
                            continue

                    cfg = json.loads(rule.threshold_config_json or "{}")
                    min_mat = cfg.get("min_materiality", 0.75)
                    target_category = cfg.get("target_category")

                    # Classify materiality and category
                    detected_cat = NewsEventCategory.GENERAL_BUSINESS
                    detected_score = 0.3
                    matched_kw = None

                    for cat, kw_dict in EVENT_CATEGORY_KEYWORDS.items():
                        for kw, score in kw_dict.items():
                            if kw in passage:
                                if score > detected_score:
                                    detected_score = score
                                    detected_cat = cat
                                    matched_kw = kw

                    # Assess trigger conditions
                    should_trigger = False
                    rationale_reasons = []

                    if rule.rule_type == "MATERIAL_DISCLOSURE":
                        if detected_score >= min_mat:
                            should_trigger = True
                            rationale_reasons.append(
                                f"Materiality score {detected_score:.2f} >= threshold {min_mat:.2f} (Keyword: '{matched_kw}')"
                            )
                    elif rule.rule_type == "EVENT_CATEGORY":
                        if target_category and detected_cat.value == target_category:
                            should_trigger = True
                            rationale_reasons.append(
                                f"Matched target category {target_category} (Keyword: '{matched_kw}')"
                            )
                    elif rule.rule_type == "ANY_ANNOUNCEMENT":
                        should_trigger = True
                        rationale_reasons.append("Triggered by new official announcement for enrolled symbol.")

                    if should_trigger:
                        # Determine severity
                        if detected_cat in (NewsEventCategory.REGULATORY_CHANGES, NewsEventCategory.MANAGEMENT_CHANGES):
                            severity = "HIGH"
                        elif detected_score >= 0.8:
                            severity = "HIGH"
                        elif detected_score >= 0.6:
                            severity = "MEDIUM"
                        else:
                            severity = "INFO"

                        rationale = (
                            f"Watchlist alert triggered for [{company.symbol}]. "
                            f"Rule ID: {rule.id} ({rule.rule_type}). "
                            f"Reason: {'; '.join(rationale_reasons)}. "
                            f"Publisher: {ev.publisher}. Source: {ev.source_url[:80]}..."
                        )

                        title = f"Alert: {company.symbol} - {detected_cat.value.title()} ({matched_kw or 'Disclosure'})"
                        alert_id = str(uuid.uuid4())

                        # Persist to mp_alert_events
                        alert_event = AlertEventRecord(
                            id=alert_id,
                            rule_id=rule.id,
                            watchlist_id=wl.id,
                            company_symbol=company.symbol,
                            severity=severity,
                            event_category=detected_cat.value,
                            title=title,
                            trigger_rationale=rationale,
                            evidence_record_id=ev.id,
                            source_url=ev.source_url,
                        )
                        self.session.add(alert_event)

                        rule.last_triggered_at = now_utc

                        triggered_alerts.append(
                            WatchlistAlertItem(
                                alert_id=alert_id,
                                watchlist_name=wl.name,
                                company_symbol=company.symbol,
                                company_name=company.name,
                                severity=severity,
                                event_category=detected_cat.value,
                                title=title,
                                trigger_rationale=rationale,
                                source_url=ev.source_url,
                                created_at=now_utc.isoformat(),
                            )
                        )

        self.session.flush()

        return WatchlistAlertEvaluation(
            evaluated_watchlist_count=len(watchlists),
            evaluated_symbol_count=len(monitored_symbols),
            alerts_triggered_count=len(triggered_alerts),
            alerts=triggered_alerts,
        )
