"""`aslms` command line: seed, users, cycle, backfill, refresh, alerts, rescore, import mappings, report,
napix-check. Every command runs the same services the workers and the API use."""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

import typer
from rich import print as rprint
from rich.table import Table

from aslms import __version__
from aslms.cli.napix_check import napix_check
from aslms.core.logging import configure_logging

app = typer.Typer(no_args_is_help=True, help="ASLMS v2 backend commands")
app.command(name="napix-check")(napix_check)


@app.callback()
def _init() -> None:
    configure_logging()


def _d(s: str | None) -> date | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            from datetime import datetime

            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise typer.BadParameter(f"not a date: {s} (use YYYY-MM-DD or DD-MM-YYYY)")


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


@app.command()
def bootstrap(
    demo: bool = typer.Option(False, help="load demo data on a first run (refused when APP_ENV=prod)"),
) -> None:
    """Container start-up step (after `alembic upgrade head`): seed, and on a laptop load the demo data once."""
    from sqlalchemy import select

    from aslms.core.config import get_settings
    from aslms.db.seed import run_seed
    from aslms.db.session import sync_session
    from aslms.domain.org import User

    with sync_session() as session:
        run_seed(session)
    if not demo or get_settings().is_prod:
        rprint("[green]bootstrap complete[/green]")
        return
    from aslms.db.demo_seed import USERS, run_demo_seed
    from aslms.services import admin

    with sync_session() as session:
        first_run = session.scalar(select(User).where(User.email == USERS[0][0])) is None
        run_demo_seed(session)
    if first_run:
        with sync_session() as session:
            rprint({"rescored": admin.rescore_all(session)})
    rprint("[green]bootstrap complete (demo data present)[/green]")


@app.command("seed-demo")
def seed_demo() -> None:
    """DEV ONLY: demo departments, counsel-code mappings and one account per role (refused in production)."""
    from aslms.db.demo_seed import DEMO_PASSWORD, USERS, run_demo_seed
    from aslms.db.session import sync_session

    with sync_session() as session:
        counts = run_demo_seed(session)
    rprint(f"[green]demo data loaded[/green] {counts}")
    rprint(f"demo accounts (password [bold]{DEMO_PASSWORD}[/bold]): " + ", ".join(u[0] for u in USERS))
    rprint("run `aslms rescore` to recommend the cases already ingested")


@app.command("create-user")
def create_user(
    email: str,
    full_name: str,
    office_code: str,
    role: str,
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True),
    designation: str = typer.Option(None),
) -> None:
    """Create a user (e.g. the first department admin)."""
    from sqlalchemy import select

    from aslms.db.session import sync_session
    from aslms.domain.org import Office, Role
    from aslms.services import admin
    from aslms.services.audit import Actor

    with sync_session() as s:
        office = s.scalar(select(Office).where(Office.code == office_code.upper()))
        if office is None:
            raise typer.BadParameter(f"no office {office_code}")
        u = admin.create_user(
            s,
            Actor.system("cli"),
            email=email,
            full_name=full_name,
            office_id=office.id,
            role=Role(role),
            password=password,
            designation=designation,
        )
        rprint(f"[green]created[/green] {u.email} ({u.role.value}) in {office.code}")


@app.command("import-offices")
def import_offices(csv_path: Path) -> None:
    """Import offices from CSV with columns code,name,kind,parent_code (parents first). Existing codes are kept."""
    from sqlalchemy import select

    from aslms.db.session import sync_session
    from aslms.domain.org import Office, OfficeKind
    from aslms.services import admin
    from aslms.services.audit import Actor

    created = 0
    with sync_session() as s, csv_path.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            code = row["code"].strip().upper()
            if s.scalar(select(Office).where(Office.code == code)):
                continue
            parent = (
                s.scalar(select(Office).where(Office.code == row.get("parent_code", "").strip().upper()))
                if row.get("parent_code")
                else None
            )
            admin.create_office(
                s,
                Actor.system("cli"),
                code=code,
                name=row["name"],
                kind=OfficeKind(row["kind"].strip()),
                parent_id=parent.id if parent else None,
            )
            created += 1
    rprint(f"[green]{created} office(s) created[/green]")


@app.command("import-codes")
def import_codes(csv_path: Path) -> None:
    """Import standing-counsel code mappings from CSV: code,office_code[,weight][,generic]."""
    from sqlalchemy import select

    from aslms.db.session import sync_session
    from aslms.domain.org import Office
    from aslms.services import admin
    from aslms.services.audit import Actor

    n = 0
    with sync_session() as s, csv_path.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            office = s.scalar(select(Office).where(Office.code == row["office_code"].strip().upper()))
            if office is None:
                rprint(f"[yellow]skip {row['code']}: no office {row['office_code']}[/yellow]")
                continue
            admin.upsert_counsel_code(
                s,
                Actor.system("cli"),
                code=row["code"],
                office_id=office.id,
                weight=float(row.get("weight") or 0.95),
                is_generic_state=(row.get("generic") or "").strip().lower() in ("1", "true", "yes"),
            )
            n += 1
    rprint(f"[green]{n} code(s) imported[/green]; run `aslms rescore` to update recommendations")


@app.command()
def cycle(
    list_date: str = typer.Option(None, "--date", help="Cause-list date (default: tomorrow)"),
    no_napix_fetch: bool = typer.Option(False, help="Skip first-sight CNR fetches and order downloads"),
) -> None:
    """Run the daily data cycle for one date now (same code the scheduler runs)."""
    from aslms.db.session import sync_session
    from aslms.services.daily_cycle import run_daily_cycle

    d = _d(list_date) or date.today() + timedelta(days=1)
    result = run_daily_cycle(
        sync_session, d, fetch_cases=not no_napix_fetch, download_orders=not no_napix_fetch
    )
    rprint(result)


@app.command()
def backfill(
    start: str = typer.Option(None, help="First date (default: earliest folder)"),
    end: str = typer.Option(None, help="Last date (default: latest folder)"),
    limit: int = typer.Option(0, help="Process at most this many dates (0 = all)"),
) -> None:
    """Ingest the cause-list PDFs already on disk (CAUSE_LIST_DIR), oldest first. Idempotent."""
    from aslms.db.session import sync_session
    from aslms.integration.ghc.website import LocalDirSource
    from aslms.services.daily_cycle import run_daily_cycle

    dates = LocalDirSource().available_dates()
    s, e = _d(start), _d(end)
    dates = [d for d in dates if (not s or d >= s) and (not e or d <= e)]
    if limit:
        dates = dates[:limit]
    table = Table("date", "lists", "entries", "new cases", "with CNR", "recs", "warnings")
    for d in dates:
        r = run_daily_cycle(sync_session, d, fetch_cases=False, download_orders=False, raise_alerts=False)
        i = r["ingest"]
        table.add_row(
            str(d),
            str(i["lists"]),
            str(i["entries_seen"]),
            str(i["cases_new"]),
            str(i["with_cnr"]),
            str(i["recommendations"]),
            str(len(i["warnings"])),
        )
    rprint(table)
    rprint(f"{len(dates)} date(s) processed. Alerts: run `aslms alerts`.")


@app.command()
def refresh(
    kind: str = typer.Argument("status", help="status | full | first-sight | orders | masters | discovery"),
) -> None:
    """Run a NAPIX refresh now (needs NAPIX credentials)."""
    from aslms.jobs import tasks

    fn = {
        "status": tasks.track_status_refresh,
        "full": tasks.track_full_refresh,
        "orders": tasks.documents_download_orders,
        "masters": tasks.ops_master_sync,
        "discovery": tasks.track_discovery,
    }.get(kind)
    if kind == "first-sight":
        from aslms.db.session import sync_session
        from aslms.integration.factory import napix_source
        from aslms.services import tracking

        built = napix_source()
        if built is None:
            raise typer.Exit("NAPIX not configured")
        with sync_session() as s:
            rprint(tracking.first_sight(s, built[0]))
            built[1].flush(s)
        return
    if fn is None:
        raise typer.BadParameter(kind)
    rprint(fn())


@app.command()
def alerts() -> None:
    """Raise alerts and deliver queued notifications now."""
    from aslms.jobs.tasks import notify_alerts

    rprint(notify_alerts())


@app.command()
def rescore(limit: int = typer.Option(0, help="0 = all pending cases")) -> None:
    """Recompute department scores and recommendations (after the mapping changes)."""
    from aslms.db.session import sync_session
    from aslms.services import admin

    with sync_session() as s:
        rprint({"rescored": admin.rescore_all(s, limit or None)})


@app.command()
def report(days: int = typer.Option(30, help="look-back for data health")) -> None:
    """Data-collection summary: cause lists, CNR resolution, recommendations by department, top unmapped codes."""
    from sqlalchemy import func, select

    from aslms.db.session import sync_session
    from aslms.domain.cases import Case
    from aslms.domain.org import Office
    from aslms.domain.ownership import Recommendation, RecommendationStatus
    from aslms.services import admin, reports

    with sync_session() as s:
        h = reports.data_health(s, days)
        rprint(
            {
                "cases": s.scalar(select(func.count()).select_from(Case)),
                "provisional": s.scalar(
                    select(func.count()).select_from(Case).where(Case.is_provisional.is_(True))
                ),
                "entries_by_source": h["entries_by_source"],
                "orders": h["orders"],
                "open_failures": len(h["open_failures"]),
            }
        )
        t = Table("department", "recommended (high)", "recommended (all)")
        for code, hi, n in s.execute(
            select(Office.code, func.count().filter(Recommendation.band == "high"), func.count())
            .join(Office, Office.id == Recommendation.office_id)
            .where(Recommendation.status == RecommendationStatus.RECOMMENDED)
            .group_by(Office.code)
            .order_by(func.count().desc())
        ):
            t.add_row(code, str(hi), str(n))
        rprint(t)
        u = Table("unmapped counsel code", "seen")
        for row in admin.unmapped_codes(s, 25):
            u.add_row(row["code"], str(row["seen"]))
        rprint(u)


if __name__ == "__main__":
    app()
