"""Sign-in with OTP, token refresh, logout, password reset; the signed-in user's profile and preferences."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.api import schemas as S
from aslms.api.deps import Ctx, client_meta, current_ctx
from aslms.db.session import get_db
from aslms.domain.org import Channel, DigestMode, Office, UserNotificationPreference
from aslms.services import audit, auth
from aslms.services.scope import DEPT_ADMIN_ROLES, INBOX_ROLES

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=S.Challenge)
def login(body: S.LoginIn, request: Request, db: Session = Depends(get_db)) -> S.Challenge:
    ip, _ = client_meta(request)
    return S.Challenge(
        challenge_id=auth.start_login(db, body.email, body.password, ip), resend_after=_resend_after()
    )


@router.post("/auth/verify", response_model=S.Tokens)
def verify(body: S.VerifyIn, request: Request, db: Session = Depends(get_db)) -> S.Tokens:
    ip, ua = client_meta(request)
    pair = auth.complete_login(db, body.challenge_id, body.code, ip=ip, user_agent=ua)
    return S.Tokens(
        access_token=pair.access_token, refresh_token=pair.refresh_token, expires_in=pair.expires_in
    )


@router.post("/auth/refresh", response_model=S.Tokens)
def refresh(body: S.RefreshIn, request: Request, db: Session = Depends(get_db)) -> S.Tokens:
    _, ua = client_meta(request)
    pair = auth.refresh(db, body.refresh_token, ua)
    return S.Tokens(
        access_token=pair.access_token, refresh_token=pair.refresh_token, expires_in=pair.expires_in
    )


@router.post("/auth/logout", response_model=S.Ok)
def logout(body: S.RefreshIn, db: Session = Depends(get_db)) -> S.Ok:
    auth.logout(db, body.refresh_token)
    return S.Ok()


@router.post("/auth/password/forgot", response_model=S.Challenge)
def forgot(body: S.ForgotIn, db: Session = Depends(get_db)) -> S.Challenge:
    cid = auth.start_password_reset(db, body.email)
    # the same answer whether or not the account exists
    return S.Challenge(
        challenge_id=cid or uuid.uuid4(),
        detail="If the account exists, a code has been sent to its e-mail.",
        resend_after=_resend_after(),
    )


@router.post("/auth/otp/resend", response_model=S.Challenge)
def resend(body: S.ResendIn, db: Session = Depends(get_db)) -> S.Challenge:
    """A new code for an earlier sign-in or password-reset step. Allowed once every OTP_RESEND_SECONDS (429 with
    `retry_after` before that). The previous code stops working."""
    cid = auth.resend_code(db, body.challenge_id)
    return S.Challenge(
        challenge_id=cid or uuid.uuid4(),
        detail="A new one-time password has been sent.",
        resend_after=_resend_after(),
    )


def _resend_after() -> int:
    from aslms.core.config import get_settings

    return get_settings().otp_resend_seconds


@router.post("/auth/password/reset", response_model=S.Ok)
def reset(body: S.ResetIn, db: Session = Depends(get_db)) -> S.Ok:
    auth.complete_password_reset(db, body.challenge_id, body.code, body.new_password)
    return S.Ok(detail="Password changed. Sign in again.")


# ------------------------------------------------------------------ me
def _me(ctx: Ctx) -> S.MeOut:
    office = ctx.db.get(Office, ctx.user.office_id)
    dept = ctx.db.get(Office, ctx.principal.department_id) if ctx.principal.department_id else None
    return S.MeOut(
        **S.UserOut.model_validate(ctx.user).model_dump(),
        office=S.OfficeOut.model_validate(office),
        department=S.OfficeOut.model_validate(dept) if dept else None,
        read_only=ctx.principal.read_only,
        can_claim=ctx.principal.role in INBOX_ROLES or ctx.principal.role.value == "central_operator",
        can_admin=ctx.principal.role in DEPT_ADMIN_ROLES,
    )


@router.get("/me", response_model=S.MeOut)
def me(ctx: Ctx = Depends(current_ctx)) -> S.MeOut:
    return _me(ctx)


@router.patch("/me", response_model=S.MeOut)
def update_me(body: S.ProfileIn, ctx: Ctx = Depends(current_ctx)) -> S.MeOut:
    before = {"full_name": ctx.user.full_name, "designation": ctx.user.designation, "mobile": ctx.user.mobile}
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(ctx.user, k, v)
    audit.record(
        ctx.db,
        ctx.actor,
        "user.profile",
        "user",
        ctx.user.id,
        before=before,
        after=body.model_dump(exclude_none=True),
    )
    return _me(ctx)


@router.post("/me/confirm-profile", response_model=S.MeOut)
def confirm_profile(ctx: Ctx = Depends(current_ctx)) -> S.MeOut:
    """First-run: the user confirms office, role and alert preferences."""
    ctx.user.must_confirm_profile = False
    audit.record(ctx.db, ctx.actor, "user.confirm_profile", "user", ctx.user.id)
    return _me(ctx)


@router.post("/me/password", response_model=S.Ok)
def change_password(body: S.ChangePasswordIn, ctx: Ctx = Depends(current_ctx)) -> S.Ok:
    auth.change_password(ctx.db, ctx.user, body.current_password, body.new_password)
    return S.Ok()


@router.get("/me/preferences", response_model=list[S.PreferenceOut])
def preferences(ctx: Ctx = Depends(current_ctx)) -> list[S.PreferenceOut]:
    stored = {
        p.channel: p
        for p in ctx.db.scalars(
            select(UserNotificationPreference).where(UserNotificationPreference.user_id == ctx.user.id)
        )
    }
    out = []
    for ch in Channel:
        p = stored.get(ch)
        out.append(
            S.PreferenceOut(
                channel=ch.value,
                enabled=p.enabled if p else True,
                digest=p.digest.value if p else "none",
                critical_only=p.critical_only if p else False,
            )
        )
    return out


@router.put("/me/preferences", response_model=list[S.PreferenceOut])
def set_preferences(body: list[S.PreferenceIn], ctx: Ctx = Depends(current_ctx)) -> list[S.PreferenceOut]:
    for item in body:
        ch = Channel(item.channel)
        p = ctx.db.scalar(
            select(UserNotificationPreference).where(
                UserNotificationPreference.user_id == ctx.user.id, UserNotificationPreference.channel == ch
            )
        )
        if p is None:
            p = UserNotificationPreference(user_id=ctx.user.id, channel=ch)
            ctx.db.add(p)
        p.enabled, p.digest, p.critical_only = item.enabled, DigestMode(item.digest), item.critical_only
    ctx.db.flush()
    audit.record(
        ctx.db,
        ctx.actor,
        "user.preferences",
        "user",
        ctx.user.id,
        after={"items": [i.model_dump() for i in body]},
    )
    return preferences(ctx)
