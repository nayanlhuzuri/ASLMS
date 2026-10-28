"""Request dependencies: the database session, the current user (with the first-sign-in gate) and
`current_user_pending` (without it), `require(function)`, `require_any(...)`, the audit actor, the virus scanner
behind uploads (`app.state.scanner` in tests, `clamd` otherwise), the mailer (`app.state.mailer` in tests) and the
NAPIX client of the integration layer (`app.state.napix_factory` in tests, design `audit-screens` decision 13)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from aslms.api.security import issued_before, read_access_claims
from aslms.domain.org import User, UserSession
from aslms.domain.reference import Permission
from aslms.integration.napix.client import NapixClient
from aslms.integration.napix.hc import NapixHighCourt
from aslms.services import access, sessions
from aslms.services.audit import Actor
from aslms.services.court_search import CourtSearchBusy
from aslms.services.mailer import Mailer, MailError, UnconfiguredMailer
from aslms.services.mailer import get_mailer as _configured_mailer
from aslms.services.runner import open_hc
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
    issued before the login's `password_changed_at` (whole seconds) is refused (decision 9). The token's session
    (`sid`) is checked on every request (design `session-timeout`, decision 7): 401 `session_limit` or
    `session_idle` once lapsed, the plain refusal without a session; nothing is written. The session id is put on
    `request.state.auth_session_id`."""
    if creds is None or creds.scheme.lower() != "bearer":
        raise _unauthorized("not signed in")
    settings = request.app.state.settings
    claims = read_access_claims(creds.credentials, settings)
    user = session.get(User, claims[0]) if claims else None
    if user is None or not user.is_active:
        raise _unauthorized("token is not valid")
    if issued_before(claims[1], user.password_changed_at):
        raise _unauthorized("token is not valid")
    sid = claims[2]
    row = session.get(UserSession, sid) if sid is not None else None
    try:
        sessions.check(row, user.id, sessions.now(), settings)
    except (sessions.SessionIdle, sessions.SessionLimit) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"code": exc.code, "message": str(exc)},
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except sessions.SessionInvalid:
        raise _unauthorized("token is not valid") from None
    request.state.user = user
    request.state.auth_session_id = sid
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


def napix_client(request: Request) -> tuple[NapixClient, NapixHighCourt]:
    """The integration-layer client for the court search and the connectivity check: a factory on `app.state`
    (tests) or the configured one (`runner.open_hc`). NAPIX is reached only through `aslms.integration.napix`.
    Routers take it through `napix_request`, never directly."""
    factory = getattr(request.app.state, "napix_factory", None)
    if factory is not None:
        return factory()
    return open_hc(request.app.state.settings)


def apart_factory(request: Request) -> sessionmaker[Session]:
    """The session factory of the apart writes (design followups-oct, decision 2): the app's small apart engine, or
    the main factory when a test passed only that."""
    return getattr(request.app.state, "apart_session_factory", None) or request.app.state.session_factory


def release_connection(session: Session) -> None:
    """Gives the request's connection back before a NAPIX slot is waited for, by committing its read-only
    transaction. A request that has written anything at this point is a defect: `RuntimeError`, never a silent
    commit of a half-done write (decision 3)."""
    if session.new or session.deleted or any(session.is_modified(o) for o in session.dirty):
        raise RuntimeError("napix_request: the request session holds unflushed changes")
    if not session.in_transaction():
        return
    if session.scalar(text("SELECT pg_current_xact_id_if_assigned()")) is not None:
        raise RuntimeError("napix_request: the request transaction has written")
    session.commit()


def busy_http(exc: CourtSearchBusy | None = None) -> HTTPException:
    exc = exc or CourtSearchBusy()
    return HTTPException(
        exc.http_status,
        {"code": exc.code, "message": exc.message, "retry_after": exc.retry_after},
        headers={"Retry-After": str(exc.retry_after)},
    )


@contextmanager
def napix_request(request: Request, session: Session) -> Iterator[tuple[NapixClient, NapixHighCourt]]:
    """The one way a router reaches NAPIX (design followups-oct, decision 3): the request's connection is given back
    first, then one of the process's `NAPIX_REQUEST_SLOTS` is waited for, up to `NAPIX_REQUEST_WAIT_SECONDS`, holding
    no connection; none frees in time: 503 `napix_busy` with `Retry-After: 15`, nothing written. The caller runs its
    guard again inside the block (the quota or the person's count may have changed during the wait). The slot is
    released in the `finally`, after the recorder's last flush inside the block."""
    release_connection(session)
    slots: threading.BoundedSemaphore = request.app.state.napix_slots
    wait = request.app.state.settings.napix_request_wait_seconds
    got = slots.acquire(timeout=wait) if wait > 0 else slots.acquire(blocking=False)
    if not got:
        raise busy_http()
    try:
        yield napix_client(request)
    finally:
        slots.release()
