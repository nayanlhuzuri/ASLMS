"""Request dependencies: the database session, the current user (with the first-sign-in gate) and
`current_user_pending` (without it), `require(function)`, `require_any(...)`, the audit actor, the virus scanner
behind uploads (`app.state.scanner` in tests, `clamd` otherwise) and the mailer (`app.state.mailer` in tests)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from aslms.api.security import issued_before, read_access_claims
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.services import access
from aslms.services.audit import Actor
from aslms.services.mailer import Mailer, MailError, UnconfiguredMailer
from aslms.services.mailer import get_mailer as _configured_mailer
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


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, message, headers={"WWW-Authenticate": "Bearer"})


def current_user_pending(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
) -> User:
    """The signed-in login without the first-sign-in gate: only for the endpoints a login must reach before it
    has changed its password and confirmed its profile (design `otp-and-profile`, decision 11). An access token
    issued before the login's `password_changed_at` (whole seconds) is refused (decision 9)."""
    if creds is None or creds.scheme.lower() != "bearer":
        raise _unauthorized("not signed in")
    claims = read_access_claims(creds.credentials, request.app.state.settings)
    user = session.get(User, claims[0]) if claims else None
    if user is None or not user.is_active:
        raise _unauthorized("token is not valid")
    if issued_before(claims[1], user.password_changed_at):
        raise _unauthorized("token is not valid")
    request.state.user = user
    return user


GATE = {
    "password_change_required": "set your own password first (POST /me/password)",
    "profile_confirmation_required": "confirm your profile first (POST /me/profile/confirm)",
}


def current_user(user: User = Depends(current_user_pending)) -> User:
    """The signed-in login, refused with 403 while it must change its password or confirm its profile."""
    if user.must_change_password:
        code = "password_change_required"
    elif user.must_confirm_profile:
        code = "profile_confirmation_required"
    else:
        return user
    raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": code, "message": GATE[code]})


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
    """The actor snapshot from the login's primary membership (design `user-memberships`, decision 10);
    services re-snapshot with the acting membership before writing."""
    return access.actor_for(
        user,
        None,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


def get_scanner(request: Request) -> Scanner:
    """The upload scanner: a test double set on `app.state.scanner`, else the configured `clamd`."""
    override = getattr(request.app.state, "scanner", None)
    return override if override is not None else _configured_scanner(request.app.state.settings)


def get_mailer(request: Request) -> Mailer:
    """The mailer: a test double set on `app.state.mailer`, else the configured backend (an
    `UnconfiguredMailer` when it cannot be built, so the sign-in path answers 503)."""
    override = getattr(request.app.state, "mailer", None)
    if override is not None:
        return override
    try:
        return _configured_mailer(request.app.state.settings)
    except MailError as exc:
        return UnconfiguredMailer(str(exc))
