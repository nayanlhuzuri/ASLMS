"""`aslms sessions sweep [--dry-run]`: ends the sign-in sessions past their idle time or their hard limit, once each,
with one audit row per end (`auth.signed_out_idle`, `auth.session_limit`), and prints the counts; `--dry-run` prints
what would end and writes nothing. The same sweep runs every 5 minutes in the scheduler (design `session-timeout`,
decision 12)."""

from __future__ import annotations

import typer
from rich import print as rprint

from aslms.core.config import get_settings
from aslms.db.session import session_scope
from aslms.services import sessions

sessions_app = typer.Typer(no_args_is_help=True, help="Sign-in sessions: sweep")


@sessions_app.command("sweep")
def sweep(
    dry_run: bool = typer.Option(False, "--dry-run", help="count what would end; write nothing"),
) -> None:
    """End idle and expired sessions now (audited by the system actor `sessions`)."""
    settings = get_settings()
    with session_scope() as s:
        if dry_run:
            counts = sessions.lapsed_counts(s, settings)
            s.rollback()
        else:
            counts = sessions.sweep(s, settings)
    label = "would end" if dry_run else "ended"
    rprint(f"sessions {label}: limit {counts['limit']}, idle {counts['idle']}")
