"""`aslms` command line: NAPIX checks and probes, `seed`, `db-check`, `db-roles`, the load pipeline (`load`, `queue-run`, `queue-status`, `queue-retry-failed`, `sync-masters`, `refetch-date`, `refetch-case`), the matching engine (`rescore`, `codes unmapped`), the `cases` group (`reindex-search`, `show`), the `documents` group (`extract`, `scan-check`), the `alerts` group (`run`, `send`, `digest`, `status`, `test-mail`), the `sourcetrace` group (`status`, `run`, `retry`, `check`), the `reports` group (`run`, `dashboard`), the `audit` group (`search`), `data-health`, `system-health`, the `data-load` group (`status`, `coverage`, `start`, `pause`, `resume`, `order`, `dedupe`), the `discovery` group (`status`, `terms`, `sweep`), the `next-dates` group (`read`, `status`, `sample`), the `ops` group (`preflight`, `db-guard`, `role-passwords`, `migrate`, `backup`, `backup-scheduler`, `backup-status`, `restore-check`, `restore`, `repair-jobs`, `load-report`, `sample-cnrs`, `make-cert`, `metrics`), and the `users`, `access` and `offices` administration groups."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import typer
from pydantic import ValidationError
from rich import print as rprint

from aslms import __version__
from aslms.cli.alerts import alerts_app
from aslms.cli.audit import audit_app, data_health_cmd
from aslms.cli.cases import cases_app
from aslms.cli.data_load import data_load_app
from aslms.cli.db import db_check, db_roles, seed
from aslms.cli.discovery import discovery_app
from aslms.cli.documents import documents_app
from aslms.cli.matching import codes_app, rescore
from aslms.cli.napix_check import napix_check
from aslms.cli.napix_fields import napix_fields
from aslms.cli.napix_probe import napix_probe_rate
from aslms.cli.next_dates import next_dates_app
from aslms.cli.offices import offices_app
from aslms.cli.ops import ops_app
from aslms.cli.pipeline import (
    daily_cycle,
    load,
    queue_retry_failed,
    queue_run,
    queue_status,
    queue_worker,
    refetch_case,
    refetch_date,
    sync_masters_cmd,
)
from aslms.cli.reports import reports_app
from aslms.cli.sourcetrace import sourcetrace_app
from aslms.cli.system_health import system_health_cmd
from aslms.cli.users import access_app, users_app
from aslms.core.config import APP_ENV_FATAL, is_app_env_error
from aslms.core.logging import configure_logging

app = typer.Typer(no_args_is_help=True, help="ASLMS v2 backend commands")
app.command(name="napix-check")(napix_check)
app.command(name="napix-fields")(napix_fields)
app.command(name="napix-probe-rate")(napix_probe_rate)
app.command(name="seed")(seed)
app.command(name="db-check")(db_check)
app.command(name="db-roles")(db_roles)
app.command(name="load")(load)
app.command(name="queue-run")(queue_run)
app.command(name="queue-status")(queue_status)
app.command(name="queue-retry-failed")(queue_retry_failed)
app.command(name="sync-masters")(sync_masters_cmd)
app.command(name="refetch-date")(refetch_date)
app.command(name="refetch-case")(refetch_case)
app.command(name="queue-worker")(queue_worker)
app.command(name="daily-cycle")(daily_cycle)
app.command(name="data-health")(data_health_cmd)
app.command(name="system-health")(system_health_cmd)
app.command(name="rescore")(rescore)
app.add_typer(users_app, name="users")
app.add_typer(access_app, name="access")
app.add_typer(offices_app, name="offices")
app.add_typer(codes_app, name="codes")
app.add_typer(cases_app, name="cases")
app.add_typer(documents_app, name="documents")
app.add_typer(alerts_app, name="alerts")
app.add_typer(sourcetrace_app, name="sourcetrace")
app.add_typer(reports_app, name="reports")
app.add_typer(audit_app, name="audit")
app.add_typer(data_load_app, name="data-load")
app.add_typer(discovery_app, name="discovery")
app.add_typer(next_dates_app, name="next-dates")
app.add_typer(ops_app, name="ops")


@app.callback()
def _init() -> None:
    # the settings load here first, before any command, so an unknown APP_ENV is reported here with the same line
    # as `aslms ops preflight` (design pre-pilot-hardening, decision 2), never as a traceback echoing the value
    try:
        configure_logging()
    except ValidationError as exc:
        if is_app_env_error(exc):
            rprint(f"[red]{APP_ENV_FATAL}[/red]")
            raise typer.Exit(1) from None
        raise


def parse_cli_date(s: str | None) -> date | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise typer.BadParameter(f"not a date: {s} (use YYYY-MM-DD or DD-MM-YYYY)")


@app.command()
def version() -> None:
    """Print the backend version."""
    rprint(f"aslms {__version__}")


REPO_ROOT = Path(__file__).resolve().parents[3]
