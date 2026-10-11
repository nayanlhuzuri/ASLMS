"""`/admin/data-load*`: the data-load console (design `data-load-console`). Reading (progress, coverage, duplicates)
needs `admin.data_load` or a health reader (`reports.state`, `admin.napix_refetch`, `admin.masters_sync`); every
action needs `admin.data_load` and is audited. No `GET` calls NAPIX; only `POST /admin/data-load/fetch` does,
through the integration layer and the court-search guard. Warnings (`already_held`, `searched_before`) are 409
answers that write nothing and make no call; the client repeats the request with `force: true`. Errors carry
`{code, message}`; times are in IST."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, get_session, napix_client, require, require_any
from aslms.api.errors import detail
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.services import case_search, data_load
from aslms.services.access import Forbidden
from aslms.services.audit_search import to_ist
from aslms.services.court_search import CourtSearchError, CourtSearchFailure
from aslms.services.napix_store import NapixRecorder

router = APIRouter(prefix="/admin/data-load", tags=["data-load"])
load_reader = require_any(*data_load.READERS)
load_manager = require(Permission.ADMIN_DATA_LOAD)
ERRORS = {
    400: {"model": schemas.ErrorOut},
    403: {"model": schemas.ErrorOut},
    409: {"model": schemas.ErrorOut},
    429: {"model": schemas.ErrorOut},
    502: {"model": schemas.ErrorOut},
    503: {"model": schemas.ErrorOut},
    504: {"model": schemas.ErrorOut},
}


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, Forbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail(exc.code, str(exc)))
    if isinstance(exc, data_load.LoadInputError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail(exc.code, str(exc)))
    if isinstance(exc, CourtSearchError | ValueError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail("bad_input", str(exc)))
    if isinstance(exc, data_load.LoadConflict):
        return HTTPException(status.HTTP_409_CONFLICT, detail(exc.code, str(exc), **exc.extra))
    if isinstance(exc, data_load.SearchTimeout):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail("search_timeout", str(exc)))
    if isinstance(exc, CourtSearchFailure):
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        return HTTPException(
            exc.http_status, detail(exc.code, exc.message, retry_after=exc.retry_after), headers=headers
        )
    raise exc


HANDLED = (
    Forbidden,
    data_load.LoadInputError,
    data_load.LoadConflict,
    data_load.SearchTimeout,
    CourtSearchFailure,
    CourtSearchError,
)


def _settings_out(s: data_load.LoadSettings) -> schemas.DataLoadSettingsOut:
    return schemas.DataLoadSettingsOut(**data_load.settings_dict(s))


# ------------------------------------------------------------------------------------------------ reading


@router.get("", response_model=schemas.DataLoadOut, responses=ERRORS)
def get_progress(
    request: Request, session: Session = Depends(get_session), user: User = Depends(load_reader)
) -> schemas.DataLoadOut:
    """Settings, the load period and its totals, work left by kind, failures, the hour's allowance by lane and the
    estimated finish with its basis (or why there is none). Never calls NAPIX."""
    return schemas.DataLoadOut(**data_load.progress(session, request.app.state.settings))


@router.get("/coverage", response_model=schemas.CoverageOut, responses=ERRORS)
def get_coverage(
    request: Request,
    from_: str | None = Query(None, alias="from", pattern=r"^\d{4}-\d{2}$"),
    to: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    session: Session = Depends(get_session),
    user: User = Depends(load_reader),
) -> schemas.CoverageOut:
    """Month by month (`YYYY-MM`, default the load period, at most 36 months): days, lists, entries, cases with and
    without details, orders, work left and failures; 503 `search_timeout` when the query takes too long."""
    try:
        months = data_load.coverage(session, request.app.state.settings, from_, to)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.CoverageOut(months=months)


@router.get("/duplicates", response_model=schemas.DuplicatesOut, responses=ERRORS)
def get_duplicates(
    kind: str = Query("review", pattern="^(merged|court|review)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    user: User = Depends(load_reader),
) -> schemas.DuplicatesOut:
    """Merged rows, court-duplicate links, or provisional rows waiting for review; ref, CNR and case number only."""
    try:
        total, items = data_load.duplicates(session, kind, limit=limit, offset=offset)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.DuplicatesOut(total=total, items=items)


# ------------------------------------------------------------------------------------------------ the load


@router.post("/preview", response_model=schemas.LoadPreviewOut, responses=ERRORS)
def preview(
    body: schemas.LoadRangeIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(load_manager),
) -> schemas.LoadPreviewOut:
    """The days of a range by state and the calls the new days need; writes nothing, makes no call."""
    try:
        data_load.acting_member(session, user, Permission.ADMIN_DATA_LOAD)
        out = data_load.preview(session, request.app.state.settings, body.from_, body.to)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.LoadPreviewOut(**out.as_dict())


@router.post(
    "/start", response_model=schemas.LoadStartOut, status_code=status.HTTP_202_ACCEPTED, responses=ERRORS
)
def start(
    body: schemas.LoadStartIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(load_manager),
) -> schemas.LoadStartOut:
    """Queue every day of the range in the load lane; 409 `already_held` with the counts when the range holds days
    already in the database and `held` (skip / refetch) is absent. Audited `data_load.started`."""
    try:
        out = data_load.start(session, actor_of(request, user, session), user, body.from_, body.to, body.held)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.LoadStartOut(**out.as_dict())


@router.post("/pause", response_model=schemas.DataLoadSettingsOut, responses=ERRORS)
def pause(
    body: schemas.LoadPauseIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(load_manager),
) -> schemas.DataLoadSettingsOut:
    """Pause the backdated load at the next claim of any worker; the daily cycle and requests keep running."""
    try:
        out = data_load.pause(session, actor_of(request, user, session), user, body.reason)
    except HANDLED as exc:
        raise _http(exc) from exc
    return _settings_out(out)


@router.post("/resume", response_model=schemas.DataLoadSettingsOut, responses=ERRORS)
def resume(
    request: Request,
    body: schemas.LoadResumeIn | None = None,
    session: Session = Depends(get_session),
    user: User = Depends(load_manager),
) -> schemas.DataLoadSettingsOut:
    try:
        out = data_load.resume(session, actor_of(request, user, session), user, body.reason if body else None)
    except HANDLED as exc:
        raise _http(exc) from exc
    return _settings_out(out)


@router.put("/order", response_model=schemas.LoadOrderOut, responses=ERRORS)
def set_order(
    body: schemas.LoadOrderIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(load_manager),
) -> schemas.LoadOrderOut:
    """What goes first: the preset and an optional period brought forward (inside the load period); every pending
    load row is re-prioritised."""
    try:
        settings, n = data_load.set_order(
            session,
            actor_of(request, user, session),
            user,
            body.load_order,
            body.first_from,
            body.first_to,
            body.reason,
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.LoadOrderOut(settings=_settings_out(settings), reprioritised=n)


# ------------------------------------------------------------------------------------------------ single cases


def _held_items(session: Session, user: User, exc: data_load.AlreadyHeld) -> list[dict]:
    out = []
    for case in exc.cases:
        item = case_search.item_for(session, user, case, match="held")
        item["dossier_fetched_at"] = to_ist(case.last_full_refresh_at)
        item["dossier_stale"] = bool(case.dossier_stale)
        out.append(schemas.HeldCaseOut(**item).model_dump(mode="json"))
    return out


async def _with_napix(request: Request, fn):
    client, hc = napix_client(request)
    recorder = NapixRecorder()
    client.on_call = recorder.on_call
    async with client:
        return await fn(hc, recorder)


@router.post("/fetch", response_model=schemas.CourtSearchOut, responses=ERRORS)
def fetch(
    body: schemas.LoadFetchIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(load_manager),
) -> schemas.CourtSearchOut:
    """Fetch cases from the court by CNR, case number or party name. Without `force`, a case already held with its
    details answers 409 `already_held` and a party name searched before 409 `searched_before`, with no call. The
    court-search guard applies (503 `napix_off` / `napix_budget`, 429 `search_limit`). Audited `case.search_court`
    with `via: data_load`. Results are summaries with `visible`."""
    settings = request.app.state.settings
    actor = actor_of(request, user, session)
    payload = body.model_dump()
    force = bool(payload.pop("force", False))
    try:
        data_load.acting_member(session, user, Permission.ADMIN_DATA_LOAD)
        if not force:
            held = data_load.check_held(session, payload, est_code=settings.napix_est_code)
            if isinstance(held, data_load.AlreadyHeld):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail(held.code, str(held), cases=_held_items(session, user, held)),
                )
            if held is not None:
                raise held
        result = asyncio.run(
            _with_napix(
                request,
                lambda hc, recorder: data_load.fetch(
                    session, actor, user, payload, force=force, hc=hc, recorder=recorder, settings=settings
                ),
            )
        )
    except HANDLED as exc:
        if isinstance(exc, CourtSearchFailure):
            session.commit()  # the call log and the audit row survive the error
        raise _http(exc) from exc
    return schemas.CourtSearchOut(
        source=result.source,
        calls=result.calls,
        created=result.created,
        items=[case_search.item_for(session, user, c, match=body.kind) for c in result.cases],
        unmatched=result.unmatched,
    )


@router.post("/fetch-details", response_model=schemas.FetchDetailsOut, responses=ERRORS)
def fetch_details(
    body: schemas.FetchDetailsIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(load_manager),
) -> schemas.FetchDetailsOut:
    """Queue the details (dossiers) of found cases in the request lane at priority 30; cases with details are
    reported `already_held` and queued only with `force`. Audited `data_load.details_requested`."""
    settings = request.app.state.settings
    try:
        states = data_load.fetch_details(
            session, actor_of(request, user, session), user, body.cases, body.force, settings
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    items = []
    for d in states:
        items.append(
            schemas.FetchDetailItemOut(
                ref=d.ref,
                case=case_search.item_for(session, user, d.case, match="details")
                if d.case is not None
                else None,
                state=d.state,
                queue=schemas.QueueStateOut(**d.queue) if d.queue else None,
                merged_into_ref_no=d.merged_into_ref_no,
            )
        )
    return schemas.FetchDetailsOut(items=items)


@router.post("/duplicates/scan", response_model=schemas.DedupeScanOut, responses=ERRORS)
def scan_duplicates(
    request: Request, session: Session = Depends(get_session), user: User = Depends(load_manager)
) -> schemas.DedupeScanOut:
    """Run the duplicate rules over every case now (merge, link, list for review); audited."""
    try:
        report = data_load.scan(session, actor_of(request, user, session), user)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.DedupeScanOut(**report.counts())
