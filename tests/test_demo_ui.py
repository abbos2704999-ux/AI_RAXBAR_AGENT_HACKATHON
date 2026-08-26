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
from ai_raxbar_agent.models import ApprovalState, ApprovalStatus

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


# ---------------------------------------------------------------------------
# Batch 5G regression tests.
#
# A live demo run showed risk=85/CRITICAL, an empty diagnosis, and
# NO_ACTION_RECOMMENDED immediately after analyze, on an asset expected to
# start at 100/CRITICAL with a REBALANCE_LOAD recommendation. Investigation
# (see README/session notes) found this was NOT a UI/API field-mapping bug:
# the live Cloud Run process's in-memory `data_store` still held DEMO-TP-007
# in its post-remediation state from an earlier live `/execute` call in the
# same running instance (nothing resets it between separate demo runs), and
# a live Gemini 429 (daily free-tier quota) independently emptied the
# diagnosis/recommended_action for that particular call. These tests pin
# down, offline, that (a) every field the demo page reads really is present
# with the exact name in both the analyze and execute responses, (b)
# risk_before/risk_after are unknown until execute and correct once it
# happens, and (c) `data_store.store.reset()` -- the mechanism that must run
# before a "fresh" demo pass -- genuinely discards a prior execution's
# mutation rather than silently preserving it.
# ---------------------------------------------------------------------------


def _extract_field_reads(prefix: str) -> set[str]:
    """Every `<prefix>.<field>` read in the demo page's inline script, e.g.
    `_extract_field_reads("a")` -> {"risk_score", "risk_level", ...} for
    every `a.risk_score`, `a.risk_level`, ... in the JS source."""
    body = (web._STATIC_DIR / "demo.html").read_text(encoding="utf-8")  # noqa: SLF001
    pattern = re.compile(r"\b" + re.escape(prefix) + r"\.([A-Za-z_][A-Za-z0-9_]*)\b")
    return set(pattern.findall(body))


def test_ui_field_reads_match_actual_analyze_response_contract(client):
    """Every `a.*` (analysis) and `ev.*` (evidence) field the demo page's JS
    reads must actually exist as a top-level key of `analysis`/`evidence` in
    the real `/api/incidents/analyze` response -- catches a silent rename on
    either side before it ever reaches a browser."""
    _install_fake_agent("DEMO-TP-007", "REBALANCE_LOAD")
    resp = client.post("/api/incidents/analyze", json={"asset_id": "DEMO-TP-007"})
    assert resp.status_code == 200
    body = resp.json()

    js_analysis_fields = _extract_field_reads("a")
    # JS-builtin/DOM properties that also match the `a.<word>` pattern but
    # are not reads of the `analysis` object (e.g. array methods).
    js_analysis_fields -= {"length", "map", "join", "reduce", "className"}
    missing = js_analysis_fields - set(body["analysis"].keys())
    assert not missing, f"demo.html reads a.* field(s) analyze response doesn't have: {missing}"

    js_evidence_fields = _extract_field_reads("ev")
    js_evidence_fields -= {"length", "map", "join"}
    missing = js_evidence_fields - set(body["evidence"].keys())
    assert not missing, f"demo.html reads ev.* field(s) analyze response doesn't have: {missing}"


def test_ui_field_reads_match_actual_execute_response_contract(client):
    """Same contract check for `rec.*` (audit_record) reads against a real
    `/execute` response -- specifically the before/after/risk/verification
    fields the "BEFORE/AFTER" and "VERIFIED RESULT" panels depend on."""
    _install_fake_agent("DEMO-TP-007", "REBALANCE_LOAD")
    incident_id = client.post(
        "/api/incidents/analyze", json={"asset_id": "DEMO-TP-007"}
    ).json()["incident_id"]
    client.post(
        f"/api/incidents/{incident_id}/approve",
        json={"approver": "test-operator", "reason": "regression test"},
    )
    resp = client.post(f"/api/incidents/{incident_id}/execute")
    assert resp.status_code == 200
    record = resp.json()["audit_record"]

    js_record_fields = _extract_field_reads("rec")
    js_record_fields -= {"length", "map", "join"}
    missing = js_record_fields - set(record.keys())
    assert not missing, f"demo.html reads rec.* field(s) execute response doesn't have: {missing}"


def test_risk_before_is_baseline_until_execution_then_matches_after_execute(client):
    """risk_score in `analysis` reflects the asset's *current* deterministic
    state at analyze time (100/CRITICAL on a freshly reset DEMO-TP-007);
    `audit_record.risk_before`/`risk_after` stay `None` until `/execute`
    actually runs, then become the real before/after values -- never
    fabricated, never present early."""
    _install_fake_agent("DEMO-TP-007", "REBALANCE_LOAD")
    analyze_body = client.post("/api/incidents/analyze", json={"asset_id": "DEMO-TP-007"}).json()

    assert analyze_body["analysis"]["risk_score"] == 100
    assert analyze_body["analysis"]["risk_level"] == "CRITICAL"
    assert analyze_body["analysis"]["diagnosis"]
    assert analyze_body["analysis"]["recommended_action"] == "REBALANCE_LOAD"
    assert analyze_body["analysis"]["policy_class"] == "HIGH_IMPACT"
    assert analyze_body["analysis"]["approval_required"] is True
    assert analyze_body["analysis"]["next_step"] == "WAIT_FOR_HUMAN_APPROVAL"
    assert analyze_body["audit_record"]["risk_before"] is None
    assert analyze_body["audit_record"]["risk_after"] is None

    incident_id = analyze_body["incident_id"]
    client.post(
        f"/api/incidents/{incident_id}/approve",
        json={"approver": "test-operator", "reason": "regression test"},
    )
    execute_body = client.post(f"/api/incidents/{incident_id}/execute").json()
    record = execute_body["audit_record"]

    assert record["risk_before"] == 100
    assert record["risk_after"] == 85
    assert record["verification_result"] == "IMPROVED"


def test_store_reset_discards_stale_post_execution_state():
    """The exact "reset must not preserve stale state" contract: after a
    full analyze->approve->execute cycle mutates DEMO-TP-007 (risk drops to
    85, load_ratio drops to 0.8), `data_store.store.reset()` -- the
    mechanism a fresh demo run/process start relies on -- must put it back
    to the untouched synthetic baseline (risk 100, load_ratio 1.3), not
    silently carry the mutation forward.
    """
    baseline = tools.get_risk_evidence("DEMO-TP-007")
    assert baseline.risk_score == 100
    assert "overload_critical" in baseline.risk_factors

    # Mutate it via a real execute, exactly like the live demo does.
    result = tools.simulate_remediation(
        "DEMO-TP-007",
        "REBALANCE_LOAD",
        approval=ApprovalState(status=ApprovalStatus.APPROVED, approver="setup", reason="setup"),
    )
    assert result.success is True
    mutated = tools.get_risk_evidence("DEMO-TP-007")
    assert mutated.risk_score == 85
    assert "overload_critical" not in mutated.risk_factors

    # The fix under test: reset must discard that mutation completely.
    store.reset()

    fresh = tools.get_risk_evidence("DEMO-TP-007")
    assert fresh.risk_score == 100
    assert fresh.risk_level.value == "CRITICAL"
    assert "overload_critical" in fresh.risk_factors
    assert store.get_asset("DEMO-TP-007").load_ratio == 1.3
