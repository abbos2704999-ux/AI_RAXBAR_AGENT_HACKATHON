# AI Raxbar Agent (Hackathon)

## Problem

Critical-infrastructure operators (electrical grid, in this case) need to
triage a growing stream of noisy signals -- outages, telemetry gaps, comm
loss, overload, maintenance backlogs, field complaints -- and decide what,
if anything, to act on. Doing this by hand doesn't scale; doing it with an
opaque model that "just decides" is unacceptable when the actions affect
physical infrastructure.

## Hackathon goal

Build an autonomous critical-infrastructure operations agent that follows a
strict, auditable loop:

```
OBSERVE -> DETECT -> DIAGNOSE -> PLAN -> POLICY GATE -> HUMAN APPROVAL
        -> ACT (SIMULATED) -> VERIFY -> AUDIT
```

**Track:** Taskmaster
**Secondary target:** Best Architectural Design

## Architecture principle

> **AI does not own the truth. Evidence does.**

Risk is computed by deterministic, testable, rule-based code from synthetic
evidence -- never inferred or asserted by an LLM. Whether an action needs
human approval is decided by deterministic policy code -- never by an LLM.
As of Batch 2, a Gemini-backed Google ADK agent *calls* these typed tools
and *plans* over their outputs, but it cannot change a risk score, override
a policy decision, or execute an action the policy gate blocks.

## Current scope: Batch 1

This repository currently contains **only** the deterministic, public-safe,
offline foundation:

- **Synthetic data** -- 12 fictional grid assets (`DEMO-TP-001` ..
  `DEMO-TP-012`) spanning NORMAL / MEDIUM / HIGH / CRITICAL risk, plus
  matching synthetic events and remediation templates. No real asset IDs,
  feeder names, coordinates, consumer data, crew names, CAS identifiers,
  spreadsheet IDs, or internal URLs.
- **Deterministic risk engine** (`risk_engine.py`) -- explicit, testable
  rules over synthetic signals, producing `risk_score`, `risk_level`,
  `risk_factors`, and `evidence_refs`.
- **Typed tools** (`tools.py`) -- four read-only tools
  (`get_asset_context`, `get_risk_evidence`, `get_recent_events`,
  `get_remediation_candidates`) and one controlled synthetic write tool
  (`simulate_remediation`) that only mutates local in-memory demo state.
- **Deterministic policy gate** (`policy.py`) -- classifies actions as
  `LOW_IMPACT` / `MEDIUM_IMPACT` / `HIGH_IMPACT`; `HIGH_IMPACT` actions
  cannot execute without a typed `ApprovalState` marked `APPROVED`.
  `simulate_remediation` enforces this -- it cannot be called around.
- **Verification** -- after a simulated remediation, risk is recomputed
  from the same deterministic engine and returned as a `VerificationResult`
  with `before_state`, `after_state`, `risk_before`, and `risk_after`, so
  the effect of an action is measurable, not asserted.

Nothing in this batch calls a network, a database, or an external service.

## Current scope: Batch 2

Batch 2 adds an agentic reasoning layer on top of Batch 1, without
rewriting or weakening it. Target loop for this batch:

```
OBSERVE -> DETECT -> DIAGNOSE -> PLAN -> POLICY GATE
```

It deliberately stops there -- no human-approval UI wiring, no automatic
action execution, no `simulate_remediation` call from the agent layer.

- **One Google ADK agent** (`agent.py`, `AGENT_NAME =
  "ai_raxbar_incident_agent"`) -- not a multi-agent fleet.
- **Typed, read-only tool access** (`agent_tools.py`) -- the model can call
  `get_asset_context`, `get_risk_evidence`, `get_recent_events`, and
  `get_remediation_candidates`, each delegating to the exact same Batch 1
  deterministic tools/risk engine. `simulate_remediation` is never in the
  agent's tool list -- policy stays outside model discretion, structurally
  (calling it raises inside ADK's tool dispatch, not just by convention).
- **Structured output** -- the model ends its turn by calling
  `propose_incident_analysis` with a diagnosis, uncertainties, a candidate
  recommended action, and a reasoning summary. `agent.py` then builds the
  final `IncidentAnalysis` by combining that narrative with fields computed
  independently in deterministic Python: `risk_score`, `risk_level`, and
  `evidence_refs` come straight from `risk_engine.py`; `policy_class` and
  `approval_required` come straight from `policy.py`. The model cannot set
  any of these fields itself -- there is no parameter for them on
  `propose_incident_analysis`, and even if a model smuggled extra values
  into a tool call, `agent.py` never reads them.
- **Hallucination guards** -- a recommended action not present in
  `get_remediation_candidates`'s real output is rejected (with a note in
  `uncertainties`); a cited evidence reference not present in the real
  `evidence_refs` is rejected the same way.
- **Prompt-injection resistance** -- `prompts.py` tells the model that tool
  output (including synthetic event `description` text) is untrusted data,
  never instructions. If a scripted/adversarial event or model response
  tries to invoke a tool the agent was never given (e.g.
  `simulate_remediation`), ADK's own tool dispatch raises before that
  function is ever reached; `agent.py` catches that failure and returns a
  safe `IncidentAnalysis` with no recommended action and no approval
  granted, rather than crashing or silently succeeding. See
  `tests/test_agent.py::test_prompt_injection_in_event_text_cannot_override_policy`.
- **Environment-driven config** (`config.py`) -- reads `GOOGLE_API_KEY` /
  `GEMINI_API_KEY` / Vertex AI env vars to decide whether a live Gemini call
  is even possible; no credential is ever hardcoded, logged, or printed.
  Default model is `gemini-3.5-flash`, overridable via
  `AI_RAXBAR_GEMINI_MODEL`.
- **Gemini integration status: CODE_READY, NOT_VERIFIED live.** The ADK
  agent and Gemini model wiring are implemented and offline-tested against
  a scripted fake model (`tests/fakes.py::ScriptedFakeLlm`, a real
  `google.adk` `BaseLlm` subclass driving the real tool-calling loop with no
  network access). No live Gemini API call has been made from this
  repository. `scripts/smoke_test_gemini.py` is an explicit, opt-in,
  human-run command (`--yes` required) for a single live smoke test once
  credentials are configured; nothing runs it automatically.

### Not yet implemented (NEXT / Batch 3+)

- A real human-approval UI/workflow wired to `WAIT_FOR_HUMAN_APPROVAL`.
- Automatic invocation of `simulate_remediation` after approval.
- Google Cloud (Cloud Run, Firestore, or any other GCP service).
- Any production write path or live Gemini verification.

## Pre-existing vs. new work

See [`docs/PRE_EXISTING_VS_NEW.md`](docs/PRE_EXISTING_VS_NEW.md). Short
version: AI RAXBAR V3 (a prior Google Apps Script ETL/scoring/dashboard
system) is reference-only and is not copied here. Everything in this
repository is new work written for this hackathon.

## Local test instructions

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

All tests are offline and deterministic -- no network access is required or
used, including the Batch 2 agent tests (`tests/test_agent.py`), which run
the real `google.adk` agent/tool-calling loop against a scripted fake model
instead of live Gemini.

To try a real, opt-in, single live Gemini call once you have
`GOOGLE_API_KEY` or `GEMINI_API_KEY` set in your environment:

```bash
python3 scripts/smoke_test_gemini.py --yes
```

Never committed, never printed: no script or test in this repository reads
an API key for any purpose other than making the one call above, and none
of them log or display its value.
