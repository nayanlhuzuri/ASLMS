"""The data-load console (design `data-load-console`): the backdated NAPIX load's settings, start, progress,
estimate and coverage; single-case fetches from the court and details of found cases, each with a warning before
any call when the data is already held; the duplicate lists and the on-demand scan.

- **Settings** (decision 18): `data_load_settings` is a versioned master. `pause`, `resume` and `set_order` insert a
  new version and close the previous one; each writes one audit row (`data_load.paused`, `data_load.resumed`,
  `data_load.order_changed`). Pausing while paused or resuming while running answers `no_change`. `set_order`
  rewrites the priority of every pending load row in one statement (decision 3).
- **Start** (decision 9): `preview` writes nothing and makes no call. `start` queues each day of the range in the
  `load` lane with its `list_date` and the policy priority; days already held (done with lists, or skipped: the
  court published none) need an explicit `held` choice (`skip` or `refetch`), otherwise `AlreadyHeld` and nothing is
  written. Failed days are revived; waiting days keep their row and take the load priority when better. The masters
  are queued when older than 24 h. One audit row `data_load.started`.
- **Progress and estimate** (decisions 6-8): read only, under the report statement timeout. The estimate uses
  measured rates only and says why when it gives none (`paused`, `not_enough_history`, `no_recent_calls`).
- **Fetch** (decisions 10-11): a check in the database first (`check_held`), then the court search with its guard;
  audited as `case.search_court` with `via: data_load`, `force` and `warned`. Details of found cases are queued in
  the `request` lane; one audit row `data_load.details_requested`.
- **Duplicates** (decision 16): `duplicates` lists merged rows, court-duplicate links and pairs needing review (ref,
  CNR and case number only); `scan` runs the sweep, audited `data_load.dedupe_scan`.
Every action needs `admin.data_load`; reading needs it or a health reader (decision 17)."""

from __future__ import annotations

import calendar
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from aslms.core.config import Settings
from aslms.domain.cases import Case, CaseLink, CaseParty, LinkKind
from aslms.domain.courts import MasterSyncRun
from aslms.domain.events import AuditLog
from aslms.domain.ops import (
    DataLoadSettings,
    FetchKind,
    FetchLane,
    FetchQueueItem,
    FetchStatus,
    LoadOrder,
    NapixCallLog,
    SourceFailure,
)
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.integration.napix.hc import API, NapixHighCourt
from aslms.services import access, case_dedupe, court_search, queue
from aslms.services.access import Member
from aslms.services.audit import Actor, write_audit
from aslms.services.audit_search import to_ist
from aslms.services.cases import CaseNotFound, normalise_name, resolve_case_ref
from aslms.services.load_policy import (
    DEFAULTS,
    FORWARD,
    LOAD_KINDS,
    OTHERWISE,
    PRESET_ORDER,
    REQUEST_PRIORITY,
    LoadSettings,
    QueueOrigin,
    current_row,
    current_settings,
    from_row,
    load_priority,
)
from aslms.services.napix_admin import NoReference, acting_member, dossier_ref, state_of
from aslms.services.napix_store import NapixRecorder
from aslms.services.reporting_common import today_ist, with_timeout

__all__ = [
    "DEFAULTS",
    "LoadSettings",
    "QueueOrigin",
    "current_settings",
    "load_priority",
]

QUERY_CANCELED = "57014"
MIN_DATE = date(1950, 1, 1)
MAX_COVERAGE_MONTHS = 36
MASTERS_MAX_AGE = timedelta(hours=24)
HISTORY_MIN = timedelta(hours=24)
REASON_MIN, REASON_MAX = 3, 500
DETAILS_MAX = 200
LATEST_FAILURES = 20
# the API families of the call log (decision 8): cause-list APIs make a day, CNR and case-number searches a dossier,
# Show Order an order PDF
FAMILY: dict[FetchKind, tuple[str, ...]] = {
    FetchKind.CAUSELIST_DAY: (API["causelist_bench"], API["causelist_details"], API["show_causelist"]),
    FetchKind.DOSSIER: (API["cnr"], API["cnr_alt"], API["case_search"]),
    FetchKind.ORDER_PDF: (API["order"],),
}
READERS = (
    Permission.ADMIN_DATA_LOAD,
    Permission.REPORTS_STATE,
    Permission.ADMIN_NAPIX_REFETCH,
    Permission.ADMIN_MASTERS_SYNC,
)


# ------------------------------------------------------------------------------------------------ errors


class LoadInputError(ValueError):
    """Bad input (HTTP 400): `bad_range`, `bad_period`, `bad_reason`, `bad_input`."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class LoadConflict(Exception):
    """The state refuses the action (HTTP 409); `extra` joins the error body."""

    code = "conflict"

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.extra = extra


class NoChange(LoadConflict):
    code = "no_change"


class AlreadyHeld(LoadConflict):
    """The data is already in the database; nothing was written and no call made. `cases` (for a fetch) holds the
    held case rows, which the router turns into summaries."""

    code = "already_held"

    def __init__(self, message: str, cases: list[Case] | None = None, **extra: Any) -> None:
        super().__init__(message, **extra)
        self.cases = cases or []


class SearchedBefore(LoadConflict):
    code = "searched_before"


class SearchTimeout(Exception):
    """A coverage query exceeded the report statement timeout (HTTP 503 `search_timeout`)."""


# ------------------------------------------------------------------------------------------------ helpers


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now(UTC)


def _value(v: Any) -> Any:
    return v.value if hasattr(v, "value") else v


def _hour_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _days(from_: date, to: date) -> list[date]:
    return [from_ + timedelta(days=i) for i in range((to - from_).days + 1)]


def settings_dict(s: LoadSettings) -> dict[str, Any]:
    return {
        "version": s.version,
        "paused": s.paused,
        "load_order": LoadOrder(s.load_order).value,
        "first_from": s.first_from,
        "first_to": s.first_to,
        "reason": s.reason,
        "changed_at": to_ist(s.changed_at),
        "changed_by": s.changed_by,
    }


def can_read(session: Session, user: User | Member) -> bool:
    return any(access.has(session, user, p) for p in READERS)


def _member(session: Session, user: User | Member | None) -> Member | None:
    return acting_member(session, user, Permission.ADMIN_DATA_LOAD)


def load_period(session: Session) -> tuple[date, date] | None:
    """From the earliest to the latest `list_date` of the load lane's `causelist_day` rows (decision 6)."""
    lo, hi = session.execute(
        select(func.min(FetchQueueItem.list_date), func.max(FetchQueueItem.list_date)).where(
            FetchQueueItem.lane == FetchLane.LOAD, FetchQueueItem.kind == FetchKind.CAUSELIST_DAY
        )
    ).one()
    return (lo, hi) if lo is not None else None


# ------------------------------------------------------------------------------------------------ settings


def _new_version(
    session: Session,
    actor: Actor,
    *,
    paused: bool,
    load_order: LoadOrder,
    first_from: date | None,
    first_to: date | None,
    reason: str,
) -> tuple[LoadSettings, LoadSettings]:
    """Close the current version and insert the next one. Returns (before, after)."""
    row = current_row(session, lock=True)
    before = from_row(session, row) if row is not None else DEFAULTS
    if row is not None:
        row.is_current = False
        row.valid_to = datetime.now(UTC)
        row.updated_by = actor.user_id
        session.flush()
    new = DataLoadSettings(
        version=before.version + 1,
        paused=paused,
        load_order=load_order,
        first_from=first_from,
        first_to=first_to,
        reason=reason,
        is_current=True,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    session.add(new)
    session.flush()
    return before, from_row(session, new)


def _reason(reason: str | None, *, required: bool = True) -> str | None:
    text_ = (reason or "").strip()
    if not text_:
        if required:
            raise LoadInputError("bad_reason", "a reason is required")
        return None
    if not (REASON_MIN <= len(text_) <= REASON_MAX):
        raise LoadInputError("bad_reason", f"the reason is {REASON_MIN} to {REASON_MAX} characters")
    return text_


def pause(session: Session, actor: Actor, user: User | Member | None, reason: str) -> LoadSettings:
    member = _member(session, user)
    why = _reason(reason)
    cur = current_settings(session)
    if cur.paused:
        raise NoChange("the load is already paused")
    before, after = _new_version(
        session,
        actor,
        paused=True,
        load_order=cur.load_order,
        first_from=cur.first_from,
        first_to=cur.first_to,
        reason=why,
    )
    write_audit(
        session,
        access.actor_as(actor, member),
        "data_load.paused",
        "data_load_settings",
        None,
        before=settings_dict(before),
        after=settings_dict(after),
    )
    return after


def resume(
    session: Session, actor: Actor, user: User | Member | None, reason: str | None = None
) -> LoadSettings:
    member = _member(session, user)
    why = _reason(reason, required=False) or "resumed"
    cur = current_settings(session)
    if not cur.paused:
        raise NoChange("the load is running")
    before, after = _new_version(
        session,
        actor,
        paused=False,
        load_order=cur.load_order,
        first_from=cur.first_from,
        first_to=cur.first_to,
        reason=why,
    )
    write_audit(
        session,
        access.actor_as(actor, member),
        "data_load.resumed",
        "data_load_settings",
        None,
        before=settings_dict(before),
        after=settings_dict(after),
    )
    return after


def reprioritise(session: Session, settings: LoadSettings) -> int:
    """Every pending load row takes the policy priority (decision 3), in one statement."""
    k = PRESET_ORDER[LoadOrder(settings.load_order)]
    params: dict[str, Any] = {
        "k1": k[0].value,
        "k2": k[1].value,
        "k3": k[2].value,
        "f1": FORWARD[0],
        "f2": FORWARD[1],
        "f3": FORWARD[2],
        "o1": OTHERWISE[0],
        "o2": OTHERWISE[1],
        "o3": OTHERWISE[2],
        "ff": settings.first_from,
        "ft": settings.first_to,
    }
    forward = (
        "CASE kind WHEN CAST(:k1 AS fetch_kind) THEN :f1 WHEN CAST(:k2 AS fetch_kind) THEN :f2 ELSE :f3 END"
    )
    otherwise = (
        "CASE kind WHEN CAST(:k1 AS fetch_kind) THEN :o1 WHEN CAST(:k2 AS fetch_kind) THEN :o2 ELSE :o3 END"
    )
    sql = f"""
        UPDATE fetch_queue SET priority = CASE
            WHEN CAST(:ff AS date) IS NOT NULL AND list_date BETWEEN CAST(:ff AS date) AND CAST(:ft AS date)
            THEN {forward} ELSE {otherwise} END
        WHERE lane = 'load' AND status = 'pending'
          AND kind IN ('causelist_day', 'dossier', 'order_pdf')
    """
    return int(session.execute(text(sql), params).rowcount or 0)


def set_order(
    session: Session,
    actor: Actor,
    user: User | Member | None,
    load_order: LoadOrder | str,
    first_from: date | None,
    first_to: date | None,
    reason: str,
) -> tuple[LoadSettings, int]:
    """A new version with the preset and the optional period brought forward; pending load rows re-prioritised.
    Returns (settings, rows re-prioritised)."""
    member = _member(session, user)
    why = _reason(reason)
    try:
        order = LoadOrder(load_order)
    except ValueError as exc:
        raise LoadInputError(
            "bad_input", f"load_order is one of {', '.join(o.value for o in LoadOrder)}"
        ) from exc
    if (first_from is None) != (first_to is None):
        raise LoadInputError("bad_period", "give both ends of the period to bring forward, or neither")
    if first_from is not None and first_to is not None:
        if first_from > first_to:
            raise LoadInputError("bad_period", "the period starts after it ends")
        period = load_period(session)
        if period is None or first_from < period[0] or first_to > period[1]:
            raise LoadInputError("bad_period", "the period brought forward must lie inside the load period")
    cur = current_settings(session)
    before, after = _new_version(
        session,
        actor,
        paused=cur.paused,
        load_order=order,
        first_from=first_from,
        first_to=first_to,
        reason=why,
    )
    n = reprioritise(session, after)
    write_audit(
        session,
        access.actor_as(actor, member),
        "data_load.order_changed",
        "data_load_settings",
        None,
        before=settings_dict(before),
        after={**settings_dict(after), "reprioritised": n},
    )
    return after, n


# ------------------------------------------------------------------------------------------------ start


@dataclass
class Preview:
    days: int
    held_with_lists: int
    held_no_list: int
    waiting: int
    failed: int
    not_queued: int
    calls_estimate: float | None
    masters_stale: bool

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class StartResult:
    days: int
    queued: int = 0
    held_skipped: int = 0
    held_requeued: int = 0
    revived: int = 0
    masters_queued: bool = False

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def check_range(from_: date, to: date, today: date | None = None) -> None:
    """`from ≤ to ≤ yesterday` (IST) and `from ≥ 1950-01-01`: today and tomorrow belong to the daily cycle."""
    today = today or today_ist()
    if from_ > to:
        raise LoadInputError("bad_range", "from must not be after to")
    if to >= today:
        raise LoadInputError("bad_range", "the backdated load ends yesterday at the latest")
    if from_ < MIN_DATE:
        raise LoadInputError("bad_range", f"the load starts on {MIN_DATE} at the earliest")


DAY_STATE = {
    FetchStatus.DONE: "held_with_lists",
    FetchStatus.SKIPPED: "held_no_list",
    FetchStatus.PENDING: "waiting",
    FetchStatus.RUNNING: "waiting",
    FetchStatus.FAILED: "failed",
}


def _day_states(session: Session, from_: date, to: date) -> dict[date, str]:
    rows = session.execute(
        select(FetchQueueItem.ref, FetchQueueItem.status).where(
            FetchQueueItem.kind == FetchKind.CAUSELIST_DAY,
            FetchQueueItem.ref >= from_.isoformat(),
            FetchQueueItem.ref <= to.isoformat(),
        )
    ).all()
    out: dict[date, str] = {}
    for ref, status in rows:
        try:
            out[date.fromisoformat(ref)] = DAY_STATE[FetchStatus(_value(status))]
        except ValueError:
            continue
    return out


def masters_stale(session: Session, now: datetime | None = None) -> bool:
    last = session.scalar(select(func.max(MasterSyncRun.fetched_at)))
    return last is None or last < _now(now) - MASTERS_MAX_AGE


def preview(
    session: Session,
    cfg: Settings,
    from_: date,
    to: date,
    today: date | None = None,
    now: datetime | None = None,
) -> Preview:
    """Decision 9: the days of the range by state, the calls the new days need (measured rates; None without
    history) and whether the masters are stale. Reads only."""
    check_range(from_, to, today)
    states = _day_states(session, from_, to)
    days = _days(from_, to)
    counts = {k: 0 for k in ("held_with_lists", "held_no_list", "waiting", "failed")}
    for st in states.values():
        counts[st] += 1
    not_queued = len(days) - len(states)
    basis = measure(session, cfg, now)
    per_day = day_tree_calls(basis)
    new_days = not_queued + counts["failed"]
    return Preview(
        days=len(days),
        not_queued=not_queued,
        calls_estimate=round(new_days * per_day, 1) if per_day is not None else None,
        masters_stale=masters_stale(session, now),
        **counts,
    )


def start(
    session: Session,
    actor: Actor,
    user: User | Member | None,
    from_: date,
    to: date,
    held: str | None,
    today: date | None = None,
    now: datetime | None = None,
) -> StartResult:
    """Decision 9. `held` is `skip`, `refetch` or None; None with held days in the range raises `AlreadyHeld`
    before anything is written."""
    member = _member(session, user)
    check_range(from_, to, today)
    if held not in (None, "skip", "refetch"):
        raise LoadInputError("bad_input", "held is skip or refetch")
    states = _day_states(session, from_, to)
    with_lists = sum(1 for s in states.values() if s == "held_with_lists")
    no_list = sum(1 for s in states.values() if s == "held_no_list")
    if (with_lists or no_list) and held is None:
        raise AlreadyHeld(
            "some days of the range are already in the database; choose to skip or to fetch them again",
            held_with_lists=with_lists,
            held_no_list=no_list,
        )
    settings = current_settings(session)
    days = _days(from_, to)
    result = StartResult(days=len(days))
    for d in days:
        state = states.get(d)
        pr = load_priority(settings, FetchKind.CAUSELIST_DAY, d)
        if state in ("held_with_lists", "held_no_list"):
            if held == "skip":
                result.held_skipped += 1
                continue
            queue.enqueue(
                session,
                FetchKind.CAUSELIST_DAY,
                d.isoformat(),
                pr,
                requeue=True,
                lane=FetchLane.LOAD,
                list_date=d,
            )
            result.held_requeued += 1
            continue
        queue.enqueue(session, FetchKind.CAUSELIST_DAY, d.isoformat(), pr, lane=FetchLane.LOAD, list_date=d)
        if state is None:
            result.queued += 1
        elif state == "failed":
            result.revived += 1
    if masters_stale(session, now):
        queue.enqueue(
            session, FetchKind.MASTERS, "all", queue.PRIORITY["masters"], requeue=True, lane=FetchLane.REQUEST
        )
        result.masters_queued = True
    write_audit(
        session,
        access.actor_as(actor, member),
        "data_load.started",
        "fetch_queue",
        None,
        after={"from": from_, "to": to, "held": held, **result.as_dict()},
    )
    return result


# ------------------------------------------------------------------------------------------------ the estimate


@dataclass
class Basis:
    """The measured figures behind the estimate (decision 8); a rate is None when nothing was finished."""

    window_days: int
    calls_per_item: dict[str, float | None]
    finished: dict[str, int]
    calls: dict[str, int]
    dossiers_per_day: float | None
    pdfs_per_dossier: float | None
    calls_per_hour: float
    pending: dict[str, int]
    history_hours: float
    calls_last_hour: int

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class Estimate:
    finish_at: datetime | None
    hours: float | None
    calls_needed: float | None
    reason: str | None
    basis: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "finish_at": to_ist(self.finish_at),
            "hours": self.hours,
            "calls_needed": self.calls_needed,
            "reason": self.reason,
            "basis": self.basis,
        }


def measure(session: Session, cfg: Settings, now: datetime | None = None) -> Basis:
    """Decision 8's rates over the window (`DATA_LOAD_ESTIMATE_WINDOW_DAYS`), from the load lane only."""
    now = _now(now)
    window = cfg.data_load_estimate_window_days
    since = now - timedelta(days=window)
    load = NapixCallLog.lane == FetchLane.LOAD
    calls: dict[str, int] = {}
    for kind, apis in FAMILY.items():
        calls[kind.value] = int(
            session.scalar(
                select(func.count()).where(load, NapixCallLog.called_at >= since, NapixCallLog.api.in_(apis))
            )
            or 0
        )
    q = FetchQueueItem
    finished_rows = dict(
        session.execute(
            select(q.kind, func.count())
            .where(
                q.lane == FetchLane.LOAD,
                q.status.in_([FetchStatus.DONE, FetchStatus.SKIPPED]),
                q.finished_at >= since,
            )
            .group_by(q.kind)
        ).all()
    )
    finished = {k.value: int(finished_rows.get(k, 0) or 0) for k in LOAD_KINDS}
    spawned = dict(
        session.execute(
            select(q.kind, func.count())
            .where(
                q.lane == FetchLane.LOAD,
                q.created_at >= since,
                q.kind.in_([FetchKind.DOSSIER, FetchKind.ORDER_PDF]),
            )
            .group_by(q.kind)
        ).all()
    )
    pending_rows = dict(
        session.execute(
            select(q.kind, func.count())
            .where(q.lane == FetchLane.LOAD, q.status == FetchStatus.PENDING)
            .group_by(q.kind)
        ).all()
    )
    pending = {k.value: int(pending_rows.get(k, 0) or 0) for k in LOAD_KINDS}

    def rate(num: float, den: int) -> float | None:
        return round(num / den, 3) if den else None

    first_call = session.scalar(select(func.min(NapixCallLog.called_at)).where(load))
    calls_24h = int(
        session.scalar(select(func.count()).where(load, NapixCallLog.called_at >= now - timedelta(hours=24)))
        or 0
    )
    calls_1h = int(
        session.scalar(select(func.count()).where(load, NapixCallLog.called_at >= now - timedelta(hours=1)))
        or 0
    )
    return Basis(
        window_days=window,
        calls_per_item={k: rate(calls[k], finished[k]) for k in finished},
        finished=finished,
        calls=calls,
        dossiers_per_day=rate(
            int(spawned.get(FetchKind.DOSSIER, 0) or 0), finished[FetchKind.CAUSELIST_DAY.value]
        ),
        pdfs_per_dossier=rate(
            int(spawned.get(FetchKind.ORDER_PDF, 0) or 0), finished[FetchKind.DOSSIER.value]
        ),
        calls_per_hour=round(calls_24h / 24, 3),
        pending=pending,
        history_hours=round((now - first_call).total_seconds() / 3600, 2) if first_call else 0.0,
        calls_last_hour=calls_1h,
    )


def day_tree_calls(b: Basis) -> float | None:
    """Calls one new cause-list day needs with everything it spawns: the day, its dossiers and their order PDFs."""
    cpd = b.calls_per_item.get(FetchKind.CAUSELIST_DAY.value)
    cdo = b.calls_per_item.get(FetchKind.DOSSIER.value)
    cpp = b.calls_per_item.get(FetchKind.ORDER_PDF.value)
    if None in (cpd, cdo, b.dossiers_per_day):
        return None
    ppd = b.pdfs_per_dossier or 0.0
    return cpd + b.dossiers_per_day * (cdo + ppd * (cpp or 0.0))


def compute_estimate(b: Basis, *, paused: bool, now: datetime) -> Estimate:
    """Calls needed = Σ(pending × calls per item) + days left × (dossiers per day × (calls per dossier + PDFs per
    dossier × calls per PDF)) + dossiers left × PDFs per dossier × calls per PDF; finish = now + calls needed ÷ load
    calls per hour. No estimate while paused, with under 24 h of load history, or with work pending and no load call
    in the last hour."""
    basis = b.as_dict()
    if paused:
        return Estimate(None, None, None, "paused", basis)
    pending_total = sum(b.pending.values())
    if pending_total == 0:
        return Estimate(now, 0.0, 0.0, None, basis)
    if b.history_hours < HISTORY_MIN.total_seconds() / 3600:
        return Estimate(None, None, None, "not_enough_history", basis)
    if b.calls_last_hour == 0 or b.calls_per_hour <= 0:
        return Estimate(None, None, None, "no_recent_calls", basis)
    days_left = b.pending[FetchKind.CAUSELIST_DAY.value]
    dossiers_left = b.pending[FetchKind.DOSSIER.value]
    needed = 0.0
    for kind, n in b.pending.items():
        if not n:
            continue
        cpi = b.calls_per_item.get(kind)
        if cpi is None:
            return Estimate(None, None, None, "not_enough_history", basis)
        needed += n * cpi
    cdo = b.calls_per_item.get(FetchKind.DOSSIER.value)
    cpp = b.calls_per_item.get(FetchKind.ORDER_PDF.value) or 0.0
    ppd = b.pdfs_per_dossier or 0.0
    if days_left:
        if b.dossiers_per_day is None or cdo is None:
            return Estimate(None, None, None, "not_enough_history", basis)
        needed += days_left * (b.dossiers_per_day * (cdo + ppd * cpp))
    needed += dossiers_left * ppd * cpp
    hours = needed / b.calls_per_hour
    return Estimate(now + timedelta(hours=hours), round(hours, 2), round(needed, 1), None, basis)


def estimate(
    session: Session, settings: LoadSettings, cfg: Settings, now: datetime | None = None
) -> Estimate:
    now = _now(now)
    return compute_estimate(measure(session, cfg, now), paused=settings.paused, now=now)


# ------------------------------------------------------------------------------------------------ progress


def _day_totals(session: Session, from_: date, to: date) -> dict[str, int]:
    states = _day_states(session, from_, to)
    calendar_days = (to - from_).days + 1
    out = {
        "calendar": calendar_days,
        "with_lists": sum(1 for s in states.values() if s == "held_with_lists"),
        "no_list": sum(1 for s in states.values() if s == "held_no_list"),
        "waiting": sum(1 for s in states.values() if s == "waiting"),
        "failed": sum(1 for s in states.values() if s == "failed"),
    }
    out["not_queued"] = calendar_days - len(states)
    return out


def _case_totals(session: Session, from_: date, to: date) -> dict[str, int]:
    listed, with_details, provisional = session.execute(
        text(
            """
            SELECT count(*), count(*) FILTER (WHERE c.last_full_refresh_at IS NOT NULL),
                   count(*) FILTER (WHERE c.is_provisional)
            FROM cases c
            WHERE c.merged_into_case_id IS NULL AND c.id IN (
                SELECT e.case_id FROM causelist_entries e JOIN causelists cl ON cl.id = e.causelist_id
                WHERE cl.list_date BETWEEN :f AND :t AND e.case_id IS NOT NULL)
            """
        ),
        {"f": from_, "t": to},
    ).one()
    return {"listed": int(listed), "with_details": int(with_details), "provisional": int(provisional)}


def _order_totals(session: Session, from_: date, to: date) -> dict[str, int]:
    referenced, stored, not_available, waiting = session.execute(
        text(
            """
            SELECT count(*), count(*) FILTER (WHERE document_id IS NOT NULL),
                   count(*) FILTER (WHERE download_status = 'not_available' AND document_id IS NULL),
                   count(*) FILTER (WHERE download_status = 'pending' AND document_id IS NULL)
            FROM orders WHERE order_date BETWEEN :f AND :t
            """
        ),
        {"f": from_, "t": to},
    ).one()
    return {
        "referenced": int(referenced),
        "stored": int(stored),
        "not_available": int(not_available),
        "waiting": int(waiting),
    }


def work_left(session: Session, now: datetime | None = None) -> list[dict[str, Any]]:
    now = _now(now)
    q = FetchQueueItem
    pending = q.status == FetchStatus.PENDING
    runnable = pending & or_(q.not_before.is_(None), q.not_before <= now)
    rows = {
        _value(kind): r
        for kind, *r in session.execute(
            select(
                q.kind,
                func.count().filter(pending),
                func.count().filter(runnable),
                func.count().filter(q.status == FetchStatus.RUNNING),
                func.count().filter(q.status == FetchStatus.FAILED),
            )
            .where(q.lane == FetchLane.LOAD)
            .group_by(q.kind)
        ).all()
    }
    out = []
    for kind in LOAD_KINDS:
        p, r, run, failed = rows.get(kind.value, (0, 0, 0, 0))
        out.append(
            {
                "kind": kind.value,
                "pending": int(p),
                "runnable": int(r),
                "waiting": int(p) - int(r),
                "running": int(run),
                "failed": int(failed),
            }
        )
    return out


def failures(session: Session) -> dict[str, Any]:
    q = FetchQueueItem
    by_kind = [
        {"kind": _value(k), "failed": int(n)}
        for k, n in session.execute(
            select(q.kind, func.count())
            .where(q.lane == FetchLane.LOAD, q.status == FetchStatus.FAILED)
            .group_by(q.kind)
            .order_by(q.kind)
        ).all()
    ]
    latest = [
        {
            "id": r.id,
            "kind": _value(r.kind),
            "ref": r.ref,
            "attempts": r.attempts,
            "last_error": r.last_error,
            "finished_at": to_ist(r.finished_at),
        }
        for r in session.scalars(
            select(q)
            .where(q.lane == FetchLane.LOAD, q.status == FetchStatus.FAILED)
            .order_by(q.finished_at.desc().nulls_last(), q.id.desc())
            .limit(LATEST_FAILURES)
        ).all()
    ]
    return {"by_kind": by_kind, "latest": latest}


def allowance(session: Session, cfg: Settings, now: datetime | None = None) -> dict[str, Any]:
    """The current clock hour: calls by lane (NULL = outside the queue: searches and the connectivity check), the
    latest remaining count and the three thresholds."""
    now = _now(now)
    start_ = _hour_start(now)
    used = {"load": 0, "daily": 0, "request": 0, "outside_queue": 0}
    for lane, n in session.execute(
        select(NapixCallLog.lane, func.count())
        .where(NapixCallLog.called_at >= start_)
        .group_by(NapixCallLog.lane)
    ).all():
        used[_value(lane) if lane is not None else "outside_queue"] += int(n)
    remaining = session.scalar(
        select(NapixCallLog.rate_limit_remaining)
        .where(NapixCallLog.called_at >= start_, NapixCallLog.rate_limit_remaining.isnot(None))
        .order_by(NapixCallLog.called_at.desc())
        .limit(1)
    )
    return {
        "hour_started_at": to_ist(start_),
        "used": used,
        "remaining": remaining,
        "rate_reserve": cfg.napix_rate_reserve,
        "live_reserve": cfg.napix_live_reserve,
        "search_floor": cfg.napix_search_floor,
        "seconds_to_next_hour": court_search.seconds_to_next_hour(now),
    }


def progress(session: Session, cfg: Settings, now: datetime | None = None) -> dict[str, Any]:
    """Decision 7: the whole progress block in one snapshot."""
    now = _now(now)
    with_timeout(session, cfg.report_statement_timeout_seconds)
    settings = current_settings(session)
    period = load_period(session)
    totals = None
    if period is not None:
        totals = {
            "days": _day_totals(session, *period),
            "cases": _case_totals(session, *period),
            "orders": _order_totals(session, *period),
        }
    return {
        "as_of": to_ist(now),
        "napix_enabled": bool(cfg.napix_configured),
        "settings": settings_dict(settings),
        "period": {"from": period[0], "to": period[1]} if period else None,
        "totals": totals,
        "work_left": work_left(session, now),
        "failures": failures(session),
        "allowance": allowance(session, cfg, now),
        "estimate": estimate(session, settings, cfg, now).as_dict(),
    }


# ------------------------------------------------------------------------------------------------ coverage


def _month(value: str) -> date:
    try:
        y, m = value.split("-", 1)
        return date(int(y), int(m), 1)
    except (ValueError, AttributeError) as exc:
        raise LoadInputError("bad_period", f"not a month (YYYY-MM): {value!r}") from exc


def _month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _next_month(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def coverage(
    session: Session, cfg: Settings, from_month: str | None = None, to_month: str | None = None
) -> list[dict[str, Any]]:
    """Decision 6: month by month over the given months (default the load period), at most 36 per call, under the
    report statement timeout (a timeout raises `SearchTimeout`)."""
    period = load_period(session)
    if period is None and (from_month is None or to_month is None):
        if from_month is None and to_month is None:
            return []
        raise LoadInputError("bad_period", "give both months: there is no load period yet")
    first = _month(from_month) if from_month else date(period[0].year, period[0].month, 1)
    last = _month(to_month) if to_month else date(period[1].year, period[1].month, 1)
    if first > last:
        raise LoadInputError("bad_period", "from must not be after to")
    months = []
    m = first
    while m <= last:
        months.append(m)
        m = _next_month(m)
    if len(months) > MAX_COVERAGE_MONTHS:
        raise LoadInputError("bad_period", f"at most {MAX_COVERAGE_MONTHS} months per call")
    with_timeout(session, cfg.report_statement_timeout_seconds)
    try:
        return [_month_figures(session, m) for m in months]
    except OperationalError as exc:
        if getattr(getattr(exc, "orig", None), "sqlstate", None) == QUERY_CANCELED:
            raise SearchTimeout("the coverage took too long; ask for fewer months") from exc
        raise


def _month_figures(session: Session, m: date) -> dict[str, Any]:
    end = _month_end(m)
    days = _day_totals(session, m, end)
    lists, entries, parse_failed = session.execute(
        text(
            """
            SELECT count(DISTINCT cl.id) FILTER (WHERE cl.document_id IS NOT NULL),
                   count(e.id),
                   count(DISTINCT cl.id) FILTER (WHERE cl.parse_status = 'failed')
            FROM causelists cl LEFT JOIN causelist_entries e ON e.causelist_id = cl.id
            WHERE cl.list_date BETWEEN :f AND :t
            """
        ),
        {"f": m, "t": end},
    ).one()
    cases = _case_totals(session, m, end)
    orders = _order_totals(session, m, end)
    q = FetchQueueItem
    left = dict.fromkeys((k.value for k in LOAD_KINDS), 0)
    failed = dict.fromkeys((k.value for k in LOAD_KINDS), 0)
    for kind, status, n in session.execute(
        select(q.kind, q.status, func.count())
        .where(
            q.lane == FetchLane.LOAD,
            q.list_date >= m,
            q.list_date <= end,
            q.status.in_([FetchStatus.PENDING, FetchStatus.RUNNING, FetchStatus.FAILED]),
        )
        .group_by(q.kind, q.status)
    ).all():
        k = _value(kind)
        if k not in left:
            continue
        if FetchStatus(_value(status)) == FetchStatus.FAILED:
            failed[k] += int(n)
        else:
            left[k] += int(n)
    covered = days["with_lists"] + days["no_list"]
    return {
        "month": f"{m.year:04d}-{m.month:02d}",
        "days": days,
        "lists": int(lists),
        "entries": int(entries),
        "lists_parse_failed": int(parse_failed),
        "cases": cases,
        "orders": orders,
        "work_left": left,
        "failed": failed,
        "days_covered_pct": round(100.0 * covered / days["calendar"], 1) if days["calendar"] else 0.0,
        "details_pct": round(100.0 * cases["with_details"] / cases["listed"], 1) if cases["listed"] else None,
    }


# ------------------------------------------------------------------------------------------------ single fetch


def _held_cases_by_cnr(session: Session, cnr: str) -> list[Case]:
    case = session.scalar(select(Case).where(Case.cnr == cnr))
    if case is not None and case.last_full_refresh_at is not None and case.merged_into_case_id is None:
        return [case]
    return []


def _same_search(after: dict[str, Any] | None, name: str, reg_year: int, pend: str) -> bool:
    if not after or after.get("kind") != "party":
        return False
    req = after.get("request") or {}
    return (
        normalise_name(str(req.get("name") or "")) == normalise_name(name)
        and str(req.get("reg_year")) == str(reg_year)
        and str(req.get("pend_disp") or "P") == pend
    )


def check_held(session: Session, request: dict[str, Any], *, est_code: str) -> LoadConflict | None:
    """Decision 10: the answer the console gives before any call (None when the court must be asked). Reads only."""
    kind = request.get("kind")
    if kind == "cnr":
        cnr = str(request.get("cnr") or "").strip().upper()
        held = _held_cases_by_cnr(session, cnr)
        if held:
            return AlreadyHeld(f"case {held[0].ref_no} and its details are already in the database", held)
        return None
    if kind == "case_number":
        court = court_search.court_for(session, est_code)
        try:
            ct = court_search._resolve_case_type(session, court, str(request.get("case_type", "")))
        except court_search.CourtSearchError:
            return None  # the court search answers the bad input
        try:
            reg_no, reg_year = int(request.get("reg_no")), int(request.get("reg_year"))
        except (TypeError, ValueError):
            return None
        local = court_search._local_by_number(session, court, ct, reg_no, reg_year)
        if local is not None and local.merged_into_case_id is None:
            return AlreadyHeld(f"case {local.ref_no} and its details are already in the database", [local])
        return None
    if kind == "party":
        name = str(request.get("name") or "").strip()
        reg_year = int(request.get("reg_year") or 0)
        pend = str(request.get("pend_disp") or "P")
        last = None
        for row in session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "case.search_court", AuditLog.after["kind"].astext == "party")
            .order_by(AuditLog.created_at.desc())
            .limit(500)
        ).all():
            if _same_search(row.after, name, reg_year, pend) and not str(
                (row.after or {}).get("outcome", "")
            ).startswith("failed"):
                last = row
                break
        if last is None:
            return None
        pattern = f"%{normalise_name(name)}%"
        local = int(
            session.scalar(
                select(func.count(func.distinct(CaseParty.case_id)))
                .join(Case, Case.id == CaseParty.case_id)
                .where(
                    CaseParty.name_normalised.like(pattern),
                    Case.merged_into_case_id.is_(None),
                    or_(Case.reg_year == reg_year, Case.reg_year.is_(None)),
                )
            )
            or 0
        )
        return SearchedBefore(
            "the court was searched for that party name before",
            last_searched_at=to_ist(last.created_at),
            stored=int((last.after or {}).get("results") or 0),
            local_matches=local,
        )
    return None


async def fetch(
    session: Session,
    actor: Actor,
    user: User,
    request: dict[str, Any],
    *,
    force: bool,
    hc: NapixHighCourt,
    recorder: NapixRecorder,
    settings: Settings,
) -> court_search.CourtSearchResult:
    """Decision 10: without `force`, the check in the database first (`AlreadyHeld` / `SearchedBefore`, nothing
    written, no call); then the court-search guard (shared per-user limit) and the court search, audited with
    `via`, `force` and `warned`."""
    _member(session, user)
    held = check_held(session, request, est_code=hc.est_code)
    if held is not None and not force:
        raise held
    court_search.guard(session, user, settings)
    fields = {k: v for k, v in request.items() if k != "force"}
    return await court_search.search_court(
        session,
        actor,
        user,
        fields,
        hc=hc,
        recorder=recorder,
        settings=settings,
        force=force,
        audit_extra={"via": "data_load", "force": force, "warned": held is not None},
    )


@dataclass
class DetailState:
    ref: str
    case: Case | None
    state: str
    queue: dict[str, Any] | None = None
    merged_into_ref_no: str | None = None


def fetch_details(
    session: Session,
    actor: Actor,
    user: User | Member,
    refs: list[str],
    force: bool,
    cfg: Settings,
) -> list[DetailState]:
    """Decision 11: dossier rows in the request lane at priority 30 for the cases without details; cases with
    details answer `already_held` and are queued only with `force`. One audit row."""
    member = _member(session, user)
    if not refs or len(refs) > DETAILS_MAX:
        raise LoadInputError("bad_input", f"between 1 and {DETAILS_MAX} cases")
    out: list[DetailState] = []
    for ref in dict.fromkeys(r.strip() for r in refs if r and r.strip()):
        try:
            case = resolve_case_ref(session, ref)
        except CaseNotFound:
            out.append(DetailState(ref, None, "not_found"))
            continue
        if case.merged_into_case_id is not None:
            target = session.get(Case, case.merged_into_case_id)
            out.append(DetailState(ref, case, "merged", merged_into_ref_no=target.ref_no if target else None))
            continue
        try:
            dref = dossier_ref(session, case)
        except NoReference:
            dref = None
        if dref is None:
            out.append(DetailState(ref, case, "no_reference"))
            continue
        held = case.last_full_refresh_at is not None
        if held and not force:
            out.append(DetailState(ref, case, "already_held"))
            continue
        queue.enqueue(
            session, FetchKind.DOSSIER, dref, REQUEST_PRIORITY, requeue=held, lane=FetchLane.REQUEST
        )
        row = queue.get_state(session, FetchKind.DOSSIER, dref)
        out.append(
            DetailState(ref, case, "queued", queue=state_of(session, row, FetchKind.DOSSIER, dref, cfg))
        )
    queued = [d for d in out if d.state == "queued"]
    write_audit(
        session,
        access.actor_as(actor, member),
        "data_load.details_requested",
        "fetch_queue",
        None,
        after={
            "count": len(out),
            "queued": len(queued),
            "force": force,
            "refs": [d.case.ref_no if d.case else d.ref for d in out],
        },
    )
    return out


# ------------------------------------------------------------------------------------------------ duplicates


def _brief(case: Case | None) -> dict[str, Any] | None:
    if case is None:
        return None
    return {"id": case.id, "ref_no": case.ref_no, "cnr": case.cnr, "case_no_text": case.case_no_text}


def duplicates(
    session: Session, kind: str, *, limit: int = 50, offset: int = 0
) -> tuple[int, list[dict[str, Any]]]:
    """Decision 16: merged rows, court-duplicate links and pairs needing review; ref, CNR and case number only."""
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    if kind == "merged":
        cond = Case.merged_into_case_id.isnot(None)
        total = int(session.scalar(select(func.count()).select_from(Case).where(cond)) or 0)
        rows = session.scalars(
            select(Case).where(cond).order_by(Case.updated_at.desc(), Case.id).limit(limit).offset(offset)
        ).all()
        return total, [
            {
                "kind": "merged",
                "case": _brief(r),
                "other": _brief(session.get(Case, r.merged_into_case_id)),
                "at": to_ist(r.updated_at),
                "reasons": None,
            }
            for r in rows
        ]
    if kind == "court":
        cond = CaseLink.kind == LinkKind.COURT_DUPLICATE
        total = int(session.scalar(select(func.count()).select_from(CaseLink).where(cond)) or 0)
        rows = session.scalars(
            select(CaseLink)
            .where(cond)
            .order_by(CaseLink.created_at.desc(), CaseLink.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return total, [
            {
                "kind": "court",
                "case": _brief(session.get(Case, r.from_case_id)),
                "other": _brief(session.get(Case, r.to_case_id) if r.to_case_id else None),
                "at": to_ist(r.created_at),
                "reasons": None,
            }
            for r in rows
        ]
    if kind == "review":
        cond = and_(SourceFailure.kind == case_dedupe.FAILURE_KIND, SourceFailure.resolved_at.is_(None))
        total = int(session.scalar(select(func.count()).select_from(SourceFailure).where(cond)) or 0)
        rows = session.scalars(
            select(SourceFailure)
            .where(cond)
            .order_by(SourceFailure.last_seen.desc(), SourceFailure.id)
            .limit(limit)
            .offset(offset)
        ).all()
        items = []
        for r in rows:
            p_id, _, c_id = r.ref.partition("|")
            items.append(
                {
                    "kind": "review",
                    "case": _brief(_case_by_id(session, p_id)),
                    "other": _brief(_case_by_id(session, c_id)),
                    "at": to_ist(r.last_seen),
                    "reasons": r.error,
                }
            )
        return total, items
    raise LoadInputError("bad_input", "kind is merged, court or review")


def _case_by_id(session: Session, value: str) -> Case | None:
    try:
        return session.get(Case, uuid.UUID(value))
    except ValueError:
        return None


def scan(
    session: Session, actor: Actor, user: User | Member | None, *, dry_run: bool = False
) -> case_dedupe.DedupeReport:
    """Decision 16: the sweep from the console or the CLI; audited `data_load.dedupe_scan` with the counts."""
    member = _member(session, user)
    acting = access.actor_as(actor, member)
    report = case_dedupe.sweep(session, dry_run=dry_run, actor=acting)
    write_audit(
        session,
        acting,
        "data_load.dedupe_scan",
        "cases",
        None,
        after={**report.counts(), "dry_run": dry_run},
    )
    return report
