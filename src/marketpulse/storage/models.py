"""SQLAlchemy data models for MarketPulse AI platform.

Enforces database constraints, foreign keys, idempotency keys, and UTC timestamps.
"""

from datetime import datetime, timezone
from enum import Enum
import uuid
from typing import Optional
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _gen_uuid() -> str:
    return str(uuid.uuid4())


class TaskStatus(str, Enum):
    """Explicit task states required for MarketPulse AI runtime."""
    PENDING = "PENDING"
    PLANNING = "PLANNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Sector(Base):
    """Indian market sector classification (e.g. NIFTY_IT, NIFTY_BANK)."""
    __tablename__ = "mp_sectors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)

    companies = relationship("Company", back_populates="sector")


class Company(Base):
    """Indian listed company registry (NSE / BSE)."""
    __tablename__ = "mp_companies"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    symbol = Column(String(30), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    isin = Column(String(20), unique=True, nullable=True, index=True)
    bse_code = Column(String(20), unique=True, nullable=True)
    sector_id = Column(Integer, ForeignKey("mp_sectors.id", ondelete="SET NULL"), nullable=True)
    market_cap_tier = Column(String(30), default="LARGE_CAP", nullable=False)  # LARGE_CAP, MID_CAP, SMALL_CAP
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, nullable=False)

    sector = relationship("Sector", back_populates="companies")
    observations = relationship("MarketObservation", back_populates="company")
    watchlist_items = relationship("WatchlistItem", back_populates="company")
    article_mappings = relationship("ArticleCompanyMapping", back_populates="company")


class SourceRegistry(Base):
    """Approved data and disclosure source registry."""
    __tablename__ = "mp_sources"

    id = Column(String(60), primary_key=True)  # e.g. bse_disclosures, nse_circulars
    name = Column(String(150), unique=True, nullable=False)
    source_type = Column(String(50), nullable=False)  # OFFICIAL_DISCLOSURE, REGULATORY_FEED, PERMITTED_RSS
    base_url = Column(String(500), nullable=False)
    feed_url = Column(String(500), nullable=True)
    access_type = Column(String(50), default="PUBLIC_FEED", nullable=False)
    retrieval_method = Column(String(50), default="HTTP_GET", nullable=False)  # HTTP_GET, RSS_FEED, BROWSER_PLAYWRIGHT, REST_API
    auth_required = Column(String(50), default="NONE", nullable=False)  # NONE, API_KEY, SESSION_COOKIE
    rate_limit_per_minute = Column(Integer, default=30, nullable=False)
    parser_name = Column(String(100), default="generic_rss", nullable=False)
    last_retrieved_at = Column(DateTime(timezone=True), nullable=True)
    freshness_max_age_hours = Column(Integer, default=24, nullable=False)
    reliability_score = Column(Float, default=1.0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    licensing_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)

    articles = relationship("Article", back_populates="source")
    evidence_records = relationship("EvidenceRecord", back_populates="source")


class Article(Base):
    """Collected, normalized financial news articles and regulatory announcements."""
    __tablename__ = "mp_articles"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    source_id = Column(String(60), ForeignKey("mp_sources.id", ondelete="RESTRICT"), nullable=False)
    source_identifier = Column(String(1000), nullable=False)  # URL or filing reference
    title = Column(String(500), nullable=False)
    content_raw = Column(Text, nullable=True)
    content_normalized = Column(Text, nullable=False)
    content_hash = Column(String(64), unique=True, nullable=False, index=True)  # SHA-256
    author = Column(String(200), nullable=True)
    materiality_score = Column(Float, default=0.0, nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=True)
    retrieved_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)

    source = relationship("SourceRegistry", back_populates="articles")
    company_mappings = relationship("ArticleCompanyMapping", back_populates="article", cascade="all, delete-orphan")
    evidence_items = relationship("EvidenceItem", back_populates="article")


class ArticleCompanyMapping(Base):
    """Associates normalized articles with identified listed companies."""
    __tablename__ = "mp_article_companies"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    article_id = Column(String(36), ForeignKey("mp_articles.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(String(36), ForeignKey("mp_companies.id", ondelete="CASCADE"), nullable=False)
    relevance_score = Column(Float, default=1.0, nullable=False)
    sentiment = Column(String(20), default="UNCERTAIN", nullable=False)  # POSITIVE, NEUTRAL, NEGATIVE, UNCERTAIN
    key_quote = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)

    article = relationship("Article", back_populates="company_mappings")
    company = relationship("Company", back_populates="article_mappings")

    __table_args__ = (
        UniqueConstraint("article_id", "company_id", name="uq_article_company"),
    )


class MarketObservation(Base):
    """Historical or daily market observation record (prices, corporate actions)."""
    __tablename__ = "mp_market_observations"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    company_id = Column(String(36), ForeignKey("mp_companies.id", ondelete="CASCADE"), nullable=False)
    observation_date = Column(Date, nullable=False, index=True)
    open_price = Column(Float, nullable=True)
    high_price = Column(Float, nullable=True)
    low_price = Column(Float, nullable=True)
    close_price = Column(Float, nullable=True)
    volume = Column(BigInteger, nullable=True)
    delivery_percentage = Column(Float, nullable=True)
    corporate_action = Column(Text, nullable=True)
    is_verified = Column(Boolean, default=False, nullable=False)
    source_reference = Column(String(500), nullable=True)
    recorded_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)

    company = relationship("Company", back_populates="observations")

    __table_args__ = (
        UniqueConstraint("company_id", "observation_date", name="uq_company_observation_date"),
    )


class AutomationTask(Base):
    """Persistent execution record for automation and research tasks with bounded execution."""
    __tablename__ = "mp_automation_tasks"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    task_type = Column(String(50), default="RESEARCH", nullable=False)  # RESEARCH, BRIEF, BROWSER, DESKTOP, WORKFLOW
    prompt = Column(Text, nullable=False)
    status = Column(String(30), default=TaskStatus.PENDING.value, nullable=False, index=True)
    idempotency_key = Column(String(64), unique=True, nullable=True, index=True)
    step_limit = Column(Integer, default=20, nullable=False)
    current_step = Column(Integer, default=0, nullable=False)
    requires_approval = Column(Boolean, default=False, nullable=False)
    approval_status = Column(String(30), nullable=True)  # PENDING, APPROVED, REJECTED
    cancellation_reason = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    recovery_metadata_json = Column(Text, nullable=True)
    result_summary = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, nullable=False)

    artifacts = relationship("ArtifactRecord", back_populates="task", cascade="all, delete-orphan")
    approvals = relationship("ApprovalRecord", back_populates="task", cascade="all, delete-orphan")


class ArtifactRecord(Base):
    """Persistent registry of files, reports, and source evidence stored in artifacts directory."""
    __tablename__ = "mp_artifacts"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    task_id = Column(String(36), ForeignKey("mp_automation_tasks.id", ondelete="SET NULL"), nullable=True)
    job_id = Column(String(36), ForeignKey("mp_research_jobs.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(255), nullable=False)
    artifact_type = Column(String(50), default="REPORT", nullable=False)  # REPORT, SOURCE_DOCUMENT, EVIDENCE_BUNDLE, SCREENSHOT
    file_path = Column(String(1000), nullable=False)
    content_hash = Column(String(64), nullable=False)  # SHA-256
    mime_type = Column(String(100), default="text/markdown", nullable=False)
    size_bytes = Column(BigInteger, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)

    task = relationship("AutomationTask", back_populates="artifacts")
    job = relationship("ResearchJob")


class ResearchJob(Base):
    """Persistence record for research jobs dispatched via CLI, API, or n8n."""
    __tablename__ = "mp_research_jobs"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    correlation_id = Column(String(64), unique=True, nullable=False, index=True)
    job_type = Column(String(50), default="ON_DEMAND", nullable=False)  # ON_DEMAND, SCHEDULED_BRIEF, WATCHLIST_ALERT
    status = Column(String(30), default=TaskStatus.PENDING.value, nullable=False, index=True)
    target_company_symbol = Column(String(30), nullable=True)
    prompt = Column(Text, nullable=False)
    parameters_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    step_limit = Column(Integer, default=20, nullable=False)
    current_step = Column(Integer, default=0, nullable=False)
    cancellation_reason = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    recovery_metadata_json = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    report = relationship("ResearchReport", back_populates="job", uselist=False)


class ResearchReport(Base):
    """Structured, evidence-backed financial research report."""
    __tablename__ = "mp_research_reports"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    job_id = Column(String(36), ForeignKey("mp_research_jobs.id", ondelete="CASCADE"), unique=True, nullable=False)
    company_id = Column(String(36), ForeignKey("mp_companies.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(500), nullable=False)
    executive_summary = Column(Text, nullable=False)
    key_developments = Column(Text, nullable=False)
    bull_scenario = Column(Text, nullable=True)
    base_scenario = Column(Text, nullable=True)
    bear_scenario = Column(Text, nullable=True)
    risks_and_counterarguments = Column(Text, nullable=False)
    data_limitations = Column(Text, nullable=False)
    generated_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)

    job = relationship("ResearchJob", back_populates="report")
    company = relationship("Company")
    evidence_items = relationship("EvidenceItem", back_populates="report", cascade="all, delete-orphan")


class EvidenceItem(Base):
    """Verifiable fact claim tied directly to an underlying source document."""
    __tablename__ = "mp_evidence_items"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    report_id = Column(String(36), ForeignKey("mp_research_reports.id", ondelete="CASCADE"), nullable=False)
    article_id = Column(String(36), ForeignKey("mp_articles.id", ondelete="SET NULL"), nullable=True)
    fact_statement = Column(Text, nullable=False)
    interpretation = Column(Text, nullable=True)
    source_url = Column(String(1000), nullable=False)
    source_publication_time = Column(DateTime(timezone=True), nullable=True)
    confidence_score = Column(Float, default=1.0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)

    report = relationship("ResearchReport", back_populates="evidence_items")
    article = relationship("Article", back_populates="evidence_items")


class EvidenceRecord(Base):
    """Normalized, verifiable evidence record with source provenance and cryptographic hash."""
    __tablename__ = "mp_evidence_records"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    source_id = Column(String(60), ForeignKey("mp_sources.id", ondelete="CASCADE"), nullable=False)
    source_url = Column(String(1000), nullable=False)
    publisher = Column(String(150), nullable=False)
    retrieved_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=True)
    company_symbol = Column(String(30), nullable=True, index=True)
    extracted_passage = Column(Text, nullable=False)
    content_hash = Column(String(64), unique=True, nullable=False, index=True)  # SHA-256
    retrieval_status = Column(String(30), default="SUCCESS", nullable=False)  # SUCCESS, PARTIAL, CACHED
    data_freshness = Column(String(30), default="RECENT", nullable=False)  # REALTIME, RECENT, STALE
    verification_status = Column(String(30), default="UNVERIFIED", nullable=False)  # UNVERIFIED, VERIFIED, FLAGGED
    is_incomplete = Column(Boolean, default=False, nullable=False)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)

    source = relationship("SourceRegistry", back_populates="evidence_records")


class Watchlist(Base):
    """User-monitored list of Indian companies."""
    __tablename__ = "mp_watchlists"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)

    items = relationship("WatchlistItem", back_populates="watchlist", cascade="all, delete-orphan")
    alert_rules = relationship("AlertRule", back_populates="watchlist", cascade="all, delete-orphan")
    alert_events = relationship("AlertEventRecord", back_populates="watchlist", cascade="all, delete-orphan")


class WatchlistItem(Base):
    """Entry associating a company with a watchlist."""
    __tablename__ = "mp_watchlist_items"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    watchlist_id = Column(String(36), ForeignKey("mp_watchlists.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(String(36), ForeignKey("mp_companies.id", ondelete="CASCADE"), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)

    watchlist = relationship("Watchlist", back_populates="items")
    company = relationship("Company", back_populates="watchlist_items")

    __table_args__ = (
        UniqueConstraint("watchlist_id", "company_id", name="uq_watchlist_company"),
    )


class AlertRule(Base):
    """Monitored condition triggering deduplicated alerts."""
    __tablename__ = "mp_alert_rules"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    watchlist_id = Column(String(36), ForeignKey("mp_watchlists.id", ondelete="CASCADE"), nullable=True)
    company_id = Column(String(36), ForeignKey("mp_companies.id", ondelete="CASCADE"), nullable=True)
    rule_type = Column(String(50), nullable=False)  # MATERIAL_DISCLOSURE, PRICE_VOLATILITY, SENTIMENT_SHIFT, EVENT_CATEGORY
    threshold_config_json = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    cooldown_minutes = Column(Integer, default=60, nullable=False)
    last_triggered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)

    watchlist = relationship("Watchlist", back_populates="alert_rules")


class AlertEventRecord(Base):
    """Persistent audit record of an alert triggered against a watchlist or company rule."""
    __tablename__ = "mp_alert_events"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    rule_id = Column(String(36), ForeignKey("mp_alert_rules.id", ondelete="SET NULL"), nullable=True)
    watchlist_id = Column(String(36), ForeignKey("mp_watchlists.id", ondelete="CASCADE"), nullable=True)
    company_symbol = Column(String(30), nullable=False, index=True)
    severity = Column(String(20), default="INFO", nullable=False)  # INFO, MEDIUM, HIGH, CRITICAL
    event_category = Column(String(50), nullable=False)  # EARNINGS, CORPORATE_ACTIONS, REGULATORY_CHANGES, MANAGEMENT_CHANGES, MACROECONOMIC, PRICE_VOLATILITY
    title = Column(String(500), nullable=False)
    trigger_rationale = Column(Text, nullable=False)
    evidence_record_id = Column(String(36), ForeignKey("mp_evidence_records.id", ondelete="SET NULL"), nullable=True)
    source_url = Column(String(1000), nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)

    watchlist = relationship("Watchlist", back_populates="alert_events")
    rule = relationship("AlertRule")
    evidence_record = relationship("EvidenceRecord")


class AuditEvent(Base):
    """Immutable audit trail for provenance and security tracking."""
    __tablename__ = "mp_audit_events"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    event_type = Column(String(60), nullable=False, index=True)  # INGESTION, RESEARCH_JOB, APPROVAL, ALERT, TASK
    entity_type = Column(String(60), nullable=True)
    entity_id = Column(String(64), nullable=True)
    details_json = Column(Text, nullable=True)
    actor = Column(String(100), default="system", nullable=False)
    timestamp = Column(DateTime(timezone=True), default=_utc_now, nullable=False, index=True)


class ApprovalRecord(Base):
    """Persistent audit and approval record for high/medium risk actions."""
    __tablename__ = "mp_approvals"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    task_id = Column(String(36), ForeignKey("mp_automation_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    action_type = Column(String(100), nullable=False)
    action_description = Column(Text, nullable=False)
    risk_level = Column(String(20), default="HIGH", nullable=False)
    status = Column(String(30), default="PENDING", nullable=False, index=True)  # PENDING, APPROVED, REJECTED
    requested_by = Column(String(100), default="orchestrator", nullable=False)
    resolved_by = Column(String(100), nullable=True)
    resolution_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    task = relationship("AutomationTask", back_populates="approvals")


class ScheduleDefinition(Base):
    """Permitted automated schedule for workflows and recurring tasks."""
    __tablename__ = "mp_schedules"

    id = Column(String(50), primary_key=True)  # e.g. daily_market_brief, news_polling
    name = Column(String(150), nullable=False)
    schedule_type = Column(String(50), default="CRON", nullable=False)  # CRON, INTERVAL_MINUTES, DAILY_TIME
    cron_expression = Column(String(50), nullable=True)  # e.g. "30 8 * * 1-5"
    timezone = Column(String(50), default="Asia/Kolkata", nullable=False)
    task_type = Column(String(50), default="RESEARCH", nullable=False)  # MARKET_BRIEF, NEWS_POLLING, WATCHLIST_EVALUATION, RESEARCH
    target_symbol = Column(String(30), nullable=True)
    prompt = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    dry_run = Column(Boolean, default=False, nullable=False)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, nullable=False)
