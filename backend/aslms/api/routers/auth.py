"""`/auth/*` and `/me`."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, current_user, get_session
from aslms.api.security import (
    consume_refresh_token,
    issue_access_token,
    issue_refresh_token,
    revoke_refresh_token,
)
from aslms.domain.org import Office, User
from aslms.services import access
from aslms.services.audit import write_audit
from aslms.services.users import authenticate

router = APIRouter(tags=["auth"])


def user_out(session: Session, user: User) -> schemas.UserOut:
    office = session.get(Office, user.office_id)
    return schemas.UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        office=schemas.OfficeOut(
            id=office.id, code=office.code, name=office.name, kind=str(office.kind.value), path=office.path
        ),
        designation=user.designation,
        mobile=user.mobile,
        is_active=user.is_active,
        must_confirm_profile=user.must_confirm_profile,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


def _tokens(request: Request, session: Session, user: User, device_label: str | None) -> schemas.TokenOut:
    settings = request.app.state.settings
    access_token, ttl = issue_access_token(user, settings)
    refresh = issue_refresh_token(session, user, device_label, settings)
    return schemas.TokenOut(
        access_token=access_token, refresh_token=refresh, expires_in=ttl, user=user_out(session, user)
    )


@router.post("/auth/login", response_model=schemas.TokenOut)
def login(
    body: schemas.LoginIn, request: Request, session: Session = Depends(get_session)
) -> schemas.TokenOut:
    user = authenticate(session, body.email, body.password)
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "e-mail or password is wrong, or the account is disabled"
        )
    write_audit(session, actor_of(request, user, session), "auth.login", "user", user.id)
    return _tokens(request, session, user, body.device_label)


@router.post("/auth/refresh", response_model=schemas.TokenOut)
def refresh(
    body: schemas.RefreshIn, request: Request, session: Session = Depends(get_session)
) -> schemas.TokenOut:
    user = consume_refresh_token(session, body.refresh_token)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh token is not valid")
    return _tokens(request, session, user, None)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    body: schemas.RefreshIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> None:
    revoke_refresh_token(session, body.refresh_token)
    write_audit(session, actor_of(request, user, session), "auth.logout", "user", user.id)


@router.get("/me", response_model=schemas.MeOut)
def me(session: Session = Depends(get_session), user: User = Depends(current_user)) -> schemas.MeOut:
    return schemas.MeOut(
        user=user_out(session, user), functions=sorted(access.effective_permissions(session, user))
    )
