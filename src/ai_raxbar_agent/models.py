"""Typed domain models for the AI Raxbar Agent Batch 1 foundation.

All data flowing through these models is synthetic/demo data. Nothing here
talks to a network, a database, or a real utility system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RiskLevel(str, Enum):
    NORMAL = "NORMAL"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ImpactClass(str, Enum):
    LOW_IMPACT = "LOW_IMPACT"
    MEDIUM_IMPACT = "MEDIUM_IMPACT"
    HIGH_IMPACT = "HIGH_IMPACT"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass
class Asset:
    """A synthetic electrical-grid asset and its current telemetry/state signals."""

    asset_id: str
    name: str
    asset_type: str
    region: str
    voltage_class: str
    install_year: int

    # Risk-relevant signals (all synthetic).
    repeated_outage_count: int
    telemetry_last_seen_minutes_ago: int
    comm_status: str  # "OK" | "LOST"
    topology_mismatch: bool
    load_ratio: float
    open_maintenance_tickets: int
    field_complaints_count: int

    def signal_snapshot(self) -> dict:
        return {
            "repeated_outage_count": self.repeated_outage_count,
            "telemetry_last_seen_minutes_ago": self.telemetry_last_seen_minutes_ago,
            "comm_status": self.comm_status,
            "topology_mismatch": self.topology_mismatch,
            "load_ratio": self.load_ratio,
            "open_maintenance_tickets": self.open_maintenance_tickets,
            "field_complaints_count": self.field_complaints_count,
        }


@dataclass
class Event:
    """A synthetic event/signal record tied to an asset."""

    event_id: str
    asset_id: str
    event_type: str
    timestamp: str
    description: str
    severity: str


@dataclass
class RiskAssessment:
    """Deterministic, reproducible risk output for a single asset."""

    asset_id: str
    risk_score: int
    risk_level: RiskLevel
    risk_factors: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)


@dataclass
class RemediationCandidate:
    """A synthetic remediation action template."""

    action_type: str
    description: str
    targets: list[str]
    impact_class: ImpactClass
    estimated_risk_reduction: int


@dataclass
class PolicyDecision:
    """Deterministic policy-gate output. The LLM never makes this decision."""

    action_type: str
    impact_class: ImpactClass
    requires_human_approval: bool
    rationale: str


@dataclass
class ApprovalState:
    """Typed representation of human-approval state (no UI in Batch 1)."""

    status: ApprovalStatus = ApprovalStatus.PENDING
    approver: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class VerificationResult:
    """Proof that a simulated action produced a measurable, deterministic change."""

    asset_id: str
    action_type: str
    before_state: dict
    after_state: dict
    risk_before: RiskAssessment
    risk_after: RiskAssessment
    verification_result: str  # "IMPROVED" | "NO_CHANGE" | "WORSENED"
    passed: bool


@dataclass
class ActionResult:
    """Result of calling the single controlled write tool: simulate_remediation."""

    success: bool
    asset_id: str
    action_type: str
    message: str
    verification: Optional[VerificationResult] = None
    error: Optional[str] = None
