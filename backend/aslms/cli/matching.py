"""`aslms rescore [--all | --case REF]` and `aslms codes unmapped [--limit N]` (design recommend-and-claim,
decisions 4 and 19): the matching engine by hand, and the report of counsel codes seen in cause lists and
dossiers that no department has mapped yet. Nothing is mapped automatically."""

from __future__ import annotations

import typer
from rich import print as rprint
from rich.table import Table

from aslms.db.session import get_sessionmaker, session_scope
from aslms.domain.ownership import RecommendationOrigin
from aslms.services import matching
from aslms.services.cases import CaseNotFound, resolve_case_ref

codes_app = typer.Typer(no_args_is_help=True, help="Counsel codes: the unmapped report")


def rescore(
    all_cases: bool = typer.Option(False, "--all", help="rescore every non-merged case (a job_runs row)"),
    case: str | None = typer.Option(None, "--case", help="one case: id, ref_no (slash or dash form) or CNR"),
    batch: int = typer.Option(500, "--batch", min=1, max=5000),
) -> None:
    """Run the matching engine: one case with --case, or everything with --all (the dirty check skipped)."""
    if bool(all_cases) == bool(case):
        raise typer.BadParameter("give exactly one of --all or --case REF")
    if case:
        with session_scope() as s:
            try:
                row = resolve_case_ref(s, case)
            except CaseNotFound as exc:
                raise typer.BadParameter(str(exc)) from exc
            report = matching.rescore_case(s, row, origin=RecommendationOrigin.RESCORE)
            rprint(f"[bold]{row.ref_no}[/bold] scored: {report.as_dict()}")
        return
    report = matching.rescore_all(get_sessionmaker(), batch=batch)
    rprint(f"rescore finished: {report.as_dict()}")


@codes_app.command("unmapped")
def unmapped(limit: int = typer.Option(50, "--limit", min=1, max=1000)) -> None:
    """Counsel codes seen in cause lists and dossiers with no mapping, most frequent first."""
    with session_scope() as s:
        rows = matching.unmapped_codes(s, limit=limit)
    table = Table("code", "entries", "last listed", "example case")
    for r in rows:
        table.add_row(r.code, str(r.entries), str(r.last_listed or ""), r.example_case_ref or "")
    rprint(table)
    rprint(f"{len(rows)} unmapped code(s)")
