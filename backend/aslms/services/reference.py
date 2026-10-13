"""Reference labels for the portal (design `portal-shell`, decision 16a): the user types, office kinds and ticket
kinds (and alert kinds, design `portal-workflow`, decision 20f) from their `ref_*` tables, so the portal shows the database's labels instead of a copy, and the user types
the caller may assign (the server still decides on every write); the High Court's case types (design
`portal-cases`, decision 14e). Reads only; no audit row."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aslms.core.config import get_settings
from aslms.domain.causelists import Causelist, CauselistEntry
from aslms.domain.courts import CaseType, Court
from aslms.domain.org import User
from aslms.domain.reference import (
    Permission,
    RefAlertKind,
    RefOfficeKind,
    RefRole,
    RefTicketKind,
    Role,
)
from aslms.services import access
from aslms.services.case_filters import bench_sql
from aslms.services.reporting_common import today_ist


def assignable_types(session: Session, user: User) -> set[Role]:
    """The super admin: every type but `super_admin`; a holder of `users.create` or `users.set_type`: the
    delegable types; anyone else: none."""
    if access.is_super_admin(user):
        return set(Role) - {Role.SUPER_ADMIN}
    if access.has(session, user, Permission.USERS_CREATE) or access.has(
        session, user, Permission.USERS_SET_TYPE
    ):
        return set(access.DELEGABLE_ROLES)
    return set()


def _rows(session: Session, model) -> list:
    return session.scalars(
        select(model).where(model.is_active.is_(True)).order_by(model.sort_order, model.code)
    ).all()


def labels(session: Session, user: User) -> dict:
    allowed = {r.value for r in assignable_types(session, user)}
    return {
        "user_types": [
            {"code": r.code, "label": r.label, "description": r.description, "assignable": r.code in allowed}
            for r in _rows(session, RefRole)
        ],
        "office_kinds": [{"code": r.code, "label": r.label} for r in _rows(session, RefOfficeKind)],
        "ticket_kinds": [{"code": r.code, "label": r.label} for r in _rows(session, RefTicketKind)],
        "alert_kinds": [{"code": r.code, "label": r.label} for r in _rows(session, RefAlertKind)],
    }


def case_types(session: Session, est_code: str | None = None) -> list[dict]:
    """The active case types of the High Court's `courts` row (`NAPIX_EST_CODE`), by short name then code.
    Master data, court-public; empty when the court is not seeded."""
    court = session.scalar(select(Court).where(Court.est_code == (est_code or get_settings().napix_est_code)))
    if court is None:
        return []
    rows = session.scalars(
        select(CaseType)
        .where(CaseType.court_id == court.id, CaseType.is_active.is_(True))
        .order_by(CaseType.short_name.asc().nulls_last(), CaseType.case_type_code)
    ).all()
    return [
        {
            "case_type_code": ct.case_type_code,
            "short_name": ct.short_name,
            "full_name": ct.full_name,
            "type_name": ct.type_name,
        }
        for ct in rows
    ]


BENCH_DAYS_DEFAULT = 90
BENCH_DAYS_MAX = 400


def _court_key(court_no: str) -> tuple:
    """Court numbers numerically (`2` before `10` before `111`), then the others as text."""
    return (0, int(court_no), "") if court_no.isdigit() else (1, 0, court_no)


def benches(session: Session, *, days: int = BENCH_DAYS_DEFAULT, today: date | None = None) -> dict:
    """The court numbers and bench texts seen in cause lists dated in the last `days` days up to today (IST),
    each with the last date it appeared and its entry count (design `portal-filters`, decision 12). Court
    numbers are trimmed and bench texts upper-cased with white space collapsed, as the filters match them.
    Court-public data, the same for every reader."""
    if not (1 <= int(days) <= BENCH_DAYS_MAX):
        raise ValueError(f"days is between 1 and {BENCH_DAYS_MAX}")
    to = today or today_ist()
    since = to - timedelta(days=int(days) - 1)
    window = (
        select(CauselistEntry.court_no, CauselistEntry.bench_text, Causelist.list_date)
        .join(Causelist, Causelist.id == CauselistEntry.causelist_id)
        .where(Causelist.list_date >= since, Causelist.list_date <= to)
        .subquery()
    )
    court = func.trim(window.c.court_no)
    courts = session.execute(
        select(court.label("court_no"), func.max(window.c.list_date), func.count())
        .where(window.c.court_no.is_not(None), court != "")
        .group_by(court)
    ).all()
    bench = func.trim(bench_sql(window.c.bench_text))
    bench_rows = session.execute(
        select(bench.label("text"), func.max(window.c.list_date), func.count())
        .where(window.c.bench_text.is_not(None), bench != "")
        .group_by(bench)
        .order_by(bench)
    ).all()
    return {
        "from": since,
        "to": to,
        "court_numbers": [
            {"court_no": c, "last_listed": last, "entries": int(n)}
            for c, last, n in sorted(courts, key=lambda r: _court_key(r[0]))
        ],
        "benches": [{"text": t, "last_listed": last, "entries": int(n)} for t, last, n in bench_rows],
    }
