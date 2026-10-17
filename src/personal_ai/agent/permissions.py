"""Permission and risk management policy."""

from typing import Optional
from personal_ai.agent.task_models import RiskLevel
from personal_ai.config import settings
from personal_ai.logging.setup import get_logger

logger = get_logger(__name__)


class PermissionPolicy:
    """Evaluates whether an action requires explicit human approval."""

    def __init__(self, mode: Optional[str] = None):
        self.mode = mode or settings.approval_mode

    def requires_approval(self, risk_level: RiskLevel | str) -> bool:
        """Determine if an action with the specified risk level requires human approval.

        Modes:
        - 'strict': Medium and High risk require approval.
        - 'safe' (default): High risk always requires approval; Medium requires approval if configured.
        - 'auto': Only High risk requires approval.
        """
        level = RiskLevel(risk_level) if isinstance(risk_level, str) else risk_level

        if self.mode == "strict":
            return level in (RiskLevel.MEDIUM, RiskLevel.HIGH)
        elif self.mode == "safe":
            return level == RiskLevel.HIGH
        elif self.mode == "auto":
            return level == RiskLevel.HIGH
        return level == RiskLevel.HIGH
