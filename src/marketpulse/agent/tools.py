"""Per-tool schemas and implementations for MarketPulse AI automation across 3 categories.

Categories:
1. Research collection & report generation.
2. Browser automation.
3. Desktop & filesystem automation.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, Field

from marketpulse.config import mp_settings
from marketpulse.agent.permissions import RiskLevel, ProhibitedActionError
from marketpulse.storage.database import get_session
from marketpulse.storage.artifacts import MarketPulseArtifactStore
from marketpulse.logging.setup import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Base Tool Abstraction
# ---------------------------------------------------------------------------
class MarketPulseTool(ABC):
    """Abstract base class for all MarketPulse automation tools."""
    name: str
    description: str
    risk_level: RiskLevel = RiskLevel.LOW
    timeout_sec: float = 30.0
    modifies_state: bool = False
    supported_modes: List[str] = ["desktop", "cloud"]
    args_schema: Optional[Type[BaseModel]] = None

    @abstractmethod
    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        """Execute tool action with validated parameters."""
        pass


# ---------------------------------------------------------------------------
# Category 1: Research Collection & Reporting Tools (LOW Risk)
# ---------------------------------------------------------------------------
class CollectSourceEvidenceInput(BaseModel):
    source_id: str = Field(default="permitted_financial_rss", description="Approved source identifier")
    target_symbol: Optional[str] = Field(default=None, description="Optional target stock ticker")


class CollectSourceEvidenceTool(MarketPulseTool):
    name = "collect_source_evidence"
    description = "Collect fresh disclosures or articles from an approved official/permitted source."
    risk_level = RiskLevel.LOW
    timeout_sec = 20.0
    modifies_state = True
    args_schema = CollectSourceEvidenceInput

    def execute(self, session: Optional[Any] = None, **kwargs: Any) -> Dict[str, Any]:
        from marketpulse.research.collectors import SourceCollector
        if session is not None:
            collector = SourceCollector(session=session)
            items = collector.collect_from_source(
                source_id=kwargs.get("source_id", "permitted_financial_rss"),
                target_symbol=kwargs.get("target_symbol"),
            )
            return {
                "collected_count": len(items),
                "source_id": kwargs.get("source_id"),
                "status": "SUCCESS",
            }
        with get_session() as sess:
            collector = SourceCollector(session=sess)
            items = collector.collect_from_source(
                source_id=kwargs.get("source_id", "permitted_financial_rss"),
                target_symbol=kwargs.get("target_symbol"),
            )
            sess.commit()
            return {
                "collected_count": len(items),
                "source_id": kwargs.get("source_id"),
                "status": "SUCCESS",
            }


class GenerateResearchReportInput(BaseModel):
    prompt: str = Field(..., description="Research question or analysis objective")
    company_symbol: Optional[str] = Field(default=None, description="NSE/BSE company symbol")


class GenerateResearchReportTool(MarketPulseTool):
    name = "generate_research_report"
    description = "Run the 7-step bounded research pipeline and save report artifacts inside approved directory."
    risk_level = RiskLevel.LOW
    timeout_sec = 60.0
    modifies_state = True
    args_schema = GenerateResearchReportInput

    def execute(self, session: Optional[Any] = None, **kwargs: Any) -> Dict[str, Any]:
        from marketpulse.research.pipeline import ResearchPipeline
        if session is not None:
            pipeline = ResearchPipeline(session=session)
            report = pipeline.run(
                prompt=kwargs["prompt"],
                company_symbol=kwargs.get("company_symbol"),
            )
            return {
                "report_id": report.report_id,
                "company_symbol": report.company_symbol,
                "title": report.title,
                "artifact_location": report.artifact_location,
                "status": "SUCCESS",
            }
        with get_session() as sess:
            pipeline = ResearchPipeline(session=sess)
            report = pipeline.run(
                prompt=kwargs["prompt"],
                company_symbol=kwargs.get("company_symbol"),
            )
            sess.commit()
            return {
                "report_id": report.report_id,
                "company_symbol": report.company_symbol,
                "title": report.title,
                "artifact_location": report.artifact_location,
                "status": "SUCCESS",
            }


class GenerateMarketBriefInput(BaseModel):
    session_date: Optional[str] = Field(default=None, description="Session date in YYYY-MM-DD")


class GenerateMarketBriefTool(MarketPulseTool):
    name = "generate_market_brief"
    description = "Generate an Indian market session brief checking IST calendar and verified statistics."
    risk_level = RiskLevel.LOW
    timeout_sec = 15.0
    modifies_state = True
    args_schema = GenerateMarketBriefInput

    def execute(self, session: Optional[Any] = None, **kwargs: Any) -> Dict[str, Any]:
        from datetime import date
        from marketpulse.research.market_brief import MarketBriefGenerator
        target_d = date.fromisoformat(kwargs["session_date"]) if kwargs.get("session_date") else None
        if session is not None:
            generator = MarketBriefGenerator(session=session)
            brief = generator.generate_brief(session_date=target_d)
            return {
                "brief_id": brief.brief_id,
                "session_state": brief.session_state.value,
                "session_date": brief.session_date,
                "artifact_path": brief.artifact_path,
                "status": "SUCCESS",
            }
        with get_session() as sess:
            generator = MarketBriefGenerator(session=sess)
            brief = generator.generate_brief(session_date=target_d)
            return {
                "brief_id": brief.brief_id,
                "session_state": brief.session_state.value,
                "session_date": brief.session_date,
                "artifact_path": brief.artifact_path,
                "status": "SUCCESS",
            }


class EvaluateWatchlistAlertsInput(BaseModel):
    watchlist_name: str = Field(default="NIFTY_CORE", description="Watchlist name to evaluate")


class EvaluateWatchlistAlertsTool(MarketPulseTool):
    name = "evaluate_watchlist_alerts"
    description = "Evaluate recent disclosures against monitored symbols and record alert rationales."
    risk_level = RiskLevel.LOW
    timeout_sec = 15.0
    modifies_state = True
    args_schema = EvaluateWatchlistAlertsInput

    def execute(self, session: Optional[Any] = None, **kwargs: Any) -> Dict[str, Any]:
        from marketpulse.research.watchlist_intelligence import WatchlistIntelligenceManager
        from marketpulse.storage.models import EvidenceRecord
        if session is not None:
            mgr = WatchlistIntelligenceManager(session=session)
            records = session.query(EvidenceRecord).order_by(EvidenceRecord.retrieved_at.desc()).limit(30).all()
            evaluation = mgr.evaluate_evidence_records(records)
            return {
                "evaluated_symbols": evaluation.evaluated_symbol_count,
                "alerts_triggered": evaluation.alerts_triggered_count,
                "status": "SUCCESS",
            }
        with get_session() as sess:
            mgr = WatchlistIntelligenceManager(session=sess)
            records = sess.query(EvidenceRecord).order_by(EvidenceRecord.retrieved_at.desc()).limit(30).all()
            evaluation = mgr.evaluate_evidence_records(records)
            sess.commit()
            return {
                "evaluated_symbols": evaluation.evaluated_symbol_count,
                "alerts_triggered": evaluation.alerts_triggered_count,
                "status": "SUCCESS",
            }


# ---------------------------------------------------------------------------
# Category 2: Browser Automation Tools (LOW / MEDIUM Risk)
# ---------------------------------------------------------------------------
class BrowserOpenUrlInput(BaseModel):
    url: str = Field(..., description="Target webpage URL to visit")


class BrowserOpenUrlTool(MarketPulseTool):
    name = "browser_open_url"
    description = "Open approved web URL in Playwright browser."
    risk_level = RiskLevel.LOW
    timeout_sec = 30.0
    args_schema = BrowserOpenUrlInput

    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        from personal_ai.tools.browser import BrowserOpenUrlTool as BaseBrowserOpen
        base_tool = BaseBrowserOpen()
        return base_tool.execute(url=kwargs["url"])


class BrowserScreenshotInput(BaseModel):
    artifact_name: Optional[str] = Field(default=None, description="Optional filename for the screenshot")


class BrowserScreenshotTool(MarketPulseTool):
    name = "browser_screenshot"
    description = "Capture screenshot of current browser page into approved artifacts directory."
    risk_level = RiskLevel.LOW
    timeout_sec = 15.0
    modifies_state = True
    args_schema = BrowserScreenshotInput

    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        from personal_ai.tools.browser import BrowserScreenshotTool as BaseScreenshot
        base_tool = BaseScreenshot()
        return base_tool.execute(artifact_name=kwargs.get("artifact_name"))


class BrowserInteractInput(BaseModel):
    selector: str = Field(..., description="CSS or text selector on the web page")
    text: Optional[str] = Field(default=None, description="Text to enter if typing")


class BrowserInteractTool(MarketPulseTool):
    name = "browser_interact"
    description = "Click or fill an interactive web form on an approved webpage."
    risk_level = RiskLevel.MEDIUM
    timeout_sec = 20.0
    modifies_state = True
    args_schema = BrowserInteractInput

    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        from personal_ai.tools.browser import BrowserClickTool, BrowserFillTool
        if kwargs.get("text"):
            fill_tool = BrowserFillTool()
            return fill_tool.execute(selector=kwargs["selector"], text=kwargs["text"])
        click_tool = BrowserClickTool()
        return click_tool.execute(selector=kwargs["selector"])


# ---------------------------------------------------------------------------
# Category 3: Desktop & Filesystem Automation Tools (LOW, MEDIUM, HIGH Risk)
# ---------------------------------------------------------------------------
class ReadResearchFileInput(BaseModel):
    file_path: str = Field(..., description="Path to research document inside project workspace")


class ReadResearchFileTool(MarketPulseTool):
    name = "read_research_file"
    description = "Read a research markdown, JSON, or text file inside approved workspace."
    risk_level = RiskLevel.LOW
    timeout_sec = 10.0
    args_schema = ReadResearchFileInput

    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        path = Path(kwargs["file_path"]).resolve()
        # Security containment check
        root = mp_settings.project_root.resolve()
        if not str(path).startswith(str(root)):
            raise PermissionError(f"Access denied: Path '{path}' is outside project root.")
        if not path.exists():
            raise FileNotFoundError(f"File '{path}' does not exist.")
        content = path.read_text(encoding="utf-8")
        return {"file_path": str(path), "size_bytes": len(content), "content": content[:2000]}


class ModifyResearchFileInput(BaseModel):
    file_path: str = Field(..., description="Path to existing research file to update")
    append_content: str = Field(..., description="Content to append to file")


class ModifyResearchFileTool(MarketPulseTool):
    name = "modify_research_file"
    description = "Append notes or updates to an existing research file inside approved directory."
    risk_level = RiskLevel.MEDIUM
    timeout_sec = 10.0
    modifies_state = True
    args_schema = ModifyResearchFileInput

    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        path = Path(kwargs["file_path"]).resolve()
        root = mp_settings.project_root.resolve()
        if not str(path).startswith(str(root)):
            raise PermissionError(f"Access denied: Path '{path}' is outside project root.")
        if not path.exists():
            raise FileNotFoundError(f"Target file '{path}' does not exist.")
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n{kwargs['append_content']}\n")
        return {"file_path": str(path), "status": "MODIFIED"}


class DeleteDataFileInput(BaseModel):
    file_path: str = Field(..., description="Path to data or cache file to delete")


class DeleteDataFileTool(MarketPulseTool):
    name = "delete_data_file"
    description = "Delete a persistent data or research file inside artifacts or data directory (High Risk)."
    risk_level = RiskLevel.HIGH
    timeout_sec = 10.0
    modifies_state = True
    args_schema = DeleteDataFileInput

    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        path = Path(kwargs["file_path"]).resolve()
        allowed_dirs = [mp_settings.artifacts_dir.resolve(), (mp_settings.project_root / "data").resolve()]
        if not any(str(path).startswith(str(d)) for d in allowed_dirs):
            raise PermissionError(f"High-risk deletion denied: '{path}' is outside data/artifacts directories.")
        if path.exists():
            path.unlink()
            return {"file_path": str(path), "status": "DELETED"}
        return {"file_path": str(path), "status": "FILE_NOT_FOUND"}


class PublishExternalReportInput(BaseModel):
    report_id: str = Field(..., description="ID of research report to publish")
    destination_channel: str = Field(..., description="External publishing channel or webhook")


class PublishExternalReportTool(MarketPulseTool):
    name = "publish_external_report"
    description = "Publish an internal research report to an external channel or distribution list (High Risk)."
    risk_level = RiskLevel.HIGH
    timeout_sec = 30.0
    modifies_state = True
    args_schema = PublishExternalReportInput

    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        # High risk action requiring human approval
        return {
            "report_id": kwargs["report_id"],
            "destination": kwargs["destination_channel"],
            "status": "PUBLISHED_EXTERNALLY",
        }


# ---------------------------------------------------------------------------
# Permanently Disabled Action (Simulation of Prohibited Action Rejection)
# ---------------------------------------------------------------------------
class FinancialOrderPlacementTool(MarketPulseTool):
    name = "place_order"
    description = "Brokerage order placement (PERMANENTLY DISABLED)."
    risk_level = RiskLevel.HIGH
    timeout_sec = 1.0

    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        raise ProhibitedActionError(
            "Financial order placement, trading, and fund transfers are permanently disabled."
        )


class DesktopScreenshotInput(BaseModel):
    artifact_name: Optional[str] = Field(default=None, description="Optional filename for desktop screenshot")


class DesktopScreenshotTool(MarketPulseTool):
    name = "desktop_screenshot"
    description = "Capture screenshot of primary Windows desktop monitor into artifacts directory."
    risk_level = RiskLevel.LOW
    timeout_sec = 15.0
    modifies_state = True
    supported_modes = ["desktop"]
    args_schema = DesktopScreenshotInput

    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        from personal_ai.tools.desktop import capture_desktop_screenshot
        res = capture_desktop_screenshot(file_name=kwargs.get("artifact_name"))
        artifact_path = res.get("file_path") if isinstance(res, dict) else str(res)
        return {
            "artifact_path": artifact_path,
            "status": "SUCCESS",
        }


class DesktopActiveWindowTool(MarketPulseTool):
    name = "desktop_active_window"
    description = "Inspect the title, geometry, and process of the currently active Windows window."
    risk_level = RiskLevel.LOW
    timeout_sec = 5.0
    supported_modes = ["desktop"]

    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        from personal_ai.tools.desktop import get_active_window_info
        info = get_active_window_info()
        return {
            "window_info": info,
            "status": "SUCCESS",
        }


# ---------------------------------------------------------------------------
# Central Tool Registry
# ---------------------------------------------------------------------------
class MarketPulseToolRegistry:
    """Registry maintaining all available MarketPulse automation tools."""

    def __init__(self):
        self._tools: Dict[str, MarketPulseTool] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        defaults = [
            CollectSourceEvidenceTool(),
            GenerateResearchReportTool(),
            GenerateMarketBriefTool(),
            EvaluateWatchlistAlertsTool(),
            BrowserOpenUrlTool(),
            BrowserScreenshotTool(),
            BrowserInteractTool(),
            DesktopScreenshotTool(),
            DesktopActiveWindowTool(),
            ReadResearchFileTool(),
            ModifyResearchFileTool(),
            DeleteDataFileTool(),
            PublishExternalReportTool(),
            FinancialOrderPlacementTool(),
        ]
        for t in defaults:
            self.register(t)

    def register(self, tool: MarketPulseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[MarketPulseTool]:
        return self._tools.get(name)

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "risk_level": t.risk_level.value,
                "timeout_sec": t.timeout_sec,
                "modifies_state": t.modifies_state,
                "input_schema": t.args_schema.model_json_schema() if t.args_schema else None,
            }
            for t in self._tools.values()
        ]
