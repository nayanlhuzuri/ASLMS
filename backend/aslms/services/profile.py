"""The person's own profile (design `otp-and-profile`, decisions 11, 12; the owner's answer of 7 Oct 2026: the
mobile number is mandatory, Indian 10 digits, stored without the country code, not verified until an SMS gateway
exists).

Shown: e-mail (read only — the sign-in and code address), full name and mobile (editable), each active membership
with office, designation and user type (read only — authority belongs to the administrators) and the
notification preferences (edited through `services/notifications.py`). Confirmation sets
`profile_confirmed_at`, clears `must_confirm_profile` and audits `profile.confirmed`; later edits of name and
mobile audit `profile.updated`."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from aslms.domain.org import Office, User
from aslms.domain.reference import Role
from aslms.services import access, notifications
from aslms.services.audit import Actor, write_audit

MOBILE_RE = re.compile(r"^[6-9][0-9]{9}$")
_SEPARATORS = re.compile(r"[\s\-().]")


class ProfileError(ValueError):
    """A refused profile step: `code` and the HTTP status for the router."""

    def __init__(self, code: str, message: str, http_status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


def normalise_mobile(value: str | None) -> str:
    """`+91 98640-12345`, `919864012345`, `09864012345` and `9864012345` all give `9864012345`; anything else
    raises `invalid_mobile`."""
    raw = _SEPARATORS.sub("", value or "")
    if raw.startswith("+91"):
        raw = raw[3:]
    elif len(raw) == 12 and raw.startswith("91"):
        raw = raw[2:]
    elif len(raw) == 11 and raw.startswith("0"):
        raw = raw[1:]
    if not MOBILE_RE.match(raw):
        raise ProfileError("invalid_mobile", "the mobile number must be an Indian 10-digit number")
    return raw


def _name(value: str | None) -> str:
    name = " ".join((value or "").split())
    if len(name) < 2 or len(name) > 200:
        raise ProfileError("invalid_name", "the full name must be 2 to 200 characters")
    return name


def _summary(user: User) -> dict[str, Any]:
    return {
        "full_name": user.full_name,
        "mobile": user.mobile,
        "must_confirm_profile": user.must_confirm_profile,
        "profile_confirmed_at": user.profile_confirmed_at.isoformat() if user.profile_confirmed_at else None,
    }


def get_profile(session: Session, user: User) -> dict[str, Any]:
    items = []
    for m in access.active_memberships(session, user):
        office = session.get(Office, m.office_id)
        items.append(
            {
                "office": {"code": office.code, "name": office.name, "kind": str(office.kind.value)},
                "designation": m.designation,
                "role": Role(m.role).value,
                "is_primary": m.is_primary,
            }
        )
    return {
        "email": user.email,
        "full_name": user.full_name,
        "mobile": user.mobile,
        "memberships": items,
        "must_change_password": user.must_change_password,
        "must_confirm_profile": user.must_confirm_profile,
        "profile_confirmed_at": user.profile_confirmed_at,
        "notification_preferences": notifications.get_preferences(session, user),
    }


def confirm(
    session: Session,
    actor: Actor,
    user: User,
    *,
    full_name: str | None,
    mobile: str | None,
    preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The first-sign-in confirmation: 409 `password_change_required` before the own password, 409
    `already_confirmed` after a confirmation; 422 `invalid_mobile` / `invalid_name` / a preference code."""
    if user.must_change_password:
        raise ProfileError("password_change_required", "set your own password first", 409)
    if not user.must_confirm_profile:
        raise ProfileError("already_confirmed", "the profile is already confirmed", 409)
    name = _name(full_name)
    phone = normalise_mobile(mobile)
    before = _summary(user)
    if preferences:
        try:
            notifications.set_preferences(session, actor, user, preferences)
        except notifications.PreferenceError as exc:
            raise ProfileError(exc.code, str(exc)) from exc
    user.full_name = name
    user.mobile = phone
    user.profile_confirmed_at = datetime.now(UTC)
    user.must_confirm_profile = False
    user.updated_by = actor.user_id
    session.flush()
    write_audit(session, actor, "profile.confirmed", "user", user.id, before=before, after=_summary(user))
    return get_profile(session, user)


def update(
    session: Session,
    actor: Actor,
    user: User,
    *,
    full_name: str | None = None,
    mobile: str | None = None,
) -> dict[str, Any]:
    """Later edits of name and mobile (`None` = unchanged); audited when something changed."""
    name = _name(full_name) if full_name is not None else None  # both checked before either is assigned
    phone = normalise_mobile(mobile) if mobile is not None else None
    before = _summary(user)
    if name is not None:
        user.full_name = name
    if phone is not None:
        user.mobile = phone
    after = _summary(user)
    if after != before:
        user.updated_by = actor.user_id
        session.flush()
        write_audit(session, actor, "profile.updated", "user", user.id, before=before, after=after)
    return get_profile(session, user)
