"""`aslms cases reindex-search [--all | --case REF]` and `aslms cases show REF --as EMAIL` (design cases-api):
the derived search vector re-run by hand (repairs after a restore or a function change), and the visibility
check the integrator uses — which bases make a case visible to a user."""

from __future__ import annotations

import typer
from rich import print as rprint
from sqlalchemy import select

from aslms.db.session import session_scope
from aslms.domain.cases import Case
from aslms.domain.org import User
from aslms.services import visibility
from aslms.services.cases import CaseNotFound, refresh_search_vector, resolve_case_ref

cases_app = typer.Typer(no_args_is_help=True, help="Cases: search index repair, visibility check")


@cases_app.command("reindex-search")
def reindex_search(
    all_cases: bool = typer.Option(False, "--all", help="recompute the search vector of every case"),
    case: str | None = typer.Option(None, "--case", help="one case: id, ref_no (slash or dash form) or CNR"),
    batch: int = typer.Option(1000, "--batch", min=1, max=10000),
) -> None:
    """Re-run `aslms_case_search_vector` for one case or for all (in batches, one transaction each)."""
    if bool(all_cases) == bool(case):
        raise typer.BadParameter("give exactly one of --all or --case REF")
    if case:
        with session_scope() as s:
            try:
                row = resolve_case_ref(s, case)
            except CaseNotFound as exc:
                raise typer.BadParameter(str(exc)) from exc
            refresh_search_vector(s, [row.id])
            rprint(f"[green]{row.ref_no} reindexed[/green]")
        return
    done = 0
    with session_scope() as s:
        ids = list(s.scalars(select(Case.id).order_by(Case.id)).all())
    for i in range(0, len(ids), batch):
        with session_scope() as s:
            done += refresh_search_vector(s, ids[i : i + batch])
    rprint(f"[green]{done} case(s) reindexed[/green]")


@cases_app.command("show")
def show(
    ref: str = typer.Argument(..., help="case id, ref_no (slash or dash form) or CNR"),
    as_email: str = typer.Option(..., "--as", help="the user whose visibility is checked"),
) -> None:
    """Print the case summary and the visibility bases that make it visible to the user (empty = not visible)."""
    with session_scope() as s:
        try:
            case = resolve_case_ref(s, ref)
        except CaseNotFound as exc:
            raise typer.BadParameter(str(exc)) from exc
        user = s.scalar(select(User).where(User.email == as_email.strip().lower()))
        if user is None:
            raise typer.BadParameter(f"no user {as_email}")
        basis = visibility.access_basis(s, user, case)
        rprint(f"[bold]{case.ref_no}[/bold] {case.case_no_text or ''} {case.cnr or '(no CNR)'}")
        rprint(
            f"status={case.status.value} provisional={case.is_provisional} merged={case.merged_into_case_id}"
        )
        rprint(f"bases for {user.email} ({user.role.value}): {basis}")
        rprint("[green]visible[/green]" if basis else "[red]not visible[/red]")
