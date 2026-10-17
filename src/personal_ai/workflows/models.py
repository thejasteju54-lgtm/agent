"""Data models for webhook payloads and n8n integration."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TaskWebhookRequest(BaseModel):
    """Payload to trigger an automated natural language task via webhook."""
    prompt: str = Field(..., min_length=1, description="Natural language task prompt to execute.")
    priority: str = Field(default="normal", description="Task priority (low, normal, high).")
    auto_approve: bool = Field(default=False, description="Whether to auto-approve high-risk actions.")
    callback_url: Optional[str] = Field(default=None, description="Optional n8n webhook URL to call on completion.")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Arbitrary metadata from the caller/n8n.")


class TaskWebhookResponse(BaseModel):
    """Response returned immediately or upon completion of a webhook task."""
    task_id: str
    status: str
    summary: Optional[str] = None
    plan: Optional[Dict[str, Any]] = None
    report: Optional[Dict[str, Any]] = None


class StatusCallbackPayload(BaseModel):
    """Payload dispatched to n8n upon task completion, failure, or approval requirement."""
    task_id: str
    status: str
    summary: str
    completed_steps: int
    total_steps: int
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class NotificationRequest(BaseModel):
    """Generic notification payload received from n8n or external triggers."""
    event: str = Field(..., description="Event name, e.g., 'workflow.completed', 'schedule.fired'.")
    source: str = Field(default="n8n", description="Originating workflow engine or system.")
    data: Dict[str, Any] = Field(default_factory=dict, description="Event-specific attributes.")
