"""`aslms` command line: NAPIX checks and probes, `seed`, `db-check`."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import typer
from rich import print as rprint

from aslms import __version__
from aslms.cli.db import db_check, seed
from aslms.cli.napix_check import napix_check
from aslms.cli.napix_fields import napix_fields
from aslms.cli.napix_probe import napix_probe_rate
from aslms.core.logging import configure_logging

app = typer.Typer(no_args_is_help=True, help="ASLMS v2 backend commands")
app.command(name="napix-check")(napix_check)
app.command(name="napix-fields")(napix_fields)
app.command(name="napix-probe-rate")(napix_probe_rate)
app.command(name="seed")(seed)
app.command(name="db-check")(db_check)


@app.callback()
def _init() -> None:
    configure_logging()


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
