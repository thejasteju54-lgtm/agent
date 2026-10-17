"""Client for sending callbacks and triggers to local n8n workflows."""

import time
from typing import Any, Dict, Optional
import httpx

from personal_ai.config import settings
from personal_ai.logging.setup import get_logger
from personal_ai.workflows.models import StatusCallbackPayload

logger = get_logger(__name__)


class N8nWebhookClient:
    """Dispatches authenticated webhook callbacks to n8n workflows."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 10.0,
    ):
        self.base_url = (base_url or settings.n8n_base_url).rstrip("/")
        self.api_key = api_key or settings.webhook_api_key
        self.timeout = timeout

    def send_callback(
        self,
        callback_url: str,
        payload: StatusCallbackPayload,
        max_retries: int = 3,
    ) -> bool:
        """Send a task status update to an n8n callback endpoint with retries."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "PersonalAI-Runtime/0.1.0",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        body = payload.model_dump()
        backoff = 0.5

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(
                    "Sending webhook callback to '%s' (attempt %d/%d)",
                    callback_url,
                    attempt,
                    max_retries,
                )
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(callback_url, json=body, headers=headers)
                    if 200 <= resp.status_code < 300:
                        logger.info("Webhook callback delivered successfully (HTTP %d)", resp.status_code)
                        return True
                    logger.warning(
                        "Webhook callback received HTTP %d: %s",
                        resp.status_code,
                        resp.text[:200],
                    )
            except Exception as e:
                logger.warning("Failed to deliver webhook callback to '%s': %s", callback_url, e)

            if attempt < max_retries:
                time.sleep(backoff)
                backoff *= 2.0

        logger.error("Failed to deliver webhook callback after %d attempts", max_retries)
        return False

    def trigger_n8n_webhook(
        self,
        webhook_path: str,
        data: Dict[str, Any],
        max_retries: int = 3,
    ) -> Optional[Dict[str, Any]]:
        """Trigger an n8n webhook workflow."""
        url = webhook_path if webhook_path.startswith("http") else f"{self.base_url}/{webhook_path.lstrip('/')}"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "PersonalAI-Runtime/0.1.0",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        for attempt in range(1, max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(url, json=data, headers=headers)
                    if 200 <= resp.status_code < 300:
                        try:
                            return resp.json()
                        except Exception:
                            return {"status": "ok", "text": resp.text}
                    logger.warning("n8n webhook returned HTTP %d: %s", resp.status_code, resp.text[:200])
            except Exception as e:
                logger.warning("Failed to trigger n8n webhook '%s': %s", url, e)

            time.sleep(0.5 * attempt)

        return None
