"""Firestore-compatible adapter for `IncidentRepository`.

Same interface as `local_repository.LocalRepository`, backed by real
Google Cloud Firestore collections (`incidents`, `approvals`,
`audit_records`) when constructed against a real client. Includes
`cleanup_incident` for removing the documents a controlled synthetic
smoke test writes (see `repository.require_demo_incident_id`) -- this is
narrow, opt-in test cleanup, not a general or production deletion API.

Safety properties:

- This module never imports `google.cloud.firestore` at module import
  time -- only inside `build_live_client()`, and only when that function is
  actually called. Importing or instantiating `FirestoreRepository` itself
  never touches the network and never requires the `google-cloud-firestore`
  package to be installed, which is why the offline test suite can exercise
  this adapter fully (against a fake client) without that dependency.
- `FirestoreRepository.__init__` never constructs a client itself -- the
  caller must pass one in, already authenticated. Credentials come only
  from the standard Google Cloud authentication chain (Application Default
  Credentials / environment), exactly like `config.py`'s Gemini
  configuration; no credential value or project id is hardcoded anywhere in
  this file.
- Nothing in this repository (module, test suite, or any other file)
  constructs a real Firestore client or calls `build_live_client()`. That
  remains a manual, opt-in action for a human, mirroring
  `scripts/smoke_test_gemini.py`'s posture for Gemini.
"""

from __future__ import annotations

from typing import Any, Optional

from .audit import AuditRecord
from .models import ApprovalState, ApprovalStatus
from .repository import (
    CleanupResult,
    IncidentRecord,
    IncidentRepository,
    RepositoryError,
    require_demo_incident_id,
)

INCIDENTS_COLLECTION = "incidents"
APPROVALS_COLLECTION = "approvals"
AUDIT_RECORDS_COLLECTION = "audit_records"


def _audit_record_doc_id(record: AuditRecord) -> str:
    return f"{record.incident_id}::{record.action_status}"


def build_live_client(project: Optional[str] = None) -> Any:
    """Manually, explicitly construct a real `google.cloud.firestore.Client`
    using standard Google Cloud authentication (Application Default
    Credentials, or `project`/env if provided). Never called automatically
    by this module, the orchestrator, or any test -- a human/operator opts
    into this the same way `scripts/smoke_test_gemini.py` opts into a live
    Gemini call. Lazily imports `google.cloud.firestore` here, not at
    module scope, so nothing about importing this module requires the
    package or touches the network.
    """
    from google.cloud import firestore  # noqa: PLC0415 -- intentional lazy import

    return firestore.Client(project=project) if project else firestore.Client()


class FirestoreRepository(IncidentRepository):
    """Adapter over a Firestore-like client.

    `client` must already be constructed and authenticated by the caller
    (e.g. via `build_live_client()`) -- this class never builds one itself.
    Any object exposing `.collection(name).document(id).set(dict)` /
    `.get()` (returning something with `.exists` and `.to_dict()`) and
    `.collection(name).stream()` works, real Firestore client or fake.
    """

    def __init__(self, client: Any) -> None:
        if client is None:
            raise ValueError(
                "FirestoreRepository requires an already-constructed client "
                "(e.g. from build_live_client()); it never creates one "
                "implicitly."
            )
        self._client = client

    # -- incidents -----------------------------------------------------

    def save_incident(self, incident: IncidentRecord) -> None:
        try:
            doc_ref = self._client.collection(INCIDENTS_COLLECTION).document(incident.incident_id)
            existing_snapshot = doc_ref.get()
            existing = (
                existing_snapshot.to_dict()
                if existing_snapshot is not None and existing_snapshot.exists
                else None
            )
            payload = incident.to_dict()
            if existing:
                # Idempotent retry: preserve original creation time.
                payload["created_at"] = existing.get("created_at", payload["created_at"])
            doc_ref.set(payload)
        except Exception as exc:  # noqa: BLE001 -- any backend failure must
            # surface as a typed, catchable RepositoryError so callers fail
            # closed instead of crashing unpredictably or silently treating
            # a failed write as a successful one.
            raise RepositoryError(
                f"Failed to save incident {incident.incident_id!r}: {exc}"
            ) from exc

    def get_incident(self, incident_id: str) -> Optional[IncidentRecord]:
        try:
            snapshot = self._client.collection(INCIDENTS_COLLECTION).document(incident_id).get()
        except Exception as exc:  # noqa: BLE001
            raise RepositoryError(f"Failed to read incident {incident_id!r}: {exc}") from exc
        if snapshot is None or not snapshot.exists:
            return None
        return IncidentRecord(**snapshot.to_dict())

    # -- audit records ---------------------------------------------------

    def save_audit_record(self, record: AuditRecord) -> None:
        try:
            doc_id = _audit_record_doc_id(record)
            self._client.collection(AUDIT_RECORDS_COLLECTION).document(doc_id).set(record.to_dict())
        except Exception as exc:  # noqa: BLE001
            raise RepositoryError(
                f"Failed to save audit record for incident {record.incident_id!r}: {exc}"
            ) from exc

    def list_audit_records(self, incident_id: Optional[str] = None) -> list[AuditRecord]:
        try:
            docs = list(self._client.collection(AUDIT_RECORDS_COLLECTION).stream())
        except Exception as exc:  # noqa: BLE001
            raise RepositoryError(f"Failed to list audit records: {exc}") from exc
        records = [AuditRecord(**doc.to_dict()) for doc in docs]
        if incident_id is not None:
            records = [r for r in records if r.incident_id == incident_id]
        return sorted(records, key=lambda r: r.created_at)

    # -- approvals ---------------------------------------------------

    def save_approval_state(self, incident_id: str, approval: ApprovalState) -> None:
        try:
            payload = {
                "incident_id": incident_id,
                "status": approval.status.value,
                "approver": approval.approver,
                "reason": approval.reason,
            }
            self._client.collection(APPROVALS_COLLECTION).document(incident_id).set(payload)
        except Exception as exc:  # noqa: BLE001
            raise RepositoryError(
                f"Failed to save approval state for incident {incident_id!r}: {exc}"
            ) from exc

    def get_approval_state(self, incident_id: str) -> Optional[ApprovalState]:
        try:
            snapshot = self._client.collection(APPROVALS_COLLECTION).document(incident_id).get()
        except Exception as exc:  # noqa: BLE001
            raise RepositoryError(
                f"Failed to read approval state for {incident_id!r}: {exc}"
            ) from exc
        if snapshot is None or not snapshot.exists:
            return None
        data = snapshot.to_dict()
        return ApprovalState(
            status=ApprovalStatus(data["status"]),
            approver=data.get("approver"),
            reason=data.get("reason"),
        )

    # -- cleanup (synthetic/demo smoke-test data only) ------------------

    def cleanup_incident(self, incident_id: str) -> CleanupResult:
        """Deletes exactly `incidents/{incident_id}`,
        `approvals/{incident_id}`, and every `audit_records` document whose
        `incident_id` field matches -- nothing else. Never issues a
        collection-wide/unbounded delete: the audit-records deletion is
        scoped by a `where("incident_id", "==", incident_id)` query, and
        each match is deleted individually by its own document reference.
        This is a narrow smoke-test cleanup path, not a production
        deletion API -- `require_demo_incident_id` refuses anything that
        doesn't look like synthetic/demo data before any delete is issued.
        """
        require_demo_incident_id(incident_id)
        try:
            incident_ref = self._client.collection(INCIDENTS_COLLECTION).document(incident_id)
            incident_existed = incident_ref.get().exists
            if incident_existed:
                incident_ref.delete()

            approval_ref = self._client.collection(APPROVALS_COLLECTION).document(incident_id)
            approval_existed = approval_ref.get().exists
            if approval_existed:
                approval_ref.delete()

            audit_records_deleted = 0
            matches = (
                self._client.collection(AUDIT_RECORDS_COLLECTION)
                .where("incident_id", "==", incident_id)
                .stream()
            )
            for snapshot in matches:
                snapshot.reference.delete()
                audit_records_deleted += 1

            return CleanupResult(
                incident_id=incident_id,
                incident_deleted=incident_existed,
                approval_deleted=approval_existed,
                audit_records_deleted=audit_records_deleted,
            )
        except Exception as exc:  # noqa: BLE001 -- any backend failure must
            # surface as a typed, catchable RepositoryError rather than a
            # partial, silent cleanup.
            raise RepositoryError(f"Failed to clean up incident {incident_id!r}: {exc}") from exc
