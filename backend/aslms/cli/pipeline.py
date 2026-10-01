"""Pipeline commands: `load`, `queue-run`, `queue-status`, `sync-masters`, `refetch-date`, `refetch-case`."""

from __future__ import annotations

import asyncio
from datetime import date

import typer
from rich import print as rprint
from rich.table import Table

from aslms.core.config import get_settings
from aslms.db.session import get_sessionmaker, session_scope
from aslms.domain.ops import FetchKind
from aslms.services import queue
from aslms.services.napix_store import NapixRecorder
from aslms.services.runner import enqueue_days, open_hc, run_queue


def _date(s: str) -> date:
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return (
                date.fromisoformat(s) if fmt == "%Y-%m-%d" else date(int(s[6:10]), int(s[3:5]), int(s[0:2]))
            )
        except ValueError:
            continue
    raise typer.BadParameter(f"not a date: {s}")


def load(
    from_date: str = typer.Option(..., "--from", help="first list date (YYYY-MM-DD)"),
    to_date: str | None = typer.Option(None, "--to", help="last list date (default: today)"),
    requeue: bool = typer.Option(False, "--requeue", help="re-run days already done"),
) -> None:
    """Enqueue one cause-list day per calendar day; `queue-run` does the fetching."""
    start, end = _date(from_date), _date(to_date) if to_date else date.today()
    with session_scope() as s:
        queue.enqueue(s, FetchKind.MASTERS, "all", queue.PRIORITY["masters"], requeue=True)
        n = enqueue_days(s, start, end, requeue=requeue)
    rprint(f"[green]queued {n} days {start} → {end} (plus a masters sync)[/green]")


def queue_run(
    max_items: int | None = typer.Option(None, "--max-items", help="stop after this many rows"),
    kinds: list[str] | None = typer.Option(
        None, "--kind", help="only these kinds (masters, causelist_day, dossier, …)"
    ),
) -> None:
    """Pull queue rows in priority order until the queue is empty or the rate budget is spent."""
    ks = [FetchKind(k) for k in kinds] if kinds else None
    s = get_settings()
    if not s.napix_configured:
        rprint("[yellow]NAPIX_ENABLED is off: only website cause-list days can run[/yellow]")
    report = run_queue(get_sessionmaker(), max_items=max_items, kinds=ks, settings=s)
    rprint(
        f"processed {report.processed}: done {report.done}, skipped {report.skipped}, failed {report.failed}; "
        f"NAPIX calls {report.calls}; stopped: {report.stopped_reason}"
    )


def queue_status() -> None:
    """Rows per kind and status."""
    with session_scope() as s:
        rows = queue.status_counts(s)
    table = Table("kind", "status", "rows")
    for k, st, c in rows:
        table.add_row(k, st, str(c))
    rprint(table)


def sync_masters_cmd() -> None:
    """Fetch the five NAPIX masters now (about five calls)."""
    from aslms.services.masters import sync_masters

    settings = get_settings()
    if not settings.napix_configured:
        raise typer.BadParameter("NAPIX is off or not configured")

    async def go() -> None:
        client, hc = open_hc(settings)
        rec = NapixRecorder()
        client.on_call = rec.on_call
        async with client:
            with session_scope() as s:
                rep = await sync_masters(s, hc)
                rec.flush(s)
        for master, c in rep.counts.items():
            rprint(
                f"  {master:<10} rows {c['rows']:>5}  +{c['inserted']}  ~{c['updated']}  -{c['deactivated']}"
            )

    asyncio.run(go())


def refetch_date(list_date: str = typer.Argument(..., help="YYYY-MM-DD")) -> None:
    """Queue a cause-list day again at top priority."""
    d = _date(list_date)
    with session_scope() as s:
        queue.enqueue(s, FetchKind.CAUSELIST_DAY, d.isoformat(), queue.PRIORITY["list_today"], requeue=True)
    rprint(f"queued {d}")


def refetch_case(cnr: str = typer.Argument(..., help="the CNR")) -> None:
    """Queue a dossier fetch for one case at high priority."""
    with session_scope() as s:
        queue.enqueue(s, FetchKind.DOSSIER, cnr.strip().upper(), queue.PRIORITY["status"], requeue=True)
    rprint(f"queued dossier {cnr.strip().upper()}")
