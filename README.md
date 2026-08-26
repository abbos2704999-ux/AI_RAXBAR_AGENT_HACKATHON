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
- **Gemini integration status: CODE_READY, LIVE_ATTEMPTED_NOT_VERIFIED.**
  The ADK agent and Gemini model wiring are implemented and offline-tested
  against a scripted fake model (`tests/fakes.py::ScriptedFakeLlm`, a real
  `google.adk` `BaseLlm` subclass driving the real tool-calling loop with no
  network access). Two controlled, opt-in live smoke-test attempts
  (`scripts/smoke_test_gemini.py --yes`) have reached the real Gemini API;
  both returned an upstream `503 UNAVAILABLE` ("high demand") error rather
  than a successful response, so a live call has been *attempted* but not
  yet *verified end-to-end*. `scripts/smoke_test_gemini.py` remains an
  explicit, opt-in, human-run command (`--yes` required); nothing in this
  repository runs it automatically or retries it on its own.

## Current scope: Batch 3

Batch 3 adds human approval, a controlled synthetic action executor, and an
audit trail on top of Batch 2's policy gate, completing the full target
loop:

```
OBSERVE -> DETECT -> DIAGNOSE -> PLAN -> POLICY GATE -> HUMAN APPROVAL
        -> ACT (SIMULATED) -> VERIFY -> AUDIT
```

- **Human-approval state machine** (`approval.py`) -- every request starts
  `PENDING`; only an explicit `approve()`/`reject()` call (with a required
  approver identity) moves it to `APPROVED`/`REJECTED`. A request cannot be
  approved once `REJECTED`.
- **Controlled action executor** (`orchestrator.execute_action`) -- the one
  entry point from an `IncidentProposal` + `ApprovalState` to a synthetic
  action. It re-derives the policy decision independently from
  `policy.py` and refuses a `HIGH_IMPACT` action without `APPROVED` *before*
  ever calling `tools.simulate_remediation` -- which enforces the identical
  rule again on its own, so there is no code path that bypasses approval.
- **Verification** -- unchanged from Batch 1: risk is recomputed
  deterministically before/after, and the before/after state + risk +
  `PASS`/`FAIL` outcome are captured on every executed action.
- **Audit trail** (`audit.py`) -- an offline, in-memory, JSON-serializable
  `AuditRecord`/`AuditTrail` shaped like a future persisted document. Every
  outcome (blocked, rejected, executed, failed) is recorded, not just
  successes.

## Current scope: Batch 4

Batch 4 adds a **Firestore-ready persistence boundary** for the same
incident/approval/audit state, without weakening any Batch 1-3 safety gate.

- **Persistence interface** (`repository.py`) -- `IncidentRepository`, an
  ABC with `save_incident` / `get_incident` / `save_audit_record` /
  `list_audit_records` / `save_approval_state` / `get_approval_state`.
  `orchestrator.execute_action` depends only on this interface, never on a
  concrete storage SDK.
- **Local/offline implementation** (`local_repository.py`) --
  `LocalRepository`, in-memory, no credentials, no network. This is the
  default repository `execute_action` uses unless a caller passes a
  different one, and what every offline test runs against.
- **Firestore-ready adapter** (`firestore_repository.py`) --
  `FirestoreRepository` implements the same interface against any client
  exposing Firestore's `collection().document().set()/get()` /
  `collection().stream()` surface (a real `google.cloud.firestore.Client`
  or a fake). The module never imports `google.cloud.firestore` at import
  time and never constructs a client itself; `build_live_client()` is a
  separate, explicit, human-invoked function (mirroring
  `scripts/smoke_test_gemini.py`'s posture) that lazily imports the SDK and
  builds a client from standard Google Cloud credentials (Application
  Default Credentials / environment) -- nothing in this repository calls it
  automatically. **No live Firestore call has been made from this
  repository; nothing here should be read as `LIVE_FIRESTORE_VERIFIED`.**
  Suggested/used collections: `incidents`, `approvals`, `audit_records`.
- **Controlled synthetic smoke-test cleanup** (`cleanup_incident`, part of
  the `IncidentRepository` interface) -- a narrow, opt-in method that
  deletes exactly one incident's `incidents`/`approvals` documents plus
  every `audit_records` entry for that `incident_id`, and nothing else.
  This exists solely so a future live Firestore smoke test can remove the
  handful of documents it writes; **it is not a general-purpose or
  production deletion API.** Every implementation calls
  `repository.require_demo_incident_id()` first and refuses any
  `incident_id` that doesn't start with an explicit synthetic/demo marker
  (`HACKATHON-SMOKE-` or `DEMO-`, optionally after the orchestrator's
  `INC-` prefix) before deleting anything. The Firestore adapter scopes the
  audit-records deletion with a `where("incident_id", "==", ...)` query and
  deletes each match by its own document reference -- never a
  collection-wide/unbounded delete. Cleanup is idempotent: calling it again
  on an already-cleaned-up `incident_id` returns all-False/zero rather than
  raising.
- **Fail-closed persistence** -- `execute_action` persists the incident and
  approval state *before* checking the policy gate or calling
  `simulate_remediation`. A `RepositoryError` raised during either save
  therefore aborts the call before the write tool is ever reached: a
  storage failure can only ever block an action, never let one through.
- **Idempotency** -- re-saving the same `incident_id` preserves its
  original `created_at` (an update, not a duplicate); audit records are
  keyed by `incident_id::action_status`, so retrying the same lifecycle
  stage overwrites in place while a genuinely new stage (e.g.
  `BLOCKED_PENDING_APPROVAL` -> `EXECUTED`) still gets its own record,
  preserving full history without uncontrolled duplication.
- **No chain-of-thought persisted** -- the persisted `IncidentRecord`
  carries only the model's concise, user-facing `diagnosis` text (the same
  field `agent.propose_incident_analysis` defines); this codebase never
  captures raw model chain-of-thought anywhere, so there is nothing else to
  leak into storage.
- Offline tests (`tests/test_repository.py`, 40 total) cover
  incident/approval/audit persistence, ordered workflow state, idempotent
  retries, rejection persisting without executing, `HIGH_IMPACT` staying
  blocked pre-approval, fail-closed behavior on a simulated persistence
  outage, `cleanup_incident`'s demo-id guard/idempotency/unrelated-data
  isolation/backend-failure handling, and the Firestore adapter's
  structural compatibility against a fake client
  (`tests/fakes.py::FakeFirestoreClient`) with zero network access.

### Not yet implemented (NEXT / Batch 5+)

- Live, successful Gemini verification (two attempts so far both hit an
  upstream `503`; not yet retried).
- A live Firestore connection/verification against a real GCP project.
- Any Cloud Run deployment or other live GCP service.
- Any production write path.

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
instead of live Gemini, and the Batch 4 persistence tests
(`tests/test_repository.py`), which exercise the Firestore-shaped adapter
against `tests/fakes.py::FakeFirestoreClient` instead of live Firestore.

To try a real, opt-in, single live Gemini call once you have
`GOOGLE_API_KEY` or `GEMINI_API_KEY` set in your environment:

```bash
python3 scripts/smoke_test_gemini.py --yes
```

Never committed, never printed: no script or test in this repository reads
an API key for any purpose other than making the one call above, and none
of them log or display its value.
