"""Deterministic, transparent, rule-based risk engine.

Every rule is explicit and testable. Given the same synthetic asset signals,
this engine always returns the same risk assessment. No model inference,
no network calls, no hidden state.

Conceptually inspired by the idea that "AI does not own the truth, evidence
does" -- but this is new code written for the hackathon, not a port of any
pre-existing system.
"""

from __future__ import annotations

from .models import Asset, Event, RiskAssessment, RiskLevel

# Maps each risk factor key to the event_type(s) in the synthetic event log
# that serve as evidence for that factor, when such events exist.
FACTOR_EVIDENCE_EVENT_TYPES: dict[str, tuple[str, ...]] = {
    "repeated_outages_warning": ("OUTAGE",),
    "repeated_outages_critical": ("OUTAGE",),
    "stale_telemetry": ("TELEMETRY_STALE",),
    "communication_loss": ("COMM_LOSS",),
    "topology_mismatch": ("TOPOLOGY_ALERT",),
    "overload_warning": ("OVERLOAD_ALERT",),
    "overload_critical": ("OVERLOAD_ALERT",),
    "unresolved_maintenance": ("MAINTENANCE_OPEN",),
    "repeated_field_complaints": ("FIELD_COMPLAINT",),
}

# Signals that each risk factor maps back to. Used to explain the factor and
# to drive synthetic remediation resets in tools.py.
FACTOR_SIGNAL_FIELDS: dict[str, str] = {
    "repeated_outages_warning": "repeated_outage_count",
    "repeated_outages_critical": "repeated_outage_count",
    "stale_telemetry": "telemetry_last_seen_minutes_ago",
    "communication_loss": "comm_status",
    "topology_mismatch": "topology_mismatch",
    "overload_warning": "load_ratio",
    "overload_critical": "load_ratio",
    "unresolved_maintenance": "open_maintenance_tickets",
    "repeated_field_complaints": "field_complaints_count",
}

_MAX_SCORE = 100

_OUTAGE_CRITICAL_THRESHOLD = 3
_OUTAGE_WARNING_THRESHOLD = 1
_TELEMETRY_STALE_MINUTES = 60
_OVERLOAD_CRITICAL_RATIO = 1.2
_OVERLOAD_WARNING_RATIO = 1.0
_MAINTENANCE_THRESHOLD = 2
_FIELD_COMPLAINTS_THRESHOLD = 3

_CRITICAL_LEVEL_MIN = 70
_HIGH_LEVEL_MIN = 40
_MEDIUM_LEVEL_MIN = 15


def _score_and_factors(asset: Asset) -> tuple[int, list[str]]:
    score = 0
    factors: list[str] = []

    if asset.repeated_outage_count >= _OUTAGE_CRITICAL_THRESHOLD:
        score += 25
        factors.append("repeated_outages_critical")
    elif asset.repeated_outage_count >= _OUTAGE_WARNING_THRESHOLD:
        score += 10
        factors.append("repeated_outages_warning")

    if asset.telemetry_last_seen_minutes_ago > _TELEMETRY_STALE_MINUTES:
        score += 15
        factors.append("stale_telemetry")

    if asset.comm_status == "LOST":
        score += 20
        factors.append("communication_loss")

    if asset.topology_mismatch:
        score += 20
        factors.append("topology_mismatch")

    if asset.load_ratio >= _OVERLOAD_CRITICAL_RATIO:
        score += 25
        factors.append("overload_critical")
    elif asset.load_ratio >= _OVERLOAD_WARNING_RATIO:
        score += 10
        factors.append("overload_warning")

    if asset.open_maintenance_tickets >= _MAINTENANCE_THRESHOLD:
        score += 10
        factors.append("unresolved_maintenance")

    if asset.field_complaints_count >= _FIELD_COMPLAINTS_THRESHOLD:
        score += 10
        factors.append("repeated_field_complaints")

    return min(score, _MAX_SCORE), factors


def _level_for_score(score: int) -> RiskLevel:
    if score >= _CRITICAL_LEVEL_MIN:
        return RiskLevel.CRITICAL
    if score >= _HIGH_LEVEL_MIN:
        return RiskLevel.HIGH
    if score >= _MEDIUM_LEVEL_MIN:
        return RiskLevel.MEDIUM
    return RiskLevel.NORMAL


def _evidence_refs_for_factors(
    factors: list[str], asset: Asset, events: list[Event]
) -> list[str]:
    refs: list[str] = []
    for factor in factors:
        event_types = FACTOR_EVIDENCE_EVENT_TYPES.get(factor, ())
        matched = [e.event_id for e in events if e.event_type in event_types]
        if matched:
            refs.extend(matched)
        else:
            field_name = FACTOR_SIGNAL_FIELDS.get(factor, factor)
            value = getattr(asset, field_name, None)
            refs.append(f"signal:{field_name}={value!r}")
    return refs


def assess_risk(asset: Asset, events: list[Event]) -> RiskAssessment:
    """Compute a deterministic risk assessment from synthetic evidence.

    Same asset signals + same events -> same result, every time.
    """
    score, factors = _score_and_factors(asset)
    level = _level_for_score(score)
    evidence_refs = _evidence_refs_for_factors(factors, asset, events)
    return RiskAssessment(
        asset_id=asset.asset_id,
        risk_score=score,
        risk_level=level,
        risk_factors=factors,
        evidence_refs=evidence_refs,
    )
