"""`aslms data-load status | coverage | start | pause | resume | order | dedupe` (design `data-load-console`,
decision 20). Every action acts as the single active super admin through its super-admin membership (the `system`
actor before one exists) and is audited, as the API's actions are. `status` and `coverage` read only."""

from __future__ import annotations

import json
from datetime import date

import typer
from rich import print as rprint
from rich.table import Table

from aslms.core.config import get_settings
from aslms.db.session import session_scope
from aslms.domain.ops import LoadOrder
from aslms.services import data_load
from aslms.services.access import Forbidden

data_load_app = typer.Typer(
    no_args_is_help=True, help="The backdated NAPIX load: progress, start, pause, order"
)

REFUSED = (Forbidden, data_load.LoadInputError, data_load.LoadConflict, data_load.SearchTimeout)


def _cli_actor(session):
    from aslms.cli.pipeline import _cli_actor as actor_of

    return actor_of(session)


def _date(value: str | None) -> date | None:
    from aslms.cli.main import parse_cli_date

    return parse_cli_date(value)


def _refused(exc: Exception) -> typer.BadParameter:
    extra = getattr(exc, "extra", None)
    tail = f" {json.dumps(extra, default=str)}" if extra else ""
    return typer.BadParameter(f"{getattr(exc, 'code', 'refused')}: {exc}{tail}")


@data_load_app.command("status")
def status() -> None:
    """The progress block as JSON (what `GET /admin/data-load` returns)."""
    settings = get_settings()
    with session_scope() as s:
        out = data_load.progress(s, settings)
    print(json.dumps(out, default=str, indent=2, ensure_ascii=False))


@data_load_app.command("coverage")
def coverage(
    from_: str | None = typer.Option(None, "--from", help="first month, YYYY-MM (default: the load period)"),
    to: str | None = typer.Option(None, "--to", help="last month, YYYY-MM"),
) -> None:
    """Coverage month by month."""
    settings = get_settings()
    with session_scope() as s:
        try:
            months = data_load.coverage(s, settings, from_, to)
        except REFUSED as exc:
            raise _refused(exc) from exc
    table = Table(
        "month", "days", "covered %", "lists", "entries", "cases", "details %", "orders", "left", "failed"
    )
    for m in months:
        table.add_row(
            m["month"],
            str(m["days"]["calendar"]),
            f"{m['days_covered_pct']:.1f}",
            str(m["lists"]),
            str(m["entries"]),
            str(m["cases"]["listed"]),
            "-" if m["details_pct"] is None else f"{m['details_pct']:.1f}",
            f"{m['orders']['stored']}/{m['orders']['referenced']}",
            str(sum(m["work_left"].values())),
            str(sum(m["failed"].values())),
        )
    rprint(table)


@data_load_app.command("start")
def start(
    from_: str = typer.Option(..., "--from", help="first list date (YYYY-MM-DD)"),
    to: str = typer.Option(..., "--to", help="last list date (YYYY-MM-DD, yesterday at the latest)"),
    refetch_held: bool = typer.Option(False, "--refetch-held", help="queue days already held again"),
) -> None:
    """Queue every cause-list day of the range in the load lane (days already held are skipped unless
    `--refetch-held`)."""
    with session_scope() as s:
        actor, member = _cli_actor(s)
        try:
            res = data_load.start(
                s, actor, member, _date(from_), _date(to), "refetch" if refetch_held else "skip"
            )
        except REFUSED as exc:
            raise _refused(exc) from exc
    rprint(res.as_dict())


@data_load_app.command("pause")
def pause(reason: str = typer.Option(..., "--reason", help="why (3-500 characters)")) -> None:
    """Pause the backdated load (the daily cycle and requests keep running)."""
    with session_scope() as s:
        actor, member = _cli_actor(s)
        try:
            out = data_load.pause(s, actor, member, reason)
        except REFUSED as exc:
            raise _refused(exc) from exc
    rprint(f"paused (version {out.version})")


@data_load_app.command("resume")
def resume(reason: str | None = typer.Option(None, "--reason")) -> None:
    """Resume the backdated load."""
    with session_scope() as s:
        actor, member = _cli_actor(s)
        try:
            out = data_load.resume(s, actor, member, reason)
        except REFUSED as exc:
            raise _refused(exc) from exc
    rprint(f"running (version {out.version})")


@data_load_app.command("order")
def order(
    preset: str = typer.Option(..., "--preset", help="cases_first | lists_first | cases_with_orders"),
    first_from: str | None = typer.Option(None, "--first-from", help="period to bring forward: first day"),
    first_to: str | None = typer.Option(None, "--first-to", help="period to bring forward: last day"),
    reason: str = typer.Option(..., "--reason"),
) -> None:
    """What goes first; every pending load row is re-prioritised."""
    if preset not in {o.value for o in LoadOrder}:
        raise typer.BadParameter("preset is cases_first, lists_first or cases_with_orders")
    with session_scope() as s:
        actor, member = _cli_actor(s)
        try:
            out, n = data_load.set_order(s, actor, member, preset, _date(first_from), _date(first_to), reason)
        except REFUSED as exc:
            raise _refused(exc) from exc
    rprint(f"{out.load_order} (version {out.version}); {n} pending load rows re-prioritised")


@data_load_app.command("dedupe")
def dedupe(dry_run: bool = typer.Option(False, "--dry-run", help="print the pairs; write nothing")) -> None:
    """Run the duplicate rules over every case (merge provisional rows, link court duplicates, list for review)."""
    with session_scope() as s:
        actor, member = _cli_actor(s)
        try:
            report = data_load.scan(s, actor, member, dry_run=dry_run)
        except REFUSED as exc:
            raise _refused(exc) from exc
        if dry_run:
            s.rollback()
    table = Table("kind", "case", "cnr", "case no", "other", "other cnr", "other case no")
    for p in report.pairs:
        table.add_row(
            p["kind"],
            p["case"]["ref_no"],
            p["case"]["cnr"] or "",
            p["case"]["case_no_text"] or "",
            p["other"]["ref_no"],
            p["other"]["cnr"] or "",
            p["other"]["case_no_text"] or "",
        )
    rprint(table)
    rprint({**report.counts(), "dry_run": dry_run})
