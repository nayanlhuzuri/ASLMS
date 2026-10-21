"""`/admin/system-health`: the System health screen (design `api-health-checker`). Every endpoint needs
`admin.service_health`, reading included. The court cards are read from the call log and never call NAPIX; the
service checks never call NAPIX; only `POST /admin/system-health/napix/{api}/test` makes one court call through the
integration layer (audited `napix.api_tested`). Errors carry `{code, message}`, plus `retry_after` and a
`Retry-After` header on 429. Times are in IST."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, get_session, napix_client, require
from aslms.api.errors import detail
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.services import napix_api_check, service_checks, system_health
from aslms.services.access import Forbidden
from aslms.services.audit_search import to_ist

router = APIRouter(prefix="/admin/system-health", tags=["system-health"])
holder = require(Permission.ADMIN_SERVICE_HEALTH)
ERRORS = {
    403: {"model": schemas.ErrorOut},
    404: {"model": schemas.ErrorOut},
    409: {"model": schemas.ErrorOut},
    429: {"model": schemas.ErrorOut},
}


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, Forbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail(exc.code, str(exc)))
    if isinstance(exc, system_health.UnknownApi):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail("not_found", "no such court API"))
    if isinstance(exc, napix_api_check.TestRefused):
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        body = detail(exc.code, str(exc), retry_after=exc.retry_after)
        return HTTPException(exc.http_status, body, headers=headers)
    raise exc


HANDLED = (Forbidden, system_health.UnknownApi, napix_api_check.TestRefused)


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
    api: str, request: Request, session: Session = Depends(get_session), user: User = Depends(holder)
) -> schemas.ApiTestOut:
    """ONE court call to this API with an input ASLMS holds (no body: the server picks it), on a fresh client with no
    retry, logged and audited. Refused with no call and nothing written: 404 `not_found`; 409 `napix_off`,
    `no_sample`, `test_running`; 429 `test_too_soon`, `test_limit`, `napix_budget`. The court's own failure is a 200
    with `ok: false`."""
    settings = request.app.state.settings
    actor = actor_of(request, user, session)
    try:
        napix_api_check.guard(session, settings, user, api)
        client, hc = napix_client(request)
        outcome = asyncio.run(napix_api_check.run(session, actor, user, settings, client, hc, api))
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.ApiTestOut(**outcome.to_dict())


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
