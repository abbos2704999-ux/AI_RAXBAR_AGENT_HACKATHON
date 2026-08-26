"""Batch 2 agentic reasoning layer: one Google ADK agent, backed by Gemini,
that reasons over Batch 1's deterministic evidence and produces a structured
`IncidentAnalysis`.

Loop implemented here: OBSERVE -> DETECT -> DIAGNOSE -> PLAN -> POLICY GATE.
This module deliberately stops there -- it never calls
`ai_raxbar_agent.tools.simulate_remediation` and the ADK agent's tool list
never includes it. HIGH_IMPACT recommendations come back with
`approval_required=True` and `next_step="WAIT_FOR_HUMAN_APPROVAL"`; nothing
in this module attempts to clear that gate automatically.

Freeze principle: every field on `IncidentAnalysis` that represents ground
truth (risk_score, risk_level, evidence_refs, policy_class,
approval_required) is computed here in plain deterministic Python from
Batch 1's risk engine and policy gate -- never read from the model's
proposal. The model (via `propose_incident_analysis`) only supplies the
narrative fields: diagnosis, uncertainties, reasoning_summary, and a
*candidate* recommended_action that is validated against real remediation
templates before it is trusted.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from google.adk.agents import Agent
from google.adk.models.base_llm import BaseLlm
from google.adk.runners import InMemoryRunner
from google.genai import types

from . import agent_tools, config, prompts
from . import tools as batch1_tools
from .data_store import store
from .models import ImpactClass, RiskLevel
from .policy import evaluate_policy

AGENT_NAME = "ai_raxbar_incident_agent"


@dataclass
class IncidentAnalysis:
    """Structured Batch 2 output. Ground-truth fields (risk_score,
    risk_level, evidence_refs, policy_class, approval_required) are always
    computed by deterministic code, never by the model."""

    asset_id: str
    risk_score: int
    risk_level: RiskLevel
    evidence_refs: list[str]
    diagnosis: str
    uncertainties: list[str] = field(default_factory=list)
    recommended_action: Optional[str] = None
    reasoning_summary: str = ""
    policy_class: Optional[ImpactClass] = None
    approval_required: bool = False
    next_step: str = "NO_ACTION_RECOMMENDED"


def propose_incident_analysis(
    diagnosis: str,
    reasoning_summary: str,
    recommended_action: str = "",
    uncertainties: Optional[list[str]] = None,
    cited_evidence_refs: Optional[list[str]] = None,
) -> dict:
    """Submit your final structured incident analysis. Call this exactly
    once, after you have gathered evidence with the read-only tools, and
    treat it as the last step of your turn.

    Args:
      diagnosis: plain-language explanation of the likely cause(s), based
        only on evidence returned by your tools.
      reasoning_summary: a short, concrete, evidence-based justification for
        your recommendation. Not a chain of thought -- a user-facing summary.
      recommended_action: exactly one action_type returned by
        get_remediation_candidates, or an empty string if none apply.
      uncertainties: open questions or points you are not confident about.
      cited_evidence_refs: evidence_refs (from get_risk_evidence) that
        support your diagnosis.
    """
    # This tool is a structured-output capture point, not an executor. It
    # performs no action and mutates no state; the real work happens when
    # analyze_incident() reads back the model's function-call arguments.
    return {"status": "recorded"}


def build_agent(model: Optional[str | BaseLlm] = None) -> Agent:
    """Constructs the single primary ADK agent for this batch.

    Typed, read-only access to Batch 1 evidence tools plus the structured
    output tool above. `simulate_remediation` is never in this list --
    policy stays outside model discretion.
    """
    return Agent(
        name=AGENT_NAME,
        model=model if model is not None else config.get_model_name(),
        description=(
            "Analyzes synthetic grid-asset incidents using deterministic "
            "evidence tools and proposes a remediation plan for policy and "
            "human review. Cannot execute or approve any action."
        ),
        instruction=prompts.SYSTEM_INSTRUCTION,
        tools=[
            agent_tools.get_asset_context,
            agent_tools.get_risk_evidence,
            agent_tools.get_recent_events,
            agent_tools.get_remediation_candidates,
            propose_incident_analysis,
        ],
    )


def _extract_last_function_call_args(events: list[Any], tool_name: str) -> Optional[dict]:
    """Scans ADK run events for the most recent call to `tool_name` and
    returns its arguments, or None if it was never called."""
    found: Optional[dict] = None
    for event in events:
        content = getattr(event, "content", None)
        if content is None or not content.parts:
            continue
        for part in content.parts:
            fc = getattr(part, "function_call", None)
            if fc is not None and fc.name == tool_name:
                found = dict(fc.args or {})
    return found


async def _analyze_incident_async(
    asset_id: str,
    agent: Agent,
    *,
    user_id: str = "operator",
    max_events: int = 50,
) -> IncidentAnalysis:
    # Fail safe on an unknown asset before any model call is made.
    store.get_asset(asset_id)

    # Ground truth, fetched independently of anything the model does or
    # claims. These values -- and only these -- populate the
    # risk/evidence/policy fields of the final IncidentAnalysis.
    risk = batch1_tools.get_risk_evidence(asset_id)
    candidates = batch1_tools.get_remediation_candidates(asset_id)
    candidate_by_action = {c.action_type: c for c in candidates}

    runner = InMemoryRunner(agent=agent, app_name=AGENT_NAME)
    session = await runner.session_service.create_session(app_name=AGENT_NAME, user_id=user_id)

    user_message = types.Content(
        role="user",
        parts=[types.Part(text=f"Analyze asset {asset_id}.")],
    )

    events: list[Any] = []
    run_error: Optional[str] = None
    try:
        async for event in runner.run_async(
            user_id=user_id, session_id=session.id, new_message=user_message
        ):
            events.append(event)
            if len(events) >= max_events:
                break
    except Exception as exc:  # noqa: BLE001 -- any tool-dispatch failure (e.g.
        # a model requesting a tool that was never registered, such as
        # simulate_remediation) must abort safely rather than propagate an
        # unhandled crash or silently pretend the run succeeded.
        run_error = str(exc)

    proposal = _extract_last_function_call_args(events, "propose_incident_analysis")

    diagnosis = ""
    reasoning_summary = ""
    uncertainties: list[str] = []
    recommended_action: Optional[str] = None

    if run_error is not None:
        uncertainties.append(
            "Agent run aborted before producing a valid proposal (rejected "
            f"tool call or internal error): {run_error}"
        )

    if proposal is None:
        if run_error is None:
            uncertainties.append(
                "Model did not submit a structured proposal via "
                "propose_incident_analysis; no recommendation available."
            )
    else:
        diagnosis = str(proposal.get("diagnosis") or "")
        reasoning_summary = str(proposal.get("reasoning_summary") or "")

        raw_uncertainties = proposal.get("uncertainties") or []
        if isinstance(raw_uncertainties, list):
            uncertainties.extend(str(u) for u in raw_uncertainties)
        elif raw_uncertainties:
            uncertainties.append(str(raw_uncertainties))

        raw_action = proposal.get("recommended_action") or None
        if raw_action:
            if raw_action in candidate_by_action:
                recommended_action = raw_action
            else:
                uncertainties.append(
                    f"Model recommended action_type {raw_action!r}, which is "
                    "not a valid remediation candidate for this asset; ignored."
                )

        cited_refs = proposal.get("cited_evidence_refs") or []
        if isinstance(cited_refs, list):
            real_refs = set(risk.evidence_refs)
            hallucinated = sorted({r for r in cited_refs if r not in real_refs})
            if hallucinated:
                uncertainties.append(
                    "Rejected unsupported evidence reference(s) cited by the "
                    "model (not present in deterministic evidence): "
                    + ", ".join(hallucinated)
                )

    # Deterministic policy gate. The model never sets policy_class or
    # approval_required -- those two lines are the entire gate.
    policy_class: Optional[ImpactClass] = None
    approval_required = False
    if recommended_action is not None:
        template = candidate_by_action[recommended_action]
        policy_decision = evaluate_policy(recommended_action, template.impact_class)
        policy_class = template.impact_class
        approval_required = policy_decision.requires_human_approval

    if recommended_action is None:
        next_step = "NO_ACTION_RECOMMENDED"
    elif approval_required:
        next_step = "WAIT_FOR_HUMAN_APPROVAL"
    else:
        # Batch 2 stops before real action orchestration regardless of
        # policy class -- this only records that policy would allow it.
        next_step = "POLICY_CLEARED_NO_AUTO_EXECUTION_THIS_BATCH"

    return IncidentAnalysis(
        asset_id=asset_id,
        risk_score=risk.risk_score,
        risk_level=risk.risk_level,
        evidence_refs=list(risk.evidence_refs),
        diagnosis=diagnosis,
        uncertainties=uncertainties,
        recommended_action=recommended_action,
        reasoning_summary=reasoning_summary,
        policy_class=policy_class,
        approval_required=approval_required,
        next_step=next_step,
    )


def analyze_incident(
    asset_id: str,
    *,
    agent: Optional[Agent] = None,
    user_id: str = "operator",
) -> IncidentAnalysis:
    """Synchronous entry point: run the OBSERVE->DETECT->DIAGNOSE->PLAN loop
    for one asset and return a policy-gated IncidentAnalysis.

    Pass `agent=` with a pre-built ADK Agent (e.g. one constructed with a
    fake/offline model) for testing without any network access. With no
    `agent`, builds a live agent via `build_agent()`, which will attempt a
    real Gemini call the first time it is run -- callers driving that path
    must have already confirmed `config.is_gemini_configured()`.
    """
    if agent is None:
        agent = build_agent()
    return asyncio.run(_analyze_incident_async(asset_id, agent, user_id=user_id))
