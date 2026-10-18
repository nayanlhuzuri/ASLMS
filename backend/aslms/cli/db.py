"""Database commands: `aslms seed`, `aslms db-check` and `aslms db-roles`."""

from __future__ import annotations

import re

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
    for note in report.notes:
        rprint(f"[yellow]seed: {note}[/yellow]")
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


# ------------------------------------------------------------------------------------------------ role passwords
# design safety-fixes, decision 2: the password goes into a URL without encoding, so only these characters
ROLE_PASSWORD_RE = re.compile(r"^[A-Za-z0-9_-]+$")
ROLE_PASSWORD_MIN = 16
KNOWN_DEFAULTS = frozenset({"aslms", "aslms_app", "aslms_readonly", "changeme", "password"})


def validate_role_password(value: str | None) -> str | None:
    """The reason a role password is refused, or None when it is acceptable. Never echoes the value."""
    if not value:
        return "the password is empty"
    if value.lower() in KNOWN_DEFAULTS:
        return "the password is a known default"
    if len(value) < ROLE_PASSWORD_MIN:
        return f"the password is shorter than {ROLE_PASSWORD_MIN} characters"
    if not ROLE_PASSWORD_RE.match(value):
        return "the password may hold only letters, digits, _ and -"
    return None


def _set_password(url: str, role: str, password: str) -> None:
    """`ALTER ROLE <role> LOGIN PASSWORD <literal>` as the owner; the literal is quoted by psycopg, never by hand."""
    from psycopg import sql
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    engine = create_engine(url, poolclass=NullPool)
    try:
        raw = engine.raw_connection()
        try:
            with raw.cursor() as cur:
                cur.execute(
                    sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(role), sql.Literal(password)
                    )
                )
            raw.commit()
        finally:
            raw.close()
    finally:
        engine.dispose()


def db_roles() -> None:
    """Set the `aslms_app` password (required) and the `aslms_readonly` password (when set) from the environment, as
    the database owner (`ASLMS_MIGRATE_URL`, else `DATABASE_URL_SYNC`). Idempotent; run by the Compose `init` step on
    every start, so a rotated password reaches the database. Refuses (exit 1) an empty, short, badly formed or
    default `ASLMS_APP_PASSWORD`. The values are never printed or logged; no audit row (a deployment step)."""
    from aslms.core.config import get_settings

    settings = get_settings()
    app_pw = settings.aslms_app_password.get_secret_value() if settings.aslms_app_password else ""
    reason = validate_role_password(app_pw)
    if reason:
        rprint(f"[red]db-roles: ASLMS_APP_PASSWORD refused: {reason}[/red]")
        raise typer.Exit(1)
    ro_pw = settings.aslms_readonly_password.get_secret_value() if settings.aslms_readonly_password else ""
    if ro_pw:
        ro_reason = validate_role_password(ro_pw)
        if ro_reason:
            rprint(f"[red]db-roles: ASLMS_READONLY_PASSWORD refused: {ro_reason}[/red]")
            raise typer.Exit(1)
    url = settings.migrate_url
    try:
        _set_password(url, "aslms_app", app_pw)
        rprint("[green]aslms_app password set[/green]")
        if ro_pw:
            _set_password(url, "aslms_readonly", ro_pw)
            rprint("[green]aslms_readonly password set[/green]")
        else:
            rprint("[yellow]ASLMS_READONLY_PASSWORD is blank: aslms_readonly left as it is[/yellow]")
    except Exception as exc:  # noqa: BLE001 — the message never carries the password (psycopg sends it as data)
        rprint(f"[red]db-roles: could not set the role password ({exc.__class__.__name__})[/red]")
        raise typer.Exit(1) from None
