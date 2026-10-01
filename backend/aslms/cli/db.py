"""Database commands: `aslms seed` and `aslms db-check`."""

from __future__ import annotations

import typer
from rich import print as rprint
from sqlalchemy import text

from aslms.db.session import session_scope
from aslms.services.seed import seed_all


def seed(
    url: str | None = typer.Option(None, "--url", help="Database URL (default: DATABASE_URL_SYNC)"),
) -> None:
    """Insert the reference rows the system needs; a second run inserts nothing."""
    with session_scope(url) as session:
        report = seed_all(session)
    if report.total == 0:
        rprint("[green]seed: nothing to insert (already seeded)[/green]")
    else:
        for table, n in sorted(report.inserted.items()):
            rprint(f"  {table:<20} +{n}")
        rprint(f"[green]seed: {report.total} rows inserted[/green]")


def db_check(
    url: str | None = typer.Option(None, "--url", help="Database URL (default: DATABASE_URL_SYNC)"),
) -> None:
    """Print the migration revision and the table count."""
    with session_scope(url) as session:
        rev = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
        tables = session.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")).scalar()
    rprint(f"revision {rev}, {tables} tables")
