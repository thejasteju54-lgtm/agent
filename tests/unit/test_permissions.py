"""Unit tests for permission policies and risk evaluation."""

from personal_ai.agent.permissions import PermissionPolicy
from personal_ai.agent.task_models import RiskLevel


def test_permission_policy_safe_mode() -> None:
    policy = PermissionPolicy(mode="safe")
    assert policy.requires_approval(RiskLevel.LOW) is False
    assert policy.requires_approval(RiskLevel.MEDIUM) is False
    assert policy.requires_approval(RiskLevel.HIGH) is True


def test_permission_policy_strict_mode() -> None:
    policy = PermissionPolicy(mode="strict")
    assert policy.requires_approval(RiskLevel.LOW) is False
    assert policy.requires_approval(RiskLevel.MEDIUM) is True
    assert policy.requires_approval(RiskLevel.HIGH) is True


def test_permission_policy_auto_mode() -> None:
    policy = PermissionPolicy(mode="auto")
    assert policy.requires_approval(RiskLevel.LOW) is False
    assert policy.requires_approval(RiskLevel.MEDIUM) is False
    assert policy.requires_approval(RiskLevel.HIGH) is True
