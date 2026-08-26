"""Batch 5A: minimal, Cloud Run-shaped HTTP entrypoint.

A thin FastAPI wrapper around the existing agent / orchestrator / policy /
approval / repository modules. No risk, policy, approval, or persistence
*decision* is made in this file -- every decision is delegated to the same
deterministic code the offline test suite already exercises
(`policy.evaluate_policy`, `orchestrator.execute_action`,
`approval.approve`/`reject`). Handlers only translate HTTP <-> those calls.

Safety boundary:
- Every endpoint that accepts an asset_id or incident_id rejects anything
  that isn't a synthetic/demo identifier (`DEMO-*` / `HACKATHON-*`,
  optionally after the orchestrator's `INC-` incident-id prefix) via
  `require_synthetic_identifier`, before any other module is touched.
- `/health` never imports or calls anything Gemini- or Firestore-related --
  it is pure process liveness.
- `/api/status` reports configuration *flags* only (whether a live Gemini
  or Firestore call could be attempted). It never makes either call, and
  never returns a credential, API key, or raw project id.
- The persistence backend defaults to the offline `LocalRepository`
  (`AI_RAXBAR_REPOSITORY_BACKEND` unset or `local`). Setting it to
  `firestore` builds a `FirestoreRepository` the first time a request
  actually needs persistence, via `firestore_repository.build_live_client()`
  -- standard Application Default Credentials / the Cloud Run service
  identity, never a service-account JSON file. If that construction fails,
  the request fails closed (503); nothing here silently falls back to the
  local in-memory repository.
"""

from __future__ import annotations

import os
import threading
from dataclasses import asdict
from importlib import metadata
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import approval, config
from . import agent as agent_module
from . import orchestrator
from .audit import AuditRecord
from .data_store import AssetNotFoundError, store
from .local_repository import LocalRepository
from .models import ApprovalState, ImpactClass
from .orchestrator import ExecutionBlockedError, IncidentProposal
from .repository import IncidentRecord, IncidentRepository, RepositoryError

SERVICE_NAME = "ai-raxbar-agent"

# Public API-layer synthetic-data boundary. Deliberately broader than (and
# independent of) `repository._DEMO_CLEANUP_PREFIXES` -- that guard exists
# only for the narrow Firestore smoke-test cleanup path; this one governs
# every asset/incident identifier this HTTP service will accept at all.
_ALLOWED_ID_PREFIXES = ("DEMO-", "HACKATHON-")


def _service_version() -> str:
    try:
        return metadata.version("ai-raxbar-agent")
    except metadata.PackageNotFoundError:
        return "0.0.0-dev"


def is_synthetic_identifier(identifier: str) -> bool:
    """True if `identifier` looks like public-safe synthetic/demo data --
    starts with `DEMO-` or `HACKATHON-`, optionally after the
    orchestrator's `INC-` incident-id prefix (e.g. `new_incident_id`
    produces `INC-DEMO-TP-007-a1b2c3d4`)."""
    if not isinstance(identifier, str) or not identifier:
        return False
    candidate = identifier[len("INC-") :] if identifier.startswith("INC-") else identifier
    return candidate.startswith(_ALLOWED_ID_PREFIXES)


class SyntheticIdRejectedError(ValueError):
    """Raised when a request supplies an asset/incident id outside the
    public synthetic-data boundary. Every endpoint below that accepts an
    id calls `require_synthetic_identifier` first -- there is no code path
    through this API that reaches real/production data."""


def require_synthetic_identifier(identifier: str, *, kind: str) -> None:
    if not is_synthetic_identifier(identifier):
        raise SyntheticIdRejectedError(
            f"Rejected {kind} {identifier!r}: this API only accepts synthetic/demo "
            f"identifiers starting with one of {_ALLOWED_ID_PREFIXES!r}."
        )


# ---------------------------------------------------------------------------
# Repository backend selection (local by default; Firestore opt-in via env).
# ---------------------------------------------------------------------------


class RepositoryUnavailableError(RuntimeError):
    """Raised when the configured persistence backend cannot be reached.
    Callers must fail closed -- never fall back to a different backend."""


_local_repository = LocalRepository()
_firestore_repository: Optional[IncidentRepository] = None
_firestore_repository_lock = threading.Lock()


def get_repository() -> IncidentRepository:
    """Selects the persistence backend from `AI_RAXBAR_REPOSITORY_BACKEND`
    (`local`, the default, or `firestore`). Never called from `/health`,
    and never at import time -- only from request handlers that actually
    need persistence -- so the process can start and report health with no
    Google Cloud credential or network access at all. The Firestore client
    is constructed at most once (lazily, on first use) and cached; a
    construction failure raises `RepositoryUnavailableError` rather than
    silently returning the local repository.
    """
    backend = os.environ.get("AI_RAXBAR_REPOSITORY_BACKEND", "local").strip().lower()
    if backend in ("", "local"):
        return _local_repository
    if backend == "firestore":
        global _firestore_repository
        with _firestore_repository_lock:
            if _firestore_repository is None:
                try:
                    from .firestore_repository import FirestoreRepository, build_live_client

                    client = build_live_client(project=os.environ.get("GOOGLE_CLOUD_PROJECT") or None)
                    _firestore_repository = FirestoreRepository(client)
                except Exception as exc:  # noqa: BLE001 -- fail closed, never fall back
                    raise RepositoryUnavailableError(
                        "Firestore backend configured "
                        "(AI_RAXBAR_REPOSITORY_BACKEND=firestore) but unavailable: "
                        f"{type(exc).__name__}"
                    ) from exc
            return _firestore_repository
    raise RepositoryUnavailableError(
        f"Unknown AI_RAXBAR_REPOSITORY_BACKEND={backend!r}; expected 'local' or 'firestore'."
    )


# ---------------------------------------------------------------------------
# Agent selection (real Gemini by default; offline tests override).
# ---------------------------------------------------------------------------

_test_agent_override: Any = None


def get_agent() -> Any:
    """Returns the ADK agent `/api/incidents/analyze` should run, or None.

    None means "build a real, Gemini-backed agent via `agent.build_agent()`
    when the request is handled" -- the production path. Offline tests call
    `set_test_agent_override` with an agent built against a scripted fake
    model (see `tests/fakes.py::ScriptedFakeLlm`, the same pattern
    `tests/test_orchestrator.py` uses), so the HTTP layer can be exercised
    end-to-end with zero network access.
    """
    return _test_agent_override


def set_test_agent_override(test_agent: Any) -> None:
    """Test-only hook. Never called by production code or by this module
    itself outside of tests."""
    global _test_agent_override
    _test_agent_override = test_agent


# ---------------------------------------------------------------------------
# Request/response shapes.
# ---------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    asset_id: str = Field(..., min_length=1)


class ApprovalRequest(BaseModel):
    approver: str = Field(..., min_length=1)
    reason: str = ""


def _audit_record_to_dict(record: AuditRecord) -> dict:
    return asdict(record)


def _approval_to_dict(state: ApprovalState) -> dict:
    return {"status": state.status.value, "approver": state.approver, "reason": state.reason}


def _proposal_from_incident(record: IncidentRecord) -> IncidentProposal:
    policy_class = ImpactClass(record.policy_class) if record.policy_class else None
    return IncidentProposal(
        asset_id=record.asset_id,
        evidence_refs=list(record.evidence_refs),
        recommended_action=record.recommended_action,
        policy_class=policy_class,
        approval_required=record.approval_required,
        diagnosis=record.diagnosis,
    )


def _require_repository() -> IncidentRepository:
    try:
        return get_repository()
    except RepositoryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _require_synthetic_id(identifier: str, *, kind: str) -> None:
    try:
        require_synthetic_identifier(identifier, kind=kind)
    except SyntheticIdRejectedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _transition_approval(incident_id: str, req: ApprovalRequest, *, action: str) -> dict:
    _require_synthetic_id(incident_id, kind="incident_id")
    repo = _require_repository()

    incident = repo.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"Unknown incident_id: {incident_id!r}")

    current = repo.get_approval_state(incident_id) or approval.request_approval()
    try:
        if action == "approve":
            new_state = approval.approve(current, approver=req.approver, reason=req.reason)
        else:
            new_state = approval.reject(current, approver=req.approver, reason=req.reason)
    except approval.ApprovalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        repo.save_approval_state(incident_id, new_state)
    except RepositoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"incident_id": incident_id, "approval": _approval_to_dict(new_state)}


def create_app() -> FastAPI:
    app = FastAPI(title=SERVICE_NAME, version=_service_version())

    @app.get("/health")
    def health() -> dict:
        # Process liveness only -- no Gemini, no Firestore, no repository
        # lookup, no synthetic-data loading.
        return {"status": "ok"}

    @app.get("/api/status")
    def status() -> dict:
        backend = os.environ.get("AI_RAXBAR_REPOSITORY_BACKEND", "local").strip().lower() or "local"
        return {
            "service": SERVICE_NAME,
            "version": _service_version(),
            "gemini_integration": (
                "CONFIGURED" if config.is_gemini_configured() else "NOT_CONFIGURED"
            ),
            "gemini_model": config.get_model_name(),
            "firestore_integration": (
                "FIRESTORE_CONFIGURED" if backend == "firestore" else "LOCAL_ONLY"
            ),
            "synthetic_only_mode": True,
            "policy_gate": "ACTIVE",
        }

    @app.post("/api/incidents/analyze")
    def analyze(req: AnalyzeRequest) -> dict:
        _require_synthetic_id(req.asset_id, kind="asset_id")

        try:
            store.get_asset(req.asset_id)
        except AssetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        test_agent = get_agent()
        if test_agent is None and not config.is_gemini_configured():
            raise HTTPException(
                status_code=503,
                detail=(
                    "Gemini is not configured (no GOOGLE_API_KEY/GEMINI_API_KEY "
                    "and no Vertex AI project/location configured)."
                ),
            )

        analysis = agent_module.analyze_incident(req.asset_id, agent=test_agent)

        proposal = IncidentProposal(
            asset_id=analysis.asset_id,
            evidence_refs=analysis.evidence_refs,
            recommended_action=analysis.recommended_action,
            policy_class=analysis.policy_class,
            approval_required=analysis.approval_required,
            diagnosis=analysis.diagnosis,
            reasoning_summary=analysis.reasoning_summary,
        )
        pending_approval = approval.request_approval()
        incident_id = orchestrator.new_incident_id(req.asset_id)
        repo = _require_repository()

        blocked = False
        try:
            record = orchestrator.execute_action(
                proposal, pending_approval, incident_id=incident_id, repository=repo
            )
        except ExecutionBlockedError:
            blocked = True
            records = repo.list_audit_records(incident_id)
            record = records[-1]
        except RepositoryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        return {
            "incident_id": incident_id,
            "analysis": {
                "risk_score": analysis.risk_score,
                "risk_level": analysis.risk_level.value,
                "diagnosis": analysis.diagnosis,
                "uncertainties": analysis.uncertainties,
                "recommended_action": analysis.recommended_action,
                "policy_class": analysis.policy_class.value if analysis.policy_class else None,
                "approval_required": analysis.approval_required,
                "next_step": analysis.next_step,
            },
            "audit_record": _audit_record_to_dict(record),
            "blocked": blocked,
        }

    @app.post("/api/incidents/{incident_id}/approve")
    def approve_incident(incident_id: str, req: ApprovalRequest) -> dict:
        return _transition_approval(incident_id, req, action="approve")

    @app.post("/api/incidents/{incident_id}/reject")
    def reject_incident(incident_id: str, req: ApprovalRequest) -> dict:
        return _transition_approval(incident_id, req, action="reject")

    @app.post("/api/incidents/{incident_id}/execute")
    def execute_incident(incident_id: str) -> dict:
        _require_synthetic_id(incident_id, kind="incident_id")
        repo = _require_repository()

        incident = repo.get_incident(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail=f"Unknown incident_id: {incident_id!r}")

        approval_state = repo.get_approval_state(incident_id) or approval.request_approval()
        proposal = _proposal_from_incident(incident)

        try:
            record = orchestrator.execute_action(
                proposal, approval_state, incident_id=incident_id, repository=repo
            )
        except ExecutionBlockedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RepositoryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        return {"incident_id": incident_id, "audit_record": _audit_record_to_dict(record)}

    return app


# Cloud Run / uvicorn entrypoint target: `ai_raxbar_agent.web:app`. Building
# the app here only registers routes -- no Gemini/Firestore/network call
# happens as a side effect of importing this module.
app = create_app()
