# Pre-existing vs. New Work Disclosure

## PRE-EXISTING

**AI RAXBAR V3** was a Google Apps Script-based deterministic ETL / scoring /
dashboard system, built prior to this hackathon. It is reference-only: it
informed the general *idea* of a deterministic, evidence-based risk scoring
approach, but no source code, configuration, identifiers, credentials, asset
data, or infrastructure from V3 is copied, imported, or referenced in this
repository.

No V3 source code, TP numbers, feeder names, coordinates, consumer data,
crew names, CAS identifiers, spreadsheet IDs, internal URLs, or any other
private/internal identifiers appear anywhere in this repository.

## NEW HACKATHON WORK

**Everything in this repository** is new work written for this hackathon:

- `src/ai_raxbar_agent/` -- all typed models, the deterministic risk engine,
  the typed tool layer, and the policy gate (new implementation).
- `data/` -- 12 entirely fictional, clearly labeled synthetic assets
  (`DEMO-TP-001` .. `DEMO-TP-012`) and matching synthetic events and
  remediation templates.
- `tests/` -- new offline test suite.
- `docs/`, `README.md` -- new documentation.

The risk-scoring *concept* (transparent, rule-based, evidence-backed
assessment) is a common pattern in operations tooling and is not itself V3
IP; the rules, thresholds, code, and data here were written from scratch for
Batch 1 of this hackathon.

## Batch 2 additions (new hackathon work)

- `src/ai_raxbar_agent/agent.py`, `agent_tools.py`, `prompts.py`,
  `config.py` -- new orchestration layer: one Google ADK agent, typed
  read-only tool wrappers around the Batch 1 tools, the system prompt, and
  environment-variable-driven configuration. No credentials are hardcoded
  anywhere in this repository.
- `tests/test_agent.py`, `tests/fakes.py` -- new offline test suite for the
  agent layer, including a prompt-injection safety test.
- `scripts/smoke_test_gemini.py` -- new, explicit, opt-in, human-run live
  Gemini smoke test script. Not run automatically by anything in this
  repository.

## Scope boundary for Batch 2

Batch 2 adds Gemini + Google ADK tool-calling on top of the unmodified
Batch 1 foundation, but still makes no live network call from any test, and
still touches no Google Cloud service. `scripts/smoke_test_gemini.py` is
the one exception -- a manual, opt-in command a human runs on purpose,
never invoked automatically. See `README.md` for current scope and what
remains for later batches (human-approval UI, automatic action execution,
GCP deployment).
