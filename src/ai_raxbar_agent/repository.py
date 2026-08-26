"""Batch 4 persistence interface: a Firestore-compatible repository
abstraction for incident/approval/audit workflow state.

`orchestrator.py` depends only on `IncidentRepository` (this ABC), never on
a concrete storage SDK. `local_repository.LocalRepository` is the default,
offline, in-memory implementation used by every test and by any caller that
hasn't opted into a real backend. `firestore_repository.FirestoreRepository`
is a same-interface adapter for real Google Cloud Firestore, used only when
a caller explicitly constructs one with an already-authenticated client --
it is never wired in automatically.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from .audit import AuditRecord
from .models import ApprovalState


@dataclass
class IncidentRecord:
    """The persisted, current-state projection of one incident, spanning
    ANALYSIS -> POLICY -> APPROVAL -> ACTION -> VERIFICATION. This is the
    document shape written to the `incidents` Firestore collection
    (document id = incident_id).

    `diagnosis` is the model's short, user-facing diagnosis text only (the
    `diagnosis` field `agent.propose_incident_analysis` defines) -- never
    raw model chain-of-thought. This codebase never captures or exposes
    chain-of-thought in the first place: the ADK structured-output tool
    call only ever carries the narrative fields defined on
    `propose_incident_analysis` (diagnosis, reasoning_summary,
    uncertainties), so there is nothing else to accidentally persist here.
    """

    incident_id: str
    asset_id: str
    detected_at: str
    evidence_refs: list[str]
    diagnosis: str
    recommended_action: Optional[str]
    policy_class: Optional[str]
    approval_required: bool
    approval_status: str
    approved_by: Optional[str]
    action_status: str
    risk_before: Optional[int]
    risk_after: Optional[int]
    verification_result: Optional[str]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        """Flat, JSON/Firestore-safe dict -- the exact document shape a
        Firestore write would take."""
        return {
            "incident_id": self.incident_id,
            "asset_id": self.asset_id,
            "detected_at": self.detected_at,
            "evidence_refs": list(self.evidence_refs),
            "diagnosis": self.diagnosis,
            "recommended_action": self.recommended_action,
            "policy_class": self.policy_class,
            "approval_required": self.approval_required,
            "approval_status": self.approval_status,
            "approved_by": self.approved_by,
            "action_status": self.action_status,
            "risk_before": self.risk_before,
            "risk_after": self.risk_after,
            "verification_result": self.verification_result,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


_DEMO_CLEANUP_PREFIXES = ("HACKATHON-SMOKE-", "DEMO-")


class CleanupNotAllowedError(ValueError):
    """Raised when `cleanup_incident` is asked to delete an `incident_id`
    that doesn't look like synthetic/demo data.

    `cleanup_incident` is a narrow, opt-in path for removing the handful of
    documents a controlled Firestore smoke test writes -- it is not, and
    must never become, a general production deletion mechanism. Refusing
    anything that doesn't obviously look disposable is the whole point.
    """


def is_demo_incident_id(incident_id: str) -> bool:
    """True if `incident_id` looks like synthetic/demo data safe for
    `cleanup_incident` to delete: it (optionally after the orchestrator's
    `INC-` prefix, e.g. `INC-DEMO-TP-007-a1b2c3d4`) starts with an explicit
    demo/smoke-test marker such as `HACKATHON-SMOKE-` or `DEMO-`. Anything
    else is refused."""
    if not isinstance(incident_id, str) or not incident_id:
        return False
    candidate = incident_id[len("INC-") :] if incident_id.startswith("INC-") else incident_id
    return any(candidate.startswith(prefix) for prefix in _DEMO_CLEANUP_PREFIXES)


def require_demo_incident_id(incident_id: str) -> None:
    """Raises `CleanupNotAllowedError` unless `is_demo_incident_id` is
    True. Every `cleanup_incident` implementation must call this before
    touching any storage backend."""
    if not is_demo_incident_id(incident_id):
        raise CleanupNotAllowedError(
            f"Refusing to clean up {incident_id!r}: cleanup_incident only "
            f"accepts synthetic/demo incident_ids starting with one of "
            f"{_DEMO_CLEANUP_PREFIXES!r} (optionally after an 'INC-' "
            "prefix). This is not a production deletion mechanism."
        )


@dataclass
class CleanupResult:
    """What `cleanup_incident` actually removed. All-False/zero on a
    second call for the same `incident_id` -- cleanup is idempotent, not
    an error, to delete something that's already gone."""

    incident_id: str
    incident_deleted: bool
    approval_deleted: bool
    audit_records_deleted: int


class RepositoryError(RuntimeError):
    """Raised by a repository implementation when a save/read fails.

    Callers (`orchestrator.execute_action`) must treat this as a
    fail-closed signal: a persistence failure never implies an approval or
    an executed action. Because `execute_action` persists the incident and
    approval state *before* checking the policy gate or calling the write
    tool, a `RepositoryError` raised at that point propagates and aborts
    the call -- `tools.simulate_remediation` is never reached.
    """


class IncidentRepository(ABC):
    """Storage-agnostic interface for incident/approval/audit workflow
    state. The orchestrator depends only on this ABC, never on a concrete
    SDK -- see `local_repository.LocalRepository` (offline default) and
    `firestore_repository.FirestoreRepository` (real-backend adapter)."""

    @abstractmethod
    def save_incident(self, incident: IncidentRecord) -> None: ...

    @abstractmethod
    def get_incident(self, incident_id: str) -> Optional[IncidentRecord]: ...

    @abstractmethod
    def save_audit_record(self, record: AuditRecord) -> None: ...

    @abstractmethod
    def list_audit_records(self, incident_id: Optional[str] = None) -> list[AuditRecord]: ...

    @abstractmethod
    def save_approval_state(self, incident_id: str, approval: ApprovalState) -> None: ...

    @abstractmethod
    def get_approval_state(self, incident_id: str) -> Optional[ApprovalState]: ...

    @abstractmethod
    def cleanup_incident(self, incident_id: str) -> CleanupResult:
        """Narrow, opt-in deletion of exactly one incident's data --
        `incidents/{incident_id}`, `approvals/{incident_id}`, and every
        `audit_records` entry whose `incident_id` matches. Every
        implementation MUST call `require_demo_incident_id(incident_id)`
        before deleting anything, MUST scope every delete to that exact
        `incident_id` (no collection-wide/unbounded delete), and MUST be
        safe to call again on an already-cleaned-up incident_id (returns
        all-False/zero, does not raise). This exists only for controlled
        synthetic smoke-test cleanup -- it is not a general-purpose or
        production deletion API.
        """
        ...
