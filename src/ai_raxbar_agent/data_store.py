"""Loads synthetic demo data and holds the in-memory "live" demo state.

Everything here is local and offline: JSON files under data/ are read from
disk once, and a deep-copied mutable working set is kept in memory so that
simulate_remediation() can mutate synthetic asset signals without ever
touching a network, a database, or the on-disk baseline files.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from .models import Asset, Event, ImpactClass, RemediationCandidate

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_ASSETS_FILE = _DATA_DIR / "synthetic_assets.json"
_EVENTS_FILE = _DATA_DIR / "synthetic_events.json"
_REMEDIATION_FILE = _DATA_DIR / "synthetic_remediation.json"


class AssetNotFoundError(Exception):
    """Raised when a requested asset_id does not exist in the synthetic data set."""


def _load_assets_baseline() -> dict[str, Asset]:
    with _ASSETS_FILE.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    assets: dict[str, Asset] = {}
    for entry in raw:
        asset = Asset(**entry)
        if asset.asset_id in assets:
            raise ValueError(f"Duplicate asset_id in synthetic data: {asset.asset_id}")
        assets[asset.asset_id] = asset
    return assets


def _load_events_baseline() -> dict[str, list[Event]]:
    with _EVENTS_FILE.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    events_by_asset: dict[str, list[Event]] = {}
    for entry in raw:
        event = Event(**entry)
        events_by_asset.setdefault(event.asset_id, []).append(event)
    for events in events_by_asset.values():
        events.sort(key=lambda e: e.timestamp, reverse=True)
    return events_by_asset


def _load_remediation_templates() -> list[RemediationCandidate]:
    with _REMEDIATION_FILE.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    templates: list[RemediationCandidate] = []
    for entry in raw:
        templates.append(
            RemediationCandidate(
                action_type=entry["action_type"],
                description=entry["description"],
                targets=list(entry["targets"]),
                impact_class=ImpactClass(entry["impact_class"]),
                estimated_risk_reduction=entry["estimated_risk_reduction"],
            )
        )
    return templates


class DataStore:
    """Holds the synthetic baseline data and a mutable in-memory demo copy."""

    def __init__(self) -> None:
        self._assets_baseline = _load_assets_baseline()
        self._events = _load_events_baseline()
        self._remediation_templates = _load_remediation_templates()
        self._assets_live: dict[str, Asset] = copy.deepcopy(self._assets_baseline)

    def reset(self) -> None:
        """Restore live demo state to the on-disk synthetic baseline."""
        self._assets_live = copy.deepcopy(self._assets_baseline)

    def list_asset_ids(self) -> list[str]:
        return list(self._assets_baseline.keys())

    def get_asset(self, asset_id: str) -> Asset:
        try:
            return self._assets_live[asset_id]
        except KeyError as exc:
            raise AssetNotFoundError(f"Unknown synthetic asset_id: {asset_id!r}") from exc

    def get_events(self, asset_id: str) -> list[Event]:
        if asset_id not in self._assets_baseline:
            raise AssetNotFoundError(f"Unknown synthetic asset_id: {asset_id!r}")
        return list(self._events.get(asset_id, []))

    def get_remediation_templates(self) -> list[RemediationCandidate]:
        return list(self._remediation_templates)

    def get_remediation_template(self, action_type: str) -> RemediationCandidate | None:
        for template in self._remediation_templates:
            if template.action_type == action_type:
                return template
        return None


# Module-level singleton used by the tools layer. Batch 1 is a single-process
# offline demo, so one shared in-memory store is sufficient.
store = DataStore()
