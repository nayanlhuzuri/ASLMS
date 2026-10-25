"""`aslms users …` and `aslms access …`: user and access administration from the command line. The CLI acts as
the single active super admin (design `user-memberships`, decision 13; before one exists, as `system`) and
audits every change as such. `create-super-admin` works only on a system with none; `replace-super-admin` is
the only way to change it. `aslms users memberships add|end|list` manage memberships (a head through the
head-change service, recorded as an approved ticket)."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich import print as rprint
from rich.table import Table
from sqlalchemy import select

from aslms.db.session import session_scope
from aslms.domain.org import Office, PermissionEffect, User
from aslms.domain.reference import Permission, Role
from aslms.services import access, memberships, tickets
from aslms.services.access import Conflict, Forbidden
from aslms.services.audit import Actor
from aslms.services.memberships import MembershipError
from aslms.services.tickets import TicketError
from aslms.services.users import UserError, create_user, set_password, user_summary

users_app = typer.Typer(no_args_is_help=True, help="Users: create, type, enable/disable, functions")
access_app = typer.Typer(no_args_is_help=True, help="Access: the type matrix")
memberships_app = typer.Typer(no_args_is_help=True, help="Memberships: add, end, list")
users_app.add_typer(memberships_app, name="memberships")
REFUSED = (Forbidden, Conflict, MembershipError, TicketError, UserError)


def _actor(session) -> tuple[Actor, User | None]:
    """The single active super admin (decision 13), or `system` before one exists."""
    current = memberships.super_admin_membership(session)
    if current is not None:
        user = session.get(User, current.user_id)
        if user is not None and user.is_active:
            return access.actor_for(user), user
    return Actor.system("cli"), None


def _refused(exc: Exception) -> typer.BadParameter:
    code = getattr(exc, "code", None)
    return typer.BadParameter(f"{code}: {exc}" if code else str(exc))


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
    """Create the super admin (the root office GOA) on a system that has none. Only from the command line;
    to change it, use replace-super-admin."""
    with session_scope() as s:
        current = memberships.super_admin_membership(s)
        if current is not None:
            holder = s.get(User, current.user_id)
            raise typer.BadParameter(f"a super admin exists ({holder.email}); use replace-super-admin")
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


@users_app.command("replace-super-admin")
def replace_super_admin(
    email: str = typer.Option(..., "--email"),
    full_name: str | None = typer.Option(None, "--name"),
    designation: str | None = typer.Option(None, "--designation"),
) -> None:
    """Replace the super admin in one transaction: the current one is ended, its login disabled and its
    sessions revoked; the new one is a new login (password prompted, never echoed) or an existing login that
    holds no membership."""
    with session_scope() as s:
        existing = memberships.lookup(s, email)
        password = None
        if existing is None:
            password = typer.prompt("Password for the new login", hide_input=True, confirmation_prompt=True)
        try:
            old, new = memberships.replace_super_admin(
                s, email=email, name=full_name, designation=designation, password=password
            )
        except REFUSED as exc:
            raise _refused(exc) from exc
        rprint(f"[green]super admin replaced: {old.email} -> {new.email}[/green]")


@users_app.command("create")
def create(
    email: str = typer.Option(..., "--email"),
    full_name: str = typer.Option(..., "--name"),
    role: str = typer.Option(..., "--type", help="user type: " + ", ".join(r.value for r in Role)),
    office: str = typer.Option(..., "--office", help="office code"),
    designation: str | None = typer.Option(None, "--designation"),
    password: str = typer.Option(..., "--password", prompt=True, hide_input=True, confirmation_prompt=True),
) -> None:
    """Create a user with a type in an office (acting as the super admin)."""
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
    """One row per active membership (a login with several memberships has several rows)."""
    with session_scope() as s:
        ids = {o.id for o in access.office_subtree(s, _office(s, office).id)} if office else None
        table = Table("email", "name", "type", "office", "designation", "primary", "active")
        for u in s.scalars(select(User).order_by(User.email)).all():
            ms = access.active_memberships(s, u)
            if not ms and ids is None:
                table.add_row(u.email, u.full_name, "-", "-", "-", "-", "yes" if u.is_active else "no")
            for m in ms:
                if ids is not None and m.office_id not in ids:
                    continue
                off = s.get(Office, m.office_id)
                table.add_row(
                    u.email,
                    u.full_name,
                    str(Role(m.role).value),
                    off.code if off else "?",
                    m.designation or "",
                    "yes" if m.is_primary else "",
                    "yes" if u.is_active else "no",
                )
        rprint(table)


@users_app.command("set-type")
def set_type(email: str, role: str) -> None:
    with session_scope() as s:
        actor, actor_user = _actor(s)
        user = _user(s, email)
        if actor_user is None:
            raise typer.BadParameter("there is no super admin yet; create-super-admin first")
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
            raise typer.BadParameter("there is no super admin yet; create-super-admin first")
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
            raise typer.BadParameter("there is no super admin yet; create-super-admin first")
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
    """Set a login's password (the policy applies); the person must change it at the next sign-in and every
    session of the login ends (design `otp-and-profile`, decisions 9, 14)."""
    with session_scope() as s:
        actor, _ = _actor(s)
        try:
            set_password(s, actor, _user(s, email), password)
        except UserError as exc:
            raise typer.BadParameter(str(exc)) from exc
        rprint(f"password set for {email}; it must be changed at the next sign-in")


@users_app.command("sign-out")
def sign_out(email: str = typer.Option(..., "--email")) -> None:
    """Revoke every refresh token and device of a login (audited as the super admin)."""
    from aslms.services.auth import sign_out_everywhere

    with session_scope() as s:
        actor, _ = _actor(s)
        counts = sign_out_everywhere(s, actor, _user(s, email))
        rprint(
            f"{email} signed out: {counts['tokens_revoked']} session(s), {counts['devices_revoked']} device(s)"
        )


@memberships_app.command("list")
def memberships_list(email: str, ended: bool = typer.Option(False, "--ended", help="include ended")) -> None:
    """A login's memberships."""
    with session_scope() as s:
        user = _user(s, email)
        table = Table("id", "office", "type", "designation", "primary", "active", "end reason")
        for m in memberships.memberships_of(s, user, include_ended=ended):
            table.add_row(
                str(m.id),
                s.get(Office, m.office_id).code,
                str(Role(m.role).value),
                m.designation or "",
                "yes" if m.is_primary else "",
                "yes" if m.is_active else "no",
                m.end_reason or "",
            )
        rprint(table)


@memberships_app.command("add")
def memberships_add(
    email: str = typer.Option(..., "--email"),
    office: str = typer.Option(..., "--office"),
    role: str = typer.Option(..., "--type"),
    designation: str | None = typer.Option(None, "--designation"),
) -> None:
    """Add a membership as the super admin. `--type dept_head` goes through the head-change service (applied
    at once, recorded as an approved ticket)."""
    with session_scope() as s:
        actor, actor_user = _actor(s)
        if actor_user is None:
            raise typer.BadParameter("there is no super admin yet; create-super-admin first")
        user = _user(s, email)
        off = _office(s, office)
        try:
            r = Role(role)
        except ValueError as exc:
            raise typer.BadParameter(f"unknown type {role}") from exc
        try:
            if r == Role.DEPT_HEAD:
                current = access.member_in_department(s, user, access.department_of(s, off))
                incoming = (
                    {"membership_id": str(current.membership_id), "designation": designation}
                    if current is not None
                    else {"email": user.email, "designation": designation}
                )
                t = tickets.request_head_change(
                    s,
                    actor,
                    actor_user,
                    {"operation": "set", "department_code": off.code, "incoming": incoming},
                    request_remark="set from the command line",
                )
                rprint(f"[green]{email} is head of {off.code} ({t.ref_no})[/green]")
                return
            m = memberships.add(s, actor, actor_user, user, office=off, role=r, designation=designation)
        except REFUSED as exc:
            raise _refused(exc) from exc
        rprint(f"[green]{email}: {r.value} at {off.code} ({m.id})[/green]")


@memberships_app.command("end")
def memberships_end(
    email: str = typer.Option(..., "--email"),
    office: str = typer.Option(..., "--office", help="the membership's office code"),
    reason: str = typer.Option(..., "--reason"),
    assignments: Path | None = typer.Option(
        None,
        "--assignments",
        help='JSON file: {"items_fingerprint": ..., "assignments": [{"key", "to_membership", ...}]}',
    ),
) -> None:
    """End a membership with the per-item exit (every allotted case and case with them needs a target)."""
    with session_scope() as s:
        actor, actor_user = _actor(s)
        if actor_user is None:
            raise typer.BadParameter("there is no super admin yet; create-super-admin first")
        user = _user(s, email)
        off = _office(s, office)
        m = next((x for x in access.active_memberships(s, user) if x.office_id == off.id), None)
        if m is None:
            raise typer.BadParameter(f"{email} has no active membership at {off.code}")
        items_fp = memberships.fingerprint(memberships.exit_items(s, m))
        plan: list = []
        if assignments is not None:
            data = json.loads(assignments.read_text(encoding="utf-8"))
            if isinstance(data, list):
                plan = data
            else:
                plan = data.get("assignments") or []
                items_fp = data.get("items_fingerprint") or items_fp
        try:
            result = memberships.end(
                s, actor, actor_user, m, reason=reason, assignments=plan, items_fingerprint=items_fp
            )
        except REFUSED as exc:
            extra = getattr(exc, "extra", None)
            if extra:
                rprint(extra)
            raise _refused(exc) from exc
        rprint(f"[yellow]ended {email} at {off.code}: {result.counts}[/yellow]")


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
    """Switch one function on or off for a type (acting as the super admin)."""
    with session_scope() as s:
        actor, actor_user = _actor(s)
        if actor_user is None:
            raise typer.BadParameter("there is no super admin yet; create-super-admin first")
        access.set_matrix(s, actor, actor_user, Role(role), Permission(permission), state.lower() == "on")
        rprint(f"{role}: {permission} {state}")
