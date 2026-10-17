"""Next dates from orders (design `next-date-extraction`, "API"): the review queue, confirm and reject of a date read
from an order, manual next dates (`NXT`) and a case's next dates.

`{id}` is a next date's uuid or its dash-form `ref_no`; `{ref}` a case id, CNR or dash-form `ref_no`. Every
case-scoped read applies the case visibility rule first (404 "no such case"); the queue and every write also need
`next_dates.review` with a working basis on a claimed case. Errors carry `{code, message}`. Dates are IST days."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, get_session, require, require_any
from aslms.api.filters import case_filter_query
from aslms.domain.cases import Case
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.services import access, next_dates
from aslms.services.case_filters import CaseFilters
from aslms.services.cases import CaseNotFound, resolve_case_ref
from aslms.services.visibility import NotVisibleCase
from aslms.services.workflow_common import WorkflowError

router = APIRouter(tags=["next-dates"])
read = require_any(Permission.CASES_VIEW_SCOPE, Permission.CASES_VIEW_ALL)
review = require(Permission.NEXT_DATES_REVIEW)
ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": schemas.ErrorOut},
    403: {"model": schemas.ErrorOut},
    404: {"model": schemas.ErrorOut},
    409: {"model": schemas.ErrorOut},
}
HANDLED = (NotVisibleCase, CaseNotFound, next_dates.NextDateNotFound, WorkflowError, access.Forbidden)


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, next_dates.NextDateNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": "not_found", "message": "no such next date"})
    if isinstance(exc, NotVisibleCase | CaseNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": "not_found", "message": "no such case"})
    if isinstance(exc, WorkflowError):
        return HTTPException(exc.http_status, {"code": exc.code, "message": str(exc)})
    if isinstance(exc, access.Forbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, {"code": exc.code, "message": str(exc)})
    raise exc


def _cfg(request: Request) -> next_dates.NextDateConfig:
    return next_dates.NextDateConfig.from_settings(request.app.state.settings)


def _case(session: Session, ref: str) -> Case:
    try:
        return resolve_case_ref(session, ref)
    except CaseNotFound as exc:
        raise _http(exc) from exc


@router.get("/next-dates/review", response_model=schemas.NextDateReviewListOut, responses=ERRORS)
def review_queue(
    request: Request,
    kind: str | None = Query(None, description="confirm or enter"),
    limit: int = 50,
    offset: int = 0,
    filters: CaseFilters = Depends(case_filter_query),
    session: Session = Depends(get_session),
    user: User = Depends(review),
) -> schemas.NextDateReviewListOut:
    """Next dates to confirm and orders to enter a date for, on claimed cases where one of your memberships holding
    `next_dates.review` works on the case; sorted by the date to act by, then the case."""
    try:
        page = next_dates.review_items(
            session, user, kind=kind, filters=filters, limit=limit, offset=offset, cfg=_cfg(request)
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.NextDateReviewListOut(items=page.items, total=page.total)


@router.post("/next-dates/{id}/confirm", response_model=schemas.NextDateOut, responses=ERRORS)
def confirm(
    id: str,
    request: Request,
    body: schemas.NextDateConfirmIn | None = None,
    session: Session = Depends(get_session),
    user: User = Depends(review),
) -> schemas.NextDateOut:
    """Confirm a next date read from an order: it then feeds the calendar and the hearing alerts."""
    try:
        row = next_dates.confirm(session, actor_of(request, user, session), user, id, cfg=_cfg(request))
        out = next_dates.next_date_out(session, row)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.NextDateOut(**out)


@router.post("/next-dates/{id}/reject", response_model=schemas.NextDateRejectOut, responses=ERRORS)
def reject(
    id: str,
    body: schemas.NextDateRejectIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(review),
) -> schemas.NextDateRejectOut:
    """Reject a next date read from an order, optionally giving the correct date (entered as a manual date)."""
    try:
        rejected, entered = next_dates.reject(
            session,
            actor_of(request, user, session),
            user,
            id,
            note=body.note,
            replacement=body.next_date,
            cfg=_cfg(request),
        )
        out = schemas.NextDateRejectOut(
            rejected=next_dates.next_date_out(session, rejected),
            entered=next_dates.next_date_out(session, entered) if entered is not None else None,
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return out


@router.post(
    "/cases/{ref}/next-dates",
    response_model=schemas.NextDateOut,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def enter(
    ref: str,
    body: schemas.NextDateEnterIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(review),
) -> schemas.NextDateOut:
    """Enter the next date of a claimed case you work on (today up to about 18 months ahead). The note is shown to
    everyone who can see the case."""
    case = _case(session, ref)
    try:
        row = next_dates.enter(
            session,
            actor_of(request, user, session),
            user,
            case,
            next_date=body.next_date,
            note=body.note,
            order_id=body.order,
            cfg=_cfg(request),
        )
        out = next_dates.next_date_out(session, row)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.NextDateOut(**out)


@router.get("/cases/{ref}/next-dates", response_model=schemas.CaseNextDateListOut, responses=ERRORS)
def case_next_dates(
    ref: str,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> schemas.CaseNextDateListOut:
    """Every next date of the case (court status, orders, manual), newest first; `effective` marks the next date
    from orders that drives the calendar."""
    case = _case(session, ref)
    try:
        page = next_dates.case_next_dates(session, user, case, limit=limit, offset=offset)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.CaseNextDateListOut(items=page.items, total=page.total)
