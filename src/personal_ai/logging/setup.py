"""Logging setup for Personal AI Automation System."""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional
from personal_ai.config import settings

_LOGGING_INITIALIZED = False


def setup_logging(
    log_level: Optional[str] = None,
    log_dir: Optional[Path] = None,
    console_output: bool = True,
) -> None:
    """Initialize structured application logging.

    Args:
        log_level: Optional logging level name (e.g. 'DEBUG', 'INFO').
        log_dir: Optional directory where log files are stored.
        console_output: Whether to attach a stdout console handler.
    """
    global _LOGGING_INITIALIZED
    level_name = log_level or settings.log_level
    numeric_level = getattr(logging, level_name.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Avoid duplicate handlers if re-initialized
    if root_logger.handlers:
        root_logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        target_dir = log_dir or settings.log_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        log_file = target_dir / "personal_ai.log"
        file_handler = logging.handlers.RotatingFileHandler(
            filename=str(log_file),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except Exception:
        # Fallback gracefully in read-only serverless filesystems (e.g. Vercel)
        pass

    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    _LOGGING_INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    """Retrieve a configured logger by component name."""
    if not _LOGGING_INITIALIZED:
        setup_logging()
    return logging.getLogger(name)
