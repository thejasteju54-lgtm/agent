"""Playwright browser automation tools with verification and artifact capture."""

import uuid
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from personal_ai.agent.task_models import RiskLevel
from personal_ai.config import settings
from personal_ai.storage.artifacts import ArtifactManager
from personal_ai.tools.registry import BaseTool, default_registry
from personal_ai.logging.setup import get_logger

logger = get_logger(__name__)


class BrowserSessionManager:
    """Manages dedicated, isolated Playwright browser instances."""

    _instance: Optional["BrowserSessionManager"] = None

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    @classmethod
    def get_instance(cls) -> "BrowserSessionManager":
        if cls._instance is None:
            cls._instance = BrowserSessionManager()
        return cls._instance

    def get_page(self):
        """Get or create active browser page in isolated context."""
        if self._page is None or self._page.is_closed():
            from playwright.sync_api import sync_playwright

            if self._playwright is None:
                self._playwright = sync_playwright().start()

            if self._browser is None:
                self._browser = self._playwright.chromium.launch(
                    headless=settings.playwright_headless,
                )

            self._context = self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="PersonalAI-Automation/1.0 (Windows NT 10.0; Win64; x64)",
            )
            self._page = self._context.new_page()
            self._page.set_default_timeout(settings.playwright_timeout_ms)

        return self._page

    def close(self) -> None:
        """Safely close active browser context and engine."""
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception as e:
            logger.debug("Error while closing browser session: %s", e)
        finally:
            self._playwright = None
            self._browser = None
            self._context = None
            self._page = None


class OpenUrlInput(BaseModel):
    url: str = Field(..., description="Target URL to open (must be http://, https://, or file://).")
    timeout_ms: Optional[int] = Field(default=None, description="Navigation timeout in milliseconds.")


class BrowserOpenUrlTool(BaseTool):
    name = "browser_open_url"
    description = "Navigate browser to an approved web URL."
    risk_level = RiskLevel.LOW
    args_schema = OpenUrlInput

    def execute(self, url: str, timeout_ms: Optional[int] = None) -> Dict[str, Any]:
        if not (url.startswith("http://") or url.startswith("https://") or url.startswith("file://")):
            raise ValueError(f"Invalid URL protocol: '{url}'. Only http, https, and file are allowed.")

        page = BrowserSessionManager.get_instance().get_page()
        timeout = timeout_ms or settings.playwright_timeout_ms

        logger.info("Navigating to URL: %s", url)
        response = page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        status_code = response.status if response else 200

        return {
            "requested_url": url,
            "final_url": page.url,
            "title": page.title(),
            "status_code": status_code,
        }


class ExtractContentInput(BaseModel):
    selector: str = Field(default="body", description="CSS or semantic selector to extract text from.")
    max_chars: int = Field(default=5000, description="Maximum characters of text to return.")


class BrowserExtractContentTool(BaseTool):
    name = "browser_extract_content"
    description = "Extract text content from current browser page."
    risk_level = RiskLevel.LOW
    args_schema = ExtractContentInput

    def execute(self, selector: str = "body", max_chars: int = 5000) -> Dict[str, Any]:
        page = BrowserSessionManager.get_instance().get_page()
        element = page.locator(selector).first
        if not element.is_visible(timeout=5000):
            raise ValueError(f"Element matching '{selector}' not visible on page.")

        text = element.inner_text() or ""
        clean_text = " ".join(text.split())

        return {
            "selector": selector,
            "text": clean_text[:max_chars],
            "total_chars": len(clean_text),
            "truncated": len(clean_text) > max_chars,
            "page_title": page.title(),
            "page_url": page.url,
        }


class ScreenshotInput(BaseModel):
    file_name: Optional[str] = Field(default=None, description="Optional custom filename for screenshot.")
    full_page: bool = Field(default=False, description="Whether to capture full scrollable page.")
    task_id: Optional[str] = Field(default=None, description="Associated task ID for artifact grouping.")


class BrowserScreenshotTool(BaseTool):
    name = "browser_screenshot"
    description = "Capture a screenshot of current browser page and save to artifacts."
    risk_level = RiskLevel.LOW
    args_schema = ScreenshotInput
    modifies_state = True

    def execute(
        self,
        file_name: Optional[str] = None,
        full_page: bool = False,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        page = BrowserSessionManager.get_instance().get_page()
        name = file_name or f"screenshot_{uuid.uuid4().hex[:8]}.png"
        if not name.lower().endswith(".png"):
            name += ".png"

        img_bytes = page.screenshot(full_page=full_page)
        artifact_mgr = ArtifactManager()
        artifact = artifact_mgr.save_bytes(name, img_bytes, task_id=task_id, mime_type="image/png")

        return {
            "artifact_id": artifact["id"],
            "file_name": artifact["file_name"],
            "file_path": artifact["file_path"],
            "size_bytes": artifact["size_bytes"],
            "page_title": page.title(),
            "page_url": page.url,
        }


class ClickInput(BaseModel):
    selector: str = Field(..., description="Selector, text or role of element to click.")


class BrowserClickTool(BaseTool):
    name = "browser_click"
    description = "Click an interactive element on the current page."
    risk_level = RiskLevel.LOW
    args_schema = ClickInput

    def execute(self, selector: str) -> Dict[str, Any]:
        page = BrowserSessionManager.get_instance().get_page()
        logger.info("Clicking element: %s", selector)
        page.click(selector, timeout=settings.playwright_timeout_ms)
        page.wait_for_load_state("domcontentloaded", timeout=10000)

        return {
            "clicked": selector,
            "final_url": page.url,
            "title": page.title(),
        }


class FillInput(BaseModel):
    selector: str = Field(..., description="Selector of form input.")
    value: str = Field(..., description="Text value to enter into input.")


class BrowserFillTool(BaseTool):
    name = "browser_fill"
    description = "Fill text into a form input element."
    risk_level = RiskLevel.LOW
    args_schema = FillInput

    def execute(self, selector: str, value: str) -> Dict[str, Any]:
        page = BrowserSessionManager.get_instance().get_page()
        logger.info("Filling input '%s'", selector)
        page.fill(selector, value, timeout=settings.playwright_timeout_ms)

        return {
            "filled": selector,
            "status": "success",
        }


# Register browser tools into default_registry
default_registry.register(BrowserOpenUrlTool())
default_registry.register(BrowserExtractContentTool())
default_registry.register(BrowserScreenshotTool())
default_registry.register(BrowserClickTool())
default_registry.register(BrowserFillTool())
