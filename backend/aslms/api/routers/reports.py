"""`/reports`: management information for departments and State oversight (design `reports-dashboards`,
decisions 4-8, 12-14). `GET /reports` lists what the caller may run; each report takes `format=json` (default),
`xlsx` or `pdf` and returns the same content. Department scope needs `reports.department` in that department
(or `reports.state`); State scope and `data-health` need `reports.state`. An xlsx or pdf file is built in memory,
streamed with `Content-Disposition: attachment` and `Cache-Control: no-store`, and audited (`report.exported`);
a JSON report writes nothing. A report that runs past the statement timeout answers 503 `report_timeout` (design
`portal-reports`, decision 9b). No NAPIX or SourceTrace call is made."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, get_session, require_any
from aslms.api.routers.dashboard import config_of, http_error
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.services import access, report_export, reports
from aslms.services.access import Forbidden
from aslms.services.reporting_common import ReportError

router = APIRouter(prefix="/reports", tags=["reports"])
reporter = require_any(Permission.REPORTS_DEPARTMENT, Permission.REPORTS_STATE)
Format = Literal["json", "xlsx", "pdf"]
FILE_RESPONSES = {
    200: {
        "content": {report_export.XLSX_MEDIA_TYPE: {}, report_export.PDF_MEDIA_TYPE: {}},
        "description": "The report as JSON, or the Excel / PDF file with `format=xlsx|pdf`.",
    }
}


def _run(
    request: Request,
    session: Session,
    user: User,
    key: str,
    fmt: Format,
    **params,
):
    cfg = config_of(request)
    row_cap = cfg.pdf_max_rows if fmt == "pdf" else cfg.xlsx_max_rows
    try:
        report, scope = reports.build(
            session, user, key, row_cap=row_cap, config=cfg, settings=request.app.state.settings, **params
        )
    except (Forbidden, ReportError) as exc:
        raise http_error(exc) from exc
    if fmt == "json":
        return report.to_dict()
    if fmt == "xlsx":
        content, media, ext = report_export.to_xlsx(report), report_export.XLSX_MEDIA_TYPE, "xlsx"
    else:
        content, media, ext = report_export.to_pdf(report), report_export.PDF_MEDIA_TYPE, "pdf"
    actor = access.actor_as(actor_of(request, user, session), scope.member)
    report_export.audit_export(session, actor, report, fmt)
    return Response(
        content,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{report_export.filename(report, ext)}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("", response_model=schemas.ReportCatalogueOut)
def catalogue(session: Session = Depends(get_session), user: User = Depends(reporter)) -> dict:
    """The reports the caller may run, their parameters, scopes and the departments they may name; `departments`
    names every code the items list (with `is_active`)."""
    try:
        return reports.catalogue_for(session, user)
    except (Forbidden, ReportError) as exc:
        raise http_error(exc) from exc


@router.get("/pending-cases", response_model=schemas.ReportOut, responses=FILE_RESPONSES)
def pending_cases(
    request: Request,
    department: str | None = None,
    fmt: Format = Query("json", alias="format"),
    session: Session = Depends(get_session),
    user: User = Depends(reporter),
):
    """Active cases (pending or unknown) by department (or unit), court and NJDG age band, as of now (503 `report_timeout`
    past the statement timeout)."""
    return _run(request, session, user, "pending-cases", fmt, department=department)


@router.get("/hearings-disposals", response_model=schemas.ReportOut, responses=FILE_RESPONSES)
def hearings_disposals(
    request: Request,
    from_: date = Query(..., alias="from"),
    to: date = Query(...),
    department: str | None = None,
    fmt: Format = Query("json", alias="format"),
    session: Session = Depends(get_session),
    user: User = Depends(reporter),
):
    """Listings, proceedings, cases listed and disposals in the period, by group and by month (422 on a bad
    period; 503 `report_timeout` past the statement timeout)."""
    return _run(request, session, user, "hearings-disposals", fmt, department=department, from_=from_, to=to)


@router.get("/pending-actions", response_model=schemas.ReportOut, responses=FILE_RESPONSES)
def pending_actions(
    request: Request,
    department: str | None = None,
    holder_department: str | None = None,
    include_cases: bool = False,
    fmt: Format = Query("json", alias="format"),
    session: Session = Depends(get_session),
    user: User = Depends(reporter),
):
    """Files with a pending action by holder office and officer, overdue compliance by office, and with
    `include_cases=true` one row per file the caller may open (never the remark); 503 `report_timeout` past the
    statement timeout."""
    return _run(
        request,
        session,
        user,
        "pending-actions",
        fmt,
        department=department,
        holder_department=holder_department,
        include_cases=include_cases,
    )


@router.get("/data-health", response_model=schemas.ReportOut, responses=FILE_RESPONSES)
def data_health(
    request: Request,
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    department: str | None = None,
    fmt: Format = Query("json", alias="format"),
    session: Session = Depends(get_session),
    user: User = Depends(reporter),
):
    """The daily data cycle per date, NAPIX calls by API, open source failures, SourceTrace status (State scope;
    default the last 7 days; `department` refused with 400; 503 `report_timeout` past the statement timeout)."""
    return _run(request, session, user, "data-health", fmt, department=department, from_=from_, to=to)
