"""Deterministic policy gate.

The policy gate decides -- by explicit code, never by LLM judgment -- whether
a proposed remediation action requires human approval before it can execute.
"""

from __future__ import annotations

from .models import ImpactClass, PolicyDecision

# Only HIGH_IMPACT actions require human approval in Batch 1. This is the one
# rule the hackathon spec calls out explicitly; LOW/MEDIUM impact actions are
# auto-clearable by policy.
_APPROVAL_REQUIRED_IMPACT_CLASSES = {ImpactClass.HIGH_IMPACT}


def evaluate_policy(action_type: str, impact_class: ImpactClass) -> PolicyDecision:
    """Classify an action's impact and decide whether approval is required.

    This function is pure and deterministic: same inputs, same decision.
    """
    requires_approval = impact_class in _APPROVAL_REQUIRED_IMPACT_CLASSES
    if requires_approval:
        rationale = (
            f"Action '{action_type}' is classified {impact_class.value}; "
            "policy requires explicit human approval before execution."
        )
    else:
        rationale = (
            f"Action '{action_type}' is classified {impact_class.value}; "
            "policy allows automatic execution without human approval."
        )
    return PolicyDecision(
        action_type=action_type,
        impact_class=impact_class,
        requires_human_approval=requires_approval,
        rationale=rationale,
    )
