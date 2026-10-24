"""`/auth/*` and `/me` (design `otp-and-profile`, "API"): sign-in in two steps (password, then the e-mailed
code), code resend, password reset by e-mail, refresh with reuse detection, logout; the caller's own login,
password, profile and devices.

Decision 5: a refused sign-in step is *returned* as a response, never raised, so the request transaction
commits the attempt counter, the spent code, the audit row and any revocation with it. Every error carries
`{code, message}` under `detail`; 429 adds `retry_after` and a `Retry-After` header."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from aslms.api import schemas
from aslms.api.deps import actor_of, current_user, current_user_pending, get_mailer, get_session
from aslms.api.security import revoke_refresh_token
from aslms.domain.org import Office, User
from aslms.services import access, auth, memberships, profile
from aslms.services.assistant import portal_mode
from aslms.services.audit import write_audit
from aslms.services.mailer import Mailer
from aslms.services.otp import OtpError
from aslms.services.passwords import WeakPassword

router = APIRouter(tags=["auth"])


def membership_list(session: Session, user: User, *, functions: bool = False) -> list[schemas.MembershipOut]:
    """The login's active memberships, the primary first (design `user-memberships`)."""
    return [
        schemas.MembershipOut(**memberships.membership_out(session, m, functions=functions))
        for m in access.active_memberships(session, user)
    ]


def user_out(session: Session, user: User, *, functions: bool = False) -> schemas.UserOut:
    """The login with its memberships. `role`, `office` and `designation` are the primary membership's (the
    mirror, kept at the last values when the login has no membership): display only."""
    office = session.get(Office, user.office_id)  # display
    return schemas.UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,  # display
        office=schemas.OfficeOut.from_office(office),
        designation=user.designation,
        mobile=user.mobile,
        is_active=user.is_active,
        must_confirm_profile=user.must_confirm_profile,
        must_change_password=user.must_change_password,
        profile_confirmed_at=user.profile_confirmed_at,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        memberships=membership_list(session, user, functions=functions),
    )


def error_response(status_code: int, code: str, message: str, **extra) -> JSONResponse:
    headers = {}
    if extra.get("retry_after") is not None:
        headers["Retry-After"] = str(extra["retry_after"])
    if status_code == status.HTTP_401_UNAUTHORIZED:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(
        status_code=status_code,
        content={"detail": {"code": code, "message": message, **extra}},
        headers=headers,
    )


def _refused(exc: Exception) -> JSONResponse:
    if isinstance(exc, WeakPassword):
        return error_response(status.HTTP_422_UNPROCESSABLE_ENTITY, "weak_password", str(exc))
    if isinstance(exc, profile.ProfileError):
        return error_response(exc.http_status, exc.code, str(exc))
    if isinstance(exc, OtpError):
        return error_response(exc.http_status, exc.code, str(exc), **exc.extra)
    raise exc


REFUSED = (OtpError, WeakPassword, profile.ProfileError)


def _client(
    request: Request, device_token: str | None = None, device_label: str | None = None
) -> auth.Client:
    return auth.Client(
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        device_token=device_token,
        device_label=device_label,
    )


def _token_out(session: Session, signed: auth.Signed) -> schemas.TokenOut:
    return schemas.TokenOut(
        access_token=signed.access_token,
        refresh_token=signed.refresh_token,
        expires_in=signed.expires_in,
        user=user_out(session, signed.user),
        next_step=signed.next_step,
        device_token=signed.device_token,
    )


def _step_out(step: auth.LoginStep | auth.ResetStep):
    if isinstance(step, auth.LoginStep):
        return schemas.LoginStepOut(
            challenge_id=step.challenge_id,
            purpose=step.purpose,
            sent_to=step.sent_to,
            expires_in=step.expires_in,
            resend_after=step.resend_after,
        )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=schemas.ResetStepOut(
            challenge_id=step.challenge_id, expires_in=step.expires_in, resend_after=step.resend_after
        ).model_dump(mode="json"),
    )


# ------------------------------------------------------------------------------------------------ sign-in


@router.post("/auth/login", response_model=schemas.LoginStepOut)
def login(
    body: schemas.LoginIn,
    request: Request,
    session: Session = Depends(get_session),
    mailer: Mailer = Depends(get_mailer),
):
    """Step one: e-mail and password; a 6-digit code is e-mailed (every sign-in). 401 `invalid_credentials`
    (one answer for a wrong e-mail, a wrong password and a disabled login), 429 `locked` / `too_many_codes`,
    502 `mail_failed`, 503 `mail_not_configured`."""
    try:
        step = auth.start_login(
            session,
            body.email,
            body.password,
            _client(request, body.device_token, body.device_label),
            mailer,
            request.app.state.settings,
        )
    except REFUSED as exc:
        return _refused(exc)
    return _step_out(step)


@router.post("/auth/otp/verify", response_model=schemas.TokenOut)
def verify_code(
    body: schemas.OtpVerifyIn,
    request: Request,
    session: Session = Depends(get_session),
    mailer: Mailer = Depends(get_mailer),
):
    """Step two: the code; the tokens, `next_step`, and a `device_token` when the device is new. 401
    `otp_invalid` with `attempts_left`, 401 `otp_expired` (expired or spent), 429 `locked`."""
    try:
        signed = auth.complete_login(
            session,
            body.challenge_id,
            body.code,
            _client(request, body.device_token, body.device_label),
            mailer,
            request.app.state.settings,
        )
    except REFUSED as exc:
        return _refused(exc)
    return _token_out(session, signed)


@router.post("/auth/otp/resend", response_model=schemas.LoginStepOut)
def resend_code(
    body: schemas.OtpResendIn,
    request: Request,
    session: Session = Depends(get_session),
    mailer: Mailer = Depends(get_mailer),
):
    """A new code for a challenge (the old one ends). Sign-in: 429 `too_many_codes` with `retry_after` inside
    the wait. A reset challenge (or an unknown id): the neutral 202 answer of the reset request."""
    try:
        step = auth.resend(session, body.challenge_id, _client(request), mailer, request.app.state.settings)
    except REFUSED as exc:
        return _refused(exc)
    return _step_out(step)


@router.post(
    "/auth/password-reset/request", response_model=schemas.ResetStepOut, status_code=status.HTTP_202_ACCEPTED
)
def password_reset_request(
    body: schemas.ResetRequestIn,
    request: Request,
    session: Session = Depends(get_session),
    mailer: Mailer = Depends(get_mailer),
):
    """Always 202 with a challenge id and the same timings, whether or not the account exists."""
    try:
        step = auth.request_reset(session, body.email, _client(request), mailer, request.app.state.settings)
    except REFUSED as exc:
        return _refused(exc)
    return _step_out(step)


@router.post("/auth/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
def password_reset_confirm(
    body: schemas.ResetConfirmIn, request: Request, session: Session = Depends(get_session)
):
    """The code and a new password; every session ends; the user signs in again. 401 `otp_invalid`, 429
    `locked`, 422 `weak_password`."""
    try:
        auth.confirm_reset(
            session,
            body.challenge_id,
            body.code,
            body.new_password,
            _client(request),
            request.app.state.settings,
        )
    except REFUSED as exc:
        return _refused(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/auth/refresh", response_model=schemas.TokenOut)
def refresh(body: schemas.RefreshIn, request: Request, session: Session = Depends(get_session)):
    """Rotation. 401 `refresh_invalid`; an already-rotated token ends every session of the login (401
    `session_ended`)."""
    try:
        signed = auth.refresh(session, body.refresh_token, _client(request), request.app.state.settings)
    except REFUSED as exc:
        return _refused(exc)
    return _token_out(session, signed)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    body: schemas.RefreshIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user_pending),
) -> None:
    revoke_refresh_token(session, body.refresh_token, user.id)
    write_audit(session, actor_of(request, user, session), "auth.logout", "user", user.id)


# ------------------------------------------------------------------------------------------------ me


@router.get("/me", response_model=schemas.MeOut)
def me(
    request: Request, session: Session = Depends(get_session), user: User = Depends(current_user_pending)
) -> schemas.MeOut:
    """The caller's own login, each active membership with its functions, and the union (the gate). Empty
    `memberships` for a login after its last exit (design `user-memberships`, decision 22). `assistant_mode` says
    whether the portal shows the Case Assistant (design `assistant`, "API")."""
    return schemas.MeOut(
        user=user_out(session, user),
        memberships=membership_list(session, user, functions=True),
        functions=sorted(access.effective_permissions(session, user)),
        assistant_mode=portal_mode(request.app.state.settings),
    )


@router.post("/me/password", response_model=schemas.TokenOut)
def change_password(
    body: schemas.PasswordChangeIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user_pending),
):
    """The caller's own password (also the first-sign-in step): every other session ends and a fresh pair for
    this device is returned. 401 `wrong_password` (counted as a failure), 422 `weak_password`, 429 `locked`."""
    try:
        signed = auth.change_password(
            session,
            user,
            body.current_password,
            body.new_password,
            _client(request, body.device_token),
            request.app.state.settings,
        )
    except REFUSED as exc:
        return _refused(exc)
    return _token_out(session, signed)


@router.get("/me/profile", response_model=schemas.ProfileOut)
def get_profile(session: Session = Depends(get_session), user: User = Depends(current_user_pending)):
    return schemas.ProfileOut(**profile.get_profile(session, user))


@router.post("/me/profile/confirm", response_model=schemas.ProfileOut)
def confirm_profile(
    body: schemas.ProfileConfirmIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user_pending),
):
    """409 `password_change_required` before the own password, 409 `already_confirmed`, 422 `invalid_mobile`
    (mandatory, an Indian 10-digit number)."""
    prefs = (
        body.notification_preferences.model_dump(exclude_unset=True)
        if body.notification_preferences
        else None
    )
    try:
        out = profile.confirm(
            session,
            actor_of(request, user, session),
            user,
            full_name=body.full_name,
            mobile=body.mobile,
            preferences=prefs,
        )
    except REFUSED as exc:
        return _refused(exc)
    return schemas.ProfileOut(**out)


@router.patch("/me/profile", response_model=schemas.ProfileOut)
def patch_profile(
    body: schemas.ProfilePatchIn,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    fields = body.model_dump(exclude_unset=True)
    try:
        out = profile.update(
            session,
            actor_of(request, user, session),
            user,
            full_name=fields.get("full_name"),
            mobile=fields.get("mobile"),
        )
    except REFUSED as exc:
        return _refused(exc)
    return schemas.ProfileOut(**out)


@router.get("/me/devices", response_model=list[schemas.DeviceOut])
def my_devices(
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
    x_device_token: str | None = Header(None, max_length=200),
) -> list[schemas.DeviceOut]:
    """The caller's own devices; `current` marks the one named by the `X-Device-Token` header."""
    return [schemas.DeviceOut(**d) for d in auth.devices(session, user, x_device_token)]


@router.post("/me/devices/{device_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_my_device(
    device_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """Signs the device out (the device and its refresh tokens); 404 for another login's device."""
    try:
        auth.revoke_device(session, actor_of(request, user, session), user, device_id)
    except REFUSED as exc:
        return _refused(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
