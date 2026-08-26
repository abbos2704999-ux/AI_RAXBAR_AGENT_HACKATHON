# Live Verification Matrix

Every row below was verified against real Google Cloud infrastructure in
project `ai-raxbar-agent-hackathon`, using only synthetic data. See
`README.md` ("Live Verification Evidence" and the Batch 5B-5H sections) for
full narrative detail; this table is the condensed judge-facing summary.

| Component | Status | Evidence |
|---|---|---|
| Google ADK | LIVE_VERIFIED | Real ADK tool-calling loop executed against the live, deployed Cloud Run service (not an offline fake model) for `DEMO-TP-007`; the model's diagnosis/recommended action came from live tool results returned through ADK's real dispatch. |
| Gemini 3.5 Flash | LIVE_VERIFIED | Multiple real API responses received (local smoke test and hosted via Cloud Run), including one full successful run after Gemini key rotation and Tier 1 billing activation: non-empty diagnosis, `recommended_action = REBALANCE_LOAD`. |
| Cloud Run | LIVE_VERIFIED | Service `ai-raxbar-agent`, region `us-central1`, deployed and re-deployed across six revisions; `/health` and `/api/status` repeatedly returned `HTTP 200` from the live public URL. |
| Firestore | LIVE_VERIFIED | Live incident/approval/audit-record writes and reads confirmed via direct Firestore client reads, both in a standalone smoke test (`HACKATHON-SMOKE-001`) and as the hosted service's actual persistence backend (`AI_RAXBAR_REPOSITORY_BACKEND=firestore`) during a full hosted workflow. |
| Secret Manager | LIVE_VERIFIED | Gemini API key stored as secret `ai-raxbar-gemini-api-key`, mounted into Cloud Run as `GEMINI_API_KEY` via the runtime service identity; rotated live to a new key version (version 1 -> version 2) without the key value ever being printed, logged, or committed. |
| Human Approval | LIVE_VERIFIED | Hosted `POST /api/incidents/{id}/approve` moved a real `HIGH_IMPACT` incident from `PENDING` to `APPROVED`; a parallel run confirmed `POST .../reject` permanently blocks execution for that incident. |
| Policy Gate | LIVE_VERIFIED | `DEMO-TP-007`'s `REBALANCE_LOAD` action was independently classified `HIGH_IMPACT` by `policy.py` on every live run; `POST /api/incidents/{id}/execute` before approval consistently returned `HTTP 409`. |
| Simulated Action | LIVE_VERIFIED | Hosted `/execute` (post-approval) produced a real, measurable synthetic state change (`load_ratio` 1.3 -> 0.8) with no external system contacted. |
| Verification Loop | LIVE_VERIFIED | Same hosted execution returned `risk_before = 100`, `risk_after = 85`, `verification_result = IMPROVED`, deterministically recomputed, not asserted by the model. |
| Judge UI | LIVE_VERIFIED | `/demo` deployed to the same Cloud Run service; visually confirmed to render the full `INCIDENT -> ... -> AUDIT TRAIL` narrative using only live API responses (offline regression tests additionally pin the exact field contract the page depends on). |

All incidents created during verification were removed afterward via the
guarded, demo-id-only `cleanup_incident()` path; post-cleanup reads
confirmed the `incidents`, `approvals`, and `audit_records` Firestore
collections were left exactly as they were before each run.
