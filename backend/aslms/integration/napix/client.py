"""NAPIX transport: OAuth2 token, the encrypted envelope, rate limiting, retries and call logging.

Every call goes through `NapixClient.call()`. It never touches the database: the caller passes an `on_call`
hook that receives one `NapixResult` per HTTP attempt (the service layer writes `napix_call_log` from it).

Error handling (spec, chapter "Status codes"): NAPIX answers errors as `{"status": <6xx>}` — and the status
value itself is usually encrypted. 600 (invalid CNR) and 628 (record not found) raise `SourceNotFound`;
626 (invalid token) and 629 (unexpected error), HTTP 401/429/5xx and network errors raise `SourceUnavailable`
and are retried; everything else raises `IntegrationError` (a configuration or contract problem)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from aslms.core.config import get_settings
from aslms.core.errors import IntegrationError, SourceNotFound, SourceUnavailable
from aslms.core.logging import get_logger
from aslms.integration.napix.crypto import NapixCrypto, build_plain

log = get_logger(__name__)

NAPIX_STATUS: dict[int, str] = {
    600: "INVALID_CNR",
    601: "INVALID_DATE",
    602: "INVALID_ORDER_NO",
    603: "INVALID_EST_CODE",
    604: "INVALID_CASE_TYPE",
    616: "INVALID_CAUSELIST_DATE",
    626: "INVALID_TOKEN",
    627: "INVALID_DEPT_ID",
    628: "RECORD_NOT_FOUND",
    629: "UNEXPECTED_ERROR",
    631: "API_ACCESS_NOT_ALLOWED",
    632: "INVALID_VERSION",
    633: "INVALID_BENCH_ID",
    634: "INVALID_CAUSELIST_ID",
}
NOT_FOUND_CODES = {600, 628}
RETRY_CODES = {626, 629}


@dataclass
class NapixResult:
    """One HTTP attempt. `data` is the decrypted JSON (dict or list), `pdf` the bytes of a PDF response."""

    api: str
    params_sha256: str
    ok: bool
    http_status: int | None = None
    napix_status: int | None = None
    duration_ms: int = 0
    data: Any = None
    pdf: bytes | None = None
    token_verified: bool | None = None
    error: str | None = None
    raw_text: str | None = field(default=None, repr=False)


CallHook = Callable[[NapixResult], None]


class RateLimiter:
    """Sliding window: at most `per_minute` calls in any 60 s."""

    def __init__(self, per_minute: int):
        self.per_minute = max(1, per_minute)
        self._stamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            while self._stamps and now - self._stamps[0] > 60:
                self._stamps.popleft()
            if len(self._stamps) >= self.per_minute:
                delay = 60 - (now - self._stamps[0]) + 0.05
                log.info("napix rate limit reached, waiting", seconds=round(delay, 1))
                await asyncio.sleep(delay)
            self._stamps.append(time.monotonic())


class NapixClient:
    def __init__(
        self,
        *,
        base: str,
        client_id: str,
        client_secret: str,
        dept_id: str,
        crypto: NapixCrypto,
        version: str = "v1.0",
        timeout: float = 40.0,
        rate_limit_per_min: int = 60,
        on_call: CallHook | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base = base.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.dept_id = dept_id
        self.crypto = crypto
        self.version = version
        self.timeout = timeout
        self.on_call = on_call
        self._transport = transport
        self._limiter = RateLimiter(rate_limit_per_min)
        self._token: str | None = None
        self._token_exp = 0.0

    @classmethod
    def from_settings(cls, on_call: CallHook | None = None, **overrides: Any) -> NapixClient:
        s = get_settings()
        if not s.napix_configured:
            raise IntegrationError(
                "NAPIX credentials missing: set NAPIX_CLIENT_ID, NAPIX_CLIENT_SECRET, NAPIX_DEPT_ID, NAPIX_AUTH_KEY"
            )
        assert s.napix_client_secret and s.napix_auth_key and s.napix_client_id and s.napix_dept_id
        kwargs: dict[str, Any] = dict(
            base=s.napix_base,
            client_id=s.napix_client_id,
            client_secret=s.napix_client_secret.get_secret_value(),
            dept_id=s.napix_dept_id,
            crypto=NapixCrypto(s.napix_auth_key.get_secret_value(), s.napix_hash_key, s.napix_auth_key_mode),
            version=s.napix_version,
            timeout=s.napix_timeout_seconds,
            rate_limit_per_min=s.napix_rate_limit_per_min,
            on_call=on_call,
        )
        kwargs.update(overrides)
        return cls(**kwargs)

    # ------------------------------------------------------------------ token
    async def _get_token(self, http: httpx.AsyncClient, force: bool = False) -> str:
        if self._token and not force and time.time() < self._token_exp - 60:
            return self._token
        try:
            r = await http.post(
                f"{self.base}/oauth2/token",
                data={"grant_type": "client_credentials", "scope": "napix"},
                auth=(self.client_id, self.client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as e:
            raise SourceUnavailable(f"NAPIX token endpoint: {e}") from e
        if r.status_code != 200:
            raise SourceUnavailable(f"NAPIX token endpoint HTTP {r.status_code}: {r.text[:200]}")
        payload = r.json()
        token = payload.get("access_token")
        if not token:
            raise IntegrationError(f"NAPIX token response has no access_token: {list(payload)}")
        self._token = token
        self._token_exp = time.time() + float(payload.get("expires_in", 3600))
        return token

    # ------------------------------------------------------------------ call
    @retry(
        retry=retry_if_exception_type(SourceUnavailable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def call(
        self, api_path: str, params: dict[str, Any] | None = None, method: str = "GET"
    ) -> NapixResult:
        """`api_path` like `hc-cnr-api/CNR`; `params` in the spec's documented order (empty for master APIs)."""
        return await self._call_once(api_path, params or {}, method)

    async def _call_once(self, api_path: str, params: dict[str, Any], method: str) -> NapixResult:
        plain = build_plain(params)
        request_str = self.crypto.encrypt(plain) if plain else ""
        query = {
            "dept_id": self.dept_id,
            "request_str": request_str,
            "request_token": self.crypto.token(plain),
            "version": self.version,
        }
        result = NapixResult(api=api_path, params_sha256=hashlib.sha256(plain.encode()).hexdigest(), ok=False)
        url = f"{self.base}/{api_path.lstrip('/')}"
        await self._limiter.wait()
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as http:
                token = await self._get_token(http)
                headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, application/pdf"}
                try:
                    if method.upper() == "POST":
                        r = await http.post(url, data=query, headers=headers)
                    else:
                        qs = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in query.items())
                        r = await http.get(f"{url}?{qs}", headers=headers)
                except httpx.HTTPError as e:
                    raise SourceUnavailable(f"NAPIX {api_path}: {e}") from e
                result.http_status = r.status_code
                if r.status_code == 401:
                    await self._get_token(http, force=True)
                    raise SourceUnavailable("NAPIX 401: token refreshed, retrying")
                if r.status_code in (429, 500, 502, 503, 504):
                    raise SourceUnavailable(f"NAPIX HTTP {r.status_code}")
                if r.status_code != 200:
                    raise IntegrationError(f"NAPIX HTTP {r.status_code}: {r.text[:300]}")
                self._parse_response(r, result)
            result.ok = True
            return result
        except Exception as e:  # noqa: BLE001 — recorded, then re-raised
            result.error = f"{type(e).__name__}: {e}"[:500]
            raise
        finally:
            result.duration_ms = int((time.perf_counter() - started) * 1000)
            if self.on_call:
                try:
                    self.on_call(result)
                except Exception:  # noqa: BLE001 — logging must never break the call
                    log.exception("napix on_call hook failed")

    # ------------------------------------------------------------------ envelope
    def _parse_response(self, r: httpx.Response, result: NapixResult) -> None:
        ctype = r.headers.get("content-type", "")
        if "pdf" in ctype or r.content.startswith(b"%PDF"):
            result.pdf = r.content
            return
        try:
            body = r.json()
        except ValueError as e:
            result.raw_text = r.text[:2000]
            raise IntegrationError(f"NAPIX non-JSON response: {r.text[:200]}") from e
        self.parse_body(body, result)

    def parse_body(self, body: Any, result: NapixResult) -> None:
        """Decrypts `response_str`, verifies `response_token`, maps `status` codes. Pure; used by tests."""
        if isinstance(body, dict) and "response_str" in body:
            text = self.crypto.decrypt(body["response_str"])
            result.raw_text = text
            if body.get("response_token"):
                result.token_verified = body["response_token"] == self.crypto.token(text)
                if not result.token_verified:
                    log.warning("napix response_token mismatch", api=result.api)
            stripped = text.strip()
            if stripped.startswith(("{", "[")):
                data = json.loads(stripped)
                status = _status_code(data)
                if status is not None and not _has_payload(data):
                    self._raise_for_status(status, result, data)
                result.data = data
                return
            try:
                pdf = base64.b64decode(stripped, validate=True)
            except ValueError:
                pdf = b""
            if pdf.startswith(b"%PDF"):
                result.pdf = pdf
            else:
                result.data = {"raw": text}
            return

        if isinstance(body, dict) and "status" in body and len(body) <= 3:
            status_val = body["status"]
            if isinstance(status_val, str) and not status_val.strip().isdigit():
                try:
                    dec = json.loads(self.crypto.decrypt(status_val))
                except (ValueError, json.JSONDecodeError) as e:
                    raise IntegrationError(
                        "NAPIX returned an encrypted status that NAPIX_AUTH_KEY cannot decrypt"
                    ) from e
                status = _status_code(dec) if isinstance(dec, dict) else int(dec)
            else:
                status = int(status_val)
            if status is not None:
                self._raise_for_status(status, result, body)
        result.data = body

    def _raise_for_status(self, status: int, result: NapixResult, body: Any) -> None:
        result.napix_status = status
        name = NAPIX_STATUS.get(status, "UNKNOWN")
        if status in NOT_FOUND_CODES:
            raise SourceNotFound(f"NAPIX {status} {name}", napix_status=status)
        if status in RETRY_CODES:
            raise SourceUnavailable(f"NAPIX {status} {name}", napix_status=status)
        raise IntegrationError(f"NAPIX {status} {name}: {str(body)[:200]}", napix_status=status)


def _status_code(data: Any) -> int | None:
    if not isinstance(data, dict):
        return None
    for key in ("status", "status_code"):
        v = data.get(key)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.strip().isdigit():
            return int(v)
    return None


def _has_payload(data: dict[str, Any]) -> bool:
    """A 200-style body may carry `status` beside real data; only a bare status block is an error."""
    return any(k not in ("status", "status_code", "message", "msg") for k in data)


def nested_list(obj: Any) -> list[dict[str, Any]]:
    """NAPIX renders lists as `{"case1": {...}, "case2": {...}}` or `{"sr_no1": {...}}` rather than arrays.
    Returns the dict values in numeric key order; passes real lists through; anything else → []."""
    if obj is None:
        return []
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        items = sorted(obj.items(), key=lambda kv: _trailing_int(kv[0]))
        vals = [v for _, v in items if isinstance(v, dict)]
        if vals:
            return vals
        return []
    return []


def _trailing_int(key: str) -> int:
    digits = "".join(ch for ch in str(key) if ch.isdigit())
    return int(digits) if digits else 0
