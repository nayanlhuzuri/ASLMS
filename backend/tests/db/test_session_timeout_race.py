"""Design `session-timeout`, decisions 12 and 14 under real concurrency (review finding 5): two connections at once.
The sweep's and the ping's updates are conditional on `ended_at IS NULL` (and the lapse), so while one connection holds
the row the other waits, then re-checks its condition against the committed row: two sweeps end a session once with
one audit row, a ping waiting behind a sweep is refused and revives nothing, and a sweep waiting behind a ping ends
nothing."""

from __future__ import annotations

import threading
import time
from datetime import timedelta

import pytest
import sqlalchemy as sa

from aslms.domain.org import SessionEndReason, UserSession
from aslms.services import sessions
from tests.db.auth_support import age_session, sign_in
from tests.db.test_session_timeout import OFF, audits, make, row, rows
from tests.db.world import PW, USERS


@pytest.fixture()
def api(world):
    client = make(world)
    yield client
    client.__exit__(None, None, None)


HOLD = 0.6  # seconds the first connection keeps the row before it commits


class Behind(threading.Thread):
    """Runs `work(session)` on a connection of its own and commits; keeps the result or the exception."""

    def __init__(self, factory, work) -> None:
        super().__init__(daemon=True)
        self.factory, self.work = factory, work
        self.result = None
        self.error: BaseException | None = None

    def run(self) -> None:
        with self.factory() as s:
            try:
                self.result = self.work(s)
                s.commit()
            except BaseException as exc:  # noqa: BLE001 - handed to the test
                s.rollback()
                self.error = exc


def _waits_then_runs(first_session, second: Behind) -> None:
    """Starts `second` while `first_session` holds the row, checks it is blocked, then commits the first."""
    second.start()
    time.sleep(HOLD)
    assert second.is_alive(), "the second connection did not wait for the row"
    first_session.commit()
    second.join(timeout=10)
    assert not second.is_alive()


def test_two_sweeps_at_once_end_a_session_once_with_one_audit_row(api):
    sign_in(api, OFF, PW)
    age_session(api, OFF, 40)
    [x] = rows(api, OFF)
    settings = api.app.state.settings
    factory = api.world.Session
    with factory() as first:
        assert sessions.sweep(first, settings) == {"limit": 0, "idle": 1}  # holds the row, not committed
        second = Behind(factory, lambda s: sessions.sweep(s, settings))
        _waits_then_runs(first, second)
    assert second.error is None and second.result == {"limit": 0, "idle": 0}
    assert row(api, x.id).end_reason == SessionEndReason.IDLE
    assert len(audits(api, "auth.signed_out_idle")) == 1


def test_a_ping_waiting_behind_the_sweep_is_refused_and_revives_nothing(api):
    sign_in(api, OFF, PW)
    age_session(api, OFF, 40)
    [x] = rows(api, OFF)
    settings = api.app.state.settings
    factory = api.world.Session
    # the ping's clock still sees the session live (ten minutes after the last activity): only the row decides
    ping_at = x.last_activity_at + timedelta(minutes=10)
    with factory() as first:
        assert sessions.sweep(first, settings)["idle"] == 1
        second = Behind(factory, lambda s: sessions.touch(s, x.id, x.user_id, ping_at, settings))
        _waits_then_runs(first, second)
    assert isinstance(second.error, sessions.SessionIdle)
    ended = row(api, x.id)
    assert ended.end_reason == SessionEndReason.IDLE and ended.last_activity_at == x.last_activity_at
    assert len(audits(api, "auth.signed_out_idle")) == 1


def test_a_sweep_waiting_behind_a_ping_ends_nothing(api):
    sign_in(api, OFF, PW)
    age_session(api, OFF, 40)
    [x] = rows(api, OFF)
    settings = api.app.state.settings
    factory = api.world.Session
    ping_at = x.last_activity_at + timedelta(
        minutes=20
    )  # live then; the new idle end is 10 minutes ahead of now
    with factory() as first:
        touched = sessions.touch(first, x.id, x.user_id, ping_at, settings)
        assert touched.last_activity_at == ping_at  # holds the row, not committed
        second = Behind(factory, lambda s: sessions.sweep(s, settings))
        _waits_then_runs(first, second)
    assert second.error is None and second.result == {"limit": 0, "idle": 0}
    kept = row(api, x.id)
    assert kept.ended_at is None and kept.last_activity_at == ping_at
    assert audits(api, "auth.signed_out_idle") == []


def test_many_sweeps_at_once_over_many_sessions_end_each_once(api):
    sweeps = 4
    for key in ("edu_off1", "edu_admin", "edu_head"):
        sign_in(api, USERS[key][0], PW)
        age_session(api, USERS[key][0], 45)
    settings = api.app.state.settings
    barrier = threading.Barrier(sweeps)

    def work(s):
        barrier.wait(timeout=10)
        return sessions.sweep(s, settings)

    threads = [Behind(api.world.Session, work) for _ in range(sweeps)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert all(t.error is None for t in threads)
    assert sum(t.result["idle"] for t in threads) == 3
    with api.world.Session() as s:
        ended = s.scalar(
            sa.select(sa.func.count())
            .select_from(UserSession)
            .where(UserSession.end_reason == SessionEndReason.IDLE)
        )
    assert ended == 3 and len(audits(api, "auth.signed_out_idle")) == 3
