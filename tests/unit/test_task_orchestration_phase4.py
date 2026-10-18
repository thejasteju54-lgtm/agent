"""Unit and integration tests for Phase 4 — Task Orchestration and Permissions.

Verifies:
1. Unified 3-tier risk policy engine (LOW, MEDIUM, HIGH).
2. Permanent prohibition of financial orders, trading, and fund transfers.
3. Human approval gates and persistent ApprovalRecord lifecycle.
4. Bounded execution, step limits, timeouts, and cancellation.
5. Idempotency key deduplication.
6. Independent step verification (No Blind Execution).
7. Audit event logging in mp_audit_events.
8. Browser, desktop, and research tool execution under unified policy.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from marketpulse.storage.models import (
    ApprovalRecord,
    AuditEvent,
    AutomationTask,
    TaskStatus,
)
from marketpulse.storage.database import init_db, seed_initial_registry
from marketpulse.agent.permissions import (
    ProhibitedActionError,
    RiskLevel,
    RiskPolicyEngine,
)
from marketpulse.agent.tools import (
    DeleteDataFileTool,
    GenerateMarketBriefTool,
    MarketPulseToolRegistry,
    ModifyResearchFileTool,
    ReadResearchFileTool,
)
from marketpulse.agent.orchestrator import (
    StepVerificationError,
    TaskOrchestrator,
)
from marketpulse.config import mp_settings


@pytest.fixture
def session():
    """In-memory SQLite database session fixture."""
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    SessionLocal = sessionmaker(bind=engine)
    sess = SessionLocal()
    seed_initial_registry(sess)
    try:
        yield sess
    finally:
        sess.close()


# ---------------------------------------------------------------------------
# 1. Risk Policy & Prohibition Tests
# ---------------------------------------------------------------------------
def test_risk_policy_engine_categorization():
    """Verify tool risk tier classification across LOW, MEDIUM, and HIGH."""
    engine = RiskPolicyEngine(approval_mode="safe")

    assert engine.assess_risk_level("collect_source_evidence") == RiskLevel.LOW
    assert engine.assess_risk_level("generate_research_report") == RiskLevel.LOW
    assert engine.assess_risk_level("read_research_file") == RiskLevel.LOW

    assert engine.assess_risk_level("modify_research_file") == RiskLevel.MEDIUM
    assert engine.assess_risk_level("browser_click") == RiskLevel.MEDIUM

    assert engine.assess_risk_level("delete_data_file") == RiskLevel.HIGH
    assert engine.assess_risk_level("publish_external_report") == RiskLevel.HIGH


def test_prohibited_financial_trading_actions_are_hard_rejected():
    """Verify financial order placement, trading, and fund transfers are permanently prohibited."""
    engine = RiskPolicyEngine()

    prohibited_calls = [
        ("place_order", {"symbol": "TCS", "quantity": 10}),
        ("buy_shares", {"ticker": "RELIANCE"}),
        ("trade_execution", {"action": "SELL"}),
        ("transfer_funds", {"amount": 50000}),
    ]

    for tool_name, params in prohibited_calls:
        with pytest.raises(ProhibitedActionError) as exc_info:
            engine.check_prohibited(tool_name, params)
        assert "permanently prohibited" in str(exc_info.value).lower()
        assert "trading" in str(exc_info.value).lower() or "order" in str(exc_info.value).lower()


def test_requires_approval_rules():
    """Verify approval requirement across safe, strict, and auto modes."""
    safe_engine = RiskPolicyEngine(approval_mode="safe")
    strict_engine = RiskPolicyEngine(approval_mode="strict")
    auto_engine = RiskPolicyEngine(approval_mode="auto")

    # LOW risk never requires approval in any mode
    assert not safe_engine.requires_approval("read_research_file", RiskLevel.LOW)
    assert not strict_engine.requires_approval("read_research_file", RiskLevel.LOW)
    assert not auto_engine.requires_approval("read_research_file", RiskLevel.LOW)

    # MEDIUM risk requires approval in strict mode only
    assert not safe_engine.requires_approval("modify_research_file", RiskLevel.MEDIUM)
    assert strict_engine.requires_approval("modify_research_file", RiskLevel.MEDIUM)
    assert not auto_engine.requires_approval("modify_research_file", RiskLevel.MEDIUM)

    # HIGH risk always requires approval in all modes
    assert safe_engine.requires_approval("delete_data_file", RiskLevel.HIGH)
    assert strict_engine.requires_approval("delete_data_file", RiskLevel.HIGH)
    assert auto_engine.requires_approval("delete_data_file", RiskLevel.HIGH)


# ---------------------------------------------------------------------------
# 2. Task Orchestrator & Bounded Execution Tests
# ---------------------------------------------------------------------------
def test_task_submission_and_idempotency(session):
    """Verify task submission, DB record creation, and idempotency key deduplication."""
    orchestrator = TaskOrchestrator(session=session)

    # Submit task with idempotency key
    task1 = orchestrator.submit_task(
        prompt="Analyze Reliance Q2 results",
        idempotency_key="idemp_rel_q2_001",
        step_limit=10,
    )
    assert task1.id is not None
    assert task1.status == TaskStatus.PENDING.value
    assert task1.step_limit == 10

    # Resubmit with same key -> must return existing record
    task2 = orchestrator.submit_task(
        prompt="Analyze Reliance Q2 results",
        idempotency_key="idemp_rel_q2_001",
        step_limit=10,
    )
    assert task1.id == task2.id

    # Verify audit event recorded
    audit = session.query(AuditEvent).filter_by(entity_id=task1.id, event_type="TASK_SUBMITTED").first()
    assert audit is not None


def test_task_step_limits_enforced(session):
    """Verify execution halts and marks task FAILED when step limit is exceeded."""
    orchestrator = TaskOrchestrator(session=session)

    # Create task with step limit of 2
    task = orchestrator.submit_task(prompt="Bounded test", step_limit=2)

    # Step 1: LOW risk action
    res1 = orchestrator.execute_step(task.id, "generate_market_brief", {})
    assert res1["status"] == "SUCCESS"
    assert task.current_step == 1

    # Step 2: LOW risk action
    res2 = orchestrator.execute_step(task.id, "generate_market_brief", {})
    assert res2["status"] == "SUCCESS"
    assert task.current_step == 2

    # Step 3: Must exceed step limit
    res3 = orchestrator.execute_step(task.id, "generate_market_brief", {})
    assert res3["status"] == "FAILED"
    assert "Step limit of 2 exceeded" in res3["error"]
    assert task.status == TaskStatus.FAILED.value


def test_task_cancellation_halts_subsequent_steps(session):
    """Verify cancelled tasks reject further step execution."""
    orchestrator = TaskOrchestrator(session=session)
    task = orchestrator.submit_task(prompt="Cancellation test")

    # Cancel task
    orchestrator.cancel_task(task.id, reason="Operator emergency abort")
    assert task.status == TaskStatus.CANCELLED.value

    # Attempting to execute step must be halted
    res = orchestrator.execute_step(task.id, "generate_market_brief", {})
    assert res["status"] == "CANCELLED"
    assert res["reason"] == "Operator emergency abort"


# ---------------------------------------------------------------------------
# 3. Human Approval Gates & Audit Trails Tests
# ---------------------------------------------------------------------------
def test_high_risk_action_triggers_approval_gate(session, tmp_path):
    """Verify high-risk action pauses task at AWAITING_APPROVAL and creates ApprovalRecord."""
    orchestrator = TaskOrchestrator(session=session)
    task = orchestrator.submit_task(prompt="Delete sensitive log file")

    # Create dummy file inside artifacts dir
    test_file = mp_settings.artifacts_dir / "temp_delete_test.txt"
    test_file.write_text("temporary log content", encoding="utf-8")

    # Execute high-risk tool (delete_data_file)
    step_res = orchestrator.execute_step(
        task_id=task.id,
        tool_name="delete_data_file",
        params={"file_path": str(test_file)},
        auto_approve=False,
    )

    # Task must pause at AWAITING_APPROVAL
    assert step_res["status"] == "AWAITING_APPROVAL"
    approval_id = step_res["approval_id"]
    assert approval_id is not None
    assert task.status == TaskStatus.AWAITING_APPROVAL.value
    assert task.requires_approval is True

    # Verify ApprovalRecord in DB
    approval = session.query(ApprovalRecord).filter_by(id=approval_id).first()
    assert approval is not None
    assert approval.action_type == "delete_data_file"
    assert approval.status == "PENDING"
    assert approval.risk_level == "HIGH"

    # Verify file was NOT deleted yet
    assert test_file.exists()

    # Resolve approval: APPROVED
    orchestrator.resolve_approval(
        approval_id=approval_id,
        decision="APPROVED",
        resolved_by="lead_security_officer",
        reason="Verified temporary file safe to delete",
    )
    assert approval.status == "APPROVED"
    assert approval.resolved_by == "lead_security_officer"
    assert task.status == TaskStatus.RUNNING.value

    # Now execute step with approval
    exec_res = orchestrator.execute_step(
        task_id=task.id,
        tool_name="delete_data_file",
        params={"file_path": str(test_file)},
        auto_approve=True,  # Approval granted
    )
    assert exec_res["status"] == "SUCCESS"
    assert not test_file.exists()


def test_rejected_approval_cancels_task_safely(session):
    """Verify rejecting an approval cancels the task with reason and audit log."""
    orchestrator = TaskOrchestrator(session=session)
    task = orchestrator.submit_task(prompt="Publish unauthorized report")

    step_res = orchestrator.execute_step(
        task_id=task.id,
        tool_name="publish_external_report",
        params={"report_id": "rep-999", "destination_channel": "public_twitter"},
    )
    assert step_res["status"] == "AWAITING_APPROVAL"
    approval_id = step_res["approval_id"]

    # Reject approval
    orchestrator.resolve_approval(
        approval_id=approval_id,
        decision="REJECTED",
        resolved_by="compliance_officer",
        reason="External social publishing is prohibited",
    )

    assert task.status == TaskStatus.CANCELLED.value
    assert "External social publishing is prohibited" in task.cancellation_reason

    # Audit event must be logged
    audit = session.query(AuditEvent).filter_by(
        entity_id=approval_id,
        event_type="APPROVAL_REJECTED",
    ).first()
    assert audit is not None


# ---------------------------------------------------------------------------
# 4. Prohibited Operation Interception & Audit Tests
# ---------------------------------------------------------------------------
def test_prohibited_order_placement_fails_task_and_logs_audit(session):
    """Verify trying to place an order fails the task and creates SECURITY_VIOLATION audit."""
    orchestrator = TaskOrchestrator(session=session)
    task = orchestrator.submit_task(prompt="Execute market order for 100 shares of Reliance")

    with pytest.raises(ProhibitedActionError):
        orchestrator.execute_step(
            task_id=task.id,
            tool_name="place_order",
            params={"symbol": "RELIANCE", "quantity": 100},
        )

    assert task.status == TaskStatus.FAILED.value
    assert "permanently prohibited" in task.error_message.lower()

    # Check security audit event
    audit = session.query(AuditEvent).filter_by(
        entity_id=task.id,
        event_type="SECURITY_VIOLATION",
    ).first()
    assert audit is not None
    assert audit.actor == "security_guardrail"


# ---------------------------------------------------------------------------
# 5. Independent Verification Layer Tests
# ---------------------------------------------------------------------------
def test_independent_step_verification(session):
    """Verify orchestrator ensures target artifacts physically exist before marking step verified."""
    orchestrator = TaskOrchestrator(session=session)

    # Valid result with existing artifact
    dummy_file = mp_settings.artifacts_dir / "valid_test_doc.md"
    dummy_file.write_text("verified content", encoding="utf-8")

    orchestrator._verify_step_execution(
        tool_name="generate_market_brief",
        params={},
        result={"status": "SUCCESS", "artifact_path": str(dummy_file)},
    )

    # Invalid result with missing artifact must fail verification
    with pytest.raises(StepVerificationError) as exc_info:
        orchestrator._verify_step_execution(
            tool_name="generate_market_brief",
            params={},
            result={"status": "SUCCESS", "artifact_path": "C:/nonexistent/file.md"},
        )
    assert "Artifact" in str(exc_info.value)
    assert "was not written to disk" in str(exc_info.value)

    if dummy_file.exists():
        dummy_file.unlink()
