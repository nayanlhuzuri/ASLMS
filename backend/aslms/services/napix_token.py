"""The Access token card of the System health screen (design `system-health-inspector`, decision 10).

- `state` reads, with no call: whether a token is held and for how long (the shared Redis copy), the non-secret
  metadata the integration layer writes on every token request (issued, expires, type, scope, the last request and
  failure, requests today), and whether the court gateway accepted the current token since it was issued (the call
  log). Never the token, never a token request: opening the screen spends nothing.
- `check` is "Check token": one fresh token request through `NapixClient.renew_token()` (no retry), refused before any
  request and writing nothing by `check_guard` (switch off, a check by anyone within `HEALTH_TOKEN_CHECK_MIN_SECONDS`,
  the person's hourly cap shared with sends, the quota floor, one check at a time); then one audit row
  `napix.token_checked` written apart, as a send's audit row is. A token-service failure is an outcome."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from aslms.core import clock
from aslms.core.config import Settings
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.integration.napix.client import NapixClient, TokenCache
from aslms.services import access, audit, napix_inspect, napix_window, system_health
from aslms.services.access import Member
from aslms.services.audit import Actor
from aslms.services.audit_search import to_ist
from aslms.services.napix_admin import acting_member
from aslms.services.napix_api_check import TestRefused, _over_cap
from aslms.services.reporting_common import with_timeout

ACTION = system_health.TOKEN_ACTION
RENEW_MARGIN_SECONDS = 60  # the client renews when under 60 s remain
OFF = "Court calls are switched off on this server (NAPIX_ENABLED is false)"


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _int(value: str | None) -> int | None:
    return int(value) if value not in (None, "") and str(value).lstrip("-").isdigit() else None


def outcome_words(ok: bool | None, http_status: int | None, error_family: str | None) -> str | None:
    """The plain words of a token request's outcome."""
    if ok is None:
        return None
    if ok:
        return "obtained"
    if http_status in (401, 403):
        return "refused: check NAPIX_CLIENT_ID / SECRET"
    if error_family == "NapixProtocolError":
        return "no access_token in the answer"
    if http_status is not None:
        return f"the token service answered HTTP {http_status}"
    return "the token service did not answer"


def _accepted_since(session: Session, since: datetime) -> tuple[dict[str, Any] | None, int]:
    """The latest call the gateway accepted the token on (any HTTP status other than 401) since `since`, and the
    count of HTTP 401 answers since then (`ix_napix_call_log_called_at`)."""
    row = session.execute(
        text(
            """
            SELECT api, called_at, http_status FROM napix_call_log
            WHERE called_at >= :since AND http_status IS NOT NULL AND http_status <> 401
            ORDER BY called_at DESC, id DESC LIMIT 1
            """
        ),
        {"since": since},
    ).first()
    rejected = session.scalar(
        text("SELECT count(*) FROM napix_call_log WHERE called_at >= :since AND http_status = 401"),
        {"since": since},
    )
    accepted = None
    if row is not None:
        e = system_health.BY_PATH.get(row.api)
        accepted = {
            "at": to_ist(row.called_at),
            "api_label": e.label if e is not None else row.api,
            "http_status": row.http_status,
        }
    return accepted, int(rejected or 0)


def status_of(
    *,
    napix_enabled: bool,
    shared_store: bool,
    held: bool,
    last_ok: bool | None,
    rejected_since: int,
) -> str:
    """Decision 10's status rules, in order."""
    if not napix_enabled and not held:
        return "unknown"
    if last_ok is False and not held:
        return "down"
    if rejected_since > 0:
        return "down"
    if not shared_store:
        return "warn"
    if last_ok is False and held:
        return "warn"
    if held:
        return "ok"
    return "unknown"


def _wait(at: datetime, now: datetime) -> int:
    return max(1, math.ceil((at - now).total_seconds()))


def last_check_at(session: Session) -> datetime | None:
    return session.scalar(
        text("SELECT max(created_at) FROM audit_log WHERE action = :a"),
        {"a": ACTION},
    )


def check_guard(
    session: Session, settings: Settings, user: User | Member, now: datetime | None = None
) -> None:
    """Refusals before any request, writing nothing: 409 `napix_off`; 429 `check_too_soon`, `test_limit`,
    `napix_budget`."""
    now = now or datetime.now(UTC)
    if not settings.napix_configured:
        raise TestRefused("napix_off", OFF, 409)
    last = last_check_at(session)
    if last is not None:
        at = last + timedelta(seconds=settings.health_token_check_min_seconds)
        if at > now:
            wait = _wait(at, now)
            raise TestRefused(
                "check_too_soon",
                f"The token was checked a moment ago; the next check is possible in {wait} s",
                429,
                wait,
            )
    _over_cap(session, settings, user, now)
    window = napix_window.current(session, settings, now)
    if window.remaining is not None and window.remaining < settings.napix_search_floor:
        raise TestRefused(
            "napix_budget",
            "The court's hourly allowance is nearly used up; the check is possible after the reset",
            429,
            window.retry_after(now),
        )


def check_block(
    session: Session, settings: Settings, user: User | Member | None, now: datetime
) -> dict[str, Any]:
    """`check`: whether "Check token" may be pressed now, the reason and the next allowed time (no request)."""
    if user is None:
        return {"allowed": False, "reason": None, "next_allowed_at": None}
    try:
        check_guard(session, settings, user, now)
    except TestRefused as exc:
        at = now + timedelta(seconds=exc.retry_after) if exc.retry_after else None
        return {"allowed": False, "reason": str(exc), "next_allowed_at": to_ist(at)}
    return {"allowed": True, "reason": None, "next_allowed_at": None}


def state(
    session: Session,
    settings: Settings,
    cache: TokenCache,
    user: User | Member | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """`TokenOut`: read when the screen and the modal open; no call, not audited, never the token."""
    now = now or clock.now_utc()
    with_timeout(session, settings.report_statement_timeout_seconds)
    held = cache.state()
    meta = cache.meta(now)  # `requests_today` by the IST date of the same `now` as the rest of the card
    obtained = _dt(meta.get("obtained_at"))
    accepted, rejected = _accepted_since(session, obtained) if obtained is not None else (None, 0)
    last_ok = None if not meta.get("requested_at") else meta.get("ok") == "1"
    http_status = _int(meta.get("http_status"))
    family = meta.get("error_family") or None
    status = status_of(
        napix_enabled=bool(settings.napix_configured),
        shared_store=held.shared_store,
        held=held.held,
        last_ok=last_ok,
        rejected_since=rejected,
    )
    ttl = held.ttl_seconds
    return {
        "status": status,
        "napix_enabled": bool(settings.napix_configured),
        "shared_store": held.shared_store,
        "held": held.held,
        "ttl_seconds": ttl,
        "renewing_soon": bool(held.held and ttl is not None and ttl < RENEW_MARGIN_SECONDS),
        "valid_until": to_ist(now + timedelta(seconds=ttl)) if ttl else None,
        "expires_at": to_ist(_dt(meta.get("expires_at"))),
        "obtained_at": to_ist(obtained),
        "token_type": meta.get("token_type") or None,
        "scope": meta.get("scope") or None,
        "accepted_since": accepted,
        "rejected_since": rejected,
        "last_request": (
            {
                "at": to_ist(_dt(meta.get("requested_at"))),
                "ok": bool(last_ok),
                "outcome": outcome_words(last_ok, http_status, family),
                "http_status": http_status,
                "duration_ms": _int(meta.get("duration_ms")),
                "rate_limit": {
                    "limit": _int(meta.get("rate_limit_limit")),
                    "remaining": _int(meta.get("rate_limit_remaining")),
                },
            }
            if last_ok is not None
            else None
        ),
        "last_failure": (
            {
                "at": to_ist(_dt(meta.get("last_failure_at"))),
                "family": meta.get("last_failure_family") or None,
            }
            if meta.get("last_failure_at")
            else None
        ),
        "requests_today": _int(meta.get("requests_today")) or 0,
        "endpoint": napix_inspect.token_endpoint(settings),
        "curl_token": napix_inspect.curl_token(settings),
        "check": check_block(session, settings, user, now),
    }


def lock(session: Session) -> None:
    """409 `check_running` while another token check is in flight (transaction-scoped: PgBouncer-safe)."""
    got = session.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": "napix-token-check"}
    )
    if not got:
        raise TestRefused("check_running", "A token check is running; try again in a moment", 409)


async def check(
    session: Session,
    session_factory: sessionmaker[Session],
    actor: Actor,
    user: User | Member,
    settings: Settings,
    client: NapixClient,
    cache: TokenCache,
) -> dict[str, Any]:
    """One token request (decision 10). The request session only reads and holds the lock; the audit row is
    committed apart."""
    member = acting_member(session, user, Permission.ADMIN_SERVICE_HEALTH)
    check_guard(session, settings, user)
    lock(session)
    check_guard(session, settings, user)  # a check committed while this request waited for the lock
    client.tokens = cache
    client.max_attempts = 1
    client.timeout = settings.health_test_timeout_seconds
    try:
        async with client:
            renewal = await client.renew_token()
    except Exception as exc:  # ASLMS's own defect: recorded by its class in the audit row, then raised again
        known = getattr(client, "last_token_request", None)  # the request's outcome, when it got that far
        audit.write_audit_apart(
            session_factory,
            access.actor_as(actor, member),
            ACTION,
            "napix",
            None,
            after={
                "ok": False,
                "http_status": known.http_status if known is not None else None,
                "error_family": known.error_family if known is not None else None,
                "duration_ms": known.duration_ms if known is not None else None,
                "unexpected": type(exc).__name__,  # the class only, never the text (followups-oct, 6)
            },
        )
        raise
    rate = {"limit": renewal.rate_limit[0], "remaining": renewal.rate_limit[1]}
    audit.write_audit_apart(
        session_factory,
        access.actor_as(actor, member),
        ACTION,
        "napix",
        None,
        after={
            "ok": renewal.ok,
            "http_status": renewal.http_status,
            "error_family": renewal.error_family,
            "duration_ms": renewal.duration_ms,
            "expires_in": renewal.expires_in,
            "rate_limit": rate,
        },
    )
    return {
        "ok": renewal.ok,
        "http_status": renewal.http_status,
        "outcome": outcome_words(renewal.ok, renewal.http_status, renewal.error_family),
        "duration_ms": renewal.duration_ms,
        "expires_in": renewal.expires_in,
        "rate_limit": rate,
    }
