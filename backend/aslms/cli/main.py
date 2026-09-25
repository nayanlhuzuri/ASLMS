"""`aslms` command line: version, seed, napix-check (later: cycle, backfill, report)."""

from __future__ import annotations

import typer
from rich import print as rprint

from aslms import __version__
from aslms.cli.napix_check import napix_check
from aslms.core.logging import configure_logging

app = typer.Typer(no_args_is_help=True, help="ASLMS v2 backend commands")
app.command(name="napix-check")(napix_check)


@app.callback()
def _init() -> None:
    configure_logging()


@app.command()
def version() -> None:
    """Print the backend version."""
    rprint(f"aslms {__version__}")


@app.command()
def seed() -> None:
    """Create or update the structural offices, the Gauhati High Court establishment and the operator account."""
    from aslms.db.seed import run_seed
    from aslms.db.session import sync_session

    with sync_session() as session:
        counts = run_seed(session)
    rprint(f"[green]seed complete[/green] {counts}")


if __name__ == "__main__":
    app()
