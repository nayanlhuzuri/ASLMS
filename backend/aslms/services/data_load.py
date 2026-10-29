"""The data-load console (design `data-load-console`): the backdated NAPIX load's settings, start, progress,
estimate and coverage; single-case fetches from the court and details of found cases, each with a warning before
any call when the data is already held; the duplicate lists and the on-demand scan.

- **Settings** (decision 18): `data_load_settings` is a versioned master. `pause`, `resume` and `set_order` insert a
  new version and close the previous one; each writes one audit row (`data_load.paused`, `data_load.resumed`,
  `data_load.order_changed`). Pausing while paused or resuming while running answers `no_change`. `set_order`
  rewrites the priority of every pending load cause-list day and dossier in one statement (decision 3).
- **PDFs after details** (owner, 24 Oct 2026): `pdfs_after_details` moves the order PDFs queued before the change
  (daily, load and discovery rows below 60 in any status but running) to 60 for a pending case, 80 otherwise, in
  batches and repeated passes under a `job_runs` row; never a request-lane row; audited
  `data_load.pdfs_after_details`; a dry run by default.
- **Start** (decision 9): `preview` writes nothing and makes no call. `start` queues each day of the range in the
  `load` lane with its `list_date` and the policy priority; days already held (done with lists, or skipped: the
  court published none) need an explicit `held` choice (`skip` or `refetch`), otherwise `AlreadyHeld` and nothing is
  written. Failed days are revived; waiting days keep their row and take the load priority when better. The masters
  are queued when older than 24 h. One audit row `data_load.started`.
- **Progress and estimate** (decisions 6-8): read only, under the report statement timeout. The estimate uses
  measured rates only and says why when it gives none (`paused`, `not_enough_history`, `no_recent_calls`).
- **Fetch** (decisions 10-11): a check in the database first (`check_held`), then the court search with its guard;
  audited as `case.search_court` with `via: data_load`, `force` and `warned`. Details of found cases are queued in
  the `request` lane carrying the person who asked (`requested_by`, design `napix-window`); one audit row
  `data_load.details_requested`.
- **Allowance** (design `napix-window`, decision 6): the detected quota window, not the clock hour.
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
from sqlalchemy.orm import Session, sessionmaker

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
    JobRun,
    JobStatus,
    LoadOrder,
    NapixCallLog,
    SourceFailure,
)
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.integration.napix.hc import API, NapixHighCourt
from aslms.services import access, case_dedupe, court_search, data_health, napix_window, queue
from aslms.services.access import Member
from aslms.services.audit import Actor, write_audit
from aslms.services.audit_search import to_ist
from aslms.services.cases import CaseNotFound, normalise_name, resolve_case_ref
from aslms.services.load_policy import (
    DEFAULTS,
    DISPOSED_ORDER_PDF,
    FORWARD,
    LIVE_ORDER_PDF,
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
    """Every pending load cause-list day and dossier takes the policy priority (decision 3), in one statement.
    Order PDFs do not depend on the preset (60 / 80 after every detail kind, owner 24 Oct 2026) and are left as they
    are; `pdfs_after_details` moves the ones queued before that change."""
    k = PRESET_ORDER[LoadOrder(settings.load_order)]
    params: dict[str, Any] = {
        "k1": k[0].value,
        "f1": FORWARD[0],
        "f2": FORWARD[1],
        "o1": OTHERWISE[0],
        "o2": OTHERWISE[1],
        "ff": settings.first_from,
        "ft": settings.first_to,
    }
    forward = "CASE kind WHEN CAST(:k1 AS fetch_kind) THEN :f1 ELSE :f2 END"
    otherwise = "CASE kind WHEN CAST(:k1 AS fetch_kind) THEN :o1 ELSE :o2 END"
    sql = f"""
        UPDATE fetch_queue SET priority = CASE
            WHEN CAST(:ff AS date) IS NOT NULL AND list_date BETWEEN CAST(:ff AS date) AND CAST(:ft AS date)
            THEN {forward} ELSE {otherwise} END
        WHERE lane = 'load' AND status = 'pending'
          AND kind IN ('causelist_day', 'dossier')
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


# ------------------------------------------------------------------------------------------------ PDFs after details

PDFS_AFTER_DETAILS_JOB = "pdfs-after-details"
PDFS_AFTER_DETAILS_BATCH = 5000
PDFS_AFTER_DETAILS_PASSES = 5
_PDF_LANES = "q.kind = 'order_pdf' AND q.lane IN ('daily', 'load', 'discovery')"
# the order PDFs queued before the owner's change of 24 Oct 2026 (case details before order PDFs): daily, load and
# discovery rows still ahead of the detail kinds, in every status but `running` (a pending row runs too early; a
# failed, skipped or done row would be revived at its old priority by `queue.enqueue`'s LEAST or by
# `queue-retry-failed`); a request-lane row is never touched
_PDF_ROWS = f"""
    FROM fetch_queue q LEFT JOIN cases c ON c.cnr = split_part(q.ref, '|', 1)
    WHERE {_PDF_LANES} AND q.status <> 'running' AND q.priority < {LIVE_ORDER_PDF}
"""
# the enqueue path's rule (`QueueOrigin.order_pdf_priority`): only a pending case's PDF takes 60; a disposed or
# unknown case, or a row whose case is not held, takes 80
_PDF_TARGET = f"CASE WHEN c.status = 'pending' THEN {LIVE_ORDER_PDF} ELSE {DISPOSED_ORDER_PDF} END"


def _pdf_counts(by: dict[tuple[str, str, int], int]) -> dict[str, Any]:
    by_lane: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for (lane, status, _), n in by.items():
        by_lane[lane] = by_lane.get(lane, 0) + n
        by_status[status] = by_status.get(status, 0) + n
    return {
        "rows": sum(by.values()),
        f"to_{LIVE_ORDER_PDF}": sum(n for (_, _, p), n in by.items() if p == LIVE_ORDER_PDF),
        f"to_{DISPOSED_ORDER_PDF}": sum(n for (_, _, p), n in by.items() if p == DISPOSED_ORDER_PDF),
        "by_lane": dict(sorted(by_lane.items())),
        "by_status": dict(sorted(by_status.items())),
    }


def _pdf_running(s: Session) -> int:
    """Rows of the three lanes below 60 that are running now: not moved; a re-run catches them once they finish."""
    return int(
        s.scalar(
            text(
                f"SELECT count(*) FROM fetch_queue q WHERE {_PDF_LANES} AND q.status = 'running' "
                f"AND q.priority < {LIVE_ORDER_PDF}"
            )
        )
        or 0
    )


def _pdf_pass(session_factory: sessionmaker[Session], batch: int) -> tuple[list[tuple[str, str, int]], int]:
    """One keyset pass over the rows in id order, `batch` at a time, one commit per batch. `SKIP LOCKED`: a row a
    runner holds is left for the next pass, so the command never waits on the worker."""
    moved: list[tuple[str, str, int]] = []
    batches = 0
    last: uuid.UUID | None = None
    while True:
        with session_factory() as s:
            rows = s.execute(
                text(
                    f"""
                    WITH picked AS (
                        SELECT q.id, {_PDF_TARGET} AS target
                        {_PDF_ROWS}
                          AND (CAST(:last AS uuid) IS NULL OR q.id > CAST(:last AS uuid))
                        ORDER BY q.id
                        LIMIT :batch
                        FOR UPDATE OF q SKIP LOCKED
                    )
                    UPDATE fetch_queue f SET priority = picked.target
                    FROM picked WHERE f.id = picked.id
                    RETURNING f.id, f.lane, f.status, f.priority
                    """
                ),
                {"last": last, "batch": batch},
            ).all()
            s.commit()
        if not rows:
            return moved, batches
        batches += 1
        moved.extend((str(lane), str(status), int(priority)) for _, lane, status, priority in rows)
        last = max(r[0] for r in rows)


def pdfs_after_details(
    session_factory: sessionmaker[Session],
    actor: Actor,
    user: User | Member | None,
    *,
    apply: bool,
    batch: int = PDFS_AFTER_DETAILS_BATCH,
    passes: int = PDFS_AFTER_DETAILS_PASSES,
) -> dict[str, Any]:
    """`aslms data-load pdfs-after-details` (owner, 24 Oct 2026): every `order_pdf` row of the daily, load and
    discovery lanes below 60, in any status but `running` (pending, failed, skipped or done, so no old priority
    survives a later revival), takes its priority under the new policy: 60 for a pending case, 80 otherwise (the
    enqueue path's rule). A request-lane row is never touched (a person's own case keeps 40). A dry run writes
    nothing and returns the counts. With `apply` the rows move in keyset passes of batches of `batch` (one commit
    each, `FOR UPDATE SKIP LOCKED`) under a `job_runs` row `pdfs-after-details`, repeated until a pass moves nothing
    (at most `passes`), so a row that was running or locked and came back below 60 is caught; `left` counts the rows
    still below 60 afterwards (running ones: run it again later). One audit row `data_load.pdfs_after_details`
    records the counts when anything moved. Idempotent: a second run moves nothing. Needs `admin.data_load` (the
    `system` actor before a super admin)."""
    with session_factory() as s:
        member = _member(s, user)
        who = access.actor_as(actor, member)
        found = {
            (str(lane), str(status), int(target)): int(n)
            for lane, status, target, n in s.execute(
                text(
                    f"SELECT q.lane, q.status, {_PDF_TARGET} AS target, count(*) {_PDF_ROWS} GROUP BY 1, 2, 3"
                )
            ).all()
        }
        running = _pdf_running(s)
        request_kept = int(
            s.scalar(
                text(
                    "SELECT count(*) FROM fetch_queue "
                    "WHERE kind = 'order_pdf' AND status <> 'running' AND lane = 'request'"
                )
            )
            or 0
        )
    out: dict[str, Any] = {
        "dry_run": not apply,
        "found": {**_pdf_counts(found), "running": running},
        "request_lane_kept": request_kept,
        "moved": None,
        "job_run_id": None,
    }
    if not apply or not found:
        if apply:
            out["moved"] = {**_pdf_counts({}), "batches": 0, "passes": 0, "left": running}
        return out
    with session_factory() as s:
        run = JobRun(job=PDFS_AFTER_DETAILS_JOB, run_date=today_ist(), counters={})
        s.add(run)
        s.commit()
        run_id = run.id
    moved: dict[tuple[str, str, int], int] = {}
    batches = done_passes = 0
    left: int | None = None
    status, error = JobStatus.FAILED, None
    try:
        while done_passes < max(1, passes):
            rows, n = _pdf_pass(session_factory, batch)
            done_passes += 1
            batches += n
            for key in rows:
                moved[key] = moved.get(key, 0) + 1
            if not rows:
                break
        with session_factory() as s:
            left = int(s.scalar(text(f"SELECT count(*) {_PDF_ROWS}")) or 0) + _pdf_running(s)
        status = JobStatus.SUCCEEDED
    except Exception as exc:
        error = f"{exc.__class__.__name__}: {exc}"[:2000]
        raise
    finally:
        counts = {**_pdf_counts(moved), "batches": batches, "passes": done_passes, "left": left}
        with session_factory() as s:
            run = s.get(JobRun, run_id)
            if run is not None:
                run.finished_at = datetime.now(UTC)
                run.status = status
                run.error = error
                run.counters = counts
            if moved:
                write_audit(
                    s,
                    who,
                    "data_load.pdfs_after_details",
                    "fetch_queue",
                    None,
                    after={**counts, "request_lane_kept": request_kept, "job_run_id": str(run_id)},
                )
            s.commit()
    out["moved"] = counts
    out["job_run_id"] = run_id
    return out


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


# the case's `dossier` queue row, in any lane: by CNR, or `<est_code>|<case number>` for a provisional case
# (`napix_admin.dossier_ref`); `uq_fetch_queue_kind_ref` answers each probe
_DOSSIER_ROW = """
    EXISTS (SELECT 1 FROM fetch_queue q WHERE q.kind = 'dossier' AND q.status IN ({statuses})
            AND (q.ref = c.cnr OR q.ref = (SELECT co.est_code FROM courts co WHERE co.id = c.court_id)
                 || '|' || c.case_no_text))
"""


def _case_totals(session: Session, from_: date, to: date) -> dict[str, int]:
    """The cases listed in [from_, to] (current lists, not merged): with details, provisional, and (design
    `data-collection-redesign`, decision 20) without details, of which `queued` have a pending or running dossier row
    in any lane and `failed` a failed one."""
    queued = _DOSSIER_ROW.format(statuses="'pending', 'running'")
    failed = _DOSSIER_ROW.format(statuses="'failed'")
    listed, with_details, provisional, n_queued, n_failed = session.execute(
        text(
            f"""
            SELECT count(*), count(*) FILTER (WHERE c.last_full_refresh_at IS NOT NULL),
                   count(*) FILTER (WHERE c.is_provisional),
                   count(*) FILTER (WHERE c.last_full_refresh_at IS NULL AND {queued}),
                   count(*) FILTER (WHERE c.last_full_refresh_at IS NULL AND NOT {queued} AND {failed})
            FROM cases c
            WHERE c.merged_into_case_id IS NULL AND c.id IN (
                SELECT e.case_id FROM causelist_entries e JOIN causelists cl ON cl.id = e.causelist_id
                WHERE cl.list_date BETWEEN :f AND :t AND e.case_id IS NOT NULL AND cl.superseded_at IS NULL)
            """
        ),
        {"f": from_, "t": to},
    ).one()
    return {
        "listed": int(listed),
        "with_details": int(with_details),
        "provisional": int(provisional),
        "without_details": int(listed) - int(with_details),
        "queued": int(n_queued),
        "failed": int(n_failed),
    }


def _order_totals(session: Session, from_: date | None, to: date | None) -> dict[str, int]:
    """Orders by `order_date` in [from_, to] (an open end when None): known, stored, not available at the court,
    waiting (pending with no document) and failed (design `data-collection-redesign`, decision 14)."""
    referenced, stored, not_available, waiting, failed = session.execute(
        text(
            """
            SELECT count(*), count(*) FILTER (WHERE document_id IS NOT NULL),
                   count(*) FILTER (WHERE download_status = 'not_available' AND document_id IS NULL),
                   count(*) FILTER (WHERE download_status = 'pending' AND document_id IS NULL),
                   count(*) FILTER (WHERE download_status = 'failed' AND document_id IS NULL)
            FROM orders
            WHERE (CAST(:f AS date) IS NULL OR order_date >= CAST(:f AS date))
              AND (CAST(:t AS date) IS NULL OR order_date <= CAST(:t AS date))
            """
        ),
        {"f": from_, "t": to},
    ).one()
    return {
        "referenced": int(referenced),
        "stored": int(stored),
        "not_available": int(not_available),
        "waiting": int(waiting),
        "failed": int(failed),
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
    """The detected quota window (design `napix-window`, decision 6): its start, the expected next reset and the
    state; calls by lane since the reset was observed (NULL lane = outside the queue: searches, checks and probes);
    the remaining count the guards use and the three thresholds. No user data."""
    now = _now(now)
    window = napix_window.current(session, cfg, now)
    used = napix_window.calls_since(session, window.observed_at, lane_split=True)["by_lane"]
    return {
        "window_started_at": to_ist(window.started_at),
        "next_reset_at": to_ist(window.next_reset_at),
        "seconds_to_next_reset": window.seconds_to_reset(now),
        "window_status": window.status,
        "used": used,
        "remaining": window.remaining,
        "rate_reserve": cfg.napix_rate_reserve,
        "live_reserve": cfg.napix_live_reserve,
        "search_floor": cfg.napix_search_floor,
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


# ------------------------------------------------------------------------------------------------ overview, pulse
# design `data-collection-redesign` (round 1): the Overview tab's honest counts across every lane, the live pulse and
# the estimate in two dates. Reads only, no NAPIX call.

ACTIVE = (FetchStatus.PENDING, FetchStatus.RUNNING)
PULSE_RECENT = timedelta(minutes=5)
LIMIT_LOOKBACK = timedelta(hours=24)
PULSE_RUNNING_MAX = 20
# Still to Fetch's named parts (decision 14); every other kind is `other`
LEFT_PARTS = {
    FetchKind.CAUSELIST_DAY.value: "causelist_days",
    FetchKind.DOSSIER.value: "case_details",
    FetchKind.ORDER_PDF.value: "order_pdfs",
}


def position(session: Session) -> dict[str, Any]:
    """Where the past-months collection is (decision 14): the earliest load-lane cause-list day still pending or
    running, and its month; None when nothing waits."""
    q = FetchQueueItem
    d = session.scalar(
        select(func.min(q.list_date)).where(
            q.lane == FetchLane.LOAD, q.kind == FetchKind.CAUSELIST_DAY, q.status.in_(ACTIVE)
        )
    )
    return {"working_on": d, "working_on_month": f"{d.year:04d}-{d.month:02d}" if d else None}


def collection_state(session: Session, settings: LoadSettings, period: tuple[date, date] | None) -> str:
    """`not_started` (no load period), `paused`, `running` (load-lane work pending or running) or `finished`."""
    if period is None:
        return "not_started"
    if settings.paused:
        return "paused"
    q = FetchQueueItem
    active = session.scalar(
        select(func.count()).select_from(q).where(q.lane == FetchLane.LOAD, q.status.in_(ACTIVE))
    )
    return "running" if active else "finished"


def _all_cases(session: Session) -> dict[str, int]:
    """Every case held, not merged (decision 14: cases found are all cases held)."""
    found, with_details, provisional = session.execute(
        text(
            """
            SELECT count(*), count(*) FILTER (WHERE last_full_refresh_at IS NOT NULL),
                   count(*) FILTER (WHERE is_provisional)
            FROM cases WHERE merged_into_case_id IS NULL
            """
        )
    ).one()
    return {
        "found": int(found),
        "with_details": int(with_details),
        "without_details": int(found) - int(with_details),
        "provisional": int(provisional),
    }


def waiting_work(session: Session) -> list[dict[str, Any]]:
    """The queue in every lane by kind (decision 15): waiting rows (`total`) split by lane, fetching and failed.
    Kinds with no row are left out."""
    q = FetchQueueItem
    out: dict[str, dict[str, Any]] = {}
    for kind, lane, status, n in session.execute(
        select(q.kind, q.lane, q.status, func.count())
        .where(q.status.in_([FetchStatus.PENDING, FetchStatus.RUNNING, FetchStatus.FAILED]))
        .group_by(q.kind, q.lane, q.status)
    ).all():
        k = _value(kind)
        row = out.setdefault(
            k,
            {"kind": k, "total": 0, "by_lane": {ln.value: 0 for ln in FetchLane}, "running": 0, "failed": 0},
        )
        st = FetchStatus(_value(status))
        if st == FetchStatus.PENDING:
            row["total"] += int(n)
            row["by_lane"][_value(lane)] += int(n)
        elif st == FetchStatus.RUNNING:
            row["running"] += int(n)
        else:
            row["failed"] += int(n)
    order = [k.value for k in FetchKind]
    return sorted(out.values(), key=lambda r: order.index(r["kind"]) if r["kind"] in order else len(order))


def still_to_fetch(work: list[dict[str, Any]]) -> dict[str, int]:
    """Still to Fetch (decision 14): pending and running rows in every lane, the request lane included."""
    left = {"causelist_days": 0, "case_details": 0, "order_pdfs": 0, "other": 0}
    for row in work:
        left[LEFT_PARTS.get(row["kind"], "other")] += row["total"] + row["running"]
    left["total"] = sum(left.values())
    return left


def problem_counts(
    session: Session, work: list[dict[str, Any]], cases: dict[str, int], orders: dict[str, int]
) -> dict[str, int]:
    """The Problems line (decision 16)."""
    review = session.scalar(
        select(func.count())
        .select_from(SourceFailure)
        .where(SourceFailure.kind == case_dedupe.FAILURE_KIND, SourceFailure.resolved_at.is_(None))
    )
    return {
        "failed": sum(r["failed"] for r in work),
        "duplicates_review": int(review or 0),
        "cases_without_details": cases["without_details"],
        "orders_not_available": orders["not_available"],
        "orders_failed": orders["failed"],
    }


def hourly_limit(session: Session, now: datetime) -> int | None:
    """The hourly limit as the court reports it: the highest remaining count read in the last 24 hours, plus the
    call that read it. None with no reading."""
    top = session.scalar(
        select(func.max(NapixCallLog.rate_limit_remaining)).where(
            NapixCallLog.called_at >= now - LIMIT_LOOKBACK, NapixCallLog.rate_limit_remaining.isnot(None)
        )
    )
    return int(top) + 1 if top is not None else None


@dataclass
class BasisAll:
    """The measured figures behind the two-date estimate (decision 21), over every queue lane."""

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
    hourly_limit: int | None

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def measure_all(session: Session, cfg: Settings, now: datetime | None = None) -> BasisAll:
    """Decision 21: decision 8's rates widened to every queue lane (a call with a lane). Calls per item and PDFs per
    case come from every lane; dossiers per cause-list day from the load lane (a daily or weekly dossier is not spawned
    by a day), falling back to every lane; the pace is the queue calls of the last 24 hours. `pending` counts the
    pending and running rows of the three kinds in every lane."""
    now = _now(now)
    window = cfg.data_load_estimate_window_days
    since = now - timedelta(days=window)
    queued = NapixCallLog.lane.isnot(None)
    calls: dict[str, int] = {}
    for kind, apis in FAMILY.items():
        calls[kind.value] = int(
            session.scalar(
                select(func.count()).where(
                    queued, NapixCallLog.called_at >= since, NapixCallLog.api.in_(apis)
                )
            )
            or 0
        )
    q = FetchQueueItem
    done = q.status.in_([FetchStatus.DONE, FetchStatus.SKIPPED])
    finished_rows = dict(
        session.execute(
            select(q.kind, func.count()).where(done, q.finished_at >= since).group_by(q.kind)
        ).all()
    )
    finished = {k.value: int(finished_rows.get(k, 0) or 0) for k in LOAD_KINDS}
    load_days = int(
        session.scalar(
            select(func.count()).where(
                q.lane == FetchLane.LOAD, q.kind == FetchKind.CAUSELIST_DAY, done, q.finished_at >= since
            )
        )
        or 0
    )
    load_dossiers = int(
        session.scalar(
            select(func.count()).where(
                q.lane == FetchLane.LOAD, q.kind == FetchKind.DOSSIER, q.created_at >= since
            )
        )
        or 0
    )
    spawned = dict(
        session.execute(
            select(q.kind, func.count())
            .where(q.created_at >= since, q.kind.in_([FetchKind.DOSSIER, FetchKind.ORDER_PDF]))
            .group_by(q.kind)
        ).all()
    )
    pending_rows = dict(
        session.execute(select(q.kind, func.count()).where(q.status.in_(ACTIVE)).group_by(q.kind)).all()
    )
    pending = {k.value: int(pending_rows.get(k, 0) or 0) for k in LOAD_KINDS}

    def rate(num: float, den: int) -> float | None:
        return round(num / den, 3) if den else None

    first_call = session.scalar(select(func.min(NapixCallLog.called_at)).where(queued))
    calls_24h = int(
        session.scalar(
            select(func.count()).where(queued, NapixCallLog.called_at >= now - timedelta(hours=24))
        )
        or 0
    )
    calls_1h = int(
        session.scalar(select(func.count()).where(queued, NapixCallLog.called_at >= now - timedelta(hours=1)))
        or 0
    )
    per_day = rate(load_dossiers, load_days)
    if per_day is None:
        per_day = rate(int(spawned.get(FetchKind.DOSSIER, 0) or 0), finished[FetchKind.CAUSELIST_DAY.value])
    return BasisAll(
        window_days=window,
        calls_per_item={k: rate(calls[k], finished[k]) for k in finished},
        finished=finished,
        calls=calls,
        dossiers_per_day=per_day,
        pdfs_per_dossier=rate(
            int(spawned.get(FetchKind.ORDER_PDF, 0) or 0), finished[FetchKind.DOSSIER.value]
        ),
        calls_per_hour=round(calls_24h / 24, 3),
        pending=pending,
        history_hours=round((now - first_call).total_seconds() / 3600, 2) if first_call else 0.0,
        calls_last_hour=calls_1h,
        hourly_limit=hourly_limit(session, now),
    )


def _line(needed: float | None, b: BasisAll, now: datetime, reason: str | None) -> dict[str, Any]:
    if reason is not None or needed is None:
        return {
            "finish_at": None,
            "hours": None,
            "calls_needed": None,
            "reason": reason or "not_enough_history",
        }
    hours = needed / b.calls_per_hour if needed else 0.0
    return {
        "finish_at": to_ist(now + timedelta(hours=hours)),
        "hours": round(hours, 2),
        "calls_needed": round(needed, 1),
        "reason": None,
    }


def compute_two(b: BasisAll, *, paused: bool, gateway_on: bool, now: datetime) -> dict[str, Any]:
    """Decision 21: two lines from measured rates only. `details`: the cause-list days and case details waiting in
    every lane, with the dossiers the waiting days will spawn; `all`: those and every order PDF, waiting or still to be
    spawned. The worker takes details before order PDFs (priorities 40-46 before 60 and 80), so the details finish
    first at the shared pace. No date, with the reason: `connection_off`, `not_enough_history` (under 24 hours of
    queue calls, or a kind with work and no measured rate), `no_recent_calls` (work waiting and no queue call in the
    last hour), and `paused` for the details line."""
    days = b.pending[FetchKind.CAUSELIST_DAY.value]
    dossiers = b.pending[FetchKind.DOSSIER.value]
    pdfs = b.pending[FetchKind.ORDER_PDF.value]
    cpd = b.calls_per_item.get(FetchKind.CAUSELIST_DAY.value)
    cdo = b.calls_per_item.get(FetchKind.DOSSIER.value)
    cpp = b.calls_per_item.get(FetchKind.ORDER_PDF.value)
    details_needed: float | None = 0.0
    if days:
        if cpd is None or cdo is None or b.dossiers_per_day is None:
            details_needed = None
        else:
            details_needed = days * cpd + days * b.dossiers_per_day * cdo
    if dossiers and details_needed is not None:
        details_needed = None if cdo is None else details_needed + dossiers * cdo
    all_needed: float | None = details_needed
    if all_needed is not None:
        future_dossiers = dossiers + days * (b.dossiers_per_day or 0.0)
        future_pdfs = pdfs + future_dossiers * (b.pdfs_per_dossier or 0.0)
        if future_pdfs:
            all_needed = None if cpp is None else all_needed + future_pdfs * cpp

    def reason(needed: float | None, *, details: bool) -> str | None:
        if needed == 0:
            return None
        if not gateway_on:
            return "connection_off"
        if details and paused:
            return "paused"
        if b.history_hours < HISTORY_MIN.total_seconds() / 3600:
            return "not_enough_history"
        if b.calls_last_hour == 0 or b.calls_per_hour <= 0:
            return "no_recent_calls"
        if needed is None:
            return "not_enough_history"
        return None

    return {
        "details": _line(details_needed, b, now, reason(details_needed, details=True)),
        "all": _line(all_needed, b, now, reason(all_needed, details=False)),
        "basis": b.as_dict(),
    }


def estimate_all(
    session: Session, settings: LoadSettings, cfg: Settings, now: datetime | None = None
) -> dict[str, Any]:
    now = _now(now)
    return compute_two(
        measure_all(session, cfg, now), paused=settings.paused, gateway_on=bool(cfg.napix_configured), now=now
    )


def overview(session: Session, cfg: Settings, now: datetime | None = None) -> dict[str, Any]:
    """`GET /admin/data-load/overview` (decisions 14-16, 21): what is held, done and left, in one snapshot under the
    report statement timeout. `days` counts the calendar days of the load period up to today (any lane: the daily
    cycle collects the recent ones); `cases` every case held; `orders` every order known, and `in_period` those dated
    inside the period; `left` the work in every lane; `bulk` is the active bulk request (always None until round
    3)."""
    now = _now(now)
    today = today_ist(now)
    with_timeout(session, cfg.report_statement_timeout_seconds)
    settings = current_settings(session)
    period = load_period(session)
    days = None
    in_period = None
    if period is not None:
        end = max(period[1], today)
        t = _day_totals(session, period[0], end)
        days = {**t, "collected": t["with_lists"] + t["no_list"], "to": end}
        in_period = _order_totals(session, period[0], period[1])
    cases = _all_cases(session)
    orders = {**_order_totals(session, None, None), "in_period": in_period}
    work = waiting_work(session)
    return {
        "as_of": to_ist(now),
        "napix_enabled": bool(cfg.napix_configured),
        "settings": settings_dict(settings),
        "collection": collection_state(session, settings, period),
        "period": {"from": period[0], "to": period[1]} if period else None,
        "position": position(session),
        "days": days,
        "cases": cases,
        "orders": orders,
        "left": still_to_fetch(work),
        "waiting_work": work,
        "problems": problem_counts(session, work, cases, orders),
        "estimate": estimate_all(session, settings, cfg, now),
        "bulk": None,
    }


def pulse(session: Session, cfg: Settings, now: datetime | None = None) -> dict[str, Any]:
    """`GET /admin/data-load/pulse` (decisions 17-18), polled every 5 s: the quota window and its calls, the queue by
    kind in every lane, what is fetching now (kind, lane and start, never a reference), calls in the last 5 minutes,
    the last call and the request-lane rows waiting or fetching. A handful of indexed counts."""
    now = _now(now)
    window = napix_window.current(session, cfg, now)
    used = napix_window.calls_since(session, window.observed_at)["calls"]
    q = FetchQueueItem
    queue_rows = [
        {"kind": _value(kind), "pending": int(p), "running": int(r)}
        for kind, p, r in session.execute(
            select(
                q.kind,
                func.count().filter(q.status == FetchStatus.PENDING),
                func.count().filter(q.status == FetchStatus.RUNNING),
            )
            .where(q.status.in_(ACTIVE))
            .group_by(q.kind)
            .order_by(q.kind)
        ).all()
    ]
    running = [
        {"kind": _value(kind), "lane": _value(lane), "started_at": to_ist(started)}
        for kind, lane, started in session.execute(
            select(q.kind, q.lane, q.started_at)
            .where(q.status == FetchStatus.RUNNING)
            .order_by(q.started_at.desc().nulls_last())
            .limit(PULSE_RUNNING_MAX)
        ).all()
    ]
    recent = int(
        session.scalar(select(func.count()).where(NapixCallLog.called_at >= now - PULSE_RECENT)) or 0
    )
    requests = int(
        session.scalar(
            select(func.count()).select_from(q).where(q.lane == FetchLane.REQUEST, q.status.in_(ACTIVE))
        )
        or 0
    )
    return {
        "as_of": to_ist(now),
        "napix_enabled": bool(cfg.napix_configured),
        "window": {
            "status": window.status,
            "remaining": window.remaining,
            "used": used,
            "hourly_limit": hourly_limit(session, now),
            "next_reset_at": to_ist(window.next_reset_at),
            "seconds_to_next_reset": window.seconds_to_reset(now),
        },
        "queue": queue_rows,
        "running": running,
        "calls_last_5_min": recent,
        "last_call_at": to_ist(session.scalar(select(func.max(NapixCallLog.called_at)))),
        "requests_active": requests,
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


def _months_between(first: date, last: date) -> list[date]:
    months = []
    m = first
    while m <= last:
        months.append(m)
        m = _next_month(m)
    return months


def _default_months(period: tuple[date, date], today: date) -> tuple[date, date]:
    """The load period's first month to the later of its last month and this month (design
    `data-collection-redesign`, decision 19: the months then add up with `earlier_orders`), at most 36 months: the
    oldest are left to `earlier_orders`."""
    last = max(date(period[1].year, period[1].month, 1), date(today.year, today.month, 1))
    first = date(period[0].year, period[0].month, 1)
    floor = last
    for _ in range(MAX_COVERAGE_MONTHS - 1):
        floor = date(floor.year - (floor.month == 1), (floor.month - 2) % 12 + 1, 1)
    return max(first, floor), last


def _coverage_months(
    session: Session, from_month: str | None, to_month: str | None, today: date
) -> list[date] | None:
    period = load_period(session)
    if period is None and (from_month is None or to_month is None):
        if from_month is None and to_month is None:
            return None
        raise LoadInputError("bad_period", "give both months: there is no load period yet")
    if period is not None:
        d_first, d_last = _default_months(period, today)
    first = _month(from_month) if from_month else d_first
    last = _month(to_month) if to_month else d_last
    if first > last:
        raise LoadInputError("bad_period", "from must not be after to")
    months = _months_between(first, last)
    if len(months) > MAX_COVERAGE_MONTHS:
        raise LoadInputError("bad_period", f"at most {MAX_COVERAGE_MONTHS} months per call")
    return months


def _timed(fn, message: str = "the coverage took too long; ask for fewer months"):
    try:
        return fn()
    except OperationalError as exc:
        if getattr(getattr(exc, "orig", None), "sqlstate", None) == QUERY_CANCELED:
            raise SearchTimeout(message) from exc
        raise


def coverage(
    session: Session,
    cfg: Settings,
    from_month: str | None = None,
    to_month: str | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Decision 6: month by month over the given months (default: the load period's first month to this month,
    design `data-collection-redesign`, decision 19), at most 36 per call, under the report statement timeout (a
    timeout raises `SearchTimeout`)."""
    today = today or today_ist()
    months = _coverage_months(session, from_month, to_month, today)
    if months is None:
        return []
    with_timeout(session, cfg.report_statement_timeout_seconds)
    pos = position(session)
    period = load_period(session)
    return _timed(lambda: [_month_figures(session, m, today, period, pos) for m in months])


def coverage_view(
    session: Session,
    cfg: Settings,
    from_month: str | None = None,
    to_month: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """`GET /admin/data-load/coverage`: the months, the orders dated before the first month shown
    (`earlier_orders`, so the rows add up to every order known) and where the past-months collection is
    (`position`), design `data-collection-redesign`, decisions 19-20."""
    today = today or today_ist()
    months = coverage(session, cfg, from_month, to_month, today)
    earlier = None
    if months:
        first = _month(months[0]["month"])
        earlier = _timed(lambda: _order_totals(session, None, first - timedelta(days=1)))
    return {"months": months, "earlier_orders": earlier, "position": position(session)}


def _month_state(
    m: date,
    days: dict[str, int],
    period: tuple[date, date] | None,
    pos: dict[str, Any],
) -> str:
    """Decision 19's badge: `done` (every day up to today collected), `in_progress`, `not_reached` (inside the load
    period, after the month it works on), `failed_days` (some days failed, none waiting) or `not_in_load`."""
    upto = days["calendar"]
    collected = days["with_lists"] + days["no_list"]
    if upto > 0 and collected >= upto:
        return "done"
    if days["failed"] and not days["waiting"]:
        return "failed_days"
    working = pos.get("working_on")
    in_period = period is not None and m <= period[1] and _month_end(m) >= period[0]
    if in_period and working is not None:
        here = date(working.year, working.month, 1)
        if m > here:
            return "not_reached"
        if m == here or days["waiting"]:
            return "in_progress"
    if days["waiting"]:
        return "in_progress"
    return "not_in_load"


def _month_figures(
    session: Session,
    m: date,
    today: date | None = None,
    period: tuple[date, date] | None = None,
    pos: dict[str, Any] | None = None,
) -> dict[str, Any]:
    today = today or today_ist()
    end = _month_end(m)
    if m > today:
        days = {"calendar": 0, "with_lists": 0, "no_list": 0, "waiting": 0, "failed": 0, "not_queued": 0}
    else:
        days = _day_totals(session, m, min(end, today))  # days counted up to today only (decision 20)
    lists, entries, parse_failed = session.execute(
        text(
            """
            SELECT count(DISTINCT cl.id) FILTER (WHERE cl.document_id IS NOT NULL),
                   count(e.id),
                   count(DISTINCT cl.id) FILTER (WHERE cl.parse_status = 'failed')
            FROM causelists cl LEFT JOIN causelist_entries e ON e.causelist_id = cl.id
            WHERE cl.list_date BETWEEN :f AND :t AND cl.superseded_at IS NULL
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
        # kept for older clients: the load lane only, by listing date
        "work_left": left,
        "failed": failed,
        "days_covered_pct": round(100.0 * covered / days["calendar"], 1) if days["calendar"] else 0.0,
        "details_pct": round(100.0 * cases["with_details"] / cases["listed"], 1) if cases["listed"] else None,
        # design data-collection-redesign, decision 20: each column's own date, every lane
        "left": {
            "days": max(0, days["calendar"] - covered),
            "cases": cases["queued"],
            "order_pdfs": orders["waiting"],
        },
        "state": _month_state(m, days, period, pos or {}),
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
            session,
            FetchKind.DOSSIER,
            dref,
            REQUEST_PRIORITY,
            requeue=held,
            lane=FetchLane.REQUEST,
            requested_by=napix_window.user_id_of(user),
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


# ------------------------------------------------------------------------------------------------ data gaps
# design `data-collection-redesign`, round 2 (decision 45): the cases held without details, each with the state of its
# `dossier` row in any lane; the orders whose PDF is not available at the court or failed; and the documents without
# searchable text. Reads only, under the report statement timeout; references, CNRs and case numbers only (as
# Duplicates and the queue already show the same readers), never parties or notes.

GAP_KINDS = ("cases", "orders")
GAP_MAX = 200
GAP_CASE_STATES = ("being_fetched", "not_found", "failed", "not_queued")

# the case's dossier row by CNR or `<est_code>|<case number>` (`napix_admin.dossier_ref`), a waiting one first
_GAP_CASES = """
    SELECT c.id, c.ref_no, c.cnr, c.case_no_text, c.created_at,
           CASE WHEN q.status IN ('pending', 'running') THEN 'being_fetched'
                WHEN q.status = 'skipped' THEN 'not_found'
                WHEN q.status = 'failed' THEN 'failed'
                ELSE 'not_queued' END AS state,
           q.last_error, q.attempts
    FROM cases c
    LEFT JOIN LATERAL (
        SELECT q.status, q.last_error, q.attempts FROM fetch_queue q
        WHERE q.kind = 'dossier'
          AND (q.ref = c.cnr
               OR q.ref = (SELECT co.est_code FROM courts co WHERE co.id = c.court_id) || '|' || c.case_no_text)
        ORDER BY (q.status IN ('pending', 'running')) DESC, q.updated_at DESC
        LIMIT 1) q ON true
    WHERE c.merged_into_case_id IS NULL AND c.last_full_refresh_at IS NULL
"""

_GAP_ORDERS = """
    FROM orders o JOIN cases c ON c.id = o.case_id
    WHERE o.document_id IS NULL AND o.download_status IN ('not_available', 'failed')
"""


def _gap_cases(session: Session, limit: int, offset: int) -> tuple[int, dict[str, int], list[dict[str, Any]]]:
    counts = dict.fromkeys(GAP_CASE_STATES, 0)
    for state, n in session.execute(
        text(f"SELECT g.state, count(*) FROM ({_GAP_CASES}) g GROUP BY g.state")
    ).all():
        counts[state] = int(n)
    rows = session.execute(
        text(f"{_GAP_CASES} ORDER BY c.created_at DESC, c.id DESC LIMIT :l OFFSET :o"),
        {"l": limit, "o": offset},
    ).all()
    items = [
        {
            "case": {"id": r.id, "ref_no": r.ref_no, "cnr": r.cnr, "case_no_text": r.case_no_text},
            "first_seen_at": to_ist(r.created_at),
            "state": r.state,
            "attempts": r.attempts,
            "problem": r.last_error if r.state in ("failed", "not_found") else None,
        }
        for r in rows
    ]
    return sum(counts.values()), counts, items


def _gap_orders(
    session: Session, limit: int, offset: int
) -> tuple[int, dict[str, int], list[dict[str, Any]]]:
    counts = {"not_available": 0, "failed": 0}
    for status, n in session.execute(
        text(f"SELECT o.download_status, count(*) {_GAP_ORDERS} GROUP BY o.download_status")
    ).all():
        counts[_value(status)] = int(n)
    rows = session.execute(
        text(
            f"""
            SELECT o.id AS order_id, o.order_no, o.order_date, o.download_status, o.last_error,
                   o.download_attempts, c.id, c.ref_no, c.cnr, c.case_no_text
            {_GAP_ORDERS}
            ORDER BY o.order_date DESC, o.id DESC LIMIT :l OFFSET :o
            """
        ),
        {"l": limit, "o": offset},
    ).all()
    items = [
        {
            "case": {"id": r.id, "ref_no": r.ref_no, "cnr": r.cnr, "case_no_text": r.case_no_text},
            "order_id": r.order_id,
            "order_no": r.order_no,
            "order_date": r.order_date,
            "state": _value(r.download_status),
            "attempts": int(r.download_attempts or 0),
            "problem": r.last_error,
        }
        for r in rows
    ]
    return sum(counts.values()), counts, items


def gaps(session: Session, cfg: Settings, kind: str, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """`GET /admin/data-load/gaps` (decision 45): `cases` held without details (not merged), newest first, each with
    its dossier row's state (`being_fetched` pending or running, `not_found` skipped, `failed`, `not_queued` no row);
    or `orders` without a PDF that the court marked not available or whose fetch failed, latest order first. `counts`
    splits the total by state; `documents_text` is the document-text block of the data-health snapshot. A cancelled
    query raises `SearchTimeout`."""
    if kind not in GAP_KINDS:
        raise LoadInputError("bad_input", f"kind is one of {', '.join(GAP_KINDS)}")
    limit = max(1, min(int(limit), GAP_MAX))
    offset = max(0, int(offset))
    with_timeout(session, cfg.report_statement_timeout_seconds)
    reader = _gap_cases if kind == "cases" else _gap_orders
    slow = "the data gaps took too long; try again"
    total, counts, items = _timed(lambda: reader(session, limit, offset), slow)
    return {
        "kind": kind,
        "total": total,
        "counts": counts,
        "items": items,
        "documents_text": _timed(lambda: data_health.documents_text(session), slow),
    }


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
