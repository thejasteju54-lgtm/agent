"""Security hardening, path containment, prompt injection defense, and emergency stop."""

import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from personal_ai.config import settings
from personal_ai.logging.setup import get_logger

logger = get_logger(__name__)

# Patterns indicating potential indirect prompt injection embedded in external data
SUSPICIOUS_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(?:all\s+)?previous\s+(?:instructions|rules|prompts)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(?:in|operating\s+as)\s+(?:developer\s+mode|unrestricted|god\s+mode|dan)", re.IGNORECASE),
    re.compile(r"disregard\s+(?:the\s+)?(?:safety|system|permission)\s+guidelines", re.IGNORECASE),
    re.compile(r"elevate\s+privileges?\s+to\s+admin", re.IGNORECASE),
    re.compile(r"system\s+override:\s*", re.IGNORECASE),
    re.compile(r"execute\s+(?:format\s+[c-z]:|rmdir\s+/s|del\s+/f|rm\s+-rf)", re.IGNORECASE),
    re.compile(r"send\s+(?:all\s+)?passwords?\s+to\s+http", re.IGNORECASE),
]

# Patterns for sensitive tokens / secrets redaction
SENSITIVE_PATTERNS = [
    (re.compile(r"(api[_-]?key|access[_-]?token|secret|password|bearer\s+[a-z0-9_\-\.]+)\s*[:=]\s*['\"]?([a-zA-Z0-9_\-\.]{8,})['\"]?", re.IGNORECASE), r"\1=***REDACTED***"),
    (re.compile(r"sk-[a-zA-Z0-9]{20,}", re.IGNORECASE), "***REDACTED_API_KEY***"),
    (re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"), "***REDACTED_CARD_NUMBER***"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9\-\._~\+\/]+=*", re.IGNORECASE), r"\1***REDACTED_BEARER_TOKEN***"),
]

# Critical Windows System Directories that should never be written to or deleted
BLOCKED_WINDOWS_PATHS: Set[str] = {
    r"c:\windows",
    r"c:\windows\system32",
    r"c:\windows\syswow64",
    r"c:\program files",
    r"c:\program files (x86)",
    r"c:\boot",
    r"c:\recovery",
}


class PathSecurityError(PermissionError):
    """Raised when a file operation attempts to access an unauthorized or dangerous directory."""
    pass


class PromptInjectionWarning:
    """Represents a detected injection attempt inside untrusted content."""

    def __init__(self, detected_phrase: str, pattern: str):
        self.detected_phrase = detected_phrase
        self.pattern = pattern

    def __repr__(self) -> str:
        return f"PromptInjectionWarning(phrase='{self.detected_phrase}')"


def validate_path_safety(
    target_path: Path | str,
    allow_write: bool = False,
    allow_delete: bool = False,
    custom_allowed_roots: Optional[List[Path]] = None,
) -> Path:
    """Validate that a path does not target critical Windows system directories or attempt path traversal.

    Args:
        target_path: Path to validate.
        allow_write: Whether the operation plans to write or create files.
        allow_delete: Whether the operation plans to delete files or directories.
        custom_allowed_roots: Optional list of directory roots permitted for writing/deleting.

    Returns:
        The resolved Path.

    Raises:
        PathSecurityError: If the target path violates security boundaries.
    """
    path_obj = Path(target_path).resolve()
    path_str = str(path_obj).lower()

    # 1. Check for blocked Windows system directories
    for blocked in BLOCKED_WINDOWS_PATHS:
        if path_str == blocked or path_str.startswith(blocked + "\\"):
            if allow_write or allow_delete:
                logger.critical("Path security violation: Attempt to modify system directory: %s", path_obj)
                raise PathSecurityError(f"Security Policy: Access to critical system directory '{path_obj}' is strictly prohibited.")

    # 2. Prevent root drive deletion (e.g. C:\)
    if allow_delete:
        if path_obj.parent == path_obj or str(path_obj).endswith(":\\"):
            logger.critical("Path security violation: Attempt to delete root volume: %s", path_obj)
            raise PathSecurityError(f"Security Policy: Deletion of root drive volume '{path_obj}' is strictly prohibited.")

    # 3. If restricted to allowed roots, enforce confinement
    if custom_allowed_roots:
        resolved_roots = [r.resolve() for r in custom_allowed_roots]
        within_any = any(
            str(path_obj).lower().startswith(str(root).lower())
            for root in resolved_roots
        )
        if not within_any:
            raise PathSecurityError(f"Security Policy: Path '{path_obj}' is outside permitted workspace roots.")

    return path_obj


def scan_untrusted_content(content: str) -> List[PromptInjectionWarning]:
    """Scan external content (from web pages, emails, clipboard, PDFs) for prompt injection patterns.

    External instructions MUST NEVER be treated as authorization to bypass user safety policies.
    """
    warnings = []
    if not content:
        return warnings

    for pattern in SUSPICIOUS_INJECTION_PATTERNS:
        matches = pattern.finditer(content)
        for match in matches:
            warnings.append(PromptInjectionWarning(match.group(0), pattern.pattern))
            logger.warning("Indirect Prompt Injection attempt detected: '%s'", match.group(0))

    return warnings


def redact_sensitive_text(text: str) -> str:
    """Redact API keys, tokens, credit cards, and credentials from string output or logs."""
    if not text:
        return text

    sanitized = text
    for pattern, replacement in SENSITIVE_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


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
                cls._instance._stop_flag_file = settings.data_dir / ".emergency_stop"
        return cls._instance

    @property
    def is_stopped(self) -> bool:
        """Check if emergency stop has been activated (in-memory or file flag)."""
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
        return self._stop_reason

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
