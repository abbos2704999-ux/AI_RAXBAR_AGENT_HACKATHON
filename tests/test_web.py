"""Batch 5A: offline HTTP-layer tests for `ai_raxbar_agent.web`.

Every test here uses `fastapi.testclient.TestClient` against the in-process
ASGI app -- no socket, no real network call. Gemini is stubbed out with the
same `ScriptedFakeLlm` pattern `tests/test_orchestrator.py` uses (a real
ADK tool-calling loop, scripted model responses, zero network access), and
persistence uses the default offline `LocalRepository` -- never Firestore.
These tests exist to prove the HTTP layer delegates to (and never bypasses
or duplicates) the existing deterministic policy/approval/orchestrator
modules, not to test those modules' internals again.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ai_raxbar_agent import agent, tools, web
from ai_raxbar_agent.data_store import store

from fakes import ScriptedFakeLlm


@pytest.fixture(autouse=True)
def _reset_state():
    store.reset()
    web.set_test_agent_override(None)
    yield
    store.reset()
    web.set_test_agent_override(None)


@pytest.fixture
def client():
    return TestClient(web.app)


def _script(asset_id, recommended_action, cited_evidence_refs):
    return [
        {"call": "get_asset_context", "args": {"asset_id": asset_id}},
        {"call": "get_recent_events", "args": {"asset_id": asset_id, "limit": 10}},
        {"call": "get_risk_evidence", "args": {"asset_id": asset_id}},
        {"call": "get_remediation_candidates", "args": {"asset_id": asset_id}},
        {
            "call": "propose_incident_analysis",
            "args": {
                "diagnosis": "Synthetic diagnosis for HTTP-layer test.",
                "reasoning_summary": "Synthetic reasoning summary.",
                "recommended_action": recommended_action,
                "uncertainties": [],
                "cited_evidence_refs": cited_evidence_refs,
            },
        },
        {"text": "Analysis submitted."},
    ]


def _install_fake_agent(asset_id: str, recommended_action: str) -> None:
    real_risk = tools.get_risk_evidence(asset_id)
    fake_llm = ScriptedFakeLlm(script=_script(asset_id, recommended_action, real_risk.evidence_refs))
    web.set_test_agent_override(agent.build_agent(model=fake_llm))


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health_ok_offline(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /api/status
# ---------------------------------------------------------------------------


def test_status_shape_and_no_secrets(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "ai-raxbar-agent"
    assert "version" in body
    assert body["gemini_integration"] in ("CONFIGURED", "NOT_CONFIGURED")
    assert body["firestore_integration"] in ("LOCAL_ONLY", "FIRESTORE_CONFIGURED")
    assert body["synthetic_only_mode"] is True
    assert body["policy_gate"] == "ACTIVE"

    raw = resp.text.lower()
    for forbidden in (
        "api_key",
        "apikey",
        "credential",
        "secret",
        "private_key",
        "service_account",
        "ai-raxbar-agent-hackathon",  # real GCP project id must never appear
    ):
        assert forbidden not in raw


# ---------------------------------------------------------------------------
# Synthetic-id boundary.
# ---------------------------------------------------------------------------


def test_analyze_rejects_non_synthetic_asset_id(client):
    resp = client.post("/api/incidents/analyze", json={"asset_id": "PROD-FEEDER-1"})
    assert resp.status_code == 400
    assert "synthetic" in resp.json()["detail"].lower()


def test_analyze_rejects_unknown_demo_asset_id(client):
    resp = client.post("/api/incidents/analyze", json={"asset_id": "DEMO-TP-999"})
    assert resp.status_code == 404


def test_approve_rejects_non_synthetic_incident_id(client):
    resp = client.post(
        "/api/incidents/PROD-INC-1/approve", json={"approver": "op1", "reason": "x"}
    )
    assert resp.status_code == 400


def test_execute_rejects_non_synthetic_incident_id(client):
    resp = client.post("/api/incidents/PROD-INC-1/execute")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# HIGH_IMPACT: analyze must block before execution; approval required.
# ---------------------------------------------------------------------------


def test_high_impact_blocks_then_approve_then_execute(client):
    _install_fake_agent("DEMO-TP-007", "REBALANCE_LOAD")
    before = store.get_asset("DEMO-TP-007").signal_snapshot()

    analyze_resp = client.post("/api/incidents/analyze", json={"asset_id": "DEMO-TP-007"})
    assert analyze_resp.status_code == 200
    body = analyze_resp.json()
    assert body["blocked"] is True
    assert body["audit_record"]["action_status"] == "BLOCKED_PENDING_APPROVAL"
    assert body["analysis"]["policy_class"] == "HIGH_IMPACT"
    assert body["analysis"]["approval_required"] is True

    incident_id = body["incident_id"]
    after = store.get_asset("DEMO-TP-007").signal_snapshot()
    assert before == after  # no state mutation from a blocked analyze call

    # Execute before approval must still be refused.
    exec_before_approval = client.post(f"/api/incidents/{incident_id}/execute")
    assert exec_before_approval.status_code == 409
    assert store.get_asset("DEMO-TP-007").signal_snapshot() == before

    approve_resp = client.post(
        f"/api/incidents/{incident_id}/approve",
        json={"approver": "demo-operator", "reason": "evidence verified"},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["approval"]["status"] == "APPROVED"

    exec_resp = client.post(f"/api/incidents/{incident_id}/execute")
    assert exec_resp.status_code == 200
    record = exec_resp.json()["audit_record"]
    assert record["action_status"] == "EXECUTED"
    assert record["verification_result"] == "IMPROVED"
    assert store.get_asset("DEMO-TP-007").signal_snapshot() != before


def test_rejected_incident_cannot_execute(client):
    _install_fake_agent("DEMO-TP-007", "REBALANCE_LOAD")
    analyze_resp = client.post("/api/incidents/analyze", json={"asset_id": "DEMO-TP-007"})
    incident_id = analyze_resp.json()["incident_id"]
    before = store.get_asset("DEMO-TP-007").signal_snapshot()

    reject_resp = client.post(
        f"/api/incidents/{incident_id}/reject",
        json={"approver": "demo-operator", "reason": "insufficient evidence"},
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["approval"]["status"] == "REJECTED"

    exec_resp = client.post(f"/api/incidents/{incident_id}/execute")
    assert exec_resp.status_code == 409
    assert store.get_asset("DEMO-TP-007").signal_snapshot() == before


# ---------------------------------------------------------------------------
# LOW_IMPACT: no approval required, executes synchronously with analyze.
# ---------------------------------------------------------------------------


def test_low_impact_action_executes_through_analyze_and_returns_verification(client):
    _install_fake_agent("DEMO-TP-003", "DISPATCH_SYNTHETIC_INSPECTION")

    resp = client.post("/api/incidents/analyze", json={"asset_id": "DEMO-TP-003"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["blocked"] is False
    assert body["analysis"]["policy_class"] == "LOW_IMPACT"
    assert body["analysis"]["approval_required"] is False
    record = body["audit_record"]
    assert record["action_status"] == "EXECUTED"
    assert record["verification_result"] in ("IMPROVED", "NO_CHANGE")


# ---------------------------------------------------------------------------
# No business-logic bypass: HTTP can't skip the policy gate.
# ---------------------------------------------------------------------------


def test_execute_on_unknown_incident_id_is_404(client):
    resp = client.post("/api/incidents/HACKATHON-DOES-NOT-EXIST/execute")
    assert resp.status_code == 404


def test_default_backend_is_local(client):
    # No AI_RAXBAR_REPOSITORY_BACKEND set in the test environment -> local,
    # offline repository; confirms no accidental Firestore wiring.
    resp = client.get("/api/status")
    assert resp.json()["firestore_integration"] == "LOCAL_ONLY"
