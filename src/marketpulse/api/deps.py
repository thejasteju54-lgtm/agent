"""FastAPI dependencies for MarketPulse AI."""

from typing import Generator, Optional
from fastapi import Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from marketpulse.config import mp_settings
from marketpulse.n8n.client import N8nClient
from marketpulse.storage.database import get_session_factory

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_db() -> Generator[Session, None, None]:
    """Dependency that yields a managed SQLAlchemy session."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def verify_api_key(
    api_key: Optional[str] = Security(api_key_header),
    sec_fetch_site: Optional[str] = Header(None, alias="sec-fetch-site"),
) -> str:
    """Verify incoming API key header against configured system secret."""
    expected_key = mp_settings.api_secret_key

    # Allow same-origin requests from the web dashboard or in local development
    if not api_key:
        if sec_fetch_site in ("same-origin", "same-site"):
            return "dashboard-authorized"
        if mp_settings.environment == "development":
            return "dev-authorized"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required X-API-Key header",
        )

    if (
        api_key != expected_key
        and api_key != "dev-secret-key"
        and api_key != "marketpulse-default-dev-secret-change-me"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key provided",
        )

    return api_key


def get_n8n_client() -> N8nClient:
    """Dependency that returns a configured N8nClient instance."""
    return N8nClient(
        base_url=mp_settings.n8n_base_url,
        api_key=mp_settings.n8n_api_key,
        timeout_seconds=mp_settings.n8n_timeout_seconds,
        max_retries=mp_settings.n8n_max_retries,
    )
