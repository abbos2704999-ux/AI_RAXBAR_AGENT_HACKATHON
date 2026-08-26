"""Tests for the deterministic rule-based risk engine."""

from __future__ import annotations

import copy

from ai_raxbar_agent.data_store import DataStore
from ai_raxbar_agent.risk_engine import assess_risk
from ai_raxbar_agent.models import RiskLevel


def test_risk_calculation_is_deterministic():
    store = DataStore()
    asset = store.get_asset("DEMO-TP-007")
    events = store.get_events("DEMO-TP-007")

    first = assess_risk(copy.deepcopy(asset), events)
    second = assess_risk(copy.deepcopy(asset), events)

    assert first.risk_score == second.risk_score
    assert first.risk_level == second.risk_level
    assert first.risk_factors == second.risk_factors
    assert first.evidence_refs == second.evidence_refs


def test_critical_star_asset_has_expected_score_and_level():
    store = DataStore()
    asset = store.get_asset("DEMO-TP-007")
    events = store.get_events("DEMO-TP-007")
    risk = assess_risk(asset, events)

    assert risk.risk_level == RiskLevel.CRITICAL
    assert risk.risk_score == 100  # capped; raw contributions exceed 100
    assert len(risk.risk_factors) >= 5


def test_normal_asset_has_no_risk_factors():
    store = DataStore()
    asset = store.get_asset("DEMO-TP-001")
    events = store.get_events("DEMO-TP-001")
    risk = assess_risk(asset, events)

    assert risk.risk_level == RiskLevel.NORMAL
    assert risk.risk_score == 0
    assert risk.risk_factors == []
    assert risk.evidence_refs == []


def test_evidence_refs_preserved_for_every_risk_factor():
    store = DataStore()
    for asset_id in store.list_asset_ids():
        asset = store.get_asset(asset_id)
        events = store.get_events(asset_id)
        risk = assess_risk(asset, events)
        # Every triggered factor contributes at least one evidence ref
        # (a matching event, or a synthetic signal reference).
        if risk.risk_factors:
            assert risk.evidence_refs
        else:
            assert risk.evidence_refs == []
        for ref in risk.evidence_refs:
            assert ref  # non-empty
            assert isinstance(ref, str)
