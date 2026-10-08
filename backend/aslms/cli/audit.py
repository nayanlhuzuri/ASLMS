"""`aslms audit search [--user EMAIL] [--case REF] [--from D] [--to D] [--action A] [--limit N]` and `aslms data-health`
(design `audit-screens`, "API"). The search acts as the single active super admin, as the other administration
commands do; the data-health snapshot (counts only) needs none. Both write nothing: the search prints a table
newest first, the data-health snapshot prints as JSON."""

from __future__ import annotations

import json

import typer
from rich import print as rprint
from rich.table import Table

from aslms.cli.users import _actor
from aslms.core.config import get_settings
from aslms.db.session import session_scope
from aslms.services import audit_search, data_health
from aslms.services.access import Forbidden
from aslms.services.cases import CaseNotFound

audit_app = typer.Typer(no_args_is_help=True, help="The audit log: search")


def _super_admin(session):
    _actor_, user = _actor(session)
    if user is None:
        raise typer.BadParameter("there is no super admin yet; run `aslms users create-super-admin` first")
    return user


def _date(value: str | None):
    from aslms.cli.main import parse_cli_date

    return parse_cli_date(value)


@audit_app.command("search")
def search(
    user: str | None = typer.Option(None, "--user", help="the acting login's e-mail"),
    case: str | None = typer.Option(None, "--case", help="case id, ref_no or CNR"),
    from_: str | None = typer.Option(None, "--from", help="first IST day, YYYY-MM-DD"),
    to: str | None = typer.Option(None, "--to", help="last IST day, YYYY-MM-DD"),
    action: str | None = typer.Option(None, "--action", help="exact code, or a prefix ending in '.'"),
    limit: int = typer.Option(50, "--limit", min=1, max=audit_search.MAX_LIMIT),
) -> None:
    """Audit rows newest first (one page; writes nothing)."""
    settings = get_settings()
    with session_scope() as s:
        admin = _super_admin(s)
        q = audit_search.AuditQuery(
            user_email=user, case_ref=case, from_=_date(from_), to=_date(to), action=action, limit=limit
        )
        try:
            page = audit_search.search(s, admin, q, settings=settings)
        except (Forbidden, audit_search.AuditInputError, CaseNotFound, audit_search.SearchTimeout) as exc:
            raise typer.BadParameter(f"{getattr(exc, 'code', 'refused')}: {exc}") from exc
    table = Table("at (IST)", "action", "actor", "office", "case", "entity", "id")
    for row in page.items:
        case_ref = (row["case"] or {}).get("ref_no") or ""
        table.add_row(
            row["at"].strftime("%Y-%m-%d %H:%M:%S"),
            row["action"],
            row["actor"]["name"] or "",
            row["actor"]["office_code"] or "",
            case_ref,
            row["entity_type"],
            str(row["id"]),
        )
    rprint(table)
    if page.next_cursor:
        rprint(f"more rows: narrow the period or raise --limit (cursor {page.next_cursor})")


def data_health_cmd() -> None:
    """The live data-health snapshot as JSON (what `GET /admin/data-health` returns). Counts only, so like
    `queue-status` it needs no super admin."""
    settings = get_settings()
    with session_scope() as s:
        _actor_, admin = _actor(s)
        snap = data_health.snapshot(s, admin, settings)
    print(json.dumps(snap, default=str, indent=2, ensure_ascii=False))
