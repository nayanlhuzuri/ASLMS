"""The HTTP client of a local Ollama server (design `assistant-ollama`, decisions 11 and 12): the only place an Ollama
call is made. It knows nothing of cases or documents.

Calls (field names from Ollama's published API documentation and the owner's test of 27 Oct 2026):
- `chat` — `POST /api/chat` (non-streaming); `load` — `POST /api/generate` with only `model` and `keep_alive`
  (Ollama's documented way to load a model); `loaded` — `GET /api/ps`; `models` — `GET /api/tags`; `version` —
  `GET /api/version`; synchronous twins of the last three for the health card and the CLI.

Errors map onto the Case Assistant contract's existing types: a connection failure, a connect timeout, a 5xx (Ollama's
busy 503 included) and a 404 (model missing) are `SourceTraceUnavailable`; a 400 is `SourceTraceRejected`; a reply
that is not JSON, has no `message.content` or has `done` false is `SourceTraceProtocolError`. A read timeout is left
to the caller's wait (`TimeoutError`). Response bodies are never logged.

No cloud model (decision 12): `model_name_ok` refuses a name or tag holding `cloud`, and `url_problem` refuses an
address on `ollama.com` (or a subdomain), with user information or with a query. There is no API-key setting."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from aslms.integration.sourcetrace.connector import (
    SourceTraceProtocolError,
    SourceTraceRejected,
    SourceTraceUnavailable,
)

MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,150}(:[A-Za-z0-9._-]{1,60})?$")
CLOUD_DOMAIN = "ollama.com"
LOCAL_MIN_BYTES = 100 * 1024 * 1024  # a model held locally is at least this big; a cloud stub is a few KB
MIN_VERSION = (0, 40)
CONNECT_SECONDS = 3.0
INFO_SECONDS = 5.0


# ------------------------------------------------------------------------------------------------ the cloud rule


def model_name_ok(name: str | None) -> bool:
    """Decision 12: the pattern, and no `cloud` in the name or tag (case-insensitive)."""
    value = (name or "").strip()
    return bool(MODEL_NAME_RE.match(value)) and "cloud" not in value.lower()


def cloud_host(url: str | None) -> bool:
    """True when the address is on `ollama.com` or any subdomain."""
    host = (urlsplit((url or "").strip()).hostname or "").lower().rstrip(".")
    return host == CLOUD_DOMAIN or host.endswith("." + CLOUD_DOMAIN)


def url_problem(url: str | None) -> str | None:
    """Why `ASSISTANT_OLLAMA_URL` is refused, in words without the value, or None."""
    raw = (url or "").strip()
    try:
        parts = urlsplit(raw)
    except ValueError:
        return "is not a valid http:// or https:// address"
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "is not a valid http:// or https:// address"
    if cloud_host(raw):
        return "points at Ollama's cloud (ollama.com); only a local model on Government servers is allowed"
    if parts.username is not None or parts.password is not None:
        return "carries user information; give the address only"
    if parts.query or parts.fragment:
        return "carries a query or fragment; give the address only"
    return None


def full_name(name: str) -> str:
    """`qwen3.5` is `qwen3.5:latest` in Ollama's lists."""
    return name if ":" in name.rsplit("/", 1)[-1] else f"{name}:latest"


def parse_version(value: str | None) -> tuple[int, ...] | None:
    m = re.match(r"^\s*v?(\d+)\.(\d+)(?:\.(\d+))?", value or "")
    if not m:
        return None
    return tuple(int(g) for g in m.groups() if g is not None)


# ------------------------------------------------------------------------------------------------ replies


@dataclass(frozen=True)
class OllamaReply:
    """One `/api/chat` reply: the text, the tool calls (verbatim), the stop reason, counts and durations (ns)."""

    content: str
    done_reason: str | None
    model: str | None
    prompt_eval_count: int | None
    eval_count: int | None
    total_duration: int | None
    load_duration: int | None
    eval_duration: int | None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class ModelState:
    """What `/api/version`, `/api/tags` and `/api/ps` say about one model. `reason` (when not ready): `unreachable`,
    `missing`, `not_local`, `cloud` or None. Never holds the address."""

    reachable: bool
    version: str | None = None
    held: bool = False
    held_size: int | None = None
    local: bool = False
    loaded: bool = False
    size: int | None = None
    size_vram: int | None = None
    expires_at: str | None = None
    digest: str | None = None
    reason: str | None = None

    @property
    def ready(self) -> bool:
        return self.reachable and self.local and self.loaded

    @property
    def version_ok(self) -> bool:
        parsed = parse_version(self.version)
        return parsed is not None and parsed[:2] >= MIN_VERSION

    @property
    def on_gpu(self) -> str | None:
        """`full`, `partial`, `none` or None (not loaded)."""
        if not self.loaded or not self.size:
            return None
        vram = self.size_vram or 0
        if vram >= self.size:
            return "full"
        return "partial" if vram > 0 else "none"


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def parse_chat(data: Any) -> OllamaReply:
    """A `/api/chat` reply, or `SourceTraceProtocolError` (not an object, no `message.content`, `done` false)."""
    if not isinstance(data, dict):
        raise SourceTraceProtocolError("the model's reply is not a JSON object")
    message = data.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise SourceTraceProtocolError("the model's reply has no message content")
    if data.get("done") is not True:
        raise SourceTraceProtocolError("the model's reply is not complete")
    calls = message.get("tool_calls")
    return OllamaReply(
        content=message["content"],
        done_reason=data.get("done_reason") if isinstance(data.get("done_reason"), str) else None,
        model=data.get("model") if isinstance(data.get("model"), str) else None,
        prompt_eval_count=_int(data.get("prompt_eval_count")),
        eval_count=_int(data.get("eval_count")),
        total_duration=_int(data.get("total_duration")),
        load_duration=_int(data.get("load_duration")),
        eval_duration=_int(data.get("eval_duration")),
        tool_calls=[c for c in calls if isinstance(c, dict)] if isinstance(calls, list) else [],
        raw=data,
    )


def _models(data: Any) -> list[dict[str, Any]]:
    models = data.get("models") if isinstance(data, dict) else None
    return [m for m in models if isinstance(m, dict)] if isinstance(models, list) else []


def _named(models: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    want = full_name(name)
    for m in models:
        for key in ("name", "model"):
            got = m.get(key)
            if isinstance(got, str) and full_name(got) == want:
                return m
    return None


def model_state(name: str, version: Any, tags: Any, ps: Any) -> ModelState:
    """Decisions 12, 13 and 17 from the three answers (None: that call failed)."""
    if tags is None:
        return ModelState(reachable=False, reason="unreachable")
    ver = version.get("version") if isinstance(version, dict) else None
    ver = ver if isinstance(ver, str) else None
    if not model_name_ok(name):
        return ModelState(reachable=True, version=ver, reason="cloud")
    held = _named(_models(tags), name)
    if held is None:
        return ModelState(reachable=True, version=ver, reason="missing")
    held_size = _int(held.get("size"))
    local = (
        held_size is not None
        and held_size >= LOCAL_MIN_BYTES
        and not held.get("remote_host")
        and not held.get("remote_model")
    )
    running = _named(_models(ps), name) if ps is not None else None
    expires = running.get("expires_at") if running else None
    return ModelState(
        reachable=True,
        version=ver,
        held=True,
        held_size=held_size,
        local=bool(local),
        loaded=running is not None,
        size=_int(running.get("size")) if running else None,
        size_vram=_int(running.get("size_vram")) if running else None,
        expires_at=expires if isinstance(expires, str) else None,
        digest=held.get("digest") if isinstance(held.get("digest"), str) else None,
        reason=None if local else "not_local",
    )


def expires_label(value: str | None) -> datetime | None:
    """`expires_at` as a datetime (Ollama writes RFC 3339 with nanoseconds), or None."""
    if not value:
        return None
    m = re.match(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.\d+)?(Z|[+-]\d\d:\d\d)?$", value.strip())
    if not m:
        return None
    tz = m.group(2) or "+00:00"
    try:
        return datetime.fromisoformat(m.group(1) + ("+00:00" if tz == "Z" else tz))
    except ValueError:
        return None


# ------------------------------------------------------------------------------------------------ the client


def _raise_for(resp: httpx.Response) -> None:
    code = resp.status_code
    if code == 404 or code >= 500 or code == 429:
        raise SourceTraceUnavailable(f"the model server answered HTTP {code}", status=code)
    if code == 400:
        raise SourceTraceRejected("the model server refused the request (HTTP 400)", status=code)
    if code >= 400:
        raise SourceTraceRejected(f"the model server refused the request (HTTP {code})", status=code)


def _json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError as exc:
        raise SourceTraceProtocolError("the model server's reply is not JSON") from exc


class OllamaClient:
    """`base_url` is `ASSISTANT_OLLAMA_URL`; `transport` is for tests (`httpx.MockTransport`)."""

    def __init__(
        self, base_url: str, *, transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None
    ):
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    def _async(self, timeout: float) -> httpx.AsyncClient:
        t = httpx.Timeout(timeout, connect=min(CONNECT_SECONDS, timeout))
        kw: dict[str, Any] = {"base_url": self.base_url, "timeout": t, "trust_env": False}
        if self.transport is not None:
            kw["transport"] = self.transport
        return httpx.AsyncClient(**kw)

    def _sync(self, timeout: float) -> httpx.Client:
        t = httpx.Timeout(timeout, connect=min(CONNECT_SECONDS, timeout))
        kw: dict[str, Any] = {"base_url": self.base_url, "timeout": t, "trust_env": False}
        if self.transport is not None:
            kw["transport"] = self.transport
        return httpx.Client(**kw)

    async def _request(self, method: str, path: str, *, timeout: float, body: dict | None = None) -> Any:
        try:
            async with self._async(timeout) as client:
                resp = await client.request(method, path, json=body)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError) as exc:
            raise SourceTraceUnavailable(
                f"the model server cannot be reached ({type(exc).__name__})"
            ) from exc
        except httpx.TimeoutException as exc:
            raise TimeoutError("the model server did not answer in time") from exc
        except httpx.HTTPError as exc:
            raise SourceTraceUnavailable(
                f"the model server cannot be reached ({type(exc).__name__})"
            ) from exc
        _raise_for(resp)
        return _json(resp)

    def _request_sync(self, method: str, path: str, *, timeout: float) -> Any:
        try:
            with self._sync(timeout) as client:
                resp = client.request(method, path)
        except httpx.TimeoutException as exc:
            raise SourceTraceUnavailable("the model server did not answer in time") from exc
        except httpx.HTTPError as exc:
            raise SourceTraceUnavailable(
                f"the model server cannot be reached ({type(exc).__name__})"
            ) from exc
        _raise_for(resp)
        return _json(resp)

    async def chat(self, body: dict[str, Any], *, timeout: float) -> OllamaReply:
        return parse_chat(await self._request("POST", "/api/chat", timeout=timeout, body=body))

    async def load(self, model: str, keep_alive: str | int, *, timeout: float) -> None:
        await self._request(
            "POST", "/api/generate", timeout=timeout, body={"model": model, "keep_alive": keep_alive}
        )

    async def loaded(self, *, timeout: float = INFO_SECONDS) -> Any:
        return await self._request("GET", "/api/ps", timeout=timeout)

    async def models(self, *, timeout: float = INFO_SECONDS) -> Any:
        return await self._request("GET", "/api/tags", timeout=timeout)

    async def version(self, *, timeout: float = INFO_SECONDS) -> Any:
        return await self._request("GET", "/api/version", timeout=timeout)

    def loaded_sync(self, *, timeout: float = INFO_SECONDS) -> Any:
        return self._request_sync("GET", "/api/ps", timeout=timeout)

    def models_sync(self, *, timeout: float = INFO_SECONDS) -> Any:
        return self._request_sync("GET", "/api/tags", timeout=timeout)

    def version_sync(self, *, timeout: float = INFO_SECONDS) -> Any:
        return self._request_sync("GET", "/api/version", timeout=timeout)

    def state_sync(self, model: str, *, timeout: float = INFO_SECONDS) -> ModelState:
        """`/api/version`, `/api/tags` and `/api/ps`, read only (never generates, never loads)."""
        if not model_name_ok(model):
            return ModelState(reachable=False, reason="cloud")
        try:
            tags = self.models_sync(timeout=timeout)
        except (SourceTraceUnavailable, SourceTraceRejected, SourceTraceProtocolError):
            return ModelState(reachable=False, reason="unreachable")
        version = _quiet(lambda: self.version_sync(timeout=timeout))
        ps = _quiet(lambda: self.loaded_sync(timeout=timeout))
        return model_state(model, version, tags, ps)

    async def state(self, model: str, *, timeout: float = INFO_SECONDS) -> ModelState:
        if not model_name_ok(model):
            return ModelState(reachable=False, reason="cloud")
        try:
            tags = await self.models(timeout=timeout)
        except (SourceTraceUnavailable, SourceTraceRejected, SourceTraceProtocolError, TimeoutError):
            return ModelState(reachable=False, reason="unreachable")
        try:
            version = await self.version(timeout=timeout)
        except (SourceTraceUnavailable, SourceTraceRejected, SourceTraceProtocolError, TimeoutError):
            version = None
        try:
            ps = await self.loaded(timeout=timeout)
        except (SourceTraceUnavailable, SourceTraceRejected, SourceTraceProtocolError, TimeoutError):
            ps = None
        return model_state(model, version, tags, ps)


def _quiet(fn) -> Any:
    try:
        return fn()
    except (SourceTraceUnavailable, SourceTraceRejected, SourceTraceProtocolError):
        return None
