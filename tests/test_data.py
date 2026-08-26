"""Tests proving the synthetic data set is well-formed, complete, and safe."""

from __future__ import annotations

import re

from ai_raxbar_agent.data_store import DataStore
from ai_raxbar_agent.risk_engine import assess_risk
from ai_raxbar_agent.models import RiskLevel


def test_twelve_synthetic_assets_load():
    store = DataStore()
    assert len(store.list_asset_ids()) == 12


def test_no_duplicate_asset_ids():
    store = DataStore()
    ids = store.list_asset_ids()
    assert len(ids) == len(set(ids))


def test_all_required_risk_levels_represented():
    store = DataStore()
    levels_seen = set()
    for asset_id in store.list_asset_ids():
        asset = store.get_asset(asset_id)
        events = store.get_events(asset_id)
        levels_seen.add(assess_risk(asset, events).risk_level)
    assert levels_seen == {
        RiskLevel.NORMAL,
        RiskLevel.MEDIUM,
        RiskLevel.HIGH,
        RiskLevel.CRITICAL,
    }


def test_critical_scenario_with_multiple_independent_signals_exists():
    store = DataStore()
    found = False
    for asset_id in store.list_asset_ids():
        asset = store.get_asset(asset_id)
        events = store.get_events(asset_id)
        risk = assess_risk(asset, events)
        if risk.risk_level == RiskLevel.CRITICAL and len(risk.risk_factors) >= 3:
            found = True
            break
    assert found, "expected at least one CRITICAL asset with >= 3 independent risk factors"


def test_synthetic_data_contains_no_obvious_real_or_private_identifiers():
    store = DataStore()
    for asset_id in store.list_asset_ids():
        asset = store.get_asset(asset_id)
        assert asset_id.startswith("DEMO-TP-")
        assert "fictional" in asset.name.lower()
        assert "demo region" in asset.region.lower()
        assert "-DEMO" in asset.voltage_class

    # No plausible real-looking TP identifiers (e.g. "TP-1234" without the
    # DEMO- prefix) anywhere in the loaded asset data.
    real_looking_tp = re.compile(r"(?<!DEMO-)TP-\d")
    for asset_id in store.list_asset_ids():
        asset = store.get_asset(asset_id)
        blob = f"{asset.asset_id} {asset.name} {asset.region} {asset.voltage_class}"
        assert not real_looking_tp.search(blob)
