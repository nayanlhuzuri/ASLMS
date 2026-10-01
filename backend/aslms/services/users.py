"""Users: creation with a type and an office, passwords (argon2id), authentication. Rights to do any of this
are checked in `services/access.py`; this module only performs and audits."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.domain.events import Event, EventVisibility
from aslms.domain.org import Designation, Office, User
from aslms.domain.reference import EventType, Role
from aslms.services.audit import Actor, write_audit

_hasher = PasswordHasher()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 10


class UserError(ValueError):
    """A request that cannot be honoured (bad input, duplicate email, unknown office)."""


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD:
        raise UserError(f"password must be at least {MIN_PASSWORD} characters")
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:  # noqa: BLE001 — a malformed hash never authenticates
        return False


def user_summary(user: User) -> dict:
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
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    session.add(user)
    session.flush()
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
) -> User:
    before = user_summary(user)
    if full_name is not None:
        user.full_name = full_name.strip()[:200]
    if designation is not None:
        user.designation = designation.strip()[:200] or None
    if designation_id is not None:
        if session.get(Designation, designation_id) is None:
            raise UserError("unknown designation")
        user.designation_id = designation_id
    if mobile is not None:
        user.mobile = mobile.strip()[:20] or None
    user.updated_by = actor.user_id
    session.flush()
    write_audit(session, actor, "user.update", "user", user.id, before=before, after=user_summary(user))
    return user


def set_password(session: Session, actor: Actor, user: User, password: str) -> None:
    user.password_hash = hash_password(password)
    user.updated_by = actor.user_id
    session.flush()
    write_audit(session, actor, "user.set_password", "user", user.id)


def authenticate(session: Session, email: str, password: str) -> User | None:
    """The user when the e-mail exists, the password matches and the account is active; else None. The hash
    is verified even for unknown e-mails so the response time does not reveal which e-mails exist."""
    user = session.scalar(select(User).where(User.email == email.strip().lower()))
    ok = verify_password(user.password_hash if user else _DUMMY_HASH, password)
    if user is None or not ok or not user.is_active:
        return None
    user.last_login_at = datetime.now(UTC)
    session.flush()
    return user


_DUMMY_HASH = _hasher.hash("not-a-real-password-just-timing")
