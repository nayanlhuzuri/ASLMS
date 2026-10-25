"""`/audit`: the audit log search for auditors (design `audit-screens`, decisions 1-4; plan §5.13). Every endpoint
needs `audit.view` held in a State-wide membership (the super admin, or a membership with `cases.view_all`): a
caller without `audit.view` gets 403, a holder outside a State-wide membership 403 `audit_scope`. Reading writes
nothing. Errors carry `{code, message}`; times are in IST. `/audit/actions` is declared before `/audit/{id}`."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import get_session, require
from aslms.api.errors import detail
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.services import audit_search as svc
from aslms.services.access import Forbidden
from aslms.services.cases import CaseNotFound

router = APIRouter(prefix="/audit", tags=["audit"])
audit_view = require(Permission.AUDIT_VIEW)
ERRORS = {
    400: {"model": schemas.ErrorOut},
    403: {"model": schemas.ErrorOut},
    404: {"model": schemas.ErrorOut},
    503: {"model": schemas.ErrorOut},
}


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, Forbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail(exc.code, str(exc)))
    if isinstance(exc, svc.AuditInputError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail(exc.code, str(exc)))
    if isinstance(exc, CaseNotFound | svc.AuditNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail("not_found", str(exc)))
    if isinstance(exc, svc.SearchTimeout):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail("search_timeout", str(exc)))
    raise exc


HANDLED = (Forbidden, svc.AuditInputError, CaseNotFound, svc.AuditNotFound, svc.SearchTimeout)


def _user_ref(value: str | None) -> tuple[uuid.UUID | None, str | None]:
    """A login id or an e-mail address."""
    if not value:
        return None, None
    try:
        return uuid.UUID(value.strip()), None
    except ValueError:
        return None, value.strip()


@router.get("", response_model=schemas.AuditPageOut, responses=ERRORS)
def search(
    request: Request,
    user_: str | None = Query(None, alias="user", description="the acting login: id or e-mail"),
    actor: str | None = Query(None, min_length=2, max_length=100, description="text in the actor's name"),
    about_user: str | None = Query(None, description="the login a row is about: id or e-mail"),
    case: str | None = Query(None, description="case id, ref_no or CNR (with the cases merged into it)"),
    office: str | None = Query(None, description="actor office code (its subtree)"),
    office_subtree: bool = Query(True, description="false: the office alone, without its sub-offices"),
    action: str | None = Query(None, max_length=80, description="exact code, or a prefix ending in '.'"),
    entity_type: str | None = Query(None, max_length=60),
    entity_id: uuid.UUID | None = None,
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    limit: int = Query(svc.DEFAULT_LIMIT, ge=1, le=svc.MAX_LIMIT),
    cursor: str | None = Query(None, max_length=200),
    session: Session = Depends(get_session),
    user: User = Depends(audit_view),
) -> schemas.AuditPageOut:
    """Newest first; filters AND together; pass `next_cursor` back as `cursor` for the next page (no total)."""
    user_id, user_email = _user_ref(user_)
    about_id, about_email = _user_ref(about_user)
    q = svc.AuditQuery(
        user_id=user_id,
        user_email=user_email,
        actor_text=actor,
        about_user_id=about_id,
        about_user_email=about_email,
        case_ref=case,
        office_code=office,
        office_subtree=office_subtree,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        from_=from_,
        to=to,
        cursor=cursor,
        limit=limit,
    )
    try:
        page = svc.search(session, user, q, settings=request.app.state.settings)
    except HANDLED as exc:
        raise _http(exc) from exc
    return schemas.AuditPageOut(items=page.items, next_cursor=page.next_cursor)


@router.get("/actions", response_model=schemas.AuditActionsOut, responses=ERRORS)
def list_actions(
    request: Request, session: Session = Depends(get_session), user: User = Depends(audit_view)
) -> schemas.AuditActionsOut:
    """The distinct action codes, for the filter list."""
    try:
        return schemas.AuditActionsOut(
            actions=svc.actions(session, user, settings=request.app.state.settings)
        )
    except HANDLED as exc:
        raise _http(exc) from exc


@router.get("/{row_id}", response_model=schemas.AuditRowOut, responses=ERRORS)
def get_row(
    row_id: uuid.UUID, session: Session = Depends(get_session), user: User = Depends(audit_view)
) -> schemas.AuditRowOut:
    """One audit row (deep links)."""
    try:
        return schemas.AuditRowOut(**svc.get(session, user, row_id))
    except HANDLED as exc:
        raise _http(exc) from exc
