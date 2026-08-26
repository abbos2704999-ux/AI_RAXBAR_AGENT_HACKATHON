"""Batch 3 human-approval workflow.

Wraps the existing `ApprovalState`/`ApprovalStatus` types (models.py) with a
tiny, explicit state machine: every request starts PENDING, and only an
explicit `approve()` or `reject()` call can move it to APPROVED/REJECTED.
There is no path here that skips PENDING, self-approves, or re-approves a
REJECTED request. This module never executes anything and never talks to a
network -- it only produces typed `ApprovalState` values for
`orchestrator.execute_action` (and, underneath that, `tools.simulate_remediation`)
to enforce.
"""

from __future__ import annotations

from dataclasses import replace

from .models import ApprovalState, ApprovalStatus


class ApprovalError(ValueError):
    """Raised on an invalid approval-state transition."""


def request_approval() -> ApprovalState:
    """Start a new approval request in PENDING state."""
    return ApprovalState(status=ApprovalStatus.PENDING)


def approve(approval: ApprovalState, approver: str, reason: str = "") -> ApprovalState:
    """Move a PENDING request to APPROVED. Never allowed from REJECTED."""
    if approval.status == ApprovalStatus.REJECTED:
        raise ApprovalError("Cannot approve a request that was already REJECTED.")
    if not approver:
        raise ApprovalError("An approver identity is required to approve an action.")
    return replace(
        approval,
        status=ApprovalStatus.APPROVED,
        approver=approver,
        reason=reason or approval.reason,
    )


def reject(approval: ApprovalState, approver: str, reason: str = "") -> ApprovalState:
    """Move a request to REJECTED. Allowed from PENDING or APPROVED (revoke)."""
    if not approver:
        raise ApprovalError("An approver identity is required to reject an action.")
    return replace(
        approval,
        status=ApprovalStatus.REJECTED,
        approver=approver,
        reason=reason or approval.reason,
    )
