"""Environment-driven configuration for the Batch 2 agent layer.

No credentials are hardcoded anywhere in this module or read from any file
other than the process environment. If the environment is not configured,
`is_gemini_configured()` returns False and callers must not attempt a
network call.
"""

from __future__ import annotations

import os

# Accept either name -- google-genai's client itself recognizes GOOGLE_API_KEY,
# and Gemini API docs commonly reference GEMINI_API_KEY. We check both but
# never print, log, or persist the value.
_API_KEY_ENV_VARS = ("GOOGLE_API_KEY", "GEMINI_API_KEY")

_VERTEX_ENV_VARS = ("GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION")

_DEFAULT_MODEL_NAME = "gemini-2.5-flash"


def get_model_name() -> str:
    """Returns the configured Gemini model name.

    Reads AI_RAXBAR_GEMINI_MODEL if set, else falls back to a fixed default.
    Never touches the network.
    """
    return os.environ.get("AI_RAXBAR_GEMINI_MODEL", _DEFAULT_MODEL_NAME)


def _has_api_key() -> bool:
    return any(os.environ.get(name) for name in _API_KEY_ENV_VARS)


def _has_vertex_config() -> bool:
    uses_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in (
        "1",
        "true",
        "yes",
    )
    return uses_vertex and all(os.environ.get(name) for name in _VERTEX_ENV_VARS)


def is_gemini_configured() -> bool:
    """True if the environment has enough configuration to attempt a live
    Gemini call (either an API key, or Vertex AI project + location with the
    Vertex flag enabled). Does not validate the credential is *valid* --
    only that a live call could be attempted.

    Callers must still treat any live call as opt-in and never trigger one
    automatically from this check alone.
    """
    return _has_api_key() or _has_vertex_config()
