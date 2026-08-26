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
