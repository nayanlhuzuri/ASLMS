"""NAPIX transport: token cache, the encrypted envelope, error families, retries, rate limiting and the
per-attempt call hook (docs/napix_integration_design.md §3–§7).

`NapixClient` is an async context manager that owns one `httpx.AsyncClient`. It never touches the database:
every attempt produces a `NapixResult` handed to `on_call`; the service layer stores it in `napix_call_log`."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import random
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from aslms.core.config import Settings, get_settings
from aslms.core.errors import (
    IntegrationError,
    NapixAuthError,
    NapixEmptyResponse,
    NapixGatewayError,
    NapixInputError,
    NapixNotFound,
    NapixProtocolError,
    NapixUnavailable,
)
from aslms.core.logging import get_logger
from aslms.integration.napix.crypto import NapixCrypto, build_plain

log = get_logger(__name__)

# A signature mismatch is recorded on every call (`token_verified` in the call log) but warned at most once per API
# in this many seconds, with the number of mismatches since the last warning: the gateway signs PDF answers in a form
# that does not match on every Show Order call, and one warning per order flooded the worker's log.
MISMATCH_WARN_SECONDS = 600
_mismatch_lock = threading.Lock()
_mismatch_seen: dict[str, tuple[float, int]] = {}


def _warn_mismatch(api: str) -> None:
    now = time.monotonic()
    with _mismatch_lock:
        last, quiet = _mismatch_seen.get(api, (0.0, 0))
        if last and now - last < MISMATCH_WARN_SECONDS:
            _mismatch_seen[api] = (last, quiet + 1)
            return
        _mismatch_seen[api] = (now, 0)
    log.warning(
        "napix response_token mismatch",
        api=api,
        mismatches_since_last_warning=quiet,
        warned_at_most_every_seconds=MISMATCH_WARN_SECONDS,
    )


NAPIX_STATUS: dict[int, str] = {
    600: "INVALID_CNR",
    601: "INVALID_DATE",
    602: "INVALID_ORDER_NO",
    603: "INVALID_EST_CODE",
    604: "INVALID_CASE_TYPE",
    605: "INVALID_REG_NO",
    606: "INVALID_REG_YEAR",
    607: "INVALID_FIL_NO",
    608: "INVALID_FIL_YEAR",
    609: "INVALID_PEND_DISP",
    610: "INVALID_LITIGANT_NAME",
    614: "INVALID_ADVOCATE_NAME",
    616: "INVALID_CAUSELIST_DATE",
    624: "INVALID_STATE_CODE",
    626: "INVALID_TOKEN",
    627: "INVALID_DEPT_ID",
    628: "RECORD_NOT_FOUND",
    629: "UNEXPECTED_ERROR",
    631: "API_ACCESS_NOT_ALLOWED",
    632: "INVALID_VERSION",
    633: "INVALID_BENCH_ID",
    634: "INVALID_CAUSELIST_ID",
}
NOT_FOUND_CODES = frozenset({600, 628})
RETRY_CODES = frozenset({629})
AUTH_CODES = frozenset({626, 627})
GATEWAY_CODES = frozenset({631})

PRINT_R_STATUS = re.compile(r"\[status_code\]\s*=>\s*(\d{3})")
PRINT_R_NAME = re.compile(r"\[status\]\s*=>\s*([A-Z_]+)")
RATE_LIMIT_NUMBER = re.compile(r"(\d+)\s*;?\s*$")
# the `error` of a token renewal's 401 step (`ok` false, `http_status` 401, no family; api-health-checker-followups)
RENEWED = "HTTP 401: the token had expired; it was renewed and the call repeated"


@dataclass
class NapixResult:
    """One HTTP attempt. `data` is the decrypted JSON (dict or list), `pdf` the bytes of a PDF response."""

    api: str
    params_sha256: str
    ok: bool = False
    http_status: int | None = None
    napix_status: int | None = None
    duration_ms: int = 0
    data: Any = None
    pdf: bytes | None = None
    token_verified: bool | None = None
    error: str | None = None
    error_family: str | None = None
    rate_limit: tuple[int | None, int | None] = (None, None)  # (limit, remaining) from the headers
    params: dict[str, Any] = field(default_factory=dict)  # the input parameters, for the verbatim store
    method: str = "GET"
    raw_text: str | None = field(default=None, repr=False)
    # the attempt's own time: after the local limiter's wait, before the request (design napix-window, decision 7)
    called_at: datetime | None = None


CallHook = Callable[[NapixResult], None]

META_KEY = "napix:token:meta"
REQUESTS_KEY = "napix:token:requests:"  # + the IST date
META_TTL_SECONDS = 8 * 24 * 3600
IST = ZoneInfo("Asia/Kolkata")
# the per-request fields of the token metadata: rewritten (blank when absent) on every token request
REQUEST_FIELDS = (
    "requested_at",
    "ok",
    "http_status",
    "error_family",
    "duration_ms",
    "expires_in",
    "token_type",
    "scope",
    "rate_limit_limit",
    "rate_limit_remaining",
)


@dataclass(frozen=True)
class TokenState:
    """Whether a token is held and for how long; never the token itself."""

    held: bool
    ttl_seconds: int | None
    shared_store: bool


@dataclass(frozen=True)
class TokenRenewal:
    """The outcome of one token request; never the token (design `system-health-inspector`, decision 10)."""

    ok: bool
    http_status: int | None
    error_family: str | None
    duration_ms: int
    expires_in: int | None
    rate_limit: tuple[int | None, int | None] = (None, None)
    token_type: str | None = None
    scope: str | None = None


def _rate_number(value: str | None) -> int | None:
    if not value:
        return None
    m = RATE_LIMIT_NUMBER.search(value)
    return int(m.group(1)) if m else None


def _text(v: Any) -> str:
    return v.decode() if isinstance(v, bytes) else str(v)


def _blank(v: Any) -> str:
    return "" if v is None else str(v)


def _ist_date(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(IST).date().isoformat()


class TokenCache:
    """One token per process (threads share it); mirrored in Redis under `napix:token` when a URL is given,
    so the API, the workers and the CLI reuse one token. Redis trouble never fails a call.

    Every token request, background or manual, also writes non-secret metadata (`note_request`): the hash
    `napix:token:meta` and the day counter `napix:token:requests:<IST date>`, both expiring after 8 days (design
    `system-health-inspector`, decision 10). `redis_client` is a seam for tests (a dict-backed stub)."""

    def __init__(self, redis_url: str | None = None, key: str = "napix:token", redis_client: Any = None):
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at = 0.0
        self._key = key
        self._redis = redis_client
        self._meta: dict[str, str] = {}  # this process's copy when there is no shared store
        if redis_client is None and redis_url:
            try:
                import redis  # optional dependency

                self._redis = redis.Redis.from_url(redis_url, socket_timeout=2)
            except Exception:  # noqa: BLE001 — optional
                log.warning("napix token cache: redis unavailable, using the process cache only")

    def get(self, margin: float = 60.0) -> str | None:
        with self._lock:
            if self._token and time.time() < self._expires_at - margin:
                return self._token
        if self._redis is not None:
            try:
                raw = self._redis.get(self._key)
                ttl = self._redis.ttl(self._key)
                if raw and ttl and ttl > margin:
                    token = raw.decode() if isinstance(raw, bytes) else str(raw)
                    with self._lock:
                        self._token, self._expires_at = token, time.time() + ttl
                    return token
            except Exception:  # noqa: BLE001
                log.warning("napix token cache: redis read failed")
        return None

    def set(self, token: str, ttl: float) -> None:
        with self._lock:
            self._token, self._expires_at = token, time.time() + ttl
        if self._redis is not None:
            try:
                self._redis.set(self._key, token, ex=max(1, int(ttl)))
            except Exception:  # noqa: BLE001
                log.warning("napix token cache: redis write failed")

    def clear(self) -> None:
        with self._lock:
            self._token, self._expires_at = None, 0.0
        if self._redis is not None:
            try:
                self._redis.delete(self._key)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ metadata (never the token)
    @property
    def shared_store(self) -> bool:
        return self._redis is not None

    def state(self) -> TokenState:
        """Whether a token is held and its remaining seconds: the shared copy's TTL when there is a store, else this
        process's copy. Never the value."""
        if self._redis is not None:
            try:
                ttl = int(self._redis.ttl(self._key) or -2)
            except Exception:  # noqa: BLE001
                log.warning("napix token cache: redis read failed")
                return TokenState(held=False, ttl_seconds=None, shared_store=True)
            return TokenState(held=ttl > 0, ttl_seconds=ttl if ttl > 0 else None, shared_store=True)
        with self._lock:
            left = int(self._expires_at - time.time()) if self._token else 0
        return TokenState(held=left > 0, ttl_seconds=left if left > 0 else None, shared_store=False)

    def meta(self) -> dict[str, str]:
        """The metadata hash as text, plus `requests_today` (read-only; {} when nothing is recorded)."""
        if self._redis is None:
            return dict(self._meta)
        try:
            raw = self._redis.hgetall(META_KEY) or {}
            out = {_text(k): _text(v) for k, v in raw.items()}
            count = self._redis.get(REQUESTS_KEY + _ist_date())
            if count is not None:
                out["requests_today"] = _text(count)
            return out
        except Exception:  # noqa: BLE001
            log.warning("napix token cache: redis read failed")
            return {}

    def note_request(self, renewal: TokenRenewal, now: datetime | None = None) -> None:
        """Records one token request in the metadata and the day counter; Redis trouble never fails a call."""
        now = now or datetime.now(UTC)
        stamp = now.isoformat()
        fields: dict[str, str] = dict.fromkeys(REQUEST_FIELDS, "")
        fields.update(
            {
                "requested_at": stamp,
                "ok": "1" if renewal.ok else "0",
                "http_status": _blank(renewal.http_status),
                "error_family": renewal.error_family or "",
                "duration_ms": str(renewal.duration_ms),
                "expires_in": _blank(renewal.expires_in),
                "token_type": renewal.token_type or "",
                "scope": renewal.scope or "",
                "rate_limit_limit": _blank(renewal.rate_limit[0]),
                "rate_limit_remaining": _blank(renewal.rate_limit[1]),
            }
        )
        if renewal.ok:
            fields["obtained_at"] = stamp
            if renewal.expires_in:
                fields["expires_at"] = datetime.fromtimestamp(
                    now.timestamp() + renewal.expires_in, UTC
                ).isoformat()
        else:
            fields["last_failure_at"] = stamp
            fields["last_failure_family"] = renewal.error_family or ""
        if self._redis is None:
            self._meta.update(fields)
            self._meta["requests_today"] = str(int(self._meta.get("requests_today") or 0) + 1)
            return
        try:
            day = REQUESTS_KEY + _ist_date(now)
            self._redis.hset(META_KEY, mapping=fields)
            self._redis.expire(META_KEY, META_TTL_SECONDS)
            self._redis.incr(day)
            self._redis.expire(day, META_TTL_SECONDS)
        except Exception:  # noqa: BLE001
            log.warning("napix token cache: redis metadata write failed")


class RateLimiter:
    """A local sliding window (`per_minute`) plus the gateway's `X-RateLimit-Limit` / `X-RateLimit-Remaining`
    headers: under 10 % remaining the next call waits a share of the window; at 0 it waits
    `min(window_seconds, zero_wait_seconds)`, never a whole window, so a call is not slept through the reset (design
    `napix-window`, decision 8: the window's phase is detected by the service layer from the call log)."""

    def __init__(self, per_minute: int, window_seconds: float = 3600.0, zero_wait_seconds: float = 180.0):
        self.per_minute = max(1, per_minute)
        self.window_seconds = window_seconds
        self.zero_wait_seconds = zero_wait_seconds
        self._stamps: deque[float] = deque()
        self.limit: int | None = None
        self.remaining: int | None = None
        self._lock: asyncio.Lock | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def observe(self, headers: Mapping[str, str]) -> tuple[int | None, int | None]:
        def num(v: str | None) -> int | None:
            if not v:
                return None
            m = RATE_LIMIT_NUMBER.search(v)
            return int(m.group(1)) if m else None

        self.limit = num(headers.get("x-ratelimit-limit")) or self.limit
        self.remaining = num(headers.get("x-ratelimit-remaining"))
        return self.limit, self.remaining

    def _header_delay(self) -> float:
        if self.remaining is None:
            return 0.0
        if self.remaining <= 0:
            return min(self.window_seconds, self.zero_wait_seconds)
        if self.limit and self.remaining < self.limit * 0.1:
            return min(self.window_seconds, self.window_seconds / self.remaining)
        return 0.0

    async def wait(self) -> None:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._loop is not loop:  # sync callers use asyncio.run(), one loop per call
            self._lock, self._loop = asyncio.Lock(), loop
        async with self._lock:
            now = time.monotonic()
            while self._stamps and now - self._stamps[0] > 60:
                self._stamps.popleft()
            delay = self._header_delay()
            if len(self._stamps) >= self.per_minute:
                delay = max(delay, 60 - (now - self._stamps[0]) + 0.05)
            if delay > 0:
                log.info("napix rate limit, waiting", seconds=round(delay, 1), remaining=self.remaining)
                await asyncio.sleep(delay)
            self._stamps.append(time.monotonic())


class NapixClient:
    def __init__(
        self,
        *,
        base_url: str,
        client_id: str,
        client_secret: str,
        dept_id: str,
        crypto: NapixCrypto,
        version: str = "v1.0",
        timeout: float = 40.0,
        rate_limit_per_min: int = 60,
        rate_window_seconds: float = 3600.0,
        rate_zero_wait_seconds: float = 180.0,
        token_ttl_seconds: int = 3300,
        token_cache: TokenCache | None = None,
        on_call: CallHook | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        max_attempts: int = 3,
        backoff_base: float = 2.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.client_id, self.client_secret, self.dept_id = client_id, client_secret, dept_id
        self.crypto, self.version, self.timeout = crypto, version, timeout
        self.token_ttl_seconds = token_ttl_seconds
        self.tokens = token_cache or TokenCache()
        self.on_call = on_call
        self.limiter = RateLimiter(rate_limit_per_min, rate_window_seconds, rate_zero_wait_seconds)
        self.max_attempts, self.backoff_base = max_attempts, backoff_base
        self._transport = transport
        self._http: httpx.AsyncClient | None = None
        self.last_token_request: TokenRenewal | None = None

    @classmethod
    def from_settings(cls, s: Settings | None = None, **overrides: Any) -> NapixClient:
        s = s or get_settings()
        if not s.napix_configured:
            raise IntegrationError(
                "NAPIX is off or not configured: set NAPIX_ENABLED=true and NAPIX_CLIENT_ID, "
                "NAPIX_CLIENT_SECRET, NAPIX_DEPT_ID, NAPIX_AUTH_KEY"
            )
        assert s.napix_client_id and s.napix_client_secret and s.napix_dept_id and s.napix_auth_key
        kwargs: dict[str, Any] = dict(
            base_url=s.napix_base_url,
            client_id=s.napix_client_id,
            client_secret=s.napix_client_secret.get_secret_value(),
            dept_id=s.napix_dept_id,
            crypto=NapixCrypto(s.napix_auth_key.get_secret_value(), s.napix_hash_key),
            version=s.napix_version,
            timeout=s.napix_timeout_seconds,
            rate_limit_per_min=s.napix_rate_limit_per_min,
            rate_window_seconds=float(s.napix_rate_window_seconds),
            rate_zero_wait_seconds=float(s.napix_window_probe_seconds),
            token_ttl_seconds=s.napix_token_ttl_seconds,
            token_cache=TokenCache(s.redis_url),
        )
        kwargs.update(overrides)
        return cls(**kwargs)

    # ------------------------------------------------------------------ lifecycle
    async def __aenter__(self) -> NapixClient:
        self._http = httpx.AsyncClient(timeout=self.timeout, transport=self._transport)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            raise RuntimeError("use `async with NapixClient(...) as client:`")
        return self._http

    # ------------------------------------------------------------------ token (§3)
    async def token(self, force: bool = False) -> str:
        """The cached token, or one token request. Every request is recorded in the token metadata and one log line
        ("napix token requested": outcome, HTTP status, duration; never the token or the answer's body)."""
        if not force:
            cached = self.tokens.get()
            if cached:
                return cached
        started = time.perf_counter()
        facts: dict[str, Any] = {"http_status": None, "rate_limit": (None, None)}
        try:
            token, ttl, payload = await self._request_token(facts)
        except IntegrationError as e:
            self._note_token(started, facts, error_family=type(e).__name__)
            raise
        self.tokens.set(token, ttl)
        self._note_token(started, facts, payload=payload, expires_in=int(ttl))
        return token

    async def _request_token(self, facts: dict[str, Any]) -> tuple[str, float, dict[str, Any]]:
        try:
            r = await self.http.post(
                f"{self.base_url}//oauth2/token",  # the manual's form; what succeeded live
                data={"grant_type": "client_credentials", "scope": "napix"},
                auth=(self.client_id, self.client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as e:
            raise NapixUnavailable(f"NAPIX token endpoint: {e}") from e
        facts["http_status"] = r.status_code
        facts["rate_limit"] = (
            _rate_number(r.headers.get("x-ratelimit-limit")),
            _rate_number(r.headers.get("x-ratelimit-remaining")),
        )
        if r.status_code in (401, 403):
            raise NapixAuthError(f"NAPIX token endpoint HTTP {r.status_code}: check NAPIX_CLIENT_ID / SECRET")
        if r.status_code != 200:
            raise NapixUnavailable(f"NAPIX token endpoint HTTP {r.status_code}: {r.text[:200]}")
        payload = _json_or_none(r.text)
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not token:
            raise NapixProtocolError("NAPIX token response has no access_token")
        ttl = float(payload.get("expires_in") or self.token_ttl_seconds)
        return token, ttl, payload

    def _note_token(
        self,
        started: float,
        facts: dict[str, Any],
        *,
        error_family: str | None = None,
        payload: dict[str, Any] | None = None,
        expires_in: int | None = None,
    ) -> None:
        payload = payload or {}
        renewal = TokenRenewal(
            ok=error_family is None,
            http_status=facts.get("http_status"),
            error_family=error_family,
            duration_ms=int((time.perf_counter() - started) * 1000),
            expires_in=expires_in,
            rate_limit=facts.get("rate_limit") or (None, None),
            token_type=str(payload["token_type"])[:40] if payload.get("token_type") else None,
            scope=str(payload["scope"])[:80] if payload.get("scope") else None,
        )
        self.last_token_request = renewal
        try:
            self.tokens.note_request(renewal)
        except Exception:  # noqa: BLE001 — recording must never break the call
            log.warning("napix token metadata could not be written")
        log.info(
            "napix token requested",
            outcome="obtained" if renewal.ok else "failed",
            error_family=renewal.error_family,
            http_status=renewal.http_status,
            duration_ms=renewal.duration_ms,
        )

    async def renew_token(self) -> TokenRenewal:
        """One fresh token request with no retry ("Check token", design `system-health-inspector`, decision 10): the
        new token replaces the shared one; a failure is an outcome. Never returns the token."""
        self.last_token_request = None
        try:
            await self.token(force=True)
        except IntegrationError:
            pass
        assert self.last_token_request is not None
        return self.last_token_request

    # ------------------------------------------------------------------ call (§4–§7)
    async def call(
        self, api_path: str, params: Mapping[str, Any] | None = None, method: str = "GET"
    ) -> NapixResult:
        """`api_path` like `hc-cnr-api/CNR`; `params` in the notes' documented order (empty for no-input APIs).
        Retries `NapixUnavailable` with exponential back-off; refreshes the token once on 401 (the 401 step and the
        repeated attempt are two hook calls, in that order: design `api-health-checker-followups`, decision 4). An
        empty or unreadable
        HTTP 200 body (`NapixEmptyResponse`) is re-raised at once: retrying seconds later spends the allowance on the
        same fault (design `safety-fixes`, decision 5); the queue's ladder backs off instead."""
        last: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                return await self._attempt(api_path, dict(params or {}), method, refresh_token=True)
            except NapixEmptyResponse:
                raise
            except NapixUnavailable as e:
                last = e
                if attempt + 1 < self.max_attempts:
                    delay = min(30.0, self.backoff_base * (2**attempt)) * (1 + random.random() * 0.25)
                    log.warning(
                        "napix call failed, retrying",
                        api=api_path,
                        attempt=attempt + 1,
                        delay=round(delay, 1),
                    )
                    await asyncio.sleep(delay)
        assert last is not None
        raise last

    async def _attempt(
        self, api_path: str, params: dict[str, Any], method: str, *, refresh_token: bool
    ) -> NapixResult:
        plain = build_plain(params)
        query = {
            "dept_id": self.dept_id,
            "request_str": self.crypto.encrypt(plain),  # the empty string is encrypted too (notes §3.3)
            "request_token": self.crypto.token(plain),
            "version": self.version,
        }
        result = NapixResult(
            api=api_path,
            params_sha256=hashlib.sha256(plain.encode()).hexdigest(),
            params={k: str(v) for k, v in params.items()},
            method=method,
        )
        url = f"{self.base_url}/{api_path.lstrip('/')}"
        await self.limiter.wait()
        result.called_at = datetime.now(UTC)
        started = time.perf_counter()
        emitted = False  # the 401 step of a token renewal is handed over before the call is repeated
        try:
            headers = {
                "Authorization": f"Bearer {await self.token()}",
                "Accept": "application/json, application/pdf",
            }
            try:
                # the four parameters travel in the query string for GET and POST alike (verified live, 1 Oct:
                # Current Status answers 400 "required API parameters are missing" to a form or JSON body)
                qs = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in query.items())
                if method.upper() == "POST":
                    r = await self.http.post(f"{url}?{qs}", headers=headers)
                else:
                    r = await self.http.get(f"{url}?{qs}", headers=headers)
            except httpx.HTTPError as e:
                raise NapixUnavailable(f"NAPIX {api_path}: {e}", api=api_path) from e
            result.http_status = r.status_code
            result.rate_limit = self.limiter.observe(r.headers)
            if r.status_code == 401:
                self.tokens.clear()
                if refresh_token:
                    # a failed renewal raises here and is recorded on this attempt below; once it succeeds, this
                    # 401 step is closed and logged before the call is repeated, so the log stays in time order and
                    # a failure of the repeat is never copied onto it (design api-health-checker-followups, 4)
                    await self.token(force=True)
                    result.error = RENEWED
                    result.duration_ms = int((time.perf_counter() - started) * 1000)
                    self._emit(result)
                    emitted = True
                    return await self._attempt(api_path, params, method, refresh_token=False)
                raise NapixAuthError("NAPIX 401 after a fresh token: check the credentials", api=api_path)
            if r.status_code in (429, 500, 502, 503, 504):
                raise NapixUnavailable(f"NAPIX HTTP {r.status_code}", api=api_path)
            if r.status_code == 404:
                raise NapixGatewayError(
                    f"NAPIX gateway 404 for {api_path}: wrong path or product", api=api_path
                )
            if r.status_code != 200:
                raise NapixProtocolError(f"NAPIX HTTP {r.status_code}: {r.text[:300]}", api=api_path)
            self._parse_response(r, result)
            result.ok = True
            return result
        except IntegrationError as e:
            if not emitted:
                result.error, result.error_family = f"{type(e).__name__}: {e.message}"[:500], type(e).__name__
                if e.napix_status:
                    result.napix_status = e.napix_status
            raise
        except Exception as e:  # noqa: BLE001 — recorded, then re-raised
            if not emitted:
                result.error, result.error_family = f"{type(e).__name__}: {e}"[:500], type(e).__name__
            raise
        finally:
            if not emitted:
                result.duration_ms = int((time.perf_counter() - started) * 1000)
                self._emit(result)

    def _emit(self, result: NapixResult) -> None:
        if self.on_call:
            try:
                self.on_call(result)
            except Exception:  # noqa: BLE001 — logging must never break the call
                log.exception("napix on_call hook failed")

    # ------------------------------------------------------------------ envelope (§5)
    def _parse_response(self, r: httpx.Response, result: NapixResult) -> None:
        if r.content.startswith(b"%PDF") or "application/pdf" in r.headers.get("content-type", ""):
            result.pdf = r.content
            return
        text = r.text
        body = _json_or_none(text)
        if body is None:
            result.raw_text = text[:2000]
            m = PRINT_R_STATUS.search(
                text
            )  # PHP print_r: "Array ( [status_code] => 626 [status] => INVALID_TOKEN )"
            if m:
                self._raise_for_status(int(m.group(1)), result, text[:300])
            # empty, or neither JSON, a PDF nor a print_r status: the gateway's intermittent fault (safety-fixes, 5)
            what = "empty response" if not text.strip() else f"non-JSON response: {text[:200]}"
            raise NapixEmptyResponse(f"NAPIX {what}", api=result.api)
        self.parse_body(body, result)

    def signature_matches(self, token: str, text: str, cipher: Any) -> bool:
        """The gateway's `response_token` is HMAC-SHA256 (key 15081947) of the decrypted JSON text, and JSON answers
        verify that way. PDF answers (Show Order, Show Cause List: a JSON string holding Base64) do not
        (napix_integration_notes.md section 4), so the other forms the gateway may have signed are tried too: the
        unquoted Base64 inside the string, and the encrypted `response_str` as sent. A match on any of them counts."""
        candidates = [text]
        inner = _json_or_none(text.strip())
        if isinstance(inner, str):
            candidates.append(inner)
        if isinstance(cipher, str):
            candidates.append(cipher)
        return any(hmac.compare_digest(token, self.crypto.token(c)) for c in candidates)

    def parse_body(self, body: Any, result: NapixResult) -> None:
        """Decrypts `response_str`, verifies `response_token`, maps every error shape seen live. Pure."""
        if isinstance(body, dict) and "response_str" in body:
            try:
                text = self.crypto.decrypt(body["response_str"])
            except ValueError as e:
                raise NapixProtocolError(str(e), api=result.api) from e
            result.raw_text = text
            if body.get("response_token"):
                result.token_verified = self.signature_matches(
                    str(body["response_token"]), text, body["response_str"]
                )
                if not result.token_verified:
                    _warn_mismatch(result.api)
            stripped = text.strip()
            data = _json_or_none(stripped)
            if isinstance(data, str):  # Show Cause List: a JSON string holding the Base64 PDF
                stripped, data = data.strip(), None
            if data is not None:
                status = _status_code(data)
                if status is not None and not _has_payload(data):
                    self._raise_for_status(status, result, data)
                result.data = data
                return
            pdf = _base64_pdf(stripped)
            if pdf is not None:
                result.pdf = pdf
            else:
                result.data = {"raw": stripped}
            return

        if isinstance(body, dict) and "httpCode" in body:  # the gateway answered, eCourts was never reached
            raise NapixGatewayError(
                f"NAPIX gateway {body.get('httpCode')} {body.get('httpMessage')}: {body.get('moreInformation')}",
                api=result.api,
            )

        if isinstance(body, dict) and "status" in body and len(body) <= 3:
            status_val = body["status"]
            if isinstance(status_val, str) and not status_val.strip().isdigit():
                try:
                    dec = self.crypto.decrypt(status_val)
                except ValueError as e:
                    raise NapixProtocolError(
                        "NAPIX returned an encrypted status that NAPIX_AUTH_KEY cannot decrypt",
                        api=result.api,
                    ) from e
                parsed = _json_or_none(dec)
                status = _status_code(parsed) if isinstance(parsed, dict) else _int_or_none(dec)
                if status is None:
                    m = PRINT_R_STATUS.search(dec)
                    status = int(m.group(1)) if m else None
                body = parsed if parsed is not None else {"status": dec}
            else:
                status = _int_or_none(status_val)
            if status is not None:
                self._raise_for_status(status, result, body)
        result.data = body

    def _raise_for_status(self, status: int, result: NapixResult, body: Any) -> None:
        result.napix_status = status
        name = NAPIX_STATUS.get(status, "UNKNOWN")
        msg = f"NAPIX {status} {name}"
        if status in NOT_FOUND_CODES:
            raise NapixNotFound(msg, napix_status=status, api=result.api)
        if status in RETRY_CODES:
            raise NapixUnavailable(msg, napix_status=status, api=result.api)
        if status in AUTH_CODES:
            raise NapixAuthError(
                f"{msg}: the Authentication Key or dept_id is wrong", napix_status=status, api=result.api
            )
        if status in GATEWAY_CODES:
            raise NapixGatewayError(
                f"{msg}: the app is not subscribed to this API", napix_status=status, api=result.api
            )
        raise NapixInputError(f"{msg}: {str(body)[:200]}", napix_status=status, api=result.api)


# ---------------------------------------------------------------------- helpers
def _json_or_none(text: str) -> Any:
    """Parses JSON; tolerates text around it (first `{` to last `}`); None when there is no JSON."""
    t = (text or "").strip()
    if not t:
        return None
    try:
        return json.loads(t)
    except ValueError:
        pass
    s, e = t.find("{"), t.rfind("}")
    if 0 <= s < e:
        try:
            return json.loads(t[s : e + 1])
        except ValueError:
            return None
    return None


def _base64_pdf(text: str) -> bytes | None:
    """Bytes of a PDF carried as Base64 text (`JVBERi0…`), else None."""
    try:
        raw = base64.b64decode("".join(text.split()), validate=True)
    except (ValueError, binascii.Error):
        return None
    return raw if raw.startswith(b"%PDF") else None


def _int_or_none(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None


def _status_code(data: Any) -> int | None:
    if not isinstance(data, dict):
        return None
    for key in ("status", "status_code"):
        n = _int_or_none(data.get(key))
        if n is not None:
            return n
    m = PRINT_R_NAME.search(str(data.get("status", "")))
    return None if m else None


def _has_payload(data: dict[str, Any]) -> bool:
    """A 200-style body may carry `status` beside real data; only a bare status block is an error."""
    return any(k not in ("status", "status_code", "message", "msg") for k in data)


def nested_list(obj: Any) -> list[dict[str, Any]]:
    """NAPIX renders lists as `{"case1": {...}, "case2": {...}}` or `{"sr_no1": {...}}` (notes §4). Returns
    the dict values in numeric key order; passes real lists through; anything else → []."""
    if obj is None:
        return []
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        items = sorted(obj.items(), key=lambda kv: _trailing_int(kv[0]))
        return [v for _, v in items if isinstance(v, dict)]
    return []


def _trailing_int(key: str) -> int:
    digits = "".join(ch for ch in str(key) if ch.isdigit())
    return int(digits) if digits else 0
