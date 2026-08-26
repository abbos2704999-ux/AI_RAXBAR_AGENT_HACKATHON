"""Batch 3 audit trail.

Local, offline, in-memory log of every incident's approval + action outcome.
Each record is a flat, JSON-serializable dict shaped like a future
Firestore document (`incident_id` as the document key), so swapping this
for a real Firestore-backed store later is a storage-layer change, not a
schema change. No network call is made from this module, and nothing here
writes to disk unless a caller explicitly opts in via `persist_path`.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AuditRecord:
    """One audit entry. Field set matches the spec:
    incident_id, asset_id, evidence_refs, proposed_action, policy_class,
    approval_status, action_status, before_state, after_state, risk_before,
    risk_after, verification_result, plus created_at/updated_at timestamps.
    """

    incident_id: str
    asset_id: str
    evidence_refs: list[str]
    proposed_action: Optional[str]
    policy_class: Optional[str]
    approval_status: str
    action_status: str
    before_state: dict
    after_state: dict
    risk_before: Optional[int]
    risk_after: Optional[int]
    verification_result: Optional[str]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        """Flat, JSON-safe dict -- the shape a Firestore document write
        would take, keyed by `incident_id`."""
        return asdict(self)


class AuditTrail:
    """In-memory audit log, optionally mirrored to a local JSONL file.

    Records are keyed by `incident_id`; re-recording the same `incident_id`
    (e.g. blocked-then-approved for the same incident) overwrites with the
    latest state, matching how a Firestore document update would behave.
    """

    def __init__(self, persist_path: Optional[Path] = None) -> None:
        self._records: dict[str, AuditRecord] = {}
        self._persist_path = persist_path
        self._lock = threading.Lock()
        if self._persist_path is not None:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, entry: AuditRecord) -> AuditRecord:
        with self._lock:
            self._records[entry.incident_id] = entry
            if self._persist_path is not None:
                with self._persist_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry.to_dict(), sort_keys=True) + "\n")
        return entry

    def get(self, incident_id: str) -> Optional[AuditRecord]:
        return self._records.get(incident_id)

    def list(self) -> list[AuditRecord]:
        return list(self._records.values())


# Module-level singleton, in-memory only (no disk writes) unless a caller
# constructs its own AuditTrail with an explicit persist_path.
audit_trail = AuditTrail()
