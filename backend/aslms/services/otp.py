"""One-time codes e-mailed for sign-in and password reset (design `otp-and-profile`, decisions 2, 3, 15).

- Six digits from `secrets.randbelow`, stored as HMAC-SHA256 keyed with `ASLMS_JWT_SECRET`, compared in
  constant time; valid `OTP_TTL_MINUTES`, at most `OTP_MAX_ATTEMPTS` tries, then spent.
- One live code per login and purpose: issuing a new one consumes the older ones.
- A new code for the same login and purpose at most every `OTP_RESEND_SECONDS`; at most `OTP_MAX_PER_HOUR` codes
  per login across purposes (`TooManyCodes`, 429 with `retry_after`).
- The code is never logged, never put in an audit row, never returned by the API; only the mail body holds it.
- `verify` never raises on a wrong code: the caller commits the attempt counter (decision 5).
- A send failure leaves no live code (the unsent row is removed, the older ones stay consumed): `OtpMailFailed`.
- Concurrency: `issue` locks the login's `users` row (`lock_user`) and `verify` locks the `otp_codes` row
  (`SELECT ... FOR UPDATE`), so parallel requests cannot leave two live codes, overwrite the attempt counter or
  redeem one code twice. Lock order is always the `users` row first, then the code.

`utcnow()` is the one clock of the sign-in services; tests move it."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from aslms.api.security import jwt_secret
from aslms.core.config import Settings
from aslms.domain.org import OtpCode, OtpPurpose, User
from aslms.services.mailer import Mailer, MailError, mask_address

log = logging.getLogger(__name__)

CODE_DIGITS = 6
SUBJECTS = {
    OtpPurpose.LOGIN: "ASLMS sign-in code",
    OtpPurpose.NEW_DEVICE: "ASLMS sign-in code",
    OtpPurpose.PASSWORD_RESET: "ASLMS password reset code",
}
PURPOSE_TEXT = {
    OtpPurpose.LOGIN: "to sign in to ASLMS",
    OtpPurpose.NEW_DEVICE: "to sign in to ASLMS from a new device",
    OtpPurpose.PASSWORD_RESET: "to set a new ASLMS password",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def mask_email(address: str) -> str:
    return mask_address(address)


class OtpError(Exception):
    """A refused code step, mapped to HTTP by the auth router."""

    http_status = 400
    code = "otp_error"

    def __init__(self, message: str, **extra: object) -> None:
        super().__init__(message)
        self.extra = extra


class TooManyCodes(OtpError):
    http_status = 429
    code = "too_many_codes"


class OtpMailFailed(OtpError):
    http_status = 502
    code = "mail_failed"


class MailNotConfigured(OtpError):
    http_status = 503
    code = "mail_not_configured"


@dataclass
class VerifyResult:
    ok: bool
    row: OtpCode | None = None
    user: User | None = None
    attempts_left: int = 0
    reason: str | None = None  # invalid | expired | spent | unknown


def new_code() -> str:
    return f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"


def code_hash(code: str, settings: Settings) -> str:
    return hmac.new(jwt_secret(settings).encode(), code.encode(), hashlib.sha256).hexdigest()


def code_matches(code: str, stored: str, settings: Settings) -> bool:
    return hmac.compare_digest(code_hash(code, settings), stored)


def ensure_mail_ready(mailer: Mailer, settings: Settings) -> None:
    """Decision 15: no sign-in code without a mail service. An unconfigured mailer, or the console backend in
    production, answers 503 `mail_not_configured`."""
    name = getattr(mailer, "name", "")
    if name == "unconfigured" or (name == "console" and settings.is_prod):
        raise MailNotConfigured("mail is not configured on this server; sign-in codes cannot be sent")


def lock_user(session: Session, user_id: uuid.UUID) -> User | None:
    """The login's `users` row, locked for the rest of the transaction (`SELECT ... FOR UPDATE`) and re-read, so
    the sign-in steps of one login run one after another and each sees the failures and codes the previous one
    committed. Pending changes are flushed first, so the re-read never drops them."""
    session.flush()
    return session.get(User, user_id, with_for_update=True, populate_existing=True)


def lock_code(session: Session, code_id: uuid.UUID) -> OtpCode | None:
    """The `otp_codes` row, locked and re-read (lock the login first)."""
    session.flush()
    return session.get(OtpCode, code_id, with_for_update=True, populate_existing=True)


def latest(session: Session, user: User, purpose: OtpPurpose) -> OtpCode | None:
    """The newest code of the login and purpose (live or not)."""
    return session.scalar(
        select(OtpCode)
        .where(OtpCode.user_id == user.id, OtpCode.purpose == purpose)
        .order_by(OtpCode.created_at.desc(), OtpCode.id.desc())
        .limit(1)
    )


def _latest_created(session: Session, user: User, purpose: OtpPurpose) -> datetime | None:
    return session.scalar(
        select(func.max(OtpCode.created_at)).where(OtpCode.user_id == user.id, OtpCode.purpose == purpose)
    )


def seconds_until_resend(
    session: Session, user: User, purpose: OtpPurpose, settings: Settings, now: datetime | None = None
) -> int:
    """Seconds before a new code of this purpose may be sent (0 = now)."""
    now = now or utcnow()
    last = _latest_created(session, user, purpose)
    if last is None:
        return 0
    wait = (last + timedelta(seconds=settings.otp_resend_seconds) - now).total_seconds()
    return max(0, int(wait + 0.999))


def seconds_until_hourly_slot(
    session: Session, user: User, settings: Settings, now: datetime | None = None
) -> int:
    """Seconds before the hourly cap admits another code (0 = now)."""
    now = now or utcnow()
    since = now - timedelta(hours=1)
    rows = session.scalars(
        select(OtpCode.created_at)
        .where(OtpCode.user_id == user.id, OtpCode.created_at > since)
        .order_by(OtpCode.created_at.desc())
    ).all()
    if len(rows) < settings.otp_max_per_hour:
        return 0
    oldest_counted = rows[settings.otp_max_per_hour - 1]
    return max(1, int((oldest_counted + timedelta(hours=1) - now).total_seconds() + 0.999))


def send_wait(session: Session, user: User, purpose: OtpPurpose, settings: Settings, now: datetime) -> int:
    return max(
        seconds_until_resend(session, user, purpose, settings, now),
        seconds_until_hourly_slot(session, user, settings, now),
    )


def issue(
    session: Session,
    user: User,
    purpose: OtpPurpose,
    mailer: Mailer,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> OtpCode:
    """A new code for the login, mailed to its address. Raises `TooManyCodes` inside the resend wait or above the
    hourly cap, `MailNotConfigured`, or `OtpMailFailed` (no live code is left)."""
    now = now or utcnow()
    ensure_mail_ready(mailer, settings)
    lock_user(session, user.id)  # one issue at a time per login: the wait and the one-live-code rule hold
    wait = seconds_until_resend(session, user, purpose, settings, now)
    if wait:
        raise TooManyCodes("a code was sent a moment ago; wait before asking again", retry_after=wait)
    wait = seconds_until_hourly_slot(session, user, settings, now)
    if wait:
        raise TooManyCodes("too many codes were sent in the last hour", retry_after=wait)
    session.execute(
        update(OtpCode)
        .where(OtpCode.user_id == user.id, OtpCode.purpose == purpose, OtpCode.consumed_at.is_(None))
        .values(consumed_at=now)
        .execution_options(synchronize_session=False)
    )
    code = new_code()
    row = OtpCode(
        user_id=user.id,
        purpose=purpose,
        code_hash=code_hash(code, settings),
        expires_at=now + timedelta(minutes=settings.otp_ttl_minutes),
        created_at=now,
    )
    session.add(row)
    session.flush()
    text = (
        f"Dear {user.full_name},\n\n"
        f"Your one-time code {PURPOSE_TEXT[purpose]} is:\n\n    {code}\n\n"
        f"It is valid for {settings.otp_ttl_minutes} minutes and can be used once. "
        "ASLMS staff will never ask you for this code.\n"
        "If you did not ask for it, someone may know your password: change it and tell your administrator.\n"
    )
    try:
        mailer.send(user.email, SUBJECTS[purpose], text)
    except MailError as exc:
        session.delete(row)
        session.flush()
        log.warning("sign-in code to %s not sent: %s", mask_address(user.email), exc)
        raise OtpMailFailed("the code could not be e-mailed; try again in a moment") from exc
    return row


def verify(
    session: Session,
    challenge_id: uuid.UUID | str | None,
    code: str,
    purposes: tuple[OtpPurpose, ...],
    settings: Settings,
    *,
    now: datetime | None = None,
) -> VerifyResult:
    """Checks a code against its challenge. A success consumes the code; a wrong code adds an attempt and the
    last allowed attempt spends it. Never raises on a wrong code."""
    now = now or utcnow()
    try:
        cid = uuid.UUID(str(challenge_id))
    except (TypeError, ValueError):
        return VerifyResult(False, reason="unknown")
    row = session.get(OtpCode, cid)
    if row is None or OtpPurpose(row.purpose) not in purposes:
        return VerifyResult(False, reason="unknown")
    user = lock_user(session, row.user_id)
    row = lock_code(session, cid)  # attempts and consumption are read and written under the row lock
    if row.consumed_at is not None:
        return VerifyResult(False, row, user, reason="spent")
    if row.expires_at <= now:
        return VerifyResult(False, row, user, reason="expired")
    if code_matches(str(code or ""), row.code_hash, settings):
        row.consumed_at = now
        session.flush()
        return VerifyResult(True, row, user, attempts_left=settings.otp_max_attempts - row.attempts)
    row.attempts = (row.attempts or 0) + 1
    if row.attempts >= settings.otp_max_attempts:
        row.consumed_at = now
    session.flush()
    return VerifyResult(
        False, row, user, attempts_left=max(0, settings.otp_max_attempts - row.attempts), reason="invalid"
    )
