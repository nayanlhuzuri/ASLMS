"""`aslms users …` and `aslms access …`: user and access administration from the command line. The CLI acts as
the super admin named in `.env` (or, before one exists, as `system`) and audits every change as such."""

from __future__ import annotations

import typer
from rich import print as rprint
from rich.table import Table
from sqlalchemy import select

from aslms.core.config import get_settings
from aslms.db.session import session_scope
from aslms.domain.org import Office, PermissionEffect, User
from aslms.domain.reference import Permission, Role
from aslms.services import access
from aslms.services.audit import Actor
from aslms.services.users import UserError, create_user, set_password, user_summary

users_app = typer.Typer(no_args_is_help=True, help="Users: create, type, enable/disable, functions")
access_app = typer.Typer(no_args_is_help=True, help="Access: the type matrix")


def _actor(session) -> tuple[Actor, User | None]:
    s = get_settings()
    if s.aslms_superadmin_email:
        user = session.scalar(select(User).where(User.email == s.aslms_superadmin_email.strip().lower()))
        if user is not None:
            office = session.get(Office, user.office_id)
            return access.actor_for(user, office), user
    return Actor.system("cli"), None


def _user(session, email: str) -> User:
    user = session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        raise typer.BadParameter(f"no user {email}")
    return user


def _office(session, code: str) -> Office:
    office = session.scalar(select(Office).where(Office.code == code.strip().upper()))
    if office is None:
        raise typer.BadParameter(f"no office {code}")
    return office


@users_app.command("create-super-admin")
def create_super_admin(
    email: str = typer.Option(..., "--email"),
    full_name: str = typer.Option("Super Administrator", "--name"),
    password: str = typer.Option(..., "--password", prompt=True, hide_input=True, confirmation_prompt=True),
) -> None:
    """Create a super admin (the root office GOA). Only from the command line."""
    with session_scope() as s:
        root = _office(s, "GOA")
        try:
            user = create_user(
                s,
                Actor.system("cli"),
                email=email,
                password=password,
                full_name=full_name,
                role=Role.SUPER_ADMIN,
                office=root,
            )
        except UserError as exc:
            raise typer.BadParameter(str(exc)) from exc
        rprint(f"[green]created super admin {user.email}[/green]")


@users_app.command("create")
def create(
    email: str = typer.Option(..., "--email"),
    full_name: str = typer.Option(..., "--name"),
    role: str = typer.Option(..., "--type", help="user type: " + ", ".join(r.value for r in Role)),
    office: str = typer.Option(..., "--office", help="office code"),
    designation: str | None = typer.Option(None, "--designation"),
    password: str = typer.Option(..., "--password", prompt=True, hide_input=True, confirmation_prompt=True),
) -> None:
    """Create a user with a type in an office (acting as the super admin from .env)."""
    with session_scope() as s:
        actor, actor_user = _actor(s)
        off = _office(s, office)
        try:
            r = Role(role)
        except ValueError as exc:
            raise typer.BadParameter(f"unknown type {role}") from exc
        if actor_user is not None:
            access.assert_can_manage(s, actor_user, "create", target_office=off, target_role=r)
        try:
            user = create_user(
                s,
                actor,
                email=email,
                password=password,
                full_name=full_name,
                role=r,
                office=off,
                designation=designation,
            )
        except UserError as exc:
            raise typer.BadParameter(str(exc)) from exc
        rprint(f"[green]created {user.email} ({r.value}, {off.code})[/green]")


@users_app.command("list")
def list_users(office: str | None = typer.Option(None, "--office")) -> None:
    with session_scope() as s:
        stmt = select(User).order_by(User.email)
        if office:
            ids = [o.id for o in access.office_subtree(s, _office(s, office).id)]
            stmt = stmt.where(User.office_id.in_(ids))
        table = Table("email", "name", "type", "office", "active")
        for u in s.scalars(stmt).all():
            off = s.get(Office, u.office_id)
            table.add_row(
                u.email,
                u.full_name,
                str(u.role.value),
                off.code if off else "?",
                "yes" if u.is_active else "no",
            )
        rprint(table)


@users_app.command("set-type")
def set_type(email: str, role: str) -> None:
    with session_scope() as s:
        actor, actor_user = _actor(s)
        user = _user(s, email)
        if actor_user is None:
            raise typer.BadParameter("a super admin in .env is required")
        access.set_type(s, actor, actor_user, user, Role(role))
        rprint(f"{email} is now {role}")


@users_app.command("enable")
def enable(email: str) -> None:
    _toggle(email, True)


@users_app.command("disable")
def disable(email: str) -> None:
    _toggle(email, False)


def _toggle(email: str, enabled: bool) -> None:
    with session_scope() as s:
        actor, actor_user = _actor(s)
        if actor_user is None:
            raise typer.BadParameter("a super admin in .env is required")
        access.set_enabled(s, actor, actor_user, _user(s, email), enabled)
        rprint(f"{email} {'enabled' if enabled else 'disabled'}")


@users_app.command("grant")
def grant(email: str, permission: str, reason: str | None = typer.Option(None, "--reason")) -> None:
    _override(email, permission, PermissionEffect.GRANT, reason)


@users_app.command("deny")
def deny(email: str, permission: str, reason: str | None = typer.Option(None, "--reason")) -> None:
    _override(email, permission, PermissionEffect.DENY, reason)


@users_app.command("revoke")
def revoke(email: str, permission: str) -> None:
    """End a grant or deny: the user falls back to their type's functions."""
    _override(email, permission, None, None)


def _override(email: str, permission: str, effect: PermissionEffect | None, reason: str | None) -> None:
    with session_scope() as s:
        actor, actor_user = _actor(s)
        if actor_user is None:
            raise typer.BadParameter("a super admin in .env is required")
        access.set_override(
            s, actor, actor_user, _user(s, email), Permission(permission), effect, reason=reason
        )
        rprint(f"{email}: {permission} {'reset' if effect is None else effect.value}")


@users_app.command("functions")
def functions(email: str) -> None:
    """The user's effective functions."""
    with session_scope() as s:
        user = _user(s, email)
        perms = sorted(p.value for p in access.effective_permissions(s, user))
        rprint(user_summary(user))
        rprint("\n".join(perms) or "(none)")


@users_app.command("set-password")
def set_password_cmd(
    email: str,
    password: str = typer.Option(..., "--password", prompt=True, hide_input=True, confirmation_prompt=True),
) -> None:
    with session_scope() as s:
        actor, _ = _actor(s)
        set_password(s, actor, _user(s, email), password)
        rprint(f"password set for {email}")


@access_app.command("matrix")
def matrix(role: str | None = typer.Argument(None)) -> None:
    """The type matrix (all types, or one)."""
    with session_scope() as s:
        m = access.matrix(s, Role(role) if role else None)
    roles = sorted(m)
    table = Table("function", *roles)
    for perm in Permission:
        table.add_row(perm.value, *("on" if m.get(r, {}).get(perm.value) else "-" for r in roles))
    rprint(table)


@access_app.command("set")
def set_cmd(role: str, permission: str, state: str = typer.Argument(..., help="on | off")) -> None:
    """Switch one function on or off for a type (super admin from .env)."""
    with session_scope() as s:
        actor, actor_user = _actor(s)
        if actor_user is None:
            raise typer.BadParameter("a super admin in .env is required")
        access.set_matrix(s, actor, actor_user, Role(role), Permission(permission), state.lower() == "on")
        rprint(f"{role}: {permission} {state}")
