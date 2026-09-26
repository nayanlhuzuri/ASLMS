"""Reports (plan §5.10): pending cases by department / court / age, hearings and disposals in a period, open
actions by office, and data-collection health. Exported as Excel (xlsx) or CSV; printing to PDF is done from
the browser. All report queries are filtered by the caller's case scope."""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from aslms.core.time import now_utc, today_ist
from aslms.domain.alerts import Alert, AlertStatus
from aslms.domain.cases import Case, CaseHearing, CaseStatus
from aslms.domain.causelists import CauseList, CauseListEntry, EntrySource
from aslms.domain.documents import Order
from aslms.domain.ops import JobRun, NapixCallLog, SourceFailure
from aslms.domain.org import Office
from aslms.domain.ownership import CaseOwnership, OwnershipRole, OwnershipStatus
from aslms.domain.reference import Court
from aslms.services.scope import Principal, case_scope_clause


def pending_by_department(session: Session, p: Principal) -> list[dict[str, Any]]:
    today = today_ist()
    age = func.coalesce(Case.registration_date, Case.filing_date, func.date(Case.created_at))
    rows = session.execute(
        select(
            func.coalesce(Office.code, "UNCLAIMED"),
            func.coalesce(Office.name, "Not claimed by any department"),
            func.count(func.distinct(Case.id)),
            func.count(func.distinct(case((age >= today - timedelta(days=365), Case.id)))),
            func.count(
                func.distinct(
                    case(
                        (
                            and_(age < today - timedelta(days=365), age >= today - timedelta(days=5 * 365)),
                            Case.id,
                        )
                    )
                )
            ),
            func.count(func.distinct(case((age < today - timedelta(days=5 * 365), Case.id)))),
        )
        .select_from(Case)
        .outerjoin(
            CaseOwnership,
            and_(
                CaseOwnership.case_id == Case.id,
                CaseOwnership.status == OwnershipStatus.ACTIVE,
                CaseOwnership.role == OwnershipRole.PRIMARY,
            ),
        )
        .outerjoin(Office, Office.id == CaseOwnership.office_id)
        .where(case_scope_clause(p), Case.status != CaseStatus.DISPOSED, Case.merged_into_case_id.is_(None))
        .group_by(Office.code, Office.name)
        .order_by(func.count(func.distinct(Case.id)).desc())
    )
    return [
        {"department": c, "name": n, "pending": t, "under_1y": a, "1_to_5y": b, "over_5y": o}
        for c, n, t, a, b, o in rows
    ]


def pending_by_court(session: Session, p: Principal) -> list[dict[str, Any]]:
    rows = session.execute(
        select(Court.name, func.coalesce(Case.case_type_text, "?"), func.count())
        .join(Court, Court.id == Case.court_id)
        .where(case_scope_clause(p), Case.status != CaseStatus.DISPOSED)
        .group_by(Court.name, Case.case_type_text)
        .order_by(Court.name, func.count().desc())
    )
    return [{"court": c, "case_type": t, "pending": n} for c, t, n in rows]


def hearings_and_disposals(session: Session, p: Principal, start: date, end: date) -> list[dict[str, Any]]:
    hearings = dict(
        session.execute(
            select(CaseHearing.business_date, func.count(func.distinct(CaseHearing.case_id)))
            .join(Case, Case.id == CaseHearing.case_id)
            .where(case_scope_clause(p), CaseHearing.business_date.between(start, end))
            .group_by(CaseHearing.business_date)
        ).all()
    )
    disposals = dict(
        session.execute(
            select(Case.disposal_date, func.count())
            .where(case_scope_clause(p), Case.disposal_date.between(start, end))
            .group_by(Case.disposal_date)
        ).all()
    )
    days = sorted(set(hearings) | set(disposals))
    return [
        {"date": d.isoformat(), "cases_heard": hearings.get(d, 0), "disposed": disposals.get(d, 0)}
        for d in days
    ]


def open_actions_by_office(session: Session, p: Principal) -> list[dict[str, Any]]:
    today_dt = now_utc()
    rows = session.execute(
        select(
            Office.code,
            Office.name,
            func.count(func.distinct(Alert.id)),
            func.count(func.distinct(case((Alert.due_at < today_dt, Alert.id)))),
        )
        .select_from(Alert)
        .join(Case, Case.id == Alert.case_id)
        .join(
            CaseOwnership,
            and_(
                CaseOwnership.case_id == Case.id,
                CaseOwnership.status == OwnershipStatus.ACTIVE,
                CaseOwnership.role == OwnershipRole.PRIMARY,
            ),
        )
        .join(Office, Office.id == CaseOwnership.office_id)
        .where(case_scope_clause(p), Alert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]))
        .group_by(Office.code, Office.name)
        .order_by(func.count(func.distinct(Alert.id)).desc())
    )
    return [{"office": c, "name": n, "open_alerts": t, "overdue": o} for c, n, t, o in rows]


def data_health(session: Session, days: int = 7) -> dict[str, Any]:
    since = now_utc() - timedelta(days=days)
    jobs = [
        {
            "job": j.job.value,
            "run_date": j.run_date.isoformat() if j.run_date else None,
            "status": j.status.value,
            "started_at": j.started_at.isoformat(),
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            "counters": j.counters,
            "error": j.error,
        }
        for j in session.scalars(
            select(JobRun).where(JobRun.started_at >= since).order_by(JobRun.started_at.desc()).limit(100)
        )
    ]
    calls = session.execute(
        select(
            NapixCallLog.api,
            func.count(),
            func.sum(case((NapixCallLog.ok, 1), else_=0)),
            func.avg(NapixCallLog.duration_ms),
        )
        .where(NapixCallLog.called_at >= since)
        .group_by(NapixCallLog.api)
    ).all()
    failures = [
        {
            "id": str(f.id),
            "kind": f.kind.value,
            "ref": f.ref,
            "error": f.error[:300],
            "attempts": f.attempts,
            "first_seen": f.first_seen.isoformat(),
            "last_seen": f.last_seen.isoformat(),
        }
        for f in session.scalars(
            select(SourceFailure)
            .where(SourceFailure.resolved_at.is_(None))
            .order_by(SourceFailure.last_seen.desc())
            .limit(200)
        )
    ]
    lists = session.execute(
        select(CauseList.list_date, CauseList.source, func.count(), func.sum(CauseList.entry_count))
        .where(CauseList.list_date >= (today_ist() - timedelta(days=days)))
        .group_by(CauseList.list_date, CauseList.source)
        .order_by(CauseList.list_date.desc())
    ).all()
    entries = session.execute(
        select(
            CauseListEntry.source, func.count(), func.sum(case((CauseListEntry.cnr.isnot(None), 1), else_=0))
        )
        .join(CauseList, CauseList.id == CauseListEntry.causelist_id)
        .where(CauseList.list_date >= (today_ist() - timedelta(days=days)))
        .group_by(CauseListEntry.source)
    ).all()
    orders = dict(
        session.execute(select(Order.download_status, func.count()).group_by(Order.download_status)).all()
    )
    return {
        "jobs": jobs,
        "napix_calls": [
            {"api": a, "calls": n, "ok": int(ok or 0), "avg_ms": int(avg or 0)} for a, n, ok, avg in calls
        ],
        "open_failures": failures,
        "cause_lists": [
            {"date": d.isoformat(), "source": s.value, "lists": n, "entries": int(e or 0)}
            for d, s, n, e in lists
        ],
        "entries_by_source": [
            {
                "source": s.value,
                "entries": n,
                "with_cnr": int(c or 0),
                "cnr_rate": round((c or 0) / n, 4) if n else 0,
            }
            for s, n, c in entries
        ],
        "orders": {k.value: v for k, v in orders.items()},
        "pdf_vs_napix": EntrySource.PDF_PARSE.value,
    }


REPORTS = {
    "pending-by-department": ("Pending cases by department", pending_by_department),
    "pending-by-court": ("Pending cases by court and case type", pending_by_court),
    "open-actions-by-office": ("Open and overdue actions by office", open_actions_by_office),
}


def to_csv(rows: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def to_xlsx(title: str, rows: list[dict[str, Any]]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([f"Generated {now_utc():%d-%m-%Y %H:%M} UTC"])
    ws.append([])
    if rows:
        ws.append([k.replace("_", " ").title() for k in rows[0]])
        for c in ws[4]:
            c.font = Font(bold=True)
        for r in rows:
            ws.append(list(r.values()))
        for col in ws.columns:
            width = max(len(str(c.value or "")) for c in col[3:]) if len(col) > 3 else 10
            ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 60)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
