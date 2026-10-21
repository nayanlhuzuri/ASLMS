"""The request a court call would make, built without making it (design `system-health-inspector`, decision 13).

`preview` runs the API's own `hc.py` method against a `CaptureClient`, whose `call` records the path, the parameters
and the method and then raises `Captured`: the real method runs up to its call and no further. Method, path, parameter
names, order and values therefore come from the code that makes the real call, never from a second copy. No
Authentication Key is needed and no connection is ever opened.

`request_token` is HMAC-SHA256 of the plain string under the hash key published in the specification (Annexure A):
it is not secret and is shown only while `NAPIX_HASH_KEY` is that published value. `request_str` (AES under the
Authentication Key) is never built here; only its length is computed from the plain string."""

from __future__ import annotations

import hashlib
import hmac
import math
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from aslms.core.config import Settings
from aslms.integration.napix.crypto import DEFAULT_HASH_KEY, build_plain
from aslms.integration.napix.hc import NapixHighCourt

Invoke = Callable[[NapixHighCourt, dict[str, Any]], Any]  # returns the method's coroutine
TOKEN_PATH = "/oauth2/token"  # after a double slash, the manual's form (notes §2)


class Captured(Exception):  # noqa: N818 — an internal signal, not an error
    """Raised by `CaptureClient.call` once the request is recorded: the method stops before any network."""


class CaptureClient:
    """Stands in for `NapixClient` under `NapixHighCourt`: records the first call and stops."""

    def __init__(self) -> None:
        self.api_path: str | None = None
        self.params: dict[str, Any] = {}
        self.method: str = "GET"

    async def call(self, api_path: str, params: Mapping[str, Any] | None = None, method: str = "GET") -> Any:
        self.api_path, self.params, self.method = api_path, dict(params or {}), method
        raise Captured


@dataclass(frozen=True)
class RequestPreview:
    method: str
    path: str
    url: str
    params: list[tuple[str, str]] = field(default_factory=list)  # the plain parameters, in order
    plain: str = ""
    plain_sha256: str = ""
    request_token: str | None = None
    request_str_length: int = 0
    placeholders: tuple[str, ...] = ()  # parameter names whose value is a placeholder, not a real value

    @property
    def complete(self) -> bool:
        return not self.placeholders


def request_str_length(plain: str) -> int:
    """The Base64 length of AES-128-CBC with PKCS7 over the plain string's UTF-8 bytes (no key needed)."""
    padded = (len(plain.encode("utf-8")) // 16 + 1) * 16
    return 4 * math.ceil(padded / 3)


def display_url(base_url: str, path: str) -> str:
    """The base URL with any user-info part removed, plus the path."""
    parts = urlsplit(base_url.rstrip("/"))
    netloc = parts.netloc.rsplit("@", 1)[-1]
    base = urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    return f"{base}/{path.lstrip('/')}"


def token_url(base_url: str) -> str:
    """The token endpoint as the client posts to it: `{base}//oauth2/token`."""
    return display_url(base_url, "") + TOKEN_PATH


def published_token(settings: Settings, plain: str) -> str | None:
    """HMAC-SHA256 of the plain string under the published hash key; None when another key is configured."""
    if settings.napix_hash_key != DEFAULT_HASH_KEY:
        return None
    return hmac.new(DEFAULT_HASH_KEY.encode("ascii"), plain.encode("utf-8"), hashlib.sha256).hexdigest()


def _run(coro: Coroutine[Any, Any, Any]) -> None:
    """Drives the method's coroutine by hand: `CaptureClient.call` raises before anything awaits, so no event loop
    is needed (the preview also runs inside the Send's own loop)."""
    try:
        coro.send(None)
    except Captured:
        return
    except StopIteration:
        raise RuntimeError("the API method finished without calling the court") from None
    finally:
        coro.close()
    raise RuntimeError("the API method waited before calling the court")


def preview(
    settings: Settings,
    key: str,
    invoke: Invoke,
    values: dict[str, Any],
    placeholders: Mapping[str, str] | None = None,
) -> RequestPreview:
    """The request `invoke` would send with `values` (the chooser's keys; `est_code` / `state_code` in `values`
    replace the configured codes, as the console sends them). `placeholders` maps a parameter name to the text shown
    in place of a value the caller has not typed yet (decision 6): that request is incomplete and has no
    `request_token`."""
    capture = CaptureClient()
    hc = NapixHighCourt(capture, settings.napix_est_code, settings.napix_state_code).for_codes(  # type: ignore[arg-type]
        est_code=values.get("est_code"), state_code=values.get("state_code")
    )

    _run(invoke(hc, values))
    assert capture.api_path is not None
    marks = dict(placeholders or {})
    params = [(k, marks.get(k, str(v))) for k, v in capture.params.items()]
    plain = build_plain(dict(params))
    used = tuple(k for k, _ in params if k in marks)
    return RequestPreview(
        method=capture.method.upper(),
        path=capture.api_path,
        url=display_url(settings.napix_base_url, capture.api_path),
        params=params,
        plain=plain,
        plain_sha256=hashlib.sha256(plain.encode()).hexdigest(),
        request_token=None if used else published_token(settings, plain),
        request_str_length=request_str_length(plain),
        placeholders=used,
    )
