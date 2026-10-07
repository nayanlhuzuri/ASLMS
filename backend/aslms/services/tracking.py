"""Pipeline stage 4: keeping cases current. Current Status takes up to `NAPIX_STATUS_BATCH` CNRs per call (250 by
default: the gateway refuses longer query strings with HTTP 414, see napix_integration_notes.md §7), so the daily
refresh of every non-disposed case is a handful of `status_batch` queue rows (`<YYYY-MM-DD>:<n>` = the n-th block of
`NAPIX_STATUS_BATCH`
non-disposed CNRs in CNR order on that day). A change in a tracked field updates the case, writes a
`next_dates` row and an event, and queues a dossier re-fetch. The weekly sweep queues a dossier re-fetch for
every pending case regardless."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.domain.alerts import NextDate, NextDateSource, ReviewStatus
from aslms.domain.cases import Case, CaseStatus
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
    run_date = run_date or date.today()
    total = len(non_disposed_cnrs(session))
    n = 0
    size = batch_size()
    for i in range((total + size - 1) // size):
        if queue.enqueue(
            session, FetchKind.STATUS_BATCH, f"{run_date.isoformat()}:{i}", queue.PRIORITY["status"]
        ):
            n += 1
    return n


def enqueue_weekly_dossier_sweep(session: Session) -> int:
    n = 0
    for cnr in non_disposed_cnrs(session):
        if queue.enqueue(session, FetchKind.DOSSIER, cnr, queue.PRIORITY["dossier_refetch"], requeue=True):
            n += 1
    return n


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
