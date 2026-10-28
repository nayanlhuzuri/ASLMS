"""Edge cases for design `session-timeout`, added by the tester: the exact boundaries, the earlier-deadline rule when
both ends have passed, the limit reached while the person is active, logout from a stale cookie, a second device,
a scoped sweep, the `aslms sessions sweep` command and the scheduler entry."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
import typer
from typer.testing import CliRunner

from aslms.domain.org import SessionEndReason, User, UserSession
from aslms.services import sessions
from tests.db.auth_support import age_session, sign_in
from tests.db.test_session_timeout import (
    OFF,
    ROOT,
    Clock,
    audits,
    auth,
    code_of,
    make,
    row,
    rows,
    sweep,
)
from tests.db.world import PW, USERS

IDLE = timedelta(minutes=30)


@pytest.fixture()
def api(world):
    client = make(world)
    yield client
    client.__exit__(None, None, None)


def set_times(api, sid, *, started=None, activity=None, expires=None) -> None:
    with api.world.Session() as s:
        r = s.get(UserSession, sid)
        if started is not None:
            r.started_at = started
        if activity is not None:
            r.last_activity_at = activity
        if expires is not None:
            r.expires_at = expires
        s.commit()


def sweep_at(api, at, **kw) -> dict:
    with api.world.Session() as s:
        out = sessions.sweep(s, api.app.state.settings, at, **kw)
        s.commit()
        return out


def test_sweep_boundary_is_inclusive_at_the_idle_moment(api):
    sign_in(api, OFF, PW)
    [x] = rows(api, OFF)
    idle_end = x.last_activity_at + IDLE
    assert sweep_at(api, idle_end - timedelta(seconds=1)) == {"limit": 0, "idle": 0}
    with api.world.Session() as s:
        assert sessions.lapsed_counts(s, api.app.state.settings, idle_end) == {"limit": 0, "idle": 1}
    assert row(api, x.id).ended_at is None  # the dry run wrote nothing
    assert sweep_at(api, idle_end) == {"limit": 0, "idle": 1}
    done = row(api, x.id)
    assert done.end_reason == SessionEndReason.IDLE and done.ended_at == idle_end


def test_sweep_boundary_is_inclusive_at_the_hard_limit(api):
    sign_in(api, OFF, PW)
    [x] = rows(api, OFF)
    # activity kept recent, so only the limit can be the end
    set_times(api, x.id, activity=x.expires_at - timedelta(minutes=1))
    assert sweep_at(api, x.expires_at - timedelta(seconds=1)) == {"limit": 0, "idle": 0}
    assert sweep_at(api, x.expires_at) == {"limit": 1, "idle": 0}
    assert row(api, x.id).ended_at == x.expires_at


def test_limit_reached_while_active_ends_as_limit_everywhere(api):
    tok = sign_in(api, OFF, PW)
    age_session(api, OFF, 12 * 60 + 1, field="limit")
    [x] = rows(api, OFF)
    assert x.last_activity_at > datetime.now(UTC) - timedelta(minutes=1)  # still active
    for call in (
        lambda: api.get("/me", headers=auth(tok)),
        lambda: api.post("/me/activity", headers=auth(tok)),
    ):
        r = call()
        assert r.status_code == 401 and code_of(r) == "session_limit"
    r = api.post("/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 401 and code_of(r) == "session_limit"
    assert sweep(api) == {"limit": 1, "idle": 0}
    done = row(api, x.id)
    assert (done.end_reason, done.ended_at) == (SessionEndReason.LIMIT, x.expires_at)
    # the ended row keeps its reason on every later request
    assert code_of(api.get("/me", headers=auth(tok))) == "session_limit"
    [a] = audits(api, "auth.session_limit")
    assert a.after["session_id"] == str(x.id)


@pytest.mark.parametrize(
    ("idle_first", "reason", "code"),
    [(True, SessionEndReason.IDLE, "session_idle"), (False, SessionEndReason.LIMIT, "session_limit")],
)
def test_earlier_deadline_names_the_end_when_both_have_passed(api, idle_first, reason, code):
    tok = sign_in(api, OFF, PW)
    [x] = rows(api, OFF)
    now = datetime.now(UTC)
    if idle_first:  # idle end 2 h ago, limit 1 h ago
        activity, expires = now - timedelta(hours=2, minutes=30), now - timedelta(hours=1)
        expected_end = activity + IDLE
    else:  # limit 2 h ago, idle end 1 h ago
        expires, activity = now - timedelta(hours=2), now - timedelta(hours=1, minutes=30)
        expected_end = expires
    set_times(api, x.id, started=now - timedelta(hours=13), activity=activity, expires=expires)
    r = api.get("/me", headers=auth(tok))
    assert r.status_code == 401 and code_of(r) == code
    assert code_of(api.post("/me/activity", headers=auth(tok))) == code
    want = {"limit": 0, "idle": 0}
    want["idle" if reason == SessionEndReason.IDLE else "limit"] = 1
    with api.world.Session() as s:
        assert sessions.lapsed_counts(s, api.app.state.settings) == want
    assert sweep(api) == want
    done = row(api, x.id)
    assert (done.end_reason, done.ended_at) == (reason, expected_end)
    assert code_of(api.get("/me", headers=auth(tok))) == code  # the recorded end and the 401 agree


def test_tie_between_idle_end_and_limit_is_a_limit(api):
    tok = sign_in(api, OFF, PW)
    [x] = rows(api, OFF)
    end = datetime.now(UTC) - timedelta(minutes=5)
    set_times(api, x.id, started=end - timedelta(hours=1), activity=end - IDLE, expires=end)
    assert code_of(api.get("/me", headers=auth(tok))) == "session_limit"
    assert sweep(api) == {"limit": 1, "idle": 0}


def test_sign_in_from_a_second_device_leaves_the_first_open(api):
    a = sign_in(api, OFF, PW)
    b = sign_in(api, OFF, PW)  # no device token: a new device
    first, second = rows(api, OFF)
    assert first.device_id != second.device_id
    assert first.ended_at is None and second.ended_at is None
    assert api.get("/me", headers=auth(a)).status_code == 200
    assert api.get("/me", headers=auth(b)).status_code == 200


def test_logout_with_a_stale_refresh_token_still_ends_the_callers_session(api):
    tok = sign_in(api, OFF, PW)
    [x] = rows(api, OFF)
    r = api.post("/auth/logout", json={"refresh_token": "not-a-real-refresh-token"}, headers=auth(tok))
    assert r.status_code == 204
    done = row(api, x.id)
    assert done.end_reason == SessionEndReason.SIGNED_OUT and done.ended_at is not None
    assert len(audits(api, "auth.logout")) == 1
    r = api.post("/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 401  # the session is over, the token cannot start another


def test_logout_of_one_login_does_not_end_another_logins_session(api):
    mine = sign_in(api, OFF, PW)
    theirs = sign_in(api, USERS["edu_admin"][0], PW)
    api.post("/auth/logout", json={"refresh_token": theirs["refresh_token"]}, headers=auth(mine))
    assert [x.ended_at for x in rows(api, USERS["edu_admin"][0])] == [None]
    assert api.get("/me", headers=auth(theirs)).status_code == 200


def test_ping_after_logout_is_refused_without_a_new_end(api):
    tok = sign_in(api, OFF, PW)
    api.post("/auth/logout", json={"refresh_token": tok["refresh_token"]}, headers=auth(tok))
    [x] = rows(api, OFF)
    r = api.post("/me/activity", headers=auth(tok))
    assert r.status_code == 401 and r.json()["detail"] == "token is not valid"
    assert row(api, x.id).end_reason == SessionEndReason.SIGNED_OUT
    assert sweep(api) == {"limit": 0, "idle": 0}


def test_activity_exactly_at_the_idle_moment_is_refused_and_one_second_before_is_not(api, monkeypatch):
    Clock(monkeypatch)
    tok = sign_in(api, OFF, PW)
    [x] = rows(api, OFF)
    base = x.last_activity_at
    monkeypatch.setattr(sessions.otp, "utcnow", lambda: base + IDLE - timedelta(seconds=1))
    assert api.post("/me/activity", headers=auth(tok)).status_code == 200
    moved = row(api, x.id).last_activity_at
    monkeypatch.setattr(sessions.otp, "utcnow", lambda: moved + IDLE)
    r = api.post("/me/activity", headers=auth(tok))
    assert r.status_code == 401 and code_of(r) == "session_idle"


def test_a_scoped_sweep_touches_only_that_login(api):
    sign_in(api, OFF, PW)
    sign_in(api, ROOT, PW)
    age_session(api, OFF, 45)
    age_session(api, ROOT, 45)
    with api.world.Session() as s:
        uid = s.scalar(sa.select(User.id).where(User.email == OFF))
        out = sessions.sweep(s, api.app.state.settings, user_id=uid)
        s.commit()
    assert out == {"limit": 0, "idle": 1}
    assert rows(api, OFF)[0].ended_at is not None and rows(api, ROOT)[0].ended_at is None
    assert sweep(api) == {"limit": 0, "idle": 1}
    assert sweep(api) == {"limit": 0, "idle": 0}
    assert len(audits(api, "auth.signed_out_idle")) == 2


def test_every_session_end_has_an_audit_row(api):
    # logout, replaced and idle each leave a record of the end
    a = sign_in(api, OFF, PW)
    api.post("/auth/logout", json={"refresh_token": a["refresh_token"]}, headers=auth(a))
    assert len(audits(api, "auth.logout")) == 1
    first = sign_in(api, OFF, PW)
    sign_in(api, OFF, PW, device_token=first["device_token"])  # replaces `first`'s session
    assert len(audits(api, "auth.login")) >= 3
    age_session(api, OFF, 45)
    sweep(api)
    assert len(audits(api, "auth.signed_out_idle")) == 1
    with api.world.Session() as s:
        open_rows = s.scalar(
            sa.select(sa.func.count()).select_from(UserSession).where(UserSession.ended_at.is_(None))
        )
        ended_without_reason = s.scalar(
            sa.select(sa.func.count())
            .select_from(UserSession)
            .where(UserSession.ended_at.is_not(None), UserSession.end_reason.is_(None))
        )
    assert open_rows == 0 and ended_without_reason == 0


def _cli(world, monkeypatch):
    from aslms.cli import sessions as cli

    @contextmanager
    def scope():
        with world.Session() as s:
            yield s
            s.commit()

    monkeypatch.setattr(cli, "session_scope", scope)
    app = typer.Typer()
    app.add_typer(cli.sessions_app, name="sessions")
    return app, CliRunner()


def test_cli_sweep_dry_run_writes_nothing_then_the_real_run_ends_once(api, world, monkeypatch):
    sign_in(api, OFF, PW)
    age_session(api, OFF, 45)
    app, runner = _cli(world, monkeypatch)
    r = runner.invoke(app, ["sessions", "sweep", "--dry-run"])
    assert r.exit_code == 0 and "would end: limit 0, idle 1" in r.output
    assert rows(api, OFF)[0].ended_at is None and audits(api, "auth.signed_out_idle") == []
    r = runner.invoke(app, ["sessions", "sweep"])
    assert r.exit_code == 0 and "ended: limit 0, idle 1" in r.output
    assert len(audits(api, "auth.signed_out_idle")) == 1
    r = runner.invoke(app, ["sessions", "sweep"])
    assert "limit 0, idle 0" in r.output and len(audits(api, "auth.signed_out_idle")) == 1


def test_scheduler_runs_the_sweep_every_five_minutes():
    from aslms.jobs.celery_app import app as celery

    entry = celery.conf.beat_schedule["sessions-sweep"]
    assert entry["task"] == "aslms.sessions_sweep"
    assert "aslms.sessions_sweep" in celery.tasks
    assert entry["schedule"].minute == set(range(1, 60, 5))
