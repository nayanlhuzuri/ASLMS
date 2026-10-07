"""Users (logins): creation with a first membership (type and office), passwords (argon2id), authentication.
Rights to do any of this are checked in `services/access.py`; this module only performs and audits. The
membership rows are written by `services/memberships.py` (design `user-memberships`)."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from aslms.domain.events import Event, EventVisibility
from aslms.domain.org import Designation, Office, OtpCode, RefreshToken, User
from aslms.domain.reference import EventType, Role
from aslms.services.audit import Actor, write_audit
from aslms.services.passwords import (
    DUMMY_HASH,
    MIN_PASSWORD,
    UserError,
    WeakPassword,
    check_policy,
    hash_password,
    verify_password,
)

__all__ = [
    "MIN_PASSWORD",
    "UserError",
    "WeakPassword",
    "authenticate",
    "check_policy",
    "create_user",
    "end_codes",
    "end_sessions",
    "hash_password",
    "set_password",
    "update_profile",
    "user_summary",
    "verify_password",
]

log = logging.getLogger(__name__)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailTaken(UserError):
    """Another login already uses the e-mail (HTTP 409 `email_taken`)."""

    code = "email_taken"


def _now() -> datetime:
    return datetime.now(UTC)


def end_sessions(session: Session, user: User, at: datetime | None = None) -> int:
    """Revokes every live refresh token of the login (design `otp-and-profile`, decision 9); the count."""
    at = at or _now()
    result = session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=at)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


def end_codes(session: Session, user: User, at: datetime | None = None) -> int:
    """Spends every live code of the login, whatever its purpose: a code vouches for the password and the
    mailbox it was sent under, so a change of either ends it (sign-in, new-device and reset codes alike); the
    count."""
    at = at or _now()
    result = session.execute(
        update(OtpCode)
        .where(OtpCode.user_id == user.id, OtpCode.consumed_at.is_(None))
        .values(consumed_at=at)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


def user_summary(user: User) -> dict:
    """The login as audited (the mirror columns name its primary membership)."""
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role.value if isinstance(user.role, Role) else str(user.role),
        "office_id": str(user.office_id),
        "designation": user.designation,
        "is_active": user.is_active,
    }


def create_user(
    session: Session,
    actor: Actor,
    *,
    email: str,
    password: str,
    full_name: str,
    role: Role,
    office: Office,
    designation: str | None = None,
    designation_id: uuid.UUID | None = None,
    mobile: str | None = None,
    must_confirm_profile: bool = True,
) -> User:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise UserError("not an e-mail address")
    if session.scalar(select(User.id).where(User.email == email)) is not None:
        raise UserError("a user with this e-mail already exists")
    if designation_id is not None and session.get(Designation, designation_id) is None:
        raise UserError("unknown designation")
    if not office.is_active:
        raise UserError(f"the office {office.code} is inactive")
    user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name.strip()[:200],
        role=role,
        office_id=office.id,
        designation=(designation or None) and designation.strip()[:200],
        designation_id=designation_id,
        mobile=(mobile or None) and mobile.strip()[:20],
        must_confirm_profile=must_confirm_profile,
        must_change_password=True,  # someone other than the person set it (design otp-and-profile, decision 14)
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    session.add(user)
    session.flush()
    from aslms.services import memberships

    memberships.insert_membership(
        session,
        actor,
        user,
        office=office,
        role=role,
        designation=user.designation,
        designation_id=designation_id,
        audit=False,
    )
    write_audit(session, actor, "user.create", "user", user.id, after=user_summary(user))
    session.add(
        Event(
            type=EventType.USER_CREATED,
            payload={"user_id": str(user.id), "email": email, "role": role.value, "office": office.code},
            dedupe_key=f"user_created:{user.id}",
            visibility=EventVisibility.SCOPED,
        )
    )
    session.flush()
    return user


def update_profile(
    session: Session,
    actor: Actor,
    user: User,
    *,
    full_name: str | None = None,
    designation: str | None = None,
    designation_id: uuid.UUID | None = None,
    mobile: str | None = None,
    email: str | None = None,
    mailer=None,
) -> User:
    """Login-level fields. `designation` / `designation_id` change the primary membership's designation (the
    compatibility path of `PATCH /admin/users/{id}`); the mirror follows. `email` (design `otp-and-profile`,
    decision 13) is lower-cased and unique, ends the login's sessions, audits `user.email_changed` and sends a
    notice to the old address through `mailer` (a failure is logged, never blocks the change)."""
    before = user_summary(user)
    old_email = None
    if email is not None:
        new_email = email.strip().lower()
        if not EMAIL_RE.match(new_email):
            raise UserError("not an e-mail address")
        if new_email != user.email:
            taken = session.scalar(select(User.id).where(User.email == new_email, User.id != user.id))
            if taken is not None:
                raise EmailTaken("a user with this e-mail already exists")
            old_email, user.email = user.email, new_email
    if full_name is not None:
        user.full_name = full_name.strip()[:200]
    if designation is not None or designation_id is not None:
        if designation_id is not None and session.get(Designation, designation_id) is None:
            raise UserError("unknown designation")
        from aslms.domain.org import UserMembership

        primary = session.scalar(
            select(UserMembership).where(
                UserMembership.user_id == user.id,
                UserMembership.is_primary.is_(True),
                UserMembership.is_active.is_(True),
            )
        )
        if primary is not None:
            if designation is not None:
                primary.designation = designation.strip()[:200] or None
            if designation_id is not None:
                primary.designation_id = designation_id
            user.designation, user.designation_id = primary.designation, primary.designation_id
    if mobile is not None:
        user.mobile = mobile.strip()[:20] or None
    user.updated_by = actor.user_id
    if old_email is not None:
        now = _now()
        user.password_changed_at = now
        end_sessions(session, user, now)
        end_codes(session, user, now)  # a code mailed to the old address must not reset or sign in
    session.flush()
    write_audit(session, actor, "user.update", "user", user.id, before=before, after=user_summary(user))
    if old_email is not None:
        write_audit(
            session,
            actor,
            "user.email_changed",
            "user",
            user.id,
            before={"email": old_email},
            after={"email": user.email},
        )
        _email_change_notice(mailer, old_email, user)
    return user


def _email_change_notice(mailer, old_email: str, user: User) -> None:
    if mailer is None:
        return
    from aslms.services.mailer import MailError, mask_address

    text = (
        f"Dear {user.full_name},\n\n"
        "The e-mail address of your ASLMS login was changed by an administrator. "
        f"Sign-in codes now go to {mask_address(user.email)}.\n"
        "If you did not expect this change, contact your department administrator at once.\n"
    )
    try:
        mailer.send(old_email, "ASLMS: your sign-in e-mail was changed", text)
    except MailError as exc:
        log.warning("e-mail change notice to %s not sent: %s", mask_address(old_email), exc)


def set_password(session: Session, actor: Actor, user: User, password: str, *, by_self: bool = False) -> None:
    """Sets the password under the policy (design `otp-and-profile`, decisions 8, 9, 14): records
    `password_changed_at` (older access tokens stop), revokes every refresh token, spends every live code, and sets
    `must_change_password` unless the person set it themself. Someone else's set is audited
    `user.set_password`; the person's own change or reset is audited by `services/auth.py`."""
    check_policy(password, user.password_hash)
    now = _now()
    user.password_hash = hash_password(password)
    user.must_change_password = not by_self
    user.password_changed_at = now
    user.updated_by = actor.user_id
    end_sessions(session, user, now)
    end_codes(session, user, now)  # a pending sign-in begun with the old password ends too
    session.flush()
    if not by_self:
        write_audit(session, actor, "user.set_password", "user", user.id, after={"must_change": True})


def authenticate(session: Session, email: str, password: str) -> User | None:
    """The user when the e-mail exists, the password matches and the account is active; else None. The hash
    is verified even for unknown e-mails so the response time does not reveal which e-mails exist."""
    user = session.scalar(select(User).where(User.email == email.strip().lower()))
    ok = verify_password(user.password_hash if user else DUMMY_HASH, password)
    if user is None or not ok or not user.is_active:
        return None
    user.last_login_at = datetime.now(UTC)
    session.flush()
    return user
