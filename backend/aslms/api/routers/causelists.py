"""`/causelists` (design `portal-causelist`): the dates with what is known about each, one day's benches and
lists, the day's entries as published with the portal's facts per row, and the original cause-list PDF. Every
endpoint is a read gated by `cases.view_scope` or `cases.view_all`; the file also needs `documents.view` (inline)
or `documents.download` (attachment). Reading writes nothing (no audit, no event, no NAPIX call). The static
routes `/dates` and `/lists/{id}/file` are declared before `/{list_date}`."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import get_session, require_any
from aslms.api.routers.documents import _serve, _store
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.services import causelist_view as svc
from aslms.services.causelist_view import CauselistNotFound, CauselistViewError, NoPdf, NotAllowed
from aslms.services.documents import DocumentError, FileMissing

router = APIRouter(prefix="/causelists", tags=["causelists"])

read = require_any(Permission.CASES_VIEW_SCOPE, Permission.CASES_VIEW_ALL)


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("/dates", response_model=schemas.CauselistDatesOut, responses={400: {"description": "bad range"}})
def causelist_dates(
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> schemas.CauselistDatesOut:
    """Decision 4: the dates of the range (at most 400 days; default today − 60 to today + 7, IST) with lists or
    a queue row, each with its state, and `default_date` — the first date on or after today with lists, else the
    latest."""
    try:
        out = svc.dates(session, date_from=from_, date_to=to)
    except CauselistViewError as exc:
        raise _bad(exc) from exc
    return schemas.CauselistDatesOut(**out)


@router.get(
    "/lists/{causelist_id}/file",
    responses={
        400: {"description": "bad disposition"},
        403: {"description": "without the file function"},
        404: {"model": schemas.ErrorOut},
    },
)
def causelist_file(
    causelist_id: uuid.UUID,
    request: Request,
    disposition: str = Query("attachment", pattern="^(inline|attachment)$"),
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> FileResponse:
    """Decision 9: the list's original PDF, `inline` (`documents.view`) or `attachment` (`documents.download`);
    404 `no_pdf` (with the list's `fetch_status`) when the court's PDF is not stored, 404 `file_missing` when the
    stored file is gone (a `source_failures` row is kept). Not audited."""
    try:
        served = svc.list_file(session, user, causelist_id, store=_store(request), disposition=disposition)
    except NotAllowed as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except CauselistNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such cause list") from exc
    except NoPdf as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            {"code": "no_pdf", "message": str(exc), "fetch_status": exc.fetch_status},
        ) from exc
    except FileMissing as exc:
        session.commit()  # the failure row survives the error
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "file_missing", "message": str(exc)}) from exc
    except (CauselistViewError, DocumentError) as exc:
        raise _bad(exc) from exc
    return _serve(served)


@router.get("/{list_date}", response_model=schemas.CauselistDayOut)
def causelist_day(
    list_date: date,
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> schemas.CauselistDayOut:
    """Decision 2: the day's benches ordered by court number, each with its label, court numbers, entry count and
    lists; a day with nothing is an empty answer with its state, never 404."""
    return schemas.CauselistDayOut(**svc.day(session, list_date))


@router.get(
    "/{list_date}/entries",
    response_model=schemas.CauselistEntriesOut,
    responses={400: {"description": "bad filter"}},
)
def causelist_entries(
    list_date: date,
    bench_id: int | None = None,
    list_id: uuid.UUID | None = None,
    list_type: str | None = None,
    court_no: str | None = None,
    q: str | None = None,
    only: str | None = None,
    limit: int = svc.DEFAULT_LIMIT,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> schemas.CauselistEntriesOut:
    """Decisions 1, 3, 6-8: every stored row of the date (narrowed by bench or list, list type and court), in
    court order, with `visible`, the owner, `held_by_you`, the recommendations the caller is shown and
    `claimable`; `q` (words over the printed row, or a CNR / case number) and `only` (`recommended`, `mine`,
    `claimable`, `unclaimed`, `claimed`, `visible`) narrow the page; `counts` are for the place."""
    try:
        out = svc.entries(
            session,
            user,
            list_date,
            bench_id=bench_id,
            list_id=list_id,
            list_type=list_type,
            court_no=court_no,
            q=q,
            only=only,
            limit=limit,
            offset=offset,
        )
    except CauselistViewError as exc:
        raise _bad(exc) from exc
    return schemas.CauselistEntriesOut(**out)
