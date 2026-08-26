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

## Scope boundary for Batch 1

This batch is deliberately offline and deterministic. It does not call
Gemini, Google ADK, or any Google Cloud service, and it makes no network
calls of any kind. See `README.md` for what is planned for Batch 2.
