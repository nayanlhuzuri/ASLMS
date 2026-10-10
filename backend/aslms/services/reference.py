"""Reference labels for the portal (design `portal-shell`, decision 16a): the user types, office kinds and ticket
kinds from their `ref_*` tables, so the portal shows the database's labels instead of a copy, and the user types
the caller may assign (the server still decides on every write). Reads only; no audit row."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.domain.org import User
from aslms.domain.reference import Permission, RefOfficeKind, RefRole, RefTicketKind, Role
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
    }
