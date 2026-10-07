"""`/alerts`, `/cases/{ref}/alerts`, `/calendar` and `/me/notification-preferences` (design
`alerts-notifications`, "API"). `{alr}` is an alert id or its `ref_no` in dash form
(`ASLMS-GOA-ALR-2026-000042`); `{ref}` a case as in the cases API. Reading alerts and the calendar needs
`cases.view_scope` or `cases.view_all`; acting on an alert needs `alerts.acknowledge`; preferences and marking
one's own notifications read need only a signed-in user. Every list is filtered by the visibility rule in SQL;
an alert the caller may not see answers 404. Reading writes no audit row; acknowledge, done and a preference
change do. Errors carry `{code, message}`."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, current_user, current_user_pending, get_session, require, require_any
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.services import alerts, calendar, notifications
from aslms.services.access import Forbidden
from aslms.services.alerts import AlertConflict, AlertError, AlertNotFound
from aslms.services.calendar import CalendarError
from aslms.services.cases import CaseNotFound, resolve_case_ref
from aslms.services.notifications import PreferenceError
from aslms.services.visibility import NotVisibleCase

router = APIRouter(tags=["alerts"])

read = require_any(Permission.CASES_VIEW_SCOPE, Permission.CASES_VIEW_ALL)
act = require(Permission.ALERTS_ACKNOWLEDGE)


def _error(code: str, message: str, http_status: int) -> HTTPException:
    return HTTPException(http_status, {"code": code, "message": message})


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, Forbidden):
        return _error("forbidden", str(exc), status.HTTP_403_FORBIDDEN)
    if isinstance(exc, AlertNotFound):
        return _error("not_found", "no such alert", status.HTTP_404_NOT_FOUND)
    if isinstance(exc, NotVisibleCase | CaseNotFound):
        return _error("not_found", "no such case", status.HTTP_404_NOT_FOUND)
    if isinstance(exc, AlertConflict):
        return _error(exc.code, str(exc), status.HTTP_409_CONFLICT)
    if isinstance(exc, PreferenceError):
        return _error(exc.code, str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY)
    if isinstance(exc, CalendarError):
        return _error("bad_range", str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY)
    if isinstance(exc, AlertError | ValueError):
        return _error("bad_request", str(exc), status.HTTP_400_BAD_REQUEST)
    raise exc


HANDLED = (
    Forbidden,
    AlertNotFound,
    NotVisibleCase,
    CaseNotFound,
    AlertConflict,
    PreferenceError,
    CalendarError,
    AlertError,
    ValueError,
)


def _settings(request: Request):
    return request.app.state.settings


def _detail(session: Session, user: User, alert) -> schemas.AlertDetailOut:
    return schemas.AlertDetailOut(**alerts.detail_item(session, user, alert))


# ------------------------------------------------------------------------------------------------ alerts


@router.get("/alerts", response_model=schemas.AlertListOut)
def list_alerts(
    status_: str | None = Query(None, alias="status"),
    kind: str | None = None,
    severity: str | None = None,
    unread: bool | None = None,
    case: str | None = None,
    limit: int = alerts.DEFAULT_LIMIT,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> schemas.AlertListOut:
    """The caller's own in-app notifications (the latest per alert), newest first; `status` defaults to
    open and acknowledged (`all` for every state)."""
    try:
        page = alerts.list_for_user(
            session,
            user,
            status=status_,
            kind=kind,
            severity=severity,
            unread=unread,
            case_ref=case,
            limit=limit,
            offset=offset,
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.AlertListOut(items=page.items, total=page.total)


@router.get("/alerts/counts", response_model=schemas.AlertCountsOut)
def alert_counts(
    session: Session = Depends(get_session), user: User = Depends(read)
) -> schemas.AlertCountsOut:
    return schemas.AlertCountsOut(**alerts.counts_for_user(session, user))


@router.post("/alerts/read", response_model=schemas.AlertsReadOut)
def mark_read(
    body: schemas.AlertsReadIn,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> schemas.AlertsReadOut:
    """Own in-app rows only."""
    marked = alerts.mark_read(session, user, alert_ids=body.alert_ids, all_=body.all)
    return schemas.AlertsReadOut(marked=marked)


@router.get("/alerts/{alr}", response_model=schemas.AlertDetailOut)
def get_alert(
    alr: str, session: Session = Depends(get_session), user: User = Depends(read)
) -> schemas.AlertDetailOut:
    try:
        alert = alerts.get_for_user(session, user, alr)
    except HANDLED as exc:
        raise _http(exc) from exc
    return _detail(session, user, alert)


@router.post("/alerts/{alr}/acknowledge", response_model=schemas.AlertDetailOut)
def acknowledge(
    alr: str,
    body: schemas.AlertNoteIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(act),
) -> schemas.AlertDetailOut:
    try:
        alert = alerts.resolve_alert_ref(session, alr)
        alerts.acknowledge(session, actor_of(request, user, session), user, alert, note=body.note)
    except HANDLED as exc:
        raise _http(exc) from exc
    return _detail(session, user, alert)


@router.post("/alerts/{alr}/done", response_model=schemas.AlertDetailOut)
def done(
    alr: str,
    body: schemas.AlertNoteIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(act),
) -> schemas.AlertDetailOut:
    try:
        alert = alerts.resolve_alert_ref(session, alr)
        alerts.mark_done(session, actor_of(request, user, session), user, alert, note=body.note)
    except HANDLED as exc:
        raise _http(exc) from exc
    return _detail(session, user, alert)


# ------------------------------------------------------------------------------------------------ case tab


@router.get("/cases/{ref}/alerts", response_model=schemas.AlertListOut)
def case_alerts(
    ref: str,
    status_: str | None = Query(None, alias="status"),
    limit: int = alerts.DEFAULT_LIMIT,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> schemas.AlertListOut:
    """The alerts of a visible case for callers who work on it or read State-wide; others get an empty list."""
    try:
        case = resolve_case_ref(session, ref)
        page = alerts.alerts_for_case(session, user, case, status=status_, limit=limit, offset=offset)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.AlertListOut(items=page.items, total=page.total)


# ------------------------------------------------------------------------------------------------ calendar


@router.get("/calendar", response_model=schemas.CalendarOut)
def hearing_calendar(
    request: Request,
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    office: str | None = None,
    session: Session = Depends(get_session),
    user: User = Depends(read),
) -> schemas.CalendarOut:
    """The caller's hearings (working cases) from `from` to `to` (at most 62 days, default today … +7),
    each flagged critical (within 48 hours) or this week; State-wide readers pass `office`."""
    s = _settings(request)
    try:
        items = calendar.calendar_for_user(
            session,
            user,
            from_=from_,
            to=to,
            office=office,
            critical_hours=s.alert_critical_hours,
            sitting_time=s.court_sitting_time,
        )
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.CalendarOut(items=items)


# ------------------------------------------------------------------------------------------------ preferences


@router.get("/me/notification-preferences", response_model=schemas.NotificationPreferencesOut)
def get_preferences(
    session: Session = Depends(get_session), user: User = Depends(current_user_pending)
) -> schemas.NotificationPreferencesOut:
    return schemas.NotificationPreferencesOut(**notifications.get_preferences(session, user))


@router.put("/me/notification-preferences", response_model=schemas.NotificationPreferencesOut)
def set_preferences(
    body: schemas.NotificationPreferencesIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user_pending),  # reachable during the first-sign-in confirmation
) -> schemas.NotificationPreferencesOut:
    changes = body.model_dump(exclude_unset=True)
    try:
        out = notifications.set_preferences(session, actor_of(request, user, session), user, changes)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.NotificationPreferencesOut(**out)
