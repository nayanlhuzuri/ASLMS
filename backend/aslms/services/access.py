"""Access control: what a person may do, and who may change that (design `user-memberships`, decisions 1, 5,
6, 8-11, built on the access-control slice of 1 Oct 2026).

- **A membership is the unit of authority.** A login (`users`) holds one or more memberships
  (`user_memberships`: office + designation + user type). `Member` is the frozen view services receive for an
  action: the login, the membership, its office and department, its type and its functions.
- **Functions per membership** = the enabled rows of the membership type's matrix (`role_permissions`) + the
  membership's active `grant` overrides − its active `deny` overrides. A `super_admin` membership has every
  function and cannot be denied. An inactive login, or an ended membership, has none. The **union** over the
  active memberships is only a gate (`has(session, user, ...)`, the `require(...)` dependency, `/me`); services
  check the function in the membership that acts.
- **Managing users** (`users.create`, `users.edit`, `users.set_type`, `users.enable_disable`, `users.grant`):
  the super admin may act on anyone (no delegation limit). Anyone else acts through the membership whose office
  subtree contains the target office, only on the delegable types (`dept_officer`, `directorate_user`,
  `standing_counsel`, `referral_reviewer`), and grants only functions held in that membership.
- **The type matrix** is changed only with `access.manage_types` (the super admin's own function).
  `admin.tickets` is reserved: never enabled for a type, never overridden.
Every change writes an `audit_log` row and an `access_changed` / `user_updated` event. The users mirror columns
(`users.office_id`, `role`, `designation`) are never read here for authorisation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.orm import Session, object_session

from aslms.domain.events import Event, EventVisibility
from aslms.domain.org import Office, PermissionEffect, RolePermission, User, UserMembership, UserPermission
from aslms.domain.reference import RETIRED_PERMISSIONS, EventType, OfficeKind, Permission, Role
from aslms.services.audit import Actor, write_audit

DELEGABLE_ROLES = frozenset(
    {Role.DEPT_OFFICER, Role.DIRECTORATE_USER, Role.STANDING_COUNSEL, Role.REFERRAL_REVIEWER}
)
# State-wide types (no department of their own) and the types that never act as a department's officer
NOT_OFFICERS = frozenset({Role.SUPER_ADMIN, Role.STATE_OVERSIGHT, Role.AUDITOR, Role.CENTRAL_OPERATOR})
RESERVED_FUNCTIONS = frozenset({Permission.ADMIN_TICKETS})
# retired functions (design custody-workflow, decision 22): nobody holds them, the super admin included
ACTIVE_FUNCTIONS = frozenset(Permission) - RETIRED_PERMISSIONS
DEPARTMENT_TIER_KINDS = frozenset({OfficeKind.DEPARTMENT, OfficeKind.CENTRAL, OfficeKind.ADVOCATE_GENERAL})
MANAGE_PERMISSIONS = {
    "create": Permission.USERS_CREATE,
    "edit": Permission.USERS_EDIT,
    "set_type": Permission.USERS_SET_TYPE,
    "enable_disable": Permission.USERS_ENABLE_DISABLE,
    "grant": Permission.USERS_GRANT,
    "reset_password": Permission.USERS_RESET_PASSWORD,
}
_CACHE_KEY = "aslms_members"


class Forbidden(PermissionError):
    """The actor lacks the function or the scope for this action (HTTP 403). `code` names the rule."""

    def __init__(self, message: str, code: str = "forbidden") -> None:
        super().__init__(message)
        self.code = code


class Conflict(ValueError):
    """The state does not allow the change (HTTP 409). `code` is machine-readable."""

    def __init__(self, code: str, message: str | None = None, **extra: Any) -> None:
        super().__init__(message or code)
        self.code = code
        self.extra = extra


class ReservedFunction(ValueError):
    """`admin.tickets` cannot be enabled for a type or overridden (HTTP 400 `reserved_function`)."""

    code = "reserved_function"


class RetiredFunction(ReservedFunction):
    """A retired function (`requests.send`, `requests.answer`) cannot be granted, denied or enabled (HTTP 400
    `retired_function`; design custody-workflow, decision 22)."""

    code = "retired_function"


def _as_role(value: Role | str) -> Role:
    return value if isinstance(value, Role) else Role(value)


def _as_perm(value: Permission | str) -> Permission:
    return value if isinstance(value, Permission) else Permission(value)


# ------------------------------------------------------------------------------------------------ the tree


def is_department(office: Office | None) -> bool:
    """A Department-tier office: a direct child of the State root of a department, central or AG kind."""
    return (
        office is not None
        and office.path.count("/") == 1
        and OfficeKind(office.kind) in DEPARTMENT_TIER_KINDS
    )


def department_of(session: Session, office: Office | None) -> Office | None:
    """The Department-tier ancestor of an office (the second segment of `offices.path`), None for the root."""
    if office is None:
        return None
    parts = office.path.split("/")
    if len(parts) < 2:
        return None
    dept = office if len(parts) == 2 else session.scalar(select(Office).where(Office.code == parts[1]))
    return dept if is_department(dept) else None


def subtree_contains(root: Office, office: Office) -> bool:
    return office.id == root.id or office.path.startswith(root.path + "/")


def office_subtree(session: Session, office_id: uuid.UUID) -> list[Office]:
    root = session.get(Office, office_id)
    if root is None:
        return []
    return list(
        session.scalars(
            select(Office).where((Office.id == root.id) | (Office.path.like(root.path + "/%")))
        ).all()
    )


# ------------------------------------------------------------------------------------------------ members


@dataclass(frozen=True, eq=False)
class Member:
    """One active membership of a login, as the unit of authority (decision 6). `id` is the person's id, so a
    Member can stand where the acting person is named (custody holder, allotted officer, author)."""

    user: User
    membership: UserMembership
    office: Office
    department: Office | None
    role: Role
    functions: frozenset[Permission]

    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    @property
    def membership_id(self) -> uuid.UUID:
        return self.membership.id

    @property
    def full_name(self) -> str:
        return self.user.full_name

    @property
    def designation(self) -> str | None:
        return self.membership.designation

    @property
    def is_active(self) -> bool:
        return bool(self.user.is_active and self.membership.is_active)

    @property
    def is_super_admin(self) -> bool:
        return self.role == Role.SUPER_ADMIN

    def holds(self, permission: Permission | str) -> bool:
        return _as_perm(permission) in self.functions

    def covers(self, office: Office) -> bool:
        """The membership's subtree contains `office` (the super admin's covers everything)."""
        return self.is_super_admin or subtree_contains(self.office, office)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Member({self.user.email}, {self.office.code}, {self.role.value})"


def _clear_cache(session: Session, *_: Any) -> None:
    session.info.pop(_CACHE_KEY, None)


# Any write may change memberships, overrides or the matrix: the per-session cache lives between flushes only.
event.listen(Session, "after_flush", _clear_cache)
event.listen(Session, "after_commit", _clear_cache)
event.listen(Session, "after_soft_rollback", _clear_cache)


def role_functions(session: Session, role: Role | str) -> set[Permission]:
    role = _as_role(role)
    if role == Role.SUPER_ADMIN:
        return set(ACTIVE_FUNCTIONS)
    rows = session.scalars(
        select(RolePermission.permission).where(
            RolePermission.role == role, RolePermission.is_enabled.is_(True)
        )
    ).all()
    return {_as_perm(p) for p in rows} - RESERVED_FUNCTIONS - RETIRED_PERMISSIONS


def membership_overrides(session: Session, membership: UserMembership) -> dict[Permission, PermissionEffect]:
    today = date.today()
    out: dict[Permission, PermissionEffect] = {}
    rows = session.scalars(select(UserPermission).where(UserPermission.membership_id == membership.id)).all()
    for row in rows:
        if not row.is_active or (row.valid_to is not None and row.valid_to < today) or row.valid_from > today:
            continue
        out[_as_perm(row.permission)] = row.effect
    return out


def membership_functions(
    session: Session, membership: UserMembership, user: User | None = None
) -> set[Permission]:
    """Decision 5: type matrix + the membership's grants − its denies; nothing for an ended membership or an
    inactive login; everything for the super admin."""
    user = user if user is not None else session.get(User, membership.user_id)
    if user is None or not user.is_active or not membership.is_active:
        return set()
    role = _as_role(membership.role)
    if role == Role.SUPER_ADMIN:
        return set(ACTIVE_FUNCTIONS)
    perms = role_functions(session, role)
    for perm, effect in membership_overrides(session, membership).items():
        if perm in RESERVED_FUNCTIONS or perm in RETIRED_PERMISSIONS:
            continue
        if effect == PermissionEffect.GRANT:
            perms.add(perm)
        else:
            perms.discard(perm)
    return perms


def member_of(session: Session, membership: UserMembership, user: User | None = None) -> Member:
    user = user if user is not None else session.get(User, membership.user_id)
    office = session.get(Office, membership.office_id)
    dept = session.get(Office, membership.department_id) if membership.department_id else None
    return Member(
        user=user,
        membership=membership,
        office=office,
        department=dept,
        role=_as_role(membership.role),
        functions=frozenset(membership_functions(session, membership, user)),
    )


def active_memberships(session: Session, user: User | uuid.UUID) -> list[UserMembership]:
    """Active memberships of a login, the primary first, then by age."""
    user_id = user if isinstance(user, uuid.UUID) else user.id
    return list(
        session.scalars(
            select(UserMembership)
            .where(UserMembership.user_id == user_id, UserMembership.is_active.is_(True))
            .order_by(UserMembership.is_primary.desc(), UserMembership.created_at, UserMembership.id)
        ).all()
    )


def members(session: Session, user: User | Member) -> list[Member]:
    """The login's active memberships as `Member`s (primary first); empty for an inactive login. A `Member`
    stands for itself. Cached per session between flushes."""
    if isinstance(user, Member):
        return [user] if user.is_active else []
    if not user.is_active:
        return []
    cache: dict[uuid.UUID, list[Member]] = session.info.setdefault(_CACHE_KEY, {})
    if user.id not in cache:
        cache[user.id] = [member_of(session, m, user) for m in active_memberships(session, user)]
    return cache[user.id]


def primary_member(session: Session, user: User | Member) -> Member | None:
    if isinstance(user, Member):
        return user
    ms = members(session, user)
    return ms[0] if ms and ms[0].membership.is_primary else (ms[0] if ms else None)


def member_in_department(session: Session, user: User | Member, department: Office | None) -> Member | None:
    """The person's membership in `department` (unique, decision 2); None when there is none."""
    if department is None:
        return None
    return next(
        (m for m in members(session, user) if m.department is not None and m.department.id == department.id),
        None,
    )


def departments(session: Session, user: User | Member) -> list[Office]:
    """The departments the person works in (primary first, each once)."""
    out: list[Office] = []
    for m in members(session, user):
        if m.department is not None and all(d.id != m.department.id for d in out):
            out.append(m.department)
    return out


# ------------------------------------------------------------------------------------------------ reading


def effective_permissions(session: Session, user: User | Member) -> set[Permission]:
    """The union over active memberships (a gate and `/me`), or one membership's functions for a `Member`."""
    out: set[Permission] = set()
    for m in members(session, user):
        out |= m.functions
    return out


def has(session: Session, user: User | Member, permission: Permission | str) -> bool:
    perm = _as_perm(permission)
    return any(perm in m.functions for m in members(session, user))


def is_super_admin(user: User | Member) -> bool:
    if isinstance(user, Member):
        return user.is_super_admin
    session = object_session(user)
    if session is None:
        return False
    return any(m.is_super_admin for m in members(session, user))


def super_admin_member(session: Session, user: User | Member) -> Member | None:
    return next((m for m in members(session, user) if m.is_super_admin), None)


def holders_in(session: Session, user: User | Member, permission: Permission | str) -> list[Member]:
    perm = _as_perm(permission)
    return [m for m in members(session, user) if perm in m.functions]


# ------------------------------------------------------------------------------------------------ scope


def in_scope(
    session: Session, actor_user: User | Member, office: Office, *, permission: Permission | None = None
) -> bool:
    """Some membership of the actor covers `office` (and holds `permission` when given)."""
    return acting_member_for_office(session, actor_user, office, permission=permission) is not None


def acting_member_for_office(
    session: Session, user: User | Member, office: Office | None, *, permission: Permission | None = None
) -> Member | None:
    """Decision 6, an action on a user or membership: the caller's membership whose subtree contains the
    target office (the super admin's always does), holding `permission` when given."""
    if office is None:
        return None
    candidates = [m for m in members(session, user) if m.covers(office)]
    if permission is not None:
        candidates = [m for m in candidates if permission in m.functions]
    candidates.sort(key=lambda m: (not m.is_super_admin, -len(m.office.path)))
    return candidates[0] if candidates else None


def require(session: Session, actor_user: User | Member, permission: Permission) -> None:
    if not has(session, actor_user, permission):
        raise Forbidden(f"{permission.value} is not enabled for this user")


def assert_can_manage(
    session: Session,
    actor_user: User | Member,
    action: str,
    *,
    target_office: Office,
    target_role: Role | str | None = None,
    functions: set[Permission] | None = None,
) -> Member:
    """Raises Forbidden unless the actor may perform `action` (a MANAGE_PERMISSIONS key) on a membership in
    `target_office` of type `target_role`, granting `functions`. Returns the acting membership."""
    permission = MANAGE_PERMISSIONS[action]
    require(session, actor_user, permission)
    member = acting_member_for_office(session, actor_user, target_office, permission=permission)
    if member is None:
        raise Forbidden("the user is outside your offices")
    if member.is_super_admin:
        return member
    if target_role is not None and _as_role(target_role) not in DELEGABLE_ROLES:
        raise Forbidden(
            f"only a super admin may create or change users of type {_as_role(target_role).value}",
            "not_delegable",
        )
    if functions:
        missing = {p.value for p in functions} - {p.value for p in member.functions}
        if missing:
            raise Forbidden("you cannot grant functions you do not hold: " + ", ".join(sorted(missing)))
    return member


def actor_as(actor: Actor, member: Member | None) -> Actor:
    """The actor snapshot naming the acting membership (decision 10)."""
    if member is None:
        return actor
    return replace(actor, designation=member.designation, office_code=member.office.code)


# ------------------------------------------------------------------------------------------------ changes


def _event(session: Session, kind: EventType, payload: dict, key: str) -> None:
    if session.scalar(select(Event.id).where(Event.dedupe_key == key)) is None:
        session.add(Event(type=kind, payload=payload, dedupe_key=key, visibility=EventVisibility.SCOPED))


def _primary_membership(session: Session, user: User) -> UserMembership | None:
    ms = active_memberships(session, user)
    return next((m for m in ms if m.is_primary), None)


def set_type(session: Session, actor: Actor, actor_user: User | Member, user: User, role: Role | str) -> User:
    """Compatibility path (`PUT /admin/users/{id}/type`): changes the type of the login's primary membership
    through the membership service (same limits)."""
    from aslms.services import memberships

    membership = _primary_membership(session, user)
    if membership is None:
        raise Conflict("no_membership", "the login has no active membership")
    memberships.update(session, actor, actor_user, membership, role=role)
    return user


def login_scope_member(session: Session, actor_user: User | Member, user: User, action: str) -> Member:
    """Login-level actions (name, e-mail, mobile, password, enable/disable): the super admin, or the caller's
    membership covering the target's **primary** membership office (decision 8). A login with no active
    membership: the super admin only."""
    permission = MANAGE_PERMISSIONS[action]
    require(session, actor_user, permission)
    sa_member = super_admin_member(session, actor_user)
    if sa_member is not None:
        return sa_member
    primary = _primary_membership(session, user)
    if primary is None:
        raise Forbidden("only the super admin may act on a login with no membership")
    office = session.get(Office, primary.office_id)
    member = acting_member_for_office(session, actor_user, office, permission=permission)
    if member is None:
        raise Forbidden("the user is outside your offices")
    if _as_role(primary.role) not in DELEGABLE_ROLES:
        raise Forbidden(
            f"only a super admin may change users of type {_as_role(primary.role).value}", "not_delegable"
        )
    return member


def _holds_role(session: Session, user: User, role: Role) -> bool:
    return any(_as_role(m.role) == role for m in active_memberships(session, user))


def set_enabled(session: Session, actor: Actor, actor_user: User | Member, user: User, enabled: bool) -> User:
    """Enable or disable a login (decision 8). The super admin's login is changed only from the CLI (403
    `super_admin_cli_only`); a department head's login cannot be disabled (409 `head_required`)."""
    if _holds_role(session, user, Role.SUPER_ADMIN):
        raise Forbidden(
            "the super admin is changed only from the server's command line", "super_admin_cli_only"
        )
    require(session, actor_user, MANAGE_PERMISSIONS["enable_disable"])
    if not enabled and _holds_role(session, user, Role.DEPT_HEAD):
        raise Conflict(
            "head_required",
            "the user is a department's head; replace the head first (or the super admin ends it)",
        )
    member = login_scope_member(session, actor_user, user, "enable_disable")
    if user.id == member.user.id and not enabled:
        raise Forbidden("you cannot disable yourself")
    actor = actor_as(actor, member)
    before = user_summary(user)
    user.is_active = enabled
    user.deactivated_at = None if enabled else datetime.now(UTC)
    user.updated_by = actor.user_id
    session.flush()
    write_audit(
        session,
        actor,
        "user.enable" if enabled else "user.disable",
        "user",
        user.id,
        before=before,
        after=user_summary(user),
    )
    _event(
        session,
        EventType.USER_UPDATED,
        {"user_id": str(user.id), "is_active": enabled},
        f"user_enabled:{user.id}:{enabled}:{datetime.now(UTC).isoformat()}",
    )
    return user


def set_override(
    session: Session,
    actor: Actor,
    actor_user: User | Member,
    target: User | UserMembership,
    permission: Permission | str,
    effect: PermissionEffect | None,
    *,
    reason: str | None = None,
) -> UserPermission | None:
    """Grant or deny one function for one membership (a `User` means its primary membership, the
    compatibility path); `effect=None` ends the override. Denying a super admin, overriding a super admin's
    membership and any override of a reserved function are refused."""
    permission = _as_perm(permission)
    if permission in RESERVED_FUNCTIONS:
        raise ReservedFunction(f"{permission.value} is reserved and cannot be granted or denied")
    if permission in RETIRED_PERMISSIONS:
        raise RetiredFunction(f"{permission.value} is retired and cannot be granted or denied")
    if isinstance(target, User):
        membership = _primary_membership(session, target)
        if membership is None:
            raise Conflict("no_membership", "the login has no active membership")
        user = target
    else:
        membership = target
        user = session.get(User, membership.user_id)
    office = session.get(Office, membership.office_id)
    member = assert_can_manage(
        session,
        actor_user,
        "grant",
        target_office=office,
        target_role=membership.role,
        functions={permission} if effect == PermissionEffect.GRANT else None,
    )
    if _as_role(membership.role) == Role.SUPER_ADMIN:
        raise Forbidden("a super admin's functions cannot be overridden", "super_admin_cli_only")
    actor = actor_as(actor, member)
    row = session.scalar(
        select(UserPermission).where(
            UserPermission.membership_id == membership.id, UserPermission.permission == permission
        )
    )
    before = None if row is None else {"effect": row.effect.value, "is_active": row.is_active}
    if effect is None:
        if row is None:
            return None
        row.is_active, row.deactivated_at, row.valid_to = False, datetime.now(UTC), date.today()
    else:
        if row is None:
            row = UserPermission(
                user_id=user.id, membership_id=membership.id, permission=permission, effect=effect
            )
            session.add(row)
        row.effect, row.is_active, row.deactivated_at, row.valid_to = effect, True, None, None
        row.granted_by_user_id = actor.user_id
        row.reason = reason
        row.actor_user_id, row.actor_name = actor.user_id, actor.name
        row.actor_designation, row.actor_office_code = actor.designation, actor.office_code
    session.flush()
    after = {"effect": row.effect.value, "is_active": row.is_active}
    write_audit(
        session,
        actor,
        "access.override",
        "user_permission",
        row.id,
        before=before,
        after={
            "user_id": str(user.id),
            "membership_id": str(membership.id),
            "permission": permission.value,
            **after,
        },
    )
    _event(
        session,
        EventType.ACCESS_CHANGED,
        {
            "user_id": str(user.id),
            "membership_id": str(membership.id),
            "permission": permission.value,
            **after,
        },
        f"access_override:{row.id}:{datetime.now(UTC).isoformat()}",
    )
    return row


def matrix(session: Session, role: Role | str | None = None) -> dict[str, dict[str, bool]]:
    stmt = select(RolePermission)
    if role is not None:
        stmt = stmt.where(RolePermission.role == _as_role(role))
    out: dict[str, dict[str, bool]] = {}
    for row in session.scalars(stmt).all():
        r = _as_role(row.role).value
        out.setdefault(r, {})[_as_perm(row.permission).value] = row.is_enabled
    if role is None or _as_role(role) == Role.SUPER_ADMIN:
        out[Role.SUPER_ADMIN.value] = {p.value: p in ACTIVE_FUNCTIONS for p in Permission}
    return out


def set_matrix(
    session: Session,
    actor: Actor,
    actor_user: User | Member,
    role: Role | str,
    permission: Permission | str,
    enabled: bool,
) -> RolePermission:
    require(session, actor_user, Permission.ACCESS_MANAGE_TYPES)
    role, permission = _as_role(role), _as_perm(permission)
    if role == Role.SUPER_ADMIN:
        raise Forbidden("the super admin type always has every function")
    if permission in RESERVED_FUNCTIONS:
        raise ReservedFunction(f"{permission.value} is reserved for the super admin")
    if permission in RETIRED_PERMISSIONS:
        raise RetiredFunction(f"{permission.value} is retired")
    row = session.scalar(
        select(RolePermission).where(RolePermission.role == role, RolePermission.permission == permission)
    )
    before = None if row is None else {"is_enabled": row.is_enabled}
    if row is None:
        row = RolePermission(role=role, permission=permission, is_enabled=enabled, created_by=actor.user_id)
        session.add(row)
    else:
        row.is_enabled = enabled
        row.updated_by = actor.user_id
    session.flush()
    write_audit(
        session,
        actor,
        "access.matrix",
        "role_permission",
        row.id,
        before=before,
        after={"role": role.value, "permission": permission.value, "is_enabled": enabled},
    )
    _event(
        session,
        EventType.ACCESS_CHANGED,
        {"role": role.value, "permission": permission.value, "is_enabled": enabled},
        f"access_matrix:{row.id}:{datetime.now(UTC).isoformat()}",
    )
    return row


def actor_for(
    user: User, office: Office | None = None, *, ip: str | None = None, user_agent: str | None = None
) -> Actor:
    """The actor snapshot of a login acting through its primary membership (sign-in, profile, non-case
    actions); services re-snapshot with `actor_as` for the acting membership."""
    session = object_session(user)
    designation = user.designation
    if session is not None:
        primary = primary_member(session, user)
        if primary is not None:
            designation = primary.designation
            office = office if office is not None else primary.office
    return Actor(
        user_id=user.id,
        name=user.full_name,
        designation=designation,
        office_code=office.code if office else None,
        ip=ip,
        user_agent=user_agent,
    )


def user_summary(user: User) -> dict:
    from aslms.services.users import user_summary as _summary

    return _summary(user)
