"""Pipeline stage 4: keeping cases current. Current Status takes up to `NAPIX_STATUS_BATCH` CNRs per call (250 by
default: the gateway refuses longer query strings with HTTP 414, see napix_integration_notes.md §7), so the daily
refresh of every non-disposed case is a handful of `status_batch` queue rows (`<YYYY-MM-DD>:<n>` = the n-th block of
`NAPIX_STATUS_BATCH`
non-disposed CNRs in CNR order on that day). A change in a tracked field updates the case, writes a
`next_dates` row and an event, and queues a dossier re-fetch. The weekly sweep queues a dossier re-fetch for
every pending case regardless, and a first fetch for every case never fully fetched whatever its status (design
`safety-fixes`, decision 9). A disposed case is refreshed monthly for a year after its disposal (design
`court-data-freshness`, decisions 1-6): the 02:30 IST job queues the due ones, oldest refresh first, capped."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aslms.core.clock import today_ist
from aslms.domain.alerts import NextDate, NextDateSource, ReviewStatus
from aslms.domain.cases import Case, CaseStatus
from aslms.domain.courts import Court
from aslms.domain.ops import FetchKind
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


def enqueue_weekly_dossier_sweep(session: Session) -> int:
    """The non-disposed CNRs plus every case never fully fetched (decision 9), priority 50, lane daily, `requeue`
    (failed and skipped rows are revived with zero attempts). Returns the count queued."""
    n = 0
    refs = dict.fromkeys(non_disposed_cnrs(session))
    refs.update(dict.fromkeys(never_fetched_refs(session)))
    for ref in refs:
        if queue.enqueue(session, FetchKind.DOSSIER, ref, queue.PRIORITY["dossier_refetch"], requeue=True):
            n += 1
    return n


def disposal_day():
    """The disposal day of a case as SQL: `disposal_date`, else the IST date ASLMS first saw the disposal (some court
    records give `D` without `date_of_decision`; decision 3)."""
    return func.coalesce(Case.disposal_date, func.date(func.timezone("Asia/Kolkata", Case.closed_at)))


def disposed_window(today: date, keep_days: int) -> list:
    """The cases inside the year window (decision 3): disposed, CNR held, not merged, fully fetched at least once (a
    case never fully fetched is the Sunday sweep's), disposed within the last `keep_days` IST days counting today (a
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
    from aslms.domain.ops import FetchLane

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
            if queue.enqueue(
                session, FetchKind.DOSSIER, cnr, queue.PRIORITY["dossier_refetch"], requeue=True
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
        emit_event(
            session,
            kind,
            case,
            {"cnr": case.cnr, **payload},
            dedupe=f"{kind.value}:{case.cnr}:{case.status.value}:{case.disposal_date}",
        )
    elif set(changes) - {"next_hearing_date"}:
        emit_event(session, EventType.STATUS_CHANGED, case, {"cnr": case.cnr, **payload})
