"""Structured logging setup for MarketPulse AI with active secret redaction."""

import logging
import logging.handlers
import re
import sys
from pathlib import Path
from typing import Optional, Set

from marketpulse.config import mp_settings

_LOGGING_INITIALIZED = False

# Common secret patterns: bearer tokens, high-entropy hex/base64 strings, API keys
TOKEN_PATTERN = re.compile(r"(Bearer\s+)([A-Za-z0-9_\-\.]{12,})", re.IGNORECASE)
GENERIC_SECRET_PATTERN = re.compile(
    r"(api[_-]?key|secret[_-]?key|password|token|authorization)\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.]{8,})['\"]?",
    re.IGNORECASE,
)


class RedactingFormatter(logging.Formatter):
    """Custom logging formatter that strips API tokens and sensitive credentials from log outputs."""

    def __init__(self, fmt: Optional[str] = None, datefmt: Optional[str] = None):
        super().__init__(fmt=fmt, datefmt=datefmt)

    def _get_active_secrets(self) -> Set[str]:
        """Fetch current configured secrets that should never appear in plaintext."""
        secrets: Set[str] = set()
        if mp_settings.api_secret_key and len(mp_settings.api_secret_key) >= 6:
            secrets.add(mp_settings.api_secret_key)
        if mp_settings.n8n_api_key and len(mp_settings.n8n_api_key) >= 6:
            secrets.add(mp_settings.n8n_api_key)
        if mp_settings.cloud_api_key and len(mp_settings.cloud_api_key) >= 6:
            secrets.add(mp_settings.cloud_api_key)
        return secrets

    def format(self, record: logging.LogRecord) -> str:
        original = super().format(record)
        redacted = original

        # 1. Redact known active secrets
        for secret in self._get_active_secrets():
            if secret in redacted:
                redacted = redacted.replace(secret, "[REDACTED_SECRET]")

        # 2. Redact Bearer tokens
        redacted = TOKEN_PATTERN.sub(r"\1[REDACTED_TOKEN]", redacted)

        # 3. Redact key-value pairs with sensitive names
        redacted = GENERIC_SECRET_PATTERN.sub(r"\1: '[REDACTED]'", redacted)

        return redacted


def setup_logging(
    log_level: Optional[str] = None,
    log_dir: Optional[Path] = None,
    console_output: bool = True,
) -> None:
    """Initialize structured application logging with rotating file handler and secret redaction.

    Args:
        log_level: Optional logging level name (e.g. 'DEBUG', 'INFO').
        log_dir: Optional directory where log files are stored.
        console_output: Whether to attach a stdout console handler.
    """
    global _LOGGING_INITIALIZED
    level_name = log_level or mp_settings.log_level
    numeric_level = getattr(logging, level_name.upper(), logging.INFO)

    target_dir = log_dir or mp_settings.log_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    log_file = target_dir / "marketpulse.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Avoid duplicate handlers if re-initialized
    if root_logger.handlers:
        root_logger.handlers.clear()

    formatter = RedactingFormatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler (up to 10MB per file, keeping 5 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        filename=str(log_file),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    _LOGGING_INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    """Get a named logger, initializing logging with defaults if not already setup."""
    global _LOGGING_INITIALIZED
    if not _LOGGING_INITIALIZED:
        setup_logging()
    return logging.getLogger(name)
