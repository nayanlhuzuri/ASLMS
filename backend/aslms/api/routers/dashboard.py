"""`/dashboard`: the first screen after sign-in (design `reports-dashboards`, decisions 1-3 and 8-11). `GET
/dashboard` says which blocks the caller has; `/dashboard/me`, `/dashboard/department?department=CODE` and
`/dashboard/state` return them, so the portal loads them in parallel. Reading needs `cases.view_scope` or
`cases.view_all`; the department block needs an eligible membership in that department (or `dashboard.state`),
the State block `dashboard.state`. Counts only, apart from lists filtered by the caller's case visibility.
Nothing is written; no NAPIX or SourceTrace call is made."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import get_session, require, require_any
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.services import dashboard
from aslms.services.access import Forbidden
from aslms.services.reporting_common import ReportConfig, ReportError

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
reader = require_any(Permission.CASES_VIEW_SCOPE, Permission.CASES_VIEW_ALL)


def http_error(exc: Exception) -> HTTPException:
    """403 for a missing function or scope; `{code, message}` (and `candidates`) for a refused request."""
    if isinstance(exc, Forbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, {"code": exc.code, "message": str(exc)})
    if isinstance(exc, ReportError):
        return HTTPException(exc.http_status, {"code": exc.code, "message": str(exc), **exc.extra})
    raise exc


def config_of(request: Request) -> ReportConfig:
    return ReportConfig.from_settings(request.app.state.settings)


@router.get("", response_model=schemas.DashboardIndexOut)
def index(session: Session = Depends(get_session), user: User = Depends(reader)) -> dict:
    """Which blocks the caller has: always `me`, one department block per eligible department, `state` with
    `dashboard.state`."""
    try:
        return dashboard.available(session, user)
    except (Forbidden, ReportError) as exc:
        raise http_error(exc) from exc


@router.get("/me", response_model=schemas.DashboardMeOut)
def me(request: Request, session: Session = Depends(get_session), user: User = Depends(reader)) -> dict:
    """Own cases per department membership, files held, own alerts, own hearings in the next 7 days, drafts."""
    try:
        return dashboard.me_block(session, user, config=config_of(request))
    except (Forbidden, ReportError) as exc:
        raise http_error(exc) from exc


@router.get("/department", response_model=schemas.DashboardDepartmentOut)
def department(
    request: Request,
    department: str | None = None,
    session: Session = Depends(get_session),
    user: User = Depends(reader),
) -> dict:
    """One department's block; each section is null when the caller lacks its function there. Without
    `department` and with several eligible departments: 400 `department_required` with the candidates."""
    try:
        office, _member = dashboard.resolve_department(session, user, department)
        return dashboard.department_block(session, user, office, config=config_of(request))
    except (Forbidden, ReportError) as exc:
        raise http_error(exc) from exc


@router.get("/state", response_model=schemas.DashboardStateOut)
def state(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require(Permission.DASHBOARD_STATE)),
) -> dict:
    """Per Department-tier office: claimed, recommended, hearings in 7 days, files with a pending action and
    overdue, compliance; the not-claimed row; hearings across the State; overdue files; compliance totals."""
    try:
        return dashboard.state_block(session, user, config=config_of(request))
    except (Forbidden, ReportError) as exc:
        raise http_error(exc) from exc
