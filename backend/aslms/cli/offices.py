"""`aslms offices …`: departments, directorates and units from the command line, so a fresh deployment can be
bootstrapped without the portal. Acts as the super admin named in `.env` (required: every office write is
attributed and audited to a user)."""

from __future__ import annotations

import typer
from rich import print as rprint
from rich.tree import Tree

from aslms.cli.users import _actor, _office
from aslms.db.session import session_scope
from aslms.domain.reference import OfficeKind
from aslms.services import offices
from aslms.services.access import Forbidden
from aslms.services.offices import OfficeError

offices_app = typer.Typer(no_args_is_help=True, help="Offices: create, list, deactivate")


def _super_admin(session):
    actor, actor_user = _actor(session)
    if actor_user is None:
        raise typer.BadParameter("a super admin in .env (ASLMS_SUPERADMIN_EMAIL) is required")
    return actor, actor_user


@offices_app.command("create")
def create(
    code: str = typer.Option(..., "--code", help="the Secretariat's code, e.g. EDU or EDU-DSE"),
    name: str = typer.Option(..., "--name"),
    kind: str = typer.Option(..., "--kind", help="one of: " + ", ".join(k.value for k in OfficeKind)),
    parent: str = typer.Option(..., "--parent", help="parent office code (GOA for a department)"),
    notes: str | None = typer.Option(None, "--notes"),
) -> None:
    """Create an office under a parent (acting as the super admin from .env)."""
    with session_scope() as s:
        actor, actor_user = _super_admin(s)
        try:
            office = offices.create_office(
                s, actor, actor_user, code=code, name=name, kind=kind, parent=_office(s, parent), notes=notes
            )
        except (OfficeError, Forbidden) as exc:
            raise typer.BadParameter(str(exc)) from exc
        rprint(f"[green]created {office.code} ({office.kind.value}) at {office.path}[/green]")


@offices_app.command("list")
def list_offices(
    root: str = typer.Option("GOA", "--root", help="office code to start from"),
    include_inactive: bool = typer.Option(True, "--all/--active-only", help="show deactivated offices"),
) -> None:
    """Print the office tree; deactivated offices are marked."""
    with session_scope() as s:
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
    """Deactivate an office (refused while children, users, ownership or custody still point at it)."""
    with session_scope() as s:
        actor, actor_user = _super_admin(s)
        try:
            office = offices.deactivate_office(s, actor, actor_user, _office(s, code))
        except (OfficeError, Forbidden) as exc:
            raise typer.BadParameter(str(exc)) from exc
        rprint(f"[yellow]{office.code} deactivated (valid_to {office.valid_to})[/yellow]")
