"""Dashboard (plan §5.1) and reports (§5.10) with Excel / CSV export."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response

from aslms.api import schemas as S
from aslms.api.deps import Ctx, current_ctx, roles
from aslms.api.present import cards
from aslms.core.errors import NotFoundError
from aslms.core.time import today_ist
from aslms.domain.org import Role
from aslms.services import dashboard as dash
from aslms.services import reports

router = APIRouter(tags=["dashboard & reports"])


@router.get("/dashboard", response_model=S.DashboardOut)
def dashboard(ctx: Ctx = Depends(current_ctx)) -> dict[str, Any]:
    return dash.summary(ctx.db, ctx.principal)


@router.get("/dashboard/hearings", response_model=list[S.CaseCard])
def hearings(days: int = Query(7, ge=1, le=60), ctx: Ctx = Depends(current_ctx)) -> list[S.CaseCard]:
    return cards(ctx.db, ctx.principal, dash.upcoming_hearings(ctx.db, ctx.principal, days))


def _export(title: str, rows: list[dict[str, Any]], fmt: str, name: str) -> Response:
    if fmt == "csv":
        return Response(
            reports.to_csv(rows),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{name}-{today_ist()}.csv"'},
        )
    if fmt == "xlsx":
        return Response(
            reports.to_xlsx(title, rows),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{name}-{today_ist()}.xlsx"'},
        )
    return JSONResponse({"title": title, "rows": rows})


@router.get("/reports/hearings-disposals", responses={200: {"model": S.ReportOut}})
def hearings_disposals(
    start: date | None = None,
    end: date | None = None,
    format: str = Query("json", pattern="^(json|csv|xlsx)$"),
    ctx: Ctx = Depends(current_ctx),
) -> Response:
    end = end or today_ist()
    start = start or end - timedelta(days=30)
    rows = reports.hearings_and_disposals(ctx.db, ctx.principal, start, end)
    return _export(
        f"Hearings and disposals {start:%d-%m-%Y} to {end:%d-%m-%Y}", rows, format, "hearings-disposals"
    )


@router.get("/reports/data-health", response_model=S.DataHealthOut)
def data_health(
    days: int = Query(7, ge=1, le=90),
    ctx: Ctx = Depends(roles(Role.CENTRAL_OPERATOR, Role.STATE_OVERSIGHT, Role.AUDITOR, Role.DEPT_ADMIN)),
) -> dict[str, Any]:
    return reports.data_health(ctx.db, days)


@router.get("/reports/{name}", responses={200: {"model": S.ReportOut}})
def report(
    name: str, format: str = Query("json", pattern="^(json|csv|xlsx)$"), ctx: Ctx = Depends(current_ctx)
) -> Response:
    if name not in reports.REPORTS:
        raise NotFoundError("unknown report", available=list(reports.REPORTS))
    title, fn = reports.REPORTS[name]
    return _export(title, fn(ctx.db, ctx.principal), format, name)
