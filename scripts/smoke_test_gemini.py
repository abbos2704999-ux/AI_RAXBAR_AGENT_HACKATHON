#!/usr/bin/env python3
"""Optional, explicit, opt-in live Gemini smoke test.

This script is NEVER run automatically by the test suite, by CI, or by any
other code in this repository. It is a manual command a human runs on
purpose, from a terminal, after confirming credentials are configured.

It makes exactly one live network call: analyzing a single synthetic
demo asset (default DEMO-TP-007) through the real ADK agent + real Gemini
model. No production data, no real assets, no write action -- it calls the
same read-only OBSERVE->DETECT->DIAGNOSE->PLAN path as the offline tests,
just with a real model backend instead of a scripted fake.

Usage:
    python3 scripts/smoke_test_gemini.py --yes [--asset-id DEMO-TP-007]

Requires GOOGLE_API_KEY or GEMINI_API_KEY (or Vertex AI env config) to
already be set in the environment. This script never prints, logs, or
otherwise displays the key value.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_raxbar_agent import agent, config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required. Confirms you intend to make a live network call to Gemini.",
    )
    parser.add_argument(
        "--asset-id",
        default="DEMO-TP-007",
        help="Synthetic demo asset_id to analyze (default: DEMO-TP-007).",
    )
    args = parser.parse_args()

    if not config.is_gemini_configured():
        print(
            "Gemini is not configured (no GOOGLE_API_KEY / GEMINI_API_KEY / "
            "Vertex AI env vars found). Nothing was called. Set credentials "
            "via environment variables and re-run explicitly if you want a "
            "live smoke test.",
        )
        return 1

    if not args.yes:
        print(
            "Gemini appears to be configured in this environment. This "
            "script is about to make ONE live network call to the Gemini "
            f"API (model: {config.get_model_name()!r}) to analyze synthetic "
            f"asset {args.asset_id!r}.\n"
            "Re-run with --yes to confirm and proceed. No API key value "
            "will ever be printed.",
        )
        return 1

    print(f"Running live Gemini smoke test against asset {args.asset_id!r}...")
    result = agent.analyze_incident(args.asset_id)
    print("\n--- IncidentAnalysis (live) ---")
    print(f"asset_id:            {result.asset_id}")
    print(f"risk_score:          {result.risk_score}")
    print(f"risk_level:          {result.risk_level}")
    print(f"evidence_refs:       {result.evidence_refs}")
    print(f"diagnosis:           {result.diagnosis}")
    print(f"uncertainties:       {result.uncertainties}")
    print(f"recommended_action:  {result.recommended_action}")
    print(f"reasoning_summary:   {result.reasoning_summary}")
    print(f"policy_class:        {result.policy_class}")
    print(f"approval_required:   {result.approval_required}")
    print(f"next_step:           {result.next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
