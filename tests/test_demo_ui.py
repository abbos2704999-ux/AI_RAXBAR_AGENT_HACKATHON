"""Batch 5E: offline tests for the judge-facing demo page (`GET /demo`) and
the deterministic "evidence" enrichment `POST /api/incidents/analyze` gained
to support it.

Everything here uses `TestClient` against the in-process ASGI app -- no
socket, no real network call, no live Gemini/Firestore. The demo page's
JavaScript itself is not executed (no headless browser here); these tests
instead prove: the page is served correctly and contains no secrets, its
JS element references are internally consistent with the markup (catches
id typos statically), and the backend JSON it depends on carries real,
non-fabricated deterministic values.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from ai_raxbar_agent import agent, tools, web
from ai_raxbar_agent.data_store import store

from fakes import ScriptedFakeLlm


@pytest.fixture(autouse=True)
def _reset_state():
    store.reset()
    web.set_test_agent_override(None)
    yield
    store.reset()
    web.set_test_agent_override(None)


@pytest.fixture
def client():
    return TestClient(web.app)


def _script(asset_id, recommended_action, cited_evidence_refs):
    return [
        {"call": "get_asset_context", "args": {"asset_id": asset_id}},
        {"call": "get_recent_events", "args": {"asset_id": asset_id, "limit": 10}},
        {"call": "get_risk_evidence", "args": {"asset_id": asset_id}},
        {"call": "get_remediation_candidates", "args": {"asset_id": asset_id}},
        {
            "call": "propose_incident_analysis",
            "args": {
                "diagnosis": "Synthetic diagnosis for demo-UI evidence test.",
                "reasoning_summary": "Synthetic reasoning summary.",
                "recommended_action": recommended_action,
                "uncertainties": [],
                "cited_evidence_refs": cited_evidence_refs,
            },
        },
        {"text": "Analysis submitted."},
    ]


def _install_fake_agent(asset_id: str, recommended_action: str) -> None:
    real_risk = tools.get_risk_evidence(asset_id)
    fake_llm = ScriptedFakeLlm(script=_script(asset_id, recommended_action, real_risk.evidence_refs))
    web.set_test_agent_override(agent.build_agent(model=fake_llm))


# ---------------------------------------------------------------------------
# GET /demo
# ---------------------------------------------------------------------------


def test_demo_page_loads_offline(client):
    resp = client.get("/demo")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]

    body = resp.text
    for marker in (
        "AI RAXBAR",
        "SYNTHETIC DEMO",
        "LIVE GOOGLE CLOUD BACKEND",
        "DEMO-TP-007",
        "DETERMINISTIC EVIDENCE",
        "AI DOES NOT OWN THE TRUTH",
        "GEMINI 3.5 DIAGNOSIS",
        "HUMAN APPROVAL",
        "SIMULATED ACTION",
        "SIMULATION",
        "NO REAL GRID CONTROL",
        "AUDIT TRAIL",
        "RUN LIVE ANALYSIS",
    ):
        assert marker in body, f"missing demo-page marker: {marker!r}"


def test_demo_page_has_no_secrets_or_credentials(client):
    # Matches tests/test_repo_safety.py's intent: catch actual secret
    # *material* (a key value, a service-account blob), not the word
    # "credential"/"secret" appearing in benign prose (the page legitimately
    # says things like "no Gemini credential" when reporting live status).
    body = client.get("/demo").text
    assert "AIza" not in body  # Google API key prefix
    assert "ai-raxbar-agent-hackathon" not in body  # real GCP project id
    assert not re.search(r'-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----', body)
    assert not re.search(r'"type"\s*:\s*"service_account"', body)
    assert not re.search(
        r"""(?ix)
        \b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password)
        \s*[:=]\s*
        ['"][A-Za-z0-9/_\-.]{8,}['"]
        """,
        body,
    )


def test_demo_page_never_asserts_a_real_grid_command():
    body = (
        web._STATIC_DIR / "demo.html"  # noqa: SLF001 -- reading the same source the app serves
    ).read_text(encoding="utf-8")
    assert "SIMULATION" in body
    assert "NO REAL GRID CONTROL" in body
    assert "real electrical" not in body.lower()


def test_demo_page_js_element_ids_are_consistent():
    """Every `$("some-id")` lookup in the page's inline script must resolve
    to an `id="some-id"` present in the markup -- a static proxy for "the
    JS won't crash on a typo'd element id" without needing a real browser.
    """
    body = (web._STATIC_DIR / "demo.html").read_text(encoding="utf-8")  # noqa: SLF001

    referenced_ids = set(re.findall(r'\$\("([a-zA-Z][\w-]*)"\)', body))
    referenced_ids |= set(re.findall(r"getElementById\(\"([a-zA-Z][\w-]*)\"\)", body))
    assert referenced_ids, "expected at least one $(id) reference in the demo page"

    declared_ids = set(re.findall(r'id="([a-zA-Z][\w-]*)"', body))

    missing = referenced_ids - declared_ids
    assert not missing, f"JS references element id(s) not present in markup: {sorted(missing)}"


# ---------------------------------------------------------------------------
# Deterministic evidence enrichment on POST /api/incidents/analyze.
# ---------------------------------------------------------------------------


def test_analyze_response_includes_real_deterministic_evidence_for_ui(client):
    _install_fake_agent("DEMO-TP-007", "REBALANCE_LOAD")
    real_risk = tools.get_risk_evidence("DEMO-TP-007")

    resp = client.post("/api/incidents/analyze", json={"asset_id": "DEMO-TP-007"})
    assert resp.status_code == 200
    body = resp.json()

    assert "evidence" in body
    ev = body["evidence"]

    # risk_factors/evidence_refs must match the real deterministic risk
    # engine's output exactly -- not anything the model asserted or the UI
    # fabricated.
    assert ev["risk_factors"] == real_risk.risk_factors
    assert set(ev["evidence_refs"]) == set(real_risk.evidence_refs)
    assert len(ev["evidence_refs"]) == 14  # known DEMO-TP-007 baseline

    assert isinstance(ev["recent_events"], list) and ev["recent_events"]
    for event in ev["recent_events"]:
        assert {"event_id", "asset_id", "event_type", "timestamp", "description", "severity"} <= set(
            event.keys()
        )
        assert event["asset_id"] == "DEMO-TP-007"

    assert ev["asset_state"] == store.get_asset("DEMO-TP-007").signal_snapshot()

    # Original Batch 5A response shape is untouched by this additive field.
    assert body["analysis"]["risk_score"] == real_risk.risk_score
    assert body["audit_record"]["action_status"] == "BLOCKED_PENDING_APPROVAL"


def test_evidence_panel_data_present_even_for_low_impact_auto_executed_action(client):
    _install_fake_agent("DEMO-TP-003", "DISPATCH_SYNTHETIC_INSPECTION")

    resp = client.post("/api/incidents/analyze", json={"asset_id": "DEMO-TP-003"})
    assert resp.status_code == 200
    ev = resp.json()["evidence"]
    assert ev["evidence_refs"]
    assert ev["asset_state"]
