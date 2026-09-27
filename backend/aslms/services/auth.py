"""Local accounts with OTP (plan §8.1). Sign-in is two steps:
  1. email + password → a 6-digit OTP is e-mailed (logged to the console in dev) → a challenge id is returned
  2. challenge id + OTP → 15-minute JWT access token + rotating refresh token (stored hashed)
Refresh-token reuse (a revoked token presented again) revokes every token of that user.
Password reset uses the same OTP mechanism with purpose `password_reset`."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from aslms.core.config import get_settings
from aslms.core.errors import SourceUnavailable, TooManyRequestsError, UnauthorizedError, ValidationError
from aslms.core.logging import get_logger
from aslms.core.security import (
    create_access_token,
    generate_otp,
    hash_password,
    new_refresh_token,
    sha256_hex,
    verify_password,
)
from aslms.core.time import now_utc
from aslms.domain.org import Office, OtpCode, OtpPurpose, RefreshToken, User
from aslms.integration.email import get_mailer
from aslms.services import audit
from aslms.services.audit import Actor

log = get_logger(__name__)
GENERIC_FAIL = "invalid email or password"


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


def validate_password(pw: str) -> None:
    if len(pw) < 10 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        raise ValidationError("password must be at least 10 characters and contain letters and digits")


def seconds_until_next_code(session: Session, user_id: uuid.UUID, purpose: OtpPurpose) -> int:
    """How long before another code may be sent for this account and purpose (0 = now)."""
    last = session.scalar(
        select(func.max(OtpCode.created_at)).where(OtpCode.user_id == user_id, OtpCode.purpose == purpose)
    )
    if last is None:
        return 0
    wait = get_settings().otp_resend_seconds - int((now_utc() - last).total_seconds())
    return max(0, wait)


def _check_send_limits(session: Session, user: User, purpose: OtpPurpose, *, cooldown: bool) -> None:
    s = get_settings()
    if cooldown:
        wait = seconds_until_next_code(session, user.id, purpose)
        if wait:
            raise TooManyRequestsError(
                f"please wait {wait} seconds before asking for a new code", retry_after=wait
            )
    recent = (
        session.scalar(
            select(func.count())
            .select_from(OtpCode)
            .where(OtpCode.user_id == user.id, OtpCode.created_at > now_utc() - timedelta(hours=1))
        )
        or 0
    )
    if recent >= s.otp_max_per_hour:
        raise TooManyRequestsError("too many codes requested; try again in an hour", retry_after=3600)


def _issue_otp(session: Session, user: User, purpose: OtpPurpose, *, cooldown: bool = False) -> uuid.UUID:
    _check_send_limits(session, user, purpose, cooldown=cooldown)
    # one live code per purpose: older unused codes stop working
    session.execute(
        update(OtpCode)
        .where(OtpCode.user_id == user.id, OtpCode.purpose == purpose, OtpCode.consumed_at.is_(None))
        .values(consumed_at=now_utc())
    )
    code, code_hash, expires = generate_otp()
    otp = OtpCode(user_id=user.id, purpose=purpose, code_hash=code_hash, expires_at=expires)
    session.add(otp)
    session.flush()
    minutes = get_settings().otp_expiry_minutes
    try:
        get_mailer().send(
            to=user.email,
            subject="ASLMS one-time password",
            body=f"Your ASLMS one-time password is {code}. It expires in {minutes} minutes. Do not share it.",
        )
    except Exception as e:  # noqa: BLE001 — any mail backend failure becomes one clear, non-secret message
        log.error("otp e-mail could not be sent", user_id=str(user.id), error=str(e)[:300])
        raise SourceUnavailable(
            "the one-time password could not be e-mailed; try again or contact the administrator"
        ) from e
    return otp.id


def _check_otp(session: Session, challenge_id: uuid.UUID, code: str, purpose: OtpPurpose) -> User:
    otp = session.get(OtpCode, challenge_id)
    if otp is None or otp.purpose != purpose or otp.consumed_at is not None or otp.expires_at < now_utc():
        raise UnauthorizedError("the code has expired; sign in again")
    # The attempt counter must survive the error: the request transaction is rolled back when we raise, so the
    # counter is committed first. Otherwise the attempt limit would never trigger.
    if otp.attempts >= get_settings().otp_max_attempts:
        otp.consumed_at = now_utc()
        session.commit()
        raise UnauthorizedError("too many attempts; sign in again")
    otp.attempts += 1
    if sha256_hex(code.strip()) != otp.code_hash:
        session.commit()
        raise UnauthorizedError("incorrect code")
    otp.consumed_at = now_utc()
    user = session.get(User, otp.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError(GENERIC_FAIL)
    return user


def start_login(session: Session, email: str, password: str, ip: str | None = None) -> uuid.UUID:
    user = session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        log.info("login failed", email=email.strip().lower(), ip=ip)
        raise UnauthorizedError(GENERIC_FAIL)
    return _issue_otp(session, user, OtpPurpose.LOGIN)


def _tokens(session: Session, user: User, device: str | None) -> TokenPair:
    office = session.get(Office, user.office_id)
    raw, hashed, expires = new_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id, token_hash=hashed, expires_at=expires, device_label=(device or "")[:200] or None
        )
    )
    minutes = get_settings().access_token_minutes
    return TokenPair(create_access_token(user.id, user.role.value, office.path), raw, minutes * 60)


def complete_login(
    session: Session,
    challenge_id: uuid.UUID,
    code: str,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> TokenPair:
    user = _check_otp(session, challenge_id, code, OtpPurpose.LOGIN)
    user.last_login_at = now_utc()
    pair = _tokens(session, user, user_agent)
    audit.record(session, Actor.of(user, ip, user_agent), "auth.login", "user", user.id)
    return pair


def refresh(session: Session, raw_token: str, user_agent: str | None = None) -> TokenPair:
    tok = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw_token)))
    if tok is None:
        raise UnauthorizedError("invalid refresh token")
    if tok.revoked_at is not None:
        # reuse of a rotated token: assume theft, end every session of the user
        session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == tok.user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now_utc())
        )
        log.warning("refresh token reuse detected", user_id=str(tok.user_id))
        session.commit()  # the revocation must survive the error response (the request rolls back on raise)
        raise UnauthorizedError("session ended; sign in again")
    if tok.expires_at < now_utc():
        raise UnauthorizedError("session expired; sign in again")
    user = session.get(User, tok.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("account disabled")
    tok.revoked_at = now_utc()
    return _tokens(session, user, user_agent or tok.device_label)


def logout(session: Session, raw_token: str) -> None:
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == sha256_hex(raw_token), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now_utc())
    )


def start_password_reset(session: Session, email: str) -> uuid.UUID | None:
    """Always answers the same way to the caller; returns None when no such account (not revealed) or when the
    account asked too recently (no code is sent, and that is not revealed either: this endpoint needs no
    password, so it must not become a way to flood someone's inbox)."""
    user = session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active:
        return None
    try:
        return _issue_otp(session, user, OtpPurpose.PASSWORD_RESET, cooldown=True)
    except TooManyRequestsError:
        return None


RESEND_WINDOW_MINUTES = 30


def resend_code(session: Session, challenge_id: uuid.UUID) -> uuid.UUID | None:
    """Sends a fresh code for an earlier sign-in or reset challenge (at most every OTP_RESEND_SECONDS, and at
    most OTP_MAX_PER_HOUR codes an hour). The earlier code stops working. Returns the new challenge id, or None
    for an unknown or stale challenge (the caller answers as if a code had been sent)."""
    old = session.get(OtpCode, challenge_id)
    if old is None or old.created_at < now_utc() - timedelta(minutes=RESEND_WINDOW_MINUTES):
        return None
    user = session.get(User, old.user_id)
    if user is None or not user.is_active:
        return None
    return _issue_otp(session, user, old.purpose, cooldown=True)


def complete_password_reset(session: Session, challenge_id: uuid.UUID, code: str, new_password: str) -> None:
    validate_password(new_password)
    user = _check_otp(session, challenge_id, code, OtpPurpose.PASSWORD_RESET)
    user.password_hash = hash_password(new_password)
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now_utc())
    )
    audit.record(session, Actor.of(user), "auth.password_reset", "user", user.id)


def change_password(session: Session, user: User, old: str, new: str) -> None:
    if not verify_password(old, user.password_hash):
        raise UnauthorizedError("current password is incorrect")
    validate_password(new)
    user.password_hash = hash_password(new)
    audit.record(session, Actor.of(user), "auth.password_change", "user", user.id)
