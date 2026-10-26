"""`aslms offices …`: departments, directorates and units from the command line, so a fresh deployment can be
bootstrapped without the portal. Acts as the single active super admin (required: every office write is
attributed and audited to a user). A department is created with its head (`--head-email`, an existing login,
including one created with `aslms users create --no-office`; design `office-head-picker`, decision 21);
`list --missing-head` lists departments without one."""

from __future__ import annotations

import typer
from rich import print as rprint
from rich.tree import Tree

from aslms.cli.users import _actor, _office
from aslms.db.session import session_scope
from aslms.domain.reference import OfficeKind
from aslms.services import memberships, offices
from aslms.services.access import Conflict, Forbidden
from aslms.services.memberships import MembershipError
from aslms.services.offices import DEPARTMENT_TIER_KINDS, OfficeError
from aslms.services.tickets import TicketError
from aslms.services.users import UserError

offices_app = typer.Typer(no_args_is_help=True, help="Offices: create, list, deactivate")


def _super_admin(session):
    actor, actor_user = _actor(session)
    if actor_user is None:
        raise typer.BadParameter("there is no super admin yet; run `aslms users create-super-admin` first")
    return actor, actor_user


@offices_app.command("create")
def create(
    code: str = typer.Option(..., "--code", help="the Secretariat's code, e.g. EDU or EDU-DSE"),
    name: str = typer.Option(..., "--name"),
    kind: str = typer.Option(..., "--kind", help="one of: " + ", ".join(k.value for k in OfficeKind)),
    parent: str = typer.Option(..., "--parent", help="parent office code (GOA for a department)"),
    notes: str | None = typer.Option(None, "--notes"),
    head_email: str | None = typer.Option(
        None, "--head-email", help="the head, an existing login (required for a department)"
    ),
    head_designation: str | None = typer.Option(None, "--head-designation"),
) -> None:
    """Create an office under a parent (acting as the super admin). A Department-tier office needs its head: an
    existing login by e-mail, including one with no office yet."""
    with session_scope() as s:
        actor, actor_user = _super_admin(s)
        head = None
        try:
            dept_tier = OfficeKind(kind) in DEPARTMENT_TIER_KINDS
        except ValueError:
            dept_tier = False
        if dept_tier:
            if not head_email:
                raise typer.BadParameter(
                    "head_required: a department is created with its head (--head-email)"
                )
            if memberships.lookup(s, head_email) is None:
                raise typer.BadParameter(
                    f"no login {head_email}: add the person first with `aslms users create --no-office`"
                )
            head = {"email": head_email, "designation": head_designation}
        try:
            office = offices.create_office(
                s,
                actor,
                actor_user,
                code=code,
                name=name,
                kind=kind,
                parent=_office(s, parent),
                notes=notes,
                head={k: v for k, v in head.items() if v is not None} if head else None,
            )
        except (OfficeError, Forbidden, Conflict, MembershipError, TicketError, UserError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        rprint(f"[green]created {office.code} ({office.kind.value}) at {office.path}[/green]")


@offices_app.command("list")
def list_offices(
    root: str = typer.Option("GOA", "--root", help="office code to start from"),
    include_inactive: bool = typer.Option(True, "--all/--active-only", help="show deactivated offices"),
    missing_head: bool = typer.Option(False, "--missing-head", help="only departments without a head"),
) -> None:
    """Print the office tree; deactivated offices are marked. `--missing-head`: the departments without a
    head (design `user-memberships`, decision 24)."""
    with session_scope() as s:
        if missing_head:
            rows = offices.departments_without_head(s)
            for o in rows:
                rprint(f"{o.code}  {o.name}")
            rprint(f"[bold]{len(rows)}[/bold] department(s) without a head")
            return
        top = offices.office_tree(s, [_office(s, root)], include_inactive=include_inactive)

        def add(branch: Tree, node: offices.OfficeNode) -> None:
            o = node.office
            state = "" if o.is_active else " [red](inactive)[/red]"
            users = f" [dim]{node.users_active} users[/dim]" if node.users_active else ""
            leaf = branch.add(
                f"[bold]{o.code}[/bold] {o.name} [dim]({o.kind.value}, {node.tier})[/dim]{users}{state}"
            )
            for child in node.children:
                add(leaf, child)

        for node in top:
            tree = Tree(
                f"[bold]{node.office.code}[/bold] {node.office.name} [dim]({node.office.kind.value})[/dim]"
                + ("" if node.office.is_active else " [red](inactive)[/red]")
            )
            for child in node.children:
                add(tree, child)
            rprint(tree)


@offices_app.command("deactivate")
def deactivate(code: str) -> None:
    """Deactivate an office (refused while children, memberships, ownership or custody still point at it)."""
    with session_scope() as s:
        actor, actor_user = _super_admin(s)
        try:
            office = offices.deactivate_office(s, actor, actor_user, _office(s, code))
        except (OfficeError, Forbidden) as exc:
            raise typer.BadParameter(str(exc)) from exc
        rprint(f"[yellow]{office.code} deactivated (valid_to {office.valid_to})[/yellow]")
