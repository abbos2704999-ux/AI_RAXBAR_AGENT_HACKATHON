# Safety Statement

**AI Raxbar Agent** is a synthetic-data demonstration of a safe pattern for
using an LLM inside a critical-infrastructure operations workflow. The
following are structural properties of the system, enforced in code and
covered by the offline test suite -- not policy promises layered on top.

- **Synthetic data only.** Every asset, event, and incident in this system
  is fictional. The public API accepts only identifiers starting with
  `DEMO-` or `HACKATHON-`; anything else is rejected before any other code
  runs.
- **No production infrastructure identifiers.** No real feeder names,
  coordinates, consumer data, crew names, CAS identifiers, spreadsheet IDs,
  or internal URLs appear anywhere in this repository, its data, or its
  live services.
- **No real grid command is ever issued.** The one write action in this
  system, `simulate_remediation`, mutates only an in-memory synthetic
  signal (e.g. a load ratio). It has no network client, no device
  protocol, and no code path to any external system -- simulated means
  simulated.
- **High-impact actions require human approval.** A `HIGH_IMPACT` action
  cannot execute without an explicit, identified human `APPROVE` decision.
  This is enforced twice independently (the orchestrator and the write tool
  itself), so there is no single code path whose removal would bypass it.
- **Gemini cannot override deterministic policy.** The model proposes a
  diagnosis and a candidate action; the risk score, the policy
  classification, and the approval requirement are all computed by plain,
  deterministic Python that never reads a value the model set.
- **Risk and evidence are tool-owned, not model-owned.** `risk_score`,
  `risk_level`, `risk_factors`, and `evidence_refs` come from the
  deterministic risk engine, independent of anything the model asserts. A
  recommended action or cited evidence reference the model invents that
  doesn't match real tool output is rejected and recorded as an
  uncertainty, never silently trusted.
- **All demo actions are auditable.** Every outcome -- blocked, rejected,
  executed, or failed -- is written to a persistent audit trail
  (Firestore in the hosted deployment), including the before/after state
  and the verification result, not just successful executions.
