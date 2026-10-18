"""n8n integration endpoints for status, workflow registry, and test triggers."""

from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from marketpulse.api.deps import get_n8n_client, verify_api_key
from marketpulse.api.schemas import N8nStatusResponse, WorkflowItemResponse
from marketpulse.config import mp_settings
from marketpulse.n8n.client import N8nClient

router = APIRouter(prefix="/n8n", tags=["n8n Automation"])

REGISTERED_WORKFLOWS = [
    {
        "id": "MP-00",
        "name": "Connectivity Test Workflow",
        "filename": "MP-00-connectivity-test.json",
        "trigger_type": "WEBHOOK",
        "schedule_or_webhook": "/webhook/test-connection",
        "active": True,
        "description": "Harmless ping/pong workflow verifying bidirectional n8n webhook connectivity.",
    },
    {
        "id": "MP-01",
        "name": "Daily Market Brief",
        "filename": "MP-01-daily-market-brief.json",
        "trigger_type": "CRON",
        "schedule_or_webhook": "30 8 * * 1-5 (08:30 IST Mon-Fri)",
        "active": True,
        "description": "Morning intelligence brief covering Indian indices, pre-market updates, and watchlist tickers.",
    },
    {
        "id": "MP-02",
        "name": "News Intelligence Ingestion",
        "filename": "MP-02-news-intelligence.json",
        "trigger_type": "CRON",
        "schedule_or_webhook": "*/15 * * * * (Every 15 mins)",
        "active": True,
        "description": "Polls permitted RSS and regulatory disclosure feeds, normalizes metadata, and deduplicates.",
    },
    {
        "id": "MP-03",
        "name": "On-Demand Research Trigger",
        "filename": "MP-03-on-demand-research.json",
        "trigger_type": "WEBHOOK",
        "schedule_or_webhook": "/webhook/marketpulse-research",
        "active": True,
        "description": "Dispatches 7-agent deep dive pipeline for a ticker or sector on-demand.",
    },
    {
        "id": "MP-04",
        "name": "Watchlist Alerts",
        "filename": "MP-04-watchlist-alerts.json",
        "trigger_type": "WEBHOOK_OR_CRON",
        "schedule_or_webhook": "/webhook/marketpulse-alerts (or */10 * * * *)",
        "active": True,
        "description": "Evaluates price and news conditions against active user watchlist alert rules.",
    },
    {
        "id": "MP-05",
        "name": "Health & Failure Recovery",
        "filename": "MP-05-health-recovery.json",
        "trigger_type": "CRON",
        "schedule_or_webhook": "*/5 * * * * (Every 5 mins)",
        "active": True,
        "description": "Probes system health and automatically handles transient connection recovery.",
    },
]


@router.get("/status", response_model=N8nStatusResponse)
def get_n8n_status(
    n8n: N8nClient = Depends(get_n8n_client),
    _auth: str = Depends(verify_api_key),
) -> N8nStatusResponse:
    """Check live connectivity to the configured n8n automation runtime."""
    res = n8n.test_connection()
    return N8nStatusResponse(
        status=res.state.value,
        base_url=mp_settings.n8n_base_url,
        api_key_configured=bool(mp_settings.n8n_api_key),
        details=res.message,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/workflows", response_model=List[WorkflowItemResponse])
def list_registered_workflows(
    _auth: str = Depends(verify_api_key),
) -> List[WorkflowItemResponse]:
    """List all version-controlled workflows available in MarketPulse AI."""
    return [WorkflowItemResponse(**w) for w in REGISTERED_WORKFLOWS]


class TestTriggerRequest(BaseModel):
    workflow_id: str = "MP-00"
    correlation_id: str = "test-corr-001"


@router.post("/workflows/test-trigger")
def trigger_workflow_test(
    payload: TestTriggerRequest,
    n8n: N8nClient = Depends(get_n8n_client),
    _auth: str = Depends(verify_api_key),
):
    """Trigger harmless test execution on the configured n8n runtime."""
    webhook_path = "test-connection"
    try:
        result = n8n.trigger_webhook(
            webhook_path=webhook_path,
            payload={
                "workflow_id": payload.workflow_id,
                "correlation_id": payload.correlation_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        return {
            "status": "TRIGGERED",
            "correlation_id": payload.correlation_id,
            "response": result,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to execute n8n webhook test: {str(exc)}",
        )
