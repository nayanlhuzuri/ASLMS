"""The data-health buttons (design `audit-screens`, decisions 8-11): masters sync, re-fetch a cause-list day, a case
or an order PDF, retry a failed queue row or every failed row of a kind, and the one live connectivity check.

- **The buttons enqueue; the API never fetches** (decision 8). Each writes or revives a `fetch_queue` row through
  `queue.enqueue` and returns its state; the worker does the calls within its budget and reserve. Enqueuing while
  the switch is off is allowed (the row waits; nothing is lost).
- **Functions**: masters (sync, retry of `masters` rows) need `admin.masters_sync`; the other kinds
  `admin.napix_refetch`; the check either of them. A re-fetch of a case or an order needs the case visible.
- **Never a made-up identifier**: a case with neither a CNR nor a printed number answers `no_reference`.
- **Lanes and the warning** (design `data-load-console`, decision 12): every button queues in the `request` lane.
  Re-fetching a day already held (done with lists stored, or skipped) or a case with details answers 409
  `already_held` unless `force`; a stored order PDF keeps answering `already_stored` (no `force`).
- **Audit** (decision 11): one row per button (`napix.masters_sync_requested`, `napix.refetch_requested`,
  `napix.queue_retry`, `napix.queue_retry_failed`, `napix.health_checked`); no event, no alert.
- **The check** (decision 10) is the only NAPIX call here, through the integration layer with a `NapixRecorder`:
  one Overview call, refused without a call when the switch is off, a check ran within
  `NAPIX_HEALTH_CHECK_MIN_SECONDS`, or the hour's remaining quota is below `NAPIX_SEARCH_FLOOR`. The payload is
  never returned or stored in the audit row."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from aslms.core.config import Settings
from aslms.core.errors import IntegrationError
from aslms.domain.cases import Case
from aslms.domain.courts import Court
from aslms.domain.documents import DownloadStatus, Order
from aslms.domain.ops import FetchKind, FetchLane, FetchQueueItem, FetchStatus, NapixCallLog
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.integration.napix.client import NapixClient
from aslms.integration.napix.hc import NapixHighCourt
from aslms.services import access, queue
from aslms.services.access import Forbidden, Member
from aslms.services.audit import Actor, write_audit
from aslms.services.audit_search import to_ist
from aslms.services.court_search import latest_remaining_this_hour, seconds_to_next_hour
from aslms.services.data_health import OVERVIEW_API
from aslms.services.napix_store import NapixRecorder
from aslms.services.orders import order_ref
from aslms.services.reporting_common import today_ist
from aslms.services.visibility import require_visible

# decision 9: a person's request runs ahead of new dossiers (40), sweeps (50) and history (60), behind today's lists
REQUEST_PRIORITY = 30
RETRYABLE = (FetchStatus.FAILED, FetchStatus.SKIPPED)


class AdminInputError(ValueError):
    """Bad input (HTTP 400), e.g. `date_in_future`."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AdminConflict(Exception):
    """The state does not allow the button (HTTP 409); `extra` goes into the error body."""

    code = "conflict"

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.extra = extra


class Merged(AdminConflict):
    code = "merged"


class NoReference(AdminConflict):
    code = "no_reference"


class AlreadyStored(AdminConflict):
    code = "already_stored"


class AlreadyHeld(AdminConflict):
    """The data is already in the database; the caller may send `force` (design `data-load-console`, decision 12)."""

    code = "already_held"


class NotRetryable(AdminConflict):
    code = "not_retryable"


class AdminNotFound(LookupError):
    """No such queue row or order of that case (HTTP 404)."""


class CheckRefused(Exception):
    """The connectivity check was refused before any call: `napix_off` (409), `check_too_soon` or `napix_budget`
    (429 with `retry_after`)."""

    def __init__(self, code: str, message: str, http_status: int, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.code, self.http_status, self.retry_after = code, http_status, retry_after


@dataclass
class CheckOutcome:
    ok: bool
    called_at: datetime
    http_status: int | None
    napix_status: int | None
    error_family: str | None
    duration_ms: int
    token_verified: bool | None
    remaining: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "called_at": to_ist(self.called_at),
            "http_status": self.http_status,
            "napix_status": self.napix_status,
            "error_family": self.error_family,
            "duration_ms": self.duration_ms,
            "token_verified": self.token_verified,
            "remaining": self.remaining,
        }


# ------------------------------------------------------------------------------------------------ helpers


def _value(v: Any) -> Any:
    return v.value if hasattr(v, "value") else v


def acting_member(session: Session, user: User | Member | None, *permissions: Permission) -> Member | None:
    """The caller's membership holding one of the functions (the super admin's first); `None` for the CLI before a
    super admin exists (the `system` actor). Forbidden when a login holds none of them."""
    if user is None:
        return None
    holders = [m for m in access.members(session, user) if any(m.holds(p) for p in permissions)]
    if not holders:
        raise Forbidden(" or ".join(p.value for p in permissions) + " is not enabled for you")
    holders.sort(key=lambda m: not m.is_super_admin)
    return holders[0]


def state_of(
    session: Session, row: FetchQueueItem | None, kind: FetchKind, ref: str, settings: Settings
) -> dict:
    return {
        "kind": kind.value,
        "ref": ref,
        "queue_id": row.id if row is not None else None,
        "status": _value(row.status) if row is not None else None,
        "priority": row.priority if row is not None else None,
        "attempts": row.attempts if row is not None else 0,
        "not_before": to_ist(row.not_before) if row is not None else None,
        "lane": _value(row.lane) if row is not None else None,
        "napix_enabled": bool(settings.napix_configured),
    }


def _enqueue(
    session: Session,
    actor: Actor,
    member: Member | None,
    action: str,
    kind: FetchKind,
    ref: str,
    priority: int,
    settings: Settings,
    *,
    case_id: uuid.UUID | None = None,
    extra: dict[str, Any] | None = None,
    list_date: date | None = None,
) -> dict[str, Any]:
    before = queue.get_state(session, kind, ref)
    status_before = _value(before.status) if before is not None else None
    queue.enqueue(session, kind, ref, priority, requeue=True, lane=FetchLane.REQUEST, list_date=list_date)
    row = queue.get_state(session, kind, ref)
    write_audit(
        session,
        access.actor_as(actor, member),
        action,
        "fetch_queue",
        row.id if row is not None else None,
        after={
            "kind": kind.value,
            "ref": ref,
            "priority": row.priority if row is not None else priority,
            "status_before": status_before,
            "status_after": _value(row.status) if row is not None else None,
            "lane": _value(row.lane) if row is not None else FetchLane.REQUEST.value,
            **(extra or {}),
        },
        case_id=case_id,
    )
    return state_of(session, row, kind, ref, settings)


# ------------------------------------------------------------------------------------------------ buttons


def request_masters_sync(
    session: Session, actor: Actor, user: User | Member | None, settings: Settings
) -> dict[str, Any]:
    """`masters/all` at priority 10, re-queued even when done."""
    member = acting_member(session, user, Permission.ADMIN_MASTERS_SYNC)
    return _enqueue(
        session,
        actor,
        member,
        "napix.masters_sync_requested",
        FetchKind.MASTERS,
        "all",
        queue.PRIORITY["masters"],
        settings,
    )


def refetch_day(
    session: Session,
    actor: Actor,
    user: User | Member | None,
    list_date: date,
    settings: Settings,
    today: date | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """`causelist_day/<date>` at priority 20 in the request lane, as `aslms refetch-date`; not after tomorrow
    (IST). A day already held (done with lists stored, or skipped: the court published none) answers
    `already_held` without `force`, before anything is written."""
    member = acting_member(session, user, Permission.ADMIN_NAPIX_REFETCH)
    today = today or today_ist()
    if list_date > today + timedelta(days=1):
        raise AdminInputError("date_in_future", "a cause list can be fetched up to tomorrow")
    if not force:
        held = day_held(session, list_date)
        if held is not None:
            raise AlreadyHeld(f"the cause lists of {list_date} are already in the database", **held)
    extra = {"force": force} if force else None
    return _enqueue(
        session,
        actor,
        member,
        "napix.refetch_requested",
        FetchKind.CAUSELIST_DAY,
        list_date.isoformat(),
        queue.PRIORITY["list_today"],
        settings,
        extra=extra,
        list_date=list_date,
    )


def day_held(session: Session, list_date: date) -> dict[str, Any] | None:
    """The `already_held` body for a day whose row is done with lists stored, or skipped; None otherwise."""
    row = queue.get_state(session, FetchKind.CAUSELIST_DAY, list_date.isoformat())
    if row is None:
        return None
    status = FetchStatus(_value(row.status))
    stored = int(
        session.scalar(
            text("SELECT count(*) FROM causelists WHERE list_date = :d AND document_id IS NOT NULL"),
            {"d": list_date},
        )
        or 0
    )
    if (status == FetchStatus.DONE and stored > 0) or status == FetchStatus.SKIPPED:
        return {"status": status.value, "lists_stored": stored, "finished_at": to_ist(row.finished_at)}
    return None


def dossier_ref(session: Session, case: Case) -> str:
    """The runner's ref: the CNR, or `<est_code>|<case number as printed>` for a provisional case."""
    if case.cnr:
        return case.cnr
    if case.case_no_text:
        court = session.get(Court, case.court_id)
        return f"{court.est_code}|{case.case_no_text}"
    raise NoReference("the case has neither a CNR nor a case number; it cannot be fetched")


def _visible(session: Session, user: User | Member | None, case: Case) -> None:
    if user is not None:
        require_visible(session, user, case)  # NotVisibleCase → 404


def refetch_case(
    session: Session,
    actor: Actor,
    user: User | Member | None,
    case: Case,
    settings: Settings,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """`dossier/<ref>` at priority 30 in the request lane, as `aslms refetch-case`; the case visible to the caller.
    A case whose details are held answers `already_held` without `force`."""
    member = acting_member(session, user, Permission.ADMIN_NAPIX_REFETCH)
    _visible(session, user, case)
    if case.merged_into_case_id is not None:
        target = session.get(Case, case.merged_into_case_id)
        raise Merged(
            f"the case was merged into {target.ref_no if target else 'another case'}",
            ref_no=target.ref_no if target else None,
        )
    ref = dossier_ref(session, case)
    if not force and case.last_full_refresh_at is not None:
        raise AlreadyHeld(
            "the case's details are already in the database",
            dossier_fetched_at=to_ist(case.last_full_refresh_at),
            dossier_stale=bool(case.dossier_stale),
        )
    return _enqueue(
        session,
        actor,
        member,
        "napix.refetch_requested",
        FetchKind.DOSSIER,
        ref,
        REQUEST_PRIORITY,
        settings,
        case_id=case.id,
        extra={"force": True} if force else None,
    )


def refetch_order(
    session: Session,
    actor: Actor,
    user: User | Member | None,
    case: Case,
    order_id: uuid.UUID,
    settings: Settings,
) -> dict[str, Any]:
    """The order of this case goes back to `pending` and `order_pdf/<CNR>|<order_no>|<date>` is queued at 30."""
    member = acting_member(session, user, Permission.ADMIN_NAPIX_REFETCH)
    _visible(session, user, case)
    order = session.scalar(select(Order).where(Order.id == order_id, Order.case_id == case.id))
    if order is None:
        raise AdminNotFound("no such order of this case")
    if order.document_id is not None:
        raise AlreadyStored("the order's PDF is already stored")
    if not case.cnr:
        raise NoReference("the case has no CNR; its orders cannot be fetched")
    status_before = _value(order.download_status)
    order.download_status = DownloadStatus.PENDING
    session.flush()
    return _enqueue(
        session,
        actor,
        member,
        "napix.refetch_requested",
        FetchKind.ORDER_PDF,
        order_ref(case.cnr, order),
        REQUEST_PRIORITY,
        settings,
        case_id=case.id,
        extra={"order_id": str(order.id), "download_status_before": status_before},
    )


def _kind_permission(kind: FetchKind) -> Permission:
    return Permission.ADMIN_MASTERS_SYNC if kind == FetchKind.MASTERS else Permission.ADMIN_NAPIX_REFETCH


def retry_item(
    session: Session, actor: Actor, user: User | Member, item_id: uuid.UUID, settings: Settings
) -> dict[str, Any]:
    """A `failed` or `skipped` row back to `pending` with no attempts; any other state is `not_retryable`."""
    row = session.scalar(
        select(FetchQueueItem)
        .where(FetchQueueItem.id == item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise AdminNotFound("no such queue row")
    kind = FetchKind(_value(row.kind))
    member = acting_member(session, user, _kind_permission(kind))
    status_before = _value(row.status)
    if FetchStatus(status_before) not in RETRYABLE:
        raise NotRetryable(
            f"the row is {status_before}; only failed or skipped rows are retried", status=status_before
        )
    ref, priority = row.ref, row.priority
    queue.enqueue(session, kind, ref, priority)
    row = queue.get_state(session, kind, ref)
    write_audit(
        session,
        access.actor_as(actor, member),
        "napix.queue_retry",
        "fetch_queue",
        row.id,
        after={
            "kind": kind.value,
            "ref": ref,
            "priority": row.priority,
            "status_before": status_before,
            "status_after": _value(row.status),
        },
    )
    return state_of(session, row, kind, ref, settings)


def retry_failed(
    session: Session, actor: Actor, user: User | Member, kind: FetchKind, lane: FetchLane | None = None
) -> int:
    """Every `failed` row of one kind (of one lane when given: "retry the load's failed details" leaves the daily
    lane alone) back to `pending` in one statement; one audit row with the count."""
    member = acting_member(session, user, _kind_permission(kind))
    lane_filter = "AND lane = CAST(:lane AS fetch_lane)" if lane is not None else ""
    n = (
        session.execute(
            text(
                f"""
                UPDATE fetch_queue SET status = 'pending', attempts = 0, not_before = NULL, last_error = NULL
                WHERE kind = CAST(:kind AS fetch_kind) AND status = 'failed' {lane_filter}
                """
            ),
            {"kind": kind.value, "lane": FetchLane(lane).value if lane is not None else None},
        ).rowcount
        or 0
    )
    write_audit(
        session,
        access.actor_as(actor, member),
        "napix.queue_retry_failed",
        "fetch_queue",
        None,
        after={"kind": kind.value, "lane": FetchLane(lane).value if lane is not None else None, "retried": n},
    )
    return n


# ------------------------------------------------------------------------------------------------ the check


def check_guard(session: Session, settings: Settings, now: datetime | None = None) -> None:
    """Decision 10's refusals, before any call and writing nothing."""
    now = now or datetime.now(UTC)
    if not settings.napix_configured:
        raise CheckRefused("napix_off", "NAPIX is switched off on this server", 409)
    last = session.scalar(select(func.max(NapixCallLog.called_at)).where(NapixCallLog.api == OVERVIEW_API))
    min_s = settings.napix_health_check_min_seconds
    if last is not None:
        elapsed = (now - last).total_seconds()
        if elapsed < min_s:
            raise CheckRefused(
                "check_too_soon",
                f"a connectivity check ran {int(max(elapsed, 0))} s ago; wait {min_s} s between checks",
                429,
                retry_after=max(1, int(min_s - elapsed + 0.999)),
            )
    remaining = latest_remaining_this_hour(session)
    if remaining is not None and remaining < settings.napix_search_floor:
        raise CheckRefused(
            "napix_budget",
            f"the court gateway's hourly quota is nearly spent ({remaining} calls left)",
            429,
            retry_after=seconds_to_next_hour(now),
        )


async def health_check(
    session: Session,
    actor: Actor,
    user: User | Member,
    settings: Settings,
    client: NapixClient,
    hc: NapixHighCourt,
) -> CheckOutcome:
    """One Overview call with the recorder attached; the attempt(s) land in `napix_call_log` like any other call. An
    integration error is an outcome (`ok = false` with its family), not an exception."""
    member = acting_member(session, user, Permission.ADMIN_NAPIX_REFETCH, Permission.ADMIN_MASTERS_SYNC)
    check_guard(session, settings)
    recorder = NapixRecorder()
    client.on_call = recorder.on_call
    called_at = datetime.now(UTC)
    error_family: str | None = None
    ok = True
    try:
        async with client:
            await hc.overview()
    except (IntegrationError, httpx.HTTPError) as exc:
        ok = False
        error_family = type(exc).__name__
    attempts = list(recorder.pending)
    recorder.flush(session)
    last = attempts[-1] if attempts else None
    outcome = CheckOutcome(
        ok=ok and last is not None and last.ok,
        called_at=called_at,
        http_status=last.http_status if last else None,
        napix_status=last.napix_status if last else None,
        error_family=(last.error_family if last and last.error_family else error_family),
        duration_ms=sum(a.duration_ms for a in attempts),
        token_verified=last.token_verified if last else None,
        remaining=recorder.last_remaining,
    )
    write_audit(
        session,
        access.actor_as(actor, member),
        "napix.health_checked",
        "napix",
        None,
        after={**outcome.to_dict(), "attempts": len(attempts)},
    )
    return outcome
