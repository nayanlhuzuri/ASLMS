"""`/insights` and `/admin/insights/*`: State Insights (design `state-insights`, round 1, "API").

- `GET /insights/scopes`, `GET /insights`, `GET /insights/cases`, `GET /insights/fields` and `GET /insights/export`
  need `insights.state` or `insights.department`, then the scope rule of decisions 18 and 19 (403
  `state_scope_not_state_wide`, `department_not_yours`, `no_insights_function`). The filters of decision 24 are query
  parameters validated by the service (400 `bad_filter` / `bad_dates` naming the parameter, 400 `bad_sort`); a
  statement past `INSIGHTS_STATEMENT_TIMEOUT_SECONDS` answers 503 `insights_timeout`. Visibility is applied in SQL on
  every read. The JSON reads write nothing; an export is built in memory, streamed with `Content-Disposition:
  attachment` and `Cache-Control: no-store`, and audited (`insights.exported`) after the file is built (400
  `bad_field`).
- `/admin/insights/groups`, `/categories` and `/case-types` need the reserved function `admin.insights_groups` (the
  Super Administrator alone); every change is audited.
No NAPIX, SourceTrace or model call."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, get_session, require, require_any
from aslms.api.errors import detail, list_error
from aslms.core.clock import today_ist
from aslms.domain.insights import InsightGroup
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.services import access, insights, insights_export, insights_groups, insights_scope
from aslms.services import insights_filters as F
from aslms.services.access import Forbidden
from aslms.services.insights_groups import GroupsError
from aslms.services.list_search import ListSearchError
from aslms.services.list_sort import ListSortError

router = APIRouter(tags=["insights"])
reader = require_any(Permission.INSIGHTS_STATE, Permission.INSIGHTS_DEPARTMENT)
groups_admin = require(Permission.ADMIN_INSIGHTS_GROUPS)
ERRORS = {
    400: {"model": schemas.ErrorOut},
    403: {"model": schemas.ErrorOut},
    503: {"model": schemas.ErrorOut},
}
FILE_RESPONSES = {
    **ERRORS,
    200: {
        "content": {insights_export.XLSX_MEDIA_TYPE: {}, insights_export.PDF_MEDIA_TYPE: {}},
        "description": "The filtered case list as an Excel or PDF file.",
    },
}


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, Forbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail(exc.code, str(exc)))
    if isinstance(exc, F.InsightFilterError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail(exc.code, str(exc), param=exc.param))
    if isinstance(exc, insights.InsightsTimeout):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail(exc.code, str(exc)))
    if isinstance(exc, insights_export.BadField):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail(exc.code, str(exc), field=exc.key))
    if isinstance(exc, GroupsError):
        return HTTPException(exc.http_status, detail(exc.code, str(exc)))
    if isinstance(exc, ListSearchError | ListSortError):
        return list_error(exc)
    raise exc


def filter_params(
    scope: str | None = Query(None, description="state or department"),
    department: str | None = Query(None, description="the scope's department code"),
    status_: str | None = Query(None, alias="status", description="pending (default), disposed or all"),
    state_only: str | None = Query(None, description="true (default) or false"),
    include_ia: str | None = Query(None, description="false (default) or true"),
    kind: str | None = Query(None, description="an active kind-of-case code"),
    age: str | None = Query(None, description="an age band key or over_5"),
    next_: str | None = Query(None, alias="next", description="a next-hearing band or within_7"),
    filed: str | None = Query(None, description="a year from 1950 to this year, earlier or unknown"),
    dept: str | None = Query(None, description="a department code (State scope only)"),
    band: str | None = Query(None, description="claimed, likely or named (with dept)"),
    unit: str | None = Query(None, description="an office of the scope's department, or none"),
    post: str | None = Query(None, description="a post code"),
    subject: str | None = Query(None, description="a subject group code, none or not_grouped"),
    counsel: str | None = Query(None, description="a printed counsel code"),
    outcome: str | None = Query(None, description="an outcome key"),
    action: str | None = Query(None, description="an action-status key"),
    compliance: str | None = Query(None, description="overdue or due_soon"),
    holder: str | None = Query(None, description="an office code"),
    date_of: str | None = Query(None, description="registration, next_hearing, latest_order or disposal"),
    from_: str | None = Query(None, alias="from", description="inclusive IST date (YYYY-MM-DD)"),
    to: str | None = Query(None, description="inclusive IST date (YYYY-MM-DD)"),
) -> dict:
    return {
        "scope": scope,
        "department": department,
        "status": status_,
        "state_only": state_only,
        "include_ia": include_ia,
        "kind": kind,
        "age": age,
        "next": next_,
        "filed": filed,
        "dept": dept,
        "band": band,
        "unit": unit,
        "post": post,
        "subject": subject,
        "counsel": counsel,
        "outcome": outcome,
        "action": action,
        "compliance": compliance,
        "holder": holder,
        "date_of": date_of,
        "from": from_,
        "to": to,
    }


def _resolve(session: Session, user: User, params: dict):
    sc = insights_scope.resolve(session, user, params.pop("scope"), params.pop("department"))
    f = F.parse(session, sc, today=today_ist(), **params)
    return sc, f


def _cfg(request: Request) -> insights.InsightsConfig:
    return insights.InsightsConfig.from_settings(request.app.state.settings)


@router.get("/insights/scopes", response_model=schemas.InsightsScopesOut, responses=ERRORS)
def scopes(session: Session = Depends(get_session), user: User = Depends(reader)) -> dict:
    """Whether the State view is open (a State-wide membership holding View State Insights), the departments of the
    switch and the default view."""
    try:
        return insights_scope.available(session, user)
    except Forbidden as exc:
        raise _http(exc) from exc


@router.get("/insights", response_model=schemas.InsightsOut, responses=ERRORS)
def overview(
    request: Request,
    params: dict = Depends(filter_params),
    session: Session = Depends(get_session),
    user: User = Depends(reader),
) -> dict:
    """The headline figures, every chart and the accountability section; each chart counts with every filter except
    its own dimension (decision 22). Writes nothing."""
    try:
        sc, f = _resolve(session, user, params)
        return insights.overview(session, user, f, sc, cfg=_cfg(request))
    except (Forbidden, F.InsightFilterError, insights.InsightsTimeout) as exc:
        raise _http(exc) from exc


@router.get("/insights/cases", response_model=schemas.InsightsCasesOut, responses=ERRORS)
def cases(
    request: Request,
    page: int = Query(1, ge=1, le=100_000),
    sort: str | None = Query(None, description="next (default), registered or latest_order"),
    params: dict = Depends(filter_params),
    session: Session = Depends(get_session),
    user: User = Depends(reader),
) -> dict:
    """20 cases a page of the filtered selection, with who has each case (decision 26). Writes nothing."""
    try:
        sc, f = _resolve(session, user, params)
        return insights.case_page(session, user, f, sc, page=page, sort=sort, cfg=_cfg(request))
    except (Forbidden, F.InsightFilterError, insights.InsightsTimeout) as exc:
        raise _http(exc) from exc


@router.get("/insights/fields", response_model=list[schemas.InsightsFieldOut], responses=ERRORS)
def fields(session: Session = Depends(get_session), user: User = Depends(reader)) -> list[dict]:
    """The export field registry: the owner's 33 numbered fields in four groups, the defaults marked, then
    Applications Pending."""
    try:
        insights_scope.require_any_insights(session, user)
    except Forbidden as exc:
        raise _http(exc) from exc
    return insights_export.registry()


@router.get("/insights/export", response_class=Response, responses=FILE_RESPONSES)
def export(
    request: Request,
    fmt: Literal["xlsx", "pdf"] = Query("xlsx", alias="format"),
    fields_: str | None = Query(
        None, alias="fields", description="comma list of field keys; default the marked set"
    ),
    sort: str | None = Query(None, description="next (default), registered or latest_order"),
    params: dict = Depends(filter_params),
    session: Session = Depends(get_session),
    user: User = Depends(reader),
) -> Response:
    """The filtered list as Excel (up to INSIGHTS_XLSX_MAX_ROWS) or PDF (up to INSIGHTS_PDF_MAX_ROWS), only cases of
    the scope the viewer may open; audited `insights.exported` after the file is built."""
    cfg = _cfg(request)
    try:
        sc, f = _resolve(session, user, params)
        chosen = insights_export.parse_fields(fields_, fmt, f)
        sort = insights.check_sort(sort)
        now = datetime.now(UTC)
        today = today_ist(now)

        def build() -> tuple[bytes, insights_export.ExportMeta]:
            from aslms.services.reporting_common import with_timeout

            with_timeout(session, cfg.export_timeout_seconds)
            meta = insights_export.ExportMeta(
                scope_words="State" if sc.is_state else f"Department: {sc.department.name}",
                filters=[c["label"] for c in F.chips(session, f, today)],
                exported_by=insights_export.exporter_words(sc.member),
                exported_at=now,
                coverage_line=insights.coverage(session, f)["line"],
                total=insights_export.count(session, f, sc, cfg, today),
            )
            cap = cfg.pdf_max_rows if fmt == "pdf" else cfg.xlsx_max_rows
            data = insights_export.rows(session, user, f, sc, chosen, cap, sort=sort, cfg=cfg, today=today)
            content = (
                insights_export.to_pdf(meta, chosen, data, cap)
                if fmt == "pdf"
                else insights_export.to_xlsx(meta, chosen, data, cap)
            )
            return content, meta

        content, meta = insights.guard(build)
    except (Forbidden, F.InsightFilterError, insights.InsightsTimeout, insights_export.BadField) as exc:
        raise _http(exc) from exc
    actor = access.actor_as(actor_of(request, user, session), sc.member)
    insights_export.audit_export(session, actor, sc, f, chosen, fmt, meta)
    media = insights_export.PDF_MEDIA_TYPE if fmt == "pdf" else insights_export.XLSX_MEDIA_TYPE
    return Response(
        content,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{insights_export.filename(sc, fmt, now)}"',
            "Cache-Control": "no-store",
        },
    )


# ------------------------------------------------------------------------------------------------ the groupings


def _group_out(session: Session, row: InsightGroup) -> dict:
    """The group's line as `GET /admin/insights/groups` shows it, with its real counts."""
    return insights_groups.group_line(session, row)


@router.get("/admin/insights/groups", response_model=list[schemas.InsightGroupOut], responses=ERRORS)
def list_groups(
    kind: str = Query(..., description="subject or family"),
    session: Session = Depends(get_session),
    user: User = Depends(groups_admin),
) -> list[dict]:
    """The groups of one kind in their order, with their categories or case types and case counts."""
    try:
        return insights_groups.list_groups(session, user, kind)
    except (Forbidden, GroupsError) as exc:
        raise _http(exc) from exc


@router.post(
    "/admin/insights/groups",
    response_model=schemas.InsightGroupOut,
    status_code=status.HTTP_201_CREATED,
    responses={**ERRORS, 409: {"model": schemas.ErrorOut}},
)
def create_group(
    body: schemas.InsightGroupIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(groups_admin),
) -> dict:
    """A new group (never reserved); 409 `code_taken` / `label_taken`, 400 `bad_sort_order` outside 0 to 10,000;
    audited `insights.group_created`. Answers the group's line with its counts."""
    try:
        row = insights_groups.create_group(
            session,
            actor_of(request, user, session),
            user,
            kind=body.kind,
            code=body.code,
            label=body.label,
            sort_order=body.sort_order,
            description=body.description,
        )
    except (Forbidden, GroupsError) as exc:
        raise _http(exc) from exc
    return _group_out(session, row)


@router.patch(
    "/admin/insights/groups/{group_id}",
    response_model=schemas.InsightGroupOut,
    responses={**ERRORS, 404: {"model": schemas.ErrorOut}, 409: {"model": schemas.ErrorOut}},
)
def patch_group(
    group_id: uuid.UUID,
    body: schemas.InsightGroupPatchIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(groups_admin),
) -> dict:
    """Rename, reorder or (de)activate; a reserved group cannot be deactivated (409 `reserved_group`), 400
    `bad_sort_order` outside 0 to 10,000; audited `insights.group_updated`. Answers the group's line with its counts."""
    row = session.get(InsightGroup, group_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail("not_found", "no such group"))
    kw = {k: getattr(body, k) for k in body.model_fields_set}
    try:
        row = insights_groups.update_group(session, actor_of(request, user, session), user, row, **kw)
    except (Forbidden, GroupsError) as exc:
        raise _http(exc) from exc
    return _group_out(session, row)


@router.get("/admin/insights/categories", response_model=list[schemas.InsightCategoryOut], responses=ERRORS)
def list_categories(
    q: str | None = None,
    group: str | None = Query(None, description="a subject group code or not_grouped"),
    sort: str | None = Query(None, description="code (default), label, group, cases or pending"),
    session: Session = Depends(get_session),
    user: User = Depends(groups_admin),
) -> list[dict]:
    try:
        return insights_groups.list_categories(session, user, q=q, group=group, sort=sort)
    except (Forbidden, GroupsError, ListSearchError, ListSortError) as exc:
        raise _http(exc) from exc


@router.put(
    "/admin/insights/categories",
    response_model=list[schemas.InsightCategoryOut],
    responses={**ERRORS, 404: {"model": schemas.ErrorOut}},
)
def put_categories(
    body: schemas.InsightCategoriesIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(groups_admin),
) -> list[dict]:
    """A batch Save: one `insights.category_grouped` audit row per changed line (`group` null = Not Grouped); takes
    effect at once. Answers each changed line with its cases and pending."""
    try:
        return insights_groups.set_categories(
            session, actor_of(request, user, session), user, [(c.code, c.group) for c in body.changes]
        )
    except (Forbidden, GroupsError) as exc:
        raise _http(exc) from exc


@router.get("/admin/insights/case-types", response_model=list[schemas.InsightCaseTypeOut], responses=ERRORS)
def list_case_types(
    q: str | None = None,
    group: str | None = Query(None, description="a kind-of-case code"),
    sort: str | None = Query(None, description="code (default), name, group, cases or pending"),
    session: Session = Depends(get_session),
    user: User = Depends(groups_admin),
) -> list[dict]:
    try:
        return insights_groups.list_case_types(session, user, q=q, group=group, sort=sort)
    except (Forbidden, GroupsError, ListSearchError, ListSortError) as exc:
        raise _http(exc) from exc


@router.put(
    "/admin/insights/case-types",
    response_model=list[schemas.InsightCaseTypeOut],
    responses={**ERRORS, 404: {"model": schemas.ErrorOut}},
)
def put_case_types(
    body: schemas.InsightCaseTypesIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(groups_admin),
) -> list[dict]:
    """A batch Save: one `insights.case_type_grouped` audit row per changed line (`group` null = Other). Answers each
    changed line with its full name, cases and pending."""
    try:
        return insights_groups.set_case_types(
            session, actor_of(request, user, session), user, [(c.case_type_id, c.group) for c in body.changes]
        )
    except (Forbidden, GroupsError) as exc:
        raise _http(exc) from exc
