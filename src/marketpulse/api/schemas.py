"""Pydantic request and response schemas for MarketPulse AI API."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


# Health & System Status
class HealthResponse(BaseModel):
    status: str = "HEALTHY"
    database: str = "CONNECTED"
    database_connected: bool = True
    mode: str = "desktop"
    n8n_status: str
    environment: str
    timestamp: datetime
    version: str = "0.1.0"


class ReadinessResponse(BaseModel):
    ready: bool
    checks: Dict[str, bool]
    timestamp: datetime


# n8n Schemas
class N8nStatusResponse(BaseModel):
    status: str
    base_url: str
    api_key_configured: bool
    details: Optional[str] = None
    timestamp: datetime


class WorkflowItemResponse(BaseModel):
    id: str
    name: str
    filename: str
    trigger_type: str
    schedule_or_webhook: str
    active: bool
    description: str


# Company & Sector Schemas
class CompanyResponse(BaseModel):
    id: str
    ticker: str
    name: str
    isin: Optional[str] = None
    bse_code: Optional[str] = None
    sector_code: Optional[str] = None
    market_cap_category: Optional[str] = None


class SectorResponse(BaseModel):
    id: str
    code: str
    name: str
    description: Optional[str] = None
    companies_count: int = 0


# Watchlist Schemas
class WatchlistCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = None


class WatchlistItemAddRequest(BaseModel):
    ticker: str
    target_price: Optional[float] = None
    notes: Optional[str] = None


class WatchlistItemResponse(BaseModel):
    id: str
    ticker: str
    company_name: Optional[str] = None
    added_at: datetime
    notes: Optional[str] = None


class WatchlistResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_at: datetime
    items: List[WatchlistItemResponse] = []


# News & Ingestion Schemas
class RawArticleInput(BaseModel):
    title: str
    content: str
    url: str
    source_name: str = "RSS_FEED"
    published_at: Optional[str] = None
    raw_metadata: Optional[Dict[str, Any]] = None


class ArticleIngestRequest(BaseModel):
    articles: List[RawArticleInput] = Field(default_factory=list)
    correlation_id: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_single_or_list(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "articles" not in data:
                title = data.get("title")
                content = data.get("content") or data.get("content_raw")
                url = data.get("url") or data.get("source_identifier") or "https://marketpulse.local/ingest"
                if title and content:
                    data = {
                        "articles": [{
                            "title": title,
                            "content": content,
                            "url": url,
                            "source_name": data.get("source_id", "RSS_FEED"),
                            "published_at": data.get("published_at"),
                            "raw_metadata": data,
                        }],
                        "correlation_id": data.get("correlation_id"),
                    }
        return data


class ArticleIngestResponse(BaseModel):
    ingested_count: int
    duplicates_skipped: int
    article_ids: List[str]
    correlation_id: str


class ArticleResponse(BaseModel):
    id: str
    title: str
    url: str
    source_type: str
    published_at: Optional[datetime] = None
    retrieved_at: datetime
    content_snippet: str
    associated_tickers: List[str] = []


class EvidenceResponse(BaseModel):
    id: str
    claim: str
    source_quote: str
    source_url: str
    confidence_score: float
    ticker: Optional[str] = None


# Research Schemas
class ResearchJobSubmitRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=1000)
    ticker: Optional[str] = None
    sector: Optional[str] = None
    correlation_id: Optional[str] = None
    sync_execute: bool = False

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("query") and data.get("prompt"):
                data["query"] = data.get("prompt")
            if not data.get("ticker") and data.get("company_symbol"):
                data["ticker"] = data.get("company_symbol")
        return data


class ResearchJobResponse(BaseModel):
    id: str
    query: str
    ticker: Optional[str] = None
    sector: Optional[str] = None
    status: str
    error: Optional[str] = None
    report_id: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    correlation_id: str


class ResearchReportResponse(BaseModel):
    id: str
    query: str
    ticker: Optional[str] = None
    sector: Optional[str] = None
    executive_summary: str
    relevant_companies: List[str] = []
    relevant_sectors: List[str] = []
    key_developments: List[str] = []
    verified_facts: List[str] = []
    hypotheses: List[str] = []
    bull_scenario: Optional[str] = None
    base_scenario: Optional[str] = None
    bear_scenario: Optional[str] = None
    risks_and_counterarguments: List[str] = []
    data_limitations: List[str] = []
    freshness_notes: Optional[str] = None
    evidence_references: List[Dict[str, Any]] = []
    generated_at: datetime


# Alerts Schemas
class AlertRuleCreateRequest(BaseModel):
    watchlist_id: str
    rule_type: str = "PRICE_MOVEMENT"  # PRICE_MOVEMENT, MATERIAL_NEWS, DISCLOSURE
    condition_expr: str
    threshold_value: Optional[float] = None


class AlertResponse(BaseModel):
    id: str
    alert_type: str
    ticker: Optional[str] = None
    message: str
    triggered_at: datetime
    deduplication_hash: str


# Audit Schemas
class AuditEventResponse(BaseModel):
    id: str
    event_type: str
    entity_type: str
    entity_id: Optional[str] = None
    actor: str
    details: Optional[Dict[str, Any]] = None
    created_at: datetime
    correlation_id: Optional[str] = None


# Approval Schemas
class ApprovalItemResponse(BaseModel):
    id: str
    action_type: str
    description: str
    status: str
    requested_by: str
    payload: Optional[Dict[str, Any]] = None
    created_at: datetime
    decided_at: Optional[datetime] = None


class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(..., pattern="^(APPROVED|REJECTED)$")
    rationale: Optional[str] = None


class StepExecuteRequest(BaseModel):
    tool_name: str
    params: Optional[Dict[str, Any]] = None
    auto_approve: bool = False


class StepExecuteResponse(BaseModel):
    status: str
    step: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    approval_id: Optional[str] = None
    task_id: Optional[str] = None
    tool_name: Optional[str] = None
    risk_level: Optional[str] = None
    error: Optional[str] = None


# Unified Task Models & Error Schemas
class TaskCreateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Task prompt or research objective")
    task_type: str = Field(default="RESEARCH", description="Task category: RESEARCH, BRIEF, BROWSER, DESKTOP, WORKFLOW")
    idempotency_key: Optional[str] = Field(default=None, description="Optional deduplication key")
    step_limit: int = Field(default=20, ge=1, le=100, description="Maximum execution steps")
    auto_approve: bool = Field(default=False, description="Auto-approve non-critical steps")
    metadata: Optional[Dict[str, Any]] = None


class TaskResponse(BaseModel):
    id: str
    task_type: str
    prompt: str
    status: str
    idempotency_key: Optional[str] = None
    step_limit: int
    current_step: int
    requires_approval: bool
    approval_status: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    cancellation_reason: Optional[str] = None
    retry_count: int
    result_summary: Optional[str] = None
    error_message: Optional[str] = None
    artifacts_count: int = 0


class TaskCancelRequest(BaseModel):
    reason: str = Field(default="Operator cancelled task", description="Reason for cancellation")


class ArtifactItemResponse(BaseModel):
    id: str
    task_id: Optional[str] = None
    job_id: Optional[str] = None
    name: str
    artifact_type: str
    file_path: str
    content_hash: str
    mime_type: str
    size_bytes: int
    created_at: datetime


class ErrorDetail(BaseModel):
    loc: Optional[List[str]] = None
    msg: str
    type: Optional[str] = None


class StandardErrorResponse(BaseModel):
    status: str = "ERROR"
    message: str
    error_code: str = "INTERNAL_ERROR"
    detail: Optional[str] = None
    errors: Optional[List[ErrorDetail]] = None
    correlation_id: Optional[str] = None


# Webhook & n8n Integration Models
class TaskWebhookRequest(BaseModel):
    """Payload to trigger an automated natural language task via webhook."""
    prompt: str = Field(..., min_length=1, description="Natural language task prompt to execute.")
    priority: str = Field(default="normal", description="Task priority (low, normal, high).")
    auto_approve: bool = Field(default=False, description="Whether to auto-approve high-risk actions.")
    callback_url: Optional[str] = Field(default=None, description="Optional n8n webhook URL to call on completion.")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Arbitrary metadata from the caller/n8n.")
    sync_execute: bool = Field(default=False, description="Whether to execute synchronously before returning.")
    task_type: str = Field(default="GENERAL", description="Type of task (RESEARCH, ANALYSIS, GENERAL).")


class TaskWebhookResponse(BaseModel):
    """Response returned immediately or upon completion of a webhook task."""
    task_id: str
    status: str
    summary: Optional[str] = None
    plan: Optional[Dict[str, Any]] = None
    report: Optional[Dict[str, Any]] = None
    check_url: Optional[str] = None
    created_at: Optional[str] = None


class StatusCallbackPayload(BaseModel):
    """Payload dispatched to n8n upon task completion, failure, or approval requirement."""
    task_id: str
    status: str
    summary: str
    completed_steps: int = 0
    total_steps: int = 0
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class NotificationRequest(BaseModel):
    """Generic notification payload received from n8n or external triggers."""
    event: str = Field(..., description="Event name, e.g., 'workflow.completed', 'schedule.fired'.")
    source: str = Field(default="n8n", description="Originating workflow engine or system.")
    data: Dict[str, Any] = Field(default_factory=dict, description="Event-specific attributes.")

