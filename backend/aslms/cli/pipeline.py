"""Pipeline commands: `load`, `queue-run`, `queue-status`, `sync-masters`, `refetch-date`, `refetch-case`."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import typer
from rich import print as rprint
from rich.table import Table

from aslms.core.config import get_settings
from aslms.db.session import get_sessionmaker, session_scope
from aslms.domain.ops import FetchKind, FetchLane
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
    """Enqueue one cause-list day per calendar day; `queue-run` does the fetching. Days up to yesterday go through
    the data-load service as the backdated load (design `data-load-console`, decision 9: held days are skipped, or
    fetched again with `--requeue`; audited `data_load.started`); today and later belong to the daily cycle."""
    from aslms.services import data_load
    from aslms.services.reporting_common import today_ist

    start, end = _date(from_date), _date(to_date) if to_date else date.today()
    today = today_ist()
    yesterday = today - timedelta(days=1)
    with session_scope() as s:
        actor, member = _cli_actor(s)
        loaded = None
        if start <= yesterday:
            try:
                loaded = data_load.start(
                    s,
                    actor,
                    member,
                    start,
                    min(end, yesterday),
                    "refetch" if requeue else "skip",
                    today=today,
                )
            except (data_load.LoadInputError, data_load.LoadConflict) as exc:
                raise typer.BadParameter(f"{exc.code}: {exc}") from exc
        daily = 0
        if end >= today:
            daily = enqueue_days(s, max(start, today), end, requeue=requeue, lane=FetchLane.DAILY)
        if loaded is None:
            queue.enqueue(s, FetchKind.MASTERS, "all", queue.PRIORITY["masters"], requeue=True)
    if loaded is not None:
        rprint(f"[green]backdated load {start} → {min(end, yesterday)}: {loaded.as_dict()}[/green]")
    if daily:
        rprint(f"[green]queued {daily} days of the daily cycle[/green]")


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


def _cli_actor(session):
    """The single active super admin acting through its super-admin membership (design `audit-screens`, decision
    11), or the `system` actor before one exists."""
    from aslms.cli.users import _actor
    from aslms.services import access

    actor, user = _actor(session)
    member = access.super_admin_member(session, user) if user is not None else None
    return actor, member


def refetch_date(
    list_date: str = typer.Argument(..., help="YYYY-MM-DD"),
    force: bool = typer.Option(False, "--force", help="queue a day already held anyway"),
) -> None:
    """Queue a cause-list day again at top priority (audited `napix.refetch_requested`); a day already held needs
    `--force`."""
    from aslms.services import napix_admin

    d = _date(list_date)
    with session_scope() as s:
        actor, member = _cli_actor(s)
        try:
            state = napix_admin.refetch_day(s, actor, member, d, get_settings(), force=force)
        except (napix_admin.AdminInputError, napix_admin.AdminConflict) as exc:
            raise typer.BadParameter(f"{exc.code}: {exc}") from exc
    rprint(f"queued {d} ({state['status']}, priority {state['priority']})")


def refetch_case(
    ref: str = typer.Argument(..., help="the case: CNR, ref_no or id"),
    force: bool = typer.Option(False, "--force", help="queue a case whose details are held anyway"),
) -> None:
    """Queue a dossier fetch for one case at priority 30 (audited `napix.refetch_requested`); a case whose details
    are held needs `--force`."""
    from aslms.services import napix_admin
    from aslms.services.cases import CaseNotFound, resolve_case_ref

    with session_scope() as s:
        actor, member = _cli_actor(s)
        try:
            case = resolve_case_ref(s, ref)
            state = napix_admin.refetch_case(s, actor, member, case, get_settings(), force=force)
        except CaseNotFound as exc:
            raise typer.BadParameter(f"no such case {ref}; search the court for a new one") from exc
        except napix_admin.AdminConflict as exc:
            raise typer.BadParameter(f"{exc.code}: {exc}") from exc
    rprint(f"queued dossier {state['ref']} ({state['status']}, priority {state['priority']})")


def queue_worker(
    idle_seconds: int = typer.Option(60, "--idle", help="sleep this long when the queue is empty"),
    max_items: int | None = typer.Option(None, "--max-items", help="rows per pass (default: unlimited)"),
) -> None:
    """Run the queue continuously (the Compose `worker` service): pass after pass, sleeping when the queue
    is empty and until the next clock hour when the gateway budget is spent."""
    import time
    from datetime import datetime

    settings = get_settings()
    factory = get_sessionmaker()
    rprint(f"queue worker started (NAPIX {'on' if settings.napix_configured else 'off'})")
    while True:
        try:
            report = run_queue(factory, max_items=max_items, kinds=None, settings=settings)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 — logged, then the loop continues
            rprint(f"[red]pass failed: {exc.__class__.__name__}: {str(exc)[:300]}[/red]")
            time.sleep(idle_seconds)
            continue
        rprint(
            f"{datetime.now():%H:%M:%S} pass: {report.processed} rows (done {report.done}, skipped "
            f"{report.skipped}, failed {report.failed}), {report.calls} calls; {report.stopped_reason}"
        )
        if report.stopped_reason and report.stopped_reason.startswith("rate budget"):
            now = datetime.now()
            wait = (60 - now.minute) * 60 - now.second + 5
            rprint(f"budget spent: sleeping {wait}s until the next hour")
            time.sleep(wait)
        elif report.processed == 0:
            time.sleep(idle_seconds)


def daily_cycle(
    what: str = typer.Argument("all", help="all | masters | lists | status | weekly"),
) -> None:
    """Enqueue what the scheduler would (for a manual run or a test)."""
    from aslms.services import schedules

    with session_scope() as s:
        out = {}
        if what in ("all", "masters"):
            out["masters"] = schedules.enqueue_masters(s)
        if what in ("all", "lists"):
            out["lists"] = schedules.enqueue_daily_lists(s)
        if what in ("all", "status"):
            out["status_batches"] = schedules.enqueue_daily_status(s)
        if what == "weekly":
            out["weekly"] = schedules.enqueue_weekly(s)
    rprint(out)
