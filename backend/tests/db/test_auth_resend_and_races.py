"""Design `otp-and-profile`, review findings of 8 Oct 2026: a sign-in challenge spent by wrong codes must not be
resent once the password or e-mail changed, once it expired or once a newer code superseded it (decision 9,
deviation 14); and parallel requests for one login must not get more than 5 tries per code, more than the 10
failures of the lock, two live codes or two token pairs from one code (decisions 2 and 4). The race tests run
each request in its own committed session on its own connection, the way the API does."""

from __future__ import annotations

import re
import threading

import pytest
import sqlalchemy as sa

from aslms.core.config import Settings
from aslms.domain.org import OtpCode
from aslms.services import auth
from aslms.services.mailer import RecordingMailer
from tests.db.auth_support import last_code, sign_in, start
from tests.db.test_api_auth import EDU_OFF, Clock, codes, make, user_row
from tests.db.world import PW, USERS

SETTINGS = Settings(_env_file=None, aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters")
CLIENT = auth.Client(ip="10.1.2.3", user_agent="pytest")
CODE_RE = re.compile(r"\b(\d{6})\b")


@pytest.fixture()
def api(world):
    client = make(world)
    yield client
    client.__exit__(None, None, None)


def wrong_of(right: str) -> str:
    return "000000" if right != "000000" else "111111"


def spend(api, step: dict) -> None:
    """Five wrong codes on the challenge: it is spent by codes."""
    bad = wrong_of(last_code(api, EDU_OFF))
    for _ in range(5):
        r = api.post("/auth/otp/verify", json={"challenge_id": step["challenge_id"], "code": bad})
        assert r.status_code == 401
    assert codes(api, EDU_OFF)[-1].attempts == 5


def admin_password(api) -> None:
    admin = sign_in(api, USERS["edu_admin"][0], PW)
    uid = str(user_row(api, EDU_OFF).id)
    r = api.post(
        f"/admin/users/{uid}/password",
        json={"password": "reset-by-admin-1"},
        headers={"Authorization": f"Bearer {admin['access_token']}"},
    )
    assert r.status_code == 204, r.text


def admin_email(api) -> None:
    admin = sign_in(api, USERS["edu_admin"][0], PW)
    uid = str(user_row(api, EDU_OFF).id)
    r = api.patch(
        f"/admin/users/{uid}",
        json={"email": "off1.elsewhere@example.org"},
        headers={"Authorization": f"Bearer {admin['access_token']}"},
    )
    assert r.status_code == 200, r.text


def own_reset(api) -> None:
    reset = api.post("/auth/password-reset/request", json={"email": EDU_OFF}).json()
    r = api.post(
        "/auth/password-reset/confirm",
        json={
            "challenge_id": reset["challenge_id"],
            "code": last_code(api, EDU_OFF),
            "new_password": "brand-new-pass-1",
        },
    )
    assert r.status_code == 204, r.text


# ------------------------------------------------------------------------------------------------ resend


@pytest.mark.parametrize("change", [admin_password, admin_email, own_reset], ids=lambda f: f.__name__)
def test_a_challenge_spent_by_codes_is_not_resent_after_a_credential_change(api, monkeypatch, change):
    """The attacker with the old password spends a challenge on purpose; after the change the challenge must not
    yield fresh codes (it stood in for a password that no longer exists, or a mailbox no longer the login's)."""
    clock = Clock(monkeypatch)
    step = start(api, EDU_OFF, PW).json()
    spend(api, step)
    clock.move(seconds=1)
    change(api)
    sent_before = len(api.mailer.sent)
    for _ in range(3):
        clock.move(seconds=121)
        r = api.post("/auth/otp/resend", json={"challenge_id": step["challenge_id"]})
        assert r.status_code == 401 and r.json()["detail"]["code"] == "otp_expired", r.text
    assert len(api.mailer.sent) == sent_before, "a spent challenge mailed a new code after the change"


def test_a_challenge_spent_by_codes_is_not_resent_after_it_expired(api, monkeypatch):
    clock = Clock(monkeypatch)
    step = start(api, EDU_OFF, PW).json()
    spend(api, step)
    clock.move(minutes=11)
    r = api.post("/auth/otp/resend", json={"challenge_id": step["challenge_id"]})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "otp_expired"


def test_an_expired_live_challenge_is_not_resent(api, monkeypatch):
    clock = Clock(monkeypatch)
    step = start(api, EDU_OFF, PW).json()
    clock.move(minutes=11)
    r = api.post("/auth/otp/resend", json={"challenge_id": step["challenge_id"]})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "otp_expired"


def test_a_spent_challenge_resends_once_then_only_the_newest_resends(api, monkeypatch):
    """Nothing changed: the spent challenge gives one new code (deviation 6); the old id cannot be replayed for
    more, the new one can."""
    clock = Clock(monkeypatch)
    step = start(api, EDU_OFF, PW).json()
    spend(api, step)
    clock.move(seconds=121)
    first = api.post("/auth/otp/resend", json={"challenge_id": step["challenge_id"]})
    assert first.status_code == 200, first.text
    clock.move(seconds=121)
    replay = api.post("/auth/otp/resend", json={"challenge_id": step["challenge_id"]})
    assert replay.status_code == 401 and replay.json()["detail"]["code"] == "otp_expired"
    newest = api.post("/auth/otp/resend", json={"challenge_id": first.json()["challenge_id"]})
    assert newest.status_code == 200, newest.text
    v = api.post(
        "/auth/otp/verify",
        json={"challenge_id": newest.json()["challenge_id"], "code": last_code(api, EDU_OFF)},
    )
    assert v.status_code == 200


# ------------------------------------------------------------------------------------------------ races


def parallel(world, n: int, step) -> list[object]:
    """Runs `step(session)` in `n` threads at once, each in its own session; a refusal is committed like the
    router does (decision 5). Returns each result or refusal."""
    barrier = threading.Barrier(n)
    results: list[object] = [None] * n

    def run(i: int) -> None:
        with world.Session() as s:
            barrier.wait()
            try:
                results[i] = step(s)
                s.commit()
            except auth.OtpError as exc:
                s.commit()
                results[i] = exc
            except Exception as exc:  # noqa: BLE001 - reported by the assertions
                s.rollback()
                results[i] = exc

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    return results


def begin(world, mailer: RecordingMailer) -> tuple[str, str]:
    with world.Session() as s:
        step = auth.start_login(s, EDU_OFF, PW, CLIENT, mailer, SETTINGS)
        s.commit()
    return str(step.challenge_id), CODE_RE.search(mailer.sent[-1].text).group(1)


def kinds(results: list[object]) -> list[str]:
    return sorted(type(r).__name__ for r in results)


def failures(world, action: str) -> int:
    with world.Session() as s:
        return s.scalar(
            sa.text(
                "select count(*) from audit_log a join users u on u.id = a.entity_id "
                "where a.action = :a and u.email = :e"
            ),
            {"a": action, "e": EDU_OFF},
        )


def test_parallel_wrong_codes_get_five_tries_per_code(world):
    mailer = RecordingMailer()
    cid, right = begin(world, mailer)
    bad = wrong_of(right)
    results = parallel(world, 12, lambda s: auth.complete_login(s, cid, bad, CLIENT, mailer, SETTINGS))
    assert kinds(results) == ["OtpExpired"] * 7 + ["OtpInvalid"] * 5, kinds(results)
    with world.Session() as s:
        row = s.get(OtpCode, cid)
        assert row.attempts == 5 and row.consumed_at is not None
    assert failures(world, "auth.otp_failed") == 5


def test_parallel_right_codes_sign_in_once(world):
    mailer = RecordingMailer()
    cid, right = begin(world, mailer)
    results = parallel(world, 6, lambda s: auth.complete_login(s, cid, right, CLIENT, mailer, SETTINGS))
    assert kinds(results) == ["OtpExpired"] * 5 + ["Signed"], kinds(results)
    assert failures(world, "auth.login") == 1


def test_parallel_sign_ins_leave_one_live_code(world):
    mailer = RecordingMailer()
    results = parallel(world, 6, lambda s: auth.start_login(s, EDU_OFF, PW, CLIENT, mailer, SETTINGS))
    assert kinds(results) == ["LoginStep"] + ["TooManyCodes"] * 5, kinds(results)
    with world.Session() as s:
        live = s.scalar(
            sa.text(
                "select count(*) from otp_codes o join users u on u.id = o.user_id "
                "where u.email = :e and o.purpose = 'login' and o.consumed_at is null"
            ),
            {"e": EDU_OFF},
        )
    assert live == 1 and len(mailer.sent) == 1


def test_parallel_wrong_passwords_stop_at_the_lock(world):
    mailer = RecordingMailer()
    results = parallel(
        world, 14, lambda s: auth.start_login(s, EDU_OFF, "not-the-password-9", CLIENT, mailer, SETTINGS)
    )
    assert kinds(results) == ["InvalidCredentials"] * 10 + ["Locked"] * 4, kinds(results)
    assert failures(world, "auth.login_failed") == 10
    assert failures(world, "auth.locked") == 1
