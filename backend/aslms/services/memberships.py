"""Memberships (design `user-memberships`): one login, several offices, each with its own designation and user
type. This module is the only writer of `user_memberships` and of the login's mirror columns (`users.office_id`,
`role`, `designation`, `designation_id` = the primary membership, decision 3).

- `add`, `update`, `end`, `reactivate`, `make_primary`, `lookup`: the API's membership actions, each checked
  with the acting membership (decision 8), audited (`membership.*`) and announced with a `user_updated` event.
- The admin types (decisions 13-15): exactly one active `super_admin` membership (written only by the CLI,
  `replace_super_admin`), one active `dept_admin` per department (changed only by the super admin's swap,
  `replace_department_admin`), at most one active `dept_head` per department (changed only through the
  head-change request, `apply_head_change`, called by `services/tickets.py`). The partial unique indexes refuse a
  racing second row; the services answer 409 with the same codes.
- The exit step (decisions 21-22): ending a membership that holds allotted cases or files needs a target officer
  for every item, chosen by the admin; `exit_preview` lists them with a fingerprint and `end` applies them in one
  transaction under the membership lock, then the case locks in case-id order."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aslms.core.clock import today_ist
from aslms.domain.alerts import Alert, AlertStatus, Notification
from aslms.domain.cases import Case
from aslms.domain.courts import Court
from aslms.domain.events import Event, EventVisibility
from aslms.domain.org import Designation, Office, RefreshToken, User, UserMembership, UserPermission
from aslms.domain.ownership import CaseOwnership, OwnershipRole, OwnershipStatus
from aslms.domain.reference import EventType, Role
from aslms.domain.workflow import CaseNoteDraft, Custody, CustodyHistory, PendingAction
from aslms.services import access
from aslms.services.access import DELEGABLE_ROLES, NOT_OFFICERS, Conflict, Forbidden, Member
from aslms.services.audit import Actor, write_audit

MAX_REASON = 500
MAX_REMARK = 2000
DUE_DAYS_MAX = 365
INDEX_CODES = {
    "ix_user_memberships_one_per_department": "one_per_department",
    "ix_user_memberships_one_super_admin": "super_admin_single",
    "ix_user_memberships_one_dept_admin": "one_dept_admin",
    "ix_user_memberships_one_dept_head": "one_dept_head",
    "ix_user_memberships_primary": "primary_conflict",
}


class MembershipError(ValueError):
    """Bad input (HTTP 400). `code` is machine-readable."""

    def __init__(self, code: str, message: str | None = None, **extra: Any) -> None:
        super().__init__(message or code)
        self.code = code
        self.extra = extra


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET: Any = _Unset()


def _now() -> datetime:
    return datetime.now(UTC)


def _role(value: Role | str) -> Role:
    return value if isinstance(value, Role) else Role(value)


def _text(value: str | None, limit: int) -> str | None:
    s = (value or "").strip() or None
    return s[:limit] if s else None


# ------------------------------------------------------------------------------------------------ reading


def lookup(session: Session, email: str) -> User | None:
    """A login by exact e-mail (case-insensitive), for adding a membership to a person outside the actor's
    scope (decision 8)."""
    return session.scalar(select(User).where(User.email == (email or "").strip().lower()))


def memberships_of(session: Session, user: User, *, include_ended: bool = False) -> list[UserMembership]:
    stmt = select(UserMembership).where(UserMembership.user_id == user.id)
    if not include_ended:
        stmt = stmt.where(UserMembership.is_active.is_(True))
    return list(
        session.scalars(
            stmt.order_by(
                UserMembership.is_active.desc(),
                UserMembership.is_primary.desc(),
                UserMembership.created_at,
                UserMembership.id,
            )
        ).all()
    )


def summary(session: Session, m: UserMembership) -> dict[str, Any]:
    office = session.get(Office, m.office_id)
    dept = session.get(Office, m.department_id) if m.department_id else None
    return {
        "membership_id": str(m.id),
        "user_id": str(m.user_id),
        "office_code": office.code if office else None,
        "department_code": dept.code if dept else None,
        "designation": m.designation,
        "role": _role(m.role).value,
        "is_primary": m.is_primary,
        "is_active": m.is_active,
    }


def membership_out(session: Session, m: UserMembership, *, functions: bool = False) -> dict[str, Any]:
    office = session.get(Office, m.office_id)
    dept = session.get(Office, m.department_id) if m.department_id else None
    out: dict[str, Any] = {
        "id": m.id,
        "office": {"code": office.code, "name": office.name, "kind": str(office.kind.value)},
        "department_code": dept.code if dept else None,
        "designation": m.designation,
        "designation_id": m.designation_id,
        "role": _role(m.role).value,
        "is_primary": m.is_primary,
        "is_active": m.is_active,
        "valid_from": m.valid_from,
        "valid_to": m.valid_to,
        "end_reason": m.end_reason,
    }
    if functions:
        out["functions"] = sorted(p.value for p in access.membership_functions(session, m))
    return out


def head_of(session: Session, department: Office) -> UserMembership | None:
    return session.scalar(
        select(UserMembership).where(
            UserMembership.department_id == department.id,
            UserMembership.role == Role.DEPT_HEAD,
            UserMembership.is_active.is_(True),
        )
    )


def admin_of(session: Session, department: Office) -> UserMembership | None:
    return session.scalar(
        select(UserMembership).where(
            UserMembership.department_id == department.id,
            UserMembership.role == Role.DEPT_ADMIN,
            UserMembership.is_active.is_(True),
        )
    )


def super_admin_membership(session: Session) -> UserMembership | None:
    return session.scalar(
        select(UserMembership).where(
            UserMembership.role == Role.SUPER_ADMIN, UserMembership.is_active.is_(True)
        )
    )


def state_root(session: Session) -> Office:
    return session.scalar(select(Office).where(Office.parent_id.is_(None)).order_by(Office.path))


# ------------------------------------------------------------------------------------------------ writing helpers


def write_mirror(user: User, m: UserMembership) -> None:
    """Decision 3: the login's four mirror columns follow its primary membership."""
    user.office_id = m.office_id
    user.role = _role(m.role)
    user.designation = m.designation
    user.designation_id = m.designation_id


def _event(session: Session, m: UserMembership, change: str, office_code: str | None) -> None:
    key = f"membership:{m.id}:{change}:{uuid.uuid4()}"
    session.add(
        Event(
            type=EventType.USER_UPDATED,
            payload={
                "user_id": str(m.user_id),
                "membership_id": str(m.id),
                "office_code": office_code,
                "change": change,
            },
            dedupe_key=key,
            visibility=EventVisibility.SCOPED,
        )
    )


def _flush(session: Session) -> None:
    """Flush in a savepoint; a race on one of the partial unique indexes becomes a 409 with its code."""
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        text = str(exc.orig)
        code = next((c for name, c in INDEX_CODES.items() if name in text), None)
        if code is None:
            raise
        raise Conflict(code, f"another membership change happened at the same time ({code})") from exc


def _lock(session: Session, m: UserMembership) -> None:
    session.execute(select(UserMembership.id).where(UserMembership.id == m.id).with_for_update())
    session.refresh(m)


def _designation(session: Session, designation_id: uuid.UUID | None) -> uuid.UUID | None:
    if designation_id is not None and session.get(Designation, designation_id) is None:
        raise MembershipError("bad_field", "unknown designation")
    return designation_id


def check_type_limits(
    session: Session,
    user: User,
    office: Office,
    role: Role,
    *,
    exclude: UserMembership | None = None,
) -> Office | None:
    """The one-per-department rule and the admin-type limits for an active membership of `user` at `office`
    of type `role` (decisions 2, 4, 13-15). Returns the department."""
    dept = access.department_of(session, office)
    others = [m for m in access.active_memberships(session, user) if exclude is None or m.id != exclude.id]
    if any(_role(m.role) == Role.SUPER_ADMIN for m in others):
        raise Conflict("super_admin_single", "the super admin holds no other membership")
    if role == Role.SUPER_ADMIN and others:
        raise Conflict("super_admin_single", "the super admin holds no other membership")
    same = [m for m in others if m.department_id == (dept.id if dept else None)]
    if same:
        raise Conflict(
            "one_per_department",
            "the person already has an active membership in this department; change that one instead",
            membership_id=str(same[0].id),
        )
    if role == Role.DEPT_ADMIN:
        if dept is None or dept.id != office.id:
            raise MembershipError("admin_at_department", "a department admin sits at the department office")
        current = admin_of(session, dept)
        if current is not None and (exclude is None or current.id != exclude.id):
            raise Conflict("one_dept_admin", f"{dept.code} already has a department admin; use the swap")
    if role == Role.DEPT_HEAD:
        if dept is None or dept.id != office.id:
            raise MembershipError("head_at_department", "a department head sits at the department office")
        current = head_of(session, dept)
        if current is not None and (exclude is None or current.id != exclude.id):
            raise Conflict("one_dept_head", f"{dept.code} already has a head")
    if role == Role.SUPER_ADMIN:
        current = super_admin_membership(session)
        if current is not None and (exclude is None or current.id != exclude.id):
            raise Conflict("super_admin_single", "there is already a super admin")
    return dept


def insert_membership(
    session: Session,
    actor: Actor,
    user: User,
    *,
    office: Office,
    role: Role | str,
    designation: str | None = None,
    designation_id: uuid.UUID | None = None,
    ticket_ref: str | None = None,
    audit: bool = True,
) -> UserMembership:
    """Inserts an active membership after the limits (no authority check: callers check). It becomes the primary
    membership when the login has none (decision 22)."""
    role = _role(role)
    if not office.is_active:
        raise MembershipError("bad_field", f"the office {office.code} is inactive")
    dept = check_type_limits(session, user, office, role)
    has_primary = any(m.is_primary for m in access.active_memberships(session, user))
    m = UserMembership(
        user_id=user.id,
        office_id=office.id,
        department_id=dept.id if dept else None,
        role=role,
        designation=_text(designation, 200),
        designation_id=_designation(session, designation_id),
        is_primary=not has_primary,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    session.add(m)
    _flush(session)
    if m.is_primary:
        write_mirror(user, m)
        session.flush()
    if audit:
        after = summary(session, m)
        if ticket_ref:
            after["ticket_ref"] = ticket_ref
        write_audit(session, actor, "membership.added", "user_membership", m.id, after=after)
        _event(session, m, "added", office.code)
    return m


def _ensure_primary(session: Session, actor: Actor, user: User) -> UserMembership | None:
    """After an end: the oldest other active membership becomes primary (mirror rewritten); none left → the
    login keeps the last mirror values and has no membership (decision 22)."""
    active = access.active_memberships(session, user)
    if not active or any(m.is_primary for m in active):
        return next((m for m in active if m.is_primary), None)
    nxt = sorted(active, key=lambda m: (m.created_at, m.id))[0]
    nxt.is_primary = True
    _flush(session)
    write_mirror(user, nxt)
    session.flush()
    write_audit(
        session,
        actor,
        "membership.primary_changed",
        "user_membership",
        nxt.id,
        before=None,
        after=summary(session, nxt),
    )
    _event(session, nxt, "primary_changed", session.get(Office, nxt.office_id).code)
    return nxt


def _close(session: Session, m: UserMembership, reason: str | None) -> None:
    m.is_active = False
    m.is_primary = False
    m.deactivated_at = _now()
    m.valid_to = today_ist()
    m.end_reason = _text(reason, MAX_REASON)


def set_role(
    session: Session, actor: Actor, m: UserMembership, role: Role, *, ticket_ref: str | None = None
) -> UserMembership:
    """Changes a membership's type after the limits (no authority or head-route check: callers check)."""
    old = _role(m.role)
    if old == role:
        return m
    user = session.get(User, m.user_id)
    office = session.get(Office, m.office_id)
    check_type_limits(session, user, office, role, exclude=m)
    before = summary(session, m)
    m.role = role
    m.updated_by = actor.user_id
    _flush(session)
    if m.is_primary:
        write_mirror(user, m)
        session.flush()
    after = summary(session, m)
    if ticket_ref:
        after["ticket_ref"] = ticket_ref
    write_audit(session, actor, "membership.updated", "user_membership", m.id, before=before, after=after)
    _event(session, m, "type", office.code)
    return m


def reactivate_internal(
    session: Session,
    actor: Actor,
    m: UserMembership,
    *,
    role: Role | None = None,
    ticket_ref: str | None = None,
) -> UserMembership:
    if m.is_active:
        raise Conflict("membership_active", "the membership is active")
    user = session.get(User, m.user_id)
    office = session.get(Office, m.office_id)
    if not office.is_active:
        raise MembershipError("bad_field", f"the office {office.code} is inactive")
    new_role = role or _role(m.role)
    check_type_limits(session, user, office, new_role, exclude=m)
    before = summary(session, m)
    has_primary = any(x.is_primary for x in access.active_memberships(session, user))
    m.is_active, m.deactivated_at, m.valid_to, m.end_reason = True, None, None, None
    m.role = new_role
    m.is_primary = not has_primary
    m.updated_by = actor.user_id
    _flush(session)
    if m.is_primary:
        write_mirror(user, m)
        session.flush()
    after = summary(session, m)
    if ticket_ref:
        after["ticket_ref"] = ticket_ref
    write_audit(session, actor, "membership.reactivated", "user_membership", m.id, before=before, after=after)
    _event(session, m, "reactivated", office.code)
    return m


# ------------------------------------------------------------------------------------------------ the API actions


def _require_active_login(member: Member, user: User) -> None:
    """Decisions 8 and 13: only the super admin adds or reactivates a membership on a disabled login, so a
    department admin cannot make a dormant login primary in their office and then enable it or set its
    password (409 `login_inactive`)."""
    if not user.is_active and not member.is_super_admin:
        raise Conflict(
            "login_inactive", "the login is disabled; only the super admin can add a membership to it"
        )


def add(
    session: Session,
    actor: Actor,
    actor_user: User | Member,
    user: User,
    *,
    office: Office,
    role: Role | str,
    designation: str | None = None,
    designation_id: uuid.UUID | None = None,
) -> UserMembership:
    """Decision 8: a membership for an existing login, in an office the acting membership covers, of a
    delegable type (the super admin: any type but `super_admin`). `dept_head` only through the head-change
    request (409 `use_head_change`)."""
    role = _role(role)
    if role == Role.SUPER_ADMIN:
        raise Forbidden(
            "the super admin is created only from the server's command line", "super_admin_cli_only"
        )
    member = access.assert_can_manage(session, actor_user, "create", target_office=office, target_role=role)
    if role == Role.DEPT_HEAD:
        raise Conflict("use_head_change", "a department head is set through the head-change request")
    _require_active_login(member, user)
    return insert_membership(
        session,
        access.actor_as(actor, member),
        user,
        office=office,
        role=role,
        designation=designation,
        designation_id=designation_id,
    )


def update(
    session: Session,
    actor: Actor,
    actor_user: User | Member,
    m: UserMembership,
    *,
    designation: Any = UNSET,
    designation_id: Any = UNSET,
    role: Any = UNSET,
) -> UserMembership:
    """Decision 8: designation (`users.edit`) or type (`users.set_type`, between delegable types for anyone but
    the super admin). A type change to `dept_head` → 409 `use_head_change`; of the current head → 409
    `head_required`; to or from `super_admin` → 403 `super_admin_cli_only`; `dept_admin` only by the super
    admin, one per department."""
    if not m.is_active:
        raise Conflict("membership_ended", "the membership is ended; reactivate it first")
    office = session.get(Office, m.office_id)
    old = _role(m.role)
    if role is not UNSET and role is not None and _role(role) != old:
        new = _role(role)
        if Role.SUPER_ADMIN in (old, new):
            raise Forbidden(
                "the super admin is changed only from the server's command line", "super_admin_cli_only"
            )
        if old == Role.DEPT_HEAD:
            raise Conflict("head_required", "the head changes only through the head-change request")
        member = access.assert_can_manage(
            session, actor_user, "set_type", target_office=office, target_role=new
        )
        if not member.is_super_admin and old not in DELEGABLE_ROLES:
            raise Forbidden(
                f"only a super admin may change a membership of type {old.value}", "not_delegable"
            )
        if new == Role.DEPT_HEAD:
            raise Conflict("use_head_change", "a department head is set through the head-change request")
        if old == Role.DEPT_HEAD:
            raise Conflict("head_required", "the head changes only through the head-change request")
        set_role(session, access.actor_as(actor, member), m, new)
    changes: dict[str, Any] = {}
    if designation is not UNSET and designation is not None:
        changes["designation"] = _text(designation, 200)
    if designation_id is not UNSET and designation_id is not None:
        changes["designation_id"] = _designation(session, designation_id)
    if changes:
        if old == Role.SUPER_ADMIN:
            raise Forbidden(
                "the super admin is changed only from the server's command line", "super_admin_cli_only"
            )
        member = access.assert_can_manage(
            session, actor_user, "edit", target_office=office, target_role=m.role
        )
        before = summary(session, m)
        for k, v in changes.items():
            setattr(m, k, v)
        m.updated_by = actor.user_id
        session.flush()
        if m.is_primary:
            write_mirror(session.get(User, m.user_id), m)
            session.flush()
        write_audit(
            session,
            access.actor_as(actor, member),
            "membership.updated",
            "user_membership",
            m.id,
            before=before,
            after=summary(session, m),
        )
        _event(session, m, "designation", office.code)
    return m


def reactivate(
    session: Session, actor: Actor, actor_user: User | Member, m: UserMembership
) -> UserMembership:
    role = _role(m.role)
    if role == Role.SUPER_ADMIN:
        raise Forbidden(
            "the super admin is changed only from the server's command line", "super_admin_cli_only"
        )
    office = session.get(Office, m.office_id)
    member = access.assert_can_manage(
        session, actor_user, "enable_disable", target_office=office, target_role=role
    )
    if role == Role.DEPT_HEAD:
        raise Conflict("use_head_change", "a department head is set through the head-change request")
    _require_active_login(member, session.get(User, m.user_id))
    return reactivate_internal(session, access.actor_as(actor, member), m)


def make_primary(
    session: Session, actor: Actor, actor_user: User | Member, user: User, m: UserMembership
) -> UserMembership:
    """Decision 8: the super admin, or an actor whose scope (with `users.edit`) contains both the old and the
    new primary office."""
    if m.user_id != user.id or not m.is_active:
        raise MembershipError("bad_field", "the membership is not an active membership of this user")
    if m.is_primary:
        return m
    old = next((x for x in access.active_memberships(session, user) if x.is_primary), None)
    new_office = session.get(Office, m.office_id)
    member = access.assert_can_manage(session, actor_user, "edit", target_office=new_office)
    if not member.is_super_admin and old is not None:
        old_office = session.get(Office, old.office_id)
        if (
            access.acting_member_for_office(
                session, actor_user, old_office, permission=access.MANAGE_PERMISSIONS["edit"]
            )
            is None
        ):
            raise Forbidden("the current primary office is outside your offices")
    before = summary(session, old) if old else None
    if old is not None:
        old.is_primary = False
        session.flush()
    m.is_primary = True
    _flush(session)
    write_mirror(user, m)
    session.flush()
    write_audit(
        session,
        access.actor_as(actor, member),
        "membership.primary_changed",
        "user_membership",
        m.id,
        before=before,
        after=summary(session, m),
    )
    _event(session, m, "primary_changed", new_office.code)
    return m


def end(
    session: Session,
    actor: Actor,
    actor_user: User | Member,
    m: UserMembership,
    *,
    reason: str,
    assignments: list[dict[str, Any]] | None = None,
    items_fingerprint: str | None = None,
) -> ExitResult:
    """Decisions 8 and 21: end a membership with the per-item exit. `super_admin` → 403
    `super_admin_cli_only`; `dept_admin` → 403 for anyone but the super admin (who may leave a department
    without an admin, decision 14); the current head → 409 `head_required` (the head-change endpoint), for
    every caller."""
    role = _role(m.role)
    if role == Role.SUPER_ADMIN:
        raise Forbidden(
            "the super admin is changed only from the server's command line", "super_admin_cli_only"
        )
    if role == Role.DEPT_HEAD and m.is_active:
        raise Conflict("head_required", "the head changes only through the head-change request")
    if role == Role.DEPT_ADMIN and access.super_admin_member(session, actor_user) is None:
        raise Forbidden("a department admin is changed only by the super admin", "use_admin_swap")
    office = session.get(Office, m.office_id)
    member = access.assert_can_manage(
        session, actor_user, "enable_disable", target_office=office, target_role=role
    )
    return apply_exit(
        session,
        access.actor_as(actor, member),
        actor_user,
        m,
        reason=reason,
        assignments=assignments or [],
        items_fingerprint=items_fingerprint,
    )


# ------------------------------------------------------------------------------------------------ the exit step


@dataclass
class ExitItem:
    key: str
    kind: str  # allotment | file
    case_id: uuid.UUID
    ownership_id: uuid.UUID | None = None
    ownership_role: str | None = None
    pending_action: str | None = None
    due_date: date | None = None
    since: datetime | None = None
    leg_seq_no: int | None = None


@dataclass
class ExitResult:
    membership: UserMembership
    reassigned: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)


def _exit_scope(session: Session, m: UserMembership) -> Office:
    """The office subtree whose files belong to the membership: its department, else its own office."""
    dept = session.get(Office, m.department_id) if m.department_id else None
    return dept or session.get(Office, m.office_id)


def exit_items(session: Session, m: UserMembership) -> list[ExitItem]:
    """Decision 21: an allotment item per active ownership row of the department allotted to the person, a file
    item per custody row the membership holds (`custody.holder_membership_id`, design custody-workflow; a leg
    naming the person without a membership counts when its office is in the department's subtree)."""
    items: list[ExitItem] = []
    if m.department_id is not None:
        rows = session.scalars(
            select(CaseOwnership)
            .where(
                CaseOwnership.office_id == m.department_id,
                CaseOwnership.officer_user_id == m.user_id,
                CaseOwnership.status == OwnershipStatus.ACTIVE,
            )
            .order_by(CaseOwnership.case_id)
        ).all()
        for r in rows:
            items.append(
                ExitItem(
                    key=f"allotment:{r.id}",
                    kind="allotment",
                    case_id=r.case_id,
                    ownership_id=r.id,
                    ownership_role=OwnershipRole(r.role).value,
                )
            )
    root = _exit_scope(session, m)
    held = session.execute(
        select(Custody, Office)
        .join(Office, Office.id == Custody.holder_office_id)
        .where(
            (Custody.holder_membership_id == m.id)
            | (
                Custody.holder_membership_id.is_(None)
                & (Custody.holder_user_id == m.user_id)
                & ((Office.id == root.id) | Office.path.like(root.path + "/%"))
            )
        )
        .order_by(Custody.case_id)
    ).all()
    for c, _office in held:
        leg = session.get(CustodyHistory, c.current_leg_id) if c.current_leg_id else None
        items.append(
            ExitItem(
                key=f"file:{c.case_id}:{c.current_leg_id}",
                kind="file",
                case_id=c.case_id,
                pending_action=PendingAction(c.pending_action).value,
                due_date=c.due_date,
                since=c.since,
                leg_seq_no=leg.seq_no if leg else None,
            )
        )
    items.sort(key=lambda i: (str(i.case_id), i.kind))
    return items


def fingerprint(items: list[ExitItem]) -> str:
    return hashlib.sha256("\n".join(sorted(i.key for i in items)).encode()).hexdigest()


def eligible_target(session: Session, leaving: UserMembership, target: UserMembership | None) -> bool:
    """An active membership of an active login in the same department, not the leaver, of an officer type."""
    if target is None or not target.is_active or target.id == leaving.id or target.user_id == leaving.user_id:
        return False
    if leaving.department_id is None or target.department_id != leaving.department_id:
        return False
    if _role(target.role) in NOT_OFFICERS:
        return False
    user = session.get(User, target.user_id)
    return user is not None and user.is_active


def eligible_targets(session: Session, leaving: UserMembership) -> list[UserMembership]:
    if leaving.department_id is None:
        return []
    rows = session.scalars(
        select(UserMembership)
        .join(User, User.id == UserMembership.user_id)
        .where(
            UserMembership.department_id == leaving.department_id,
            UserMembership.is_active.is_(True),
            UserMembership.id != leaving.id,
            User.is_active.is_(True),
        )
        .order_by(User.full_name, UserMembership.id)
    ).all()
    return [r for r in rows if eligible_target(session, leaving, r)]


def _open_alerts(
    session: Session, case_ids: list[uuid.UUID], dept_root: Office, user_id: uuid.UUID
) -> list[Alert]:
    if not case_ids:
        return []
    return list(
        session.scalars(
            select(Alert)
            .join(Office, Office.id == Alert.office_id)
            .where(
                Alert.case_id.in_(case_ids),
                Alert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
                (Office.id == dept_root.id) | Office.path.like(dept_root.path + "/%"),
                select(Notification.id)
                .where(Notification.alert_id == Alert.id, Notification.user_id == user_id)
                .exists(),
            )
            .order_by(Alert.created_at)
        ).all()
    )


def _case_facts(session: Session, case: Case) -> dict[str, Any]:
    from aslms.services.recipients import owning_office

    court = session.get(Court, case.court_id) if case.court_id else None
    owner = owning_office(session, case)
    return {
        "ref_no": case.ref_no,
        "case_no": case.case_no_text,
        "cnr": case.cnr,
        "court": court.name if court else None,
        "owning_department": owner.code if owner else None,
    }


def exit_preview(session: Session, actor_user: User | Member, m: UserMembership) -> dict[str, Any]:
    """Decision 22: every item with its key, the counts, the open alerts per case, the fingerprint and the
    eligible targets; writes nothing. Same scope as ending."""
    from aslms.services import visibility

    office = session.get(Office, m.office_id)
    # the head's preview serves the head-change request's exit (the head itself is never ended here)
    target_role = None if _role(m.role) == Role.DEPT_HEAD else m.role
    access.assert_can_manage(
        session, actor_user, "enable_disable", target_office=office, target_role=target_role
    )
    items = exit_items(session, m)
    case_ids = sorted({i.case_id for i in items}, key=str)
    root = _exit_scope(session, m)
    alerts = _open_alerts(session, case_ids, root, m.user_id)
    per_case: dict[uuid.UUID, int] = {}
    for a in alerts:
        per_case[a.case_id] = per_case.get(a.case_id, 0) + 1
    out_items = []
    for i in items:
        case = session.get(Case, i.case_id)
        facts = _case_facts(session, case)
        facts["visible"] = visibility.can_view_case(session, actor_user, case)
        out_items.append(
            {
                "key": i.key,
                "kind": i.kind,
                "case": facts,
                "ownership_role": i.ownership_role,
                "pending_action": i.pending_action,
                "due_date": i.due_date,
                "since": i.since,
                "leg_seq_no": i.leg_seq_no,
                "open_alerts": per_case.get(i.case_id, 0),
            }
        )
    user = session.get(User, m.user_id)
    others = [x for x in access.active_memberships(session, user) if x.id != m.id]
    primary_after = (
        None
        if not others
        else (
            next((x for x in others if x.is_primary), None)
            or sorted(others, key=lambda x: (x.created_at, x.id))[0]
        )
    )
    targets = []
    for t in eligible_targets(session, m):
        tu = session.get(User, t.user_id)
        to = session.get(Office, t.office_id)
        targets.append(
            {
                "membership": t.id,
                "name": tu.full_name,
                "designation": t.designation,
                "office_code": to.code,
                "role": _role(t.role).value,
            }
        )
    return {
        "items": out_items,
        "counts": {
            "allotments": sum(1 for i in items if i.kind == "allotment"),
            "files": sum(1 for i in items if i.kind == "file"),
            # the leaver's draft notes, made permanent by the exit legs (design custody-workflow, decision 13)
            "drafts": int(
                session.scalar(
                    select(func.count(CaseNoteDraft.id)).where(CaseNoteDraft.membership_id == m.id)
                )
                or 0
            ),
            "open_alerts": len(alerts),
        },
        "items_fingerprint": fingerprint(items),
        "targets": targets,
        "primary_after": primary_after.id if (primary_after and m.is_primary) else None,
    }


def _parse_due(value: Any) -> date | None:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise MembershipError("bad_field", f"due_date {value!r} is not a date") from exc


def _validate_assignments(
    session: Session,
    m: UserMembership,
    items: list[ExitItem],
    assignments: list[dict[str, Any]],
    items_fingerprint: str | None,
    *,
    stale_code: str = "stale_exit",
) -> dict[str, tuple[dict[str, Any], UserMembership]]:
    from aslms.services.alert_rules import today_ist

    current = [i.key for i in items]
    if items and (items_fingerprint or "") != fingerprint(items):
        raise Conflict(stale_code, "the items changed since the preview", items=current)
    if not items and items_fingerprint and items_fingerprint != fingerprint(items):
        raise Conflict(stale_code, "the items changed since the preview", items=current)
    by_key = {i.key: i for i in items}
    seen: set[str] = set()
    out: dict[str, tuple[dict[str, Any], UserMembership]] = {}
    today = today_ist(_now())
    for a in assignments:
        key = str(a.get("key") or "")
        if key in seen:
            raise MembershipError("duplicate_item", f"the item {key} is assigned twice", key=key)
        seen.add(key)
        if key not in by_key:
            raise Conflict(stale_code, f"the item {key} is no longer held", items=current)
        raw = a.get("to_membership")
        try:
            target = session.get(UserMembership, uuid.UUID(str(raw))) if raw else None
        except ValueError:
            target = None
        if not eligible_target(session, m, target):
            raise MembershipError("bad_target", f"the target of {key} is not an eligible officer", key=key)
        item = by_key[key]
        if item.kind == "file":
            if a.get("pending_action") is not None:
                try:
                    pa = PendingAction(str(a["pending_action"]))
                except ValueError as exc:
                    raise MembershipError("bad_field", f"unknown pending_action for {key}", key=key) from exc
                if pa == PendingAction.NONE:
                    raise MembershipError("bad_field", f"pending_action cannot be none ({key})", key=key)
            due = _parse_due(a.get("due_date"))
            if due is not None and not (today <= due <= today + timedelta(days=DUE_DAYS_MAX)):
                raise MembershipError(
                    "bad_field", f"due_date of {key} is from today to {DUE_DAYS_MAX} days ahead", key=key
                )
        remark = a.get("remark")
        if remark is not None and len(str(remark)) > MAX_REMARK:
            raise MembershipError(
                "bad_field", f"the remark of {key} is at most {MAX_REMARK} characters", key=key
            )
        out[key] = (a, target)
    missing = [k for k in current if k not in out]
    if missing:
        raise Conflict("unassigned_items", "every allotted case and held file needs a target", items=missing)
    return out


def apply_exit(
    session: Session,
    actor: Actor,
    actor_user: User | Member | None,
    m: UserMembership,
    *,
    reason: str,
    assignments: list[dict[str, Any]],
    items_fingerprint: str | None,
    stale_code: str = "stale_exit",
) -> ExitResult:
    """Decision 21, after the authority checks: lock, recompute, validate, then move every item to its target in
    case-id order, end the membership and pass the primary flag."""
    from aslms.services import notifications
    from aslms.services.custody import move_custody
    from aslms.services.ownership import reallot_on_exit

    reason_t = (reason or "").strip()
    if not 3 <= len(reason_t) <= MAX_REASON:
        raise MembershipError("bad_field", f"a reason of 3 to {MAX_REASON} characters is required")
    _lock(session, m)
    if not m.is_active:
        raise Conflict("membership_ended", "the membership is already ended")
    items = exit_items(session, m)
    plan = _validate_assignments(session, m, items, assignments, items_fingerprint, stale_code=stale_code)
    leaver = session.get(User, m.user_id)
    office = session.get(Office, m.office_id)
    dept_root = _exit_scope(session, m)
    reassigned: list[dict[str, Any]] = []
    audit_items: list[dict[str, Any]] = []
    case_ids = sorted({i.case_id for i in items}, key=str)
    alerts_done = 0
    notes_finalised = 0
    for case_id in case_ids:
        session.execute(select(Case.id).where(Case.id == case_id).with_for_update())
        case = session.get(Case, case_id)
        targets_on_case: list[UserMembership] = []
        for item in [i for i in items if i.case_id == case_id]:
            a, target = plan[item.key]
            to_member = access.member_of(session, target)
            targets_on_case.append(target)
            if item.kind == "allotment":
                row = session.get(CaseOwnership, item.ownership_id)
                reallot_on_exit(session, actor, case, row=row, from_user=leaver, to_member=to_member)
                audit_items.append(
                    {
                        "key": item.key,
                        "kind": "allotment",
                        "case_id": str(case_id),
                        "to_membership": str(target.id),
                    }
                )
            else:
                custody = session.get(Custody, case_id)
                pa_before, due_before = PendingAction(custody.pending_action), custody.due_date
                pa = PendingAction(str(a["pending_action"])) if a.get("pending_action") else pa_before
                due = _parse_due(a.get("due_date")) if a.get("due_date") is not None else due_before
                dept = session.get(Office, m.department_id) if m.department_id else office
                remark = f"Reassigned on the transfer of {leaver.full_name}, {m.designation or _role(m.role).value} out of {dept.code}: {(a.get('remark') or '').strip() or reason_t}"
                leg = move_custody(
                    session,
                    actor,
                    case,
                    office=to_member.office,
                    user=to_member.user,
                    membership=target,
                    reason="reassigned_on_exit",
                    pending_action=pa,
                    due_date=due,
                    remark=remark[:MAX_REMARK],
                    extra={"on_exit": True},
                )
                notes_finalised += len(getattr(leg, "finalised_ref_nos", []))
                audit_items.append(
                    {
                        "key": item.key,
                        "kind": "file",
                        "case_id": str(case_id),
                        "to_membership": str(target.id),
                        "pending_action": {"before": pa_before.value, "after": pa.value},
                        "due_date": {"before": due_before, "after": due},
                    }
                )
            reassigned.append(
                {"key": item.key, "kind": item.kind, "case_ref": case.ref_no, "to_membership": target.id}
            )
        for alert in _open_alerts(session, [case_id], dept_root, leaver.id):
            users = []
            for t in targets_on_case:
                tu = session.get(User, t.user_id)
                if tu is not None and all(u.id != tu.id for u in users):
                    users.append(tu)
            if (
                AlertStatus(alert.status) == AlertStatus.ACKNOWLEDGED
                and alert.acknowledged_by_user_id == leaver.id
            ):
                alert.status = AlertStatus.OPEN
                alert.acknowledged_by_user_id = None
                alert.acknowledged_at = None
                session.flush()
            notifications.notify(session, alert, users, alert.severity)
            alerts_done += 1
    before = summary(session, m)
    was_primary = m.is_primary
    _close(session, m, reason_t)
    m.updated_by = actor.user_id
    session.flush()
    counts = {
        "allotments": sum(1 for i in items if i.kind == "allotment"),
        "files": sum(1 for i in items if i.kind == "file"),
        "notes_finalised": notes_finalised,
        "alerts": alerts_done,
    }
    write_audit(
        session,
        actor,
        "membership.exit",
        "user_membership",
        m.id,
        before=before,
        after={"reason": reason_t, "items": audit_items, "counts": counts},
    )
    write_audit(
        session, actor, "membership.ended", "user_membership", m.id, before=before, after=summary(session, m)
    )
    _event(session, m, "ended", office.code)
    if was_primary:
        _ensure_primary(session, actor, leaver)
    return ExitResult(m, reassigned, counts)


# ------------------------------------------------------------------------------------------------ department admin


def _new_login(
    session: Session,
    actor: Actor,
    *,
    email: str,
    password: str,
    full_name: str,
    office: Office,
    role: Role,
    designation: str | None,
    designation_id: uuid.UUID | None,
    mobile: str | None,
) -> User:
    from aslms.services.users import create_user

    return create_user(
        session,
        actor,
        email=email,
        password=password,
        full_name=full_name,
        role=role,
        office=office,
        designation=designation,
        designation_id=designation_id,
        mobile=mobile,
        must_confirm_profile=True,
    )


def replace_department_admin(
    session: Session,
    actor: Actor,
    actor_user: User | Member,
    department: Office,
    *,
    incoming: dict[str, Any],
    outgoing: str = "dept_officer",
    reason: str,
    assignments: list[dict[str, Any]] | None = None,
    items_fingerprint: str | None = None,
) -> tuple[UserMembership, dict[str, Any]]:
    """Decision 14: the super admin's swap, in one transaction: the outgoing admin first (`dept_officer`, or
    `end` with the per-item exit to existing memberships), then the incoming admin (an existing membership of
    the department, an existing login, or a new login). Returns (admin membership, outgoing result)."""
    sa_member = access.super_admin_member(session, actor_user)
    if sa_member is None:
        raise Forbidden("only the super admin replaces a department admin", "super_admin_only")
    actor = access.actor_as(actor, sa_member)
    if not access.is_department(department) or not department.is_active:
        raise MembershipError("bad_field", f"{department.code} is not an active department")
    reason_t = (reason or "").strip()
    if not 3 <= len(reason_t) <= MAX_REASON:
        raise MembershipError("bad_field", f"a reason of 3 to {MAX_REASON} characters is required")
    if outgoing not in ("dept_officer", "end"):
        raise MembershipError("bad_field", "outgoing is dept_officer or end")
    current = admin_of(session, department)
    out: dict[str, Any] = {"membership": None, "reassigned": None}
    before = summary(session, current) if current else None
    if current is not None:
        _lock(session, current)
        out["membership"] = current.id
        if outgoing == "dept_officer":
            set_role(session, actor, current, Role.DEPT_OFFICER)
        else:
            result = apply_exit(
                session,
                actor,
                actor_user,
                current,
                reason=reason_t,
                assignments=assignments or [],
                items_fingerprint=items_fingerprint,
            )
            out["reassigned"] = result.reassigned
    admin = _make_incoming(session, actor, department, incoming, Role.DEPT_ADMIN)
    write_audit(
        session,
        actor,
        "office.admin_replaced",
        "office",
        department.id,
        before=before,
        after={
            "admin": summary(session, admin),
            "outgoing": outgoing,
            "reason": reason_t,
            "items": [
                {"key": r["key"], "to_membership": str(r["to_membership"])} for r in (out["reassigned"] or [])
            ],
        },
    )
    return admin, out


def _make_incoming(
    session: Session,
    actor: Actor,
    department: Office,
    incoming: dict[str, Any],
    role: Role,
    *,
    ticket_ref: str | None = None,
) -> UserMembership:
    """The incoming admin or head: an existing membership of the department (changed to `role`; an ended one is
    reactivated), an existing login by id or e-mail (a new membership at the department office), or a new login."""
    incoming = incoming or {}
    if incoming.get("membership"):
        try:
            m = session.get(UserMembership, uuid.UUID(str(incoming["membership"])))
        except ValueError:
            m = None
        if m is None or m.department_id != department.id:
            raise MembershipError("bad_field", f"the membership is not a membership of {department.code}")
        user = session.get(User, m.user_id)
        if not user.is_active:
            raise Conflict("login_inactive", "the incoming person's login is disabled")
        if _role(m.role) == Role.DEPT_HEAD and role != Role.DEPT_HEAD and m.is_active:
            raise Conflict("head_required", "the head changes only through the head-change request")
        if not m.is_active:
            return reactivate_internal(session, actor, m, role=role, ticket_ref=ticket_ref)
        if m.office_id != department.id:
            if role == Role.DEPT_HEAD:
                raise MembershipError("head_at_department", "a department head sits at the department office")
            _close(session, m, f"moved to the department office as {role.value}")
            session.flush()
            write_audit(
                session, actor, "membership.ended", "user_membership", m.id, after=summary(session, m)
            )
            was_primary = not any(x.is_primary for x in access.active_memberships(session, user))
            new = insert_membership(
                session,
                actor,
                user,
                office=department,
                role=role,
                designation=incoming.get("designation") or m.designation,
                designation_id=incoming.get("designation_id") or m.designation_id,
                ticket_ref=ticket_ref,
            )
            if was_primary and not new.is_primary:
                _ensure_primary(session, actor, user)
            return new
        set_role(session, actor, m, role, ticket_ref=ticket_ref)
        if incoming.get("designation"):
            m.designation = _text(incoming["designation"], 200)
            session.flush()
        return m
    user: User | None = None
    if incoming.get("user"):
        try:
            user = session.get(User, uuid.UUID(str(incoming["user"])))
        except ValueError:
            user = None
        if user is None:
            raise MembershipError("bad_field", "no such user")
    elif incoming.get("email") and not incoming.get("password"):
        user = lookup(session, incoming["email"])
        if user is None:
            raise MembershipError("bad_field", "no login with this e-mail")
    if user is not None:
        if not user.is_active:
            raise Conflict("login_inactive", "the incoming person's login is disabled")
        return insert_membership(
            session,
            actor,
            user,
            office=department,
            role=role,
            designation=incoming.get("designation"),
            designation_id=incoming.get("designation_id"),
            ticket_ref=ticket_ref,
        )
    if not incoming.get("email") or not incoming.get("password") or not incoming.get("full_name"):
        raise MembershipError(
            "bad_field", "incoming is a membership, a user, or a new login (e-mail, name, password)"
        )
    new_user = _new_login(
        session,
        actor,
        email=incoming["email"],
        password=incoming["password"],
        full_name=incoming["full_name"],
        office=department,
        role=role,
        designation=incoming.get("designation"),
        designation_id=incoming.get("designation_id"),
        mobile=incoming.get("mobile"),
    )
    return access.active_memberships(session, new_user)[0]


# ------------------------------------------------------------------------------------------------ the head


def apply_head_change(
    session: Session,
    actor: Actor,
    department: Office,
    *,
    operation: str,
    incoming: dict[str, Any] | None,
    outgoing: dict[str, Any] | None,
    ticket_ref: str | None,
    stale_code: str = "stale_exit",
) -> dict[str, Any]:
    """Decisions 15-16 and 24, after the ticket service's checks: the outgoing change first (retype or the
    per-item exit), then the incoming one, in the caller's transaction. Returns what was applied."""
    result: dict[str, Any] = {"operation": operation, "membership_ids": []}
    current = head_of(session, department)
    if operation in ("replace", "end"):
        if current is None:
            raise Conflict("no_head", f"{department.code} has no head")
        _lock(session, current)
        out = outgoing or {}
        before = summary(session, current)
        if out.get("mode") == "exit":
            res = apply_exit(
                session,
                actor,
                None,
                current,
                reason=out.get("reason") or "",
                assignments=out.get("assignments") or [],
                items_fingerprint=out.get("items_fingerprint"),
                stale_code=stale_code,
            )
            result["outgoing"] = {
                "membership_id": str(current.id),
                "mode": "exit",
                "before": before,
                "reassigned": [
                    {"key": r["key"], "to_membership": str(r["to_membership"])} for r in res.reassigned
                ],
            }
        else:
            role_to = _role(out.get("role_to") or Role.DEPT_OFFICER)
            if role_to not in DELEGABLE_ROLES:
                raise MembershipError("bad_field", "the outgoing head becomes an officer type")
            set_role(session, actor, current, role_to, ticket_ref=ticket_ref)
            result["outgoing"] = {
                "membership_id": str(current.id),
                "mode": "retype",
                "before": before,
                "after": summary(session, current),
            }
        result["membership_ids"].append(str(current.id))
    elif current is not None:
        raise Conflict("head_exists", f"{department.code} already has a head; replace it")
    if operation in ("set", "replace"):
        head = _make_incoming(
            session, actor, department, incoming or {}, Role.DEPT_HEAD, ticket_ref=ticket_ref
        )
        result["incoming"] = {"membership_id": str(head.id), "after": summary(session, head)}
        result["membership_ids"].append(str(head.id))
    return result


# ------------------------------------------------------------------------------------------------ the super admin


def replace_super_admin(
    session: Session,
    *,
    email: str,
    name: str | None = None,
    designation: str | None = None,
    password: str | None = None,
) -> tuple[User, User]:
    """Decision 13, the CLI only: in one transaction end the current super admin membership, disable that login
    and revoke its refresh tokens, then make the new one (a new login, or an existing login with no active
    membership). Returns (old login, new login)."""
    from aslms.services.users import UserError, create_user

    actor = Actor.system("cli: replace-super-admin")
    current = super_admin_membership(session)
    if current is None:
        raise Conflict("no_super_admin", "there is no super admin; use create-super-admin")
    session.execute(select(UserMembership.id).where(UserMembership.id == current.id).with_for_update())
    old_user = session.get(User, current.user_id)
    email_n = (email or "").strip().lower()
    if email_n == old_user.email:
        raise MembershipError("bad_field", "the new super admin is a different person")
    existing = lookup(session, email_n)
    if existing is not None and access.active_memberships(session, existing):
        raise Conflict(
            "login_has_memberships", "the super admin holds nothing else; that login has memberships"
        )
    before = {"user_id": str(old_user.id), "email": old_user.email}
    _close(session, current, "replaced")
    old_user.is_active = False
    old_user.deactivated_at = _now()
    for t in session.scalars(
        select(RefreshToken).where(RefreshToken.user_id == old_user.id, RefreshToken.revoked_at.is_(None))
    ).all():
        t.revoked_at = _now()
    session.flush()
    root = state_root(session)
    if existing is None:
        if not password:
            raise UserError("a password is required for a new login")
        new_user = create_user(
            session,
            actor,
            email=email_n,
            password=password,
            full_name=name or "Super Administrator",
            role=Role.SUPER_ADMIN,
            office=root,
            designation=designation or "Super Administrator",
            must_confirm_profile=True,
        )
    else:
        new_user = existing
        new_user.is_active, new_user.deactivated_at = True, None
        if name:
            new_user.full_name = name.strip()[:200]
        session.flush()
        insert_membership(
            session,
            actor,
            new_user,
            office=root,
            role=Role.SUPER_ADMIN,
            designation=designation or "Super Administrator",
        )
    write_audit(
        session,
        actor,
        "membership.super_admin_replaced",
        "user_membership",
        current.id,
        before=before,
        after={"user_id": str(new_user.id), "email": new_user.email},
    )
    return old_user, new_user


def overrides_out(session: Session, m: UserMembership) -> list[dict[str, Any]]:
    rows = session.scalars(select(UserPermission).where(UserPermission.membership_id == m.id)).all()
    return [
        {
            "permission": r.permission,
            "effect": r.effect.value,
            "is_active": r.is_active,
            "granted_by_user_id": r.granted_by_user_id,
            "reason": r.reason,
            "valid_to": r.valid_to,
        }
        for r in rows
    ]
