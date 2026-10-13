"""`aslms discovery status | terms | sweep` (design `department-discovery`). `status` prints the Data collection
block as JSON (what `GET /admin/discovery` returns); `terms` lists the terms with their departments; `sweep` queues
every active term, or one with `--term`, for 2025 to the current year, acting as the single active super admin
(the `system` actor before one exists), audited `discovery.sweep` as the API's sweep is. Nothing here calls NAPIX:
the worker runs the queued searches within the discovery share."""

from __future__ import annotations

import json

import typer
from rich import print as rprint
from rich.table import Table
from sqlalchemy import select

from aslms.core.config import get_settings
from aslms.db.session import session_scope
from aslms.domain.ownership import DiscoveryTerm
from aslms.services import access, discovery
from aslms.services.access import Forbidden
from aslms.services.offices import find_office

discovery_app = typer.Typer(
    no_args_is_help=True, help="Department discovery: party-name searches of the departments' terms"
)
REFUSED = (Forbidden, discovery.DiscoveryError, discovery.DiscoveryNotFound, discovery.DiscoveryConflict)


def _refused(exc: Exception) -> typer.BadParameter:
    return typer.BadParameter(f"{getattr(exc, 'code', 'refused')}: {exc}")


@discovery_app.command("status")
def status() -> None:
    """The discovery block as JSON: the share and this window's discovery calls, queue rows, terms, cases."""
    with session_scope() as s:
        out = discovery.summary(s, get_settings())
    print(json.dumps(out, default=str, indent=2, ensure_ascii=False))


@discovery_app.command("terms")
def terms(
    office: str | None = typer.Option(
        None, "--office", help="only terms with an active rule in this subtree"
    ),
    all_: bool = typer.Option(False, "--all", help="inactive terms too"),
) -> None:
    """Every term with its departments, last search, searches done and cases found."""
    with session_scope() as s:
        root = None
        if office:
            root = find_office(s, office)
            if root is None:
                raise typer.BadParameter(f"no such office {office!r}")
        rows = s.scalars(select(DiscoveryTerm).order_by(DiscoveryTerm.term)).all()
        active = discovery.active_departments(s, [r.term for r in rows])
        table = Table("term", "active", "departments", "last searched", "searches", "cases found")
        for r in rows:
            depts = active.get(r.term, [])
            if root is not None and not any(
                access.subtree_contains(root, d) or access.subtree_contains(d, root) for d in depts
            ):
                continue
            if not depts and not all_:
                continue
            table.add_row(
                r.term,
                "yes" if depts else "no",
                ", ".join(d.code for d in depts) or "-",
                str(r.last_searched_at or "-"),
                str(r.searches_done),
                str(r.cases_found),
            )
    rprint(table)


@discovery_app.command("sweep")
def sweep(
    term: str | None = typer.Option(None, "--term", help="one term (its text), else every active term"),
) -> None:
    """Queue a sweep (2025 to the current year); audited `discovery.sweep`."""
    from aslms.cli.pipeline import _cli_actor

    with session_scope() as s:
        actor, member = _cli_actor(s)
        try:
            out = discovery.sweep(s, actor, member, term_text=term, settings=get_settings())
        except REFUSED as exc:
            raise _refused(exc) from exc
    rprint(f"queued {out['rows_queued']} party-name searches for {out['terms']} term(s)")
