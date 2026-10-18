"""Permission and Risk-Policy Engine for MarketPulse AI automation.

Enforces:
1. Strict three-tier risk categorization: LOW, MEDIUM, HIGH.
2. Hard permanent prohibition of financial order placement, trading, and fund transfers.
3. Mandatory human approval gates for high-risk external and destructive operations.
4. Defense against prompt injection: external content never overrides system permission policies.
"""

from enum import Enum
import re
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field

from marketpulse.logging.setup import get_logger

logger = get_logger(__name__)


class RiskLevel(str, Enum):
    """Automation risk tier classification."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ProhibitedActionError(PermissionError):
    """Raised when an operation violates absolute system safety boundaries."""
    pass


# Permanently prohibited actions that can never be executed or approved
PROHIBITED_ACTION_KEYWORDS: Set[str] = {
    "place_order",
    "buy_shares",
    "sell_shares",
    "trade_execution",
    "execute_trade",
    "brokerage_order",
    "transfer_funds",
    "wire_transfer",
    "bank_transfer",
    "withdraw_money",
    "order_placement",
}


class RiskPolicyEngine:
    """Evaluates automation action risk tiers and enforces approval requirements."""

    def __init__(self, approval_mode: str = "safe"):
        """Initialize risk policy engine.

        Args:
            approval_mode: 'safe' (default), 'strict', or 'auto'.
        """
        self.approval_mode = approval_mode.lower()

    def check_prohibited(self, tool_name: str, params: Optional[Dict[str, Any]] = None) -> None:
        """Verify action is not among permanently disabled financial trading actions."""
        check_str = f"{tool_name} {str(params or '')}".lower()
        for prohibited in PROHIBITED_ACTION_KEYWORDS:
            if prohibited in check_str:
                logger.critical(
                    "SECURITY ALERT: Prohibited financial action intercepted: '%s' (keyword: '%s')",
                    tool_name,
                    prohibited,
                )
                raise ProhibitedActionError(
                    f"Action '{tool_name}' is permanently prohibited: Financial order placement, trading, "
                    f"transfers, and brokerage-account operations are strictly disabled in MarketPulse AI."
                )

    def assess_risk_level(
        self,
        tool_name: str,
        declared_risk: Optional[RiskLevel] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> RiskLevel:
        """Classify action into LOW, MEDIUM, or HIGH risk tier."""
        # 1. First ensure not prohibited
        self.check_prohibited(tool_name, params)

        # 2. Check for HIGH risk operations
        high_risk_tools = {
            "delete_file",
            "delete_data_file",
            "publish_external_report",
            "send_external_communication",
            "modify_security_settings",
            "delete_watchlist",
        }
        if tool_name in high_risk_tools or declared_risk == RiskLevel.HIGH:
            return RiskLevel.HIGH

        # 3. Check for MEDIUM risk operations
        medium_risk_tools = {
            "modify_file",
            "modify_research_file",
            "browser_click",
            "browser_fill",
            "update_workflow_settings",
            "authenticated_web_access",
            "desktop_interact",
        }
        if tool_name in medium_risk_tools or declared_risk == RiskLevel.MEDIUM:
            return RiskLevel.MEDIUM

        # 4. Defaults to LOW risk for read-only / report generation inside approved directories
        return declared_risk or RiskLevel.LOW

    def requires_approval(
        self,
        tool_name: str,
        risk_level: RiskLevel,
        params: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Determine if an action requires human approval before execution.

        Rules:
        - HIGH: Always requires human approval in all modes.
        - MEDIUM: Requires approval in 'strict' mode; runs with logging in 'safe' mode.
        - LOW: Never requires approval (read public sources, save reports in approved paths).
        """
        self.check_prohibited(tool_name, params)

        if risk_level == RiskLevel.HIGH:
            return True

        if risk_level == RiskLevel.MEDIUM and self.approval_mode == "strict":
            return True

        return False
