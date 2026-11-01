"""Collect Now: manual requests carried out at once (design `data-collection-redesign`, decisions 22-33; round 3).

- **At once, through the worker** (decision 23): a request writes its `fetch_queue` rows at a "now" priority
  (`NOW_ONE` 3 for one to 20 cases, `NOW_BULK` 5 for a list or a day; `load_policy`, decision 24) in the `request`
  lane with the person in `requested_by`, and returns at once. The worker claims them ahead of everything, outside the
  reserve bands, and what they spawn (a dossier's order PDFs) inherits the priority. Nothing here calls NAPIX.
- **The request record is its audit row** (decision 32): `data_load.collect_requested` with `after.refs` = the queue
  rows (`[{kind, ref}]`; a fresh case is in `after.fresh` only), plus the existing buttons' rows
  (`napix.refetch_requested`, `napix.masters_sync_requested`) and `data_load.details_requested` (`after.queue_refs`).
  The rows a request writes carry its id (`fetch_queue.result.request_ids`, `after.tagged`; row 174 review), and so do
  the order PDFs its rows spawn when the worker runs them (`queue.from_parent`). A request's items are its own rows
  and the request-lane `order_pdf` rows carrying its id; an item is open while it is pending or running and still
  carries the id. Later work of anyone else (a claim's court refresh, Fetch Details, a court search, another request,
  the weekly sweep) revives a finished row without the id, so it never reopens a finished request. It is finished
  when none of its items waits ready or is fetching; the bulk request using the allowance is one with an item still
  open, a retry included (`_open`). A request written before the tags (no `after.tagged`) keeps the earlier rule for
  its own rows (`_LEGACY_OPEN_SQL`) and has no spawned items.
- **One Case** (decision 25): each case's dossier, unless its details were fetched in the last 10 minutes, then every
  order PDF it lacks.
- **Bulk requests** (decisions 26-27, 30): a pasted list (up to 200 lines, read by `case_filters.parse_query`) or
  every case on a day's current lists (up to 2,000; never fetched, or every case but those refreshed in the last 6
  hours). One at a time (409 `bulk_running`, under a transaction-scoped advisory lock); they use the whole hourly
  allowance; the checks (`check_list`, `check_day`) write nothing.
- **Stop** (decision 31): the request's rows still pending at `NOW_BULK` go to the request lane's normal priority
  (30); running rows finish; nothing is thrown away. Audited `data_load.collect_stopped`.
- References, CNRs and case numbers only, as Duplicates and the queue already show the same readers; no parties or
  notes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text, tuple_
from sqlalchemy.orm import Session
from uuid6 import uuid7

from aslms.core.config import Settings
from aslms.domain.cases import Case
from aslms.domain.courts import Court
from aslms.domain.events import AuditLog
from aslms.domain.ops import FetchKind, FetchLane, FetchStatus
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.services import access, napix_window, queue
from aslms.services.access import Member
from aslms.services.audit import Actor, write_audit
from aslms.services.audit_search import to_ist
from aslms.services.case_filters import CaseFilterError, parse_query, query_condition
from aslms.services.cases import CaseNotFound, resolve_case_ref
from aslms.services.load_policy import NOW_BULK, NOW_ONE, REQUEST_PRIORITY, QueueOrigin
from aslms.services.napix_admin import NoReference, acting_member, dossier_ref
from aslms.services.orders import enqueue_order_pdfs
from aslms.services.reporting_common import today_ist, with_timeout

ONE_MAX = 20
LIST_MAX = 200
DAY_MAX = 2000
FRESH_DETAILS = timedelta(minutes=10)
RECENTLY_REFRESHED = timedelta(hours=6)
REQUEST_DAYS = 7
ITEMS_MAX = 500
CASES_SHOWN = 20  # the per-case result of a request with at most this many cases
PACE_WINDOW = timedelta(minutes=5)
COLLECTOR_IDLE = timedelta(
    minutes=2
)  # the System Health worker-liveness rule's "no claimed row" for now rows
BULK_LOCK = "aslms-collect-bulk"
LEFT_OUT_KEPT = 200

COLLECT_ACTION = "data_load.collect_requested"
STOP_ACTION = "data_load.collect_stopped"
REQUEST_ACTIONS = (
    COLLECT_ACTION,
    "napix.refetch_requested",
    "napix.masters_sync_requested",
    "data_load.details_requested",
)
DAY_SCOPES = ("never", "all")
LINE_STATES = (
    "will_fetch",
    "already_has_details",
    "not_held",
    "several_match",
    "not_a_reference",
    "merged",
    "no_reference",
)
ITEM_STATES = ("waiting", "waiting_retry", "fetching", "done", "not_found", "failed")
REFETCH_KINDS = {
    FetchKind.CAUSELIST_DAY.value: "refetch_day",
    FetchKind.CAUSELIST_RECHECK.value: "recheck_day",
    FetchKind.DOSSIER.value: "refetch_case",
    FetchKind.ORDER_PDF.value: "refetch_order",
    FetchKind.MASTERS.value: "masters",
}


# ------------------------------------------------------------------------------------------------ errors


class CollectInputError(ValueError):
    """Bad input (HTTP 400): `bad_input`, `no_lists`, `date_in_future`, `too_many`, `nothing_to_fetch`."""

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.extra = extra


class CollectConflict(Exception):
    """The state does not allow it (HTTP 409); `extra` goes into the error body."""

    code = "conflict"

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.extra = extra


class BulkRunning(CollectConflict):
    code = "bulk_running"


class NotRunning(CollectConflict):
    code = "not_running"


class RequestNotFound(LookupError):
    """No such request (HTTP 404)."""


# ------------------------------------------------------------------------------------------------ helpers


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now(UTC)


def _value(v: Any) -> Any:
    return v.value if hasattr(v, "value") else v


def brief(case: Case | None) -> dict[str, Any] | None:
    """`CaseBrief`: `{id, ref_no, cnr, case_no_text}`."""
    if case is None:
        return None
    return {"id": case.id, "ref_no": case.ref_no, "cnr": case.cnr, "case_no_text": case.case_no_text}


def _ref_of(session: Session, case: Case) -> str | None:
    try:
        return dossier_ref(session, case)
    except NoReference:
        return None


def _merged_target(session: Session, case: Case) -> Case | None:
    return session.get(Case, case.merged_into_case_id) if case.merged_into_case_id else None


def hourly_limit(session: Session, now: datetime) -> int | None:
    from aslms.services.data_load import hourly_limit as limit

    return limit(session, now)


def plan(session: Session, cfg: Settings, calls: int, now: datetime | None = None) -> dict[str, Any]:
    """The "use everything" panel's figures (decision 30): the calls, how many fit in this hour (the window's remaining
    count) and how many after the next reset, and when it should finish at the court's hourly limit. No finish time
    when the limit or the remaining count is not known (never a guess)."""
    now = _now(now)
    window = napix_window.current(session, cfg, now)
    limit = hourly_limit(session, now)
    remaining = window.remaining
    reset_at = window.next_reset_at
    this_hour = min(calls, remaining) if remaining is not None else None
    after_reset = calls - this_hour if this_hour is not None else None
    finish_at = None
    speed = min(limit, cfg.napix_rate_limit_per_min * 60) if limit else None
    if speed and this_hour is not None:
        if not after_reset:
            finish_at = now + timedelta(hours=calls / speed)
        elif reset_at is not None:
            finish_at = max(reset_at, now) + timedelta(hours=after_reset / speed)
    return {
        "calls": int(calls),
        "remaining": remaining,
        "this_hour": this_hour,
        "after_reset": after_reset,
        "next_reset_at": to_ist(reset_at),
        "finish_at": to_ist(finish_at),
        "hourly_limit": limit,
        "search_floor": cfg.napix_search_floor,
        "rate_reserve": cfg.napix_rate_reserve,
        "live_reserve": cfg.napix_live_reserve,
    }


def _avg_orders(session: Session) -> float:
    """Orders per case among the cases with details: the expected order PDFs of a case never fetched."""
    cases = session.scalar(
        select(func.count()).select_from(Case).where(Case.last_full_refresh_at.isnot(None))
    )
    if not cases:
        return 0.0
    orders = session.scalar(text("SELECT count(*) FROM orders"))
    return float(orders or 0) / float(cases)


def estimate_calls(session: Session, cases: list[Case], new_cnrs: int = 0) -> int:
    """About how many court calls the cases need: one dossier call each (two for a case known only by its printed
    number: the case-number search first), then every order PDF it lacks; a case never fetched counts the average
    orders per case held."""
    ids = [c.id for c in cases if c.last_full_refresh_at is not None]
    missing: dict[uuid.UUID, int] = {}
    if ids:
        missing = {
            cid: int(n)
            for cid, n in session.execute(
                text(
                    "SELECT case_id, count(*) FROM orders WHERE case_id = ANY(:ids) AND document_id IS NULL "
                    "AND download_status = 'pending' GROUP BY case_id"
                ),
                {"ids": ids},
            ).all()
        }
    never = sum(1 for c in cases if c.last_full_refresh_at is None) + new_cnrs
    avg = _avg_orders(session) if never else 0.0
    calls = sum(1 + (0 if c.cnr else 1) for c in cases) + new_cnrs
    calls += sum(missing.values()) + round(never * avg)
    return int(calls)


# ------------------------------------------------------------------------------------------------ the list check


@dataclass
class LineCheck:
    line: str
    state: str
    case: Case | None = None
    cnr: str | None = None  # a CNR not held: fetched from the court by that very CNR
    merged_into: str | None = None
    matches: int = 0

    @property
    def ref(self) -> str | None:
        return self.cnr

    def as_dict(self) -> dict[str, Any]:
        return {
            "line": self.line,
            "state": self.state,
            "case": brief(self.case),
            "cnr": self.cnr if self.case is None else (self.case.cnr if self.case else None),
            "details_fetched_at": to_ist(self.case.last_full_refresh_at) if self.case else None,
            "merged_into_ref_no": self.merged_into,
            "matches": self.matches,
        }


def _held(session: Session, line: str, case: Case | None) -> LineCheck:
    if case is None:
        return LineCheck(line, "not_held")
    if case.merged_into_case_id is not None:
        target = _merged_target(session, case)
        return LineCheck(line, "merged", case, merged_into=target.ref_no if target else None)
    if _ref_of(session, case) is None:
        return LineCheck(line, "no_reference", case)
    if case.last_full_refresh_at is not None:
        return LineCheck(line, "already_has_details", case)
    return LineCheck(line, "will_fetch", case)


def classify(session: Session, line: str) -> LineCheck:
    """One pasted line (decision 26): an ASLMS reference or id → the held case; a CNR → the held case, or when not held
    a dossier by that CNR (the court's own identifier); a case number → the held cases the local search matches (one,
    several or none); anything else → not a case reference."""
    try:
        p = parse_query(line)
    except CaseFilterError:
        return LineCheck(line, "not_a_reference")
    if p.kind == "id":
        return _held(session, line, session.get(Case, p.id))
    if p.kind == "ref_no":
        return _held(session, line, session.scalar(select(Case).where(Case.ref_no == p.ref_no)))
    if p.kind == "cnr":
        case = session.scalar(select(Case).where(Case.cnr == p.cnr))
        if case is None:
            return LineCheck(line, "will_fetch", cnr=p.cnr)
        return _held(session, line, case)
    if p.kind == "number":
        found = session.scalars(
            select(Case)
            .where(query_condition(session, p), Case.merged_into_case_id.is_(None))
            .order_by(Case.created_at)
            .limit(2)
        ).all()
        if len(found) > 1:
            return LineCheck(line, "several_match", matches=len(found))
        return _held(session, line, found[0] if found else None)
    return LineCheck(line, "not_a_reference")


def _lines(lines: list[str]) -> list[str]:
    out = list(dict.fromkeys(ln.strip() for ln in lines if ln and ln.strip()))
    if not out:
        raise CollectInputError("bad_input", "at least one case, one per line")
    if len(out) > LIST_MAX:
        raise CollectInputError("too_many", f"at most {LIST_MAX} cases, one per line", limit=LIST_MAX)
    return out


@dataclass
class Target:
    """A case (or a CNR not held) a request fetches: its dossier ref, unless its details are fresh."""

    ref: str
    case: Case | None
    fresh: bool = False


@dataclass
class ListPlan:
    checks: list[LineCheck]
    targets: list[Target]
    calls: int
    counts: dict[str, int] = field(default_factory=dict)


def _list_plan(session: Session, lines: list[str], force: bool) -> ListPlan:
    checks = [classify(session, ln) for ln in _lines(lines)]
    counts = {s: 0 for s in LINE_STATES}
    targets: dict[str, Target] = {}
    for c in checks:
        counts[c.state] += 1
        if c.state == "will_fetch" or (force and c.state == "already_has_details"):
            ref = c.cnr if c.case is None else _ref_of(session, c.case)
            if ref is not None and ref not in targets:
                targets[ref] = Target(ref, c.case)
    held = [t.case for t in targets.values() if t.case is not None]
    new = sum(1 for t in targets.values() if t.case is None)
    return ListPlan(checks, list(targets.values()), estimate_calls(session, held, new), counts)


def check_list(
    session: Session, cfg: Settings, lines: list[str], force: bool = False, now: datetime | None = None
) -> dict[str, Any]:
    """`POST /admin/data-load/collect/list/check`: each line read, the counts, what would be fetched and the calls, and
    the "use everything" panel. Writes nothing."""
    p = _list_plan(session, lines, force)
    return {
        "items": [c.as_dict() for c in p.checks],
        "counts": p.counts,
        "force": force,
        "to_fetch": len(p.targets),
        "plan": plan(session, cfg, p.calls, now),
        "bulk": active_bulk_summary(session, cfg, now),
    }


# ------------------------------------------------------------------------------------------------ the day check


@dataclass
class DayPlan:
    list_date: date
    scope: str
    lists: int
    cases: list[Case]
    with_details: int
    details_from: datetime | None
    details_to: datetime | None
    never_fetched: int
    refreshed_recently: int
    no_reference: int
    targets: list[Target]
    calls: int


def _day_plan(session: Session, d: date, scope: str, now: datetime) -> DayPlan:
    if scope not in DAY_SCOPES:
        raise CollectInputError("bad_input", "scope is never or all")
    today = today_ist(now)
    if d > today + timedelta(days=1):
        raise CollectInputError("date_in_future", "cases can be collected for days up to tomorrow")
    lists = int(
        session.scalar(
            text("SELECT count(*) FROM causelists WHERE list_date = :d AND superseded_at IS NULL"), {"d": d}
        )
        or 0
    )
    if not lists:
        raise CollectInputError("no_lists", f"no cause list of {d.isoformat()} is held")
    ids = [
        row[0]
        for row in session.execute(
            text(
                """
                SELECT DISTINCT e.case_id FROM causelist_entries e
                JOIN causelists cl ON cl.id = e.causelist_id
                WHERE cl.list_date = :d AND cl.superseded_at IS NULL AND e.case_id IS NOT NULL
                """
            ),
            {"d": d},
        ).all()
    ]
    cases = (
        session.scalars(
            select(Case).where(Case.id.in_(ids), Case.merged_into_case_id.is_(None)).order_by(Case.ref_no)
        ).all()
        if ids
        else []
    )
    recent = now - RECENTLY_REFRESHED
    with_details = [c for c in cases if c.last_full_refresh_at is not None]
    courts = {c.id: c.est_code for c in session.scalars(select(Court)).all()}
    targets: list[Target] = []
    no_reference = 0
    refreshed = 0
    for c in cases:
        ref = c.cnr or (f"{courts.get(c.court_id)}|{c.case_no_text}" if c.case_no_text else None)
        if ref is None:
            no_reference += 1
            continue
        held = c.last_full_refresh_at is not None
        if held and c.last_full_refresh_at >= recent:
            refreshed += 1
        if scope == "never" and held:
            continue
        if scope == "all" and held and c.last_full_refresh_at >= recent:
            continue
        targets.append(Target(ref, c))
    times = [c.last_full_refresh_at for c in with_details]
    return DayPlan(
        list_date=d,
        scope=scope,
        lists=lists,
        cases=list(cases),
        with_details=len(with_details),
        details_from=min(times) if times else None,
        details_to=max(times) if times else None,
        never_fetched=len(cases) - len(with_details),
        refreshed_recently=refreshed,
        no_reference=no_reference,
        targets=targets,
        calls=estimate_calls(session, [t.case for t in targets if t.case is not None]),
    )


def _day_cap(p: DayPlan) -> None:
    if len(p.targets) > DAY_MAX:
        raise CollectInputError(
            "too_many", f"{len(p.targets)} cases to fetch; at most {DAY_MAX}", to_fetch=len(p.targets)
        )


def check_day(
    session: Session, cfg: Settings, d: date, scope: str = "never", now: datetime | None = None
) -> dict[str, Any]:
    """`GET /admin/data-load/collect/day` (decision 27): the day's current lists, the cases listed (distinct, not
    merged), with details and when, never fetched, refreshed in the last 6 hours, without a court reference, and what
    the scope would fetch, with the calls and the "use everything" panel. Writes nothing."""
    now = _now(now)
    p = _day_plan(session, d, scope, now)
    _day_cap(p)
    return {
        "date": d,
        "scope": scope,
        "lists": p.lists,
        "cases_listed": len(p.cases),
        "with_details": p.with_details,
        "details_from": to_ist(p.details_from),
        "details_to": to_ist(p.details_to),
        "never_fetched": p.never_fetched,
        "refreshed_recently": p.refreshed_recently,
        "no_reference": p.no_reference,
        "to_fetch": len(p.targets),
        "plan": plan(session, cfg, p.calls, now),
        "bulk": active_bulk_summary(session, cfg, now),
    }


# ------------------------------------------------------------------------------------------------ collect


@dataclass
class CollectResult:
    request_id: uuid.UUID
    kind: str
    to_fetch: int
    queued: int
    already_waiting: int
    left_out: list[dict[str, Any]]
    priority: int
    expected_end: datetime | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "kind": self.kind,
            "to_fetch": self.to_fetch,
            "queued": self.queued,
            "already_waiting": self.already_waiting,
            "left_out": self.left_out,
            "priority": self.priority,
            "expected_end": self.expected_end,
        }


def _cases_targets(
    session: Session, refs: list[str], now: datetime
) -> tuple[list[Target], list[dict[str, Any]]]:
    clean = list(dict.fromkeys(r.strip() for r in refs if r and r.strip()))
    if not clean:
        raise CollectInputError("bad_input", "at least one case")
    if len(clean) > ONE_MAX:
        raise CollectInputError("too_many", f"at most {ONE_MAX} cases at once", limit=ONE_MAX)
    targets: dict[str, Target] = {}
    left_out: list[dict[str, Any]] = []
    for r in clean:
        try:
            case = resolve_case_ref(session, r)
        except CaseNotFound:
            left_out.append({"ref": r, "reason": "not_held"})
            continue
        if case.merged_into_case_id is not None:
            target = _merged_target(session, case)
            left_out.append(
                {"ref": r, "reason": "merged", "merged_into_ref_no": target.ref_no if target else None}
            )
            continue
        ref = _ref_of(session, case)
        if ref is None:
            left_out.append({"ref": r, "reason": "no_reference"})
            continue
        fresh = case.last_full_refresh_at is not None and case.last_full_refresh_at >= now - FRESH_DETAILS
        targets.setdefault(ref, Target(ref, case, fresh=fresh))
    return list(targets.values()), left_out


def _lock_bulk(session: Session) -> None:
    """One bulk request at a time: the check and the write under a transaction-scoped advisory lock (PgBouncer-safe)."""
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": BULK_LOCK})


def collect(
    session: Session,
    actor: Actor,
    user: User | Member | None,
    cfg: Settings,
    body: dict[str, Any],
    now: datetime | None = None,
) -> CollectResult:
    """`POST /admin/data-load/collect`: `{kind: "cases", refs}` (1-20 cases at `NOW_ONE`), `{kind: "list", lines,
    force}` or `{kind: "day", date, scope}` (bulk, at `NOW_BULK`, one at a time: 409 `bulk_running`). The rows are
    written in the request lane with the person; one audit row `data_load.collect_requested` with the refs."""
    now = _now(now)
    member = acting_member(session, user, Permission.ADMIN_DATA_LOAD)
    kind = body.get("kind")
    extra: dict[str, Any] = {}
    left_out: list[dict[str, Any]] = []
    if kind == "cases":
        targets, left_out = _cases_targets(session, list(body.get("refs") or []), now)
        priority, bulk = NOW_ONE, False
        calls = estimate_calls(session, [t.case for t in targets if t.case is not None])
    elif kind == "list":
        force = bool(body.get("force"))
        p = _list_plan(session, list(body.get("lines") or []), force)
        targets = p.targets
        priority, bulk, calls = NOW_BULK, True, p.calls
        fetched = {"will_fetch"} | ({"already_has_details"} if force else set())
        left_out = [
            {"ref": c.line, "reason": c.state, "merged_into_ref_no": c.merged_into}
            for c in p.checks
            if c.state not in fetched
        ]
        extra = {"force": force, "lines": len(p.checks)}
    elif kind == "day":
        d = body.get("date")
        if isinstance(d, str):
            try:
                d = date.fromisoformat(d)
            except ValueError as exc:
                raise CollectInputError("bad_input", "date is YYYY-MM-DD") from exc
        if not isinstance(d, date):
            raise CollectInputError("bad_input", "date is required")
        scope = str(body.get("scope") or "never")
        p = _day_plan(session, d, scope, now)
        _day_cap(p)
        targets = p.targets
        priority, bulk, calls = NOW_BULK, True, p.calls
        extra = {"date": d.isoformat(), "scope": scope, "cases_listed": len(p.cases)}
        held = p.with_details if scope == "never" else p.refreshed_recently
        left_out = [
            {"ref": None, "reason": reason, "count": n}
            for reason, n in (
                ("already_has_details" if scope == "never" else "refreshed_recently", held),
                ("no_reference", p.no_reference),
            )
            if n
        ]
    else:
        raise CollectInputError("bad_input", "kind is cases, list or day")
    if not targets:
        raise CollectInputError(
            "nothing_to_fetch",
            "nothing to fetch: every case already has details or cannot be fetched",
            left_out=left_out[:LEFT_OUT_KEPT],
        )
    if bulk:
        _lock_bulk(session)
        running = active_bulk(session, now)
        if running is not None:
            raise BulkRunning(
                "a data collection request is already using the whole allowance; one at a time",
                **_bulk_extra(running),
            )
    person = napix_window.user_id_of(user)
    # the request's id, chosen before its rows are written: they carry it (`result.request_ids`, row 174 review), so its
    # items are exactly the rows of its own run and what that run spawns
    request_id = uuid7()
    tags = (str(request_id),)
    origin = QueueOrigin(FetchLane.REQUEST, requested_by=person, now_priority=priority, request_ids=tags)
    refs = [t.ref for t in targets if not t.fresh]
    before = _states(session, FetchKind.DOSSIER, refs)
    queued = already = 0
    for t in targets:
        if t.fresh and t.case is not None:
            # decision 25: the details were fetched minutes ago (a CNR search just did); only the missing order PDFs
            enqueue_order_pdfs(session, t.case, origin)
            continue
        if before.get(t.ref) in (FetchStatus.PENDING.value, FetchStatus.RUNNING.value):
            already += 1
        queue.enqueue(
            session,
            FetchKind.DOSSIER,
            t.ref,
            priority,
            requeue=True,
            lane=FetchLane.REQUEST,
            requested_by=person,
            request_ids=tags,
        )
        if before.get(t.ref) not in (FetchStatus.PENDING.value, FetchStatus.RUNNING.value):
            queued += 1
    pl = plan(session, cfg, calls, now)
    expected_end = pl["finish_at"]
    entry = write_audit(
        session,
        access.actor_as(actor, member),
        COLLECT_ACTION,
        "fetch_queue",
        None,
        after={
            "kind": kind,
            "bulk": bulk,
            "priority": priority,
            # a fresh case has no dossier row of the request (deviation 4): only its order PDFs, found by `fresh`
            "refs": [{"kind": FetchKind.DOSSIER.value, "ref": ref} for ref in refs],
            "fresh": [t.ref for t in targets if t.fresh],
            "to_fetch": len(targets),
            "queued": queued,
            "already_waiting": already,
            "left_out": left_out[:LEFT_OUT_KEPT],
            "calls": calls,
            "expected_end": expected_end,
            "tagged": True,
            **extra,
        },
        row_id=request_id,
    )
    return CollectResult(
        request_id=entry.id,
        kind=kind,
        to_fetch=len(targets),
        queued=queued,
        already_waiting=already,
        left_out=left_out[:LEFT_OUT_KEPT],
        priority=priority,
        expected_end=expected_end,
    )


def _states(session: Session, kind: FetchKind, refs: list[str]) -> dict[str, str]:
    if not refs:
        return {}
    return {
        ref: _value(st)
        for ref, st in session.execute(
            text(
                "SELECT ref, status::text FROM fetch_queue WHERE kind = CAST(:kind AS fetch_kind) "
                "AND ref = ANY(CAST(:refs AS text[]))"
            ),
            {"kind": kind.value, "refs": refs},
        ).all()
    }


# ------------------------------------------------------------------------------------------------ requests


@dataclass
class Request:
    """A request record: an audit row of one of `REQUEST_ACTIONS` and its queue refs; `tagged` when its rows carry its
    id (written since the row 174 review)."""

    row: AuditLog
    kind: str
    refs: list[tuple[str, str]]
    bulk: bool
    fresh: list[str] = field(default_factory=list)
    tagged: bool = False

    @property
    def id(self) -> uuid.UUID:
        return self.row.id

    @property
    def asked_at(self) -> datetime:
        return self.row.created_at

    @property
    def has_items(self) -> bool:
        """Its own queue rows, or fresh cases whose order PDFs it queued."""
        return bool(self.refs or self.fresh)

    @property
    def case_count(self) -> int:
        return len(self.refs) + len(self.fresh)


def as_request(row: AuditLog) -> Request:
    after = row.after or {}
    tagged = bool(after.get("tagged"))
    if row.action == COLLECT_ACTION:
        fresh = [str(f) for f in after.get("fresh") or []]
        # a fresh case's dossier is never the request's item, even on a row that listed it in `refs`
        refs = [
            (str(r.get("kind")), str(r.get("ref")))
            for r in after.get("refs") or []
            if isinstance(r, dict)
            and not (r.get("kind") == FetchKind.DOSSIER.value and str(r.get("ref")) in fresh)
        ]
        return Request(row, str(after.get("kind") or "cases"), refs, bool(after.get("bulk")), fresh, tagged)
    if row.action == "data_load.details_requested":
        refs = [
            (str(r.get("kind")), str(r.get("ref")))
            for r in after.get("queue_refs") or []
            if isinstance(r, dict)
        ]
        return Request(row, "details", refs, False, tagged=tagged)
    k, ref = after.get("kind"), after.get("ref")
    refs = [(str(k), str(ref))] if k and ref else []
    return Request(row, REFETCH_KINDS.get(str(k), "refetch"), refs, False, tagged=tagged)


# whether a pending or running queue row is still this request's run (decision 32; row 174 review): it carries the
# request's id. `enqueue` gives an inserted or revived row exactly the ids it is called with (none for system work)
# and adds them to a pending or running row; `fail` keeps them, so a retry of the request's run is still its item
_TAGGED_SQL = "COALESCE(q.result -> 'request_ids' @> jsonb_build_array(CAST(:rid AS text)), false)"
# a request written before the tags: its run had not finished by the time it was asked (`finished_at` before it), or
# it is a retry of that run (attempts at least 1, or 2 while running) still carrying the request's now priority or its
# lane and person (deviation 19)
_LEGACY_OPEN_SQL = """
    (q.finished_at IS NULL OR q.finished_at < :asked
     OR (q.attempts >= CASE WHEN q.status = 'running' THEN 2 ELSE 1 END
         AND (q.priority <= :now_max OR (q.lane = 'request' AND q.requested_by = CAST(:asker AS uuid)))))
"""
_OPEN_SQL = f"(CASE WHEN :tagged THEN {_TAGGED_SQL} ELSE {_LEGACY_OPEN_SQL} END)"

_STATE_SQL = f"""
    CASE WHEN q.id IS NULL THEN 'done'
         WHEN q.status IN ('pending', 'running') AND NOT {_OPEN_SQL} THEN 'done'
         WHEN q.status = 'pending' AND q.not_before > now() THEN 'waiting_retry'
         WHEN q.status = 'pending' THEN 'waiting'
         WHEN q.status = 'running' THEN 'fetching'
         WHEN q.status = 'done' THEN 'done'
         WHEN q.status = 'skipped' THEN 'not_found'
         ELSE 'failed' END
"""

# the request's own rows (in its order), then the order PDFs carrying its id that are not among them (the ones its rows
# spawned, decision 32; row 174 review). They are looked up through the request's own rows, never by scanning the
# queue: the orders of its cases (its CNRs, its fresh cases and the CNRs its provisional dossier rows resolved to), each
# order's `order_pdf` row by the unique (kind, ref) index, then the id. So the cost follows the request's size, not the
# queue's history. A request written before the tags has no spawned items
_ITEMS_CTE = f"""
    WITH r AS (
        SELECT * FROM unnest(CAST(:kinds AS fetch_kind[]), CAST(:refs AS text[])) WITH ORDINALITY AS r(kind, ref, n)
    ),
    own AS (
        SELECT r.n AS n, r.kind::text AS kind, r.ref AS ref, q.id AS queue_id, {_STATE_SQL} AS state,
               q.priority, q.attempts, q.not_before, q.last_error, q.finished_at, q.result ->> 'cnr' AS found_cnr
        FROM r LEFT JOIN fetch_queue q ON q.kind = r.kind AND q.ref = r.ref
    ),
    req_cnrs AS (
        SELECT unnest(CAST(:cnrs AS text[])) AS cnr
        UNION
        SELECT upper(found_cnr) FROM own WHERE :tagged AND kind = 'dossier' AND found_cnr IS NOT NULL
    ),
    spawned AS (
        SELECT 1000000 + row_number() OVER (ORDER BY q.ref) AS n, 'order_pdf' AS kind, q.ref AS ref,
               q.id AS queue_id, {_STATE_SQL} AS state, q.priority, q.attempts, q.not_before, q.last_error,
               q.finished_at, NULL::text AS found_cnr
        FROM req_cnrs rc
        JOIN cases c ON c.cnr = rc.cnr
        JOIN orders o ON o.case_id = c.id
        JOIN fetch_queue q ON q.kind = 'order_pdf'
            AND q.ref = c.cnr || '|' || o.order_no || '|' || to_char(o.order_date, 'YYYY-MM-DD')
        WHERE :tagged AND {_TAGGED_SQL}
          AND NOT EXISTS (SELECT 1 FROM r WHERE r.kind = 'order_pdf' AND r.ref = q.ref)
    ),
    items AS (SELECT * FROM own UNION ALL SELECT * FROM spawned)
"""


def _params(req: Request) -> dict[str, Any]:
    """The items query's parameters."""
    return {
        "kinds": [k for k, _ in req.refs],
        "refs": [r for _, r in req.refs],
        "rid": str(req.id),
        "tagged": req.tagged,
        "cnrs": _case_keys(req)[0] if req.tagged else [],
        "asked": req.asked_at,
        "asker": req.row.actor_user_id,
        "now_max": NOW_BULK,
    }


def _case_keys(req: Request) -> tuple[list[str], list[tuple[str, str]], list[str]]:
    """The request's cases for the per-case result: its CNRs (dossier and order PDF refs, fresh cases), its printed
    numbers with their establishment (`<est_code>|<number>` refs) and those provisional refs themselves."""
    cnrs: set[str] = set()
    numbers: set[tuple[str, str]] = set()
    provisional: set[str] = set()
    for k, r in [*req.refs, *((FetchKind.DOSSIER.value, f) for f in req.fresh)]:
        if k == FetchKind.DOSSIER.value:
            if "|" in r:
                est, no = r.split("|", 1)
                numbers.add((est, no))
                provisional.add(r)
            else:
                cnrs.add(r.upper())
        elif k == FetchKind.ORDER_PDF.value:
            cnrs.add(r.split("|", 1)[0])
    return sorted(cnrs), sorted(numbers), sorted(provisional)


def _counts(session: Session, req: Request) -> dict[str, Any]:
    """The items by state and by kind, and the items finished in the last 5 minutes (the pace)."""
    by_state = {s: 0 for s in ITEM_STATES}
    by_kind: dict[str, dict[str, int]] = {}
    if not req.has_items:
        return {"by_state": by_state, "by_kind": by_kind, "total": 0, "recent": 0, "retry_at": None}
    rows = session.execute(
        text(
            _ITEMS_CTE
            + """
            SELECT kind, state, count(*), count(*) FILTER (WHERE finished_at >= :recent AND state IN ('done',
                   'not_found')), min(not_before) FILTER (WHERE state = 'waiting_retry')
            FROM items GROUP BY kind, state
            """
        ),
        {**_params(req), "recent": datetime.now(UTC) - PACE_WINDOW},
    ).all()
    total = recent = 0
    retry_at: datetime | None = None
    for kind, state, n, fin, retry in rows:
        by_state[state] = by_state.get(state, 0) + int(n)
        k = by_kind.setdefault(kind, {s: 0 for s in ITEM_STATES})
        k[state] = k.get(state, 0) + int(n)
        total += int(n)
        recent += int(fin or 0)
        if retry is not None and (retry_at is None or retry < retry_at):
            retry_at = retry
    return {"by_state": by_state, "by_kind": by_kind, "total": total, "recent": recent, "retry_at": retry_at}


def _stopped(session: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, AuditLog]:
    if not ids:
        return {}
    rows = session.scalars(
        select(AuditLog).where(
            AuditLog.action == STOP_ACTION,
            AuditLog.after["request_id"].astext.in_([str(i) for i in ids]),
        )
    ).all()
    return {uuid.UUID(r.after["request_id"]): r for r in rows}


def _finished(counts: dict[str, Any]) -> bool:
    """Decision 32: no item waits ready or is fetching (a row waiting for its retry does not hold the result)."""
    return counts["by_state"]["waiting"] == 0 and counts["by_state"]["fetching"] == 0


def _open(counts: dict[str, Any]) -> bool:
    """Whether the request still has work in the queue, a row waiting for its retry included (row 174 review): a bulk
    request with only retries left still uses the allowance when they fall due, so it stays the one bulk request
    (409 `bulk_running` for another) and Stop can still move them."""
    return not _finished(counts) or counts["by_state"]["waiting_retry"] > 0


def summary(
    session: Session,
    cfg: Settings,
    req: Request,
    stopped: AuditLog | None,
    now: datetime | None = None,
    counts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One request for the Requests card: what, who and when, the items by state, whether it is finished, and for a
    bulk request whether it is using the whole allowance or was stopped, with its expected end."""
    now = _now(now)
    counts = counts or _counts(session, req)
    finished = _finished(counts)
    left = counts["by_state"]["waiting"] + counts["by_state"]["fetching"]
    after = req.row.after or {}
    using = req.bulk and stopped is None and _open(counts)
    expected_end = None
    if using:
        expected_end = plan(session, cfg, left + counts["by_state"]["waiting_retry"], now)["finish_at"]
        retry_at = to_ist(counts["retry_at"])
        if retry_at is not None and (expected_end is None or retry_at > expected_end):
            expected_end = retry_at
    pace = counts["recent"] / (PACE_WINDOW.total_seconds() / 60) if counts["recent"] else None
    return {
        "request_id": req.id,
        "action": req.row.action,
        "kind": req.kind,
        "bulk": req.bulk,
        "asked_by": req.row.actor_name,
        "asked_by_office": req.row.actor_office_code,
        "asked_at": to_ist(req.asked_at),
        "date": after.get("date"),
        "scope": after.get("scope"),
        "cases": req.case_count if req.kind not in ("refetch_day", "recheck_day", "masters") else None,
        "ref": ([r for _, r in req.refs] + req.fresh)[0] if req.case_count == 1 else None,
        "priority": after.get("priority"),
        "counts": counts["by_state"],
        "by_kind": counts["by_kind"],
        "total": counts["total"],
        "finished": finished,
        "stopped": stopped is not None,
        "stopped_at": to_ist(stopped.created_at) if stopped is not None else None,
        "stopped_by": stopped.actor_name if stopped is not None else None,
        "using_everything": using,
        "retry_at": to_ist(counts["retry_at"]),
        "eta_seconds": round(left / pace * 60) if pace and left else None,
        "expected_end": expected_end,
    }


def _request_rows(session: Session, since: datetime, limit: int) -> list[AuditLog]:
    return list(
        session.scalars(
            select(AuditLog)
            .where(AuditLog.action.in_(REQUEST_ACTIONS), AuditLog.created_at >= since)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit)
        ).all()
    )


def collector_state(session: Session, now: datetime | None = None) -> dict[str, Any]:
    """Whether "now" rows wait for a worker that is not working (decision 23): the System Health liveness (the later of
    the latest pass and the latest claimed row) older than 2 minutes while a "now" row is runnable."""
    from aslms.services.ops_metrics import worker_alive_at

    now = _now(now)
    alive = worker_alive_at(session)
    waiting = queue.has_now(session)
    idle = alive is None or now - alive > COLLECTOR_IDLE
    return {"last_active_at": to_ist(alive), "now_waiting": waiting, "not_running": bool(waiting and idle)}


def window_state(session: Session, cfg: Settings, now: datetime | None = None) -> dict[str, Any]:
    """The court's limit for the request panels: "The court's hourly limit is used up; this continues at about …"."""
    now = _now(now)
    window = napix_window.current(session, cfg, now)
    used_up = window.remaining is not None and window.remaining < 1
    return {
        "remaining": window.remaining,
        "next_reset_at": to_ist(window.next_reset_at),
        "limit_used_up": used_up,
        "resumes_at": to_ist(window.resume_at(now)) if used_up else None,
    }


def requests(session: Session, cfg: Settings, limit: int = 20, now: datetime | None = None) -> dict[str, Any]:
    """`GET /admin/data-load/requests`: the last 7 days' requests, newest first, each with its live progress; the
    collector and the court's limit. Under the report statement timeout (row 174 review)."""
    now = _now(now)
    with_timeout(session, cfg.report_statement_timeout_seconds)
    limit = max(1, min(int(limit), 100))
    rows = _request_rows(session, now - timedelta(days=REQUEST_DAYS), limit)
    reqs = [as_request(r) for r in rows]
    stopped = _stopped(session, [r.id for r in reqs if r.bulk])
    items = [summary(session, cfg, r, stopped.get(r.id), now) for r in reqs]
    return {
        "as_of": to_ist(now),
        "items": items,
        "active": sum(1 for i in items if not i["finished"]),
        "bulk": next((i for i in items if i["using_everything"]), None),
        "collector": collector_state(session, now),
        "window": window_state(session, cfg, now),
    }


def get_request(session: Session, request_id: uuid.UUID) -> Request:
    row = session.get(AuditLog, request_id)
    if row is None or row.action not in REQUEST_ACTIONS:
        raise RequestNotFound("no such request")
    return as_request(row)


def _case_rows(session: Session, req: Request) -> list[Case]:
    """The request's cases: those of its CNRs, those its provisional refs resolved to (the CNR its dossier row found),
    and the cases not merged with a printed number on the ref's own establishment."""
    cnrs, numbers, provisional = _case_keys(req)
    if provisional:
        resolved = session.scalars(
            text(
                "SELECT DISTINCT upper(result ->> 'cnr') FROM fetch_queue WHERE kind = 'dossier' "
                "AND ref = ANY(CAST(:refs AS text[])) AND result ->> 'cnr' IS NOT NULL"
            ),
            {"refs": provisional},
        ).all()
        cnrs = sorted({*cnrs, *(c for c in resolved if c)})
    cases = list(session.scalars(select(Case).where(Case.cnr.in_(cnrs))).all()) if cnrs else []
    if numbers:
        seen = {c.id for c in cases}
        cases += [
            c
            for c in session.scalars(
                select(Case)
                .join(Court, Court.id == Case.court_id)
                .where(
                    tuple_(Court.est_code, Case.case_no_text).in_(numbers),
                    Case.merged_into_case_id.is_(None),
                )
            ).all()
            if c.id not in seen
        ]
    return cases


def _case_results(
    session: Session, req: Request, params: dict[str, Any], items: list[dict[str, Any]]
) -> list[dict]:
    """Decision 25's result per case (a request of at most 20 cases): case number, CNR, status, details fetched at,
    the order PDFs stored, not available, waiting and failed, and when a failed one is tried again."""
    cases = _case_rows(session, req)
    if not cases or len(cases) > CASES_SHOWN:
        return []
    orders = {
        cid: (int(total), int(stored), int(na), int(failed))
        for cid, total, stored, na, failed in session.execute(
            text(
                """
                SELECT case_id, count(*), count(*) FILTER (WHERE document_id IS NOT NULL),
                       count(*) FILTER (WHERE document_id IS NULL AND download_status = 'not_available'),
                       count(*) FILTER (WHERE document_id IS NULL AND download_status = 'failed')
                FROM orders WHERE case_id = ANY(:ids) GROUP BY case_id
                """
            ),
            {"ids": [c.id for c in cases]},
        ).all()
    }
    by_cnr: dict[str, dict[str, Any]] = {}
    for it in items:
        if it["kind"] == FetchKind.ORDER_PDF.value:
            cnr = it["ref"].split("|", 1)[0]
            b = by_cnr.setdefault(cnr, {"waiting": 0, "retry_at": None})
            if it["state"] in ("waiting", "fetching"):
                b["waiting"] += 1
            if it["state"] == "waiting_retry" and it["not_before"] is not None:
                if b["retry_at"] is None or it["not_before"] < b["retry_at"]:
                    b["retry_at"] = it["not_before"]
    details = {it["ref"]: it["state"] for it in items if it["kind"] == FetchKind.DOSSIER.value}
    out = []
    for c in cases:
        total, stored, na, failed = orders.get(c.id, (0, 0, 0, 0))
        q = by_cnr.get(c.cnr or "", {"waiting": 0, "retry_at": None})
        ref = _ref_of(session, c)
        out.append(
            {
                "case": brief(c),
                "status": _value(c.status) if c.status is not None else None,
                "details_fetched_at": to_ist(c.last_full_refresh_at),
                "details": details.get(c.cnr or "") or details.get(ref or "") or "done",
                "orders": {
                    "total": total,
                    "stored": stored,
                    "not_available": na,
                    "failed": failed,
                    "waiting": q["waiting"],
                    "retry_at": to_ist(q["retry_at"]),
                },
            }
        )
    return out


def request_detail(
    session: Session,
    cfg: Settings,
    request_id: uuid.UUID,
    *,
    limit: int = 100,
    offset: int = 0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """`GET /admin/data-load/requests/{id}`: the request's summary, its items paged (each with its state, attempts,
    when it is tried again and the problem in short), the per-case result of a small request, and the steps (case
    details, order PDFs) for the progress panel."""
    now = _now(now)
    with_timeout(session, cfg.report_statement_timeout_seconds)
    req = get_request(session, request_id)
    limit = max(1, min(int(limit), ITEMS_MAX))
    offset = max(0, int(offset))
    stopped = _stopped(session, [req.id]).get(req.id) if req.bulk else None
    counts = _counts(session, req)
    params = _params(req)
    items: list[dict[str, Any]] = []
    all_items: list[dict[str, Any]] = []
    if req.has_items:
        rows = session.execute(
            text(
                _ITEMS_CTE
                + """
                SELECT kind, ref, state, attempts, not_before, last_error, priority FROM items
                ORDER BY n LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": limit, "offset": offset},
        ).all()
        items = [
            {
                "kind": k,
                "ref": r,
                "state": st,
                "attempts": int(att or 0),
                "not_before": nb,
                "problem": (err or "")[:300] or None,
                "priority": pr,
            }
            for k, r, st, att, nb, err, pr in rows
        ]
        if counts["total"] <= CASES_SHOWN * 50:
            all_items = [
                {"kind": k, "ref": r, "state": st, "not_before": nb}
                for k, r, st, nb in session.execute(
                    text(_ITEMS_CTE + " SELECT kind, ref, state, not_before FROM items"), params
                ).all()
            ]
    cases = _case_results(session, req, params, all_items) if all_items or req.fresh else []
    by_kind = counts["by_kind"]
    dossier = by_kind.get(FetchKind.DOSSIER.value, {s: 0 for s in ITEM_STATES})
    orders = {
        "total": sum(c["orders"]["total"] for c in cases),
        "stored": sum(c["orders"]["stored"] for c in cases),
        "not_available": sum(c["orders"]["not_available"] for c in cases),
        "failed": sum(c["orders"]["failed"] for c in cases),
        "waiting": sum(c["orders"]["waiting"] for c in cases),
    }
    out = summary(session, cfg, req, stopped, now, counts)
    out.update(
        {
            "items": [{**i, "not_before": to_ist(i["not_before"])} for i in items],
            "limit": limit,
            "offset": offset,
            "results": cases,
            "steps": {
                "details": {s: int(dossier.get(s, 0)) for s in ITEM_STATES},
                "orders": orders,
            },
            "collector": collector_state(session, now),
            "window": window_state(session, cfg, now),
            "left_out": (req.row.after or {}).get("left_out") or [],
        }
    )
    return out


# ------------------------------------------------------------------------------------------------ bulk and stop


def active_bulk(session: Session, now: datetime | None = None) -> Request | None:
    """The bulk request using the whole allowance: the newest bulk `data_load.collect_requested` of the last 7 days
    that was not stopped and still has an item open (waiting ready, waiting for its retry or fetching)."""
    now = _now(now)
    rows = session.scalars(
        select(AuditLog)
        .where(
            AuditLog.action == COLLECT_ACTION,
            AuditLog.created_at >= now - timedelta(days=REQUEST_DAYS),
            AuditLog.after["bulk"].astext == "true",
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(5)
    ).all()
    reqs = [as_request(r) for r in rows]
    stopped = _stopped(session, [r.id for r in reqs])
    for req in reqs:
        if req.id in stopped:
            continue
        if _open(_counts(session, req)):
            return req
    return None


def _bulk_extra(req: Request) -> dict[str, Any]:
    after = req.row.after or {}
    return {
        "request_id": str(req.id),
        "asked_by": req.row.actor_name,
        "kind": req.kind,
        "date": after.get("date"),
        "cases": req.case_count,
        "asked_at": to_ist(req.asked_at).isoformat() if req.asked_at else None,
    }


def active_bulk_summary(
    session: Session, cfg: Settings, now: datetime | None = None
) -> dict[str, Any] | None:
    """The Overview's `bulk` and the panels' "a request is using the whole allowance until about …"."""
    req = active_bulk(session, now)
    return summary(session, cfg, req, None, now) if req is not None else None


def stop(
    session: Session,
    actor: Actor,
    user: User | Member | None,
    request_id: uuid.UUID,
    now: datetime | None = None,
) -> dict[str, Any]:
    """`POST /admin/data-load/requests/{id}/stop` (decision 31): the request's rows still pending at `NOW_BULK` go to
    the request lane's normal priority (30), where the bands apply again; running rows finish, at 30 too, so the order
    PDFs they spawn take the normal turn (row 174 review); nothing is skipped.
    409 `not_running` for a request that is not a bulk request using the allowance. Audited
    `data_load.collect_stopped`."""
    now = _now(now)
    member = acting_member(session, user, Permission.ADMIN_DATA_LOAD)
    req = get_request(session, request_id)
    if not req.bulk:
        raise NotRunning("only a bulk request uses the whole allowance and can be stopped")
    if _stopped(session, [req.id]):
        raise NotRunning("this request was stopped already")
    if not _open(_counts(session, req)):
        raise NotRunning("this request has finished")
    params = {**_params(req), "normal": REQUEST_PRIORITY, "bulk": NOW_BULK}
    # first the request's running rows (row 174 review): their run finishes, but what they spawn re-reads their priority
    # (`queue.from_parent`) and now goes to the normal turn. A worker spawning holds its row's lock, so this waits for
    # it, and the next statement, with a fresh snapshot, reaches the rows it spawned
    running = (
        session.execute(
            text(
                _ITEMS_CTE
                + """
                UPDATE fetch_queue q SET priority = :normal
                FROM items i
                WHERE q.id = i.queue_id AND i.state = 'fetching' AND q.status = 'running' AND q.priority = :bulk
                """
            ),
            params,
        ).rowcount
        or 0
    )
    moved = (
        session.execute(
            text(
                _ITEMS_CTE
                + """
                UPDATE fetch_queue q SET priority = :normal
                FROM items i
                WHERE q.id = i.queue_id AND i.state IN ('waiting', 'waiting_retry') AND q.status = 'pending'
                  AND q.priority = :bulk
                """
            ),
            params,
        ).rowcount
        or 0
    )
    write_audit(
        session,
        access.actor_as(actor, member),
        STOP_ACTION,
        "audit_log",
        req.id,
        after={"request_id": str(req.id), "moved": moved, "running": running},
    )
    return {"request_id": req.id, "moved": moved}


def bulk_message(session: Session, cfg: Settings, now: datetime | None = None) -> str | None:
    """The sentence a refused court search adds while a bulk request uses the allowance (decision 30)."""
    req = active_bulk(session, now)
    if req is None:
        return None
    s = summary(session, cfg, req, None, now)
    until = s["expected_end"]
    when = f" until about {until:%H:%M}" if until else ""
    after = " after that" if until else " later"
    return f"The court's hourly allowance is in use by a data collection request{when}. Try again{after}."


def active_count(session: Session, cfg: Settings, now: datetime | None = None) -> int:
    """Requests of the last 24 hours not finished yet (the pulse's `requests_active`, polled every 5 s)."""
    now = _now(now)
    rows = _request_rows(session, now - timedelta(days=1), 20)
    return sum(1 for r in rows if not _finished(_counts(session, as_request(r))))
