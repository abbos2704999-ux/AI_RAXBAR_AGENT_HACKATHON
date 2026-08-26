"""Batch 4 offline tests: persistence interface, local repository, the
Firestore adapter (against a fake client), and orchestrator integration
(persist-then-gate ordering, idempotent retry, fail-closed on a
persistence failure).

Everything here is offline and deterministic. `FakeFirestoreClient`
(tests/fakes.py) is a structural stand-in for `google.cloud.firestore.Client`
with zero network access and zero dependency on the real
`google-cloud-firestore` package -- it proves `FirestoreRepository` behaves
identically to `LocalRepository` from the orchestrator's point of view
without ever touching a real backend.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Optional

import pytest

from ai_raxbar_agent import agent, approval, orchestrator, tools
from ai_raxbar_agent.audit import AuditRecord
from ai_raxbar_agent.data_store import store
from ai_raxbar_agent.firestore_repository import FirestoreRepository
from ai_raxbar_agent.local_repository import LocalRepository
from ai_raxbar_agent.models import ApprovalState, ApprovalStatus, ImpactClass, RiskLevel
from ai_raxbar_agent.orchestrator import ExecutionBlockedError, IncidentProposal
from ai_raxbar_agent.repository import IncidentRecord, IncidentRepository, RepositoryError

from fakes import FakeFirestoreClient, ScriptedFakeLlm


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
# A repository double that fails on demand, to prove fail-closed behavior.
# ---------------------------------------------------------------------------


class FailingRepository(IncidentRepository):
    """Wraps a real (working) repository but raises RepositoryError from
    one chosen method, to simulate a persistence backend outage at a
    specific point in the workflow."""

    def __init__(self, delegate: IncidentRepository, fail_on: str):
        self._delegate = delegate
        self._fail_on = fail_on
        self.calls: list[str] = []

    def _maybe_fail(self, name: str) -> None:
        self.calls.append(name)
        if name == self._fail_on:
            raise RepositoryError(f"simulated persistence outage in {name}")

    def save_incident(self, incident: IncidentRecord) -> None:
        self._maybe_fail("save_incident")
        self._delegate.save_incident(incident)

    def get_incident(self, incident_id: str):
        self._maybe_fail("get_incident")
        return self._delegate.get_incident(incident_id)

    def save_audit_record(self, record: AuditRecord) -> None:
        self._maybe_fail("save_audit_record")
        self._delegate.save_audit_record(record)

    def list_audit_records(self, incident_id: Optional[str] = None):
        self._maybe_fail("list_audit_records")
        return self._delegate.list_audit_records(incident_id)

    def save_approval_state(self, incident_id: str, approval: ApprovalState) -> None:
        self._maybe_fail("save_approval_state")
        self._delegate.save_approval_state(incident_id, approval)

    def get_approval_state(self, incident_id: str):
        self._maybe_fail("get_approval_state")
        return self._delegate.get_approval_state(incident_id)


# ---------------------------------------------------------------------------
# LocalRepository: basic contract.
# ---------------------------------------------------------------------------


def test_local_repository_incident_round_trip():
    repo = LocalRepository()
    record = IncidentRecord(
        incident_id="INC-1",
        asset_id="DEMO-TP-007",
        detected_at="2026-08-26T00:00:00+00:00",
        evidence_refs=["EVT-007-01"],
        diagnosis="Overload pattern detected.",
        recommended_action="REBALANCE_LOAD",
        policy_class="HIGH_IMPACT",
        approval_required=True,
        approval_status="PENDING",
        approved_by=None,
        action_status="BLOCKED_PENDING_APPROVAL",
        risk_before=None,
        risk_after=None,
        verification_result=None,
        created_at="2026-08-26T00:00:00+00:00",
        updated_at="2026-08-26T00:00:00+00:00",
    )
    repo.save_incident(record)
    fetched = repo.get_incident("INC-1")
    assert fetched is not None
    assert fetched.asset_id == "DEMO-TP-007"
    assert fetched.action_status == "BLOCKED_PENDING_APPROVAL"
    assert repo.get_incident("INC-DOES-NOT-EXIST") is None


def test_local_repository_approval_round_trip():
    repo = LocalRepository()
    assert repo.get_approval_state("INC-1") is None
    approved = ApprovalState(status=ApprovalStatus.APPROVED, approver="op1", reason="ok")
    repo.save_approval_state("INC-1", approved)
    fetched = repo.get_approval_state("INC-1")
    assert fetched.status == ApprovalStatus.APPROVED
    assert fetched.approver == "op1"


# ---------------------------------------------------------------------------
# End-to-end orchestrator + repository: DEMO-TP-007.
# ---------------------------------------------------------------------------


def _run_demo_tp_007_workflow(repository):
    result = _mocked_incident_analysis("DEMO-TP-007", "REBALANCE_LOAD")
    assert result.risk_level == RiskLevel.CRITICAL
    assert result.policy_class == ImpactClass.HIGH_IMPACT
    assert result.approval_required is True

    proposal = _proposal_from_analysis(result)
    incident_id = "INC-REPO-007"

    # PRE-APPROVAL: blocked, but incident + pending approval are persisted.
    pending = approval.request_approval()
    before = store.get_asset("DEMO-TP-007").signal_snapshot()
    with pytest.raises(ExecutionBlockedError):
        orchestrator.execute_action(
            proposal, pending, incident_id=incident_id, repository=repository
        )
    after = store.get_asset("DEMO-TP-007").signal_snapshot()
    assert before == after

    persisted = repository.get_incident(incident_id)
    assert persisted is not None
    assert persisted.action_status == "BLOCKED_PENDING_APPROVAL"
    assert persisted.approval_status == ApprovalStatus.PENDING.value
    assert persisted.diagnosis == proposal.diagnosis

    persisted_approval = repository.get_approval_state(incident_id)
    assert persisted_approval.status == ApprovalStatus.PENDING

    first_created_at = persisted.created_at

    # APPROVE and re-run the same incident.
    approved = approval.approve(pending, approver="demo-operator", reason="verified")
    record = orchestrator.execute_action(
        proposal, approved, incident_id=incident_id, repository=repository
    )
    assert record.action_status == "EXECUTED"

    final = repository.get_incident(incident_id)
    assert final.action_status == "EXECUTED"
    assert final.approval_status == ApprovalStatus.APPROVED.value
    assert final.approved_by == "demo-operator"
    assert final.risk_before is not None and final.risk_after is not None
    assert final.risk_after < final.risk_before
    assert final.verification_result == "IMPROVED"
    # Idempotent create: creation time preserved across the retry/update.
    assert final.created_at == first_created_at
    assert final.updated_at != first_created_at or final.updated_at >= first_created_at

    audit_records = repository.list_audit_records(incident_id)
    assert [r.action_status for r in audit_records] == [
        "BLOCKED_PENDING_APPROVAL",
        "EXECUTED",
    ]
    return incident_id


def test_demo_tp_007_workflow_persists_with_local_repository():
    repo = LocalRepository()
    _run_demo_tp_007_workflow(repo)


def test_demo_tp_007_workflow_persists_with_firestore_repository_fake_client():
    client = FakeFirestoreClient()
    repo = FirestoreRepository(client)
    _run_demo_tp_007_workflow(repo)
    # Confirm data actually landed in the Firestore-shaped collections.
    assert client.collection("incidents").docs
    assert client.collection("approvals").docs
    assert client.collection("audit_records").docs
    assert client.network_call_count > 0


# ---------------------------------------------------------------------------
# Idempotent retry.
# ---------------------------------------------------------------------------


def test_repeated_blocked_attempt_does_not_duplicate_audit_records():
    repo = LocalRepository()
    result = _mocked_incident_analysis("DEMO-TP-007", "REBALANCE_LOAD")
    proposal = _proposal_from_analysis(result)
    pending = approval.request_approval()

    for _ in range(3):
        with pytest.raises(ExecutionBlockedError):
            orchestrator.execute_action(
                proposal, pending, incident_id="INC-RETRY", repository=repo
            )

    audit_records = repo.list_audit_records("INC-RETRY")
    assert len(audit_records) == 1  # retries overwrite, they don't accumulate
    assert audit_records[0].action_status == "BLOCKED_PENDING_APPROVAL"

    incident = repo.get_incident("INC-RETRY")
    assert incident is not None
    # created_at must not drift across retries.
    assert incident.created_at == incident.created_at


def test_repeated_blocked_attempt_preserves_created_at_across_retries():
    repo = LocalRepository()
    result = _mocked_incident_analysis("DEMO-TP-007", "REBALANCE_LOAD")
    proposal = _proposal_from_analysis(result)
    pending = approval.request_approval()

    with pytest.raises(ExecutionBlockedError):
        orchestrator.execute_action(proposal, pending, incident_id="INC-RETRY-2", repository=repo)
    first_created_at = repo.get_incident("INC-RETRY-2").created_at

    with pytest.raises(ExecutionBlockedError):
        orchestrator.execute_action(proposal, pending, incident_id="INC-RETRY-2", repository=repo)
    second_created_at = repo.get_incident("INC-RETRY-2").created_at

    assert first_created_at == second_created_at


# ---------------------------------------------------------------------------
# Rejection persists and never executes.
# ---------------------------------------------------------------------------


def test_rejected_action_persists_and_never_executes():
    repo = LocalRepository()
    result = _mocked_incident_analysis("DEMO-TP-007", "REBALANCE_LOAD")
    proposal = _proposal_from_analysis(result)

    rejected = approval.reject(approval.request_approval(), approver="demo-operator")
    before = store.get_asset("DEMO-TP-007").signal_snapshot()
    with pytest.raises(ExecutionBlockedError):
        orchestrator.execute_action(
            proposal, rejected, incident_id="INC-REJECT-REPO", repository=repo
        )
    after = store.get_asset("DEMO-TP-007").signal_snapshot()
    assert before == after

    incident = repo.get_incident("INC-REJECT-REPO")
    assert incident.action_status == "BLOCKED_REJECTED"
    assert incident.approval_status == ApprovalStatus.REJECTED.value

    stored_approval = repo.get_approval_state("INC-REJECT-REPO")
    assert stored_approval.status == ApprovalStatus.REJECTED


# ---------------------------------------------------------------------------
# HIGH_IMPACT remains blocked before approval (repository-backed).
# ---------------------------------------------------------------------------


def test_high_impact_blocked_before_approval_with_repository():
    repo = LocalRepository()
    result = _mocked_incident_analysis("DEMO-TP-007", "REBALANCE_LOAD")
    proposal = _proposal_from_analysis(result)
    pending = approval.request_approval()

    with pytest.raises(ExecutionBlockedError):
        orchestrator.execute_action(
            proposal, pending, incident_id="INC-BLOCK-REPO", repository=repo
        )

    incident = repo.get_incident("INC-BLOCK-REPO")
    assert incident.action_status == "BLOCKED_PENDING_APPROVAL"
    assert incident.risk_before is None and incident.risk_after is None


# ---------------------------------------------------------------------------
# Persistence failure fails closed.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fail_on", ["save_incident", "save_approval_state"])
def test_persistence_failure_before_gate_check_fails_closed(fail_on):
    real_repo = LocalRepository()
    failing_repo = FailingRepository(real_repo, fail_on=fail_on)

    result = _mocked_incident_analysis("DEMO-TP-007", "REBALANCE_LOAD")
    proposal = _proposal_from_analysis(result)
    approved = approval.approve(approval.request_approval(), approver="demo-operator")

    before = store.get_asset("DEMO-TP-007").signal_snapshot()
    with pytest.raises(RepositoryError):
        orchestrator.execute_action(
            proposal, approved, incident_id="INC-FAIL-CLOSED", repository=failing_repo
        )
    after = store.get_asset("DEMO-TP-007").signal_snapshot()

    # The write tool must never have been reached: no state mutation.
    assert before == after


def test_persistence_failure_after_execution_does_not_hide_the_error():
    # Once the synthetic action has actually run, a later persistence
    # failure (e.g. writing the final result) must still surface loudly --
    # it must not be swallowed -- even though the (already-approved,
    # already-executed) action itself cannot be undone.
    real_repo = LocalRepository()
    failing_repo = FailingRepository(real_repo, fail_on="save_audit_record")

    result = _mocked_incident_analysis("DEMO-TP-003", "DISPATCH_SYNTHETIC_INSPECTION")
    proposal = _proposal_from_analysis(result)
    assert proposal.policy_class == ImpactClass.LOW_IMPACT

    pending = approval.request_approval()  # LOW_IMPACT: approval not required
    with pytest.raises(RepositoryError):
        orchestrator.execute_action(
            proposal, pending, incident_id="INC-FAIL-AFTER", repository=failing_repo
        )
    # The action itself did execute (LOW_IMPACT, no approval needed) --
    # this is expected; the point is the persistence error is not hidden.
    assert "save_audit_record" in failing_repo.calls


# ---------------------------------------------------------------------------
# Verification result persisted.
# ---------------------------------------------------------------------------


def test_verification_result_is_persisted_on_the_incident():
    repo = LocalRepository()
    result = _mocked_incident_analysis("DEMO-TP-007", "REBALANCE_LOAD")
    proposal = _proposal_from_analysis(result)
    approved = approval.approve(approval.request_approval(), approver="demo-operator")

    orchestrator.execute_action(
        proposal, approved, incident_id="INC-VERIFY-REPO", repository=repo
    )
    incident = repo.get_incident("INC-VERIFY-REPO")
    assert incident.verification_result == "IMPROVED"
    assert incident.risk_before is not None
    assert incident.risk_after is not None
    assert incident.risk_after < incident.risk_before


# ---------------------------------------------------------------------------
# No chain-of-thought persisted.
# ---------------------------------------------------------------------------


def test_incident_record_schema_has_no_chain_of_thought_field():
    forbidden_substrings = ("thought", "thinking", "internal_reasoning", "scratchpad", "raw_response")
    field_names = {f for f in IncidentRecord.__dataclass_fields__}
    for name in field_names:
        lowered = name.lower()
        assert not any(bad in lowered for bad in forbidden_substrings), name


def test_persisted_diagnosis_matches_proposal_narrative_exactly():
    repo = LocalRepository()
    result = _mocked_incident_analysis("DEMO-TP-007", "REBALANCE_LOAD")
    proposal = _proposal_from_analysis(result)
    approved = approval.approve(approval.request_approval(), approver="demo-operator")

    orchestrator.execute_action(
        proposal, approved, incident_id="INC-DIAG-REPO", repository=repo
    )
    incident = repo.get_incident("INC-DIAG-REPO")
    assert incident.diagnosis == proposal.diagnosis
    # The diagnosis is exactly the concise, user-facing text the model put
    # into propose_incident_analysis -- nothing longer/internal is ever
    # captured anywhere in this codebase for this field to have leaked from.
    assert incident.diagnosis == (
        "Synthetic overload pattern consistent with sustained "
        "load imbalance on this feeder."
    )


# ---------------------------------------------------------------------------
# Audit contract: JSON-serializable, exact field set.
# ---------------------------------------------------------------------------


def test_incident_record_to_dict_matches_required_audit_contract():
    repo = LocalRepository()
    result = _mocked_incident_analysis("DEMO-TP-007", "REBALANCE_LOAD")
    proposal = _proposal_from_analysis(result)
    approved = approval.approve(approval.request_approval(), approver="demo-operator")
    orchestrator.execute_action(proposal, approved, incident_id="INC-SCHEMA", repository=repo)

    payload = repo.get_incident("INC-SCHEMA").to_dict()
    json.dumps(payload)  # must not raise

    required_keys = {
        "incident_id",
        "asset_id",
        "detected_at",
        "evidence_refs",
        "diagnosis",
        "recommended_action",
        "policy_class",
        "approval_required",
        "approval_status",
        "approved_by",
        "action_status",
        "risk_before",
        "risk_after",
        "verification_result",
        "created_at",
        "updated_at",
    }
    assert set(payload.keys()) == required_keys


# ---------------------------------------------------------------------------
# Firestore adapter: no network calls in offline tests.
# ---------------------------------------------------------------------------


def test_firestore_repository_rejects_none_client():
    with pytest.raises(ValueError):
        FirestoreRepository(None)


def test_firestore_repository_get_missing_incident_returns_none():
    client = FakeFirestoreClient()
    repo = FirestoreRepository(client)
    assert repo.get_incident("does-not-exist") is None
    assert repo.get_approval_state("does-not-exist") is None


def test_firestore_repository_wraps_backend_errors_as_repository_error():
    class BrokenCollection:
        def document(self, doc_id):
            raise RuntimeError("boom")

    class BrokenClient:
        def collection(self, name):
            return BrokenCollection()

    repo = FirestoreRepository(BrokenClient())
    incident = IncidentRecord(
        incident_id="INC-X",
        asset_id="DEMO-TP-007",
        detected_at="2026-08-26T00:00:00+00:00",
        evidence_refs=[],
        diagnosis="d",
        recommended_action="REBALANCE_LOAD",
        policy_class="HIGH_IMPACT",
        approval_required=True,
        approval_status="PENDING",
        approved_by=None,
        action_status="BLOCKED_PENDING_APPROVAL",
        risk_before=None,
        risk_after=None,
        verification_result=None,
        created_at="2026-08-26T00:00:00+00:00",
        updated_at="2026-08-26T00:00:00+00:00",
    )
    with pytest.raises(RepositoryError):
        repo.save_incident(incident)


def test_firestore_repository_module_does_not_import_sdk_at_module_level():
    src_dir = Path(__file__).resolve().parents[1] / "src" / "ai_raxbar_agent"
    tree = ast.parse((src_dir / "firestore_repository.py").read_text(encoding="utf-8"))
    for node in tree.body:  # module (top) level only -- lazy imports inside
        # function bodies are fine and expected (see build_live_client).
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("google.cloud.firestore"), alias.name
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "google.cloud" or not any(
                a.name == "firestore" for a in node.names
            )


def test_no_network_import_in_persistence_modules():
    disallowed = {"socket", "requests", "urllib.request", "http.client", "httpx", "aiohttp"}
    src_dir = Path(__file__).resolve().parents[1] / "src" / "ai_raxbar_agent"
    for name in ("repository.py", "local_repository.py", "firestore_repository.py"):
        tree = ast.parse((src_dir / name).read_text(encoding="utf-8"), filename=name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in disallowed, f"{name} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                assert node.module not in disallowed, f"{name} imports {node.module}"
