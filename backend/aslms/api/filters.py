"""The shared case filters as FastAPI query parameters (design `portal-filters`, decisions 1, 2 and 7).

The parameters are declared once here; a bad value answers 400 with the `CaseFilterError` message. Three
dependencies differ only in `q` and `owner`:
- `case_filter_query`: every shared filter (Files, Alerts, `GET /cases`);
- `search_filter_query`: the same with `q` required (`GET /cases/search`);
- `inbox_filter_query`: every shared filter except `owner` (the inbox tabs read for one department).
`with_legacy` maps the old names `status` / `office` where they meant the same thing (decision 2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import Depends, HTTPException, Query, status

from aslms.services import case_filters
from aslms.services.case_filters import CaseFilterError, CaseFilters


@dataclass
class _Shared:
    listed_from: date | None
    listed_to: date | None
    court_no: str | None
    bench: str | None
    next_from: date | None
    next_to: date | None
    next_differs: bool | None
    case_type: str | None
    year: int | None
    case_status: str | None


def _shared(
    listed_from: date | None = Query(
        None, description="A cause-list entry of the case dated on or after this day (IST)"
    ),
    listed_to: date | None = Query(
        None, description="A cause-list entry of the case dated on or before this day"
    ),
    court_no: str | None = Query(None, description="That same entry's court number, as printed"),
    bench: str | None = Query(
        None,
        description="That same entry's bench (judge names) contains this text (case and spacing ignored)",
    ),
    next_from: date | None = Query(None, description="Next hearing date on or after this day"),
    next_to: date | None = Query(None, description="Next hearing date on or before this day"),
    next_differs: bool | None = Query(
        None, description="Only cases whose latest order gives a date other than the court's record"
    ),
    case_type: str | None = Query(
        None, description="The case type: the master's short name or an alias, or the case's type text"
    ),
    year: int | None = Query(None, description="Registration year (1900-2100)"),
    case_status: str | None = Query(None, description="pending, disposed or unknown"),
) -> _Shared:
    return _Shared(
        listed_from,
        listed_to,
        court_no,
        bench,
        next_from,
        next_to,
        next_differs,
        case_type,
        year,
        case_status,
    )


Q_DESCRIPTION = (
    "Words as the Search box (at least 3 characters): a CNR, a case number (`WP(C) 4326/2025`), a `ref_no`, "
    "or words matched as prefixes over parties, advocates, counsel codes and numbers"
)
OWNER_DESCRIPTION = "The department holding the active primary ownership (a department code)"


def _parse(q: str | None, owner: str | None, shared: _Shared) -> CaseFilters:
    try:
        return case_filters.parse(q=q, owner=owner, **shared.__dict__)
    except CaseFilterError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def case_filter_query(
    q: str | None = Query(None, description=Q_DESCRIPTION),
    owner: str | None = Query(None, description=OWNER_DESCRIPTION),
    shared: _Shared = Depends(_shared),
) -> CaseFilters:
    return _parse(q, owner, shared)


def search_filter_query(
    q: str = Query(..., min_length=case_filters.MIN_QUERY, description=Q_DESCRIPTION),
    owner: str | None = Query(None, description=OWNER_DESCRIPTION),
    shared: _Shared = Depends(_shared),
) -> CaseFilters:
    return _parse(q, owner, shared)


def inbox_filter_query(
    q: str | None = Query(None, description=Q_DESCRIPTION),
    shared: _Shared = Depends(_shared),
) -> CaseFilters:
    return _parse(q, None, shared)


def with_legacy(f: CaseFilters, *, status: str | None = None, office: str | None = None) -> CaseFilters:
    """Decision 2 at the HTTP edge: 400 when an old name and a new name carry different values."""
    try:
        return case_filters.with_legacy(f, status=status, office=office)
    except CaseFilterError as exc:
        raise HTTPException(400, str(exc)) from exc
