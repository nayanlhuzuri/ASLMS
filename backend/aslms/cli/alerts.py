"""`aslms alerts run [--events] [--dates]` (one pass of the generators), `aslms alerts send` (the e-mail
outbox and digests through the configured backend), `aslms alerts digest [--date]` (build the day's digest
rows), `aslms alerts status` (open alerts by kind and severity, queued and failed e-mails, the last run of
each job) and `aslms alerts test-mail --to <address>` (one message through the configured backend; prints
the backend name, never the token). Design `alerts-notifications`, "Jobs"."""

from __future__ import annotations

from datetime import date, datetime

import typer
from rich import print as rprint

from aslms.core.config import get_settings
from aslms.db.session import session_scope
from aslms.services import alerts, notifications
from aslms.services.mailer import MailError, get_mailer, mask_address

alerts_app = typer.Typer(
    no_args_is_help=True, help="Alerts: generators, the sender, digests, status, test mail"
)


def _config():
    return alerts.AlertConfig.from_settings(get_settings())


@alerts_app.command("run")
def run(
    events: bool = typer.Option(False, "--events", help="the event scan"),
    dates: bool = typer.Option(False, "--dates", help="the date sweep"),
) -> None:
    """One pass of the generators (both when neither flag is given)."""
    if not events and not dates:
        events = dates = True
    cfg = _config()
    if events:
        with session_scope() as s:
            counters = alerts.scan_events(s, config=cfg)
        rprint("[bold]event scan[/bold]", counters)
    if dates:
        with session_scope() as s:
            counters = alerts.sweep_dates(s, config=cfg)
        rprint("[bold]date sweep[/bold]", counters)


@alerts_app.command("send")
def send(batch: int = typer.Option(None, "--batch", min=1, max=5000)) -> None:
    """Send queued and due-for-retry e-mail notifications and digests."""
    settings = get_settings()
    try:
        mailer = get_mailer(settings)
    except MailError as exc:
        rprint(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    with session_scope() as s:
        counters = notifications.send_pending(
            s,
            mailer,
            batch=batch or settings.notify_batch,
            max_attempts=settings.notify_max_attempts,
            portal_base_url=settings.portal_base_url,
        )
    rprint(f"backend {mailer.name}:", counters)


@alerts_app.command("digest")
def digest(
    for_date: str | None = typer.Option(None, "--date", help="the digest date (YYYY-MM-DD; default today)"),
) -> None:
    """Build the day's digest rows (one per user with something to say); `aslms alerts send` delivers them."""
    settings = get_settings()
    today = date.fromisoformat(for_date) if for_date else None
    with session_scope() as s:
        counters = notifications.build_digests(s, today=today, portal_base_url=settings.portal_base_url)
    rprint("[bold]digests[/bold]", counters)


@alerts_app.command("status")
def status() -> None:
    """Open alerts by kind and severity, queued and failed e-mails, the last run of each job."""
    with session_scope() as s:
        report = alerts.status_report(s)
    rprint(f"[bold]alert kinds[/bold] ({len(report['kinds'])}): {', '.join(report['kinds'])}")
    if report["open"]:
        for kind, by_sev in sorted(report["open"].items()):
            rprint(f"  {kind}: " + ", ".join(f"{sev} {n}" for sev, n in sorted(by_sev.items())))
    else:
        rprint("  no open alerts")
    rprint("[bold]e-mails[/bold]:", report["emails"] or "none")
    for job, run in report["runs"].items():
        if run is None:
            rprint(f"  {job}: never run")
        else:
            started = run["started_at"]
            when = started.isoformat(timespec="minutes") if isinstance(started, datetime) else started
            rprint(
                f"  {job}: {run['status']} at {when} {run['counters']}"
                + (f" error={run['error']}" if run["error"] else "")
            )


@alerts_app.command("test-mail")
def test_mail(to: str = typer.Option(..., "--to", help="the recipient address")) -> None:
    """One test message through the configured backend (prints the backend name, never a secret)."""
    settings = get_settings()
    try:
        mailer = get_mailer(settings)
        rprint(f"backend: {mailer.name}; to: {mask_address(to)}")
        mailer.send(
            to,
            "ASLMS test message",
            "This is a test message from ASLMS, the Assam State Litigation Management System.\n"
            f"Portal: {settings.portal_base_url}\n",
        )
    except MailError as exc:
        rprint(f"[red]not sent:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    rprint("[green]sent[/green]")
