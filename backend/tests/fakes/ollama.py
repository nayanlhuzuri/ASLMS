"""`FakeOllama`: an `httpx.MockTransport` standing in for a local Ollama server (design `assistant-ollama`, "Tests").
It gives scripted `/api/chat` replies and failures, states for `/api/ps`, `/api/tags` and `/api/version`, and records
every request body. Tests only; never in the application. No test calls a real model or needs a GPU."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx

from aslms.integration.ollama import OllamaClient

MODEL = "qwen3.5:4b"
GB = 1024**3


def chat_reply(
    content: str, *, done_reason: str = "stop", prompt_eval_count: int = 900, **extra: Any
) -> dict:
    """A `/api/chat` reply as Ollama writes it (non-streaming)."""
    return {
        "model": MODEL,
        "created_at": "2026-10-27T10:00:00.000000000Z",
        "message": {"role": "assistant", "content": content, **extra},
        "done": True,
        "done_reason": done_reason,
        "total_duration": 1_800_000_000,
        "load_duration": 20_000_000,
        "prompt_eval_count": prompt_eval_count,
        "prompt_eval_duration": 300_000_000,
        "eval_count": 60,
        "eval_duration": 1_000_000_000,
    }


class Delay:
    """A scripted chat step that waits `seconds` before answering (for the timeout test)."""

    def __init__(self, seconds: float, reply: dict | None = None):
        self.seconds = seconds
        self.reply = reply or chat_reply("late [S1]")


class FakeOllama:
    """`replies`: scripted `/api/chat` steps, used in order (a dict reply, an `httpx.Response`, an exception to raise,
    a `Delay`, or a callable taking the request body); when empty, `default` answers. `held`, `loaded`, `size`,
    `size_vram` and `version` shape the info calls; `reachable=False` refuses every connection."""

    def __init__(
        self,
        *,
        model: str = MODEL,
        held: bool = True,
        loaded: bool = True,
        size: int = int(3.7 * GB),
        size_vram: int | None = None,
        version: str = "0.40.1",
        reachable: bool = True,
        default: str = "The court directed the respondents to file an affidavit [S1].",
    ):
        self.model = model
        self.held = held
        self.loaded = loaded
        self.size = size
        self.size_vram = size if size_vram is None else size_vram
        self.version = version
        self.reachable = reachable
        self.default = default
        self.replies: list[Any] = []
        self.requests: list[tuple[str, str, Any]] = []
        self.loads = 0

    # ------------------------------------------------------------------------------------------------ inspection

    @property
    def chats(self) -> list[dict]:
        """The `/api/chat` request bodies, in order."""
        return [body for method, path, body in self.requests if path == "/api/chat"]

    def sent_text(self) -> str:
        """Everything sent to the model, as one string (planted words are looked for here)."""
        return json.dumps(self.chats, ensure_ascii=False)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def client(self) -> OllamaClient:
        return OllamaClient("http://ollama.test:11434", transport=self.transport())

    # ------------------------------------------------------------------------------------------------ the server

    def handle(self, request: httpx.Request):
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body))
        if not self.reachable:
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path
        if path == "/api/version":
            return httpx.Response(200, json={"version": self.version})
        if path == "/api/tags":
            models = []
            if self.held:
                models.append(
                    {"name": self.model, "model": self.model, "size": self.size, "digest": "sha256:abc123"}
                )
            return httpx.Response(200, json={"models": models})
        if path == "/api/ps":
            models = []
            if self.loaded:
                models.append(
                    {
                        "name": self.model,
                        "model": self.model,
                        "size": self.size,
                        "size_vram": self.size_vram,
                        "digest": "sha256:abc123",
                        "expires_at": "2318-01-01T00:00:00.000000000+05:30",
                    }
                )
            return httpx.Response(200, json={"models": models})
        if path == "/api/generate":
            self.loads += 1
            self.loaded = True
            return httpx.Response(200, json={"model": self.model, "response": "", "done": True})
        if path == "/api/chat":
            step: Any = self.replies.pop(0) if self.replies else chat_reply(self.default)
            return self._step(step, body, request)
        return httpx.Response(404, json={"error": "not found"})

    def _step(self, step: Any, body: Any, request: httpx.Request):
        if isinstance(step, Delay):

            async def later():
                await asyncio.sleep(step.seconds)
                return httpx.Response(200, json=step.reply)

            return later()
        if isinstance(step, BaseException):
            if isinstance(step, httpx.HTTPError) and getattr(step, "_request", None) is None:
                try:
                    step.request = request
                except AttributeError:
                    pass
            raise step
        if isinstance(step, httpx.Response):
            return step
        if isinstance(step, Callable):
            return self._step(step(body), body, request)
        return httpx.Response(200, json=step)
