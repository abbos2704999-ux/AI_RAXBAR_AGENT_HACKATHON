# Cloud Run deployment (reproducible template + current live state)

Status: **DEPLOYED AND LIVE.** The service `ai-raxbar-agent` is running in
region `us-central1` (project `ai-raxbar-agent-hackathon`) and serving the
judge-facing demo:

| Endpoint | Live status |
|---|---|
| `https://ai-raxbar-agent-ti5u2iy34q-uc.a.run.app/health` | `HTTP 200` |
| `https://ai-raxbar-agent-ti5u2iy34q-uc.a.run.app/api/status` | `HTTP 200` |
| `https://ai-raxbar-agent-ti5u2iy34q-uc.a.run.app/demo` | `HTTP 200` |

This document remains the **reproducible template** for that deployment:
the commands below are parameterised so anyone can redeploy this repository
into their own project. Nothing in this repository runs any command below
automatically -- every deployment step is a deliberate human action.

## Prerequisites (human, one-time, outside this repo)

- `gcloud auth login` / `gcloud auth application-default login` completed.
- Target GCP project has the Cloud Run, Artifact Registry (or Container
  Registry), and Firestore APIs enabled.
- A Firestore Native database exists in the target project (see the Batch 4
  live-verification evidence in the README for how that was confirmed in
  `ai-raxbar-agent-hackathon`).
- If live Gemini calls are wanted, a Gemini API key is available to store as
  a Cloud Run environment variable or Secret Manager secret -- **never** as
  a file baked into the image.

## Build the image

```bash
docker build -t "${IMAGE_URI}" .
docker push "${IMAGE_URI}"
```

Where `IMAGE_URI` is something like
`REGION-docker.pkg.dev/PROJECT_ID/REPO_NAME/ai-raxbar-agent:TAG` for
Artifact Registry.

## Deploy (template -- fill in and run manually)

```bash
gcloud run deploy "${SERVICE_NAME:-ai-raxbar-agent}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --image "${IMAGE_URI}" \
  --platform managed \
  --no-allow-unauthenticated \
  --service-account "${RUNTIME_SERVICE_ACCOUNT_EMAIL}" \
  --set-env-vars "AI_RAXBAR_REPOSITORY_BACKEND=firestore" \
  --set-env-vars "AI_RAXBAR_GEMINI_MODEL=gemini-3.5-flash" \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID}" \
  --set-secrets "GEMINI_API_KEY=${GEMINI_API_KEY_SECRET_NAME}:latest"
```

Notes on every placeholder:

- `PROJECT_ID`, `REGION`, `SERVICE_NAME`, `IMAGE_URI` -- fill in for the
  target environment; nothing here is hardcoded to a specific project.
- `RUNTIME_SERVICE_ACCOUNT_EMAIL` -- a dedicated Cloud Run service identity
  with least-privilege Firestore access (e.g. `roles/datastore.user`
  scoped to this project). Firestore auth then flows through Application
  Default Credentials picked up automatically from that service identity
  (`firestore_repository.build_live_client()`) -- **no service-account JSON
  key file is ever created, downloaded, or copied into the image.**
- `GEMINI_API_KEY_SECRET_NAME` -- a Secret Manager secret reference, mounted
  as the `GEMINI_API_KEY` env var at runtime via `--set-secrets`. An
  operator who instead wants Vertex AI auth would drop `--set-secrets` and
  set `GOOGLE_GENAI_USE_VERTEXAI=true` plus `GOOGLE_CLOUD_LOCATION` instead
  (see `config.py`).
- **Access policy -- deliberate divergence from the template default.**
  The template above shows `--no-allow-unauthenticated`, which is the right
  default for a private redeployment. **The judge-facing hackathon
  deployment is deliberately different: it runs with
  `--allow-unauthenticated`**, so a Devpost/Google judge can open `/demo`
  and reproduce the full workflow without a Google Cloud account or a
  signed token. That is a conscious, scoped trade-off, and it is safe only
  because of what the service can do:
  - every endpoint rejects any identifier outside `DEMO-*` / `HACKATHON-*`
    (`web.py::require_synthetic_identifier`), so there is no reachable
    real/production data;
  - the only write action is `tools.simulate_remediation`, which mutates
    in-memory synthetic state and has no network client or device
    protocol;
  - `HIGH_IMPACT` actions still require an explicit human approval,
    enforced independently in the orchestrator and in the write tool, so
    an anonymous caller cannot execute one without first approving it
    through the same audited state machine;
  - `/api/status` reports configuration flags only -- never a credential,
    key, or raw project id.

  Residual exposure that public access does create: an anonymous caller can
  trigger `POST /api/incidents/analyze`, which costs one billed Gemini
  call. This is a **quota/cost** exposure, not a data or credential
  exposure. Mitigation for the judging window is a Cloud Run
  `--max-instances` cap plus Gemini quota monitoring; after judging, the
  service should be switched back to `--no-allow-unauthenticated` or torn
  down.
- Omitting `AI_RAXBAR_REPOSITORY_BACKEND` (or setting it to `local`) runs
  Cloud Run against the offline in-memory repository instead of Firestore --
  useful for a first smoke deploy before wiring up persistence.

## Post-deploy checks (manual)

```bash
curl -s "${SERVICE_URL}/health"
curl -s "${SERVICE_URL}/api/status"
```

Confirm `/health` returns `{"status": "ok"}` and `/api/status` reports the
expected `gemini_integration` / `firestore_integration` flags with no
secret values present, before exercising any `/api/incidents/*` endpoint
with a synthetic `DEMO-*` asset id.
