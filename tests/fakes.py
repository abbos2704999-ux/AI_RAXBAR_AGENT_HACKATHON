"""Offline fake ADK model backend.

`ScriptedFakeLlm` subclasses google.adk's real `BaseLlm` and plugs into a
real `google.adk.agents.Agent` + `InMemoryRunner`, so tests exercise the
actual ADK tool-calling loop (real tool dispatch, real FunctionResponse
plumbing) with zero network access -- only the model's responses are
scripted.
"""

from __future__ import annotations

from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import Field


class ScriptedFakeLlm(BaseLlm):
    """Plays back a fixed sequence of model turns.

    Each entry in `script` is either {"call": tool_name, "args": {...}}
    (emits a function_call) or {"text": "..."} (emits final text and ends
    the turn). Steps are played back in order regardless of tool results,
    since tests fully control what evidence is available.
    """

    model: str = "fake-gemini-script"
    script: list[dict] = Field(default_factory=list)
    calls_made: list[str] = Field(default_factory=list)

    _step: int = 0

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        if self._step >= len(self.script):
            yield LlmResponse(
                content=types.Content(role="model", parts=[types.Part(text="")]),
                turn_complete=True,
            )
            return

        step = self.script[self._step]
        self._step += 1

        if "call" in step:
            self.calls_made.append(step["call"])
            part = types.Part(
                function_call=types.FunctionCall(name=step["call"], args=step.get("args", {}))
            )
            yield LlmResponse(content=types.Content(role="model", parts=[part]))
        else:
            yield LlmResponse(
                content=types.Content(role="model", parts=[types.Part(text=step.get("text", ""))]),
                turn_complete=True,
            )
