# Pre-existing vs. New Work Disclosure

## PRE-EXISTING

**AI RAXBAR V3** was a Google Apps Script-based deterministic ETL / scoring /
dashboard system, built prior to this hackathon. It is reference-only: it
informed the general *idea* of a deterministic, evidence-based risk-scoring
approach, but no source code, configuration, identifiers, credentials, asset
data, or infrastructure from V3 is copied, imported, or referenced in this
repository.

No V3 source code, TP numbers, feeder names, coordinates, consumer data,
crew names, CAS identifiers, spreadsheet IDs, internal URLs, or any other
private/internal identifiers appear anywhere in this repository.

## NEW DURING THE HACKATHON

Everything else -- all code, data, docs, and infrastructure configuration in
this repository -- is new work written for this hackathon:

- **Deterministic foundation (Batch 1)** -- 12 fictional synthetic assets
  (`DEMO-TP-001`..`DEMO-TP-012`) and matching events/remediation templates;
  the deterministic risk engine (`risk_engine.py`); the typed tool layer
  (`tools.py`); the deterministic policy gate (`policy.py`).
- **Google ADK agent + Gemini reasoning (Batch 2)** -- one Google ADK agent
  (`agent.py`, `agent_tools.py`, `prompts.py`), Gemini 3.5 Flash as its
  model backend, environment-driven config (`config.py`) with no hardcoded
  credentials, and hallucination/prompt-injection guards.
- **Human approval + simulated action + verification (Batch 3)** -- the
  approval state machine (`approval.py`), the controlled synthetic-only
  action executor and audit trail (`orchestrator.py`, `audit.py`).
- **Firestore persistence (Batch 4)** -- the storage-agnostic
  `IncidentRepository` interface (`repository.py`), the offline
  `LocalRepository`, and the real `FirestoreRepository` adapter plus its
  guarded, demo-id-only `cleanup_incident`.
- **Cloud Run service, Secret Manager, judge UI (Batch 5)** -- the FastAPI
  HTTP entrypoint (`web.py`), `Dockerfile`/`.dockerignore`, the Cloud Run
  deployment (service `ai-raxbar-agent`, region `us-central1`), the Gemini
  API key wired in via a narrowly-scoped Secret Manager secret, the
  Firestore-backed hosted revision, and the self-contained judge-facing
  demo UI at `/demo` (`static/demo.html`).
- **Tests and docs** -- the entire offline test suite (`tests/`, 125 tests
  at last count) and all documentation (`docs/`, `README.md`).

The risk-scoring *concept* (transparent, rule-based, evidence-backed
assessment) is a common pattern in operations tooling and is not itself V3
IP; the rules, thresholds, code, data, agent, workflow, and infrastructure
here were written from scratch for this hackathon.

## What is NOT claimed

- No claim that this system controls, has ever controlled, or is connected
  to any real electrical-grid device or infrastructure.
- No claim of production deployment, production data, or production traffic
  -- every asset id, incident id, and event in this system is synthetic and
  explicitly guarded (`DEMO-*` / `HACKATHON-*` prefixes only, enforced at
  both the repository-cleanup layer and the public HTTP API layer).
- No claim that Gemini makes the risk, policy, or approval decision -- see
  `docs/ARCHITECTURE.md` for exactly which values are tool-owned,
  model-owned, human-owned, or simulated.
