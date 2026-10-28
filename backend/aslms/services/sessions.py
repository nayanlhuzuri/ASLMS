"""Sign-in sessions (design `session-timeout`): one `user_sessions` row per sign-in with the e-mailed code.

- The row is opened by `services/auth.py::complete_login` (`open_session`) and never by a refresh; it ends a device's
  other open sessions as `replaced` (decision 3).
- Every authenticated request checks its row (`check`, decision 7): 401 `session_limit` at or after `expires_at`,
  401 `session_idle` at or after `last_activity_at + SESSION_IDLE_MINUTES`, a plain refusal otherwise.
- Only `POST /me/activity` moves `last_activity_at` (`touch`, decisions 4 and 14), by a conditional update that cannot
  revive a lapsed session.
- `sweep` (decision 12) writes idle and limit ends once each, at the moment the session lapsed, with one audit row
  per end (`auth.signed_out_idle`, `auth.session_limit`, actor `system:sessions`). It never revokes refresh tokens.
- `end` closes open rows with a reason for logout, `end_sessions` and `revoke_device` (decision 11).
The clock is `otp.utcnow`, the sign-in services' clock, so the tests move one clock for both."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from aslms.core.config import Settings
from aslms.domain.org import SessionEndReason, User, UserDevice, UserSession
from aslms.services import otp
from aslms.services.audit import Actor, write_audit
from aslms.services.otp import OtpError

SWEEP_ACTOR = "sessions"
ACTION_IDLE = "auth.signed_out_idle"
ACTION_LIMIT = "auth.session_limit"


class SessionFailure(OtpError):
    """A refused session (HTTP status and code for the router). Defined here rather than under
    `services/auth.py::AuthFailure` because `services/users.py` ends sessions and `auth` imports `users`."""

    http_status = 401


class SessionIdle(SessionFailure):
    code = "session_idle"


class SessionLimit(SessionFailure):
    code = "session_limit"


class SessionInvalid(SessionFailure):
    """No row, another login's row, or a row ended for a reason other than idle or limit; callers answer their own
    plain refusal (`token is not valid`, `refresh_invalid`)."""

    code = "session_invalid"


IDLE_MESSAGE = "you were signed out after a period without activity; sign in again"
LIMIT_MESSAGE = "your session reached its time limit; sign in again"


def now() -> datetime:
    return otp.utcnow()


def idle_delta(settings: Settings) -> timedelta:
    return timedelta(minutes=settings.session_idle_minutes)


def lapse(row: UserSession, settings: Settings) -> tuple[datetime, SessionEndReason]:
    """When the open session lapses and why: the earlier of the idle end and the hard limit (the limit on a tie)."""
    idle_end = row.last_activity_at + idle_delta(settings)
    if idle_end < row.expires_at:
        return idle_end, SessionEndReason.IDLE
    return row.expires_at, SessionEndReason.LIMIT


def check(row: UserSession | None, user_id: uuid.UUID, at: datetime, settings: Settings) -> None:
    """Decision 7: raises `SessionLimit`, `SessionIdle` or `SessionInvalid`; returns for a live session of `user_id`.
    A computation on the row: nothing is written."""
    if row is None or row.user_id != user_id:
        raise SessionInvalid("token is not valid")
    if row.ended_at is not None:
        reason = SessionEndReason(row.end_reason) if row.end_reason is not None else None
        if reason == SessionEndReason.LIMIT:
            raise SessionLimit(LIMIT_MESSAGE)
        if reason == SessionEndReason.IDLE:
            raise SessionIdle(IDLE_MESSAGE)
        raise SessionInvalid("token is not valid")
    when, reason = lapse(row, settings)
    if at >= when:
        if reason == SessionEndReason.LIMIT:
            raise SessionLimit(LIMIT_MESSAGE)
        raise SessionIdle(IDLE_MESSAGE)


def end(
    session: Session,
    reason: SessionEndReason,
    at: datetime | None = None,
    *,
    user_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    keep: uuid.UUID | None = None,
) -> int:
    """Ends the open rows matching every filter given (at least one) with `reason` at `at`; `keep` is spared. The
    count. Rows already loaded in this session are not refreshed (read them with `populate_existing`)."""
    if user_id is None and device_id is None and session_id is None:
        raise ValueError("sessions.end needs a filter")
    at = at or now()
    conds = [UserSession.ended_at.is_(None)]
    if user_id is not None:
        conds.append(UserSession.user_id == user_id)
    if device_id is not None:
        conds.append(UserSession.device_id == device_id)
    if session_id is not None:
        conds.append(UserSession.id == session_id)
    if keep is not None:
        conds.append(UserSession.id != keep)
    result = session.execute(
        update(UserSession)
        .where(*conds)
        .values(ended_at=at, end_reason=reason)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


def open_session(
    session: Session, user: User, device: UserDevice, at: datetime, settings: Settings
) -> UserSession:
    """Decisions 2 and 3: a device's sessions that already lapsed are swept (their idle or limit end is audited, it
    happened); its other open sessions end as `replaced`; a new row starts now with the hard limit fixed."""
    sweep(session, settings, at, device_id=device.id)
    end(session, SessionEndReason.REPLACED, at, device_id=device.id)
    row = UserSession(
        user_id=user.id,
        device_id=device.id,
        started_at=at,
        expires_at=at + timedelta(hours=settings.session_max_hours),
        last_activity_at=at,
    )
    session.add(row)
    session.flush()
    return row


def touch(
    session: Session, sid: uuid.UUID | None, user_id: uuid.UUID, at: datetime, settings: Settings
) -> UserSession:
    """Decision 14: `last_activity_at = now` only while the session is open, before its limit and not idle; otherwise
    the refusal `check` gives (a session the sweep is ending cannot be revived)."""
    if sid is None:
        raise SessionInvalid("token is not valid")
    result = session.execute(
        update(UserSession)
        .where(
            UserSession.id == sid,
            UserSession.user_id == user_id,
            UserSession.ended_at.is_(None),
            UserSession.expires_at > at,
            UserSession.last_activity_at > at - idle_delta(settings),
        )
        .values(last_activity_at=func.greatest(UserSession.last_activity_at, at))
        .execution_options(synchronize_session=False)
    )
    row = session.get(UserSession, sid, populate_existing=True)
    if not result.rowcount:
        check(row, user_id, at, settings)
        raise SessionInvalid("token is not valid")
    return row


def state(row: UserSession, at: datetime, settings: Settings) -> dict:
    """The ping answer: the limits, the seconds left (never negative) and `SESSION_MAX_HOURS` for the browser's
    hard-limit wording (review finding 3)."""
    idle_end = row.last_activity_at + idle_delta(settings)
    return {
        "idle_seconds": settings.session_idle_minutes * 60,
        "warning_seconds": settings.session_warning_seconds,
        "idle_ends_in": max(0, int((idle_end - at).total_seconds())),
        "session_ends_in": max(0, int((row.expires_at - at).total_seconds())),
        "max_hours": settings.session_max_hours,
    }


def seconds_left(row: UserSession, at: datetime | None = None) -> int:
    """`session_expires_in` of the token answers: seconds to the hard limit (never negative)."""
    return max(0, int((row.expires_at - (at or now())).total_seconds()))


def _filters(user_id: uuid.UUID | None, device_id: uuid.UUID | None) -> list:
    conds = []
    if user_id is not None:
        conds.append(UserSession.user_id == user_id)
    if device_id is not None:
        conds.append(UserSession.device_id == device_id)
    return conds


def _lapsed(at: datetime, settings: Settings) -> tuple:
    """(limit, idle) conditions on open rows: a row lapses for the earlier of its two ends (limit on a tie)."""
    idle_end = UserSession.last_activity_at + idle_delta(settings)
    limit = and_(UserSession.expires_at <= at, UserSession.expires_at <= idle_end)
    idle = and_(idle_end <= at, idle_end < UserSession.expires_at)
    return limit, idle


def lapsed_counts(session: Session, settings: Settings, at: datetime | None = None) -> dict[str, int]:
    """What a sweep would end now, written nowhere (`aslms sessions sweep --dry-run`)."""
    at = at or now()
    limit, idle = _lapsed(at, settings)
    base = select(func.count()).select_from(UserSession).where(UserSession.ended_at.is_(None))
    return {
        "limit": session.scalar(base.where(limit)) or 0,
        "idle": session.scalar(base.where(idle)) or 0,
    }


def sweep(
    session: Session,
    settings: Settings,
    at: datetime | None = None,
    *,
    user_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """Decision 12: two conditional updates (limit ends at `expires_at`, idle ends at `last_activity_at + idle`), each
    returned row audited once with the system actor. The `WHERE ended_at IS NULL` makes two sweeps at once end a
    session exactly once. Optional filters restrict it to one login or one device (used at sign-in)."""
    at = at or now()
    limit, idle = _lapsed(at, settings)
    extra = _filters(user_id, device_id)
    cols = (
        UserSession.id,
        UserSession.user_id,
        UserSession.device_id,
        UserSession.started_at,
        UserSession.last_activity_at,
        UserSession.ended_at,
    )
    limit_rows = session.execute(
        update(UserSession)
        .where(UserSession.ended_at.is_(None), limit, *extra)
        .values(ended_at=UserSession.expires_at, end_reason=SessionEndReason.LIMIT)
        .returning(*cols)
        .execution_options(synchronize_session=False)
    ).all()
    idle_rows = session.execute(
        update(UserSession)
        .where(UserSession.ended_at.is_(None), idle, *extra)
        .values(
            ended_at=UserSession.last_activity_at + idle_delta(settings), end_reason=SessionEndReason.IDLE
        )
        .returning(*cols)
        .execution_options(synchronize_session=False)
    ).all()
    actor = Actor.system(SWEEP_ACTOR)
    for rows, action, extra_after in (
        (limit_rows, ACTION_LIMIT, {"max_hours": settings.session_max_hours}),
        (idle_rows, ACTION_IDLE, {"idle_minutes": settings.session_idle_minutes}),
    ):
        for r in rows:
            write_audit(
                session,
                actor,
                action,
                "user",
                r.user_id,
                after={
                    "session_id": str(r.id),
                    "device_id": str(r.device_id),
                    "started_at": r.started_at.isoformat(),
                    "last_activity_at": r.last_activity_at.isoformat(),
                    "ended_at": r.ended_at.isoformat(),
                    **extra_after,
                },
            )
    return {"limit": len(limit_rows), "idle": len(idle_rows)}


def open_rows(session: Session, user_id: uuid.UUID) -> list[UserSession]:
    """The login's open rows, newest first (tests and the CLI)."""
    return list(
        session.scalars(
            select(UserSession)
            .where(UserSession.user_id == user_id, UserSession.ended_at.is_(None))
            .order_by(UserSession.started_at.desc())
        )
    )


__all__ = [
    "ACTION_IDLE",
    "ACTION_LIMIT",
    "SessionFailure",
    "SessionIdle",
    "SessionInvalid",
    "SessionLimit",
    "check",
    "end",
    "lapse",
    "lapsed_counts",
    "now",
    "open_rows",
    "open_session",
    "seconds_left",
    "state",
    "sweep",
    "touch",
]
