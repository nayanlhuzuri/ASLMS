"""`/admin/data-health`, `/admin/napix/*` and `/admin/failures`: the live data-health screen and its buttons (design
`audit-screens`, decisions 5-13). Reading needs any of `reports.state`, `admin.napix_refetch`,
`admin.masters_sync` and never calls NAPIX. The buttons enqueue `fetch_queue` rows (202 with the row's state) and
are audited; only `POST /admin/napix/health/check` calls NAPIX (one Overview call, through the integration layer).
Errors carry `{code, message}`; times are in IST."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, get_session, napix_client, require, require_any
from aslms.api.errors import detail
from aslms.domain.cases import Case
from aslms.domain.ops import FetchKind, FetchLane, FetchStatus
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.services import data_health, napix_admin
from aslms.services.access import Forbidden
from aslms.services.audit_search import AuditInputError
from aslms.services.cases import CaseNotFound, resolve_case_ref
from aslms.services.visibility import NotVisibleCase

router = APIRouter(prefix="/admin", tags=["data-health"])
health_reader = require_any(
    Permission.REPORTS_STATE, Permission.ADMIN_NAPIX_REFETCH, Permission.ADMIN_MASTERS_SYNC
)
napix_operator = require_any(Permission.ADMIN_NAPIX_REFETCH, Permission.ADMIN_MASTERS_SYNC)
refetcher = require(Permission.ADMIN_NAPIX_REFETCH)
masters_syncer = require(Permission.ADMIN_MASTERS_SYNC)
ERRORS = {
    400: {"model": schemas.ErrorOut},
    403: {"model": schemas.ErrorOut},
    404: {"model": schemas.ErrorOut},
    409: {"model": schemas.ErrorOut},
    429: {"model": schemas.ErrorOut},
}


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, Forbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail(exc.code, str(exc)))
    if isinstance(exc, AuditInputError | napix_admin.AdminInputError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail(exc.code, str(exc)))
    if isinstance(exc, CaseNotFound | NotVisibleCase):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail("not_found", "no such case"))
    if isinstance(exc, napix_admin.AdminNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail("not_found", str(exc)))
    if isinstance(exc, napix_admin.AdminConflict):
        return HTTPException(status.HTTP_409_CONFLICT, detail(exc.code, str(exc), **exc.extra))
    if isinstance(exc, napix_admin.CheckRefused):
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        body = detail(exc.code, str(exc), retry_after=exc.retry_after)
        return HTTPException(exc.http_status, body, headers=headers)
    raise exc


HANDLED = (
    Forbidden,
    AuditInputError,
    napix_admin.AdminInputError,
    CaseNotFound,
    NotVisibleCase,
    napix_admin.AdminNotFound,
    napix_admin.AdminConflict,
    napix_admin.CheckRefused,
)


def _case(session: Session, ref: str) -> Case:
    try:
        return resolve_case_ref(session, ref)
    except CaseNotFound as exc:
        raise _http(exc) from exc


# ------------------------------------------------------------------------------------------------ reading


@router.get("/data-health", response_model=schemas.DataHealthOut)
def get_data_health(
    request: Request, session: Session = Depends(get_session), user: User = Depends(health_reader)
) -> schemas.DataHealthOut:
    """The whole screen in one snapshot: NAPIX, queue depths, the daily cycle, status batches, masters, jobs, the
    mail outbox, SourceTrace and open failures. Counts only."""
    return schemas.DataHealthOut(**data_health.snapshot(session, user, request.app.state.settings))


@router.get("/napix/health", response_model=schemas.NapixHealthOut)
def get_napix_health(
    request: Request, session: Session = Depends(get_session), user: User = Depends(health_reader)
) -> schemas.NapixHealthOut:
    """The NAPIX block: the switch as this API sees it, this clock hour, today (IST), the last call, success,
    failure and connectivity check. Never calls NAPIX."""
    return schemas.NapixHealthOut(**data_health.napix_health(session, request.app.state.settings))


@router.get("/napix/queue", response_model=schemas.QueueListOut)
def list_queue(
    kind: FetchKind | None = None,
    status_: FetchStatus | None = Query(None, alias="status"),
    ref: str | None = Query(None, max_length=300, description="ref prefix"),
    lane: FetchLane | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    user: User = Depends(health_reader),
) -> schemas.QueueListOut:
    """Queue rows by kind, status, lane and ref prefix, in run order, with `total`."""
    items, total = data_health.queue_rows(
        session, kind=kind, status=status_, ref_prefix=ref, limit=limit, offset=offset, lane=lane
    )
    return schemas.QueueListOut(total=total, items=items)


@router.get("/napix/calls", response_model=schemas.CallListOut, responses=ERRORS)
def list_calls(
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    api: str | None = Query(None, max_length=80),
    ok: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None, max_length=200),
    session: Session = Depends(get_session),
    user: User = Depends(health_reader),
) -> schemas.CallListOut:
    """Call log rows of an IST period (default today), newest first; never the parameters."""
    try:
        items, next_cursor = data_health.call_rows(
            session, from_=from_, to=to, api=api, ok=ok, cursor=cursor, limit=limit
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.CallListOut(items=items, next_cursor=next_cursor)


@router.get("/failures", response_model=schemas.FailureListOut)
def list_failures(
    kind: str | None = Query(None, max_length=60),
    open_: bool = Query(True, alias="open"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    user: User = Depends(health_reader),
) -> schemas.FailureListOut:
    """Source failures (open by default); rows naming a document only when the document is visible to you."""
    items, total = data_health.failure_rows(
        session, user, kind=kind, open_only=open_, limit=limit, offset=offset
    )
    return schemas.FailureListOut(total=total, items=items)


# ------------------------------------------------------------------------------------------------ the check


@router.post("/napix/health/check", response_model=schemas.HealthCheckOut, responses=ERRORS)
def health_check(
    request: Request, session: Session = Depends(get_session), user: User = Depends(napix_operator)
) -> schemas.HealthCheckOut:
    """One Overview call through the integration layer (logged in `napix_call_log`, audited); refused without a
    call when the switch is off (409 `napix_off`), a check ran in the last minute (429 `check_too_soon`) or the
    hourly quota is below the floor (429 `napix_budget`). The payload is not returned."""
    settings = request.app.state.settings
    actor = actor_of(request, user, session)
    try:
        napix_admin.acting_member(
            session, user, Permission.ADMIN_NAPIX_REFETCH, Permission.ADMIN_MASTERS_SYNC
        )
        napix_admin.check_guard(session, settings)
        client, hc = napix_client(request)
        outcome = asyncio.run(napix_admin.health_check(session, actor, user, settings, client, hc))
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.HealthCheckOut(**outcome.to_dict())


# ------------------------------------------------------------------------------------------------ the buttons


@router.post(
    "/napix/sync-masters",
    response_model=schemas.QueueStateOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses=ERRORS,
)
def sync_masters(
    request: Request, session: Session = Depends(get_session), user: User = Depends(masters_syncer)
) -> schemas.QueueStateOut:
    """Queue `masters/all` at priority 10 (re-queued when done); the worker fetches it."""
    try:
        state = napix_admin.request_masters_sync(
            session, actor_of(request, user, session), user, request.app.state.settings
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.QueueStateOut(**state)


@router.post(
    "/napix/refetch/day",
    response_model=schemas.QueueStateOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses=ERRORS,
)
def refetch_day(
    body: schemas.RefetchDayIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(refetcher),
) -> schemas.QueueStateOut:
    """Queue `causelist_day/<date>` at priority 20 in the request lane (not after tomorrow, IST); 409
    `already_held` for a day already in the database (done with lists, or skipped) unless `force`."""
    try:
        state = napix_admin.refetch_day(
            session,
            actor_of(request, user, session),
            user,
            body.date,
            request.app.state.settings,
            force=body.force,
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.QueueStateOut(**state)


@router.post(
    "/napix/refetch/case",
    response_model=schemas.QueueStateOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses=ERRORS,
)
def refetch_case(
    body: schemas.RefetchCaseIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(refetcher),
) -> schemas.QueueStateOut:
    """Queue the dossier of a case you may see at priority 30 (by CNR, or by the printed number for a provisional
    case); 409 `merged` with the surviving case's `ref_no`, 409 `no_reference`, 409 `already_held` for a case
    whose details are held unless `force`."""
    case = _case(session, body.case)
    try:
        state = napix_admin.refetch_case(
            session,
            actor_of(request, user, session),
            user,
            case,
            request.app.state.settings,
            force=body.force,
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.QueueStateOut(**state)


@router.post(
    "/napix/refetch/order",
    response_model=schemas.QueueStateOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses=ERRORS,
)
def refetch_order(
    body: schemas.RefetchOrderIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(refetcher),
) -> schemas.QueueStateOut:
    """Queue the PDF of an order of a case you may see at priority 30; 409 `already_stored`, `no_reference`."""
    case = _case(session, body.case)
    try:
        state = napix_admin.refetch_order(
            session, actor_of(request, user, session), user, case, body.order_id, request.app.state.settings
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.QueueStateOut(**state)


@router.post("/napix/queue/retry-failed", response_model=schemas.RetryFailedOut, responses=ERRORS)
def retry_failed(
    body: schemas.RetryFailedIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(napix_operator),
) -> schemas.RetryFailedOut:
    """Every failed row of one kind (of one lane when given) back to pending with no attempts (`masters` needs
    `admin.masters_sync`)."""
    kind = FetchKind(body.kind)
    lane = FetchLane(body.lane) if body.lane else None
    try:
        n = napix_admin.retry_failed(session, actor_of(request, user, session), user, kind, lane)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.RetryFailedOut(kind=kind.value, retried=n)


@router.post("/napix/queue/{item_id}/retry", response_model=schemas.QueueStateOut, responses=ERRORS)
def retry_item(
    item_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(napix_operator),
) -> schemas.QueueStateOut:
    """A failed or skipped row back to pending with no attempts; 409 `not_retryable` otherwise."""
    try:
        state = napix_admin.retry_item(
            session, actor_of(request, user, session), user, item_id, request.app.state.settings
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.QueueStateOut(**state)
