"""Reference labels for the portal (design `portal-shell`, decision 16a): the user types, office kinds and ticket
kinds (and alert kinds, design `portal-workflow`, decision 20f) from their `ref_*` tables, so the portal shows the database's labels instead of a copy, and the user types
the caller may assign (the server still decides on every write); the High Court's case types (design
`portal-cases`, decision 14e). Reads only; no audit row."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.core.config import get_settings
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
