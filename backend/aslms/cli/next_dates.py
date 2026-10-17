"""`aslms next-dates read [--batch N] [--all] [--order ID] [--reread [--all-versions]] [--dry-run]` reads the next-date
direction of stored orders by rule (`--all` loops until no candidate is left; `--dry-run` reads and prints counts
without writing); `aslms next-dates status` prints orders by reading status and rule, rows by source and review
status and the queue by kind; `aslms next-dates sample --status S [--rule R] [--n 20] [--seed K]` prints a
reproducible sample for the hand check against the PDFs. Design `next-date-extraction`; no NAPIX or SourceTrace
call."""

from __future__ import annotations

import uuid

import typer
from rich import print as rprint

from aslms.core.config import get_settings
from aslms.db.session import session_scope
from aslms.services import next_dates
from aslms.services.audit import Actor
from aslms.services.workflow_common import WorkflowError

next_dates_app = typer.Typer(no_args_is_help=True, help="Next dates read from orders: read, status, sample")


def _config() -> next_dates.NextDateConfig:
    return next_dates.NextDateConfig.from_settings(get_settings())


@next_dates_app.command("read")
def read(
    batch: int = typer.Option(None, "--batch", min=1, max=5000, help="orders per pass (NEXT_DATE_BATCH)"),
    all_: bool = typer.Option(False, "--all", help="loop until no pending order with text is left"),
    order: str | None = typer.Option(None, "--order", help="one order (its id)"),
    reread: bool = typer.Option(
        False, "--reread", help="first put orders read by an older rules version back"
    ),
    all_versions: bool = typer.Option(False, "--all-versions", help="with --reread: every read order"),
    dry_run: bool = typer.Option(False, "--dry-run", help="read and count; write nothing"),
) -> None:
    """Read pending orders' stored text and record the next dates (one savepoint per order)."""
    cfg = _config()
    order_id = None
    if order:
        try:
            order_id = uuid.UUID(order)
        except ValueError as exc:
            raise typer.BadParameter("--order takes an order id") from exc
    if all_versions and not reread:
        raise typer.BadParameter("--all-versions goes with --reread")
    if dry_run:
        if reread:
            raise typer.BadParameter("--dry-run reads pending orders only; run --reread without it")
        with session_scope() as s:
            out = next_dates.dry_run(s, limit=None if all_ else (batch or cfg.batch), cfg=cfg)
            s.rollback()
        rprint({"dry_run": True, **out})
        return
    if reread:
        with session_scope() as s:
            n = next_dates.reread(s, Actor.system("cli"), all_versions=all_versions)
        rprint(f"{n} order(s) put back to pending (audited next_dates.reread)")
    totals: dict[str, int] = {}
    while True:
        with session_scope() as s:
            counters = next_dates.read_pending(s, batch=batch or cfg.batch, order_id=order_id, cfg=cfg)
        for k, v in counters.items():
            totals[k] = totals.get(k, 0) + v
        if not all_ or order_id is not None or counters["claimed"] == 0:
            break
        if counters["claimed"] == counters["failed"] + counters["skipped"]:
            break  # nothing more can be read in this pass
        rprint(f"... {totals['claimed']} read so far")
    rprint(totals)


@next_dates_app.command("status")
def status() -> None:
    """Orders by reading status and rule; next_dates rows by source and review status; the queue by kind."""
    with session_scope() as s:
        out = next_dates.status_report(s, cfg=_config())
    rprint(f"[bold]rules version[/bold] {out['rules_version']}")
    rprint("[bold]orders[/bold] (status / rule / count)")
    for st, rule, n in out["orders"]:
        rprint(f"  {st:<9} {rule or '-':<24} {n}")
    rprint("[bold]next_dates[/bold] (source / review status / count)")
    for source, review, n in out["rows"]:
        rprint(f"  {source:<15} {review:<11} {n}")
    rprint(f"[bold]queue[/bold] confirm {out['queue']['confirm']}, enter {out['queue']['enter']}")


@next_dates_app.command("sample")
def sample(
    status_: str = typer.Option(..., "--status", help="specific, period, unclear, none or no_text"),
    rule: str | None = typer.Option(None, "--rule", help="one rule, e.g. list_on_date"),
    n: int = typer.Option(20, "--n", min=1, max=200),
    seed: int = typer.Option(1, "--seed"),
) -> None:
    """A reproducible sample of read orders: order date, CNR, reading, date and phrase."""
    with session_scope() as s:
        try:
            rows = next_dates.sample(s, status=status_, rule=rule, n=n, seed=seed)
        except WorkflowError as exc:
            raise typer.BadParameter(str(exc)) from exc
    for r in rows:
        rprint(
            f"{r['order_date']}  {r['cnr'] or '-'}  {r['case_no_text'] or '-'}  order {r['order_no']}  "
            f"{r['status']}/{r['rule'] or '-'}  -> {r['date'] or '-'}  doc {r['document_id']}"
        )
        rprint(f"    {r['phrase'] or ''}")
