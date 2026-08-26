"""Offline fakes: an ADK model backend and a Firestore-shaped client.

`ScriptedFakeLlm` subclasses google.adk's real `BaseLlm` and plugs into a
real `google.adk.agents.Agent` + `InMemoryRunner`, so tests exercise the
actual ADK tool-calling loop (real tool dispatch, real FunctionResponse
plumbing) with zero network access -- only the model's responses are
scripted.

`FakeFirestoreClient` (and its `.collection()`/`.document()` helpers) is a
structural stand-in for `google.cloud.firestore.Client`: same
`collection(name).document(id).set(dict)` / `.get()` -> snapshot with
`.exists`/`.to_dict()` / `collection(name).stream()` surface, entirely
in-memory. It never imports `google.cloud.firestore` and never touches a
network, which is what lets `tests/test_repository.py` exercise
`firestore_repository.FirestoreRepository` fully offline.
"""

from __future__ import annotations

from typing import AsyncGenerator, Optional

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


class FakeFirestoreSnapshot:
    """Structural stand-in for a Firestore `DocumentSnapshot`."""

    def __init__(self, data: Optional[dict]) -> None:
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> Optional[dict]:
        return dict(self._data) if self._data is not None else None


class FakeFirestoreDocument:
    """Structural stand-in for a Firestore `DocumentReference`."""

    def __init__(self, collection: "FakeFirestoreCollection", doc_id: str) -> None:
        self._collection = collection
        self._doc_id = doc_id

    def set(self, data: dict) -> None:
        self._collection.client.network_call_count += 1
        self._collection.docs[self._doc_id] = dict(data)

    def get(self) -> FakeFirestoreSnapshot:
        self._collection.client.network_call_count += 1
        return FakeFirestoreSnapshot(self._collection.docs.get(self._doc_id))


class FakeFirestoreCollection:
    """Structural stand-in for a Firestore `CollectionReference`."""

    def __init__(self, client: "FakeFirestoreClient", name: str) -> None:
        self.client = client
        self.name = name
        self.docs: dict[str, dict] = {}

    def document(self, doc_id: str) -> FakeFirestoreDocument:
        return FakeFirestoreDocument(self, doc_id)

    def stream(self) -> list[FakeFirestoreSnapshot]:
        self.client.network_call_count += 1
        return [FakeFirestoreSnapshot(data) for data in self.docs.values()]


class FakeFirestoreClient:
    """Structural stand-in for `google.cloud.firestore.Client`: same
    `collection()/document()/get()/set()/stream()` surface, zero network
    access, zero dependency on the real `google-cloud-firestore` package.

    `network_call_count` lets tests assert exactly how many storage
    operations were attempted (e.g. to prove idempotent retries don't fan
    out into extra writes) -- every increment here is an in-memory dict
    operation, never a real network call, since this class never imports
    or touches `google.cloud.firestore`.
    """

    def __init__(self) -> None:
        self._collections: dict[str, FakeFirestoreCollection] = {}
        self.network_call_count = 0

    def collection(self, name: str) -> FakeFirestoreCollection:
        if name not in self._collections:
            self._collections[name] = FakeFirestoreCollection(self, name)
        return self._collections[name]
