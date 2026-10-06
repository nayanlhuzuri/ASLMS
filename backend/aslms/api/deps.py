"""Request dependencies: the database session, the current user, `require(function)`, `require_any(...)`,
the audit actor, and the virus scanner behind uploads (`app.state.scanner` in tests, `clamd` otherwise)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from aslms.api.security import read_access_token
from aslms.domain.org import Office, User
from aslms.domain.reference import Permission
from aslms.services import access
from aslms.services.audit import Actor
from aslms.services.scanner import Scanner
from aslms.services.scanner import get_scanner as _configured_scanner

bearer = HTTPBearer(auto_error=False)


def get_session(request: Request) -> Iterator[Session]:
    factory = request.app.state.session_factory
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "not signed in", headers={"WWW-Authenticate": "Bearer"}
        )
    user_id = read_access_token(creds.credentials, request.app.state.settings)
    user = session.get(User, user_id) if user_id else None
    if user is None or not user.is_active:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "token is not valid", headers={"WWW-Authenticate": "Bearer"}
        )
    request.state.user = user
    return user


def require(permission: Permission):
    """A dependency that admits only callers holding the function."""

    def check(user: User = Depends(current_user), session: Session = Depends(get_session)) -> User:
        if not access.has(session, user, permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"{permission.value} is not enabled for you")
        return user

    return check


def require_any(*permissions: Permission):
    """A dependency that admits callers holding at least one of the functions (cases-api decision 16:
    reading cases needs `cases.view_scope` or `cases.view_all`)."""

    def check(user: User = Depends(current_user), session: Session = Depends(get_session)) -> User:
        if not any(access.has(session, user, p) for p in permissions):
            names = " or ".join(p.value for p in permissions)
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"{names} is not enabled for you")
        return user

    return check


def actor_of(request: Request, user: User, session: Session) -> Actor:
    office = session.get(Office, user.office_id)
    return access.actor_for(
        user,
        office,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


def get_scanner(request: Request) -> Scanner:
    """The upload scanner: a test double set on `app.state.scanner`, else the configured `clamd`."""
    override = getattr(request.app.state, "scanner", None)
    return override if override is not None else _configured_scanner(request.app.state.settings)
