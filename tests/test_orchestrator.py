"""End-to-end offline tests for Batch 3:
POLICY GATE -> HUMAN APPROVAL -> ACT (SIMULATED) -> VERIFY -> AUDIT.

Everything here is offline and deterministic. The "Gemini diagnosis/plan"
step reuses the exact same offline path as tests/test_agent.py --
`ScriptedFakeLlm` driving the real `agent.analyze_incident()` -- so the
`IncidentAnalysis` fed into the Batch 3 approval/execution pipeline is
produced through the real Batch 2 structured-output contract, not a
hand-rolled dict, while making zero network calls anywhere in this file.
"""

from __future__ import annotations

import json

import pytest

from ai_raxbar_agent import agent, approval, orchestrator, tools
from ai_raxbar_agent.audit import AuditTrail
from ai_raxbar_agent.data_store import store
from ai_raxbar_agent.models import ApprovalStatus, ImpactClass, RiskLevel
from ai_raxbar_agent.orchestrator import ExecutionBlockedError, IncidentProposal

from fakes import ScriptedFakeLlm


@pytest.fixture(autouse=True)
def _reset_demo_state():
    store.reset()
    yield
    store.reset()


def _happy_path_script(asset_id, recommended_action, cited_evidence_refs):
    return [
        {"call": "get_asset_context", "args": {"asset_id": asset_id}},
        {"call": "get_recent_events", "args": {"asset_id": asset_id, "limit": 10}},
        {"call": "get_risk_evidence", "args": {"asset_id": asset_id}},
        {"call": "get_remediation_candidates", "args": {"asset_id": asset_id}},
        {
            "call": "propose_incident_analysis",
            "args": {
                "diagnosis": (
                    "Synthetic overload pattern consistent with sustained "
                    "load imbalance on this feeder."
                ),
                "reasoning_summary": (
                    "Repeated overload and outage evidence supports load "
                    "rebalancing as the primary remediation."
                ),
                "recommended_action": recommended_action,
                "uncertainties": [],
                "cited_evidence_refs": cited_evidence_refs,
            },
        },
        {"text": "Analysis submitted."},
    ]


def _mocked_incident_analysis(asset_id: str, recommended_action: str) -> agent.IncidentAnalysis:
    """Produces a Batch-2-shaped IncidentAnalysis via the real agent
    pipeline against a scripted fake model. No network call."""
    real_risk = tools.get_risk_evidence(asset_id)
    script = _happy_path_script(asset_id, recommended_action, real_risk.evidence_refs)
    fake_llm = ScriptedFakeLlm(script=script)
    built_agent = agent.build_agent(model=fake_llm)
    return agent.analyze_incident(asset_id, agent=built_agent)


def _proposal_from_analysis(result: agent.IncidentAnalysis) -> IncidentProposal:
    return IncidentProposal(
        asset_id=result.asset_id,
        evidence_refs=result.evidence_refs,
        recommended_action=result.recommended_action,
        policy_class=result.policy_class,
        approval_required=result.approval_required,
        diagnosis=result.diagnosis,
        reasoning_summary=result.reasoning_summary,
    )


# ---------------------------------------------------------------------------
# Approval state machine.
# ---------------------------------------------------------------------------


def test_new_request_starts_pending():
    req = approval.request_approval()
    assert req.status == ApprovalStatus.PENDING


def test_approve_requires_approver_identity():
    with pytest.raises(approval.ApprovalError):
        approval.approve(approval.request_approval(), approver="")


def test_reject_requires_approver_identity():
    with pytest.raises(approval.ApprovalError):
        approval.reject(approval.request_approval(), approver="")


def test_cannot_approve_after_rejected():
    rejected = approval.reject(approval.request_approval(), approver="op1")
    with pytest.raises(approval.ApprovalError):
        approval.approve(rejected, approver="op2")


# ---------------------------------------------------------------------------
# DEMO-TP-007 end-to-end: HIGH_IMPACT, blocked pre-approval, then executed.
# ---------------------------------------------------------------------------


def test_demo_tp_007_full_workflow_blocked_then_approved_then_verified_and_audited():
    trail = AuditTrail()

    # DIAGNOSE/PLAN (offline mocked Gemini via the real Batch 2 pipeline).
    result = _mocked_incident_analysis("DEMO-TP-007", "REBALANCE_LOAD")
    assert result.risk_level == RiskLevel.CRITICAL
    assert result.policy_class == ImpactClass.HIGH_IMPACT
    assert result.approval_required is True
    assert result.next_step == "WAIT_FOR_HUMAN_APPROVAL"
    assert result.diagnosis  # Gemini-shaped diagnosis text present

    proposal = _proposal_from_analysis(result)

    # PRE-APPROVAL: execution must be blocked, and the block itself audited.
    pending = approval.request_approval()
    before = store.get_asset("DEMO-TP-007").signal_snapshot()
    with pytest.raises(ExecutionBlockedError):
        orchestrator.execute_action(proposal, pending, incident_id="INC-TEST-007", trail=trail)
    after = store.get_asset("DEMO-TP-007").signal_snapshot()
    assert before == after  # no state mutation happened

    blocked_record = trail.get("INC-TEST-007")
    assert blocked_record is not None
    assert blocked_record.action_status == "BLOCKED_PENDING_APPROVAL"
    assert blocked_record.approval_status == ApprovalStatus.PENDING.value
    assert blocked_record.before_state == {}
    assert blocked_record.after_state == {}

    # APPROVE and re-run the same incident.
    approved = approval.approve(pending, approver="demo-operator", reason="evidence verified")
    record = orchestrator.execute_action(
        proposal, approved, incident_id="INC-TEST-007", trail=trail
    )

    assert record.action_status == "EXECUTED"
    assert record.approval_status == ApprovalStatus.APPROVED.value
    assert record.policy_class == ImpactClass.HIGH_IMPACT.value
    assert record.proposed_action == "REBALANCE_LOAD"
    assert record.before_state != record.after_state
    assert record.risk_before is not None and record.risk_after is not None
    assert record.risk_after < record.risk_before
    assert record.verification_result == "IMPROVED"

    # Same incident_id -> latest record wins (Firestore-style upsert).
    assert trail.get("INC-TEST-007") is record

    # Confirm against a fresh read of live state.
    fresh_risk = tools.get_risk_evidence("DEMO-TP-007")
    assert fresh_risk.risk_score == record.risk_after


# ---------------------------------------------------------------------------
# Rejection: a rejected action must never execute.
# ---------------------------------------------------------------------------


def test_rejected_action_never_executes():
    trail = AuditTrail()
    result = _mocked_incident_analysis("DEMO-TP-007", "REBALANCE_LOAD")
    proposal = _proposal_from_analysis(result)

    pending = approval.request_approval()
    rejected = approval.reject(pending, approver="demo-operator", reason="not enough evidence")

    before = store.get_asset("DEMO-TP-007").signal_snapshot()
    with pytest.raises(ExecutionBlockedError):
        orchestrator.execute_action(
            proposal, rejected, incident_id="INC-TEST-REJECT", trail=trail
        )
    after = store.get_asset("DEMO-TP-007").signal_snapshot()

    assert before == after  # no state mutation happened
    record = trail.get("INC-TEST-REJECT")
    assert record is not None
    assert record.action_status == "BLOCKED_REJECTED"
    assert record.approval_status == ApprovalStatus.REJECTED.value

    # Direct call to the write tool with this same rejected approval must
    # also refuse -- there is no back door around the orchestrator.
    direct_result = tools.simulate_remediation(
        "DEMO-TP-007", "REBALANCE_LOAD", approval=rejected
    )
    assert direct_result.success is False
    assert direct_result.error == "HUMAN_APPROVAL_REQUIRED"


# ---------------------------------------------------------------------------
# LOW_IMPACT actions don't need approval and still get audited.
# ---------------------------------------------------------------------------


def test_low_impact_action_does_not_require_approval_and_executes():
    trail = AuditTrail()
    result = _mocked_incident_analysis("DEMO-TP-003", "DISPATCH_SYNTHETIC_INSPECTION")
    assert result.policy_class == ImpactClass.LOW_IMPACT
    assert result.approval_required is False

    proposal = _proposal_from_analysis(result)
    pending = approval.request_approval()  # still PENDING -- must not matter for LOW_IMPACT

    record = orchestrator.execute_action(
        proposal, pending, incident_id="INC-TEST-LOW", trail=trail
    )
    assert record.action_status == "EXECUTED"
    assert record.policy_class == ImpactClass.LOW_IMPACT.value


def test_no_recommended_action_is_recorded_and_not_executed():
    trail = AuditTrail()
    proposal = IncidentProposal(
        asset_id="DEMO-TP-001",
        evidence_refs=[],
        recommended_action=None,
        policy_class=None,
        approval_required=False,
    )
    record = orchestrator.execute_action(
        proposal, approval.request_approval(), incident_id="INC-TEST-NONE", trail=trail
    )
    assert record.action_status == "NO_ACTION_PROPOSED"


# ---------------------------------------------------------------------------
# Audit trail shape: Firestore-compatible, JSON-serializable.
# ---------------------------------------------------------------------------


def test_audit_record_is_json_serializable_and_firestore_shaped():
    trail = AuditTrail()
    result = _mocked_incident_analysis("DEMO-TP-007", "REBALANCE_LOAD")
    proposal = _proposal_from_analysis(result)
    approved = approval.approve(approval.request_approval(), approver="demo-operator")
    record = orchestrator.execute_action(
        proposal, approved, incident_id="INC-TEST-JSON", trail=trail
    )

    payload = record.to_dict()
    json.dumps(payload)  # must not raise: flat, JSON/Firestore-safe types only

    expected_keys = {
        "incident_id",
        "asset_id",
        "evidence_refs",
        "proposed_action",
        "policy_class",
        "approval_status",
        "action_status",
        "before_state",
        "after_state",
        "risk_before",
        "risk_after",
        "verification_result",
        "created_at",
        "updated_at",
    }
    assert set(payload.keys()) == expected_keys
    assert payload["incident_id"] == "INC-TEST-JSON"
    assert payload["asset_id"] == "DEMO-TP-007"
    assert isinstance(payload["evidence_refs"], list)


def test_audit_trail_list_and_get():
    trail = AuditTrail()
    result = _mocked_incident_analysis("DEMO-TP-007", "REBALANCE_LOAD")
    proposal = _proposal_from_analysis(result)
    approved = approval.approve(approval.request_approval(), approver="demo-operator")
    orchestrator.execute_action(proposal, approved, incident_id="INC-A", trail=trail)
    orchestrator.execute_action(proposal, approved, incident_id="INC-B", trail=trail)

    ids = {r.incident_id for r in trail.list()}
    assert ids == {"INC-A", "INC-B"}
    assert trail.get("INC-A").incident_id == "INC-A"
    assert trail.get("INC-DOES-NOT-EXIST") is None


# ---------------------------------------------------------------------------
# No network dependency (mirrors tests/test_tools.py's guard).
# ---------------------------------------------------------------------------


def test_no_network_import_in_orchestrator_approval_audit_modules():
    import ast
    from pathlib import Path

    disallowed = {"socket", "requests", "urllib.request", "http.client", "httpx", "aiohttp"}
    src_dir = Path(__file__).resolve().parents[1] / "src" / "ai_raxbar_agent"
    for name in ("orchestrator.py", "approval.py", "audit.py"):
        tree = ast.parse((src_dir / name).read_text(encoding="utf-8"), filename=name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in disallowed, f"{name} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                assert node.module not in disallowed, f"{name} imports {node.module}"
