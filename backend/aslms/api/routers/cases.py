"""`/cases`: the visible work list, search, the case detail and its tabs (design `cases-api`). `{ref}` is a
case id, `ref_no` (slash or dash form) or CNR. Reading needs `cases.view_scope` or `cases.view_all`, then
the one visibility rule per case (`services/visibility.py`): an unknown case and a case the caller may not
see both answer 404 "no such case". Search returns a summary of every non-merged case with `visible` per row.
Reading writes no audit row. `POST /cases/search-court` and `/cases/{ref}/fetch-court` (`cases.search_court`)
go to NAPIX through the integration layer, are guarded by the quota rules and audited. Routes `/cases/search`
and `/cases/search-court` are declared before `/cases/{ref}`."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, get_session, napix_client, require, require_any
from aslms.api.filters import case_filter_query, search_filter_query, with_legacy
from aslms.domain.cases import Case
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.services import case_detail, case_search, court_search
from aslms.services.case_filters import CaseFilters
from aslms.services.case_search import SearchError
from aslms.services.cases import CaseNotFound, resolve_case_ref
from aslms.services.court_search import (
    AlreadyFetched,
    CourtSearchError,
    CourtSearchFailure,
    NotFoundAtCourt,
)
from aslms.services.napix_store import NapixRecorder
from aslms.services.visibility import NotVisibleCase

router = APIRouter(prefix="/cases", tags=["cases"])

read = require_any(Permission.CASES_VIEW_SCOPE, Permission.CASES_VIEW_ALL)
NOT_FOUND = (NotVisibleCase, CaseNotFound)


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, NOT_FOUND):
        return HTTPException(status.HTTP_404_NOT_FOUND, "no such case")
    if isinstance(exc, SearchError | ValueError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    raise exc


def _case(session: Session, ref: str) -> Case:
    try:
        return resolve_case_ref(session, ref)
    except CaseNotFound as exc:
        raise _http(exc) from exc


# ------------------------------------------------------------------------------------------------ lists


@router.get("", response_model=schemas.CaseSearchListOut)
def list_cases(
    filters: CaseFilters = Depends(case_filter_query),
    field: str = "auto",
    case_state: str = "all",
    status_: str | None = Query(None, alias="status", deprecated=True, description="Use case_status"),
    office: str | None = Query(None, deprecated=True, description="Use owner"),
    limit: int = case_search.DEFAULT_LIMIT,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> schemas.CaseSearchListOut:
    """The caller's visible cases (the work list of officers, directorate users, standing counsel and the
    State-wide readers); `q` is optional, filters alone are fine; `total` is counted up to 10,000."""
    filters = with_legacy(filters, status=status_, office=office)
    try:
        page = case_search.list_visible(
            session, user, field_=field, case_state=case_state, filters=filters, limit=limit, offset=offset
        )
    except (SearchError, ValueError) as exc:
        raise _http(exc) from exc
    return schemas.CaseSearchListOut(items=page.items, total=page.total, total_capped=page.total_capped)


@router.get("/search", response_model=schemas.CaseSearchListOut)
def search_cases(
    filters: CaseFilters = Depends(search_filter_query),
    field: str = "auto",
    status_: str | None = Query(None, alias="status", deprecated=True, description="Use case_status"),
    office: str | None = Query(None, deprecated=True, description="Use owner"),
    visible_only: bool = False,
    limit: int = case_search.DEFAULT_LIMIT,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> schemas.CaseSearchListOut:
    """One box: a CNR, a case number (`WP(C) 4326/2025`), a `ref_no`, an id, or party / advocate words;
    every matching case as a court-public summary with `visible`, `owner_office_code`, `in_pool`, `claimable`."""
    filters = with_legacy(filters, status=status_, office=office)
    try:
        page = case_search.search(
            session,
            user,
            q=filters.q or "",
            field_=field,
            filters=filters,
            visible_only=visible_only,
            limit=limit,
            offset=offset,
        )
    except (SearchError, ValueError) as exc:
        raise _http(exc) from exc
    return schemas.CaseSearchListOut(items=page.items, total=page.total, total_capped=page.total_capped)


# ------------------------------------------------------------------------------------------------ detail


@router.get("/{ref}", response_model=schemas.CaseDetailOut)
def case_overview(
    ref: str, session: Session = Depends(get_session), user: User = Depends(read)
) -> schemas.CaseDetailOut:
    """Every typed column of the case, the court and bench, the small child lists, the compact ownership, the
    custody card, `access_basis` (why the caller sees it), `claimable`, `dossier_status` and the tab counts."""
    case = _case(session, ref)
    try:
        return schemas.CaseDetailOut(**case_detail.overview(session, user, case))
    except NOT_FOUND as exc:
        raise _http(exc) from exc


@router.get("/{ref}/parties", response_model=schemas.PartiesOut)
def case_parties(
    ref: str,
    include_former: bool = False,
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> schemas.PartiesOut:
    case = _case(session, ref)
    try:
        return schemas.PartiesOut(**case_detail.parties(session, user, case, include_former=include_former))
    except NOT_FOUND as exc:
        raise _http(exc) from exc


@router.get("/{ref}/hearings", response_model=schemas.HearingListOut)
def case_hearings(
    ref: str,
    limit: int = case_search.DEFAULT_LIMIT,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> schemas.HearingListOut:
    case = _case(session, ref)
    try:
        page = case_detail.hearings(session, user, case, limit=limit, offset=offset)
    except NOT_FOUND as exc:
        raise _http(exc) from exc
    return schemas.HearingListOut(items=page.items, total=page.total)


@router.get("/{ref}/orders", response_model=schemas.OrderListOut)
def case_orders(
    ref: str,
    limit: int = case_search.DEFAULT_LIMIT,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> schemas.OrderListOut:
    """The orders the dossier lists, newest first, with `download_status` and `document_id`; the file itself
    comes with `documents-uploads`."""
    case = _case(session, ref)
    try:
        page = case_detail.orders(session, user, case, limit=limit, offset=offset)
    except NOT_FOUND as exc:
        raise _http(exc) from exc
    return schemas.OrderListOut(items=page.items, total=page.total)


@router.get("/{ref}/listings", response_model=schemas.ListingListOut)
def case_listings(
    ref: str,
    limit: int = case_search.DEFAULT_LIMIT,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> schemas.ListingListOut:
    case = _case(session, ref)
    try:
        page = case_detail.listings(session, user, case, limit=limit, offset=offset)
    except NOT_FOUND as exc:
        raise _http(exc) from exc
    return schemas.ListingListOut(items=page.items, total=page.total)


@router.get("/{ref}/links", response_model=schemas.LinkListOut)
def case_links(
    ref: str, session: Session = Depends(get_session), user: User = Depends(read)
) -> schemas.LinkListOut:
    case = _case(session, ref)
    try:
        return schemas.LinkListOut(**case_detail.links(session, user, case))
    except NOT_FOUND as exc:
        raise _http(exc) from exc


@router.get("/{ref}/links/graph", response_model=schemas.LinkGraphOut, response_model_by_alias=True)
def case_link_graph(
    ref: str,
    depth: int = Query(2, ge=1, le=3),
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> schemas.LinkGraphOut:
    case = _case(session, ref)
    try:
        return schemas.LinkGraphOut(**case_detail.link_graph(session, user, case, depth=depth))
    except NOT_FOUND as exc:
        raise _http(exc) from exc


@router.get("/{ref}/timeline", response_model=schemas.TimelineListOut)
def case_timeline(
    ref: str,
    limit: int = case_search.DEFAULT_LIMIT,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> schemas.TimelineListOut:
    """Court and ownership events, newest first; other departments' recommendations only with
    `cases.view_all`; notes, documents, requests, stages and alerts join in their own items."""
    case = _case(session, ref)
    try:
        page = case_detail.timeline(session, user, case, limit=limit, offset=offset)
    except NOT_FOUND as exc:
        raise _http(exc) from exc
    return schemas.TimelineListOut(items=page.items, total=page.total)


# ------------------------------------------------------------------------------------------------ the court


def _court_http(exc: Exception) -> HTTPException:
    if isinstance(exc, CourtSearchFailure):
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        return HTTPException(
            exc.http_status,
            {"code": exc.code, "message": exc.message, "retry_after": exc.retry_after},
            headers=headers,
        )
    if isinstance(exc, AlreadyFetched):
        return HTTPException(status.HTTP_409_CONFLICT, {"code": "already_fetched", "message": str(exc)})
    if isinstance(exc, NotFoundAtCourt):
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": "not_found_at_court", "message": str(exc)})
    if isinstance(exc, CourtSearchError | ValueError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, {"code": "bad_input", "message": str(exc)})
    raise exc


COURT_HANDLED = (CourtSearchFailure, AlreadyFetched, NotFoundAtCourt, CourtSearchError, ValueError)


async def _with_napix(request: Request, user_id: uuid.UUID, fn):
    """The integration client with a recorder carrying the caller's id (design napix-window, decision 9)."""
    client, hc = napix_client(request)
    recorder = NapixRecorder(user_id=user_id)
    client.on_call = recorder.on_call
    async with client:
        return await fn(hc, recorder)


@router.post(
    "/search-court", response_model=schemas.CourtSearchOut, responses={503: {"model": schemas.ErrorOut}}
)
def search_court(
    body: schemas.CourtSearchIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require(Permission.CASES_SEARCH_COURT)),
) -> schemas.CourtSearchOut:
    """Search the court through NAPIX: by CNR (the dossier is fetched and stored), by case number (every row
    stored, the exact row's dossier fetched) or by party name (rows stored, dossiers on demand through
    `fetch-court`). Refused when the switch is off (503 `napix_off`), the hourly quota is below the floor (503
    `napix_budget`) or the caller used their hourly searches (429 `search_limit`). Audited."""
    settings = request.app.state.settings
    actor = actor_of(request, user, session)
    try:
        court_search.guard(session, user, settings)
        result = asyncio.run(
            _with_napix(
                request,
                user.id,
                lambda hc, recorder: court_search.search_court(
                    session, actor, user, body.model_dump(), hc=hc, recorder=recorder, settings=settings
                ),
            )
        )
    except COURT_HANDLED as exc:
        session.commit()  # the call log and the audit row survive the error
        raise _court_http(exc) from exc
    return schemas.CourtSearchOut(
        source=result.source,
        calls=result.calls,
        created=result.created,
        items=[case_search.item_for(session, user, c, match=body.kind) for c in result.cases],
        unmatched=result.unmatched,
    )


@router.post(
    "/{ref}/fetch-court",
    response_model=schemas.CaseSearchItemOut,
    responses={409: {"model": schemas.ErrorOut}},
)
def fetch_court(
    ref: str,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require(Permission.CASES_SEARCH_COURT)),
) -> schemas.CaseSearchItemOut:
    """Fetch the dossier of a case that has none (a provisional case is resolved by its number first; the CNR
    always comes from the court). The case need not be visible: the call only fills court data."""
    settings = request.app.state.settings
    case = _case(session, ref)
    actor = actor_of(request, user, session)
    try:
        court_search.guard(session, user, settings)
        case = asyncio.run(
            _with_napix(
                request,
                user.id,
                lambda hc, recorder: court_search.fetch_court(
                    session, actor, user, case, hc=hc, recorder=recorder, settings=settings
                ),
            )
        )
    except COURT_HANDLED as exc:
        session.commit()
        raise _court_http(exc) from exc
    return schemas.CaseSearchItemOut(**case_search.item_for(session, user, case, match="fetch"))
