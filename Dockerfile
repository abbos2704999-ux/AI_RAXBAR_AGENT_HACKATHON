# Batch 5A: Cloud Run-shaped container image. Builds and runs the
# `ai_raxbar_agent.web:app` FastAPI service. This file only prepares the
# image -- nothing in this repository builds, pushes, or deploys it
# automatically.
#
# Editable install (`pip install -e`, not a wheel install) is deliberate:
# `data_store.py` resolves its synthetic-data JSON files relative to the
# source tree (`Path(__file__).resolve().parents[2] / "data"`), the same
# way local development (`pip install -e ".[dev]"`) already works. Keeping
# /app/src and /app/data laid out identically to the repo root preserves
# that path with no code change.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Only the files the service needs at build/run time -- no .env, no
# credentials, no test suite, no docs, no V3 source/data (none of which
# exist in this repository; excluded defensively via .dockerignore too).
COPY pyproject.toml ./
COPY src ./src
COPY data ./data

# Gemini (agent) + Firestore (persistence) + FastAPI/uvicorn (this service).
# No service-account JSON is ever copied into the image -- Gemini reads its
# API key from the environment at runtime (Batch 5B: Cloud Run env var /
# Secret Manager), and Firestore authenticates via the Cloud Run service
# identity (Application Default Credentials), never a key file.
RUN pip install --no-cache-dir -e ".[agent,firestore,web]"

# Non-root runtime user.
RUN useradd --create-home --uid 10001 appuser
USER appuser

# Cloud Run injects PORT; default it for local `docker run`.
ENV PORT=8080
EXPOSE 8080

# Deterministic startup: no reload, no auto-migrations, no implicit
# Gemini/Firestore call. `/health` answers before either backend is ever
# touched (see web.py).
CMD ["sh", "-c", "uvicorn ai_raxbar_agent.web:app --host 0.0.0.0 --port ${PORT}"]
