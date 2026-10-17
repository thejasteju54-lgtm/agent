"""Authenticated HTTP webhook server for local n8n workflow integration."""

import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from pydantic import ValidationError

from personal_ai.config import settings
from personal_ai.logging.setup import get_logger
from personal_ai.agent.planner import TaskPlanner
from personal_ai.agent.executor import TaskExecutor
from personal_ai.agent.task_models import TaskStatus
from personal_ai.storage.repositories import TaskRepository, StepRepository
from personal_ai.storage.artifacts import ArtifactManager
from personal_ai.workflows.models import (
    TaskWebhookRequest,
    TaskWebhookResponse,
    NotificationRequest,
    StatusCallbackPayload,
)
from personal_ai.workflows.client import N8nWebhookClient

logger = get_logger(__name__)


class WebhookRequestHandler(BaseHTTPRequestHandler):
    """Handles incoming authenticated webhook requests from n8n or external triggers."""

    server_version = "PersonalAI-Runtime/0.1.0"

    def _send_json(self, status: int, data: Dict[str, Any]) -> None:
        """Write JSON response with headers."""
        payload = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _is_authenticated(self) -> bool:
        """Verify API key using constant-time comparison."""
        expected_key = settings.webhook_api_key
        if not expected_key:
            return True

        # Check X-API-Key header
        api_key = self.headers.get("X-API-Key")
        if api_key and hmac.compare_digest(api_key.strip(), expected_key):
            return True

        # Check Authorization: Bearer <key>
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            bearer_token = auth[7:].strip()
            if hmac.compare_digest(bearer_token, expected_key):
                return True

        return False

    def do_GET(self) -> None:
        """Handle GET endpoints."""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        # Health endpoint (open to localhost)
        if path == "/health" or path == "":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "healthy",
                    "runtime": "Personal AI Automation System",
                    "version": "0.1.0",
                },
            )
            return

        # Authenticate all other endpoints
        if not self._is_authenticated():
            self._send_json(
                HTTPStatus.UNAUTHORIZED,
                {"error": "Unauthorized: Missing or invalid API key in headers"},
            )
            return

        # GET /webhook/task/<task_id>
        if path.startswith("/webhook/task/"):
            task_id = path.replace("/webhook/task/", "").strip()
            task_repo = TaskRepository()
            step_repo = StepRepository()
            artifact_mgr = ArtifactManager()

            task = task_repo.get_task(task_id)
            if not task:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Task '{task_id}' not found"})
                return

            steps = step_repo.get_steps_for_task(task_id)
            artifacts = artifact_mgr.list_artifacts(task_id=task_id)

            self._send_json(
                HTTPStatus.OK,
                {
                    "task": task,
                    "steps": steps,
                    "artifacts": artifacts,
                },
            )
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Path not found: {self.path}"})

    def do_POST(self) -> None:
        """Handle POST webhook triggers."""
        # Read and drain request body before returning any status code
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b""

        # Always enforce authentication for POST requests
        if not self._is_authenticated():
            self._send_json(
                HTTPStatus.UNAUTHORIZED,
                {"error": "Unauthorized: Missing or invalid API key in headers"},
            )
            return

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if not body_bytes:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Request body cannot be empty"})
            return

        try:
            body_json = json.loads(body_bytes.decode("utf-8"))
        except Exception as e:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": f"Invalid JSON payload: {e}"})
            return

        # POST /webhook/task
        if path == "/webhook/task":
            try:
                task_req = TaskWebhookRequest(**body_json)
            except ValidationError as ve:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid request schema", "details": ve.errors()})
                return

            logger.info("Received webhook task trigger: '%s'", task_req.prompt)

            # Plan task
            planner = TaskPlanner()
            plan = planner.plan(task_req.prompt)

            # Execute task
            executor = TaskExecutor()
            report = executor.execute(plan, auto_approve=task_req.auto_approve)

            # Query generated artifacts
            artifact_mgr = ArtifactManager()
            artifacts = artifact_mgr.list_artifacts(task_id=report.task_id)

            response_data = TaskWebhookResponse(
                task_id=report.task_id,
                status=report.status.value,
                summary=report.summary,
                plan=plan.model_dump(),
                report=report.model_dump(),
            )

            # If n8n provided a callback URL, send status asynchronously or synchronously
            if task_req.callback_url:
                client = N8nWebhookClient()
                callback_payload = StatusCallbackPayload(
                    task_id=report.task_id,
                    status=report.status.value,
                    summary=report.summary,
                    completed_steps=report.steps_completed,
                    total_steps=report.steps_total,
                    artifacts=artifacts,
                    error=None if report.status == TaskStatus.COMPLETED else report.summary,
                    metadata=task_req.metadata,
                )
                threading.Thread(
                    target=client.send_callback,
                    args=(task_req.callback_url, callback_payload),
                    daemon=True,
                ).start()

            self._send_json(HTTPStatus.OK, response_data.model_dump())
            return

        # POST /webhook/notify
        if path == "/webhook/notify":
            try:
                notif = NotificationRequest(**body_json)
            except ValidationError as ve:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid notification schema", "details": ve.errors()})
                return

            logger.info("Received notification from %s: '%s'", notif.source, notif.event)
            self._send_json(
                HTTPStatus.OK,
                {"status": "received", "event": notif.event, "source": notif.source},
            )
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown webhook endpoint: {path}"})

    def log_message(self, format: str, *args: Any) -> None:
        """Route server request logging through Personal AI logger."""
        logger.debug("%s - - [%s] %s", self.address_string(), self.log_date_time_string(), format % args)


class PersonalAIWebhookServer:
    """Manages the lifecycle of the webhook server."""

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None):
        self.host = host or settings.api_host
        self.port = port or settings.api_port
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self, block: bool = True) -> None:
        """Start the HTTP server on configured host and port."""
        self._server = ThreadingHTTPServer((self.host, self.port), WebhookRequestHandler)
        logger.info("Personal AI Webhook Server listening on http://%s:%d", self.host, self.port)

        if block:
            try:
                self._server.serve_forever()
            except KeyboardInterrupt:
                logger.info("Server received shutdown signal")
            finally:
                self.stop()
        else:
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Stop and shutdown the HTTP server."""
        if self._server:
            logger.info("Shutting down Personal AI Webhook Server")
            self._server.shutdown()
            self._server.server_close()
            self._server = None


def run_server_in_background(host: Optional[str] = None, port: Optional[int] = None) -> PersonalAIWebhookServer:
    """Helper to start server in a background daemon thread."""
    server = PersonalAIWebhookServer(host=host, port=port)
    server.start(block=False)
    return server
