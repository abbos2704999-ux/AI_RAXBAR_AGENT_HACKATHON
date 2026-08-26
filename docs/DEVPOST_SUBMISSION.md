# Devpost Architecture Summary

AI Raxbar Agent demonstrates a safe pattern for putting an LLM inside a
critical-infrastructure operations loop: OBSERVE -> DETECT -> DIAGNOSE ->
PLAN -> POLICY GATE -> HUMAN APPROVAL -> ACT (SIMULATED) -> VERIFY ->
AUDIT. The architecture is built around one rule -- AI does not own the
truth, evidence does -- enforced as hard boundaries, not a prompt
instruction.

A deterministic risk engine computes risk score, level, and evidence
references from synthetic telemetry before Gemini 3.5 Flash, running
inside a Google ADK agent, ever sees the incident; the model reads that
evidence only through typed tools and proposes a diagnosis and a candidate
remediation. A deterministic policy gate then classifies that action's
impact independently of anything the model claims, because a policy
decision that could be talked into changing isn't a policy decision.
High-impact actions require an explicit human approval before execution,
checked in two independent code paths so no single removal bypasses it.
The one write action, `simulate_remediation`, only ever mutates synthetic
in-memory state -- there is no path to a real grid device. Every outcome,
including blocked and rejected ones, is persisted to a Firestore audit
trail, so the record exists whether or not a given run succeeds. The full
pipeline runs live on Cloud Run, with the Gemini credential in Secret
Manager and Firestore for durable state -- a small, auditable machine
around one LLM call, not the other way around.
