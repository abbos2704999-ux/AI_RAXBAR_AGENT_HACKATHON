# AI Raxbar Agent (Hackathon)

## START HERE

**AI Raxbar Agent is an autonomous critical-infrastructure operations agent
that diagnoses a synthetic grid incident with Gemini, gates any
high-impact remediation behind deterministic policy and explicit human
approval, then executes and verifies it in simulation only -- with every
step audited in Firestore.**

- **Live demo (judge UI):** <https://ai-raxbar-agent-ti5u2iy34q-uc.a.run.app/demo>
- **Track:** Taskmaster
- **Also submitted for the Best Architectural Design prize/category** (not a
  second track -- the track is Taskmaster)
- **Status:** Gemini 3.5 Flash -- **LIVE VERIFIED** · Google ADK -- **LIVE VERIFIED** · Cloud Run -- **LIVE VERIFIED** · Firestore -- **LIVE VERIFIED**
  (full matrix: [`docs/LIVE_VERIFICATION_MATRIX.md`](docs/LIVE_VERIFICATION_MATRIX.md))

> **AI does not own the truth. Evidence does.**

**Judge navigation:**

- [Architecture (diagram + trust boundaries)](docs/ARCHITECTURE.md)
- [Live Verification Matrix](docs/LIVE_VERIFICATION_MATRIX.md)
- [Safety Statement](docs/SAFETY_STATEMENT.md)
- [Pre-existing vs. New Work](docs/PRE_EXISTING_VS_NEW.md)
- [Devpost Architecture Summary](docs/DEVPOST_SUBMISSION.md)
- [Local Setup / Spin-up](#local-spin-up) (below)
- [Cloud Run Deployment (live state + reproducible template)](docs/CLOUD_RUN_DEPLOYMENT.md)
- [Build History (Batch 1-5 detail)](docs/BUILD_HISTORY.md)
- [Demo video: Google Flow disclosure](#demo-video-what-is-product-evidence-and-what-is-not)
- [License (MIT, this repo only)](LICENSE)

## Product story

**Problem.** Critical-infrastructure operators face a growing stream of
noisy signals -- outages, telemetry gaps, comm loss, overload -- and need
to decide what to act on. Doing it by hand doesn't scale; an opaque model
that "just decides" is unacceptable when the actions affect physical
infrastructure.

**What the agent does.** For one synthetic incident, it gathers
deterministic evidence, asks Gemini 3.5 Flash (via Google ADK) for a
diagnosis and a candidate remediation, runs that candidate through a
deterministic policy gate, waits for human approval if it's high-impact,
executes a *simulated* remediation, deterministically verifies the result,
and writes every step to an audited Firestore trail.

**Why it is not a chatbot.** There is no open-ended conversation and no
action the model can take on its own. It calls four read-only tools and
one structured-output tool -- never the write tool -- and every value a
safety decision depends on (risk, policy class, verification outcome) is
computed by deterministic code the model never touches.

**Safety model.** See [`docs/SAFETY_STATEMENT.md`](docs/SAFETY_STATEMENT.md)
for the full, code-backed list; the short version is that risk/evidence
are tool-owned, high-impact approval is human-owned, and the only "action"
this system can take mutates synthetic in-memory state, never a real grid
device.

**Live verified workflow.** The complete loop below has been run live
against real Google Cloud infrastructure (not just offline tests) -- see
[`docs/LIVE_VERIFICATION_MATRIX.md`](docs/LIVE_VERIFICATION_MATRIX.md) and
"Live Verification Evidence" further down this file for evidence:

```
OBSERVE -> DETECT -> DIAGNOSE -> PLAN -> POLICY GATE -> HUMAN APPROVAL
        -> ACT (SIMULATED) -> VERIFY -> AUDIT
```

## Quick demo (4 steps)

1. Open the live demo: <https://ai-raxbar-agent-ti5u2iy34q-uc.a.run.app/demo>
2. Click **RUN LIVE ANALYSIS** -- watch Gemini's diagnosis and the
   deterministic risk/policy classification appear for synthetic asset
   `DEMO-TP-007`.
3. Click **APPROVE** on the high-impact remediation (policy blocks
   execution until you do).
4. Click **EXECUTE SIMULATED REMEDIATION** and inspect the before/after
   state, the verification result, and the audit timeline.

**SIMULATION -- NO REAL GRID CONTROL.** No step above ever contacts a real
electrical-grid device or external system; the "action" only mutates an
in-memory synthetic signal.

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

**Track:** Taskmaster (single track).
**Prize/category also targeted:** Best Architectural Design -- a prize
opportunity, not a secondary track.

## Architecture principle

> **AI does not own the truth. Evidence does.**

Risk is computed by deterministic, testable, rule-based code from synthetic
evidence -- never inferred or asserted by an LLM. Whether an action needs
human approval is decided by deterministic policy code -- never by an LLM.
As of Batch 2, a Gemini-backed Google ADK agent *calls* these typed tools
and *plans* over their outputs, but it cannot change a risk score, override
a policy decision, or execute an action the policy gate blocks.

## Status summary

| Component                        | Status                    |
|-----------------------------------|---------------------------|
| Firestore persistence             | LIVE_VERIFIED             |
| Gemini 3.5                        | LIVE_VERIFIED             |
| Google ADK                        | LIVE_VERIFIED             |
| Human approval                    | LIVE_VERIFIED             |
| Simulated action + verification   | LIVE_VERIFIED             |
| Cloud Run HTTP service (`web.py`)  | LIVE_VERIFIED             |
| Docker/container configuration    | LIVE_VERIFIED             |
| Cloud Run deployment              | LIVE_VERIFIED              |
| Gemini 3.5 Flash through Cloud Run | LIVE_VERIFIED             |
| Google ADK tool calling through Cloud Run | LIVE_VERIFIED      |
| Hosted approval -> simulated action -> verify -> Firestore audit | LIVE_VERIFIED |
| Secret Manager (Gemini credential) | LIVE_VERIFIED             |
| Judge-facing demo UI (`/demo`)     | LIVE_VERIFIED             |

Full evidence for every LIVE_VERIFIED row: [`docs/LIVE_VERIFICATION_MATRIX.md`](docs/LIVE_VERIFICATION_MATRIX.md).

See "Live Verification Evidence" below for what each `LIVE_VERIFIED` status
is based on.

## Build history

This hackathon implementation was built incrementally with deterministic
safety boundaries preserved at every stage.

See:
[`docs/BUILD_HISTORY.md`](docs/BUILD_HISTORY.md)

## Live Verification Evidence

Every live check below used only synthetic/fictional data, was run manually
by a human as a one-off opt-in action, and is not invoked automatically by
any test, script, or orchestrator code path.

**Gemini -- LIVE_VERIFIED.** `scripts/smoke_test_gemini.py --yes
--asset-id DEMO-TP-007`, model `gemini-3.5-flash`, against the synthetic
asset `DEMO-TP-007`. Confirmed: a real Gemini response was received;
`risk_score`/`risk_level`/`evidence_refs` matched the deterministic risk
engine's output, not anything the model asserted; the recommended action
was classified `HIGH_IMPACT` by `policy.py`, so `approval_required=True`
and `tools.simulate_remediation` was never called. Full detail in "Current
scope: Batch 2" in [`docs/BUILD_HISTORY.md`](docs/BUILD_HISTORY.md).

**Firestore -- LIVE_VERIFIED.** One controlled, opt-in live smoke test
against GCP project `ai-raxbar-agent-hackathon`, default Firestore
database, using this repository's unmodified `FirestoreRepository` +
`build_live_client()`, with a single synthetic incident id
(`HACKATHON-SMOKE-001`). Confirmed, in order: incident write + exact
readback; approval (`PENDING`) write + readback; one audit record write +
readback; `cleanup_incident("HACKATHON-SMOKE-001")` deleting exactly the
incident, approval, and matching audit record it wrote (nothing else);
post-cleanup reads confirming all three are gone; and that no unrelated
document or collection was touched. Authentication used standard
Application Default Credentials only -- no credential value, token, or ADC
path was printed at any point.

**Cloud Run -- LIVE_VERIFIED.** Service `ai-raxbar-agent` in
`us-central1` (see "Current scope: Batch 5B" and "Current scope: Batch 5C" in
[`docs/BUILD_HISTORY.md`](docs/BUILD_HISTORY.md)). `GET /health` and `GET /api/status` against the live Cloud Run URL
both returned `HTTP 200`, with `/api/status` confirming
`synthetic_only_mode: true` and no secret in the response.

**Gemini 3.5 Flash through Cloud Run -- LIVE_VERIFIED.** One hosted
`POST /api/incidents/analyze` call for synthetic asset `DEMO-TP-007`
against the live Cloud Run URL, with the Gemini credential supplied via
Secret Manager (see Batch 5C in `docs/BUILD_HISTORY.md`). Deterministic risk (`100` /
`CRITICAL`), 14 valid evidence refs, `recommended_action =
REBALANCE_LOAD`, `policy_class = HIGH_IMPACT`, `approval_required = true`,
`next_step = WAIT_FOR_HUMAN_APPROVAL`; `tools.simulate_remediation` was
never called. Firestore remained `LOCAL_ONLY` on the Batch 5C revision --
see the Batch 5D entry in `docs/BUILD_HISTORY.md` for the live Firestore-backed run.

**Google ADK tool calling through Cloud Run -- LIVE_VERIFIED.** The same
hosted call above exercised the real ADK agent's real tool-calling loop
(`get_asset_context`, `get_recent_events`, `get_risk_evidence`,
`get_remediation_candidates`) against the deployed service, not an offline
fake -- the model's diagnosis and recommended action were produced from
live tool results, not asserted independently of them.

**Hosted approval -> simulated action -> verify -> Firestore audit --
LIVE_VERIFIED.** One complete hosted synthetic workflow (see "Current
scope: Batch 5D" in `docs/BUILD_HISTORY.md`), against the live Cloud Run service with
`AI_RAXBAR_REPOSITORY_BACKEND=firestore`: `/analyze` (one Gemini call) ->
live-read-confirmed Firestore persistence of the pending incident/approval
-> `/execute` blocked pre-approval (`HTTP 409`) -> `/approve` -> `/execute`
(`EXECUTED`, `risk_before=100` -> `risk_after=85`,
`verification_result=IMPROVED`) -> live-read-confirmed Firestore held the
incident, approval, and both audit records -> guarded
`cleanup_incident()` removed exactly those documents -> live-read-confirmed
all three gone and every involved collection empty afterward (no unrelated
document touched). Firestore access used the Cloud Run runtime
identity/ADC and a narrowly scoped `roles/datastore.user` grant -- no
service-account JSON, no credential printed.

**Synthetic-only boundary.** Every verification above used only fictional
identifiers (`DEMO-TP-007`, `HACKATHON-SMOKE-001`) or no incident data at
all (`/health`, `/api/status`) -- no real coordinates, real infrastructure
identifiers, AI RAXBAR V3 data, CAS, Billing, or Google Sheets access
occurred in any of them.

### Not implemented (deliberately out of scope)

- **Any production write path.** The only "action" in this system is
  `tools.simulate_remediation`, which mutates in-memory synthetic state.
  There is no code path to a real grid device or external system.
- **Real telemetry ingestion.** All evidence comes from the synthetic
  fixtures in `data/`.
- **Multi-incident triage, role-based approval/delegation, and signed
  tamper-evident audit records.** Future direction, not claimed here.

The judge-facing browser UI listed as "next" in earlier batches **is now
implemented and live** at [`/demo`](https://ai-raxbar-agent-ti5u2iy34q-uc.a.run.app/demo)
(Batch 5E; `src/ai_raxbar_agent/static/demo.html`), and is covered by
`tests/test_demo_ui.py`. See `docs/BUILD_HISTORY.md` for the batch-by-batch
record.

## Demo video: what is product evidence and what is not

The submission video contains cinematic sequences generated with **Google
Flow**. They are there to communicate the operational stakes -- a load ratio
of 1.3 is a number until you show what it means downstream -- and nothing
more.

> **Google Flow was used for cinematic storytelling and contextual
> visualization. The deployed AI RAXBAR screen recording is the product
> evidence.**

No Flow-generated footage is real infrastructure footage, real AI RAXBAR
output, proof of deployment, or proof of grid control. Every product claim
in the video is shown as live UI or live API output from the Cloud Run
service, and every one of those is independently reproducible by a judge at
the demo URL above.

## License

[MIT](LICENSE) -- Copyright (c) 2026 Abdulbosit Ismailov.

This license applies **only to this repository**
(`AI_RAXBAR_AGENT_HACKATHON`) -- the new work written for this hackathon.
It does **not** apply to, and grants no rights over, the pre-existing
**AI RAXBAR V3** system, **MARKAZ ANALITIKA**, any CAS-related private
work, production data, or any other private repository or system. See
[`docs/PRE_EXISTING_VS_NEW.md`](docs/PRE_EXISTING_VS_NEW.md) for what is
and isn't part of this repository.

## Pre-existing vs. new work

See [`docs/PRE_EXISTING_VS_NEW.md`](docs/PRE_EXISTING_VS_NEW.md). Short
version: AI RAXBAR V3 (a prior Google Apps Script ETL/scoring/dashboard
system) is reference-only and is not copied here. Everything in this
repository is new work written for this hackathon.

## Local spin-up

Requires **Python 3.10+** (see `pyproject.toml`).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

All 137 tests are offline and deterministic -- **no Gemini API key,
Google Cloud credentials, or network access are required to run them**,
including the Batch 2 agent tests (`tests/test_agent.py`), which run the
real `google.adk` agent/tool-calling loop against a scripted fake model
instead of live Gemini; the Batch 4 persistence tests
(`tests/test_repository.py`), which exercise the Firestore-shaped adapter
against `tests/fakes.py::FakeFirestoreClient` instead of live Firestore;
and the Batch 5 HTTP/demo-UI tests (`tests/test_web.py`,
`tests/test_demo_ui.py`), which drive the FastAPI app with
`fastapi.testclient.TestClient` instead of a real server or browser.

### Run the web service + demo UI locally

Still fully offline by default -- no credentials needed to browse it:

```bash
uvicorn ai_raxbar_agent.web:app --reload
```

Then open <http://127.0.0.1:8000/demo> in a browser. With no
`GEMINI_API_KEY`/`GOOGLE_API_KEY` set, `/health` and `/api/status` work
normally (`gemini_integration: "NOT_CONFIGURED"`) and clicking **RUN LIVE
ANALYSIS** returns a clear `503` rather than attempting a network call --
see `web.py`'s fail-closed design.

### Optional: live configuration (not required for anything above)

To try a real, opt-in, single live Gemini call once you have
`GOOGLE_API_KEY` or `GEMINI_API_KEY` set in your environment:

```bash
python3 scripts/smoke_test_gemini.py --yes
```

Or run the local web service the same way (`uvicorn ai_raxbar_agent.web:app
--reload` with `GEMINI_API_KEY` exported first) to exercise `/demo` against
a real Gemini call. To use a real Firestore backend instead of the default
offline `LocalRepository`, set `AI_RAXBAR_REPOSITORY_BACKEND=firestore`
with Application Default Credentials configured (see
`docs/CLOUD_RUN_DEPLOYMENT.md`).

Never committed, never printed: no script or test in this repository reads
an API key for any purpose other than making the one call above, and none
of them log or display its value.
