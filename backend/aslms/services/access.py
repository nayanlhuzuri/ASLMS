"""Access control: what a user may do, and who may change that.

- A user's **effective functions** = the enabled rows of their type's matrix (`role_permissions`) + their
  active `grant` overrides − their active `deny` overrides. A `super_admin` has every active function and
  cannot be denied. An inactive user has none.
- **Managing users** (`users.create`, `users.edit`, `users.set_type`, `users.enable_disable`, `users.grant`):
  the super admin may act on anyone. Anyone else may act only on users in their own office subtree, only of
  the delegable types (`dept_officer`, `directorate_user`, `standing_counsel`, `referral_reviewer`), and may
  grant only functions they themselves hold.
- **The type matrix** is changed only with `access.manage_types` (the super admin's own function).
Every change writes an `audit_log` row and an `access_changed` / `user_updated` event."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.domain.events import Event, EventVisibility
from aslms.domain.org import Office, PermissionEffect, RolePermission, User, UserPermission
from aslms.domain.reference import EventType, Permission, Role
from aslms.services.audit import Actor, write_audit
from aslms.services.users import user_summary

DELEGABLE_ROLES = frozenset(
    {Role.DEPT_OFFICER, Role.DIRECTORATE_USER, Role.STANDING_COUNSEL, Role.REFERRAL_REVIEWER}
)
MANAGE_PERMISSIONS = {
    "create": Permission.USERS_CREATE,
    "edit": Permission.USERS_EDIT,
    "set_type": Permission.USERS_SET_TYPE,
    "enable_disable": Permission.USERS_ENABLE_DISABLE,
    "grant": Permission.USERS_GRANT,
    "reset_password": Permission.USERS_RESET_PASSWORD,
}


class Forbidden(PermissionError):
    """The actor lacks the function or the scope for this action."""


def _as_role(value: Role | str) -> Role:
    return value if isinstance(value, Role) else Role(value)


def _as_perm(value: Permission | str) -> Permission:
    return value if isinstance(value, Permission) else Permission(value)


# ------------------------------------------------------------------------------------------------ reading


def role_functions(session: Session, role: Role | str) -> set[Permission]:
    role = _as_role(role)
    if role == Role.SUPER_ADMIN:
        return set(Permission)
    rows = session.scalars(
        select(RolePermission.permission).where(
            RolePermission.role == role, RolePermission.is_enabled.is_(True)
        )
    ).all()
    return {_as_perm(p) for p in rows}


def user_overrides(session: Session, user: User) -> dict[Permission, PermissionEffect]:
    today = date.today()
    out: dict[Permission, PermissionEffect] = {}
    for row in session.scalars(select(UserPermission).where(UserPermission.user_id == user.id)).all():
        if not row.is_active or (row.valid_to is not None and row.valid_to < today) or row.valid_from > today:
            continue
        out[_as_perm(row.permission)] = row.effect
    return out


def effective_permissions(session: Session, user: User) -> set[Permission]:
    if not user.is_active:
        return set()
    role = _as_role(user.role)
    if role == Role.SUPER_ADMIN:
        return set(Permission)
    perms = role_functions(session, role)
    for perm, effect in user_overrides(session, user).items():
        if effect == PermissionEffect.GRANT:
            perms.add(perm)
        else:
            perms.discard(perm)
    return perms


def has(session: Session, user: User, permission: Permission | str) -> bool:
    return _as_perm(permission) in effective_permissions(session, user)


def is_super_admin(user: User) -> bool:
    return _as_role(user.role) == Role.SUPER_ADMIN


# ------------------------------------------------------------------------------------------------ scope


def office_subtree(session: Session, office_id: uuid.UUID) -> list[Office]:
    root = session.get(Office, office_id)
    if root is None:
        return []
    return list(
        session.scalars(
            select(Office).where((Office.id == root.id) | (Office.path.like(root.path + "/%")))
        ).all()
    )


def in_scope(session: Session, actor_user: User, office: Office) -> bool:
    if is_super_admin(actor_user):
        return True
    root = session.get(Office, actor_user.office_id)
    return root is not None and (office.id == root.id or office.path.startswith(root.path + "/"))


def require(session: Session, actor_user: User, permission: Permission) -> None:
    if not has(session, actor_user, permission):
        raise Forbidden(f"{permission.value} is not enabled for this user")


def assert_can_manage(
    session: Session,
    actor_user: User,
    action: str,
    *,
    target_office: Office,
    target_role: Role | str | None = None,
    functions: set[Permission] | None = None,
) -> None:
    """Raises Forbidden unless `actor_user` may perform `action` (a MANAGE_PERMISSIONS key) on a user in
    `target_office` of type `target_role`, granting `functions`."""
    require(session, actor_user, MANAGE_PERMISSIONS[action])
    if is_super_admin(actor_user):
        return
    if not in_scope(session, actor_user, target_office):
        raise Forbidden("the user is outside your offices")
    if target_role is not None and _as_role(target_role) not in DELEGABLE_ROLES:
        raise Forbidden(
            f"only a super admin may create or change users of type {_as_role(target_role).value}"
        )
    if functions:
        missing = {p.value for p in functions} - {p.value for p in effective_permissions(session, actor_user)}
        if missing:
            raise Forbidden("you cannot grant functions you do not hold: " + ", ".join(sorted(missing)))


# ------------------------------------------------------------------------------------------------ changes


def _event(session: Session, kind: EventType, payload: dict, key: str) -> None:
    if session.scalar(select(Event.id).where(Event.dedupe_key == key)) is None:
        session.add(Event(type=kind, payload=payload, dedupe_key=key, visibility=EventVisibility.SCOPED))


def set_type(session: Session, actor: Actor, actor_user: User, user: User, role: Role | str) -> User:
    role = _as_role(role)
    office = session.get(Office, user.office_id)
    assert_can_manage(session, actor_user, "set_type", target_office=office, target_role=role)
    if not is_super_admin(actor_user) and _as_role(user.role) not in DELEGABLE_ROLES:
        raise Forbidden("only a super admin may change this user's type")
    before = user_summary(user)
    user.role = role
    user.updated_by = actor.user_id
    session.flush()
    write_audit(session, actor, "user.set_type", "user", user.id, before=before, after=user_summary(user))
    _event(
        session,
        EventType.USER_UPDATED,
        {"user_id": str(user.id), "role": role.value},
        f"user_type:{user.id}:{datetime.now(UTC).isoformat()}",
    )
    return user


def set_enabled(session: Session, actor: Actor, actor_user: User, user: User, enabled: bool) -> User:
    office = session.get(Office, user.office_id)
    assert_can_manage(session, actor_user, "enable_disable", target_office=office, target_role=user.role)
    if user.id == actor_user.id and not enabled:
        raise Forbidden("you cannot disable yourself")
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
    actor_user: User,
    user: User,
    permission: Permission | str,
    effect: PermissionEffect | None,
    *,
    reason: str | None = None,
) -> UserPermission | None:
    """Grant or deny one function for one user; `effect=None` ends the override. Denying a super admin is
    refused."""
    permission = _as_perm(permission)
    office = session.get(Office, user.office_id)
    assert_can_manage(
        session,
        actor_user,
        "grant",
        target_office=office,
        target_role=user.role,
        functions={permission} if effect == PermissionEffect.GRANT else None,
    )
    if is_super_admin(user) and effect == PermissionEffect.DENY:
        raise Forbidden("a super admin cannot be denied a function")
    row = session.scalar(
        select(UserPermission).where(
            UserPermission.user_id == user.id, UserPermission.permission == permission
        )
    )
    before = None if row is None else {"effect": row.effect.value, "is_active": row.is_active}
    if effect is None:
        if row is None:
            return None
        row.is_active, row.deactivated_at, row.valid_to = False, datetime.now(UTC), date.today()
    else:
        if row is None:
            row = UserPermission(user_id=user.id, permission=permission, effect=effect)
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
        after={"user_id": str(user.id), "permission": permission.value, **after},
    )
    _event(
        session,
        EventType.ACCESS_CHANGED,
        {"user_id": str(user.id), "permission": permission.value, **after},
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
        out[Role.SUPER_ADMIN.value] = {p.value: True for p in Permission}
    return out


def set_matrix(
    session: Session,
    actor: Actor,
    actor_user: User,
    role: Role | str,
    permission: Permission | str,
    enabled: bool,
) -> RolePermission:
    require(session, actor_user, Permission.ACCESS_MANAGE_TYPES)
    role, permission = _as_role(role), _as_perm(permission)
    if role == Role.SUPER_ADMIN:
        raise Forbidden("the super admin type always has every function")
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
    return Actor(
        user_id=user.id,
        name=user.full_name,
        designation=user.designation,
        office_code=office.code if office else None,
        ip=ip,
        user_agent=user_agent,
    )
