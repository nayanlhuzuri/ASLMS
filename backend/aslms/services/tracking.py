"""Case tracker (plan §5.3, Table 4): Search by CNR on first sight and weekly; Current Status daily for all
tracked cases. All calls go through the NAPIX source; results are applied by `services.cases`."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from aslms.core.config import get_settings
from aslms.core.errors import IntegrationError, SourceNotFound
from aslms.core.time import now_utc
from aslms.domain.cases import Case, CaseStatus
from aslms.domain.ops import FailureKind
from aslms.services import cases as case_svc
from aslms.services import ops, ownership


def fetch_case(session: Session, source, case: Case) -> str:
    """Full CNR fetch for one case. Returns ok | not_found | failed."""
    try:
        rec = asyncio.run(source.case_by_cnr(case.cnr))
    except SourceNotFound:
        rec = None
    except IntegrationError as e:
        ops.record_failure(session, FailureKind.NAPIX, f"cnr:{case.cnr}", str(e))
        return "failed"
    if rec is None:
        case.last_full_refresh_at = now_utc()
        return "not_found"
    case_svc.apply_case_record(session, case, rec)
    ops.resolve_failure(session, FailureKind.NAPIX, f"cnr:{case.cnr}")
    ownership.rescore(session, case)
    return "ok"


def first_sight(session: Session, source, limit: int | None = None) -> dict[str, int]:
    """Cases seen in a cause list but never fetched by CNR."""
    limit = limit or get_settings().first_sight_batch
    cases = session.scalars(
        select(Case)
        .where(Case.cnr.isnot(None), Case.last_full_refresh_at.is_(None))
        .order_by(Case.created_at)
        .limit(limit)
    ).all()
    counts = {"ok": 0, "not_found": 0, "failed": 0}
    for c in cases:
        counts[fetch_case(session, source, c)] += 1
    return counts


def full_refresh(session: Session, source, limit: int = 500) -> dict[str, int]:
    """Weekly full refresh of tracked cases (and any not refreshed for FULL_REFRESH_DAYS)."""
    stale = now_utc() - timedelta(days=get_settings().full_refresh_days)
    cases = session.scalars(
        select(Case)
        .where(
            Case.cnr.isnot(None),
            Case.is_tracked.is_(True),
            or_(Case.last_full_refresh_at.is_(None), Case.last_full_refresh_at < stale),
        )
        .order_by(Case.last_full_refresh_at.asc().nulls_first())
        .limit(limit)
    ).all()
    counts = {"ok": 0, "not_found": 0, "failed": 0}
    for c in cases:
        counts[fetch_case(session, source, c)] += 1
    return counts


def status_refresh(session: Session, source) -> dict[str, int]:
    """Daily bulk Current Status for every tracked, pending case (≤500 CNRs per call inside the adapter)."""
    cases = {
        c.cnr: c
        for c in session.scalars(
            select(Case).where(
                Case.cnr.isnot(None), Case.is_tracked.is_(True), Case.status != CaseStatus.DISPOSED
            )
        )
    }
    counts = {"requested": len(cases), "changed": 0, "missing": 0, "failed": 0}
    if not cases:
        return counts
    try:
        records = asyncio.run(source.current_status(list(cases)))
    except IntegrationError as e:
        ops.record_failure(session, FailureKind.NAPIX, "current_status", str(e))
        counts["failed"] = len(cases)
        return counts
    seen = set()
    for st in records:
        case = cases.get(st.cnr)
        if case is None:
            continue
        seen.add(st.cnr)
        if case_svc.apply_status_record(session, case, st):
            counts["changed"] += 1
    counts["missing"] = len(set(cases) - seen)
    return counts
