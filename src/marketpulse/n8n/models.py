"""Pydantic data models for n8n API interactions and health tracking."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ConnectionState(str, Enum):
    """Classification of n8n instance connection health."""
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    UNAUTHORIZED = "UNAUTHORIZED"
    MISCONFIGURED = "MISCONFIGURED"


class ConnectionTestResult(BaseModel):
    """Result of an authenticated connection test to n8n."""
    state: ConnectionState
    status_code: Optional[int] = None
    message: str
    server_version: Optional[str] = None
    workflow_count: Optional[int] = None
    latency_ms: float = 0.0
    checked_at: str


class WorkflowSummary(BaseModel):
    """High-level summary of a registered n8n workflow."""
    id: str
    name: str
    active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class ExecutionSummary(BaseModel):
    """Summary of an n8n workflow execution."""
    id: str
    workflow_id: Optional[str] = None
    status: str
    started_at: Optional[str] = None
    stopped_at: Optional[str] = None
    finished: bool = False
    mode: str = "webhook"
    retry_of: Optional[str] = None
    error_message: Optional[str] = None


class WebhookTriggerResult(BaseModel):
    """Result of triggering an n8n workflow via webhook."""
    success: bool
    status_code: int
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    correlation_id: str
    latency_ms: float = 0.0
