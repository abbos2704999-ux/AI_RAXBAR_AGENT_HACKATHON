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
from ai_raxbar_agent.local_repository import LocalRepository
from ai_raxbar_agent.repository import RepositoryError

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


# ---------------------------------------------------------------------------
# POST /api/assets/{asset_id}/reset -- fixes the live-demo state-drift bug
# where a prior execute's mutation silently carried over into the next
# analyze because nothing reset the backend's in-memory data_store between
# demo runs (see the Batch 5G comment block in tests/test_demo_ui.py).
# ---------------------------------------------------------------------------


def test_analyze_after_prior_execute_without_reset_reuses_mutated_state(client):
    """Pins down the pre-fix bug this endpoint exists to fix: without an
    intervening reset, a second analyze/execute cycle on the same asset
    starts from the first cycle's mutated state, not the canonical
    baseline -- proving the drift is real at the HTTP layer, not just in
    the data-store unit test."""
    _install_fake_agent("DEMO-TP-007", "REBALANCE_LOAD")
    first = client.post("/api/incidents/analyze", json={"asset_id": "DEMO-TP-007"}).json()
    assert first["analysis"]["risk_score"] == 100
    incident_id = first["incident_id"]
    client.post(
        f"/api/incidents/{incident_id}/approve",
        json={"approver": "demo-operator", "reason": "evidence verified"},
    )
    client.post(f"/api/incidents/{incident_id}/execute")

    _install_fake_agent("DEMO-TP-007", "REBALANCE_LOAD")
    second = client.post("/api/incidents/analyze", json={"asset_id": "DEMO-TP-007"}).json()
    assert second["analysis"]["risk_score"] != 100  # drifted, not canonical baseline


def test_reset_asset_endpoint_restores_canonical_baseline_after_execute(client):
    # The autouse fixture already reset the store, so this is the canonical
    # on-disk baseline snapshot before any mutation in this test.
    baseline = store.get_asset("DEMO-TP-007").signal_snapshot()

    _install_fake_agent("DEMO-TP-007", "REBALANCE_LOAD")
    first = client.post("/api/incidents/analyze", json={"asset_id": "DEMO-TP-007"}).json()
    incident_id = first["incident_id"]
    client.post(
        f"/api/incidents/{incident_id}/approve",
        json={"approver": "demo-operator", "reason": "evidence verified"},
    )
    client.post(f"/api/incidents/{incident_id}/execute")
    assert store.get_asset("DEMO-TP-007").signal_snapshot() != baseline

    reset_resp = client.post("/api/assets/DEMO-TP-007/reset")
    assert reset_resp.status_code == 200
    body = reset_resp.json()
    assert body["asset_id"] == "DEMO-TP-007"
    assert body["risk_score"] == 100
    assert body["risk_level"] == "CRITICAL"
    assert store.get_asset("DEMO-TP-007").signal_snapshot() == baseline

    _install_fake_agent("DEMO-TP-007", "REBALANCE_LOAD")
    second = client.post("/api/incidents/analyze", json={"asset_id": "DEMO-TP-007"}).json()
    assert second["analysis"]["risk_score"] == 100  # fresh cycle, canonical baseline again


def test_reset_asset_endpoint_rejects_non_synthetic_asset_id(client):
    resp = client.post("/api/assets/PROD-FEEDER-1/reset")
    assert resp.status_code == 400
    assert "synthetic" in resp.json()["detail"].lower()


def test_reset_asset_endpoint_rejects_unknown_demo_asset_id(client):
    resp = client.post("/api/assets/DEMO-TP-999/reset")
    assert resp.status_code == 404


def test_reset_asset_endpoint_is_idempotent(client):
    first = client.post("/api/assets/DEMO-TP-007/reset")
    second = client.post("/api/assets/DEMO-TP-007/reset")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


# ---------------------------------------------------------------------------
# Persistence-failure disclosure boundary.
#
# `RepositoryError` messages are built by the backend adapter and embed the
# underlying exception (`firestore_repository.py` does
# `f"Failed to save incident {id!r}: {exc}"`). A real Firestore/gRPC error
# string carries the full resource path -- which includes the GCP project id
# and database name -- plus internal endpoints and IAM detail. This service is
# publicly reachable and unauthenticated for the judge demo, so none of that
# may reach the client: it is logged server-side and replaced with a generic
# 503 body (`web._persistence_unavailable`). These tests pin that contract on
# every endpoint that touches persistence.
# ---------------------------------------------------------------------------

_LEAKY_MESSAGE = (
    "Failed to save incident 'INC-DEMO-TP-007-abcd1234': 404 Requested entity was "
    "not found. resource=projects/secret-project-id-12345/databases/(default)/"
    "documents/incidents/x; endpoint=firestore.googleapis.com; "
    "serviceAccount=svc-internal@secret-project-id-12345.iam.gserviceaccount.com"
)

_LEAKY_TOKENS = (
    "secret-project-id-12345",
    "firestore.googleapis.com",
    "iam.gserviceaccount.com",
    "projects/",
)


class _ExplodingRepository(LocalRepository):
    """A repository whose every operation fails with a realistically leaky
    `RepositoryError`, matching the message shape `FirestoreRepository`
    actually produces."""

    def _boom(self):
        raise RepositoryError(_LEAKY_MESSAGE)

    def save_incident(self, incident):
        self._boom()

    def get_incident(self, incident_id):
        self._boom()

    def save_audit_record(self, record):
        self._boom()

    def list_audit_records(self, incident_id=None):
        self._boom()

    def save_approval_state(self, incident_id, approval):
        self._boom()

    def get_approval_state(self, incident_id):
        self._boom()


class _ReadOnlyExplodingRepository(_ExplodingRepository):
    """Reads succeed (so a handler gets past its 404 check) but writes
    fail -- exercises the write-side error paths specifically."""

    def get_incident(self, incident_id):
        return LocalRepository.get_incident(self, incident_id)

    def get_approval_state(self, incident_id):
        return LocalRepository.get_approval_state(self, incident_id)


def _assert_no_backend_detail_leaked(resp):
    assert resp.status_code == 503, resp.status_code
    body = resp.text
    for token in _LEAKY_TOKENS:
        assert token not in body, f"backend detail {token!r} leaked to client: {body}"
    assert "Failed to save incident" not in body
    assert resp.json()["detail"] == web._PERSISTENCE_UNAVAILABLE_DETAIL


@pytest.fixture
def exploding_repo(monkeypatch):
    def _install(repo):
        monkeypatch.setattr(web, "get_repository", lambda: repo)
        return repo

    return _install


def test_analyze_persistence_failure_returns_generic_503(client, exploding_repo):
    exploding_repo(_ExplodingRepository())
    _install_fake_agent("DEMO-TP-007", "REBALANCE_LOAD")
    resp = client.post("/api/incidents/analyze", json={"asset_id": "DEMO-TP-007"})
    _assert_no_backend_detail_leaked(resp)


def test_approve_persistence_failure_returns_generic_503(client, exploding_repo):
    # Create a real pending incident in the default local repository first...
    _install_fake_agent("DEMO-TP-007", "REBALANCE_LOAD")
    incident_id = client.post(
        "/api/incidents/analyze", json={"asset_id": "DEMO-TP-007"}
    ).json()["incident_id"]

    # ...then make only the approval *write* fail. Seed the incident across
    # via the public IncidentRepository interface (no private attribute
    # access), so the handler gets past its 404 check and the 503 under test
    # can only come from the approval write.
    incident = web._local_repository.get_incident(incident_id)
    assert incident is not None
    repo = _ReadOnlyExplodingRepository()
    LocalRepository.save_incident(repo, incident)
    assert repo.get_incident(incident_id) is not None
    exploding_repo(repo)

    resp = client.post(
        f"/api/incidents/{incident_id}/approve",
        json={"approver": "demo-operator", "reason": "evidence verified"},
    )
    _assert_no_backend_detail_leaked(resp)


def test_execute_persistence_read_failure_returns_generic_503(client, exploding_repo):
    exploding_repo(_ExplodingRepository())
    resp = client.post("/api/incidents/INC-DEMO-TP-007-abcd1234/execute")
    _assert_no_backend_detail_leaked(resp)


def test_reject_persistence_read_failure_returns_generic_503(client, exploding_repo):
    exploding_repo(_ExplodingRepository())
    resp = client.post(
        "/api/incidents/INC-DEMO-TP-007-abcd1234/reject",
        json={"approver": "demo-operator", "reason": "not now"},
    )
    _assert_no_backend_detail_leaked(resp)


def test_unavailable_backend_returns_generic_503_without_backend_detail(client, monkeypatch):
    """A `RepositoryUnavailableError` (backend selection/construction
    failure) must also fail closed with the same generic body -- never the
    underlying exception text."""

    def _unavailable():
        raise web.RepositoryUnavailableError(_LEAKY_MESSAGE)

    monkeypatch.setattr(web, "get_repository", _unavailable)
    resp = client.post("/api/incidents/INC-DEMO-TP-007-abcd1234/execute")
    _assert_no_backend_detail_leaked(resp)


def test_persistence_failure_is_logged_server_side(client, exploding_repo, caplog):
    """The detail is not lost -- it is written to the server log, where an
    operator (not an anonymous browser) can read it."""
    exploding_repo(_ExplodingRepository())
    with caplog.at_level("ERROR", logger="ai_raxbar_agent.web"):
        client.post("/api/incidents/INC-DEMO-TP-007-abcd1234/execute")

    records = [r for r in caplog.records if r.name == "ai_raxbar_agent.web"]
    assert len(records) == 1, [r.getMessage() for r in records]
    record = records[0]
    assert record.levelname == "ERROR"
    assert "Persistence failure during incident read" == record.getMessage()
    # The exception itself -- including the detail withheld from the client --
    # is attached, so an operator reading the log loses nothing.
    assert record.exc_info is not None
    assert _LEAKY_MESSAGE in str(record.exc_info[1])
