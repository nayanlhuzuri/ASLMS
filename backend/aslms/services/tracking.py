"""Pipeline stage 4: keeping cases current. Current Status takes up to `NAPIX_STATUS_BATCH` CNRs per call (250 by
default: the gateway refuses longer query strings with HTTP 414, see napix_integration_notes.md §7), so the daily
refresh of every non-disposed case is a handful of `status_batch` queue rows (`<YYYY-MM-DD>:<n>` = the n-th block of
`NAPIX_STATUS_BATCH` non-disposed CNRs in CNR order on that day). A change in a tracked field updates the case, writes
a `next_dates` row and an event, and queues a dossier re-fetch at 50, reviving a finished row `as_new`.

The nightly refresh (design `rolling-case-refresh`, 22:00 IST): first the hearing follow-ups (a case heard by the
court's own record is re-fetched about 3, 7, 14 and 30 days after the hearing until an order dated on or after it is
stored; 50), then every fetched case not disposed whose last full record is 7 IST dates old, claimed cases first (56,
57), oldest first, with a levelled quota that refreshes a few not-yet-due cases early when a clump is coming (58, 59),
bounded by `ROLLING_REFRESH_DAILY_MAX`. A case refreshed for any reason waits a fresh 7 days; a case whose dossier row
failed in the last 7 days is left out. The Sunday job queues only the cases never fully fetched (50; design
`safety-fixes`, decision 9). A disposed case is refreshed monthly for a year after its disposal (design
`court-data-freshness`, decisions 1-6): the 02:30 IST job queues the due ones, oldest refresh first, capped."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Date, Integer, exists, func, literal, select, type_coerce
from sqlalchemy import case as sa_case
from sqlalchemy.orm import Session

from aslms.core.clock import today_ist
from aslms.domain.alerts import NextDate, NextDateSource, ReviewStatus
from aslms.domain.cases import Case, CaseStatus
from aslms.domain.courts import Court
from aslms.domain.ops import FetchKind, FetchLane, FetchQueueItem, FetchStatus
from aslms.domain.reference import EventType
from aslms.integration.napix.hc import NapixHighCourt
from aslms.services import queue
from aslms.services.cases import apply_status, emit_event
from aslms.services.napix_values import as_text


def batch_size() -> int:
    from aslms.core.config import get_settings

    return get_settings().napix_status_batch


def non_disposed_cnrs(session: Session, offset: int = 0, limit: int | None = None) -> list[str]:
    stmt = (
        select(Case.cnr)
        .where(Case.cnr.is_not(None), Case.status != CaseStatus.DISPOSED, Case.merged_into_case_id.is_(None))
        .order_by(Case.cnr)
        .offset(offset)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt).all())


def enqueue_status_batches(session: Session, run_date: date | None = None) -> int:
    """One `status_batch` row per block of `NAPIX_STATUS_BATCH` non-disposed CNRs."""
    run_date = run_date or today_ist()
    total = len(non_disposed_cnrs(session))
    n = 0
    size = batch_size()
    for i in range((total + size - 1) // size):
        if queue.enqueue(
            session, FetchKind.STATUS_BATCH, f"{run_date.isoformat()}:{i}", queue.PRIORITY["status"]
        ):
            n += 1
    return n


def never_fetched_refs(session: Session) -> list[str]:
    """Dossier refs of the non-merged cases never fully fetched (`last_full_refresh_at IS NULL`), whatever their
    status: the CNR when there is one, else `<est_code>|<case number as printed>` (resolved by the runner through
    Search by Case Number; no identifier is made up); cases with neither are left out (decision 9)."""
    rows = session.execute(
        select(Case.cnr, Court.est_code, Case.case_no_text)
        .join(Court, Court.id == Case.court_id)
        .where(Case.last_full_refresh_at.is_(None), Case.merged_into_case_id.is_(None))
        .order_by(Case.created_at)
    ).all()
    refs: list[str] = []
    for cnr, est, case_no in rows:
        if cnr:
            refs.append(cnr)
        elif case_no and case_no.strip():
            refs.append(f"{est}|{case_no.strip()}")
    return refs


def enqueue_first_fetches(session: Session) -> int:
    """The Sunday job's dossiers (design `rolling-case-refresh`, decision 14): every case never fully fetched
    (`never_fetched_refs`: the CNR or `<est_code>|<case number>`, never a made-up reference), priority 50, lane daily,
    `requeue` and `as_new` (a finished row comes back at 50 with a fresh `created_at`). Fetched cases are the nightly
    refresh's. Returns the count queued."""
    n = 0
    for ref in dict.fromkeys(never_fetched_refs(session)):
        if queue.enqueue(
            session,
            FetchKind.DOSSIER,
            ref,
            queue.PRIORITY["dossier_refetch"],
            requeue=True,
            lane=FetchLane.DAILY,
            as_new=True,
        ):
            n += 1
    return n


# ------------------------------------------------------------------------------------------------ the nightly refresh
# design rolling-case-refresh, decisions 1-9

ROUTINE_DAYS = 7  # decision 2: due at an age of 7 IST dates
EARLY_FROM_AGE = 4  # decision 4: a case of age 4 to 6 may be refreshed early to level a clump
LEVEL_NIGHTS = 3  # decision 4: the quota looks 3 nights ahead
FOLLOWUP_STEPS = (3, 7, 14, 30)  # decision 9
FOLLOWUP_LAST_DAY = 37  # days 31 to 37 only catch up a missed 30-day step
FAILED_PAUSE = timedelta(days=7)  # decision 7


def refreshed_on():
    """The IST date of the case's last full record, as SQL."""
    return func.date(func.timezone("Asia/Kolkata", Case.last_full_refresh_at))


def refresh_age(d: date):
    """Decision 2: the age of the last full record in IST dates on the run date `d` (`d - IST date`), as SQL."""
    return type_coerce(literal(d, Date) - refreshed_on(), Integer)


def eligible_conditions() -> list:
    """Decision 1: every fetched case not disposed (the status check's own set, `unknown` included), CNR held, not
    merged, fully fetched at least once."""
    return [
        Case.status != CaseStatus.DISPOSED,
        Case.cnr.is_not(None),
        Case.merged_into_case_id.is_(None),
        Case.last_full_refresh_at.is_not(None),
    ]


def recently_failed(now: datetime | None = None):
    """Decision 7: the case's `dossier` row is `failed` and finished in the last 7 days (it used its six attempts)."""
    now = now or datetime.now(UTC)
    return exists().where(
        FetchQueueItem.kind == FetchKind.DOSSIER,
        FetchQueueItem.ref == Case.cnr,
        FetchQueueItem.status == FetchStatus.FAILED,
        FetchQueueItem.finished_at > now - FAILED_PAUSE,
    )


def _claimed():
    from aslms.services.next_dates import claimed_condition

    return claimed_condition()


@dataclass(frozen=True)
class RollingPlan:
    """Decisions 4 and 5: `due` (age 7 or more), the night's `quota` (bounded by `cap`; 0 switches the refresh off)
    and `over_cap` (more cases due than the cap allows)."""

    due: int
    quota: int
    cap: int
    over_cap: bool


def rolling_quota(counts_by_age: dict[int, int], cap: int) -> RollingPlan:
    """Decision 4: `Q = max over k = 0..3 of ceil(N_k / (k + 1))`, `N_k` the cases of age 7 - k or more; bounded by the
    cap (decision 5). Q is never below the due count unless capped; a cap of 0 gives 0."""

    def n_k(k: int) -> int:
        return sum(n for age, n in counts_by_age.items() if age >= ROUTINE_DAYS - k)

    due = n_k(0)
    level = max(math.ceil(n_k(k) / (k + 1)) for k in range(LEVEL_NIGHTS + 1))
    if cap <= 0:
        return RollingPlan(due=due, quota=0, cap=0, over_cap=False)
    return RollingPlan(due=due, quota=min(level, cap), cap=cap, over_cap=due > cap)


def counts_by_age(session: Session, d: date, now: datetime | None = None) -> dict[int, int]:
    """The selectable cases (eligible, not recently failed) by age on `d`; a case refreshed after `d` counts as 0."""
    day = refreshed_on()
    rows = session.execute(
        select(day, func.count()).where(*eligible_conditions(), ~recently_failed(now)).group_by(day)
    ).all()
    out: dict[int, int] = {}
    for on, n in rows:
        age = max(0, (d - on).days)
        out[age] = out.get(age, 0) + int(n)
    return out


def rolling_refresh_refs(
    session: Session, d: date, plan: RollingPlan, now: datetime | None = None
) -> list[tuple[str, int]]:
    """Decisions 3 and 4: due claimed (56), due unclaimed (57), then early (age 4 to 6) claimed (58) and early
    unclaimed (59), each oldest `last_full_refresh_at` first (then CNR), up to the quota. `(cnr, priority)` pairs."""
    day = refreshed_on()
    due = day <= d - timedelta(days=ROUTINE_DAYS)
    early = (day > d - timedelta(days=ROUTINE_DAYS)) & (day <= d - timedelta(days=EARLY_FROM_AGE))
    groups = (
        (due, True, queue.PRIORITY["dossier_routine_claimed"]),
        (due, False, queue.PRIORITY["dossier_routine"]),
        (early, True, queue.PRIORITY["dossier_early_claimed"]),
        (early, False, queue.PRIORITY["dossier_early"]),
    )
    out: list[tuple[str, int]] = []
    for when, claimed, priority in groups:
        left = plan.quota - len(out)
        if left <= 0:
            break
        claim = _claimed()
        stmt = (
            select(Case.cnr)
            .where(*eligible_conditions(), ~recently_failed(now), when, claim if claimed else ~claim)
            .order_by(Case.last_full_refresh_at, Case.cnr)
            .limit(left)
        )
        out.extend((cnr, priority) for cnr in session.scalars(stmt).all())
    return out


def followup_step(d: date, heard: date | None, refreshed: date | None) -> int | None:
    """Decision 9, pure: the follow-up step due on `d` for a hearing on `heard` and a last full record dated
    `refreshed`, or None. The step is the largest of 3, 7, 14, 30 not above `d - heard` (days 3 to 37); it is due while
    the last full record is dated before `heard + step` (any refresh on or after the step's day satisfies it). The
    order condition is the SQL's (`followup_condition`)."""
    if heard is None:
        return None
    days = (d - heard).days
    if days < FOLLOWUP_STEPS[0] or days > FOLLOWUP_LAST_DAY:
        return None
    step = max(s for s in FOLLOWUP_STEPS if s <= days)
    if refreshed is not None and refreshed >= heard + timedelta(days=step):
        return None
    return step


def followup_condition(d: date, now: datetime | None = None) -> list:
    """Decision 9 as SQL over `cases` (one function, so row 221 can reuse the trigger): eligible (decision 1), not
    recently failed (decision 7), the court's own last hearing `H` 3 to 37 days before `d`, no `orders` row of the
    case dated on or after `H`, and the last full record dated before `H + step`."""
    heard = Case.last_hearing_date
    days = type_coerce(literal(d, Date) - heard, Integer)
    step = sa_case(
        (days >= FOLLOWUP_STEPS[3], FOLLOWUP_STEPS[3]),
        (days >= FOLLOWUP_STEPS[2], FOLLOWUP_STEPS[2]),
        (days >= FOLLOWUP_STEPS[1], FOLLOWUP_STEPS[1]),
        else_=FOLLOWUP_STEPS[0],
    )
    return [
        *eligible_conditions(),
        ~recently_failed(now),
        *_heard_waiting(d),
        refreshed_on() < heard + step,
    ]


def _heard_waiting(d: date) -> list:
    """The court's own last hearing 3 to 37 days before `d` and no order of the case dated on or after it."""
    from aslms.domain.documents import Order

    heard = Case.last_hearing_date
    return [
        heard.is_not(None),
        heard <= d - timedelta(days=FOLLOWUP_STEPS[0]),
        heard >= d - timedelta(days=FOLLOWUP_LAST_DAY),
        ~exists().where(Order.case_id == Case.id, Order.order_date >= heard),
    ]


def followup_refs(session: Session, d: date, now: datetime | None = None) -> list[str]:
    """The CNRs of the cases in follow-up on `d`, oldest hearing first."""
    return list(
        session.scalars(
            select(Case.cnr).where(*followup_condition(d, now)).order_by(Case.last_hearing_date, Case.cnr)
        ).all()
    )


def enqueue_nightly_refresh(
    session: Session,
    d: date | None = None,
    settings=None,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """The 22:00 IST job (decision 8): the hearing follow-ups at 50, then the routine pairs of `rolling_refresh_refs`,
    each `queue.enqueue(DOSSIER, cnr, p, requeue=True, lane=DAILY, as_new=True)` (a finished row comes back at its
    refresh priority with a fresh `created_at`; a pending or running row keeps the better priority); a CNR already
    queued as a follow-up is skipped. `ROLLING_REFRESH_DAILY_MAX` of 0 switches the job off (nothing is queued). With
    `dry_run` nothing is written and `queued` is what would be queued. Returns `{eligible, due, due_claimed,
    due_unclaimed, early_claimed, early_unclaimed, quota, cap, over_cap, followups, queued}`."""
    from aslms.core.config import get_settings

    cfg = settings or get_settings()
    now = now or datetime.now(UTC)
    d = d or today_ist(now)
    eligible = int(session.scalar(select(func.count()).select_from(Case).where(*eligible_conditions())) or 0)
    plan = rolling_quota(counts_by_age(session, d, now), int(cfg.rolling_refresh_daily_max))
    on = plan.cap > 0
    followups = followup_refs(session, d, now) if on else []
    in_followup = set(followups)
    pairs = (
        [(c, p) for c, p in rolling_refresh_refs(session, d, plan, now) if c not in in_followup] if on else []
    )
    by_priority = dict.fromkeys(queue.ROUTINE_PRIORITIES, 0)
    for _, p in pairs:
        by_priority[p] += 1
    out: dict[str, Any] = {
        "eligible": eligible,
        "due": plan.due,
        "due_claimed": by_priority[queue.PRIORITY["dossier_routine_claimed"]],
        "due_unclaimed": by_priority[queue.PRIORITY["dossier_routine"]],
        "early_claimed": by_priority[queue.PRIORITY["dossier_early_claimed"]],
        "early_unclaimed": by_priority[queue.PRIORITY["dossier_early"]],
        "quota": plan.quota,
        "cap": plan.cap,
        "over_cap": plan.over_cap,
        "followups": len(followups),
    }
    if dry_run:
        out["queued"] = len(followups) + len(pairs)
        out["dry_run"] = True
        return out
    queued = 0
    work = [(cnr, queue.PRIORITY["dossier_refetch"]) for cnr in followups] + pairs
    for cnr, priority in work:
        if queue.enqueue(
            session, FetchKind.DOSSIER, cnr, priority, requeue=True, lane=FetchLane.DAILY, as_new=True
        ):
            queued += 1
    out["queued"] = queued
    return out


def pending_count(session: Session) -> int:
    """The schedule's `pending`: every case not disposed, CNR held, not merged (fetched or not)."""
    return int(
        session.scalar(
            select(func.count())
            .select_from(Case)
            .where(
                Case.status != CaseStatus.DISPOSED,
                Case.cnr.is_not(None),
                Case.merged_into_case_id.is_(None),
            )
        )
        or 0
    )


def not_refreshed_count(session: Session, d: date, days: int = ROUTINE_DAYS + 1) -> int:
    """Decision 20: the eligible cases whose last full record is `days` (8) or more IST dates old on `d`; 0 while the
    nightly refresh keeps up."""
    return int(
        session.scalar(
            select(func.count())
            .select_from(Case)
            .where(*eligible_conditions(), refreshed_on() <= d - timedelta(days=days))
        )
        or 0
    )


def heard_waiting_count(session: Session, d: date) -> int:
    """Decision 20: the eligible cases heard 3 to 37 days before `d` with no order dated on or after the hearing."""
    return int(
        session.scalar(
            select(func.count()).select_from(Case).where(*eligible_conditions(), *_heard_waiting(d))
        )
        or 0
    )


def disposal_day():
    """The disposal day of a case as SQL: `disposal_date`, else the IST date ASLMS first saw the disposal (some court
    records give `D` without `date_of_decision`; decision 3)."""
    return func.coalesce(Case.disposal_date, func.date(func.timezone("Asia/Kolkata", Case.closed_at)))


def disposed_window(today: date, keep_days: int) -> list:
    """The cases inside the year window (decision 3): disposed, CNR held, not merged, fully fetched at least once (a
    case never fully fetched is the Sunday job's), disposed within the last `keep_days` IST days counting today (a
    disposal date later than today counts as today)."""
    day = func.least(disposal_day(), today)
    return [
        Case.status == CaseStatus.DISPOSED,
        Case.cnr.is_not(None),
        Case.merged_into_case_id.is_(None),
        Case.last_full_refresh_at.is_not(None),
        disposal_day().is_not(None),
        day > today - timedelta(days=keep_days),
    ]


def _due(now: datetime, every_days: int):
    return Case.last_full_refresh_at < now - timedelta(days=every_days)


def disposed_refresh_refs(
    session: Session,
    today: date,
    *,
    keep_days: int,
    every_days: int,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[str]:
    """The CNRs of the cases of the window last refreshed more than `every_days` ago, oldest `last_full_refresh_at`
    first (decision 3)."""
    now = now or datetime.now(UTC)
    stmt = (
        select(Case.cnr)
        .where(*disposed_window(today, keep_days), _due(now, every_days))
        .order_by(Case.last_full_refresh_at, Case.cnr)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt).all())


def disposed_refresh_cap(eligible: int, daily_max: int, every_days: int = 28) -> int:
    """`min(DISPOSED_REFRESH_DAILY_MAX, ceil(eligible / 28))` (decision 3); a maximum of 0 switches the job off."""
    if daily_max <= 0 or eligible <= 0:
        return 0
    return min(daily_max, math.ceil(eligible / max(1, every_days)))


def disposed_eligible_count(session: Session, today: date, *, keep_days: int) -> int:
    """The cases of the window whatever their last refresh: the base of the cap."""
    return int(
        session.scalar(select(func.count()).select_from(Case).where(*disposed_window(today, keep_days))) or 0
    )


def disposed_due_count(
    session: Session, today: date, *, keep_days: int, every_days: int, now: datetime | None = None
) -> int:
    """The cases of the window due their refresh now (data health)."""
    now = now or datetime.now(UTC)
    return int(
        session.scalar(
            select(func.count())
            .select_from(Case)
            .where(*disposed_window(today, keep_days), _due(now, every_days))
        )
        or 0
    )


def enqueue_disposed_refresh(
    session: Session, today: date | None = None, settings=None, *, now: datetime | None = None
) -> dict[str, int]:
    """Decision 1-3: a dossier row (priority 55, lane daily, `requeue`) for each due disposed case, oldest refresh
    first, at most `min(DISPOSED_REFRESH_DAILY_MAX, ceil(eligible / 28))`. A done (or failed) row of the case is
    revived `as_new`, at 55 in the daily lane with a fresh `created_at`, so it never keeps the 40-48 of its first fetch
    and runs after every live kind; a pending row keeps its own better priority. Returns `{eligible, due, cap, queued}`."""
    from aslms.core.config import get_settings

    cfg = settings or get_settings()
    today = today or today_ist(now)
    eligible = disposed_eligible_count(session, today, keep_days=cfg.disposed_refresh_days)
    cap = disposed_refresh_cap(eligible, cfg.disposed_refresh_daily_max, 28)
    due_refs = disposed_refresh_refs(
        session,
        today,
        keep_days=cfg.disposed_refresh_days,
        every_days=cfg.disposed_refresh_every_days,
        now=now,
    )
    queued = 0
    for cnr in due_refs[:cap]:
        if queue.enqueue(
            session,
            FetchKind.DOSSIER,
            cnr,
            queue.PRIORITY["dossier_disposed"],
            requeue=True,
            lane=FetchLane.DAILY,
            as_new=True,
        ):
            queued += 1
    return {"eligible": eligible, "due": len(due_refs), "cap": cap, "queued": queued}


@dataclass
class BatchReport:
    ref: str
    requested: int = 0
    answered: int = 0
    changed: int = 0
    refetch_queued: int = 0
    unknown: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "unknown": self.unknown[:20]}


async def run_status_batch(session: Session, hc: NapixHighCourt, ref: str) -> BatchReport:
    _day, _, n = ref.partition(":")
    size = batch_size()
    offset = int(n or 0) * size
    cnrs = non_disposed_cnrs(session, offset=offset, limit=size)
    report = BatchReport(ref=ref, requested=len(cnrs))
    if not cnrs:
        return report
    blocks = await hc.current_status(cnrs)
    by_cnr = {as_text(b.get("cino"), 16).upper(): b for b in blocks if as_text(b.get("cino"))}
    for cnr in cnrs:
        block = by_cnr.get(cnr)
        if block is None:
            report.unknown.append(cnr)
            continue
        report.answered += 1
        case = session.scalar(select(Case).where(Case.cnr == cnr))
        if case is None:
            continue
        rep = apply_status(session, case, block)
        if rep.changed:
            report.changed += 1
            record_status_change(session, case, rep.status_changes)
            # design rolling-case-refresh, decision 13: a finished row comes back at 50 with a fresh `created_at`
            if queue.enqueue(
                session,
                FetchKind.DOSSIER,
                cnr,
                queue.PRIORITY["dossier_refetch"],
                requeue=True,
                lane=FetchLane.DAILY,
                as_new=True,
            ):
                report.refetch_queued += 1
    session.flush()
    return report


def record_status_change(session: Session, case: Case, changes: dict[str, tuple[Any, Any]]) -> None:
    """`next_dates` row and the events a change in the tracked fields produces."""
    payload = {
        k: [str(a) if a is not None else None, str(b) if b is not None else None]
        for k, (a, b) in changes.items()
    }
    if "next_hearing_date" in changes and case.next_hearing_date is not None:
        exists = session.scalar(
            select(NextDate.id).where(
                NextDate.case_id == case.id,
                NextDate.next_date == case.next_hearing_date,
                NextDate.source == NextDateSource.CURRENT_STATUS,
                NextDate.order_id.is_(None),
            )
        )
        if exists is None:
            session.add(
                NextDate(
                    case_id=case.id,
                    next_date=case.next_hearing_date,
                    source=NextDateSource.CURRENT_STATUS,
                    confidence=1.0,
                    review_status=ReviewStatus.NOT_NEEDED,
                )
            )
        emit_event(
            session,
            EventType.NEXT_DATE_CHANGED,
            case,
            {"cnr": case.cnr, **payload},
            dedupe=f"next_date_changed:{case.cnr}:{case.next_hearing_date}",
        )
    if "status" in changes:
        kind = EventType.CASE_DISPOSED if case.status == CaseStatus.DISPOSED else EventType.STATUS_CHANGED
        extra: dict[str, Any] = {}
        if case.status == CaseStatus.PENDING:
            # design close-case, decision 11: the department's closure reopens before the event is emitted
            from aslms.services import case_closure

            if case_closure.reopen_on_court_status(session, case, previous_status=changes["status"][0]):
                extra["reopened"] = True
        emit_event(
            session,
            kind,
            case,
            {"cnr": case.cnr, **payload, **extra},
            dedupe=f"{kind.value}:{case.cnr}:{case.status.value}:{case.disposal_date}",
        )
    elif set(changes) - {"next_hearing_date"}:
        emit_event(session, EventType.STATUS_CHANGED, case, {"cnr": case.cnr, **payload})
