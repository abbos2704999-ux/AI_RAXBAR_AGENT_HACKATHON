"""Tests for the typed read-only tools and the single controlled write tool."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ai_raxbar_agent import tools
from ai_raxbar_agent.data_store import AssetNotFoundError, store
from ai_raxbar_agent.models import ApprovalState, ApprovalStatus, RiskLevel

_DISALLOWED_NETWORK_MODULES = {
    "socket",
    "requests",
    "urllib.request",
    "http.client",
    "httpx",
    "aiohttp",
}


@pytest.fixture(autouse=True)
def _reset_demo_state():
    store.reset()
    yield
    store.reset()


def test_get_asset_context_returns_asset_and_risk():
    ctx = tools.get_asset_context("DEMO-TP-007")
    assert ctx["asset"].asset_id == "DEMO-TP-007"
    assert ctx["risk_assessment"].risk_level == RiskLevel.CRITICAL


def test_get_risk_evidence():
    risk = tools.get_risk_evidence("DEMO-TP-007")
    assert risk.risk_level == RiskLevel.CRITICAL
    assert risk.evidence_refs


def test_get_recent_events():
    events = tools.get_recent_events("DEMO-TP-007")
    assert len(events) > 0
    assert all(e.asset_id == "DEMO-TP-007" for e in events)


def test_get_remediation_candidates_targets_active_factors():
    candidates = tools.get_remediation_candidates("DEMO-TP-007")
    assert candidates
    action_types = {c.action_type for c in candidates}
    assert "REBALANCE_LOAD" in action_types  # overload is active on DEMO-TP-007


def test_get_remediation_candidates_empty_for_normal_asset():
    candidates = tools.get_remediation_candidates("DEMO-TP-001")
    assert candidates == []


@pytest.mark.parametrize(
    "read_fn",
    [
        tools.get_asset_context,
        tools.get_risk_evidence,
        tools.get_recent_events,
        tools.get_remediation_candidates,
    ],
)
def test_unknown_asset_fails_safely_for_read_tools(read_fn):
    with pytest.raises(AssetNotFoundError):
        read_fn("DEMO-TP-999-DOES-NOT-EXIST")


def test_simulate_remediation_unknown_asset_returns_error_result():
    result = tools.simulate_remediation("DEMO-TP-999-DOES-NOT-EXIST", "RECLOSE_BREAKER")
    assert result.success is False
    assert result.error


def test_simulate_remediation_unknown_action_returns_error_result():
    result = tools.simulate_remediation("DEMO-TP-007", "NOT_A_REAL_ACTION")
    assert result.success is False
    assert result.error


def test_simulate_remediation_cannot_bypass_policy_without_approval():
    before = store.get_asset("DEMO-TP-007").signal_snapshot()

    result = tools.simulate_remediation("DEMO-TP-007", "REBALANCE_LOAD")  # HIGH_IMPACT, no approval

    assert result.success is False
    assert result.error == "HUMAN_APPROVAL_REQUIRED"
    after = store.get_asset("DEMO-TP-007").signal_snapshot()
    assert before == after  # no state mutation happened


def test_simulate_remediation_rejected_approval_still_blocks():
    rejected = ApprovalState(status=ApprovalStatus.REJECTED, approver="demo-operator")
    result = tools.simulate_remediation("DEMO-TP-007", "REBALANCE_LOAD", approval=rejected)
    assert result.success is False
    assert result.error == "HUMAN_APPROVAL_REQUIRED"


def test_simulate_remediation_low_impact_action_needs_no_approval():
    result = tools.simulate_remediation("DEMO-TP-003", "DISPATCH_SYNTHETIC_INSPECTION")
    assert result.success is True
    assert result.verification is not None


def test_approved_high_impact_action_works_and_verification_recomputes_risk():
    risk_before_call = tools.get_risk_evidence("DEMO-TP-007")

    approval = ApprovalState(status=ApprovalStatus.APPROVED, approver="demo-operator")
    result = tools.simulate_remediation("DEMO-TP-007", "REBALANCE_LOAD", approval=approval)

    assert result.success is True
    verification = result.verification
    assert verification is not None

    # before/after state preserved and distinct
    assert verification.before_state != verification.after_state
    assert verification.before_state["load_ratio"] == 1.30
    assert verification.after_state["load_ratio"] == 0.8

    # risk was recomputed deterministically, not just copied
    assert verification.risk_before.risk_score == risk_before_call.risk_score
    assert verification.risk_after.risk_score < verification.risk_before.risk_score
    assert verification.verification_result == "IMPROVED"
    assert verification.passed is True

    # confirm against a fresh read after mutation
    risk_after_call = tools.get_risk_evidence("DEMO-TP-007")
    assert risk_after_call.risk_score == verification.risk_after.risk_score


def test_no_network_dependency_in_source_package():
    src_dir = Path(__file__).resolve().parents[1] / "src" / "ai_raxbar_agent"
    for py_file in src_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in _DISALLOWED_NETWORK_MODULES, (
                        f"{py_file.name} imports network module {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                assert node.module not in _DISALLOWED_NETWORK_MODULES, (
                    f"{py_file.name} imports network module {node.module}"
                )
