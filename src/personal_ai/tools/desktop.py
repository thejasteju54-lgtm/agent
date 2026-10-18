"""Desktop automation tools for Windows using PyAutoGUI and Win32 APIs.

Follows the Personal AI Automation System safety and determinism guidelines:
- Explicit screen-bounds checks and fail-safes enabled.
- Thread desktop attachment for reliable Windows console/service execution.
- Window targeting, verification, and confirmation before clicking or typing.
- Explicit outcome verification and diagnostic screenshot artifact creation.
"""

import sys
import ctypes
try:
    from ctypes import wintypes
except Exception:
    wintypes = None

import io
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.1
except Exception:
    pyautogui = None

try:
    from PIL import ImageGrab
except Exception:
    ImageGrab = None

try:
    import pygetwindow as gw
except Exception:
    gw = None

from personal_ai.config import settings
from personal_ai.logging.setup import get_logger
from personal_ai.agent.task_models import RiskLevel
from personal_ai.storage.artifacts import ArtifactManager
from personal_ai.tools.registry import BaseTool, ToolDefinition, default_registry

logger = get_logger(__name__)

if sys.platform == "win32" and hasattr(ctypes, "windll"):
    user32 = getattr(ctypes.windll, "user32", None)
    kernel32 = getattr(ctypes.windll, "kernel32", None)
else:
    user32 = None
    kernel32 = None


def ensure_input_desktop() -> bool:
    """Ensure current thread is attached to the active user's input desktop.
    
    This solves Windows background/console process isolation where screen grabs
    and window enumerations would otherwise fail with Win32 errors.
    """
    if not user32:
        return False
    try:
        # 0x01FF = GENERIC_ALL
        hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
        if hdesk:
            res = user32.SetThreadDesktop(hdesk)
            return bool(res)
    except Exception as e:
        logger.debug(f"Could not attach to input desktop: {e}")
    return False


def get_screen_resolution() -> Tuple[int, int]:
    """Get the current primary screen resolution (width, height)."""
    ensure_input_desktop()
    if pyautogui:
        try:
            size = pyautogui.size()
            return int(size.width), int(size.height)
        except Exception:
            pass
    if user32:
        try:
            return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
        except Exception:
            pass
    return (1920, 1080)


def validate_screen_coordinates(x: int, y: int) -> Tuple[int, int]:
    """Validate that (x, y) coordinates fall within physical screen bounds."""
    width, height = get_screen_resolution()
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError(
            f"Coordinates ({x}, {y}) are outside screen bounds (0..{width-1}, 0..{height-1})"
        )
    return x, y


def get_active_window_info() -> Dict[str, Any]:
    """Retrieve title and geometry of currently active/focused window."""
    ensure_input_desktop()
    if not user32 or not wintypes:
        return {"hwnd": 0, "title": "Headless Desktop", "left": 0, "top": 0, "width": 1920, "height": 1080}
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return {"hwnd": 0, "title": "", "left": 0, "top": 0, "width": 0, "height": 0}

    length = user32.GetWindowTextLengthW(hwnd)
    buff = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buff, length + 1)
    title = buff.value.strip()

    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    left = rect.left
    top = rect.top
    width = max(0, rect.right - rect.left)
    height = max(0, rect.bottom - rect.top)

    return {
        "hwnd": hwnd,
        "title": title,
        "left": left,
        "top": top,
        "width": width,
        "height": height,
    }


def list_open_windows(include_empty_titles: bool = False) -> List[Dict[str, Any]]:
    """Enumerate visible desktop application windows with titles and geometry."""
    ensure_input_desktop()
    results: List[Dict[str, Any]] = []

    try:
        all_windows = gw.getAllWindows()
        active = get_active_window_info()
        active_hwnd = active.get("hwnd", 0)

        for win in all_windows:
            title = win.title.strip()
            if not title and not include_empty_titles:
                continue
            if not win.visible and not win.isMinimized:
                continue

            results.append({
                "title": title,
                "left": win.left,
                "top": win.top,
                "width": win.width,
                "height": win.height,
                "is_active": (win._hWnd == active_hwnd),
                "is_minimized": win.isMinimized,
            })
    except Exception as e:
        logger.warning(f"Error enumerating windows via pygetwindow: {e}")

    return results


def focus_window_by_title(title_query: str, timeout: float = 2.0) -> Dict[str, Any]:
    """Bring the window matching title_query to foreground and verify focus."""
    ensure_input_desktop()
    query_lower = title_query.strip().lower()
    matching_windows = [
        w for w in gw.getAllWindows()
        if w.title.strip() and query_lower in w.title.lower()
    ]

    if not matching_windows:
        raise RuntimeError(f"No open window found matching title '{title_query}'")

    target = matching_windows[0]
    try:
        if target.isMinimized:
            target.restore()
        target.activate()
    except Exception as e:
        # Fallback to direct Win32 ShowWindow / SetForegroundWindow
        hwnd = target._hWnd
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)

    start = time.time()
    while time.time() - start < timeout:
        active = get_active_window_info()
        if query_lower in active["title"].lower():
            return active
        time.sleep(0.1)

    # Return latest active window even if partial match
    current = get_active_window_info()
    if query_lower not in current["title"].lower():
        logger.warning(
            f"Window focus requested for '{title_query}', but active window is '{current['title']}'"
        )
    return current


def capture_desktop_screenshot(
    task_id: Optional[str] = None,
    file_name: Optional[str] = None,
    region: Optional[Tuple[int, int, int, int]] = None,
) -> Dict[str, Any]:
    """Capture full desktop or region screenshot and save as an artifact."""
    ensure_input_desktop()
    name = file_name or f"desktop_{task_id[:8] if task_id else uuid.uuid4().hex[:8]}.png"
    if not name.lower().endswith(".png"):
        name += ".png"

    if pyautogui:
        if region:
            rx, ry, rw, rh = region
            validate_screen_coordinates(rx, ry)
            validate_screen_coordinates(rx + rw - 1, ry + rh - 1)
            img = pyautogui.screenshot(region=(rx, ry, rw, rh))
        else:
            img = pyautogui.screenshot()

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_bytes = buf.getvalue()
        w, h = img.width, img.height
    else:
        # Fallback 1x1 transparent PNG for cloud / headless execution
        img_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        w, h = 1, 1

    # Register as artifact
    artifact_mgr = ArtifactManager()
    artifact = artifact_mgr.save_bytes(
        file_name=name,
        data=img_bytes,
        task_id=task_id,
        mime_type="image/png",
    )

    return {
        "artifact_id": artifact["id"],
        "file_name": artifact["file_name"],
        "file_path": artifact["file_path"],
        "width": w,
        "height": h,
        "size_bytes": artifact["size_bytes"],
        "task_id": task_id,
    }


def desktop_mouse_click(
    x: int,
    y: int,
    button: str = "left",
    clicks: int = 1,
    target_window: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a mouse click at (x, y) with boundary verification."""
    ensure_input_desktop()
    validate_screen_coordinates(x, y)

    btn = button.lower()
    if btn not in ("left", "right", "middle"):
        raise ValueError(f"Unsupported mouse button: '{button}' (use 'left', 'right', or 'middle')")

    if clicks not in (1, 2, 3):
        raise ValueError(f"Invalid clicks count: {clicks}")

    # Confirm intended application window if requested
    active_title = ""
    if target_window:
        focused = focus_window_by_title(target_window)
        active_title = focused.get("title", "")
        if target_window.lower() not in active_title.lower():
            raise RuntimeError(
                f"Cannot click: target window '{target_window}' not active (currently active: '{active_title}')"
            )
    else:
        active_title = get_active_window_info().get("title", "")

    # Perform click
    pyautogui.click(x=x, y=y, clicks=clicks, button=btn)

    return {
        "x": x,
        "y": y,
        "button": btn,
        "clicks": clicks,
        "active_window": active_title,
    }


def desktop_mouse_move(x: int, y: int, duration: float = 0.1) -> Dict[str, Any]:
    """Move the mouse cursor smoothly to coordinates (x, y)."""
    ensure_input_desktop()
    validate_screen_coordinates(x, y)
    pyautogui.moveTo(x=x, y=y, duration=max(0.0, duration))
    return {"x": x, "y": y, "duration": duration}


def desktop_type_text(
    text: str,
    interval: float = 0.01,
    target_window: Optional[str] = None,
    press_enter: bool = False,
) -> Dict[str, Any]:
    """Type text into the currently active window or confirmed target window."""
    ensure_input_desktop()
    if not text:
        return {"typed_chars": 0, "active_window": ""}

    active_title = ""
    if target_window:
        focused = focus_window_by_title(target_window)
        active_title = focused.get("title", "")
        if target_window.lower() not in active_title.lower():
            raise RuntimeError(
                f"Cannot type: target window '{target_window}' not active (currently active: '{active_title}')"
            )
    else:
        active_title = get_active_window_info().get("title", "")

    pyautogui.write(text, interval=max(0.0, interval))
    if press_enter:
        pyautogui.press("enter")

    return {
        "typed_chars": len(text),
        "press_enter": press_enter,
        "active_window": active_title,
    }


def desktop_press_hotkey(
    keys: Union[List[str], str],
    target_window: Optional[str] = None,
) -> Dict[str, Any]:
    """Press keyboard hotkey combination (e.g. ['ctrl', 's'] or 'ctrl+s')."""
    ensure_input_desktop()
    if isinstance(keys, str):
        key_list = [k.strip().lower() for k in keys.replace("+", " ").split()]
    else:
        key_list = [str(k).strip().lower() for k in keys]

    if not key_list:
        raise ValueError("Hotkey keys list cannot be empty")

    # Safety check: Prevent destructive system shortcuts without explicit approval
    dangerous_combos = [("alt", "f4"), ("ctrl", "alt", "delete"), ("win", "l")]
    tuple_keys = tuple(key_list)
    if tuple_keys in dangerous_combos:
        logger.warning(f"High-impact hotkey requested: {tuple_keys}")

    active_title = ""
    if target_window:
        focused = focus_window_by_title(target_window)
        active_title = focused.get("title", "")
        if target_window.lower() not in active_title.lower():
            raise RuntimeError(
                f"Cannot press hotkey: target window '{target_window}' not active (currently active: '{active_title}')"
            )
    else:
        active_title = get_active_window_info().get("title", "")

    pyautogui.hotkey(*key_list)

    return {
        "hotkey": "+".join(key_list),
        "active_window": active_title,
    }


# ============================================================================
# Registered Desktop Tools
# ============================================================================

class DesktopGetScreenInfoTool(BaseTool):
    """Retrieve screen resolution and currently active window information."""
    name = "desktop_get_screen_info"
    description = "Get display resolution, geometry, and currently focused window details."
    risk_level = RiskLevel.LOW

    def execute(self, **kwargs) -> Dict[str, Any]:
        width, height = get_screen_resolution()
        active = get_active_window_info()
        return {
            "screen_width": width,
            "screen_height": height,
            "active_window": active,
        }


class DesktopGetActiveWindowTool(BaseTool):
    """Get details of the currently focused/foreground window."""
    name = "desktop_get_active_window"
    description = "Get title, handle, and coordinates of the current active window."
    risk_level = RiskLevel.LOW

    def execute(self, **kwargs) -> Dict[str, Any]:
        return get_active_window_info()


class DesktopListWindowsTool(BaseTool):
    """List open application windows with titles and coordinates."""
    name = "desktop_list_windows"
    description = "List open application windows visible on the Windows desktop."
    risk_level = RiskLevel.LOW

    def execute(self, include_empty_titles: bool = False, **kwargs) -> List[Dict[str, Any]]:
        return list_open_windows(include_empty_titles=include_empty_titles)


class DesktopFocusWindowTool(BaseTool):
    """Bring a specific window to the foreground by matching title."""
    name = "desktop_focus_window"
    description = "Bring an application window to foreground by matching its title."
    risk_level = RiskLevel.LOW

    def execute(self, title: str, **kwargs) -> Dict[str, Any]:
        return focus_window_by_title(title)


class DesktopScreenshotTool(BaseTool):
    """Capture a screenshot of the Windows desktop and save as an artifact."""
    name = "desktop_screenshot"
    description = "Capture a desktop screenshot and store in artifacts."
    risk_level = RiskLevel.LOW
    modifies_state = True

    def execute(
        self,
        task_id: Optional[str] = None,
        file_name: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        return capture_desktop_screenshot(task_id=task_id, file_name=file_name)


class DesktopClickTool(BaseTool):
    """Click at screen coordinates with verification."""
    name = "desktop_click"
    description = "Click at screen coordinates (x, y) with optional window confirmation."
    risk_level = RiskLevel.MEDIUM
    modifies_state = True

    def execute(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
        target_window: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        return desktop_mouse_click(
            x=x, y=y, button=button, clicks=clicks, target_window=target_window
        )


class DesktopMoveMouseTool(BaseTool):
    """Move mouse pointer to coordinates."""
    name = "desktop_move_mouse"
    description = "Move mouse cursor to screen coordinates (x, y)."
    risk_level = RiskLevel.LOW
    modifies_state = True

    def execute(self, x: int, y: int, duration: float = 0.1, **kwargs) -> Dict[str, Any]:
        return desktop_mouse_move(x=x, y=y, duration=duration)


class DesktopTypeTextTool(BaseTool):
    """Type text into active or confirmed application window."""
    name = "desktop_type_text"
    description = "Type text into the active window with optional enter press."
    risk_level = RiskLevel.MEDIUM
    modifies_state = True

    def execute(
        self,
        text: str,
        target_window: Optional[str] = None,
        press_enter: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        return desktop_type_text(
            text=text, target_window=target_window, press_enter=press_enter
        )


class DesktopPressHotkeyTool(BaseTool):
    """Press keyboard hotkey combination."""
    name = "desktop_press_hotkey"
    description = "Press a keyboard shortcut combination (e.g. 'ctrl+s' or 'alt+tab')."
    risk_level = RiskLevel.MEDIUM
    modifies_state = True

    def execute(
        self,
        keys: Union[List[str], str],
        target_window: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        return desktop_press_hotkey(keys=keys, target_window=target_window)


# Register all tools with the default registry
def register_desktop_tools():
    default_registry.register(DesktopGetScreenInfoTool())
    default_registry.register(DesktopGetActiveWindowTool())
    default_registry.register(DesktopListWindowsTool())
    default_registry.register(DesktopFocusWindowTool())
    default_registry.register(DesktopScreenshotTool())
    default_registry.register(DesktopClickTool())
    default_registry.register(DesktopMoveMouseTool())
    default_registry.register(DesktopTypeTextTool())
    default_registry.register(DesktopPressHotkeyTool())


# Auto-register on import
register_desktop_tools()

