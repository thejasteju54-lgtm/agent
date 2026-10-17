"""Verification engine for validating action outcomes."""

from pathlib import Path
from typing import Any, Dict, Optional
from personal_ai.logging.setup import get_logger

logger = get_logger(__name__)


class VerificationResult:
    """Outcome of an action verification check."""

    def __init__(self, passed: bool, message: str, details: Optional[Dict[str, Any]] = None):
        self.passed = passed
        self.message = message
        self.details = details or {}

    def __bool__(self) -> bool:
        return self.passed


class StepVerifier:
    """Validates actual target state after an automation action."""

    @staticmethod
    def verify_file_exists(path: Path | str, min_bytes: int = 1) -> VerificationResult:
        """Verify that a target file was actually created and is non-empty."""
        target = Path(path)
        if not target.exists():
            return VerificationResult(False, f"Target file does not exist: {target}")
        if not target.is_file():
            return VerificationResult(False, f"Target path is not a file: {target}")
        size = target.stat().st_size
        if size < min_bytes:
            return VerificationResult(False, f"Target file is smaller than expected ({size} < {min_bytes} bytes)")
        return VerificationResult(True, f"File verified: {target} ({size} bytes)", {"size_bytes": size})

    @staticmethod
    def verify_content_matches(output: Any, expected_keyword: str) -> VerificationResult:
        """Verify that the tool output contains the expected keywords or structure."""
        text = str(output) if output is not None else ""
        if expected_keyword.lower() in text.lower():
            return VerificationResult(True, f"Output contains keyword '{expected_keyword}'")
        return VerificationResult(False, f"Output did not contain expected keyword: '{expected_keyword}'")

    @staticmethod
    def verify_step(tool_name: str, params: Dict[str, Any], output: Any) -> VerificationResult:
        """Perform tool-appropriate verification."""
        if tool_name in ("write_file", "save_artifact"):
            file_path = params.get("path") or params.get("file_path")
            if file_path:
                return StepVerifier.verify_file_exists(file_path)

        if tool_name == "browser_open_url":
            if isinstance(output, dict):
                status_code = output.get("status_code", 0)
                if 200 <= status_code < 400:
                    return VerificationResult(True, f"Navigation succeeded with HTTP {status_code} ({output.get('title')})")
                return VerificationResult(False, f"Navigation returned error status code: {status_code}")

        if tool_name == "browser_screenshot":
            if isinstance(output, dict) and output.get("file_path"):
                return StepVerifier.verify_file_exists(output["file_path"], min_bytes=100)

        if tool_name == "browser_extract_content":
            if isinstance(output, dict) and output.get("text"):
                return VerificationResult(True, f"Extracted {output.get('total_chars', 0)} characters of content")
            return VerificationResult(False, "No content extracted from page")

        if tool_name == "desktop_screenshot":
            if isinstance(output, dict) and output.get("file_path"):
                return StepVerifier.verify_file_exists(output["file_path"], min_bytes=100)
            return VerificationResult(False, "Desktop screenshot did not produce a valid image file")

        if tool_name == "desktop_get_screen_info":
            if isinstance(output, dict) and output.get("screen_width", 0) > 0:
                return VerificationResult(
                    True,
                    f"Screen resolution verified: {output['screen_width']}x{output['screen_height']}",
                    {"resolution": f"{output['screen_width']}x{output['screen_height']}"},
                )
            return VerificationResult(False, "Failed to retrieve valid screen resolution")

        if tool_name == "desktop_focus_window":
            if isinstance(output, dict) and output.get("title"):
                return VerificationResult(True, f"Focused window: '{output['title']}'")
            return VerificationResult(False, "Focus window did not return active window details")

        if tool_name in ("desktop_click", "desktop_move_mouse"):
            if isinstance(output, dict) and "x" in output and "y" in output:
                return VerificationResult(True, f"Mouse action verified at ({output['x']}, {output['y']})")
            return VerificationResult(False, "Mouse action did not return coordinates")

        if tool_name == "desktop_type_text":
            if isinstance(output, dict) and "typed_chars" in output:
                return VerificationResult(True, f"Typed {output['typed_chars']} characters successfully")
            return VerificationResult(False, "Text typing produced invalid result")

        if tool_name == "desktop_press_hotkey":
            if isinstance(output, dict) and output.get("hotkey"):
                return VerificationResult(True, f"Hotkey '{output['hotkey']}' executed successfully")
            return VerificationResult(False, "Hotkey action failed")

        if output is None:
            return VerificationResult(False, "Tool produced no output")

        return VerificationResult(True, "Step completed and produced valid output")
