"""Typed domain tools.

Four read-only tools expose synthetic asset/risk/event/remediation data.
One controlled write tool, simulate_remediation, mutates only the local
in-memory demo state -- and only after the deterministic policy gate in
policy.py has cleared it. No tool here makes a network call.
"""

from __future__ import annotations

from typing import Optional

from .data_store import AssetNotFoundError, store
from .models import (
    ActionResult,
    ApprovalState,
    ApprovalStatus,
    Asset,
    Event,
    RemediationCandidate,
    RiskAssessment,
    VerificationResult,
)
from .policy import evaluate_policy
from .risk_engine import FACTOR_SIGNAL_FIELDS, assess_risk

# "Healthy" reset values applied to a signal field when a remediation action
# targeting that field's risk factor is successfully executed.
_HEALTHY_VALUES = {
    "repeated_outage_count": 0,
    "telemetry_last_seen_minutes_ago": 5,
    "comm_status": "OK",
    "topology_mismatch": False,
    "load_ratio": 0.8,
    "open_maintenance_tickets": 0,
    "field_complaints_count": 0,
}


def get_asset_context(asset_id: str) -> dict:
    """Read-only: return the asset's current synthetic state plus its
    deterministic risk assessment."""
    asset = store.get_asset(asset_id)
    events = store.get_events(asset_id)
    risk = assess_risk(asset, events)
    return {"asset": asset, "risk_assessment": risk}


def get_risk_evidence(asset_id: str) -> RiskAssessment:
    """Read-only: return the deterministic risk assessment (factors + evidence_refs)."""
    asset = store.get_asset(asset_id)
    events = store.get_events(asset_id)
    return assess_risk(asset, events)


def get_recent_events(asset_id: str, limit: int = 10) -> list[Event]:
    """Read-only: return the most recent synthetic events for an asset."""
    events = store.get_events(asset_id)
    return events[:limit]


def get_remediation_candidates(asset_id: str) -> list[RemediationCandidate]:
    """Read-only: return remediation templates applicable to the asset's
    currently active risk factors."""
    asset = store.get_asset(asset_id)
    events = store.get_events(asset_id)
    risk = assess_risk(asset, events)
    active_factors = set(risk.risk_factors)
    return [
        template
        for template in store.get_remediation_templates()
        if active_factors.intersection(template.targets)
    ]


def _apply_synthetic_effect(asset: Asset, targets: list[str]) -> None:
    fields = {FACTOR_SIGNAL_FIELDS[t] for t in targets if t in FACTOR_SIGNAL_FIELDS}
    for field_name in fields:
        setattr(asset, field_name, _HEALTHY_VALUES[field_name])


def simulate_remediation(
    asset_id: str,
    action_type: str,
    approval: Optional[ApprovalState] = None,
) -> ActionResult:
    """The single controlled write tool.

    Operates only on local, in-memory synthetic demo state. Cannot execute a
    HIGH_IMPACT action without a passed-in ApprovalState whose status is
    APPROVED -- that decision is made by policy.py, never by this function's
    caller and never by an LLM.
    """
    try:
        asset = store.get_asset(asset_id)
    except AssetNotFoundError as exc:
        return ActionResult(
            success=False,
            asset_id=asset_id,
            action_type=action_type,
            message="Action rejected: unknown asset.",
            error=str(exc),
        )

    template = store.get_remediation_template(action_type)
    if template is None:
        return ActionResult(
            success=False,
            asset_id=asset_id,
            action_type=action_type,
            message="Action rejected: unknown action_type.",
            error=f"Unknown synthetic action_type: {action_type!r}",
        )

    policy_decision = evaluate_policy(action_type, template.impact_class)
    if policy_decision.requires_human_approval:
        if approval is None or approval.status != ApprovalStatus.APPROVED:
            return ActionResult(
                success=False,
                asset_id=asset_id,
                action_type=action_type,
                message="Action blocked by policy gate: human approval required.",
                error="HUMAN_APPROVAL_REQUIRED",
            )

    events = store.get_events(asset_id)
    risk_before = assess_risk(asset, events)
    before_state = asset.signal_snapshot()

    _apply_synthetic_effect(asset, template.targets)

    risk_after = assess_risk(asset, events)
    after_state = asset.signal_snapshot()

    if risk_after.risk_score < risk_before.risk_score:
        verification_label = "IMPROVED"
        passed = True
    elif risk_after.risk_score == risk_before.risk_score:
        verification_label = "NO_CHANGE"
        passed = False
    else:
        verification_label = "WORSENED"
        passed = False

    verification = VerificationResult(
        asset_id=asset_id,
        action_type=action_type,
        before_state=before_state,
        after_state=after_state,
        risk_before=risk_before,
        risk_after=risk_after,
        verification_result=verification_label,
        passed=passed,
    )

    return ActionResult(
        success=True,
        asset_id=asset_id,
        action_type=action_type,
        message=f"Simulated action '{action_type}' executed on {asset_id}.",
        verification=verification,
    )
