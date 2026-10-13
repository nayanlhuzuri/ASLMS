"""`/inbox/*`: the department case inbox (design `recommend-and-claim`, decisions 15 and 23) — Recommended,
Claimed (Active / Disposed), the Unclaimed pool, Transfers and the dashboard counts. Summary data only; every
list is filtered on the server by the caller's department and functions (`services/inbox.py`); `?office=`
other than the caller's department needs `cases.view_all`. The lists take the shared case filters (design
`portal-filters`: `q`, `listed_from` / `listed_to`, `court_no`, `bench`, `next_from` / `next_to`, `case_type`,
`year`, `case_status`), which only narrow."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import current_user, get_session
from aslms.api.filters import inbox_filter_query, with_legacy
from aslms.domain.org import User
from aslms.services import inbox
from aslms.services.access import Forbidden
from aslms.services.case_filters import CaseFilters
from aslms.services.inbox import InboxError, OfficeRequired

router = APIRouter(prefix="/inbox", tags=["inbox"])


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, Forbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, OfficeRequired) and exc.candidates:
        return HTTPException(
            status.HTTP_400_BAD_REQUEST,
            {"code": "office_required", "message": str(exc), "candidates": exc.candidates},
        )
    if isinstance(exc, InboxError | ValueError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    raise exc


@router.get("/recommended", response_model=schemas.RecommendationListOut)
def recommended(
    office: str | None = None,
    band: str | None = None,
    filters: CaseFilters = Depends(inbox_filter_query),
    limit: int = inbox.DEFAULT_LIMIT,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> schemas.RecommendationListOut:
    """The department's active recommendations, strongest first, each with the signals behind its score;
    the shared case filters narrow them."""
    try:
        page = inbox.recommended(
            session, user, office=office, band=band, filters=filters, limit=limit, offset=offset
        )
    except (Forbidden, ValueError) as exc:
        raise _http(exc) from exc
    return schemas.RecommendationListOut(items=page.items, total=page.total)


@router.get("/claimed", response_model=schemas.OwnershipListOut)
def claimed(
    office: str | None = None,
    case_state: str = "active",
    role: str | None = None,
    unit: str | None = None,
    officer_user_id: uuid.UUID | None = None,
    filters: CaseFilters = Depends(inbox_filter_query),
    limit: int = inbox.DEFAULT_LIMIT,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> schemas.OwnershipListOut:
    """The department's active ownership rows the caller may see: the whole department for holders of
    `cases.claim` or `cases.allot`, otherwise the cases allotted to the caller or to a unit in their subtree.
    `case_state` splits Active (`pending` / `unknown`) from Disposed."""
    try:
        page = inbox.claimed(
            session,
            user,
            office=office,
            case_state=case_state,
            role=role,
            unit=unit,
            officer_user_id=officer_user_id,
            filters=filters,
            limit=limit,
            offset=offset,
        )
    except (Forbidden, ValueError) as exc:
        raise _http(exc) from exc
    return schemas.OwnershipListOut(items=page.items, total=page.total)


@router.get("/pool", response_model=schemas.PoolListOut)
def pool(
    filters: CaseFilters = Depends(inbox_filter_query),
    status_: str | None = Query(None, alias="status", deprecated=True, description="Use case_status"),
    scored_for: str | None = Query(
        None, description="Keep cases with a score row for this department (with min_score: on that row)"
    ),
    min_score: float | None = None,
    state_party: bool | None = None,
    limit: int = inbox.DEFAULT_LIMIT,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> schemas.PoolListOut:
    """The unclaimed pool: non-merged cases that have never had a primary owner, next hearing first."""
    filters = with_legacy(filters, status=status_)
    try:
        page = inbox.pool(
            session,
            user,
            filters=filters,
            scored_for=scored_for,
            min_score=min_score,
            state_party=state_party,
            limit=limit,
            offset=offset,
        )
    except (Forbidden, ValueError) as exc:
        raise _http(exc) from exc
    return schemas.PoolListOut(items=page.items, total=page.total)


@router.get("/transfers", response_model=schemas.TransferListOut)
def transfers(
    office: str | None = None,
    direction: str | None = None,
    status_: str | None = Query(None, alias="status", description="The transfer's status"),
    other_office: str | None = Query(
        None, description="The department on the other side (from for in, to for out, either without)"
    ),
    filters: CaseFilters = Depends(inbox_filter_query),
    limit: int = inbox.DEFAULT_LIMIT,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> schemas.TransferListOut:
    """Transfers in (`to` the department) or out (`from` it), newest first."""
    try:
        page = inbox.transfers(
            session,
            user,
            office=office,
            direction=direction,
            status=status_,
            other_office=other_office,
            filters=filters,
            limit=limit,
            offset=offset,
        )
    except (Forbidden, ValueError) as exc:
        raise _http(exc) from exc
    return schemas.TransferListOut(items=page.items, total=page.total)


@router.get("/counts", response_model=schemas.InboxCountsListOut)
def counts(
    office: str | None = None,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> schemas.InboxCountsListOut:
    """The dashboard counters, one block per department the caller works in (design `user-memberships`); a
    count is null when the caller lacks that tab's function in that department."""
    try:
        return schemas.InboxCountsListOut(**inbox.counts(session, user, office=office))
    except (Forbidden, ValueError) as exc:
        raise _http(exc) from exc
