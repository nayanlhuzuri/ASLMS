"""Design `session-timeout` without a database: the three session settings and their validator (decision 21), the
access token's `sid` and its `exp` capped at the session's end (decision 8), and the lapse rule shared by the
per-request check and the sweep (decisions 7 and 12)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import ValidationError

from aslms.api.security import issue_access_token, read_access_claims
from aslms.core.config import Settings
from aslms.domain.org import SessionEndReason, User, UserSession
from aslms.services import sessions

JWT = "unit-secret-of-at-least-thirty-two-characters"


def settings(**kw) -> Settings:
    return Settings(_env_file=None, aslms_jwt_secret=JWT, **kw)


def test_session_settings_validation():
    s = settings()
    assert (s.session_idle_minutes, s.session_warning_seconds, s.session_max_hours) == (30, 120, 12)
    assert not hasattr(s, "aslms_refresh_token_days")
    settings(session_idle_minutes=2, session_warning_seconds=119, session_max_hours=1)
    settings(session_idle_minutes=240, session_warning_seconds=600, session_max_hours=24)
    for bad in (
        {"session_idle_minutes": 1},
        {"session_idle_minutes": 241},
        {"session_warning_seconds": 29},
        {"session_warning_seconds": 601},
        {"session_max_hours": 0},
        {"session_max_hours": 25},
    ):
        with pytest.raises(ValidationError):
            settings(**bad)
    with pytest.raises(ValidationError, match="SESSION_WARNING_SECONDS must be less than"):
        settings(session_idle_minutes=2, session_warning_seconds=120)  # warning == idle
    with pytest.raises(ValidationError, match="SESSION_WARNING_SECONDS must be less than"):
        settings(session_idle_minutes=5, session_warning_seconds=600)  # warning > idle


def _row(started: datetime, *, hours: int = 12, activity: datetime | None = None) -> UserSession:
    return UserSession(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        device_id=uuid.uuid4(),
        started_at=started,
        expires_at=started + timedelta(hours=hours),
        last_activity_at=activity or started,
    )


def test_access_claims_carry_sid_and_cap_exp():
    s = settings(aslms_access_token_minutes=30)
    now = datetime.now(UTC)
    user = User(id=uuid.uuid4())
    row = _row(now - timedelta(hours=1))
    token, ttl = issue_access_token(user, s, row)
    payload = jwt.decode(token, JWT, algorithms=["HS256"])
    assert payload["sid"] == str(row.id) and ttl == 1800
    assert read_access_claims(token, s) == (user.id, payload["iat"], row.id)
    # ten minutes before the hard limit: the token dies with the session
    near_end = _row(now - timedelta(hours=12) + timedelta(minutes=10))
    token, ttl = issue_access_token(user, s, near_end)
    payload = jwt.decode(token, JWT, algorithms=["HS256"])
    assert 590 <= ttl <= 600
    assert payload["exp"] <= int(near_end.expires_at.timestamp()) + 1
    # a token without `sid` is read with None (and refused by the request check)
    bare = jwt.encode(
        {"sub": str(user.id), "typ": "access", "iat": int(now.timestamp()), "exp": int(now.timestamp()) + 60},
        JWT,
        algorithm="HS256",
    )
    assert read_access_claims(bare, s)[2] is None


def test_lapse_and_check_follow_the_earlier_deadline():
    s = settings()
    start = datetime(2026, 10, 27, 4, 0, tzinfo=UTC)
    row = _row(start)
    assert sessions.lapse(row, s) == (start + timedelta(minutes=30), SessionEndReason.IDLE)
    sessions.check(row, row.user_id, start + timedelta(minutes=29, seconds=59), s)
    with pytest.raises(sessions.SessionIdle):
        sessions.check(row, row.user_id, start + timedelta(minutes=30), s)
    late = _row(start, activity=start + timedelta(hours=11, minutes=45))
    assert sessions.lapse(late, s) == (late.expires_at, SessionEndReason.LIMIT)
    with pytest.raises(sessions.SessionLimit):
        sessions.check(late, late.user_id, late.expires_at, s)
    with pytest.raises(sessions.SessionInvalid):
        sessions.check(row, uuid.uuid4(), start, s)  # another login's session
    with pytest.raises(sessions.SessionInvalid):
        sessions.check(None, row.user_id, start, s)
    for reason, exc in (
        (SessionEndReason.IDLE, sessions.SessionIdle),
        (SessionEndReason.LIMIT, sessions.SessionLimit),
        (SessionEndReason.SIGNED_OUT, sessions.SessionInvalid),
        (SessionEndReason.REPLACED, sessions.SessionInvalid),
        (SessionEndReason.ENDED, sessions.SessionInvalid),
    ):
        ended = _row(start)
        ended.ended_at, ended.end_reason = start + timedelta(minutes=1), reason
        with pytest.raises(exc):
            sessions.check(ended, ended.user_id, start + timedelta(minutes=2), s)


def test_state_reports_the_seconds_left():
    s = settings()
    start = datetime(2026, 10, 27, 4, 0, tzinfo=UTC)
    row = _row(start)
    assert sessions.state(row, start, s) == {
        "idle_seconds": 1800,
        "warning_seconds": 120,
        "idle_ends_in": 1800,
        "session_ends_in": 12 * 3600,
        "max_hours": 12,
    }
    assert sessions.state(row, start + timedelta(hours=13), s)["session_ends_in"] == 0
