"""Health and readiness endpoints for MarketPulse AI."""

from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from marketpulse.api.deps import get_db, get_n8n_client
from marketpulse.api.schemas import HealthResponse, ReadinessResponse
from marketpulse.config import mp_settings
from marketpulse.n8n.client import N8nClient

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
def get_health(
    db: Session = Depends(get_db),
    n8n: N8nClient = Depends(get_n8n_client),
) -> HealthResponse:
    """Return health status of MarketPulse AI, SQLite/PostgreSQL, and n8n."""
    # Check DB
    db_status = "CONNECTED"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "DISCONNECTED"

    # Check n8n
    try:
        n8n_res = n8n.test_connection()
        n8n_state = n8n_res.state.value
    except Exception:
        n8n_state = "DISCONNECTED"

    overall_status = "HEALTHY" if db_status == "CONNECTED" else "DEGRADED"

    return HealthResponse(
        status=overall_status,
        database=db_status,
        database_connected=(db_status == "CONNECTED"),
        mode=mp_settings.operating_mode,
        n8n_status=n8n_state,
        environment=mp_settings.environment,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/ready", response_model=ReadinessResponse)
def get_readiness(
    db: Session = Depends(get_db),
) -> ReadinessResponse:
    """Readiness probe for container orchestrators and load balancers."""
    checks = {}

    # 1. Database check
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        checks["database"] = False

    # 2. Artifacts directory write check
    try:
        test_dir = Path(mp_settings.artifacts_dir)
        test_dir.mkdir(parents=True, exist_ok=True)
        checks["artifacts_store"] = test_dir.exists()
    except Exception:
        checks["artifacts_store"] = False

    ready = all(checks.values())
    return ReadinessResponse(
        ready=ready,
        checks=checks,
        timestamp=datetime.now(timezone.utc),
    )
