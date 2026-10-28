"""Design `session-timeout` through the API and the services: one `user_sessions` row per sign-in, the per-request
check (401 `session_idle` / `session_limit`), `POST /me/activity` as the only activity, refreshes that neither extend
nor revive, the end paths with their reasons, the sweep's audit rows, and the race between a ping and the sweep."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.org import RefreshToken, SessionEndReason, User, UserSession
from aslms.services import access, otp, sessions
from aslms.services import auth as auth_service
from aslms.services import users as users_service
from aslms.services.audit import Actor
from aslms.services.mailer import RecordingMailer
from tests.db.auth_support import age_session, sign_in
from tests.db.world import PW, USERS

JWT = "test-secret-of-at-least-thirty-two-characters"
OFF = USERS["edu_off1"][0]
ROOT = USERS["root"][0]


class Clock:
    """Moves the sign-in services' clock (`otp.utcnow`), which the session check, the ping and the sweep share."""

    def __init__(self, monkeypatch) -> None:
        self.offset = timedelta(0)
        monkeypatch.setattr(otp, "utcnow", lambda: datetime.now(UTC) + self.offset)

    def move(self, **kw) -> None:
        self.offset += timedelta(**kw)


def make(world, **overrides) -> TestClient:
    settings = Settings(_env_file=None, aslms_jwt_secret=JWT, aslms_access_token_minutes=5, **overrides)
    app = create_app(settings, world.Session)
    app.state.mailer = RecordingMailer()
    client = TestClient(app)
    client.__enter__()
    client.world = world
    return client


@pytest.fixture()
def api(world):
    client = make(world)
    yield client
    client.__exit__(None, None, None)


def auth(tok: dict) -> dict:
    return {"Authorization": f"Bearer {tok['access_token']}"}


def claims(tok: dict) -> dict:
    return jwt.decode(tok["access_token"], JWT, algorithms=["HS256"])


def rows(api, email: str) -> list[UserSession]:
    with api.world.Session() as s:
        uid = s.scalar(sa.select(User.id).where(User.email == email))
        return list(
            s.scalars(
                sa.select(UserSession).where(UserSession.user_id == uid).order_by(UserSession.started_at)
            )
        )


def row(api, sid) -> UserSession:
    with api.world.Session() as s:
        return s.get(UserSession, sid)


def token_row(api, raw: str) -> RefreshToken:
    with api.world.Session() as s:
        return s.scalar(
            sa.select(RefreshToken).where(RefreshToken.token_hash == auth_service.token_hash(raw))
        )


def audits(api, action: str) -> list:
    with api.world.Session() as s:
        return s.execute(
            sa.text("SELECT entity_type, entity_id, actor_name, after FROM audit_log WHERE action = :a"),
            {"a": action},
        ).all()


def code_of(r) -> str | None:
    d = r.json().get("detail")
    return d.get("code") if isinstance(d, dict) else None


def sweep(api) -> dict:
    with api.world.Session() as s:
        out = sessions.sweep(s, api.app.state.settings)
        s.commit()
        return out


# ------------------------------------------------------------------------------------------------ the session row


def test_sign_in_opens_a_session(api):
    tok = sign_in(api, OFF, PW)
    [r] = rows(api, OFF)
    assert r.ended_at is None and r.end_reason is None
    assert r.expires_at - r.started_at == timedelta(hours=12)
    assert r.last_activity_at == r.started_at
    c = claims(tok)
    assert c["sid"] == str(r.id)
    assert c["exp"] <= int(r.expires_at.timestamp())
    assert token_row(api, tok["refresh_token"]).session_id == r.id
    assert token_row(api, tok["refresh_token"]).expires_at == r.expires_at
    assert 12 * 3600 - 60 <= tok["session_expires_in"] <= 12 * 3600


def test_request_refused_when_idle(api):
    tok = sign_in(api, OFF, PW)
    age_session(api, OFF, 29)
    assert api.get("/me", headers=auth(tok)).status_code == 200
    age_session(api, OFF, 2)
    r = api.get("/me", headers=auth(tok))
    assert r.status_code == 401 and code_of(r) == "session_idle"
    assert r.headers["WWW-Authenticate"] == "Bearer"
    assert rows(api, OFF)[0].ended_at is None  # the refusal writes nothing; the sweep writes the end


def test_request_refused_past_hard_limit(api):
    tok = sign_in(api, OFF, PW)
    age_session(api, OFF, 12 * 60 + 1, field="limit")
    ping = api.post("/me/activity", headers=auth(tok))
    assert ping.status_code == 401 and code_of(ping) == "session_limit"
    r = api.get("/me", headers=auth(tok))
    assert r.status_code == 401 and code_of(r) == "session_limit"


def test_polling_does_not_extend(api, monkeypatch):
    clock = Clock(monkeypatch)
    tok = sign_in(api, ROOT, PW)
    [before] = rows(api, ROOT)
    for _ in range(3):
        clock.move(minutes=9)
        for path in ("/alerts/counts", "/inbox/mine/counts", "/admin/system-health"):
            assert api.get(path, headers=auth(tok)).status_code == 200, path
    assert rows(api, ROOT)[0].last_activity_at == before.last_activity_at
    clock.move(minutes=3)  # 30 minutes after the sign-in, with nothing but polls
    r = api.get("/alerts/counts", headers=auth(tok))
    assert r.status_code == 401 and code_of(r) == "session_idle"


def test_refresh_does_not_extend_and_keeps_the_session(api, monkeypatch):
    clock = Clock(monkeypatch)
    tok = sign_in(api, OFF, PW)
    [before] = rows(api, OFF)
    clock.move(minutes=10)
    r = api.post("/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 200, r.text
    new = r.json()
    assert claims(new)["sid"] == str(before.id)
    assert token_row(api, new["refresh_token"]).session_id == before.id
    assert token_row(api, new["refresh_token"]).expires_at == before.expires_at
    after = row(api, before.id)
    assert after.last_activity_at == before.last_activity_at and after.expires_at == before.expires_at
    assert new["session_expires_in"] <= tok["session_expires_in"]


def test_activity_extends(api, monkeypatch):
    clock = Clock(monkeypatch)
    tok = sign_in(api, OFF, PW)
    [before] = rows(api, OFF)
    clock.move(minutes=20)
    r = api.post("/me/activity", headers=auth(tok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["idle_seconds"] == 1800 and body["warning_seconds"] == 120 and body["max_hours"] == 12
    assert body["idle_ends_in"] == 1800
    assert 12 * 3600 - 20 * 60 - 60 <= body["session_ends_in"] <= 12 * 3600 - 20 * 60
    moved = row(api, before.id).last_activity_at
    assert moved - before.last_activity_at >= timedelta(minutes=20)
    clock.move(minutes=25)  # 45 minutes after the sign-in, 25 after the ping
    assert api.get("/me", headers=auth(tok)).status_code == 200
    assert api.post("/me/activity").status_code == 401  # no token, no ping


def test_activity_works_before_the_first_sign_in_steps(api):
    with api.world.Session() as s:
        s.execute(sa.text("UPDATE users SET must_change_password = true WHERE email = :e"), {"e": OFF})
        s.commit()
    tok = sign_in(api, OFF, PW)
    assert tok["next_step"] == "change_password"
    assert api.post("/me/activity", headers=auth(tok)).status_code == 200


@pytest.mark.parametrize(
    ("field", "minutes", "code"), [("activity", 31, "session_idle"), ("limit", 721, "session_limit")]
)
def test_activity_cannot_revive_an_idle_or_expired_session(api, field, minutes, code):
    tok = sign_in(api, OFF, PW)
    age_session(api, OFF, minutes, field=field)
    [before] = rows(api, OFF)
    r = api.post("/me/activity", headers=auth(tok))
    assert r.status_code == 401 and code_of(r) == code
    after = row(api, before.id)
    assert (after.last_activity_at, after.ended_at) == (before.last_activity_at, None)


@pytest.mark.parametrize(
    ("field", "minutes", "code"), [("activity", 31, "session_idle"), ("limit", 721, "session_limit")]
)
def test_refresh_refused_when_idle_or_past_limit(api, field, minutes, code):
    tok = sign_in(api, OFF, PW)
    age_session(api, OFF, minutes, field=field)
    with api.world.Session() as s:
        count = s.scalar(sa.select(sa.func.count()).select_from(RefreshToken))
    r = api.post("/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 401 and code_of(r) == code
    with api.world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(RefreshToken)) == count  # no new token
    assert token_row(api, tok["refresh_token"]).revoked_at is None


def test_token_without_session_refused(api):
    tok = sign_in(api, OFF, PW)
    with api.world.Session() as s:
        s.execute(
            sa.text("UPDATE refresh_tokens SET session_id = NULL WHERE token_hash = :h"),
            {"h": auth_service.token_hash(tok["refresh_token"])},
        )
        s.commit()
    r = api.post("/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 401 and code_of(r) == "refresh_invalid"
    c = claims(tok)
    no_sid = jwt.encode({k: v for k, v in c.items() if k != "sid"}, JWT, algorithm="HS256")
    r = api.get("/me", headers={"Authorization": f"Bearer {no_sid}"})
    assert r.status_code == 401 and r.json()["detail"] == "token is not valid"
    other = jwt.encode({**c, "sid": "0192b3c4-0000-7000-8000-000000000000"}, JWT, algorithm="HS256")
    assert api.get("/me", headers={"Authorization": f"Bearer {other}"}).status_code == 401


def test_reuse_detection_unaffected(api):
    a = sign_in(api, OFF, PW)
    b = sign_in(api, OFF, PW)  # another device
    assert api.post("/auth/refresh", json={"refresh_token": a["refresh_token"]}).status_code == 200
    r = api.post("/auth/refresh", json={"refresh_token": a["refresh_token"]})
    assert r.status_code == 401 and code_of(r) == "session_ended"
    assert {(x.end_reason, x.ended_at is not None) for x in rows(api, OFF)} == {
        (SessionEndReason.ENDED, True)
    }
    assert len(audits(api, "auth.refresh_reused")) == 1
    assert api.get("/me", headers=auth(b)).status_code == 401


def test_logout_ends_the_session_signed_out(api):
    tok = sign_in(api, OFF, PW)
    r = api.post("/auth/logout", json={"refresh_token": tok["refresh_token"]}, headers=auth(tok))
    assert r.status_code == 204
    [x] = rows(api, OFF)
    assert x.end_reason == SessionEndReason.SIGNED_OUT and x.ended_at is not None
    assert api.get("/me", headers=auth(tok)).status_code == 401
    assert sweep(api) == {"limit": 0, "idle": 0}


def test_change_password_keeps_the_caller_session_and_ends_others(api):
    mine = sign_in(api, OFF, PW)
    other = sign_in(api, OFF, PW)  # another device
    first, second = rows(api, OFF)
    r = api.post(
        "/me/password",
        json={"current_password": PW, "new_password": "another-good-password-9"},
        headers=auth(mine),
    )
    assert r.status_code == 200, r.text
    fresh = r.json()
    assert claims(fresh)["sid"] == str(first.id)
    kept = row(api, first.id)
    assert (kept.started_at, kept.expires_at, kept.ended_at) == (first.started_at, first.expires_at, None)
    assert token_row(api, fresh["refresh_token"]).session_id == first.id
    assert row(api, second.id).end_reason == SessionEndReason.ENDED
    assert api.get("/me", headers=auth(fresh)).status_code == 200
    assert api.get("/me", headers=auth(other)).status_code == 401


def test_new_sign_in_on_the_same_device_replaces_the_open_session(api, monkeypatch):
    clock = Clock(monkeypatch)
    first = sign_in(api, OFF, PW)
    again = sign_in(api, OFF, PW, device_token=first["device_token"])
    old, new = rows(api, OFF)
    assert old.end_reason == SessionEndReason.REPLACED and new.ended_at is None
    assert claims(again)["sid"] == str(new.id)
    assert len(audits(api, "auth.login")) == 2
    clock.move(minutes=45)
    assert sweep(api) == {"limit": 0, "idle": 1}  # only the new one lapses
    assert [a.after["session_id"] for a in audits(api, "auth.signed_out_idle")] == [str(new.id)]


def test_a_lapsed_session_on_the_device_is_swept_as_idle_at_the_next_sign_in(api):
    first = sign_in(api, OFF, PW)
    age_session(api, OFF, 31)
    sign_in(api, OFF, PW, device_token=first["device_token"])
    old, new = rows(api, OFF)
    assert old.end_reason == SessionEndReason.IDLE and new.ended_at is None
    assert len(audits(api, "auth.signed_out_idle")) == 1


def _revoke_device(api, s, tok):
    dev = api.get("/me/devices", headers=auth(tok)).json()[0]["id"]
    helper = sign_in(api, OFF, PW)
    assert api.post(f"/me/devices/{dev}/revoke", headers=auth(helper)).status_code == 204
    return 1  # the helper's own session stays open


def _disable(api, s, tok):
    actor, admin = api.world.actor(s, "edu_admin")
    access.set_enabled(s, actor, admin, api.world.user(s, "edu_off1"), False)
    return 0


def _email(api, s, tok):
    actor, _ = api.world.actor(s, "edu_admin")
    users_service.update_profile(s, actor, api.world.user(s, "edu_off1"), email="new.off1@example.org")
    return 0


def _admin_set(api, s, tok):
    actor, _ = api.world.actor(s, "edu_admin")
    users_service.set_password(s, actor, api.world.user(s, "edu_off1"), "an-admin-chosen-pass-4")
    return 0


def _reset(api, s, tok):
    user = api.world.user(s, "edu_off1")
    users_service.set_password(s, Actor(user.id, user.full_name), user, "a-reset-password-55", by_self=True)
    return 0


def _everywhere(api, s, tok):
    auth_service.sign_out_everywhere(s, Actor.system("cli"), api.world.user(s, "edu_off1"))
    return 0


@pytest.mark.parametrize(
    "path", [_revoke_device, _disable, _email, _admin_set, _reset, _everywhere], ids=lambda f: f.__name__
)
def test_session_ends_with_device_revoke_disable_email_change_reset_and_sign_out_everywhere(api, path):
    tok = sign_in(api, OFF, PW)
    [x] = rows(api, OFF)
    with api.world.Session() as s:
        still_open = path(api, s, tok)
        s.commit()
    assert row(api, x.id).end_reason == SessionEndReason.ENDED
    with api.world.Session() as s:
        assert len(sessions.open_rows(s, x.user_id)) == still_open
    assert api.get("/me", headers=auth(tok)).status_code == 401


# ------------------------------------------------------------------------------------------------ the sweep


def test_sweep_ends_idle_and_limit_once(api, world):
    idle_tok = sign_in(api, OFF, PW)
    age_session(api, OFF, 40)
    sign_in(api, ROOT, PW)
    age_session(api, ROOT, 12 * 60 + 5, field="limit")
    active = sign_in(api, USERS["edu_admin"][0], PW)
    [idle_row] = rows(api, OFF)
    [limit_row] = rows(api, ROOT)
    assert sweep(api) == {"limit": 1, "idle": 1}
    ended_idle = row(api, idle_row.id)
    assert ended_idle.end_reason == SessionEndReason.IDLE
    assert ended_idle.ended_at == idle_row.last_activity_at + timedelta(minutes=30)
    ended_limit = row(api, limit_row.id)
    assert ended_limit.end_reason == SessionEndReason.LIMIT and ended_limit.ended_at == limit_row.expires_at
    [i] = audits(api, "auth.signed_out_idle")
    [lim] = audits(api, "auth.session_limit")
    assert i.entity_type == "user" and i.entity_id == idle_row.user_id and i.actor_name == "sessions"
    assert set(i.after) == {
        "session_id",
        "device_id",
        "started_at",
        "last_activity_at",
        "ended_at",
        "idle_minutes",
    }
    assert i.after["session_id"] == str(idle_row.id) and i.after["idle_minutes"] == 30
    assert lim.entity_id == limit_row.user_id and lim.after["max_hours"] == 12
    assert set(lim.after) - {"max_hours"} == {
        "session_id",
        "device_id",
        "started_at",
        "last_activity_at",
        "ended_at",
    }
    assert sweep(api) == {"limit": 0, "idle": 0}  # a second sweep writes nothing
    assert len(audits(api, "auth.signed_out_idle")) == 1 and len(audits(api, "auth.session_limit")) == 1
    assert api.get("/me", headers=auth(active)).status_code == 200  # an active session is untouched
    r = api.get("/me", headers=auth(idle_tok))
    assert r.status_code == 401 and code_of(r) == "session_idle"  # the ended row keeps its reason


def test_sweep_dry_run_counts_and_writes_nothing(api):
    sign_in(api, OFF, PW)
    age_session(api, OFF, 31)
    with api.world.Session() as s:
        assert sessions.lapsed_counts(s, api.app.state.settings) == {"limit": 0, "idle": 1}
    assert rows(api, OFF)[0].ended_at is None


def test_swept_session_token_gives_session_idle_not_reuse(api):
    stale = sign_in(api, OFF, PW)
    elsewhere = sign_in(api, OFF, PW)  # another device, kept active below
    first, second = rows(api, OFF)
    with api.world.Session() as s:
        s.execute(
            sa.text(
                "UPDATE user_sessions SET started_at = started_at - interval '40 minutes', "
                "last_activity_at = last_activity_at - interval '40 minutes' WHERE id = :i"
            ),
            {"i": first.id},
        )
        s.commit()
    assert sweep(api) == {"limit": 0, "idle": 1}
    assert token_row(api, stale["refresh_token"]).revoked_at is None  # the sweep revokes no token
    r = api.post("/auth/refresh", json={"refresh_token": stale["refresh_token"]})
    assert r.status_code == 401 and code_of(r) == "session_idle"
    assert row(api, second.id).ended_at is None  # no reuse alarm
    assert audits(api, "auth.refresh_reused") == []
    assert api.get("/me", headers=auth(elsewhere)).status_code == 200


def test_ping_and_sweep_race(api):
    tok = sign_in(api, OFF, PW)
    [x] = rows(api, OFF)
    settings = api.app.state.settings
    with api.world.Session() as s:
        s.execute(
            sa.text("UPDATE user_sessions SET ended_at = now(), end_reason = 'idle' WHERE id = :i"),
            {"i": x.id},
        )
        s.commit()
    with api.world.Session() as s:
        with pytest.raises(sessions.SessionIdle):
            sessions.touch(s, x.id, x.user_id, sessions.now(), settings)
    assert row(api, x.id).last_activity_at == x.last_activity_at
    r = api.post("/me/activity", headers=auth(tok))
    assert r.status_code == 401 and code_of(r) == "session_idle"


def test_session_settings_shape_the_ping_and_the_row(world):
    api = make(world, session_idle_minutes=3, session_warning_seconds=60, session_max_hours=1)
    try:
        tok = sign_in(api, OFF, PW)
        [x] = rows(api, OFF)
        assert x.expires_at - x.started_at == timedelta(hours=1)
        assert 3600 - 60 <= tok["session_expires_in"] <= 3600
        body = api.post("/me/activity", headers=auth(tok)).json()
        assert body["idle_seconds"] == 180 and body["warning_seconds"] == 60 and body["max_hours"] == 1
        age_session(api, OFF, 3.1)
        assert code_of(api.get("/me", headers=auth(tok))) == "session_idle"
    finally:
        api.__exit__(None, None, None)


# ------------------------------------------------------------------------------------------------ review finding 1


def _logouts(api, email: str) -> int:
    with api.world.Session() as s:
        return s.scalar(
            sa.text(
                "SELECT count(*) FROM audit_log WHERE action = 'auth.logout' "
                "AND entity_id = (SELECT id FROM users WHERE email = :e)"
            ),
            {"e": email},
        )


@pytest.mark.parametrize(
    ("field", "early", "late", "reason", "action"),
    [
        ("activity", 29.5, 1, SessionEndReason.IDLE, "auth.signed_out_idle"),
        ("limit", 12 * 60 - 0.02, 1, SessionEndReason.LIMIT, "auth.session_limit"),
    ],
)
def test_a_browser_deadline_sign_out_is_never_recorded_as_a_logout(
    api, monkeypatch, field, early, late, reason, action
):
    """Deviation 12: when the browser's watch reaches its deadline the web server only clears the cookies, so the
    session, still live on the server for up to a minute (the trailing ping), runs to its own end and the sweep records
    that end with its audit row; no `signed_out` end and no `auth.logout` row by the person."""
    clock = Clock(monkeypatch)
    tok = sign_in(api, OFF, PW)
    age_session(api, OFF, early, field=field)  # the browser's deadline: nothing reaches the API
    assert api.get("/me", headers=auth(tok)).status_code == 200  # the server still holds it live
    clock.move(minutes=late)
    r = api.post("/auth/logout", json={"refresh_token": tok["refresh_token"]}, headers=auth(tok))
    assert r.status_code == 401 and code_of(r) in (
        "session_idle",
        "session_limit",
    )  # a stale logout records nothing
    assert sweep(api) == (
        {"limit": 0, "idle": 1} if reason == SessionEndReason.IDLE else {"limit": 1, "idle": 0}
    )
    [x] = rows(api, OFF)
    assert x.end_reason == reason
    assert len(audits(api, action)) == 1
    assert _logouts(api, OFF) == 0
