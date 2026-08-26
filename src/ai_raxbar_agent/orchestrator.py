"""Batch 3 orchestration: POLICY GATE -> HUMAN APPROVAL -> ACT (SIMULATED)
-> VERIFY -> AUDIT.

This module never talks to Gemini and never makes a network call. It picks
up exactly where the Batch 2 agent layer (`agent.analyze_incident`) stops:
a structured proposal (asset_id, evidence_refs, recommended_action,
policy_class, approval_required) plus an `ApprovalState`. It adds the next
links in the loop -- human approval and a controlled, synthetic-only action
execution -- without touching anything that decides risk or policy.

Freeze principle continued from Batch 1/2: this module never lets the
approval decision or the action outcome be anything other than what
deterministic code computes.  `tools.simulate_remediation` already refuses
to execute a HIGH_IMPACT action without an APPROVED `ApprovalState`;
`execute_action` below re-derives the same policy decision independently
and enforces the identical rule again *before* ever calling it (belt), and
even if that check were removed, `simulate_remediation` would still refuse
the call on its own (suspenders) -- see tools.py. There is no parameter or
code path here that can pass an approval bypass through to the write tool.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from . import tools as batch1_tools
from .audit import AuditRecord, AuditTrail, audit_trail as _default_audit_trail, utcnow_iso
from .models import ActionResult, ApprovalState, ApprovalStatus, ImpactClass
from .policy import evaluate_policy


class ExecutionBlockedError(RuntimeError):
    """Raised when the controlled executor refuses to run an action."""


@dataclass
class IncidentProposal:
    """Minimal structured shape this module needs to drive approval +
    execution -- the same fields `agent.IncidentAnalysis` (Batch 2) or an
    offline-mocked stand-in expose. Kept separate from `agent.IncidentAnalysis`
    so this module has no import-time dependency on google.adk/Gemini:
    the action-execution path must work with zero network libraries loaded.
    """

    asset_id: str
    evidence_refs: list[str]
    recommended_action: Optional[str]
    policy_class: Optional[ImpactClass]
    approval_required: bool
    diagnosis: str = ""
    reasoning_summary: str = ""


def new_incident_id(asset_id: str) -> str:
    return f"INC-{asset_id}-{uuid.uuid4().hex[:8]}"


def _record(
    *,
    incident_id: str,
    asset_id: str,
    evidence_refs: list[str],
    proposed_action: Optional[str],
    policy_class: Optional[str],
    approval_status: str,
    action_status: str,
    before_state: dict,
    after_state: dict,
    risk_before: Optional[int],
    risk_after: Optional[int],
    verification_result: Optional[str],
    created_at: str,
) -> AuditRecord:
    return AuditRecord(
        incident_id=incident_id,
        asset_id=asset_id,
        evidence_refs=list(evidence_refs),
        proposed_action=proposed_action,
        policy_class=policy_class,
        approval_status=approval_status,
        action_status=action_status,
        before_state=before_state,
        after_state=after_state,
        risk_before=risk_before,
        risk_after=risk_after,
        verification_result=verification_result,
        created_at=created_at,
        updated_at=utcnow_iso(),
    )


def execute_action(
    proposal: IncidentProposal,
    approval: ApprovalState,
    *,
    incident_id: Optional[str] = None,
    trail: Optional[AuditTrail] = None,
) -> AuditRecord:
    """The one controlled entry point from a proposal + approval decision to
    a synthetic action and an audit record.

    Every outcome -- including a blocked one -- is written to the audit
    trail before this function returns or raises, so a rejected/pending
    attempt is provably recorded, not silently dropped. Raises
    `ExecutionBlockedError` whenever policy blocks the action; the caller
    (e.g. an end-to-end test) can distinguish "blocked" from "executed" by
    catching that exception and/or reading `action_status` off the record.
    """
    trail = trail if trail is not None else _default_audit_trail
    incident_id = incident_id or new_incident_id(proposal.asset_id)
    created_at = utcnow_iso()

    if proposal.recommended_action is None:
        record = _record(
            incident_id=incident_id,
            asset_id=proposal.asset_id,
            evidence_refs=proposal.evidence_refs,
            proposed_action=None,
            policy_class=None,
            approval_status=approval.status.value,
            action_status="NO_ACTION_PROPOSED",
            before_state={},
            after_state={},
            risk_before=None,
            risk_after=None,
            verification_result=None,
            created_at=created_at,
        )
        return trail.record(record)

    # Independent re-derivation of the policy decision from the real
    # remediation template -- never trusts the caller-supplied
    # proposal.policy_class/approval_required for the actual gating
    # decision (those are only echoed into the audit record's context).
    template = batch1_tools.store.get_remediation_template(proposal.recommended_action)
    if template is None:
        record = _record(
            incident_id=incident_id,
            asset_id=proposal.asset_id,
            evidence_refs=proposal.evidence_refs,
            proposed_action=proposal.recommended_action,
            policy_class=None,
            approval_status=approval.status.value,
            action_status="UNKNOWN_ACTION_TYPE",
            before_state={},
            after_state={},
            risk_before=None,
            risk_after=None,
            verification_result=None,
            created_at=created_at,
        )
        trail.record(record)
        raise ExecutionBlockedError(
            f"Unknown remediation action_type: {proposal.recommended_action!r}"
        )

    policy_decision = evaluate_policy(proposal.recommended_action, template.impact_class)

    if policy_decision.requires_human_approval and approval.status != ApprovalStatus.APPROVED:
        blocked_status = (
            "BLOCKED_REJECTED"
            if approval.status == ApprovalStatus.REJECTED
            else "BLOCKED_PENDING_APPROVAL"
        )
        record = _record(
            incident_id=incident_id,
            asset_id=proposal.asset_id,
            evidence_refs=proposal.evidence_refs,
            proposed_action=proposal.recommended_action,
            policy_class=template.impact_class.value,
            approval_status=approval.status.value,
            action_status=blocked_status,
            before_state={},
            after_state={},
            risk_before=None,
            risk_after=None,
            verification_result=None,
            created_at=created_at,
        )
        trail.record(record)
        raise ExecutionBlockedError(
            f"Action {proposal.recommended_action!r} on {proposal.asset_id!r} is "
            f"{template.impact_class.value} and blocked: approval status is "
            f"{approval.status.value} (requires APPROVED)."
        )

    # Policy clears -- call the single controlled write tool. It re-checks
    # the exact same policy decision on its own and would refuse anyway if
    # this function's gate above were ever bypassed.
    result: ActionResult = batch1_tools.simulate_remediation(
        proposal.asset_id, proposal.recommended_action, approval=approval
    )

    if not result.success:
        record = _record(
            incident_id=incident_id,
            asset_id=proposal.asset_id,
            evidence_refs=proposal.evidence_refs,
            proposed_action=proposal.recommended_action,
            policy_class=template.impact_class.value,
            approval_status=approval.status.value,
            action_status="EXECUTION_FAILED",
            before_state={},
            after_state={},
            risk_before=None,
            risk_after=None,
            verification_result=result.error,
            created_at=created_at,
        )
        trail.record(record)
        raise ExecutionBlockedError(f"simulate_remediation refused: {result.error}")

    verification = result.verification
    record = _record(
        incident_id=incident_id,
        asset_id=proposal.asset_id,
        evidence_refs=proposal.evidence_refs,
        proposed_action=proposal.recommended_action,
        policy_class=template.impact_class.value,
        approval_status=approval.status.value,
        action_status="EXECUTED",
        before_state=verification.before_state if verification else {},
        after_state=verification.after_state if verification else {},
        risk_before=verification.risk_before.risk_score if verification else None,
        risk_after=verification.risk_after.risk_score if verification else None,
        verification_result=verification.verification_result if verification else None,
        created_at=created_at,
    )
    return trail.record(record)
