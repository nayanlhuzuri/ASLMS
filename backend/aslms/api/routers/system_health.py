"""`/admin/system-health`: the System health screen (designs `api-health-checker` and `system-health-inspector`).
Every endpoint needs `admin.service_health`, reading included. The court cards, the request console, the reference,
the documents and the token state are read without calling NAPIX; only `POST …/napix/{api}/test` (Send: one court
call, audited `napix.api_tested`) and `POST …/token/check` (one token request, audited `napix.token_checked`) reach
the court, through the integration layer. The full decrypted answer also needs `cases.view_all` (audited
`napix.response_viewed`). No secret is ever in an answer. Errors carry `{code, message}`, plus `retry_after` and a
`Retry-After` header on 429, and `errors` (per parameter) on 422 `invalid_input`. Times are in IST."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, apart_factory, get_session, napix_request, require
from aslms.api.errors import detail
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.integration.napix.client import TokenCache
from aslms.services import (
    napix_api_check,
    napix_inspect,
    napix_reference,
    napix_token,
    service_checks,
    system_health,
)
from aslms.services.access import Forbidden
from aslms.services.audit_search import to_ist

router = APIRouter(prefix="/admin/system-health", tags=["system-health"])
holder = require(Permission.ADMIN_SERVICE_HEALTH)
ERRORS = {
    403: {"model": schemas.ErrorOut},
    404: {"model": schemas.ErrorOut},
    409: {"model": schemas.ErrorOut},
    422: {"model": schemas.ErrorOut},
    429: {"model": schemas.ErrorOut},
}
DOCS_ERRORS = {403: {"model": schemas.ErrorOut}, 404: {"model": schemas.ErrorOut}}


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, Forbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail(exc.code, str(exc)))
    if isinstance(exc, system_health.UnknownApi):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail("not_found", "no such court API"))
    if isinstance(exc, napix_api_check.TestRefused):
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        body = detail(exc.code, str(exc), retry_after=exc.retry_after)
        return HTTPException(exc.http_status, body, headers=headers)
    if isinstance(exc, napix_inspect.InvalidInput):
        return HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail("invalid_input", "Some values are not valid for this API", errors=exc.errors),
        )
    if isinstance(exc, napix_inspect.NoResponse):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail("no_response", str(exc)))
    if isinstance(exc, napix_inspect.TooLarge):
        return HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail(
                "too_large", f"The answer is too large to show ({exc.size} bytes); its structure is shown"
            ),
        )
    if isinstance(exc, napix_inspect.DocMissing):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail("doc_missing", str(exc)))
    raise exc


HANDLED = (
    Forbidden,
    system_health.UnknownApi,
    napix_api_check.TestRefused,
    napix_inspect.InvalidInput,
    napix_inspect.NoResponse,
    napix_inspect.TooLarge,
    napix_inspect.DocMissing,
)


def token_cache(request: Request) -> TokenCache:
    """The shared token store: a test double on `app.state.napix_token_cache`, else Redis from the settings (the same
    copy the workers and every court call use)."""
    override = getattr(request.app.state, "napix_token_cache", None)
    return override if override is not None else TokenCache(request.app.state.settings.redis_url)


@router.get("", response_model=schemas.SystemHealthOut)
def get_system_health(
    request: Request, session: Session = Depends(get_session), user: User = Depends(holder)
) -> schemas.SystemHealthOut:
    """The 17 court cards in four groups, read from the call log of the last 7 days, the detected quota window and
    the summary. Never calls NAPIX and never probes the services."""
    return schemas.SystemHealthOut(**system_health.napix_cards(session, request.app.state.settings, user))


@router.get("/napix/{api}", response_model=schemas.ApiDetailOut, responses=ERRORS)
def get_api_detail(
    api: str, request: Request, session: Session = Depends(get_session), user: User = Depends(holder)
) -> schemas.ApiDetailOut:
    """One card with its 7 daily buckets, its last 10 calls, the held sample the test would use (a case is named
    only when the caller may see it; a name never) and the technical details. 404 for an unknown key. Never calls
    NAPIX."""
    try:
        body = system_health.api_detail(session, request.app.state.settings, user, api)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.ApiDetailOut(**body)


@router.post("/napix/{api}/test", response_model=schemas.ApiTestOut, responses=ERRORS)
def test_api(
    api: str,
    request: Request,
    body: schemas.ConsoleValuesIn | None = Body(None),
    session: Session = Depends(get_session),
    user: User = Depends(holder),
) -> schemas.ApiTestOut:
    """Send: ONE court call to this API, on a fresh client with no retry, logged and audited. With a body, the values
    in the console's form (any parameter, checked first: 422 `invalid_input`); without one, an input ASLMS holds (the
    server picks it). Refused with no call and nothing written: 404 `not_found`; 409 `napix_off`, `no_sample` (no body
    and nothing held), `sample_hidden` (no body and the held sample belongs to a case you cannot see), `test_running`, `user_test_running` (your other test is still running: one test at a time per
    person); 429 `test_too_soon`, `test_limit`, `napix_budget`. The court's own failure is a 200 with `ok: false`.
    Nothing is applied to case data. ASLMS's own failure after the call answers 500: the call and its audit row are
    recorded before the error."""
    settings = request.app.state.settings
    actor = actor_of(request, user, session)
    factory = apart_factory(request)
    values = body.values if body is not None else None
    try:
        napix_api_check.guard(session, settings, user, api, values=values)
        # run() takes the guard again inside the slot (design followups-oct, decision 3)
        with napix_request(request, session) as (client, hc):
            client.tokens = token_cache(request)
            outcome = asyncio.run(
                napix_api_check.run(session, factory, actor, user, settings, client, hc, api, values)
            )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.ApiTestOut(**outcome.to_dict())


@router.get("/napix/{api}/console", response_model=schemas.ConsoleOut, responses=ERRORS)
def get_console(
    api: str, request: Request, session: Session = Depends(get_session), user: User = Depends(holder)
) -> schemas.ConsoleOut:
    """The request console of one court API: the form pre-filled with the held sample (a name, a CNR, a case or a
    filing number only when the caller may see the case), the request built from the code that sends it (method, URL,
    plain string, the masked envelope, `request_token`, the cURL template), the Send state, the last send, the latest
    stored answer and the documentation link. Never calls NAPIX; not audited."""
    try:
        body = napix_inspect.console(session, request.app.state.settings, user, api)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.ConsoleOut(**body)


@router.post("/napix/{api}/preview", response_model=schemas.ConsoleRequestOut, responses=ERRORS)
def preview_request(
    api: str,
    body: schemas.ConsoleValuesIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(holder),
) -> schemas.ConsoleRequestOut:
    """The request for the form's values (422 `invalid_input` with a message per parameter). No call; not audited."""
    settings = request.app.state.settings
    try:
        e, p = napix_inspect.preview_values(session, settings, api, body.values)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.ConsoleRequestOut(**napix_inspect.request_part(settings, e, p))


@router.post(
    "/napix/{api}/postman",
    responses={
        **ERRORS,
        200: {"content": {"application/json": {}}, "description": "a Postman v2.1 collection"},
    },
)
def export_postman(
    api: str,
    body: schemas.ConsoleValuesIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(holder),
) -> Response:
    """A Postman v2.1 collection for this API and the form's values (checked as the preview): the token request, this
    request with `input=<plain string>` and the collection's encrypt and verify scripts. Every secret variable is
    empty. No call; not audited."""
    settings = request.app.state.settings
    try:
        e, p = napix_inspect.preview_values(session, settings, api, body.values)
    except HANDLED as exc:
        raise _http(exc) from exc
    collection = napix_inspect.postman_collection(settings, p, e.label)
    name = f"aslms-napix-{api}.postman_collection.json"
    return Response(
        json.dumps(collection, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "private, no-store",
        },
    )


@router.get(
    "/napix/{api}/response",
    response_model=schemas.StoredResponseOut,
    responses={**ERRORS, 413: {"model": schemas.ErrorOut}},
)
def get_stored_response(
    api: str,
    request: Request,
    source: Literal["send", "latest"] = Query("send"),
    response_id: uuid.UUID | None = Query(None),
    session: Session = Depends(get_session),
    user: User = Depends(holder),
) -> schemas.StoredResponseOut:
    """The full decrypted answer of a send (`source=send&response_id=…`) or the latest stored answer
    (`source=latest`), verbatim from `napix_responses`. Also needs `cases.view_all` (403 `forbidden`): a search answer
    names cases the caller might not otherwise see. Each opening is audited `napix.response_viewed` (never the
    payload). 404 `no_response`; 413 `too_large` over `HEALTH_RAW_MAX_BYTES`."""
    settings = request.app.state.settings
    try:
        body = napix_inspect.stored_response(session, settings, user, api, source, response_id)
    except HANDLED as exc:
        raise _http(exc) from exc
    napix_inspect.record_view(session, actor_of(request, user, session), api, body)
    return schemas.StoredResponseOut(**body)


@router.get("/napix/{api}/reference", response_model=schemas.ReferenceOut, responses=ERRORS)
def get_reference(api: str, request: Request, user: User = Depends(holder)) -> schemas.ReferenceOut:
    """The in-app NAPIX reference of one court API (inputs, outputs, statuses, how a request is built and an answer
    read, the document links), or of the token request with `api=token`. Static."""
    settings = request.app.state.settings
    if api == "token":
        body = napix_reference.token_reference()
    elif api in system_health.BY_KEY:
        body = napix_reference.reference(api)
    else:
        raise _http(system_health.UnknownApi(api))
    body["doc"] = {**body["doc"], "available": napix_inspect.doc_available(settings, body["doc"]["doc"])}
    return schemas.ReferenceOut(**body)


@router.get("/docs", response_model=list[schemas.NapixDocOut])
def list_docs(request: Request, user: User = Depends(holder)) -> list[schemas.NapixDocOut]:
    """The three NAPIX documents and whether each is installed on this server (pinned by SHA-256)."""
    return [schemas.NapixDocOut(**d) for d in napix_inspect.docs_list(request.app.state.settings)]


@router.get(
    "/docs/{doc}",
    responses={**DOCS_ERRORS, 200: {"content": {"application/pdf": {}}, "description": "the PDF, inline"}},
)
def get_doc(doc: str, request: Request, user: User = Depends(holder)) -> Response:
    """One NAPIX document, inline (`#page=N` opens it at a page), behind the function; never from a public path. 404
    `not_found` for an unknown id, 404 `doc_missing` when the file is absent or not the pinned edition. Not
    audited."""
    if doc not in napix_reference.DOCS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail("not_found", "no such NAPIX document"))
    try:
        path = napix_inspect.doc_path(request.app.state.settings, doc)
    except HANDLED as exc:
        raise _http(exc) from exc
    name = path.name
    ascii_name = name.encode("ascii", "replace").decode("ascii").replace('"', "")
    disposition = f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
    return Response(
        path.read_bytes(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": disposition,
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/token", response_model=schemas.NapixTokenOut)
def get_token(
    request: Request, session: Session = Depends(get_session), user: User = Depends(holder)
) -> schemas.NapixTokenOut:
    """The access token's state (held, minutes left, issued, expires, accepted by the gateway since issue, the last
    renewal), read with no call and no token request; never the token. Not audited."""
    body = napix_token.state(session, request.app.state.settings, token_cache(request), user)
    return schemas.NapixTokenOut(**body)


@router.post("/token/check", response_model=schemas.NapixTokenCheckOut, responses=ERRORS)
def check_token(
    request: Request, session: Session = Depends(get_session), user: User = Depends(holder)
) -> schemas.NapixTokenCheckOut:
    """Check token: ONE token request (no retry) that replaces the shared token, audited `napix.token_checked`.
    Refused before any request and writing nothing: 409 `napix_off`, `check_running`; 429 `check_too_soon`,
    `test_limit` (shared with sends), `napix_budget`. A token-service failure is a 200 with `ok: false`."""
    settings = request.app.state.settings
    actor = actor_of(request, user, session)
    cache = token_cache(request)
    try:
        napix_token.check_guard(session, settings, user)
        # check() takes the guard again inside the slot (design followups-oct, decision 3)
        with napix_request(request, session) as (client, _hc):
            out = asyncio.run(
                napix_token.check(session, apart_factory(request), actor, user, settings, client, cache)
            )
    except HANDLED as exc:
        raise _http(exc) from exc
    token = schemas.NapixTokenOut(**napix_token.state(session, settings, cache, user))
    return schemas.NapixTokenCheckOut(**out, token=token)


@router.get("/services", response_model=schemas.ServicesOut)
def get_services(
    request: Request, session: Session = Depends(get_session), user: User = Depends(holder)
) -> schemas.ServicesOut:
    """The ten ASLMS service checks (in parallel, each within the probe timeout) and the overall line across the
    court cards and the services. Never calls NAPIX; not audited."""
    settings = request.app.state.settings
    now = datetime.now(UTC)
    services = service_checks.run_all(
        session, settings, now, getattr(request.app.state, "service_probes", None)
    )
    court = system_health.court_statuses(session, settings, now)
    return schemas.ServicesOut(
        checked_at=to_ist(now),
        overall=system_health.overall(court, [s["status"] for s in services]),
        services=services,
    )
