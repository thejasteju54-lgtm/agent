"""Security hardening, operating-mode enforcement, and emergency stop for MarketPulse AI."""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
from typing import Any, List, Optional

from marketpulse.config import mp_settings
from marketpulse.logging.setup import get_logger

logger = get_logger(__name__)


class EmergencyStopActiveError(RuntimeError):
    """Raised when an operation is attempted while Emergency Stop is active."""
    pass


class OperatingModeError(RuntimeError):
    """Raised when a tool or operation is incompatible with the active operating mode (e.g. desktop GUI in cloud)."""
    pass


class EmergencyStopManager:
    """Global emergency stop coordinator to immediately halt all active automation tasks."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(EmergencyStopManager, cls).__new__(cls)
                cls._instance._is_stopped = False
                cls._instance._stop_reason = ""
                cls._instance._stop_flag_file = mp_settings.data_dir / ".emergency_stop"
        return cls._instance

    @property
    def is_stopped(self) -> bool:
        """Check if emergency stop has been activated (in-memory or persistent flag file)."""
        if self._is_stopped:
            return True
        if self._stop_flag_file.exists():
            self._is_stopped = True
            try:
                self._stop_reason = self._stop_flag_file.read_text(encoding="utf-8")
            except Exception:
                self._stop_reason = "Emergency stop flag file detected."
            return True
        return False

    @property
    def stop_reason(self) -> str:
        return self._stop_reason or "Emergency stop activated by operator."

    def trigger(self, reason: str = "User initiated Emergency Stop") -> None:
        """Activate global emergency stop."""
        with self._lock:
            self._is_stopped = True
            self._stop_reason = reason
            logger.critical("EMERGENCY STOP ACTIVATED: %s", reason)
            try:
                self._stop_flag_file.parent.mkdir(parents=True, exist_ok=True)
                self._stop_flag_file.write_text(reason, encoding="utf-8")
            except Exception as e:
                logger.error("Failed to write emergency stop flag file: %s", e)

    def reset(self) -> None:
        """Reset emergency stop state to allow normal execution."""
        with self._lock:
            self._is_stopped = False
            self._stop_reason = ""
            logger.info("Emergency stop has been cleared.")
            if self._stop_flag_file.exists():
                try:
                    self._stop_flag_file.unlink()
                except Exception as e:
                    logger.error("Failed to delete emergency stop flag file: %s", e)


emergency_stop = EmergencyStopManager()


def check_operating_mode_capability(
    tool_name: str,
    active_mode: Optional[str] = None,
    supported_modes: Optional[List[str]] = None,
) -> None:
    """Enforce operating mode boundaries between desktop and cloud execution.

    In cloud mode, local Windows GUI/desktop inspection and PyAutoGUI tools are blocked.
    """
    mode = active_mode or mp_settings.operating_mode
    valid_modes = supported_modes or ["desktop", "cloud"]

    if mode not in valid_modes:
        raise OperatingModeError(
            f"Tool '{tool_name}' is not supported in '{mode}' mode. Supported operating modes: {valid_modes}."
        )


# ---------------------------------------------------------------------------
# Path Containment & Traversal Defense
# ---------------------------------------------------------------------------
BLOCKED_SYSTEM_PATHS = {
    r"c:\windows",
    r"c:\windows\system32",
    r"c:\windows\syswow64",
    r"c:\program files",
    r"c:\program files (x86)",
    r"c:\boot",
    r"c:\recovery",
}


def validate_path_safety(
    target_path: Path | str,
    allow_write: bool = False,
    allow_delete: bool = False,
    allowed_roots: Optional[List[Path]] = None,
) -> Path:
    """Validate that a path does not target sensitive system directories or traverse outside permitted roots."""
    path_obj = Path(target_path).resolve()
    path_str = str(path_obj).lower()

    # Blocked Windows system paths
    for blocked in BLOCKED_SYSTEM_PATHS:
        if path_str == blocked or path_str.startswith(blocked + "\\"):
            if allow_write or allow_delete:
                logger.critical("Path security violation: Attempted write/delete in system dir: %s", path_obj)
                raise PermissionError(f"Access to critical system path '{path_obj}' is strictly prohibited.")

    # Prevent root drive deletion (e.g. C:\)
    if allow_delete and (path_obj.parent == path_obj or str(path_obj).endswith(":\\")):
        raise PermissionError(f"Deletion of root volume '{path_obj}' is strictly prohibited.")

    # Confinement to allowed roots
    roots = allowed_roots or [mp_settings.project_root, mp_settings.artifacts_dir, mp_settings.data_dir]
    resolved_roots = [r.resolve() for r in roots]
    within_any = any(str(path_obj).lower().startswith(str(r).lower()) for r in resolved_roots)
    if not within_any:
        raise PermissionError(f"Security Policy: Path '{path_obj}' is outside permitted project boundaries.")

    return path_obj


# ---------------------------------------------------------------------------
# Indirect Prompt Injection Neutralizer
# ---------------------------------------------------------------------------
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(?:all\s+)?previous\s+(?:instructions|rules|prompts)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(?:in|operating\s+as)\s+(?:developer\s+mode|unrestricted|god\s+mode|dan)", re.IGNORECASE),
    re.compile(r"disregard\s+(?:the\s+)?(?:safety|system|permission)\s+guidelines", re.IGNORECASE),
    re.compile(r"elevate\s+privileges?\s+to\s+admin", re.IGNORECASE),
    re.compile(r"system\s+override:\s*", re.IGNORECASE),
    re.compile(r"execute\s+(?:format\s+[c-z]:|rmdir\s+/s|del\s+/f|rm\s+-rf)", re.IGNORECASE),
    re.compile(r"place\s+(?:buy|sell)\s+order", re.IGNORECASE),
]


def scan_untrusted_financial_content(content: str) -> List[str]:
    """Scan news, filings, or prompt text for indirect prompt injection or trading override patterns."""
    warnings = []
    if not content:
        return warnings

    for pattern in INJECTION_PATTERNS:
        match = pattern.search(content)
        if match:
            warnings.append(f"Suspicious pattern detected: '{match.group(0)}'")
    return warnings


# ---------------------------------------------------------------------------
# Ungraceful Exit & Interrupted Task Recovery
# ---------------------------------------------------------------------------
def recover_interrupted_tasks(session: Any) -> int:
    """Detect and recover tasks left in non-terminal running state across server restarts."""
    from marketpulse.storage.models import AutomationTask, AuditEvent, TaskStatus

    interrupted_statuses = [TaskStatus.RUNNING.value, TaskStatus.PLANNING.value, TaskStatus.VERIFYING.value]
    tasks = session.query(AutomationTask).filter(AutomationTask.status.in_(interrupted_statuses)).all()

    now_utc = datetime.now(timezone.utc)
    count = 0
    for t in tasks:
        t.status = TaskStatus.FAILED.value
        t.cancellation_reason = "Process interrupted prior to completion; state preserved in database."
        t.completed_at = now_utc

        audit = AuditEvent(
            event_type="TASK_RECOVERED",
            entity_type="AutomationTask",
            entity_id=t.id,
            details_json=json.dumps({"prior_step": t.current_step, "reason": t.cancellation_reason}),
            actor="recovery_manager",
            timestamp=now_utc,
        )
        session.add(audit)
        count += 1

    if count > 0:
        session.commit()
        logger.warning("Recovered %d interrupted tasks from previous abnormal shutdown.", count)
    return count
