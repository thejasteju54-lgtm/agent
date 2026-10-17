"""Workflow automation and n8n webhook integration package."""

from .models import (
    TaskWebhookRequest,
    TaskWebhookResponse,
    NotificationRequest,
    StatusCallbackPayload,
)
from .client import N8nWebhookClient
from .server import PersonalAIWebhookServer, run_server_in_background

__all__ = [
    "TaskWebhookRequest",
    "TaskWebhookResponse",
    "NotificationRequest",
    "StatusCallbackPayload",
    "N8nWebhookClient",
    "PersonalAIWebhookServer",
    "run_server_in_background",
]
