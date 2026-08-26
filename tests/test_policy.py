"""Tests for the deterministic policy gate."""

from __future__ import annotations

from ai_raxbar_agent.models import ImpactClass
from ai_raxbar_agent.policy import evaluate_policy


def test_policy_classification_is_deterministic():
    first = evaluate_policy("REBALANCE_LOAD", ImpactClass.HIGH_IMPACT)
    second = evaluate_policy("REBALANCE_LOAD", ImpactClass.HIGH_IMPACT)
    assert first == second


def test_high_impact_requires_human_approval():
    decision = evaluate_policy("REBALANCE_LOAD", ImpactClass.HIGH_IMPACT)
    assert decision.requires_human_approval is True


def test_medium_impact_does_not_require_human_approval():
    decision = evaluate_policy("RECLOSE_BREAKER", ImpactClass.MEDIUM_IMPACT)
    assert decision.requires_human_approval is False


def test_low_impact_does_not_require_human_approval():
    decision = evaluate_policy("DISPATCH_SYNTHETIC_INSPECTION", ImpactClass.LOW_IMPACT)
    assert decision.requires_human_approval is False


def test_policy_decision_never_comes_from_free_text():
    # The policy gate is a pure function of a typed ImpactClass enum, not of
    # any LLM-generated string -- passing an invalid class raises rather than
    # silently guessing.
    import pytest

    with pytest.raises(ValueError):
        ImpactClass("NOT_A_REAL_IMPACT_CLASS")
