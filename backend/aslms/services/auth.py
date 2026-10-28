"""Sign-in, devices, password reset and change, refresh with reuse detection (design `otp-and-profile`).

- Sign-in is two steps at **every** sign-in (owner's review of 7 Oct 2026): e-mail and password, then the
  6-digit code e-mailed to the login (purpose `login`). No device skips the code.
- Each sign-in names its device: the client keeps a random device token issued after its first successful code
  (stored hashed in `user_devices`); refresh tokens are tied to it. A device the login never verified from gets
  a "new sign-in" notice e-mail (a mail failure is logged, never blocks) and an `auth.new_device` audit row.
- Lock (decision 4): `LOGIN_MAX_FAILURES` failed passwords or codes for one login within `LOGIN_LOCK_MINUTES`
  refuse sign-in steps with 429 `locked`; counted from the login's `auth.login_failed` / `auth.otp_failed`
  audit rows. Unknown e-mails are not counted.
- Failures raise an `AuthFailure` *after* their counter, spent code, audit row or revocation is flushed; the
  router turns it into a response so the request transaction commits it (decision 5).
- Password reset (decision 7) answers the same for every e-mail; a code sent only for an active, unlocked login
  outside the resend wait. A reset or a change revokes every refresh token (decision 9).
- A rotated refresh token presented again revokes every refresh token of the login (decision 10).
- Sessions (design `session-timeout`): the code step opens a `user_sessions` row; a refresh keeps it, never
  extends it and is refused once it is idle or over its limit; an own password change keeps the caller's session.
- Every step that reads or writes the lock counter or a code first locks the login's `users` row
  (`otp.lock_user`), so parallel requests for one login run one after another: the 5 tries per code and the lock
  of decision 4 hold under concurrency.
Nothing here logs or audits a code, a password or a token."""

from __future__ import annotations

import ipaddress
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from uuid6 import uuid7

from aslms.api.security import issue_access_token, issue_refresh_token, token_hash
from aslms.core.config import Settings
from aslms.domain.events import AuditLog
from aslms.domain.org import (
    OtpCode,
    OtpPurpose,
    RefreshToken,
    SessionEndReason,
    User,
    UserDevice,
    UserSession,
)
from aslms.services import access, otp, sessions
from aslms.services.audit import Actor, write_audit
from aslms.services.mailer import Mailer, MailError, mask_address
from aslms.services.otp import OtpError, OtpMailFailed, TooManyCodes
from aslms.services.passwords import DUMMY_HASH, WeakPassword, check_policy, verify_password
from aslms.services.sessions import SessionIdle, SessionInvalid, SessionLimit
from aslms.services.users import end_sessions, set_password

log = logging.getLogger(__name__)

FAILURE_ACTIONS = ("auth.login_failed", "auth.otp_failed")
SIGN_IN_PURPOSES = (OtpPurpose.LOGIN, OtpPurpose.NEW_DEVICE)


# ------------------------------------------------------------------------------------------------ results


class AuthFailure(OtpError):
    """A refused sign-in step (HTTP status and code for the router)."""


class InvalidCredentials(AuthFailure):
    http_status = 401
    code = "invalid_credentials"


class Locked(AuthFailure):
    http_status = 429
    code = "locked"


class OtpInvalid(AuthFailure):
    http_status = 401
    code = "otp_invalid"


class OtpExpired(AuthFailure):
    http_status = 401
    code = "otp_expired"


class RefreshInvalid(AuthFailure):
    http_status = 401
    code = "refresh_invalid"


class SessionEnded(AuthFailure):
    http_status = 401
    code = "session_ended"


class WrongPassword(AuthFailure):
    http_status = 401
    code = "wrong_password"


class DeviceNotFound(AuthFailure):
    http_status = 404
    code = "not_found"


@dataclass
class Client:
    """Where a request came from: IP, user agent and the device the client names."""

    ip: str | None = None
    user_agent: str | None = None
    device_token: str | None = None
    device_label: str | None = None


@dataclass
class LoginStep:
    challenge_id: uuid.UUID
    purpose: str
    sent_to: str
    expires_in: int
    resend_after: int
    step: str = "otp"


@dataclass
class ResetStep:
    challenge_id: uuid.UUID
    expires_in: int
    resend_after: int


@dataclass
class Signed:
    user: User
    access_token: str
    refresh_token: str
    expires_in: int
    next_step: str
    session_expires_in: int
    device_id: uuid.UUID | None = None
    device_token: str | None = None


def next_step(user: User) -> str:
    """Decision 11: the own password first, then the profile."""
    if user.must_change_password:
        return "change_password"
    if user.must_confirm_profile:
        return "confirm_profile"
    return "ready"


def _actor(user: User, client: Client) -> Actor:
    return access.actor_for(user, ip=client.ip, user_agent=client.user_agent)


def _valid_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    try:
        return str(ipaddress.ip_address(ip))[:64]
    except ValueError:
        return None


def mask_ip(ip: str | None) -> str:
    """`10.2.*.*` / `2001:db8:*`: enough for the owner to recognise, not a full address in a mailbox."""
    valid = _valid_ip(ip)
    if valid is None:
        return "unknown"
    addr = ipaddress.ip_address(valid)
    if addr.version == 4:
        a, b, *_ = valid.split(".")
        return f"{a}.{b}.*.*"
    groups = addr.exploded.split(":")
    return f"{groups[0]}:{groups[1]}:*"


def _find_user(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == (email or "").strip().lower()))


def _challenge(session: Session, challenge_id) -> OtpCode | None:
    try:
        cid = uuid.UUID(str(challenge_id))
    except (TypeError, ValueError):
        return None
    return session.get(OtpCode, cid)


# ------------------------------------------------------------------------------------------------ lock


def is_locked(session: Session, user: User, settings: Settings, now: datetime | None = None) -> int:
    """Seconds the login stays locked (0 = open): `LOGIN_MAX_FAILURES` failures inside the window."""
    now = now or otp.utcnow()
    since = now - timedelta(minutes=settings.login_lock_minutes)
    rows = session.scalars(
        select(AuditLog.created_at)
        .where(
            AuditLog.entity_type == "user",
            AuditLog.entity_id == user.id,
            AuditLog.action.in_(FAILURE_ACTIONS),
            AuditLog.created_at > since,
        )
        .order_by(AuditLog.created_at.desc())
        .limit(settings.login_max_failures)
    ).all()
    if len(rows) < settings.login_max_failures:
        return 0
    oldest = rows[-1]
    return max(
        1, int((oldest + timedelta(minutes=settings.login_lock_minutes) - now).total_seconds() + 0.999)
    )


def _failed(
    session: Session, user: User, client: Client, action: str, after: dict, settings: Settings
) -> None:
    """One failure row; the row that reaches the limit also writes `auth.locked`."""
    actor = _actor(user, client)
    write_audit(session, actor, action, "user", user.id, after=after)
    if is_locked(session, user, settings):
        since = otp.utcnow() - timedelta(minutes=settings.login_lock_minutes)
        already = session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.entity_type == "user",
                AuditLog.entity_id == user.id,
                AuditLog.action == "auth.locked",
                AuditLog.created_at > since,
            )
        )
        if not already:
            write_audit(
                session,
                actor,
                "auth.locked",
                "user",
                user.id,
                after={"minutes": settings.login_lock_minutes, "failures": settings.login_max_failures},
            )


def _refuse_if_locked(session: Session, user: User, settings: Settings) -> None:
    wait = is_locked(session, user, settings)
    if wait:
        raise Locked("too many failed attempts; try again later", retry_after=wait)


# ------------------------------------------------------------------------------------------------ devices


def find_device(session: Session, user: User, raw: str | None) -> UserDevice | None:
    """The login's live device for a device token, else None."""
    if not raw:
        return None
    device = session.scalar(select(UserDevice).where(UserDevice.token_hash == token_hash(raw)))
    if device is None or device.user_id != user.id or device.revoked_at is not None:
        return None
    return device


def _touch_device(
    session: Session, user: User, client: Client, now: datetime
) -> tuple[UserDevice, str | None]:
    """The device after a successful code: refreshed when known, else created with a new token (returned)."""
    ip = _valid_ip(client.ip)
    ua = (client.user_agent or None) and client.user_agent[:400]
    label = (client.device_label or "").strip()[:200] or None
    device = find_device(session, user, client.device_token)
    if device is not None:
        device.last_seen_at = max(now, device.first_seen_at)
        device.verified_at = now
        device.last_ip = ip or device.last_ip
        device.user_agent = ua or device.user_agent
        if label:
            device.label = label
        session.flush()
        return device, None
    raw = secrets.token_urlsafe(32)
    device = UserDevice(
        user_id=user.id,
        token_hash=token_hash(raw),
        label=label,
        user_agent=ua,
        first_ip=ip,
        last_ip=ip,
        first_seen_at=now,
        last_seen_at=now,
        verified_at=now,
    )
    session.add(device)
    session.flush()
    return device, raw


def _new_device_notice(
    mailer: Mailer, user: User, device: UserDevice, client: Client, settings: Settings
) -> None:
    when = otp.utcnow().astimezone(ZoneInfo(settings.timezone)).strftime("%d %b %Y, %H:%M IST")
    browser = device.label or (client.user_agent or "unknown browser")[:120]
    text = (
        f"Dear {user.full_name},\n\n"
        "Your ASLMS login was just used from a device it had not been used from before.\n\n"
        f"    Time: {when}\n    Device: {browser}\n    Network: {mask_ip(client.ip)}\n\n"
        "If this was you, nothing needs to be done. If not, change your password at once, sign the device out "
        "under your profile, and tell your administrator.\n"
    )
    try:
        mailer.send(user.email, "New sign-in to ASLMS", text)
    except MailError as exc:
        log.warning("new-device notice to %s not sent: %s", mask_address(user.email), exc)


def devices(session: Session, user: User, current_token: str | None = None) -> list[dict]:
    """The login's devices, newest first; `current` when the caller named the device."""
    current = find_device(session, user, current_token)
    rows = session.scalars(
        select(UserDevice).where(UserDevice.user_id == user.id).order_by(UserDevice.last_seen_at.desc())
    ).all()
    return [
        {
            "id": d.id,
            "label": d.label,
            "user_agent": d.user_agent,
            "first_seen_at": d.first_seen_at,
            "last_seen_at": d.last_seen_at,
            "verified_at": d.verified_at,
            "revoked_at": d.revoked_at,
            "current": current is not None and d.id == current.id,
        }
        for d in rows
    ]


def _revoke_device_tokens(session: Session, device: UserDevice, now: datetime) -> int:
    result = session.execute(
        update(RefreshToken)
        .where(RefreshToken.device_id == device.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


def revoke_device(session: Session, actor: Actor, user: User, device_id: uuid.UUID) -> UserDevice:
    """Signs one of the caller's own devices out: the device and its refresh tokens (404 for another login's)."""
    device = session.get(UserDevice, device_id)
    if device is None or device.user_id != user.id:
        raise DeviceNotFound("no such device")
    if device.revoked_at is None:
        now = otp.utcnow()
        device.revoked_at = now
        tokens = _revoke_device_tokens(session, device, now)
        sessions.end(session, SessionEndReason.ENDED, now, device_id=device.id)
        session.flush()
        write_audit(
            session,
            actor,
            "auth.device_revoked",
            "user_device",
            device.id,
            after={"user_id": str(user.id), "label": device.label, "tokens_revoked": tokens},
        )
    return device


def sign_out_everywhere(session: Session, actor: Actor, user: User) -> dict:
    """Every refresh token and device of the login (the CLI's `aslms users sign-out`)."""
    now = otp.utcnow()
    tokens = end_sessions(session, user, now)
    result = session.execute(
        update(UserDevice)
        .where(UserDevice.user_id == user.id, UserDevice.revoked_at.is_(None))
        .values(revoked_at=now)
        .execution_options(synchronize_session=False)
    )
    counts = {"tokens_revoked": tokens, "devices_revoked": result.rowcount or 0}
    session.flush()
    write_audit(session, actor, "auth.signed_out", "user", user.id, after=counts)
    return counts


# ------------------------------------------------------------------------------------------------ tokens


def _signed(
    session: Session,
    user: User,
    settings: Settings,
    device: UserDevice | None,
    session_row: UserSession,
    raw_device: str | None = None,
) -> Signed:
    """A fresh pair inside `session_row`: same `sid`, the refresh token expiring with the session."""
    access_token, ttl = issue_access_token(user, settings, session_row)
    refresh = issue_refresh_token(
        session, user, device.label if device else None, device.id if device else None, session_row
    )
    return Signed(
        user=user,
        access_token=access_token,
        refresh_token=refresh,
        expires_in=ttl,
        session_expires_in=sessions.seconds_left(session_row),
        next_step=next_step(user),
        device_id=device.id if device else None,
        device_token=raw_device,
    )


# ------------------------------------------------------------------------------------------------ sign-in


def _otp_sent(session: Session, user: User, client: Client, row: OtpCode) -> None:
    write_audit(
        session,
        _actor(user, client),
        "auth.otp_sent",
        "user",
        user.id,
        after={"purpose": OtpPurpose(row.purpose).value, "sent_to": mask_address(user.email)},
    )


def _login_step(user: User, row: OtpCode, settings: Settings) -> LoginStep:
    return LoginStep(
        challenge_id=row.id,
        purpose=OtpPurpose(row.purpose).value,
        sent_to=mask_address(user.email),
        expires_in=settings.otp_ttl_minutes * 60,
        resend_after=settings.otp_resend_seconds,
    )


def start_login(
    session: Session, email: str, password: str, client: Client, mailer: Mailer, settings: Settings
) -> LoginStep:
    """Step one: the password; a code is mailed (purpose `login`). One 401 for a wrong e-mail, a wrong password
    and a disabled login; the hash is checked for unknown e-mails too (timing)."""
    user = _find_user(session, email)
    if user is None:
        verify_password(DUMMY_HASH, password)
        log.info("sign-in attempt for an unknown e-mail %s", mask_address((email or "").strip().lower()))
        raise InvalidCredentials("e-mail or password is wrong, or the account is disabled")
    otp.lock_user(session, user.id)
    wait = is_locked(session, user, settings)
    if wait:
        verify_password(DUMMY_HASH, password)
        raise Locked("too many failed attempts; try again later", retry_after=wait)
    if not verify_password(user.password_hash, password):
        _failed(session, user, client, "auth.login_failed", {"reason": "password"}, settings)
        raise InvalidCredentials("e-mail or password is wrong, or the account is disabled")
    if not user.is_active:
        _failed(session, user, client, "auth.login_failed", {"reason": "inactive"}, settings)
        raise InvalidCredentials("e-mail or password is wrong, or the account is disabled")
    row = otp.issue(session, user, OtpPurpose.LOGIN, mailer, settings)
    _otp_sent(session, user, client, row)
    return _login_step(user, row, settings)


def complete_login(
    session: Session, challenge_id, code: str, client: Client, mailer: Mailer, settings: Settings
) -> Signed:
    """Step two: the code; the device is created or refreshed, the tokens issued."""
    row = _challenge(session, challenge_id)
    if row is None or OtpPurpose(row.purpose) not in SIGN_IN_PURPOSES:
        raise OtpExpired("the code has expired or was already used; sign in again")
    user = otp.lock_user(session, row.user_id)
    _refuse_if_locked(session, user, settings)
    result = otp.verify(session, row.id, code, SIGN_IN_PURPOSES, settings)
    if not result.ok:
        if result.reason == "invalid":
            _failed(
                session,
                user,
                client,
                "auth.otp_failed",
                {"purpose": OtpPurpose(row.purpose).value, "attempts": row.attempts},
                settings,
            )
            raise OtpInvalid("the code is wrong", attempts_left=result.attempts_left)
        raise OtpExpired("the code has expired or was already used; sign in again")
    if not user.is_active:
        raise InvalidCredentials("e-mail or password is wrong, or the account is disabled")
    now = otp.utcnow()
    device, raw_device = _touch_device(session, user, client, now)
    session_row = sessions.open_session(session, user, device, now, settings)
    user.last_login_at = now
    session.flush()
    actor = _actor(user, client)
    if raw_device is not None:
        write_audit(
            session,
            actor,
            "auth.new_device",
            "user_device",
            device.id,
            after={"user_id": str(user.id), "label": device.label, "ip": mask_ip(client.ip)},
        )
        _new_device_notice(mailer, user, device, client, settings)
    write_audit(
        session,
        actor,
        "auth.login",
        "user",
        user.id,
        after={"device_id": str(device.id), "new_device": bool(raw_device)},
    )
    return _signed(session, user, settings, device, session_row, raw_device)


def _fake_reset(settings: Settings) -> ResetStep:
    return ResetStep(uuid7(), settings.otp_ttl_minutes * 60, settings.otp_resend_seconds)


def _resendable(session: Session, user: User, row: OtpCode, settings: Settings, now: datetime) -> bool:
    """A sign-in challenge stands in for the password only while nothing has ended it: it is live or spent by
    wrong codes (not used, not superseded), still inside its validity, the newest of its purpose, and begun after
    the login's last password or e-mail change (`password_changed_at`, decision 9 and deviation 14)."""
    live_or_spent = row.consumed_at is None or row.attempts >= settings.otp_max_attempts
    if not live_or_spent or row.expires_at <= now:
        return False
    pca = user.password_changed_at
    if pca is not None and row.created_at <= pca:
        return False
    newest = otp.latest(session, user, OtpPurpose(row.purpose))
    return newest is not None and newest.id == row.id


def resend(
    session: Session, challenge_id, client: Client, mailer: Mailer, settings: Settings
) -> LoginStep | ResetStep:
    """A new code for a challenge; the old one ends. Sign-in: 429 inside the wait; 401 `otp_expired` for a
    challenge that `_resendable` refuses. Reset (and any unknown id): the neutral answer of the reset request."""
    row = _challenge(session, challenge_id)
    if row is None:
        otp.ensure_mail_ready(mailer, settings)
        return _fake_reset(settings)
    user = otp.lock_user(session, row.user_id)
    row = otp.lock_code(session, row.id)
    purpose = OtpPurpose(row.purpose)
    if purpose == OtpPurpose.PASSWORD_RESET:
        return _reset_code(session, user, client, mailer, settings)
    if not user.is_active or not _resendable(session, user, row, settings, otp.utcnow()):
        raise OtpExpired("this sign-in has ended; sign in again")
    _refuse_if_locked(session, user, settings)
    new = otp.issue(session, user, purpose, mailer, settings)
    _otp_sent(session, user, client, new)
    return _login_step(user, new, settings)


# ------------------------------------------------------------------------------------------------ password reset


def _reset_code(
    session: Session, user: User, client: Client, mailer: Mailer, settings: Settings
) -> ResetStep:
    otp.ensure_mail_ready(mailer, settings)
    otp.lock_user(session, user.id)
    now = otp.utcnow()
    reason = None
    if not user.is_active:
        reason = "inactive"
    elif is_locked(session, user, settings, now):
        reason = "locked"
    elif otp.send_wait(session, user, OtpPurpose.PASSWORD_RESET, settings, now):
        reason = "wait"
    row = None
    if reason is None:
        try:
            row = otp.issue(session, user, OtpPurpose.PASSWORD_RESET, mailer, settings, now=now)
        except (OtpMailFailed, TooManyCodes) as exc:
            reason = exc.code
    write_audit(
        session,
        _actor(user, client),
        "auth.password_reset_requested",
        "user",
        user.id,
        after={"sent": row is not None, "reason": reason},
    )
    if row is None:
        return _fake_reset(settings)
    _otp_sent(session, user, client, row)
    return ResetStep(row.id, settings.otp_ttl_minutes * 60, settings.otp_resend_seconds)


def request_reset(
    session: Session, email: str, client: Client, mailer: Mailer, settings: Settings
) -> ResetStep:
    """Always one challenge id and the same timings; a code only for an active, unlocked login outside the
    wait (decision 7)."""
    otp.ensure_mail_ready(mailer, settings)
    user = _find_user(session, email)
    if user is None:
        log.info("password reset asked for an unknown e-mail %s", mask_address((email or "").strip().lower()))
        return _fake_reset(settings)
    return _reset_code(session, user, client, mailer, settings)


def confirm_reset(
    session: Session, challenge_id, code: str, new_password: str, client: Client, settings: Settings
) -> User:
    """The code and a new password: sets it (the person's own), clears `must_change_password`, revokes every
    refresh token; does not sign in. Every failed code answers `otp_invalid` alike."""
    check_policy(new_password)
    row = _challenge(session, challenge_id)
    if row is None or OtpPurpose(row.purpose) != OtpPurpose.PASSWORD_RESET:
        raise OtpInvalid("the code is wrong or has expired")
    user = otp.lock_user(session, row.user_id)
    _refuse_if_locked(session, user, settings)
    result = otp.verify(session, row.id, code, (OtpPurpose.PASSWORD_RESET,), settings)
    if not result.ok:
        if result.reason == "invalid":
            _failed(
                session,
                user,
                client,
                "auth.otp_failed",
                {"purpose": OtpPurpose.PASSWORD_RESET.value, "attempts": row.attempts},
                settings,
            )
        raise OtpInvalid("the code is wrong or has expired")
    if not user.is_active:
        raise OtpInvalid("the code is wrong or has expired")
    try:
        check_policy(new_password, user.password_hash)
    except WeakPassword:
        row.consumed_at = None  # the code stays usable with a different password
        session.flush()
        raise
    actor = _actor(user, client)
    set_password(session, actor, user, new_password, by_self=True)
    write_audit(session, actor, "auth.password_reset", "user", user.id, after={"sessions_ended": True})
    return user


# ------------------------------------------------------------------------------------------------ signed in


def change_password(
    session: Session,
    user: User,
    current: str,
    new: str,
    client: Client,
    settings: Settings,
    auth_session_id: uuid.UUID | None = None,
) -> Signed:
    """The person's own change (also the first-sign-in step): a wrong current password counts as a failure;
    every refresh token and every other session ends; the caller's session is kept (design `session-timeout`,
    decision 13) and a fresh pair joins it, on the session's device."""
    session_row = session.get(UserSession, auth_session_id) if auth_session_id is not None else None
    if session_row is None or session_row.user_id != user.id:
        raise SessionInvalid("token is not valid")
    otp.lock_user(session, user.id)
    _refuse_if_locked(session, user, settings)
    if not verify_password(user.password_hash, current):
        _failed(
            session,
            user,
            client,
            "auth.login_failed",
            {"reason": "password", "step": "change_password"},
            settings,
        )
        raise WrongPassword("the current password is wrong")
    check_policy(new, user.password_hash)
    actor = _actor(user, client)
    set_password(session, actor, user, new, by_self=True, keep_session=session_row.id)
    write_audit(session, actor, "auth.password_changed", "user", user.id, after={"sessions_ended": True})
    return _signed(session, user, settings, session.get(UserDevice, session_row.device_id), session_row)


def refresh(session: Session, raw: str, client: Client, settings: Settings) -> Signed:
    """Rotation: the presented token is revoked and a new one issued for the same device. A token that was
    already rotated (revoked after the last password set, its device live, not ended by logout) revokes every
    refresh token of the login and answers `session_ended` (decision 10). Then the session (design
    `session-timeout`, decision 9): 401 `session_limit` / `session_idle` once lapsed, `refresh_invalid` for a token
    without a session or a session ended otherwise. The new pair keeps the session and its `expires_at`; a refresh
    is not activity."""
    row = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash(raw or "")))
    if row is None:
        raise RefreshInvalid("refresh token is not valid")
    user = session.get(User, row.user_id)
    device = session.get(UserDevice, row.device_id) if row.device_id else None
    now = otp.utcnow()
    if row.revoked_at is not None:
        pca = user.password_changed_at if user is not None else None
        logged_out = row.expires_at <= row.revoked_at  # logout ends the token's life when it revokes it
        rotated = (
            not logged_out
            and (pca is None or row.revoked_at > pca)
            and (device is None or device.revoked_at is None)
        )
        if user is not None and user.is_active and rotated:
            n = end_sessions(session, user, now)
            session.flush()
            write_audit(
                session,
                _actor(user, client),
                "auth.refresh_reused",
                "user",
                user.id,
                after={"tokens_revoked": n},
            )
            raise SessionEnded("this session was ended for safety; sign in again")
        raise RefreshInvalid("refresh token is not valid")
    session_row = session.get(UserSession, row.session_id) if row.session_id is not None else None
    try:
        sessions.check(session_row, row.user_id, now, settings)
    except SessionInvalid:
        raise RefreshInvalid("refresh token is not valid") from None
    if row.expires_at < now or user is None or not user.is_active:
        raise RefreshInvalid("refresh token is not valid")
    if device is not None and device.revoked_at is not None:
        raise RefreshInvalid("refresh token is not valid")
    row.revoked_at = now
    if device is not None:
        device.last_seen_at = max(now, device.first_seen_at)
        device.last_ip = _valid_ip(client.ip) or device.last_ip
    session.flush()
    return _signed(session, user, settings, device, session_row)


__all__ = [
    "AuthFailure",
    "Client",
    "DeviceNotFound",
    "InvalidCredentials",
    "Locked",
    "LoginStep",
    "OtpExpired",
    "OtpInvalid",
    "RefreshInvalid",
    "ResetStep",
    "SessionEnded",
    "SessionIdle",
    "SessionLimit",
    "Signed",
    "WrongPassword",
    "change_password",
    "complete_login",
    "confirm_reset",
    "devices",
    "find_device",
    "is_locked",
    "mask_ip",
    "next_step",
    "refresh",
    "request_reset",
    "resend",
    "revoke_device",
    "sign_out_everywhere",
    "start_login",
]
