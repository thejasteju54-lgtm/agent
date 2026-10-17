"""Windows clipboard capture, monitoring, classification, and search tools."""

import ctypes
import hashlib
import re
import sys
import threading
import time
import uuid
from ctypes import wintypes
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from personal_ai.agent.task_models import RiskLevel
from personal_ai.config import settings
from personal_ai.storage.database import Database, get_db
from personal_ai.storage.repositories import ClipboardRepository
from personal_ai.tools.registry import BaseTool, default_registry
from personal_ai.logging.setup import get_logger

logger = get_logger(__name__)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


class WindowsClipboard:
    """Low-level native Windows clipboard access using Win32 user32/kernel32 APIs."""

    @staticmethod
    def _get_user32():
        if sys.platform != "win32":
            return None
        return ctypes.windll.user32

    @staticmethod
    def _get_kernel32():
        if sys.platform != "win32":
            return None
        return ctypes.windll.kernel32

    @classmethod
    def get_text(cls) -> Optional[str]:
        """Read unicode text currently on the Windows clipboard."""
        user32 = cls._get_user32()
        if not user32:
            return None

        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = wintypes.HANDLE

        # Retry up to 3 times in case clipboard is temporarily locked by another app
        for _ in range(3):
            if user32.OpenClipboard(None):
                try:
                    h_data = user32.GetClipboardData(CF_UNICODETEXT)
                    if h_data:
                        text = ctypes.c_wchar_p(h_data).value
                        return text
                    return None
                finally:
                    user32.CloseClipboard()
            time.sleep(0.05)
        return None

    @classmethod
    def set_text(cls, text: str) -> bool:
        """Place unicode text onto the Windows clipboard."""
        user32 = cls._get_user32()
        kernel32 = cls._get_kernel32()
        if not user32 or not kernel32:
            return False

        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE

        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL

        for _ in range(3):
            if user32.OpenClipboard(None):
                try:
                    user32.EmptyClipboard()
                    encoded = text.encode("utf-16-le") + b"\x00\x00"
                    h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
                    p_mem = kernel32.GlobalLock(h_mem)
                    ctypes.memmove(p_mem, encoded, len(encoded))
                    kernel32.GlobalUnlock(h_mem)
                    user32.SetClipboardData(CF_UNICODETEXT, h_mem)
                    return True
                finally:
                    user32.CloseClipboard()
            time.sleep(0.05)
        return False

    @staticmethod
    def classify_content(text: str) -> str:
        """Classify clipboard content as 'url', 'code', 'prompt', or 'text'."""
        stripped = text.strip()

        # URL detection
        if re.match(r"^https?://[^\s]+$", stripped):
            return "url"

        # Code detection heuristics
        code_patterns = [
            r"^\s*(def|class|import|from|return|function|const|let|var|SELECT|INSERT|UPDATE|DELETE)\b",
            r"[;{}()\[\]=>]",
            r"^<[a-zA-Z0-9]+.*>.*</[a-zA-Z0-9]+>$",
        ]
        if any(re.search(p, stripped, re.MULTILINE) for p in code_patterns) and "\n" in stripped:
            return "code"

        # Prompt detection
        if stripped.lower().startswith(("what is", "how to", "write a", "explain", "please", "can you", "create a")):
            return "prompt"

        return "text"

    @staticmethod
    def hash_content(text: str) -> str:
        """Compute stable SHA-256 hash of text content for deduplication."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def is_sensitive(text: str) -> bool:
        """Check if content matches sensitive patterns (e.g. private keys, credentials)."""
        sensitive_patterns = [
            r"-----BEGIN [A-Z ]*KEY-----",
            r"(?i)(password|secret|api[_\-]?key|access[_\-]?token|bearer)\s*[:=]\s*['\"][^\s]{8,}['\"]",
            r"\b[A-Za-z0-9+/]{40,}\b",  # Generic base64 tokens/keys
        ]
        return any(re.search(p, text) for p in sensitive_patterns)


class ClipboardMonitor:
    """Background service monitoring clipboard changes and recording to SQLite."""

    def __init__(self, db: Optional[Database] = None, poll_interval_sec: float = 1.0):
        self.db = db or get_db()
        self.repo = ClipboardRepository(self.db)
        self.poll_interval_sec = poll_interval_sec
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_hash: Optional[str] = None
        self.total_captured = 0

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    def pause(self) -> None:
        self._pause_event.set()
        logger.info("Clipboard monitoring paused.")

    def resume(self) -> None:
        self._pause_event.clear()
        logger.info("Clipboard monitoring resumed.")

    def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self._pause_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("Clipboard monitoring started (interval: %.1fs).", self.poll_interval_sec)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        logger.info("Clipboard monitoring stopped.")

    def check_once(self) -> Optional[Dict[str, Any]]:
        """Perform a single poll check of the clipboard."""
        text = WindowsClipboard.get_text()
        if not text or not text.strip():
            return None

        # Redact/skip sensitive content
        if WindowsClipboard.is_sensitive(text):
            logger.debug("Skipping sensitive clipboard entry.")
            return None

        content_hash = WindowsClipboard.hash_content(text)
        if content_hash == self._last_hash:
            return None

        self._last_hash = content_hash
        content_type = WindowsClipboard.classify_content(text)
        entry_id = str(uuid.uuid4())

        entry = self.repo.save_entry(
            entry_id=entry_id,
            content_hash=content_hash,
            content_type=content_type,
            content_text=text,
        )
        self.total_captured += 1
        logger.debug("Captured clipboard entry [%s]: %s...", content_type, text[:30])
        return entry

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._pause_event.is_set():
                try:
                    self.check_once()
                except Exception as e:
                    logger.debug("Clipboard poll error: %s", e)
            self._stop_event.wait(self.poll_interval_sec)


# --- Reusable Registered Tools ---


class GetLatestInput(BaseModel):
    pass


class ClipboardGetLatestTool(BaseTool):
    name = "clipboard_get_latest"
    description = "Retrieve the most recent entry from clipboard history."
    risk_level = RiskLevel.LOW
    args_schema = GetLatestInput

    def execute(self) -> Dict[str, Any]:
        repo = ClipboardRepository()
        latest = repo.get_latest()
        if not latest:
            # Fall back to live clipboard read if DB history is empty
            live_text = WindowsClipboard.get_text()
            if live_text:
                return {
                    "source": "live",
                    "content_type": WindowsClipboard.classify_content(live_text),
                    "content_text": live_text,
                }
            return {"status": "empty", "message": "Clipboard history is empty."}
        return {"source": "history", **latest}


class SearchInput(BaseModel):
    query: Optional[str] = Field(default=None, description="Substring or keyword to search for.")
    content_type: Optional[str] = Field(default=None, description="Filter by type ('text', 'url', 'code', 'prompt').")
    limit: int = Field(default=20, description="Maximum number of entries to return.")


class ClipboardSearchTool(BaseTool):
    name = "clipboard_search"
    description = "Search stored clipboard history by keyword or content type."
    risk_level = RiskLevel.LOW
    args_schema = SearchInput

    def execute(
        self,
        query: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        repo = ClipboardRepository()
        results = repo.search_entries(query=query, content_type=content_type, limit=limit)
        return {
            "query": query,
            "content_type": content_type,
            "total_found": len(results),
            "entries": results,
        }


class SetClipboardInput(BaseModel):
    text: str = Field(..., description="Text content to place onto the Windows clipboard.")


class ClipboardSetTool(BaseTool):
    name = "clipboard_set"
    description = "Copy text onto the active Windows clipboard."
    risk_level = RiskLevel.LOW
    modifies_state = True
    args_schema = SetClipboardInput

    def execute(self, text: str) -> Dict[str, Any]:
        success = WindowsClipboard.set_text(text)
        return {
            "status": "success" if success else "failed",
            "characters_copied": len(text),
        }


class DeleteClipboardInput(BaseModel):
    entry_id: str = Field(..., description="ID of the clipboard entry to delete.")


class ClipboardDeleteTool(BaseTool):
    name = "clipboard_delete"
    description = "Delete a specific entry from clipboard history."
    risk_level = RiskLevel.LOW
    modifies_state = True
    args_schema = DeleteClipboardInput

    def execute(self, entry_id: str) -> Dict[str, Any]:
        repo = ClipboardRepository()
        deleted = repo.delete_entry(entry_id)
        return {
            "entry_id": entry_id,
            "deleted": deleted,
            "status": "success" if deleted else "not_found",
        }


# Register clipboard tools in default_registry
default_registry.register(ClipboardGetLatestTool())
default_registry.register(ClipboardSearchTool())
default_registry.register(ClipboardSetTool())
default_registry.register(ClipboardDeleteTool())
