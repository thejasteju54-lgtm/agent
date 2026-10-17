"""Production-grade n8n REST API and Webhook client."""

import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx

from marketpulse.config import mp_settings
from marketpulse.n8n.models import (
    ConnectionState,
    ConnectionTestResult,
    ExecutionSummary,
    WebhookTriggerResult,
    WorkflowSummary,
)

# Regex to redact potential API keys or tokens in exception/log strings
SECRET_REDACT_PATTERN = re.compile(r"([a-zA-Z0-9_\-\.]{16,})")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_error(error_msg: str) -> str:
    """Mask any potential credential strings that might leak in network error tracebacks."""
    if not error_msg:
        return ""
    # Redact common key patterns
    return SECRET_REDACT_PATTERN.sub(r"***REDACTED***", str(error_msg))


class N8nClient:
    """Robust client for interacting with n8n's official REST API and Webhooks."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        max_retries: Optional[int] = None,
    ):
        raw_url = (base_url or mp_settings.n8n_base_url or "").strip()
        self.base_url = raw_url.rstrip("/")
        self.api_key = api_key if api_key is not None else mp_settings.n8n_api_key
        self.timeout = timeout_seconds or mp_settings.n8n_timeout_seconds
        self.max_retries = max_retries or mp_settings.n8n_max_retries

    def _get_api_headers(self) -> Dict[str, str]:
        """Headers required for n8n Public REST API calls."""
        headers = {
            "Accept": "application/json",
            "User-Agent": "MarketPulse-AI/0.1.0",
        }
        if self.api_key:
            headers["X-N8N-API-KEY"] = self.api_key
        return headers

    def _get_webhook_headers(self) -> Dict[str, str]:
        """Headers for webhook invocations."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "MarketPulse-AI/0.1.0",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def test_connection(self) -> ConnectionTestResult:
        """Test authenticated connectivity to the n8n instance.

        Distinguishes CONNECTED, UNAUTHORIZED, DISCONNECTED, and MISCONFIGURED states.
        """
        start = time.perf_counter()
        now_str = _utc_now_iso()

        if not self.base_url or not (self.base_url.startswith("http://") or self.base_url.startswith("https://")):
            return ConnectionTestResult(
                state=ConnectionState.MISCONFIGURED,
                message=f"Invalid n8n base URL: '{self.base_url}'. Must start with http:// or https://.",
                checked_at=now_str,
            )

        if not self.api_key:
            # Check if server is at least reachable via healthz, but flag as MISCONFIGURED / UNAUTHORIZED
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.get(f"{self.base_url}/healthz")
                    latency = (time.perf_counter() - start) * 1000.0
                    return ConnectionTestResult(
                        state=ConnectionState.UNAUTHORIZED,
                        status_code=resp.status_code,
                        message="n8n instance is reachable, but N8N_API_KEY is not configured.",
                        latency_ms=round(latency, 2),
                        checked_at=now_str,
                    )
            except Exception as e:
                latency = (time.perf_counter() - start) * 1000.0
                return ConnectionTestResult(
                    state=ConnectionState.DISCONNECTED,
                    message=f"n8n instance unreachable and N8N_API_KEY missing: {_sanitize_error(str(e))}",
                    latency_ms=round(latency, 2),
                    checked_at=now_str,
                )

        # Authenticated check via /api/v1/workflows
        endpoint = f"{self.base_url}/api/v1/workflows"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(endpoint, headers=self._get_api_headers())
                latency = (time.perf_counter() - start) * 1000.0

                if resp.status_code == 200:
                    data = resp.json()
                    workflows_data = data.get("data", [])
                    return ConnectionTestResult(
                        state=ConnectionState.CONNECTED,
                        status_code=200,
                        message="Successfully authenticated to n8n Public API.",
                        workflow_count=len(workflows_data),
                        latency_ms=round(latency, 2),
                        checked_at=now_str,
                    )
                elif resp.status_code in (401, 403):
                    return ConnectionTestResult(
                        state=ConnectionState.UNAUTHORIZED,
                        status_code=resp.status_code,
                        message=f"Authentication failed: HTTP {resp.status_code}. The provided N8N_API_KEY is invalid or lacks permissions.",
                        latency_ms=round(latency, 2),
                        checked_at=now_str,
                    )
                else:
                    return ConnectionTestResult(
                        state=ConnectionState.DISCONNECTED,
                        status_code=resp.status_code,
                        message=f"n8n API responded with unexpected status HTTP {resp.status_code}.",
                        latency_ms=round(latency, 2),
                        checked_at=now_str,
                    )

        except httpx.ConnectError as e:
            latency = (time.perf_counter() - start) * 1000.0
            return ConnectionTestResult(
                state=ConnectionState.DISCONNECTED,
                message=f"Connection refused to {self.base_url}. Ensure n8n is running.",
                latency_ms=round(latency, 2),
                checked_at=now_str,
            )
        except httpx.TimeoutException:
            latency = (time.perf_counter() - start) * 1000.0
            return ConnectionTestResult(
                state=ConnectionState.DISCONNECTED,
                message=f"Connection timed out after {self.timeout}s connecting to {self.base_url}.",
                latency_ms=round(latency, 2),
                checked_at=now_str,
            )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000.0
            return ConnectionTestResult(
                state=ConnectionState.DISCONNECTED,
                message=f"Failed to communicate with n8n: {_sanitize_error(str(e))}",
                latency_ms=round(latency, 2),
                checked_at=now_str,
            )

    def list_workflows(self) -> List[WorkflowSummary]:
        """Fetch list of all workflows from n8n API with bounded retries."""
        if not self.api_key:
            raise PermissionError("N8N_API_KEY is required to list workflows from n8n API.")

        url = f"{self.base_url}/api/v1/workflows"
        headers = self._get_api_headers()

        resp = self._request_with_retries("GET", url, headers=headers)
        if resp.status_code in (401, 403):
            raise PermissionError(f"Unauthorized (HTTP {resp.status_code}): Invalid N8N_API_KEY.")
        if resp.status_code != 200:
            raise RuntimeError(f"n8n API returned HTTP {resp.status_code}: {_sanitize_error(resp.text[:200])}")

        payload = resp.json()
        items = payload.get("data", [])
        results = []
        for w in items:
            results.append(
                WorkflowSummary(
                    id=str(w.get("id")),
                    name=w.get("name", "Unnamed"),
                    active=bool(w.get("active", False)),
                    created_at=w.get("createdAt"),
                    updated_at=w.get("updatedAt"),
                    tags=[t.get("name") if isinstance(t, dict) else str(t) for t in w.get("tags", [])],
                )
            )
        return results

    def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Fetch detailed workflow definition by ID from n8n."""
        if not self.api_key:
            raise PermissionError("N8N_API_KEY is required to query workflow details.")

        url = f"{self.base_url}/api/v1/workflows/{workflow_id}"
        headers = self._get_api_headers()

        resp = self._request_with_retries("GET", url, headers=headers)
        if resp.status_code == 404:
            return None
        if resp.status_code in (401, 403):
            raise PermissionError(f"Unauthorized (HTTP {resp.status_code}): Invalid N8N_API_KEY.")
        if resp.status_code != 200:
            raise RuntimeError(f"n8n API returned HTTP {resp.status_code}: {_sanitize_error(resp.text[:200])}")

        return resp.json().get("data", resp.json())

    def get_execution(self, execution_id: str) -> Optional[ExecutionSummary]:
        """Fetch status and details of an execution by ID."""
        if not self.api_key:
            raise PermissionError("N8N_API_KEY is required to inspect execution status.")

        url = f"{self.base_url}/api/v1/executions/{execution_id}"
        headers = self._get_api_headers()

        resp = self._request_with_retries("GET", url, headers=headers)
        if resp.status_code == 404:
            return None
        if resp.status_code in (401, 403):
            raise PermissionError(f"Unauthorized (HTTP {resp.status_code}): Invalid N8N_API_KEY.")
        if resp.status_code != 200:
            raise RuntimeError(f"n8n API returned HTTP {resp.status_code}: {_sanitize_error(resp.text[:200])}")

        data = resp.json().get("data", resp.json())
        return ExecutionSummary(
            id=str(data.get("id", execution_id)),
            workflow_id=str(data.get("workflowId")) if data.get("workflowId") else None,
            status=str(data.get("status", "unknown")),
            started_at=data.get("startedAt"),
            stopped_at=data.get("stoppedAt"),
            finished=bool(data.get("finished", False)),
            mode=str(data.get("mode", "webhook")),
            retry_of=str(data.get("retryOf")) if data.get("retryOf") else None,
        )

    def trigger_webhook(
        self,
        webhook_path: str,
        payload: Dict[str, Any],
        correlation_id: str,
        custom_headers: Optional[Dict[str, str]] = None,
    ) -> WebhookTriggerResult:
        """Trigger an n8n workflow via its configured webhook path.

        Automatically attaches correlation ID and measures roundtrip latency.
        """
        start = time.perf_counter()
        clean_path = webhook_path.strip("/")
        if clean_path.startswith("http://") or clean_path.startswith("https://"):
            url = clean_path
        else:
            url = f"{self.base_url}/{clean_path}"

        headers = self._get_webhook_headers()
        if custom_headers:
            headers.update(custom_headers)

        body = dict(payload)
        body["correlation_id"] = correlation_id
        body["triggered_at"] = _utc_now_iso()

        try:
            resp = self._request_with_retries("POST", url, json_body=body, headers=headers)
            latency = (time.perf_counter() - start) * 1000.0

            if 200 <= resp.status_code < 300:
                try:
                    data = resp.json()
                except Exception:
                    data = {"text": resp.text}
                return WebhookTriggerResult(
                    success=True,
                    status_code=resp.status_code,
                    data=data,
                    correlation_id=correlation_id,
                    latency_ms=round(latency, 2),
                )
            else:
                return WebhookTriggerResult(
                    success=False,
                    status_code=resp.status_code,
                    error=f"Webhook returned HTTP {resp.status_code}: {_sanitize_error(resp.text[:200])}",
                    correlation_id=correlation_id,
                    latency_ms=round(latency, 2),
                )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000.0
            return WebhookTriggerResult(
                success=False,
                status_code=0,
                error=_sanitize_error(str(e)),
                correlation_id=correlation_id,
                latency_ms=round(latency, 2),
            )

    def _request_with_retries(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> httpx.Response:
        """Execute HTTP request with bounded exponential backoff for transient network/server errors."""
        backoff = 0.5
        last_exception = None

        for attempt in range(1, self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    if method.upper() == "GET":
                        resp = client.get(url, headers=headers)
                    elif method.upper() == "POST":
                        resp = client.post(url, headers=headers, json=json_body)
                    elif method.upper() == "DELETE":
                        resp = client.delete(url, headers=headers)
                    else:
                        raise ValueError(f"Unsupported HTTP method: {method}")

                    # Fail fast on client auth errors (never retry bad credentials)
                    if resp.status_code in (401, 403):
                        return resp

                    # Transient server errors (502, 503, 504) can be retried
                    if resp.status_code in (502, 503, 504) and attempt < self.max_retries:
                        time.sleep(backoff)
                        backoff *= 2.0
                        continue

                    return resp

            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
                last_exception = e
                if attempt < self.max_retries:
                    time.sleep(backoff)
                    backoff *= 2.0
                else:
                    raise e
            except Exception as e:
                raise e

        if last_exception:
            raise last_exception
        raise RuntimeError("Request retries exhausted without a response.")
