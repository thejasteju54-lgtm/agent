"""Authenticated HTTP webhook server and Web Dashboard runtime."""

import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import threading
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from pydantic import ValidationError

from personal_ai.config import settings
from personal_ai.logging.setup import get_logger
from personal_ai.agent.planner import TaskPlanner
from personal_ai.agent.executor import TaskExecutor
from personal_ai.agent.task_models import TaskStatus
from personal_ai.storage.repositories import (
    TaskRepository,
    StepRepository,
    ApprovalRepository,
    ClipboardRepository,
)
from personal_ai.storage.artifacts import ArtifactManager
from personal_ai.tools.clipboard import WindowsClipboard, ClipboardMonitor
from personal_ai.tools.desktop import (
    get_screen_resolution,
    get_active_window_info,
    list_open_windows,
    capture_desktop_screenshot,
    focus_window_by_title,
)
from personal_ai.dashboard import DASHBOARD_STATIC_DIR
from personal_ai.workflows.models import (
    TaskWebhookRequest,
    TaskWebhookResponse,
    NotificationRequest,
    StatusCallbackPayload,
)
from personal_ai.workflows.client import N8nWebhookClient

logger = get_logger(__name__)


class WebhookRequestHandler(BaseHTTPRequestHandler):
    """Handles incoming webhook requests and serves the Dashboard UI."""

    server_version = "PersonalAI-Runtime/0.1.0"

    def _send_json(self, status: int, data: Any) -> None:
        """Write JSON response with headers."""
        payload = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_file(self, file_path: Path, mime_type: Optional[str] = None) -> None:
        """Stream a static file or artifact from disk."""
        if not file_path.exists() or not file_path.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "File not found"})
            return

        guessed_type, _ = mimetypes.guess_type(str(file_path))
        resolved_mime = mime_type or guessed_type or "application/octet-stream"

        try:
            data = file_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", resolved_mime)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            logger.error("Error serving file '%s': %s", file_path, e)
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(e)})

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
        """Handle GET requests for Dashboard, APIs, and Webhooks."""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        # 1. Health endpoint
        if path == "/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "healthy",
                    "runtime": "Personal AI Automation System",
                    "version": "0.1.0",
                },
            )
            return

        # 2. Dashboard Root & Static Assets
        if path in ("", "/", "/dashboard"):
            index_path = DASHBOARD_STATIC_DIR / "index.html"
            self._send_file(index_path, "text/html; charset=utf-8")
            return

        if path.startswith("/static/"):
            rel_name = path.replace("/static/", "")
            static_file = DASHBOARD_STATIC_DIR / rel_name
            self._send_file(static_file)
            return

        # 3. Dashboard Local APIs
        if path == "/api/tasks":
            task_repo = TaskRepository()
            tasks = task_repo.list_tasks(limit=100)
            self._send_json(HTTPStatus.OK, tasks)
            return

        if path.startswith("/api/tasks/"):
            task_id = path.replace("/api/tasks/", "").strip()
            task_repo = TaskRepository()
            step_repo = StepRepository()
            artifact_mgr = ArtifactManager()

            task = task_repo.get_task(task_id)
            if not task:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Task '{task_id}' not found"})
                return

            steps = step_repo.get_steps_for_task(task_id)
            artifacts = artifact_mgr.list_artifacts(task_id=task_id)
            self._send_json(HTTPStatus.OK, {"task": task, "steps": steps, "artifacts": artifacts})
            return

        if path == "/api/approvals":
            approval_repo = ApprovalRepository()
            approvals = approval_repo.get_pending_approvals()
            self._send_json(HTTPStatus.OK, approvals)
            return

        if path == "/api/artifacts":
            artifact_mgr = ArtifactManager()
            artifacts = artifact_mgr.list_artifacts()
            self._send_json(HTTPStatus.OK, artifacts)
            return

        if path.startswith("/api/artifacts/file/"):
            artifact_id = path.replace("/api/artifacts/file/", "").strip()
            artifact_mgr = ArtifactManager()
            artifact = artifact_mgr.get_artifact(artifact_id)
            if not artifact or not artifact.get("file_path"):
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Artifact not found"})
                return

            file_path = Path(artifact["file_path"])
            self._send_file(file_path, artifact.get("mime_type"))
            return

        if path == "/api/clipboard":
            clip_repo = ClipboardRepository()
            entries = clip_repo.search_entries(limit=100)
            self._send_json(HTTPStatus.OK, entries)
            return

        if path == "/api/desktop/screen":
            w, h = get_screen_resolution()
            active = get_active_window_info()
            self._send_json(HTTPStatus.OK, {"screen_width": w, "screen_height": h, "active_window": active})
            return

        if path == "/api/desktop/windows":
            windows = list_open_windows(include_empty_titles=False)
            self._send_json(HTTPStatus.OK, windows)
            return

        if path == "/api/settings":
            safe_settings = {
                "environment": settings.environment,
                "approval_mode": settings.approval_mode,
                "default_provider": settings.default_provider,
                "ollama_base_url": settings.ollama_base_url,
                "ollama_model": settings.ollama_model,
                "cloud_api_provider": settings.cloud_api_provider or "None (local only)",
                "database_path": str(settings.database_path),
                "artifacts_dir": str(settings.artifacts_dir),
                "log_dir": str(settings.log_dir),
                "api_host": settings.api_host,
                "api_port": settings.api_port,
                "n8n_base_url": settings.n8n_base_url,
            }
            self._send_json(HTTPStatus.OK, safe_settings)
            return

        if path == "/api/logs":
            log_file = settings.log_dir / "personal_ai.log"
            content = ""
            if log_file.exists():
                try:
                    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
                    content = "\n".join(lines[-150:])
                except Exception as e:
                    content = f"Error reading logs: {e}"
            self._send_json(HTTPStatus.OK, {"logs": content})
            return

        # 4. Authenticated Webhook Endpoints (e.g. n8n)
        if path.startswith("/webhook/"):
            if not self._is_authenticated():
                self._send_json(
                    HTTPStatus.UNAUTHORIZED,
                    {"error": "Unauthorized: Missing or invalid API key in headers"},
                )
                return

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
                self._send_json(HTTPStatus.OK, {"task": task, "steps": steps, "artifacts": artifacts})
                return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Path not found: {self.path}"})

    def do_POST(self) -> None:
        """Handle POST requests for Webhooks and Dashboard Actions."""
        # Read and drain request body before returning any status code
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b""

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        # Check authentication for /webhook/* endpoints
        if path.startswith("/webhook/") and not self._is_authenticated():
            self._send_json(
                HTTPStatus.UNAUTHORIZED,
                {"error": "Unauthorized: Missing or invalid API key in headers"},
            )
            return

        if not body_bytes:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Request body cannot be empty"})
            return

        try:
            body_json = json.loads(body_bytes.decode("utf-8"))
        except Exception as e:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": f"Invalid JSON payload: {e}"})
            return

        # 1. Trigger Task (/webhook/task or /api/tasks/run)
        if path in ("/webhook/task", "/api/tasks/run"):
            try:
                task_req = TaskWebhookRequest(**body_json)
            except ValidationError as ve:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid request schema", "details": ve.errors()})
                return

            logger.info("Executing task via server: '%s'", task_req.prompt)

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

            # Dispatch callback to n8n if requested
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

        # 2. Webhook Notification
        if path == "/webhook/notify":
            try:
                notif = NotificationRequest(**body_json)
            except ValidationError as ve:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid notification schema", "details": ve.errors()})
                return

            logger.info("Received notification from %s: '%s'", notif.source, notif.event)
            self._send_json(HTTPStatus.OK, {"status": "received", "event": notif.event, "source": notif.source})
            return

        # 3. Resolve Approval (/api/approvals/<id>/resolve)
        if path.startswith("/api/approvals/") and path.endswith("/resolve"):
            approval_id = path.replace("/api/approvals/", "").replace("/resolve", "").strip()
            decision = body_json.get("decision", "approved")
            reason = body_json.get("reason", "Resolved via Dashboard")

            approval_repo = ApprovalRepository()
            app = approval_repo.get_approval(approval_id)
            if not app:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Approval '{approval_id}' not found"})
                return

            approval_repo.resolve_approval(approval_id, decision, reason)
            self._send_json(HTTPStatus.OK, {"status": "resolved", "approval_id": approval_id, "decision": decision})
            return

        # 4. Clipboard Operations
        if path == "/api/clipboard/capture":
            monitor = ClipboardMonitor()
            captured = monitor.check_once()
            self._send_json(HTTPStatus.OK, {"captured": captured})
            return

        if path == "/api/clipboard/copy":
            entry_id = body_json.get("entry_id")
            if not entry_id:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Missing entry_id"})
                return

            clip_repo = ClipboardRepository()
            entry = clip_repo.get_entry(entry_id)
            if not entry or not entry.get("content_text"):
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Clipboard entry not found"})
                return

            success = WindowsClipboard.set_text(entry["content_text"])
            self._send_json(HTTPStatus.OK, {"success": success, "entry_id": entry_id})
            return

        # 5. Desktop Operations
        if path == "/api/desktop/screenshot":
            file_name = body_json.get("file_name")
            try:
                res = capture_desktop_screenshot(file_name=file_name)
                self._send_json(HTTPStatus.OK, res)
            except Exception as e:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(e)})
            return

        if path == "/api/desktop/focus":
            title = body_json.get("title", "")
            try:
                res = focus_window_by_title(title)
                self._send_json(HTTPStatus.OK, res)
            except Exception as e:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(e)})
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown endpoint: {path}"})

    def log_message(self, format: str, *args: Any) -> None:
        """Route server request logging through Personal AI logger."""
        logger.debug("%s - - [%s] %s", self.address_string(), self.log_date_time_string(), format % args)


class PersonalAIWebhookServer:
    """Manages the lifecycle of the webhook and dashboard server."""

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None):
        self.host = host or settings.api_host
        self.port = port or settings.api_port
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self, block: bool = True) -> None:
        """Start the HTTP server on configured host and port."""
        self._server = ThreadingHTTPServer((self.host, self.port), WebhookRequestHandler)
        logger.info("Personal AI Dashboard & Webhook Server listening on http://%s:%d", self.host, self.port)

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
