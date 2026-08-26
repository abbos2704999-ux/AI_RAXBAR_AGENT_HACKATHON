"""Offline, in-memory implementation of `IncidentRepository`.

No credentials, no network, no Google Cloud. This is the default
repository the orchestrator uses unless a caller explicitly supplies a
different `IncidentRepository` implementation (e.g. a real
`FirestoreRepository`), and it's what every offline test runs against.
"""

from __future__ import annotations

import threading
from typing import Optional

from .audit import AuditRecord
from .models import ApprovalState
from .repository import (
    CleanupResult,
    IncidentRecord,
    IncidentRepository,
    require_demo_incident_id,
)


def audit_record_key(record: AuditRecord) -> str:
    """Deterministic dedupe key: the same incident reaching the same
    lifecycle stage twice (e.g. a retried save) overwrites the same key
    instead of duplicating. A new lifecycle stage (e.g.
    BLOCKED_PENDING_APPROVAL -> EXECUTED) gets its own key, so the audit
    trail keeps full history rather than losing earlier stages."""
    return f"{record.incident_id}::{record.action_status}"


class LocalRepository(IncidentRepository):
    def __init__(self) -> None:
        self._incidents: dict[str, IncidentRecord] = {}
        self._approvals: dict[str, ApprovalState] = {}
        self._audit_records: dict[str, AuditRecord] = {}
        self._lock = threading.Lock()

    def save_incident(self, incident: IncidentRecord) -> None:
        with self._lock:
            existing = self._incidents.get(incident.incident_id)
            if existing is not None:
                # Idempotent retry: a re-save of the same incident_id keeps
                # the original creation time even if the caller passed a
                # fresh one.
                incident.created_at = existing.created_at
            self._incidents[incident.incident_id] = incident

    def get_incident(self, incident_id: str) -> Optional[IncidentRecord]:
        return self._incidents.get(incident_id)

    def save_audit_record(self, record: AuditRecord) -> None:
        with self._lock:
            self._audit_records[audit_record_key(record)] = record

    def list_audit_records(self, incident_id: Optional[str] = None) -> list[AuditRecord]:
        records = list(self._audit_records.values())
        if incident_id is not None:
            records = [r for r in records if r.incident_id == incident_id]
        return sorted(records, key=lambda r: r.created_at)

    def save_approval_state(self, incident_id: str, approval: ApprovalState) -> None:
        with self._lock:
            self._approvals[incident_id] = approval

    def get_approval_state(self, incident_id: str) -> Optional[ApprovalState]:
        return self._approvals.get(incident_id)

    def cleanup_incident(self, incident_id: str) -> CleanupResult:
        require_demo_incident_id(incident_id)
        with self._lock:
            incident_deleted = self._incidents.pop(incident_id, None) is not None
            approval_deleted = self._approvals.pop(incident_id, None) is not None
            matching_keys = [
                key
                for key, record in self._audit_records.items()
                if record.incident_id == incident_id
            ]
            for key in matching_keys:
                del self._audit_records[key]
        return CleanupResult(
            incident_id=incident_id,
            incident_deleted=incident_deleted,
            approval_deleted=approval_deleted,
            audit_records_deleted=len(matching_keys),
        )
