"""Design `otp-and-profile` end to end through the API, a `RecordingMailer` on `app.state.mailer`: the two-step
sign-in, codes and their limits, the lock, mail failures, devices, password reset, refresh reuse, the
first-sign-in gate, the administrator paths and the audit rows. Every refused step's counter, spent code,
audit row or revocation is read back in a new session (decision 5: committed, not rolled back)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.org import OtpCode, RefreshToken, User, UserDevice
from aslms.services import otp
from aslms.services import users as users_service
from aslms.services.mailer import ConsoleMailer, MailError, RecordingMailer
from tests.db.auth_support import last_code, sign_in, start
from tests.db.world import PW, USERS

JWT = "test-secret-of-at-least-thirty-two-characters"
EDU_OFF = USERS["edu_off1"][0]


class Clock:
    """Moves the sign-in services' clock (`otp.utcnow`)."""

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
    client.mailer = app.state.mailer
    client.world = world
    return client


@pytest.fixture()
def api(world):
    client = make(world)
    yield client
    client.__exit__(None, None, None)


def user_row(api, email: str) -> User:
    with api.world.Session() as s:
        return s.scalar(sa.select(User).where(User.email == email))


def codes(api, email: str) -> list[OtpCode]:
    with api.world.Session() as s:
        uid = s.scalar(sa.select(User.id).where(User.email == email))
        return list(s.scalars(sa.select(OtpCode).where(OtpCode.user_id == uid).order_by(OtpCode.created_at)))


def actions(api, email: str) -> list[str]:
    """The audit actions about the login or by it, oldest first."""
    with api.world.Session() as s:
        uid = s.scalar(sa.select(User.id).where(User.email == email))
        return list(
            s.scalars(
                sa.text(
                    "select action from audit_log where entity_id = :u or actor_user_id = :u "
                    "or after->>'user_id' = :s order by created_at, id"
                ),
                {"u": uid, "s": str(uid)},
            )
        )


def live_tokens(api, email: str) -> int:
    with api.world.Session() as s:
        uid = s.scalar(sa.select(User.id).where(User.email == email))
        return s.scalar(
            sa.select(sa.func.count())
            .select_from(RefreshToken)
            .where(RefreshToken.user_id == uid, RefreshToken.revoked_at.is_(None))
        )


def auth(tok: dict) -> dict:
    return {"Authorization": f"Bearer {tok['access_token']}"}


# ------------------------------------------------------------------------------------------------ sign-in


def test_password_then_code_gives_tokens_and_one_answer_for_bad_credentials(api):
    step = start(api, EDU_OFF, PW)
    assert step.status_code == 200
    body = step.json()
    assert set(body) == {"step", "challenge_id", "purpose", "sent_to", "expires_in", "resend_after"}
    assert body["step"] == "otp" and "access_token" not in step.text  # no token from step one
    assert live_tokens(api, EDU_OFF) == 0
    v = api.post(
        "/auth/otp/verify", json={"challenge_id": body["challenge_id"], "code": last_code(api, EDU_OFF)}
    )
    assert v.status_code == 200 and v.json()["next_step"] == "ready"
    assert api.get("/cases", headers=auth(v.json())).status_code == 200
    # wrong password, unknown e-mail and a disabled login: the same 401 and body
    wrong = api.post("/auth/login", json={"email": EDU_OFF, "password": "wrong-password-1"})
    unknown = api.post("/auth/login", json={"email": "nobody@example.org", "password": PW})
    with api.world.Session() as s:
        s.execute(sa.update(User).where(User.email == USERS["edu_off2"][0]).values(is_active=False))
        s.commit()
    disabled = api.post("/auth/login", json={"email": USERS["edu_off2"][0], "password": PW})
    assert wrong.status_code == unknown.status_code == disabled.status_code == 401
    assert wrong.json() == unknown.json() == disabled.json()
    assert wrong.json()["detail"]["code"] == "invalid_credentials"
    assert actions(api, EDU_OFF)[-1] == "auth.login_failed"
    assert actions(api, USERS["edu_off2"][0])[-1] == "auth.login_failed"


def test_wrong_codes_count_survive_and_spend(api):
    step = start(api, EDU_OFF, PW).json()
    right = last_code(api, EDU_OFF)
    wrong = "000000" if right != "000000" else "111111"
    r = api.post("/auth/otp/verify", json={"challenge_id": step["challenge_id"], "code": wrong})
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "otp_invalid" and r.json()["detail"]["attempts_left"] == 4
    assert codes(api, EDU_OFF)[-1].attempts == 1  # committed with the 401
    assert actions(api, EDU_OFF)[-1] == "auth.otp_failed"
    for left in (3, 2, 1, 0):
        r = api.post("/auth/otp/verify", json={"challenge_id": step["challenge_id"], "code": wrong})
        assert r.json()["detail"]["attempts_left"] == left
    row = codes(api, EDU_OFF)[-1]
    assert row.attempts == 5 and row.consumed_at is not None  # the fifth wrong code spent it
    r = api.post("/auth/otp/verify", json={"challenge_id": step["challenge_id"], "code": right})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "otp_expired"


def test_expired_code(api, monkeypatch):
    clock = Clock(monkeypatch)
    step = start(api, EDU_OFF, PW).json()
    clock.move(minutes=11)
    r = api.post(
        "/auth/otp/verify", json={"challenge_id": step["challenge_id"], "code": last_code(api, EDU_OFF)}
    )
    assert r.status_code == 401 and r.json()["detail"]["code"] == "otp_expired"
    bogus = api.post(
        "/auth/otp/verify", json={"challenge_id": "0192b3c4-0000-7000-8000-000000000000", "code": "123456"}
    )
    assert bogus.status_code == 401 and bogus.json()["detail"]["code"] == "otp_expired"


def test_resend_wait_hourly_cap_and_resend_ends_the_old_code(api, monkeypatch):
    clock = Clock(monkeypatch)
    first = start(api, EDU_OFF, PW).json()
    old_code = last_code(api, EDU_OFF)
    r = api.post("/auth/otp/resend", json={"challenge_id": first["challenge_id"]})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "too_many_codes"
    assert 0 < r.json()["detail"]["retry_after"] <= 120 and r.headers["Retry-After"]
    again = api.post("/auth/login", json={"email": EDU_OFF, "password": PW})
    assert again.status_code == 429 and again.json()["detail"]["code"] == "too_many_codes"
    clock.move(seconds=121)
    r = api.post("/auth/otp/resend", json={"challenge_id": first["challenge_id"]})
    assert r.status_code == 200 and r.json()["challenge_id"] != first["challenge_id"]
    old = api.post("/auth/otp/verify", json={"challenge_id": first["challenge_id"], "code": old_code})
    assert old.status_code == 401 and old.json()["detail"]["code"] == "otp_expired"  # the resend ended it
    v = api.post(
        "/auth/otp/verify", json={"challenge_id": r.json()["challenge_id"], "code": last_code(api, EDU_OFF)}
    )
    assert v.status_code == 200
    # a used challenge cannot be resent (that would be a sign-in without the password)
    assert api.post("/auth/otp/resend", json={"challenge_id": r.json()["challenge_id"]}).status_code == 401
    # the hourly cap: ten codes in the hour across purposes, the eleventh refused
    for _ in range(8):
        clock.move(seconds=121)
        assert api.post("/auth/login", json={"email": EDU_OFF, "password": PW}).status_code == 200
    assert len(codes(api, EDU_OFF)) == 10
    clock.move(seconds=121)
    r = api.post("/auth/login", json={"email": EDU_OFF, "password": PW})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "too_many_codes"
    assert r.json()["detail"]["retry_after"] > 120


def test_code_is_in_the_mail_and_in_no_log_record(api, caplog):
    caplog.set_level(logging.DEBUG)
    tok = sign_in(api, EDU_OFF, PW)
    code = last_code(api, EDU_OFF)
    mail = next(m for m in api.mailer.sent if m.subject == "ASLMS sign-in code")
    assert code in mail.text and "10 minutes" in mail.text
    for rec in caplog.records:
        text = rec.getMessage()
        assert code not in text and PW not in text and tok["access_token"] not in text


def test_lock_after_ten_failures_and_open_after_the_window(api, monkeypatch):
    clock = Clock(monkeypatch)
    for _ in range(10):
        assert (
            api.post("/auth/login", json={"email": EDU_OFF, "password": "wrong-password-1"}).status_code
            == 401
        )
    r = api.post("/auth/login", json={"email": EDU_OFF, "password": PW})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "locked"
    assert 0 < r.json()["detail"]["retry_after"] <= 15 * 60
    assert actions(api, EDU_OFF).count("auth.locked") == 1
    reset = api.post("/auth/password-reset/request", json={"email": EDU_OFF})
    assert reset.status_code == 202 and api.mailer.sent == []  # neutral answer, no mail while locked
    clock.move(minutes=16)
    assert sign_in(api, EDU_OFF, PW)["next_step"] == "ready"


def test_mail_failure_and_unconfigured_mail(world, monkeypatch):
    # the test database is reached as its superuser, which a prod app refuses at start (design deployment-checklist,
    # decision 5; tested in tests/unit/test_ops_unit.py); this test is about mail only
    monkeypatch.setattr("aslms.api.main.refuse_superuser", lambda url, is_prod: None)
    api = make(world)
    try:
        api.app.state.mailer = RecordingMailer(fail_with=MailError("mailtrap api answered 500: token=***"))
        r = api.post("/auth/login", json={"email": EDU_OFF, "password": PW})
        assert r.status_code == 502 and r.json()["detail"]["code"] == "mail_failed"
        assert "token" not in r.json()["detail"]["message"]
        assert [c for c in codes(api, EDU_OFF) if c.consumed_at is None] == []  # no live code left
        api.app.state.mailer = RecordingMailer()
        assert start(api, EDU_OFF, PW).status_code == 200  # a failed send costs no resend wait
    finally:
        api.__exit__(None, None, None)
    prod = make(world, app_env="prod")
    try:
        prod.app.state.mailer = ConsoleMailer()
        r = prod.post("/auth/login", json={"email": EDU_OFF, "password": PW})
        assert r.status_code == 503 and r.json()["detail"]["code"] == "mail_not_configured"
        r = prod.post("/auth/password-reset/request", json={"email": EDU_OFF})
        assert r.status_code == 503
    finally:
        prod.__exit__(None, None, None)


# ------------------------------------------------------------------------------------------------ devices


def test_devices_notice_list_and_revoke(api):
    first = sign_in(api, EDU_OFF, PW, device_label="Office PC")
    device_token = first["device_token"]
    assert device_token
    notices = [m for m in api.mailer.sent if m.subject == "New sign-in to ASLMS" and m.to == EDU_OFF]
    assert len(notices) == 1 and "Office PC" in notices[0].text and device_token not in notices[0].text
    second = sign_in(api, EDU_OFF, PW, device_token=device_token)
    assert second["device_token"] is None
    assert (
        len([m for m in api.mailer.sent if m.subject == "New sign-in to ASLMS" and m.to == EDU_OFF]) == 1
    )  # known device: none
    listed = api.get("/me/devices", headers={**auth(second), "X-Device-Token": device_token}).json()
    assert len(listed) == 1 and listed[0]["current"] is True and listed[0]["label"] == "Office PC"
    assert "trusted_until" not in listed[0]
    # another login cannot revoke it
    other = sign_in(api, USERS["edu_off2"][0], PW)
    assert api.post(f"/me/devices/{listed[0]['id']}/revoke", headers=auth(other)).status_code == 404
    assert api.post(f"/me/devices/{listed[0]['id']}/revoke", headers=auth(second)).status_code == 204
    r = api.post("/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "refresh_invalid"
    assert "auth.device_revoked" in actions(api, EDU_OFF)
    # the revoked device is unknown again: a new token and a new notice
    third = sign_in(api, EDU_OFF, PW, device_token=device_token)
    assert third["device_token"] and third["device_token"] != device_token
    assert len([m for m in api.mailer.sent if m.subject == "New sign-in to ASLMS" and m.to == EDU_OFF]) == 2
    with api.world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(UserDevice)) == 3  # never deleted


# ------------------------------------------------------------------------------------------------ password reset


def test_reset_request_answers_alike_and_sends_only_once(api):
    with api.world.Session() as s:
        s.execute(sa.update(User).where(User.email == USERS["edu_off2"][0]).values(is_active=False))
        s.commit()
    real = api.post("/auth/password-reset/request", json={"email": EDU_OFF})
    assert len(api.mailer.sent) == 1 and api.mailer.sent[0].subject == "ASLMS password reset code"
    unknown = api.post("/auth/password-reset/request", json={"email": "nobody@example.org"})
    disabled = api.post("/auth/password-reset/request", json={"email": USERS["edu_off2"][0]})
    repeat = api.post("/auth/password-reset/request", json={"email": EDU_OFF})
    for r in (real, unknown, disabled, repeat):
        assert r.status_code == 202
        assert set(r.json()) == {"challenge_id", "expires_in", "resend_after"}
        assert (r.json()["expires_in"], r.json()["resend_after"]) == (600, 120)
    assert len(api.mailer.sent) == 1  # nothing for the unknown, the disabled or the repeat
    # a resend of a reset challenge (or of an unknown id) gets the same neutral answer
    for cid in (real.json()["challenge_id"], unknown.json()["challenge_id"]):
        r = api.post("/auth/otp/resend", json={"challenge_id": cid})
        assert r.status_code == 202 and set(r.json()) == {"challenge_id", "expires_in", "resend_after"}
    assert len(api.mailer.sent) == 1
    # a fake challenge never verifies, and answers like a wrong code on a real one
    fake = api.post(
        "/auth/password-reset/confirm",
        json={
            "challenge_id": unknown.json()["challenge_id"],
            "code": "123456",
            "new_password": "brand-new-pass-1",
        },
    )
    code = last_code(api, EDU_OFF)
    bad = "000000" if code != "000000" else "111111"
    wrong = api.post(
        "/auth/password-reset/confirm",
        json={"challenge_id": real.json()["challenge_id"], "code": bad, "new_password": "brand-new-pass-1"},
    )
    assert fake.status_code == wrong.status_code == 401 and fake.json() == wrong.json()


def test_reset_confirm_sets_password_and_ends_sessions(api, monkeypatch):
    tok = sign_in(api, EDU_OFF, PW)
    with api.world.Session() as s:
        s.execute(sa.update(User).where(User.email == EDU_OFF).values(must_change_password=True))
        s.commit()
    r = api.post("/auth/password-reset/request", json={"email": EDU_OFF}).json()
    code = last_code(api, EDU_OFF)
    weak = api.post(
        "/auth/password-reset/confirm",
        json={"challenge_id": r["challenge_id"], "code": code, "new_password": "short"},
    )
    assert weak.status_code == 422 and weak.json()["detail"]["code"] == "weak_password"
    same = api.post(
        "/auth/password-reset/confirm",
        json={"challenge_id": r["challenge_id"], "code": code, "new_password": PW},
    )
    assert same.status_code == 422  # same as the current one; the code stays usable
    real_now = users_service._now
    monkeypatch.setattr(users_service, "_now", lambda: real_now() + timedelta(seconds=2))
    ok = api.post(
        "/auth/password-reset/confirm",
        json={"challenge_id": r["challenge_id"], "code": code, "new_password": "brand-new-pass-1"},
    )
    assert ok.status_code == 204
    u = user_row(api, EDU_OFF)
    assert u.must_change_password is False and u.password_changed_at is not None
    assert live_tokens(api, EDU_OFF) == 0
    assert api.get("/me", headers=auth(tok)).status_code == 401  # the old access token stops at once
    assert api.post("/auth/refresh", json={"refresh_token": tok["refresh_token"]}).status_code == 401
    assert api.post("/auth/login", json={"email": EDU_OFF, "password": PW}).status_code == 401
    assert sign_in(api, EDU_OFF, "brand-new-pass-1")["next_step"] == "ready"
    assert {"auth.password_reset_requested", "auth.password_reset"} <= set(actions(api, EDU_OFF))


# ------------------------------------------------------------------------------------------------ refresh reuse


def test_refresh_reuse_revokes_everything_and_survives_the_401(api):
    a = sign_in(api, EDU_OFF, PW)
    b = sign_in(api, EDU_OFF, PW)  # a second session
    rotated = api.post("/auth/refresh", json={"refresh_token": a["refresh_token"]})
    assert rotated.status_code == 200 and rotated.json()["next_step"] == "ready"
    r = api.post("/auth/refresh", json={"refresh_token": a["refresh_token"]})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "session_ended"
    assert live_tokens(api, EDU_OFF) == 0  # read in a new session: committed with the 401
    assert api.post("/auth/refresh", json={"refresh_token": b["refresh_token"]}).status_code == 401
    assert "auth.refresh_reused" in actions(api, EDU_OFF)
    garbage = api.post("/auth/refresh", json={"refresh_token": "x" * 40})
    assert garbage.status_code == 401 and garbage.json()["detail"]["code"] == "refresh_invalid"


# ------------------------------------------------------------------------------------------------ the gate


def test_first_sign_in_gate_password_then_profile(api):
    admin = sign_in(api, USERS["edu_admin"][0], PW)
    body = {
        "email": "new.officer@example.org",
        "password": "given-by-admin-1",
        "full_name": "New Officer",
        "role": "dept_officer",
        "office_code": "EDU",
    }
    created = api.post("/admin/users", json=body, headers=auth(admin))
    assert created.status_code == 201, created.text
    assert created.json()["must_change_password"] is True and created.json()["must_confirm_profile"] is True
    tok = sign_in(api, "new.officer@example.org", "given-by-admin-1")
    assert tok["next_step"] == "change_password"
    h = auth(tok)
    r = api.get("/cases", headers=h)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "password_change_required"
    assert api.get("/me", headers=h).status_code == 200
    profile = api.get("/me/profile", headers=h).json()
    assert (
        profile["email"] == "new.officer@example.org" and profile["memberships"][0]["office"]["code"] == "EDU"
    )
    assert api.get("/me/notification-preferences", headers=h).status_code == 200
    r = api.post("/me/profile/confirm", json={"full_name": "New Officer", "mobile": "9864012345"}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "password_change_required"
    bad = api.post(
        "/me/password",
        json={"current_password": "wrong-password-1", "new_password": "my-own-pass-1"},
        headers=h,
    )
    assert bad.status_code == 401 and bad.json()["detail"]["code"] == "wrong_password"
    weak = api.post(
        "/me/password",
        json={"current_password": "given-by-admin-1", "new_password": "weakpassword"},
        headers=h,
    )
    assert weak.status_code == 422 and weak.json()["detail"]["code"] == "weak_password"
    changed = api.post(
        "/me/password",
        json={
            "current_password": "given-by-admin-1",
            "new_password": "my-own-pass-1",
            "device_token": tok["device_token"],
        },
        headers=h,
    )
    assert changed.status_code == 200 and changed.json()["next_step"] == "confirm_profile"
    h = auth(changed.json())
    r = api.get("/cases", headers=h)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "profile_confirmation_required"
    no_mobile = api.post("/me/profile/confirm", json={"full_name": "New Officer"}, headers=h)
    assert no_mobile.status_code == 422 and no_mobile.json()["detail"]["code"] == "invalid_mobile"
    r = api.post(
        "/me/profile/confirm",
        json={
            "full_name": "New  Officer, ACS",
            "mobile": "+91 98640 12345",
            "notification_preferences": {"email": {"digest": "none", "critical_only": True}},
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["mobile"] == "9864012345" and out["full_name"] == "New Officer, ACS"
    assert out["must_confirm_profile"] is False and out["profile_confirmed_at"]
    assert out["notification_preferences"]["email"] == {
        "enabled": True,
        "digest": "none",
        "critical_only": True,
    }
    assert api.get("/cases", headers=h).status_code == 200
    again = api.post("/me/profile/confirm", json={"full_name": "X Y", "mobile": "9864012345"}, headers=h)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_confirmed"
    p = api.patch("/me/profile", json={"mobile": "7002012345"}, headers=h)
    assert p.status_code == 200 and p.json()["mobile"] == "7002012345"
    assert api.patch("/me/profile", json={"mobile": "12345"}, headers=h).status_code == 422
    acts = actions(api, "new.officer@example.org")
    for a in (
        "auth.password_changed",
        "profile.confirmed",
        "notification_preferences.changed",
        "profile.updated",
    ):
        assert a in acts, a


# ------------------------------------------------------------------------------------------------ administrators


def test_admin_reset_forces_a_change_and_ends_sessions(api):
    officer = sign_in(api, EDU_OFF, PW)
    admin = sign_in(api, USERS["edu_admin"][0], PW)
    uid = str(user_row(api, EDU_OFF).id)
    weak = api.post(f"/admin/users/{uid}/password", json={"password": "short"}, headers=auth(admin))
    assert weak.status_code == 422 and weak.json()["detail"]["code"] == "weak_password"
    r = api.post(f"/admin/users/{uid}/password", json={"password": "reset-by-admin-1"}, headers=auth(admin))
    assert r.status_code == 204
    assert user_row(api, EDU_OFF).must_change_password is True
    assert live_tokens(api, EDU_OFF) == 0
    assert api.post("/auth/refresh", json={"refresh_token": officer["refresh_token"]}).status_code == 401
    assert sign_in(api, EDU_OFF, "reset-by-admin-1")["next_step"] == "change_password"
    with api.world.Session() as s:
        after = s.scalar(
            sa.text(
                "select after from audit_log where action = 'user.set_password' order by created_at desc limit 1"
            )
        )
    assert after == {"must_change": True}


def test_admin_corrects_an_email(api):
    officer = sign_in(api, EDU_OFF, PW)
    admin = sign_in(api, USERS["edu_admin"][0], PW)
    uid = str(user_row(api, EDU_OFF).id)
    dup = api.patch(f"/admin/users/{uid}", json={"email": USERS["edu_off2"][0]}, headers=auth(admin))
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "email_taken"
    outsider = sign_in(api, USERS["health_admin"][0], PW)
    out = api.patch(f"/admin/users/{uid}", json={"email": "x@example.org"}, headers=auth(outsider))
    assert out.status_code == 404  # outside the caller's scope the login is not even visible
    ok = api.patch(f"/admin/users/{uid}", json={"email": "Off1.New@Example.org"}, headers=auth(admin))
    assert ok.status_code == 200 and ok.json()["email"] == "off1.new@example.org"
    notice = api.mailer.sent[-1]
    assert (
        notice.to == EDU_OFF
        and "o***@example.org" in notice.text
        and "off1.new@example.org" not in notice.text
    )
    assert live_tokens(api, "off1.new@example.org") == 0
    assert api.post("/auth/refresh", json={"refresh_token": officer["refresh_token"]}).status_code == 401
    assert "user.email_changed" in actions(api, "off1.new@example.org")
    assert sign_in(api, "off1.new@example.org", PW)["next_step"] == "ready"
    root = sign_in(api, USERS["root"][0], PW)
    root_id = str(user_row(api, USERS["root"][0]).id)
    r = api.patch(f"/admin/users/{root_id}", json={"email": "root2@example.org"}, headers=auth(root))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "super_admin_cli_only"


def test_disabling_a_login_ends_its_sessions(api):
    officer = sign_in(api, EDU_OFF, PW)
    admin = sign_in(api, USERS["edu_admin"][0], PW)
    uid = str(user_row(api, EDU_OFF).id)
    assert api.post(f"/admin/users/{uid}/disable", headers=auth(admin)).status_code == 200
    assert live_tokens(api, EDU_OFF) == 0
    assert api.get("/me", headers=auth(officer)).status_code == 401


# ------------------------------------------------------------------------------------------------ audit


def test_audit_rows_hold_no_code_password_or_token(api):
    tok = sign_in(api, EDU_OFF, PW, device_label="Laptop")
    sign_code = last_code(api, EDU_OFF)
    api.post("/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    api.post("/auth/login", json={"email": EDU_OFF, "password": "wrong-password-1"})
    api.post("/auth/password-reset/request", json={"email": USERS["edu_off2"][0]})
    reset_code = last_code(api, USERS["edu_off2"][0])
    with api.world.Session() as s:
        rows = s.execute(sa.text("select action, before::text, after::text from audit_log")).all()
    assert {"auth.otp_sent", "auth.login", "auth.new_device", "auth.login_failed"} <= {r[0] for r in rows}
    blob = " ".join(f"{r[1]} {r[2]}" for r in rows)
    for secret in (sign_code, reset_code, PW, tok["access_token"], tok["refresh_token"], tok["device_token"]):
        assert secret not in blob
