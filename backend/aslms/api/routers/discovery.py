"""`/admin/discovery*`: department discovery (design `department-discovery`, with the owner's decisions of 14 Oct
2026). The Court search tab reads the caller's terms and the cases they found (`admin.keywords`, scoped to the
caller's subtree; case summaries only, details stay behind the case visibility rule) and asks for a name's years
(`POST /admin/discovery/search`: no call counts and no "searched before" warning). The Data
collection screens read the share and the queue (`GET /admin/discovery`, the data-load readers) and start a manual
sweep (`admin.data_load`). No endpoint calls NAPIX: everything is queued for the worker. Errors carry
`{code, message}`; times are in IST."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, get_session, require, require_any
from aslms.api.errors import detail, list_error
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.services import data_load, discovery
from aslms.services.access import Forbidden
from aslms.services.audit_search import to_ist
from aslms.services.case_filters import CaseFilterError
from aslms.services.list_search import ListSearchError
from aslms.services.list_sort import ListSortError
from aslms.services.offices import find_office

router = APIRouter(prefix="/admin/discovery", tags=["discovery"])
keywords_reader = require(Permission.ADMIN_KEYWORDS)
data_reader = require_any(*data_load.READERS)
sweeper = require(Permission.ADMIN_DATA_LOAD)
ERRORS = {
    400: {"model": schemas.ErrorOut},
    403: {"model": schemas.ErrorOut},
    404: {"model": schemas.ErrorOut},
    409: {"model": schemas.ErrorOut},
}
HANDLED = (Forbidden, discovery.DiscoveryError, discovery.DiscoveryNotFound, discovery.DiscoveryConflict)
LIST_ERRORS = (ListSearchError, ListSortError, CaseFilterError)
TIME_KEYS = (
    "last_searched_at",
    "full_sweep_queued_at",
    "recent_sweep_queued_at",
    "first_found_at",
    "last_found_at",
)


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, Forbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail(exc.code, str(exc)))
    if isinstance(exc, discovery.DiscoveryError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail(exc.code, str(exc)))
    if isinstance(exc, discovery.DiscoveryNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail("not_found", str(exc)))
    if isinstance(exc, discovery.DiscoveryConflict):
        return HTTPException(status.HTTP_409_CONFLICT, detail(exc.code, str(exc), **exc.extra))
    raise exc


def _ist(item: dict[str, Any]) -> dict[str, Any]:
    return {k: (to_ist(v) if k in TIME_KEYS else v) for k, v in item.items()}


@router.get("/terms", response_model=schemas.DiscoveryTermListOut, responses=ERRORS)
def list_terms(
    office: str | None = None,
    status_: str = Query("active", alias="status", description="active, inactive or all"),
    limit: int = discovery.DEFAULT_LIMIT,
    offset: int = 0,
    q: str | None = Query(None, description="the name or a department code (2 to 100 characters)"),
    sort: str | None = Query(None, description="name (default), last_searched or cases_found"),
    dir: str | None = Query(None, description="asc or desc"),  # noqa: A002
    session: Session = Depends(get_session),
    user: User = Depends(keywords_reader),
) -> schemas.DiscoveryTermListOut:
    """The terms with at least one rule ticked "Search the court" in the caller's subtree (all for the super admin):
    their rules and departments inside that subtree, years searched / waiting / failed, the last search and the
    cases found. `status` is `active` (default), `inactive` or `all`. `q`, `sort` and `dir` search and order the list
    (design list-search, decision 15); `total_all` is the count without `q`."""
    root = None
    if office:
        root = find_office(session, office)
        if root is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail("bad_input", f"no such office {office!r}")
            )
    try:
        items, total, total_all = discovery.terms_view(
            session, user, office=root, status=status_, limit=limit, offset=offset, q=q, sort=sort, dir=dir
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    except LIST_ERRORS as exc:
        raise list_error(exc) from exc
    return schemas.DiscoveryTermListOut(items=[_ist(i) for i in items], total=total, total_all=total_all)


@router.get("/terms/{term_id}/cases", response_model=schemas.DiscoveryCaseListOut, responses=ERRORS)
def term_cases(
    term_id: uuid.UUID,
    only: str = "all",
    limit: int = discovery.DEFAULT_LIMIT,
    offset: int = 0,
    q: str | None = Query(None, description="the case search: CNR, case number, reference or words"),
    sort: str | None = Query(None, description="last_found (default), case_no or year"),
    dir: str | None = Query(None, description="asc or desc"),  # noqa: A002
    session: Session = Depends(get_session),
    user: User = Depends(keywords_reader),
) -> schemas.DiscoveryCaseListOut:
    """The cases a term found (summaries), latest found first, with the owner, the caller's departments'
    recommendation (every department's with `cases.view_all`) and `claimable`. `only` is `all`, `pool`,
    `recommended` or `owned`. 404 when the term has no rule in the caller's subtree. `q` (the case search) only
    narrows; `sort` and `dir` order the list (design list-search, decision 15)."""
    try:
        items, total, total_all = discovery.term_cases(
            session, user, term_id, only=only, limit=limit, offset=offset, q=q, sort=sort, dir=dir
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    except LIST_ERRORS as exc:
        raise list_error(exc) from exc
    return schemas.DiscoveryCaseListOut(items=[_ist(i) for i in items], total=total, total_all=total_all)


@router.post("/search", response_model=schemas.DiscoverySearchOut, status_code=202, responses=ERRORS)
def search_years(
    body: schemas.DiscoverySearchIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(keywords_reader),
) -> schemas.DiscoverySearchOut:
    """Search the court for one of the department's names in the chosen years (older years included). The searches
    are queued; found cases appear on the term's list as they arrive. A year already searched simply runs again,
    with no warning (owner, 14 Oct 2026). 400 `not_a_term` when the name is not an active rule ticked "Search the
    court" in the caller's offices. Audited `discovery.sweep`."""
    try:
        out = discovery.request_years(
            session,
            actor_of(request, user, session),
            user,
            name=body.name,
            years=body.years,
            force=body.force,
            settings=request.app.state.settings,
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.DiscoverySearchOut(**out)


@router.get("", response_model=schemas.DiscoverySummaryOut, responses=ERRORS)
def get_summary(
    request: Request, session: Session = Depends(get_session), user: User = Depends(data_reader)
) -> schemas.DiscoverySummaryOut:
    """The discovery block of the Data collection screens: the share and the discovery calls of the current window,
    discovery-lane rows by kind, terms, cases found and created, the latest failures. No case data."""
    return schemas.DiscoverySummaryOut(**discovery.summary(session, request.app.state.settings))


@router.post("/sweep", response_model=schemas.DiscoverySweepOut, status_code=202, responses=ERRORS)
def post_sweep(
    body: schemas.DiscoverySweepIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(sweeper),
) -> schemas.DiscoverySweepOut:
    """Queue a sweep (2025 to the current year) of one term or of every active term; 404 unknown term, 409
    `term_inactive`. Audited `discovery.sweep`."""
    try:
        out = discovery.sweep(
            session,
            actor_of(request, user, session),
            user,
            term_id=body.term_id,
            settings=request.app.state.settings,
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.DiscoverySweepOut(**out)
