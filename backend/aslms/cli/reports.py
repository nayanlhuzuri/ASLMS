"""`aslms reports` (design `reports-dashboards`, decision 16): `run <report> [--department CODE] [--from D --to D]
[--holder-department CODE] [--include-cases] [--format json|xlsx|pdf] [--out PATH]` and `dashboard [--department
CODE] [--state]`. Acts as the single active super admin, as the other administration commands do; an xlsx or
pdf export writes one `report.exported` audit row, as from the API. JSON goes to the terminal unless `--out` is
given."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich import print as rprint

from aslms.cli.users import _actor
from aslms.core.config import get_settings
from aslms.db.session import session_scope
from aslms.services import access, dashboard, report_export, reports
from aslms.services.access import Forbidden
from aslms.services.reporting_common import ReportConfig, ReportError

reports_app = typer.Typer(no_args_is_help=True, help="Reports and dashboards: run, dashboard")
FORMATS = ("json", "xlsx", "pdf")


def _super_admin(session):
    actor, user = _actor(session)
    if user is None:
        raise typer.BadParameter("there is no super admin yet; run `aslms users create-super-admin` first")
    return actor, user


def _refused(exc: Exception) -> typer.BadParameter:
    return typer.BadParameter(f"{getattr(exc, 'code', 'forbidden')}: {exc}")


def _date(value: str | None):
    from aslms.cli.main import parse_cli_date

    return parse_cli_date(value)


@reports_app.command("run")
def run(
    report: str = typer.Argument(..., help="one of: " + ", ".join(reports.CATALOGUE)),
    department: str | None = typer.Option(None, "--department", help="department code (department scope)"),
    from_: str | None = typer.Option(None, "--from", help="period start, YYYY-MM-DD"),
    to: str | None = typer.Option(None, "--to", help="period end, YYYY-MM-DD"),
    holder_department: str | None = typer.Option(None, "--holder-department", help="pending-actions only"),
    include_cases: bool = typer.Option(False, "--include-cases", help="pending-actions: one row per case"),
    fmt: str = typer.Option("json", "--format", help="json, xlsx or pdf"),
    out: Path | None = typer.Option(None, "--out", help="write the file here (required for xlsx and pdf)"),
) -> None:
    """Build a report as the super admin; xlsx and pdf are audited."""
    if fmt not in FORMATS:
        raise typer.BadParameter(f"--format is one of {', '.join(FORMATS)}")
    if fmt != "json" and out is None:
        raise typer.BadParameter("--out is required for xlsx and pdf")
    settings = get_settings()
    cfg = ReportConfig.from_settings(settings)
    with session_scope() as s:
        actor, user = _super_admin(s)
        try:
            rep, scope = reports.build(
                s,
                user,
                report,
                department=department,
                from_=_date(from_),
                to=_date(to),
                holder_department=holder_department,
                include_cases=include_cases,
                row_cap=cfg.pdf_max_rows if fmt == "pdf" else cfg.xlsx_max_rows,
                config=cfg,
                settings=settings,
            )
        except (Forbidden, ReportError) as exc:
            raise _refused(exc) from exc
        if fmt == "json":
            text = json.dumps(rep.to_dict(), default=str, indent=2, ensure_ascii=False)
            if out is not None:
                out.write_text(text, encoding="utf-8")
                rprint(f"wrote {out}")
            else:
                print(text)
            return
        content = report_export.to_xlsx(rep) if fmt == "xlsx" else report_export.to_pdf(rep)
        out.write_bytes(content)
        report_export.audit_export(s, access.actor_as(actor, scope.member), rep, fmt)
        rprint(f"wrote {out} ({len(content)} bytes, {rep.rows} rows{', truncated' if rep.truncated else ''})")


@reports_app.command("dashboard")
def dashboard_cmd(
    department: str | None = typer.Option(None, "--department", help="one department's block"),
    state: bool = typer.Option(False, "--state", help="the State block"),
) -> None:
    """Print the block counts as the super admin: the State block with --state, a department's with
    --department (both may be given)."""
    if not state and not department:
        raise typer.BadParameter("give --state, --department CODE or both")
    cfg = ReportConfig.from_settings(get_settings())
    with session_scope() as s:
        _actor_, user = _super_admin(s)
        try:
            if state:
                block = dashboard.state_block(s, user, config=cfg)
                rprint("[bold]State[/bold]")
                for row in block["by_department"]:
                    counts = {k: v for k, v in row.items() if k not in ("code", "name", "is_active")}
                    rprint(f"  {row['code']:<12} {counts}")
                rprint(f"  not claimed {block['not_claimed']}")
                h = block["hearings"]
                rprint(f"  hearings in 7 days {h['total']} (critical {h['critical']})")
                rprint(
                    f"  overdue cases {block['overdue_actions']['total']}  compliance {block['compliance']}"
                )
            if department:
                office, _m = dashboard.resolve_department(s, user, department)
                block = dashboard.department_block(s, user, office, config=cfg)
                rprint(f"[bold]{office.code}[/bold] {office.name}")
                rprint(f"  recommendations {block['recommendations']}")
                rprint(f"  cases {block['cases']}")
                h = block["hearings"]
                rprint(f"  hearings in 7 days {h['total']} (critical {h['critical']})")
                pa = block["pending_actions"]
                if pa is not None:
                    rprint(f"  pending actions { {k: v for k, v in pa.items() if k != 'items'} }")
                att = block["attention"]
                rprint(
                    f"  attention: next dates to review {att['next_dates_to_review']}, compliance due soon "
                    f"{att['compliance_due_soon']}, overdue {att['compliance_overdue']}"
                )
        except (Forbidden, ReportError) as exc:
            raise _refused(exc) from exc
