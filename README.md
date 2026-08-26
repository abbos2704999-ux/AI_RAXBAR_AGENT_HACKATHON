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
An LLM (Batch 2+) will *call* these typed tools and *plan* over their
outputs, but it cannot change a risk score, override a policy decision, or
execute an action the policy gate blocks.

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

### Not yet implemented (NEXT / Batch 2)

- Gemini + Google ADK tool-calling over this foundation.
- Google Cloud (Cloud Run, Firestore, or any other GCP service).
- A real approval UI (Batch 1 represents approval as a typed model only).
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
used.
