# Cloud Run deployment (template only -- not yet executed)

Status: **NOT YET DEPLOYED.** This document records the command shape a
human operator will run in Batch 5B. Nothing in this repository runs any
command below automatically, and none of it has been executed as part of
Batch 5A.

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
- `--no-allow-unauthenticated` is the recommended default for this
  synthetic-data demo service; switch to `--allow-unauthenticated` only if
  public access is explicitly wanted.
- Omitting `AI_RAXBAR_REPOSITORY_BACKEND` (or setting it to `local`) runs
  Cloud Run against the offline in-memory repository instead of Firestore --
  useful for a first smoke deploy before wiring up persistence.

## Post-deploy checks (manual, Batch 5B)

```bash
curl -s "${SERVICE_URL}/health"
curl -s "${SERVICE_URL}/api/status"
```

Confirm `/health` returns `{"status": "ok"}` and `/api/status` reports the
expected `gemini_integration` / `firestore_integration` flags with no
secret values present, before exercising any `/api/incidents/*` endpoint
with a synthetic `DEMO-*` asset id.
