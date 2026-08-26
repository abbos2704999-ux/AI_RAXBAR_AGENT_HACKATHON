# AI Raxbar Agent (Hackathon)

## START HERE

**AI Raxbar Agent is an autonomous critical-infrastructure operations agent
that diagnoses a synthetic grid incident with Gemini, gates any
high-impact remediation behind deterministic policy and explicit human
approval, then executes and verifies it in simulation only -- with every
step audited in Firestore.**

- **Live demo (judge UI):** <https://ai-raxbar-agent-ti5u2iy34q-uc.a.run.app/demo>
- **Track:** Taskmaster (secondary target: Best Architectural Design)
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
- [Cloud Run Deployment (template)](docs/CLOUD_RUN_DEPLOYMENT.md)
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

## Status summary

| Component                        | Status                    |
|-----------------------------------|---------------------------|
| Firestore persistence             | LIVE_VERIFIED             |
| Gemini 3.5                        | LIVE_VERIFIED             |
| Google ADK                        | LIVE_VERIFIED             |
| Human approval                    | LIVE_VERIFIED             |
| Simulated action + verification   | LIVE_VERIFIED             |
| Cloud Run-ready HTTP service       | IMPLEMENTED               |
| Docker/container configuration    | IMPLEMENTED               |
| Cloud Run deployment              | LIVE_VERIFIED              |
| Gemini 3.5 Flash through Cloud Run | LIVE_VERIFIED             |
| Google ADK tool calling through Cloud Run | LIVE_VERIFIED      |
| Hosted approval -> simulated action -> verify -> Firestore audit | LIVE_VERIFIED |
| Secret Manager (Gemini credential) | LIVE_VERIFIED             |
| Judge-facing demo UI (`/demo`)     | LIVE_VERIFIED             |

Full evidence for every LIVE_VERIFIED row: [`docs/LIVE_VERIFICATION_MATRIX.md`](docs/LIVE_VERIFICATION_MATRIX.md).

See "Live Verification Evidence" below for what each `LIVE_VERIFIED` status
is based on.

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
- **Gemini integration status: LIVE_VERIFIED.** The ADK agent and Gemini
  model wiring are implemented and offline-tested against a scripted fake
  model (`tests/fakes.py::ScriptedFakeLlm`, a real `google.adk` `BaseLlm`
  subclass driving the real tool-calling loop with no network access), and
  have also been verified against the real Gemini API. Three controlled,
  opt-in live smoke-test attempts (`scripts/smoke_test_gemini.py --yes
  --asset-id DEMO-TP-007`, model `gemini-3.5-flash`) have been run: the
  first two returned an upstream `503 UNAVAILABLE` ("high demand") error;
  the third completed successfully end-to-end. That run confirmed: a real
  Gemini response was received; `risk_score`/`risk_level`/`evidence_refs`
  matched the deterministic risk engine's known output for
  `DEMO-TP-007` (`100`/`CRITICAL`, 14 evidence refs) rather than anything
  the model asserted; the `diagnosis` was genuine free-text model output;
  `recommended_action` was `REBALANCE_LOAD`, classified `HIGH_IMPACT` by
  `policy.py`, giving `approval_required=True` and
  `next_step="WAIT_FOR_HUMAN_APPROVAL"`; and
  `tools.simulate_remediation` was never called (it isn't in the agent's
  tool list). No approval was granted and no action was taken during that
  run -- it stopped at the policy gate, per this script's scope.
  `scripts/smoke_test_gemini.py` remains an explicit, opt-in, human-run
  command (`--yes` required); nothing in this repository runs it
  automatically or retries it on its own.

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
  automatically. **Firestore integration status: LIVE_VERIFIED.** One
  controlled, opt-in live smoke test has been run against a real GCP
  project using this adapter unmodified; see "Live Verification Evidence"
  below for what was confirmed.
  Collections used: `incidents`, `approvals`, `audit_records`.
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

## Current scope: Batch 5A

Batch 5A prepares the application for Cloud Run **deployment readiness
only** -- it does not deploy anything. It adds a thin HTTP boundary on top
of Batches 1-4 without duplicating any of their decisions.

- **HTTP entrypoint** (`web.py`, FastAPI + uvicorn) -- `GET /health` (pure
  process liveness -- never calls Gemini or Firestore), `GET /api/status`
  (service name/version, Gemini/Firestore configuration flags,
  `synthetic_only_mode`, `policy_gate` -- flags only, never a secret, API
  key, or the real GCP project id), `POST /api/incidents/analyze`,
  `POST /api/incidents/{incident_id}/approve`,
  `POST /api/incidents/{incident_id}/reject`, and
  `POST /api/incidents/{incident_id}/execute`. Every handler only
  translates HTTP <-> the existing `agent`, `orchestrator`, `policy`,
  `approval`, and repository modules -- no risk, policy, approval, or
  persistence decision is made in `web.py` itself.
- **Synthetic-only boundary at the API layer** -- every asset_id/incident_id
  this service accepts must start with `DEMO-` or `HACKATHON-` (optionally
  after the orchestrator's `INC-` incident-id prefix); anything else is
  rejected with `400` before any other module is touched.
- **Fail-closed persistence backend selection** -- `AI_RAXBAR_REPOSITORY_BACKEND`
  (`local`, the default, or `firestore`) chooses the repository. Setting it
  to `firestore` builds a `FirestoreRepository` the first time a request
  needs it, via `firestore_repository.build_live_client()` (Application
  Default Credentials / the Cloud Run service identity -- never a
  service-account JSON file); if that fails, the request returns `503`
  rather than silently falling back to the local in-memory repository.
- **Container** (`Dockerfile`, `.dockerignore`) -- small `python:3.12-slim`
  image, non-root runtime user, deterministic `uvicorn` startup, honors
  Cloud Run's `PORT` env var. No `.env`, credential, service-account JSON,
  or V3 source/data is copied into the image (none of those exist in this
  repository; excluded defensively regardless).
- **Deployment template** (`docs/CLOUD_RUN_DEPLOYMENT.md`) -- documents the
  expected `gcloud run deploy` command shape (project/region/service
  name/env vars all left as placeholders, no credential values embedded).
  This is documentation only -- no command in it has been run.
- Offline tests (`tests/test_web.py`, 11 total, part of the suite below)
  exercise every endpoint through `TestClient` against the offline
  `LocalRepository` and a `ScriptedFakeLlm`-backed agent (same pattern as
  `tests/test_orchestrator.py`) -- zero network calls. They confirm:
  `/health` and `/api/status` work with no secrets in the response;
  non-synthetic and unknown asset/incident ids are rejected; a
  `HIGH_IMPACT` action blocks at `/analyze` and stays blocked at `/execute`
  until `/approve` is called; a rejected incident can never execute; a
  `LOW_IMPACT` action executes and returns a verification result without a
  separate approval step; and an unknown incident id returns `404`.

**Cloud Run deployment status (as of this batch): NOT YET DEPLOYED.** No
image had been built, pushed, or deployed as part of Batch 5A;
`docs/CLOUD_RUN_DEPLOYMENT.md` was a template for the human-run deployment
step that follows in Batch 5B, below.

## Current scope: Batch 5B

Batch 5B performs the one controlled live Cloud Run deployment
Batch 5A prepared for, using the unmodified `Dockerfile` and `web.py` from
that batch -- no repository code changed to make this deployment work.

- **Deployed service** -- `ai-raxbar-agent`, region `us-central1`, project
  `ai-raxbar-agent-hackathon`, built and deployed via
  `gcloud run deploy ai-raxbar-agent --source .` (Cloud Build builds the
  existing `Dockerfile`; no local Docker daemon involved, no manual
  service-account key created or used -- the build and runtime identity are
  both Google-managed).
- **APIs enabled** -- exactly the three Batch 5A called for:
  `run.googleapis.com`, `artifactregistry.googleapis.com`,
  `cloudbuild.googleapis.com`. Nothing else was enabled.
- **Runtime configuration, deliberately minimal** -- no `GEMINI_API_KEY` and
  no `AI_RAXBAR_REPOSITORY_BACKEND` env var were set on this revision, so
  the deployed service runs with Gemini `NOT_CONFIGURED` and the Firestore
  backend at its `local`/offline default. This was a deliberate choice for
  the first live revision, per Batch 5A's fail-closed design (`web.py`'s
  `/api/incidents/analyze` returns `503` rather than attempting a Gemini
  call when unconfigured, and the offline `LocalRepository` default means
  no live Firestore write can happen from this revision at all) --
  extending it with real credentials is left to a following batch.
- **Public access** -- `roles/run.invoker` was granted to `allUsers` on
  this service, a deliberate choice (not the security-first default) so
  hackathon judges can reach the URL without needing a Google Cloud
  identity token. This is safe here specifically because every endpoint
  enforces the synthetic-only `DEMO-*`/`HACKATHON-*` id boundary, no
  production data or write path exists behind it, and (per the point
  above) this revision cannot reach Gemini or write to Firestore at all.
- **Live verification performed** -- `GET /health` and `GET /api/status`
  against the live Cloud Run URL both returned `HTTP 200`; `/api/status`
  reported `synthetic_only_mode: true`, `policy_gate: "ACTIVE"`,
  `gemini_integration: "NOT_CONFIGURED"`, `firestore_integration:
  "LOCAL_ONLY"`, with no secret, credential, or token in the response.
  `POST /api/incidents/analyze` was deliberately **not** attempted against
  this revision, per the same fail-closed rule the offline tests already
  cover: Gemini isn't configured on it, so the call would only ever return
  `503` -- there is nothing to safely verify there yet.

**Cloud Run deployment status (as of Batch 5B): LIVE_VERIFIED for
`/health` and `/api/status` only.** A live `/api/incidents/analyze` call
against the deployed service required a Gemini credential wired in first --
see "Current scope: Batch 5C" below for that follow-up.

## Current scope: Batch 5C

Batch 5C securely connects Gemini to the already-deployed Cloud Run
service and performs one hosted synthetic analysis, without touching
Firestore and without changing any source file.

- **Gemini credential via Secret Manager** -- the existing local Gemini API
  key was added, without ever being printed or logged, as one version of a
  narrowly named secret (`ai-raxbar-gemini-api-key`) in Google Secret
  Manager. It was never placed in source code, the Docker image, git, this
  README, or a Cloud Run command-line env value.
- **Least-privilege access** -- the existing Cloud Run runtime service
  identity was granted `roles/secretmanager.secretAccessor` scoped to only
  that one secret -- no project-level or broader IAM role.
- **Same service, new revision** -- `ai-raxbar-agent` (unchanged name,
  unchanged region `us-central1`, unchanged public demo access, unchanged
  synthetic-only boundary) was updated, not replaced, to mount that secret
  as the `GEMINI_API_KEY` environment variable `config.py` already reads.
  Firestore was deliberately left unconfigured on this revision -- it
  remains `local`/offline only.
- **One hosted, live, end-to-end analysis performed** -- a single
  `POST /api/incidents/analyze` call for synthetic asset `DEMO-TP-007`
  against the live Cloud Run URL exercised the full chain: Cloud Run ->
  Google ADK -> Gemini 3.5 Flash -> the same deterministic evidence tools
  and risk engine as every other batch -> the deterministic policy gate.
  Confirmed from that one response: risk was deterministic and tool-owned
  (`risk_score = 100`, `risk_level = CRITICAL`, matching the known
  `DEMO-TP-007` baseline, not anything the model asserted), all 14
  evidence refs it returned were valid/real (not hallucinated), the
  diagnosis was genuine live-model free text, `recommended_action =
  REBALANCE_LOAD` was classified `policy_class = HIGH_IMPACT` by
  `policy.py`, `approval_required = true`, and `next_step =
  WAIT_FOR_HUMAN_APPROVAL`. The audit record showed `action_status =
  BLOCKED_PENDING_APPROVAL` with an unchanged `before_state`/`after_state`
  (both `{}`), confirming `tools.simulate_remediation` was never called.
  No approval or execution was attempted -- this batch stopped at the
  policy gate, by design.
- **Credential exposure: NONE.** The API key was not printed to a
  terminal, not written to any repository file, not baked into the Docker
  image, and did not appear in the `/health`, `/api/status`, or `/analyze`
  responses.

**LIVE VERIFIED (this batch):** `Cloud Run -> Google ADK -> Gemini 3.5
Flash -> deterministic evidence/risk tools -> deterministic policy gate`,
for one hosted synthetic incident.

**NOT YET HOSTED END-TO-END (as of Batch 5C):** human approval -> simulated
action -> verification -> Firestore audit, against the live Cloud Run
service, as one continuous hosted call chain. Closed in Batch 5D below.

## Current scope: Batch 5D

Batch 5D switches the deployed Cloud Run service from the offline
`LocalRepository` to a live `FirestoreRepository`, then proves one
complete hosted synthetic workflow -- analyze -> approve -> execute ->
verify -> Firestore audit -> cleanup -- end to end against the real,
deployed service. No source file changed for this batch; it is entirely
infrastructure wiring (IAM + Cloud Run env var) plus one live workflow run.

- **Firestore wired into the hosted service** -- `AI_RAXBAR_REPOSITORY_BACKEND=firestore`
  set on the existing Cloud Run service (same service, new revision -- not
  a new service). Firestore access uses the same Cloud Run runtime
  identity/Application Default Credentials already used for the rest of
  this deployment -- no service-account JSON, no embedded credentials.
- **Least-privilege IAM** -- `roles/datastore.user` granted explicitly to
  the Cloud Run runtime service account, scoped to Firestore only; no new
  broad Owner/Editor role was granted (the account's pre-existing
  `roles/editor`, from earlier project setup, was left untouched, not
  added by this batch).
- **One complete hosted synthetic workflow, live** -- for a single
  synthetic incident on asset `DEMO-TP-007`: `POST /api/incidents/analyze`
  (one Gemini call, `next_step=WAIT_FOR_HUMAN_APPROVAL`) -> a live read
  confirmed the incident and `PENDING` approval were actually persisted in
  Firestore -> `POST .../execute` *before* approval was confirmed blocked
  (`HTTP 409`, policy gate enforced) -> `POST .../approve` (`APPROVED`) ->
  `POST .../execute` (`action_status=EXECUTED`, `risk_before=100` ->
  `risk_after=85`, `verification_result=IMPROVED`, a real, measurable,
  synthetic-only state change) -> a live read confirmed Firestore held the
  incident, the approval, and both audit records (`BLOCKED_PENDING_APPROVAL`
  then `EXECUTED`) -> `cleanup_incident()` removed exactly those documents
  (`incident_deleted=True`, `approval_deleted=True`,
  `audit_records_deleted=2`) -> a final live read confirmed all three are
  gone and that every collection involved is now empty, i.e. nothing
  unrelated was ever touched.
- **Exactly one Gemini call** was made for this entire batch (the single
  `/analyze` step); approve/execute/cleanup involve no Gemini call at all.
- **Credential exposure: NONE** -- the API key and Firestore access both
  used the existing runtime identity/Secret Manager wiring from Batches 5B
  -- 5C; nothing new was printed, logged, or returned by any endpoint.

**Hosted end-to-end chain -- LIVE_VERIFIED:** `Cloud Run -> Google ADK ->
Gemini 3.5 Flash -> deterministic tools -> policy gate -> human approval ->
simulated action -> deterministic verification -> Firestore audit`, for
one complete synthetic incident, with guarded cleanup leaving Firestore
exactly as it was before the run.

## Live Verification Evidence

Both live checks below used only synthetic/fictional data, were run
manually by a human as a one-off opt-in action, and are not invoked
automatically by any test, script, or orchestrator code path.

**Gemini -- LIVE_VERIFIED.** `scripts/smoke_test_gemini.py --yes
--asset-id DEMO-TP-007`, model `gemini-3.5-flash`, against the synthetic
asset `DEMO-TP-007`. Confirmed: a real Gemini response was received;
`risk_score`/`risk_level`/`evidence_refs` matched the deterministic risk
engine's output, not anything the model asserted; the recommended action
was classified `HIGH_IMPACT` by `policy.py`, so `approval_required=True`
and `tools.simulate_remediation` was never called. Full detail in "Current
scope: Batch 2" above.

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
`us-central1` (see "Current scope: Batch 5B" and "Current scope: Batch 5C"
above). `GET /health` and `GET /api/status` against the live Cloud Run URL
both returned `HTTP 200`, with `/api/status` confirming
`synthetic_only_mode: true` and no secret in the response.

**Gemini 3.5 Flash through Cloud Run -- LIVE_VERIFIED.** One hosted
`POST /api/incidents/analyze` call for synthetic asset `DEMO-TP-007`
against the live Cloud Run URL, with the Gemini credential supplied via
Secret Manager (see Batch 5C above). Deterministic risk (`100` /
`CRITICAL`), 14 valid evidence refs, `recommended_action =
REBALANCE_LOAD`, `policy_class = HIGH_IMPACT`, `approval_required = true`,
`next_step = WAIT_FOR_HUMAN_APPROVAL`; `tools.simulate_remediation` was
never called. Firestore remained `LOCAL_ONLY` on the Batch 5C revision --
see the Batch 5D entry below for the live Firestore-backed run.

**Google ADK tool calling through Cloud Run -- LIVE_VERIFIED.** The same
hosted call above exercised the real ADK agent's real tool-calling loop
(`get_asset_context`, `get_recent_events`, `get_risk_evidence`,
`get_remediation_candidates`) against the deployed service, not an offline
fake -- the model's diagnosis and recommended action were produced from
live tool results, not asserted independently of them.

**Hosted approval -> simulated action -> verify -> Firestore audit --
LIVE_VERIFIED.** One complete hosted synthetic workflow (see "Current
scope: Batch 5D" above), against the live Cloud Run service with
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

### Not yet implemented (NEXT / Batch 5E+)

- A user-facing UI (every verification so far is via direct HTTP calls,
  not a browser front end).
- Any production write path.

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

All 125 tests are offline and deterministic -- **no Gemini API key,
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
