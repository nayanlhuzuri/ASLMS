"""Negative paths and edge cases of design `otp-and-profile` that `test_api_auth.py` does not reach: the lock
counted from wrong codes and refusing a live code, purposes kept apart, a device token of another login, mail
failures on the notice and on the reset request, a login disabled between the two steps, reset-code attempts,
the gate's exempt and refused endpoints, a self-change, logout then reuse, refresh edge cases, input
validation, and the administrator paths' refusals. Every refused step's counter or revocation is read back in a
new session (decision 5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from aslms.domain.org import Office, RefreshToken, User, UserDevice
from aslms.domain.reference import OfficeKind, Role
from aslms.services import offices
from aslms.services.audit import Actor
from aslms.services.mailer import MailError, RecordingMailer
from aslms.services.users import create_user
from tests.db.auth_support import last_code, sign_in, start
from tests.db.test_api_auth import (
    EDU_OFF,
    Clock,
    actions,
    auth,
    codes,
    live_tokens,
    make,
    user_row,
)
from tests.db.world import PW, USERS

OFF2 = USERS["edu_off2"][0]
NEW_PW = "brand-new-pass-1"


@pytest.fixture()
def api(world):
    client = make(world)
    yield client
    client.__exit__(None, None, None)


def wrong_of(right: str) -> str:
    return "000000" if right != "000000" else "111111"


def set_flags(api, email: str, **values) -> None:
    with api.world.Session() as s:
        s.execute(sa.update(User).where(User.email == email).values(**values))
        s.commit()


def audit_after(api, action: str) -> list[dict]:
    with api.world.Session() as s:
        return list(
            s.scalars(
                sa.text("select after from audit_log where action = :a order by created_at"), {"a": action}
            )
        )


# ------------------------------------------------------------------------------------------------ lock


def test_wrong_codes_count_towards_the_lock_and_the_lock_refuses_reset_and_resend(api, monkeypatch):
    clock = Clock(monkeypatch)
    reset = api.post("/auth/password-reset/request", json={"email": EDU_OFF}).json()
    reset_code = last_code(api, EDU_OFF)
    for _ in range(2):  # two sign-in challenges, five wrong codes each: ten otp_failed rows
        step = start(api, EDU_OFF, PW).json()
        bad = wrong_of(last_code(api, EDU_OFF))
        for _ in range(5):
            r = api.post("/auth/otp/verify", json={"challenge_id": step["challenge_id"], "code": bad})
            assert r.status_code == 401
        clock.move(seconds=121)
    assert actions(api, EDU_OFF).count("auth.otp_failed") == 10
    assert actions(api, EDU_OFF).count("auth.locked") == 1
    # locked: the password alone, a resend and the reset confirmation are all refused, the password is unchanged
    locked = api.post("/auth/login", json={"email": EDU_OFF, "password": PW})
    assert locked.status_code == 429 and locked.json()["detail"]["code"] == "locked"
    again = api.post("/auth/otp/resend", json={"challenge_id": step["challenge_id"]})
    assert again.status_code == 429 and again.json()["detail"]["code"] == "locked"
    confirm = api.post(
        "/auth/password-reset/confirm",
        json={"challenge_id": reset["challenge_id"], "code": reset_code, "new_password": NEW_PW},
    )
    assert confirm.status_code == 429 and confirm.json()["detail"]["code"] == "locked"
    assert 0 < confirm.json()["detail"]["retry_after"] <= 15 * 60
    clock.move(minutes=16)
    assert sign_in(api, EDU_OFF, PW)["next_step"] == "ready"  # the old password still works


def test_a_locked_login_refuses_a_live_code_even_when_right(api):
    step = start(api, EDU_OFF, PW).json()
    right = last_code(api, EDU_OFF)
    for _ in range(10):
        assert (
            api.post("/auth/login", json={"email": EDU_OFF, "password": "wrong-password-1"}).status_code
            == 401
        )
    r = api.post("/auth/otp/verify", json={"challenge_id": step["challenge_id"], "code": right})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "locked"
    assert r.headers["Retry-After"]
    assert live_tokens(api, EDU_OFF) == 0
    assert all(c.consumed_at is None for c in codes(api, EDU_OFF))  # a refused step spends nothing


def test_wrong_current_password_on_self_change_counts_and_locks(api):
    tok = sign_in(api, EDU_OFF, PW)
    for _ in range(10):
        r = api.post(
            "/me/password",
            json={"current_password": "wrong-password-1", "new_password": NEW_PW},
            headers=auth(tok),
        )
        assert r.status_code == 401
    assert actions(api, EDU_OFF).count("auth.login_failed") == 10  # committed with each 401
    r = api.post("/me/password", json={"current_password": PW, "new_password": NEW_PW}, headers=auth(tok))
    assert r.status_code == 429 and r.json()["detail"]["code"] == "locked"
    assert api.post("/auth/login", json={"email": EDU_OFF, "password": PW}).status_code == 429


def test_unknown_email_is_never_counted_or_locked(api):
    for _ in range(12):
        r = api.post("/auth/login", json={"email": "nobody@example.org", "password": "wrong-password-1"})
        assert r.status_code == 401 and r.json()["detail"]["code"] == "invalid_credentials"
    with api.world.Session() as s:
        assert s.scalar(sa.text("select count(*) from audit_log where action like 'auth.%'")) == 0
    assert api.mailer.sent == []


# ------------------------------------------------------------------------------------------------ purposes and codes


def test_reset_and_sign_in_codes_are_not_interchangeable(api):
    reset = api.post("/auth/password-reset/request", json={"email": EDU_OFF}).json()
    reset_code = last_code(api, EDU_OFF)
    r = api.post("/auth/otp/verify", json={"challenge_id": reset["challenge_id"], "code": reset_code})
    assert r.status_code == 401 and "access_token" not in r.text  # a reset code never signs in
    assert live_tokens(api, EDU_OFF) == 0
    step = start(api, EDU_OFF, PW).json()
    login_code = last_code(api, EDU_OFF)
    r = api.post(
        "/auth/password-reset/confirm",
        json={"challenge_id": step["challenge_id"], "code": login_code, "new_password": NEW_PW},
    )
    assert r.status_code == 401  # a sign-in code never resets a password
    assert api.post("/auth/login", json={"email": EDU_OFF, "password": NEW_PW}).status_code == 401
    # both codes are still usable for their own purpose
    assert (
        api.post(
            "/auth/otp/verify", json={"challenge_id": step["challenge_id"], "code": login_code}
        ).status_code
        == 200
    )
    ok = api.post(
        "/auth/password-reset/confirm",
        json={"challenge_id": reset["challenge_id"], "code": reset_code, "new_password": NEW_PW},
    )
    assert ok.status_code == 204


def test_reset_code_attempts_survive_and_the_fifth_spends_it(api):
    reset = api.post("/auth/password-reset/request", json={"email": EDU_OFF}).json()
    right = last_code(api, EDU_OFF)
    bad = wrong_of(right)
    body = {"challenge_id": reset["challenge_id"], "new_password": NEW_PW}
    for n in range(1, 6):
        r = api.post("/auth/password-reset/confirm", json={**body, "code": bad})
        assert r.status_code == 401 and r.json()["detail"]["code"] == "otp_invalid"
        assert "attempts_left" not in r.json()["detail"]  # a reset challenge discloses nothing
        assert codes(api, EDU_OFF)[-1].attempts == n  # committed with the 401
    assert codes(api, EDU_OFF)[-1].consumed_at is not None
    r = api.post("/auth/password-reset/confirm", json={**body, "code": right})
    assert r.status_code == 401  # spent: the right code no longer works
    assert api.post("/auth/login", json={"email": EDU_OFF, "password": PW}).status_code == 200
    assert actions(api, EDU_OFF).count("auth.otp_failed") == 5


def test_reset_code_is_single_use_and_expires(api, monkeypatch):
    clock = Clock(monkeypatch)
    first = api.post("/auth/password-reset/request", json={"email": EDU_OFF}).json()
    code = last_code(api, EDU_OFF)
    body = {"challenge_id": first["challenge_id"], "code": code, "new_password": NEW_PW}
    assert api.post("/auth/password-reset/confirm", json=body).status_code == 204
    again = api.post("/auth/password-reset/confirm", json={**body, "new_password": "another-pass-22"})
    assert again.status_code == 401  # used once
    clock.move(seconds=121)
    second = api.post("/auth/password-reset/request", json={"email": EDU_OFF}).json()
    code2 = last_code(api, EDU_OFF)
    clock.move(minutes=11)
    r = api.post(
        "/auth/password-reset/confirm",
        json={"challenge_id": second["challenge_id"], "code": code2, "new_password": "another-pass-22"},
    )
    assert r.status_code == 401 and r.json()["detail"]["code"] == "otp_invalid"
    assert sign_in(api, EDU_OFF, NEW_PW)["next_step"] == "ready"


def test_reset_request_with_a_failing_mailer_is_neutral(world):
    api = make(world)
    try:
        api.app.state.mailer = RecordingMailer(fail_with=MailError("down"))
        real = api.post("/auth/password-reset/request", json={"email": EDU_OFF})
        unknown = api.post("/auth/password-reset/request", json={"email": "nobody@example.org"})
        assert real.status_code == unknown.status_code == 202
        assert set(real.json()) == set(unknown.json())
        assert [c for c in codes(api, EDU_OFF) if c.consumed_at is None] == []
        assert audit_after(api, "auth.password_reset_requested")[-1] == {
            "sent": False,
            "reason": "mail_failed",
        }
    finally:
        api.__exit__(None, None, None)


def test_a_weak_reset_password_does_not_touch_the_code_or_the_account(api):
    reset = api.post("/auth/password-reset/request", json={"email": EDU_OFF}).json()
    code = last_code(api, EDU_OFF)
    for weak in ("short1", "onlyletterspassword", "1234567890123"):
        r = api.post(
            "/auth/password-reset/confirm",
            json={"challenge_id": reset["challenge_id"], "code": code, "new_password": weak},
        )
        assert r.status_code == 422 and r.json()["detail"]["code"] == "weak_password"
    assert codes(api, EDU_OFF)[-1].attempts == 0 and codes(api, EDU_OFF)[-1].consumed_at is None
    assert sign_in(api, EDU_OFF, PW)["next_step"] == "ready"


def test_login_disabled_between_the_steps_gets_no_tokens(api):
    step = start(api, EDU_OFF, PW).json()
    code = last_code(api, EDU_OFF)
    set_flags(api, EDU_OFF, is_active=False)
    r = api.post("/auth/otp/verify", json={"challenge_id": step["challenge_id"], "code": code})
    assert r.status_code == 401 and "access_token" not in r.text
    assert live_tokens(api, EDU_OFF) == 0
    with api.world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(UserDevice)) == 0
    # a disabled login cannot ask for a resend of that challenge either
    assert api.post("/auth/otp/resend", json={"challenge_id": step["challenge_id"]}).status_code == 401


def test_input_validation_costs_no_attempt(api):
    step = start(api, EDU_OFF, PW).json()
    for bad in ("12345", "1234567", "abcdef", "12 456", ""):
        r = api.post("/auth/otp/verify", json={"challenge_id": step["challenge_id"], "code": bad})
        assert r.status_code == 422
    assert (
        api.post("/auth/otp/verify", json={"challenge_id": "not-a-uuid", "code": "123456"}).status_code == 422
    )
    assert api.post("/auth/otp/resend", json={"challenge_id": "nope"}).status_code == 422
    assert api.post("/auth/login", json={"email": "not-an-email", "password": PW}).status_code == 422
    assert api.post("/auth/login", json={"email": EDU_OFF, "password": ""}).status_code == 422
    assert codes(api, EDU_OFF)[-1].attempts == 0
    assert (
        api.post(
            "/auth/otp/verify", json={"challenge_id": step["challenge_id"], "code": last_code(api, EDU_OFF)}
        ).status_code
        == 200
    )


def test_step_one_answer_masks_the_address_and_the_audit_row_holds_no_full_address(api):
    r = start(api, EDU_OFF, PW)
    assert EDU_OFF not in r.text and "@example.org" in r.json()["sent_to"] and "*" in r.json()["sent_to"]
    sent = audit_after(api, "auth.otp_sent")[-1]
    assert sent["purpose"] == "login" and EDU_OFF not in str(sent) and "*" in sent["sent_to"]


# ------------------------------------------------------------------------------------------------ devices


def test_another_logins_device_token_is_unknown_and_untouched(api):
    first = sign_in(api, EDU_OFF, PW, device_label="Office PC")
    token = first["device_token"]
    with api.world.Session() as s:
        before = s.scalars(sa.select(UserDevice)).one()
        seen, verified, before_id = before.last_seen_at, before.verified_at, before.id
    second = sign_in(api, OFF2, PW, device_token=token)
    assert second["device_token"] and second["device_token"] != token  # a new device for the second login
    assert [m for m in api.mailer.sent if m.subject == "New sign-in to ASLMS" and m.to == OFF2]
    with api.world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(UserDevice)) == 2
        again = s.get(UserDevice, before_id)
        # the first login's record was not refreshed by the other login
        assert (again.last_seen_at, again.verified_at) == (seen, verified)
    listed = api.get("/me/devices", headers={**auth(second), "X-Device-Token": token}).json()
    assert (
        len(listed) == 1 and listed[0]["current"] is False
    )  # only own devices, the foreign token names none
    other = api.get("/me/devices", headers=auth(first)).json()
    assert len(other) == 1 and other[0]["label"] == "Office PC"


def test_a_failing_new_device_notice_never_blocks_the_sign_in(world):
    class NoticeFails(RecordingMailer):
        def send(self, to, subject, text, html=None):
            if subject == "New sign-in to ASLMS":
                raise MailError("mailtrap api answered 500")
            return super().send(to, subject, text, html)

    api = make(world)
    try:
        api.app.state.mailer = NoticeFails()
        tok = sign_in(api, EDU_OFF, PW)
        assert tok["access_token"] and tok["device_token"] and tok["next_step"] == "ready"
        assert "auth.new_device" in actions(api, EDU_OFF) and "auth.login" in actions(api, EDU_OFF)
    finally:
        api.__exit__(None, None, None)


def test_devices_cannot_be_revoked_twice_or_by_unknown_id_and_need_a_token(api):
    tok = sign_in(api, EDU_OFF, PW)
    dev = api.get("/me/devices", headers=auth(tok)).json()[0]["id"]
    assert api.post(f"/me/devices/{dev}/revoke").status_code == 401
    assert api.get("/me/devices").status_code == 401
    assert (
        api.post("/me/devices/0192b3c4-0000-7000-8000-000000000000/revoke", headers=auth(tok)).status_code
        == 404
    )
    assert api.post(f"/me/devices/{dev}/revoke", headers=auth(tok)).status_code == 204
    assert api.post(f"/me/devices/{dev}/revoke", headers=auth(tok)).status_code == 204  # idempotent
    assert actions(api, EDU_OFF).count("auth.device_revoked") == 1  # and audited once


# ------------------------------------------------------------------------------------------------ refresh


def test_logout_then_the_same_refresh_token_is_refused_without_ending_other_sessions(api):
    a = sign_in(api, EDU_OFF, PW)
    b = sign_in(api, EDU_OFF, PW)
    r = api.post("/auth/logout", json={"refresh_token": a["refresh_token"]}, headers=auth(a))
    assert r.status_code == 204 and "auth.logout" in actions(api, EDU_OFF)
    again = api.post("/auth/refresh", json={"refresh_token": a["refresh_token"]})
    assert again.status_code == 401 and again.json()["detail"]["code"] == "refresh_invalid"
    assert "auth.refresh_reused" not in actions(api, EDU_OFF)
    # design decision 10 treats only a *rotated* token as theft; a logged-out token must not end session b
    assert api.post("/auth/refresh", json={"refresh_token": b["refresh_token"]}).status_code == 200


def test_refresh_of_an_expired_token_and_of_a_disabled_login(api):
    a = sign_in(api, EDU_OFF, PW)
    with api.world.Session() as s:
        s.execute(
            sa.update(RefreshToken)
            .where(RefreshToken.user_id == user_row(api, EDU_OFF).id)
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        s.commit()
    r = api.post("/auth/refresh", json={"refresh_token": a["refresh_token"]})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "refresh_invalid"
    b = sign_in(api, OFF2, PW)
    set_flags(api, OFF2, is_active=False)
    r = api.post("/auth/refresh", json={"refresh_token": b["refresh_token"]})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "refresh_invalid"
    assert api.get("/me", headers=auth(b)).status_code == 401


def test_refresh_keeps_the_device_and_reports_the_next_step(api):
    tok = sign_in(api, EDU_OFF, PW, device_label="Laptop")
    set_flags(api, EDU_OFF, must_confirm_profile=True)
    r = api.post("/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 200 and r.json()["next_step"] == "confirm_profile"
    with api.world.Session() as s:
        device_ids = set(
            s.scalars(
                sa.select(RefreshToken.device_id).where(RefreshToken.user_id == user_row(api, EDU_OFF).id)
            )
        )
    assert len(device_ids) == 1 and None not in device_ids  # the rotated token stays tied to the device


# ------------------------------------------------------------------------------------------------ the gate


def test_gate_exempt_and_refused_endpoints_while_the_password_must_change(api):
    set_flags(api, EDU_OFF, must_change_password=True, must_confirm_profile=True)
    tok = sign_in(api, EDU_OFF, PW)
    assert tok["next_step"] == "change_password"
    h = auth(tok)
    for path in ("/me", "/me/profile", "/me/notification-preferences"):
        assert api.get(path, headers=h).status_code == 200, path
    put = api.put("/me/notification-preferences", json={"email": {"digest": "none"}}, headers=h)
    assert put.status_code == 200, put.text
    for method, path in (
        ("get", "/cases"),
        ("get", "/me/devices"),
        ("get", "/admin/users"),
        ("get", "/alerts"),
        ("patch", "/me/profile"),
    ):
        r = getattr(api, method)(
            path, headers=h, **({"json": {"mobile": "9864012345"}} if method == "patch" else {})
        )
        assert r.status_code == 403 and r.json()["detail"]["code"] == "password_change_required", path
    refreshed = api.post("/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert refreshed.status_code == 200 and refreshed.json()["next_step"] == "change_password"
    out = api.post("/auth/logout", json={"refresh_token": refreshed.json()["refresh_token"]}, headers=h)
    assert out.status_code == 204
    # no token at all is 401, not 403
    assert api.get("/me").status_code == 401 and api.get("/cases").status_code == 401


def test_gate_when_only_the_profile_is_unconfirmed(api):
    set_flags(api, EDU_OFF, must_change_password=False, must_confirm_profile=True)
    tok = sign_in(api, EDU_OFF, PW)
    assert tok["next_step"] == "confirm_profile"
    h = auth(tok)
    r = api.get("/cases", headers=h)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "profile_confirmation_required"
    assert api.get("/me/profile", headers=h).status_code == 200
    for bad in (
        {"full_name": "Edu Off One"},
        {"full_name": "Edu Off One", "mobile": "5864012345"},
        {"full_name": "E", "mobile": "9864012345"},
    ):
        r = api.post("/me/profile/confirm", json=bad, headers=h)
        assert r.status_code == 422, bad
    assert user_row(api, EDU_OFF).must_confirm_profile is True  # nothing half-confirmed
    ok = api.post("/me/profile/confirm", json={"full_name": "Edu Off One", "mobile": "9864012345"}, headers=h)
    assert ok.status_code == 200
    assert api.get("/cases", headers=h).status_code == 200
    # a later sign-in is ready
    assert sign_in(api, EDU_OFF, PW)["next_step"] == "ready"


def test_confirmed_profile_edits_are_audited_with_before_and_after(api):
    set_flags(api, EDU_OFF, must_confirm_profile=True)
    h = auth(sign_in(api, EDU_OFF, PW))
    api.post("/me/profile/confirm", json={"full_name": "Edu Off One", "mobile": "9864012345"}, headers=h)
    with api.world.Session() as s:
        row = s.execute(
            sa.text("select before, after from audit_log where action = 'profile.confirmed'")
        ).one()
    assert row.before["must_confirm_profile"] is True and row.after["must_confirm_profile"] is False
    assert row.after["mobile"] == "9864012345" and row.after["profile_confirmed_at"]
    unchanged = api.patch("/me/profile", json={"mobile": "9864012345"}, headers=h)
    assert unchanged.status_code == 200
    with api.world.Session() as s:
        assert s.scalar(sa.text("select count(*) from audit_log where action = 'profile.updated'")) == 0
    for bad in ({"mobile": ""}, {"full_name": ""}, {"full_name": "X"}):
        assert api.patch("/me/profile", json=bad, headers=h).status_code == 422, bad
    assert user_row(api, EDU_OFF).mobile == "9864012345"


# ------------------------------------------------------------------------------------------------ self change


def test_self_change_refuses_the_same_password_ends_other_sessions_and_keeps_this_device(api):
    a = sign_in(api, EDU_OFF, PW, device_label="PC")
    b = sign_in(api, EDU_OFF, PW)
    same = api.post("/me/password", json={"current_password": PW, "new_password": PW}, headers=auth(a))
    assert same.status_code == 422 and same.json()["detail"]["code"] == "weak_password"
    assert (
        api.post("/auth/refresh", json={"refresh_token": b["refresh_token"]}).status_code == 200
    )  # nothing changed
    b2 = api.post("/auth/refresh", json={"refresh_token": b["refresh_token"]})  # now rotated: theft, ends all
    assert b2.status_code == 401
    c = sign_in(api, EDU_OFF, PW, device_token=a["device_token"])
    changed = api.post(
        "/me/password",
        json={"current_password": PW, "new_password": NEW_PW, "device_token": a["device_token"]},
        headers=auth(c),
    )
    assert changed.status_code == 200 and changed.json()["next_step"] == "ready"
    assert user_row(api, EDU_OFF).must_change_password is False
    assert api.get("/cases", headers=auth(changed.json())).status_code == 200  # the fresh pair works at once
    assert api.post("/auth/refresh", json={"refresh_token": c["refresh_token"]}).status_code == 401
    assert (
        api.post("/auth/refresh", json={"refresh_token": changed.json()["refresh_token"]}).status_code == 200
    )
    assert api.post("/auth/login", json={"email": EDU_OFF, "password": PW}).status_code == 401
    assert "auth.password_changed" in actions(api, EDU_OFF)


def test_super_admin_may_reset_their_own_password_by_email(api):
    root = USERS["root"][0]
    reset = api.post("/auth/password-reset/request", json={"email": root}).json()
    r = api.post(
        "/auth/password-reset/confirm",
        json={"challenge_id": reset["challenge_id"], "code": last_code(api, root), "new_password": NEW_PW},
    )
    assert r.status_code == 204
    assert sign_in(api, root, NEW_PW)["next_step"] == "ready"


# ------------------------------------------------------------------------------------------------ administrators


def test_admin_paths_refuse_callers_without_the_function_and_weak_passwords(api):
    officer = sign_in(api, EDU_OFF, PW)
    target = str(user_row(api, OFF2).id)
    r = api.patch(f"/admin/users/{target}", json={"email": "x@example.org"}, headers=auth(officer))
    assert r.status_code == 403
    r = api.post(f"/admin/users/{target}/password", json={"password": NEW_PW}, headers=auth(officer))
    assert r.status_code == 403
    assert user_row(api, OFF2).email == OFF2 and user_row(api, OFF2).must_change_password is False
    admin = sign_in(api, USERS["edu_admin"][0], PW)
    for weak in ("onlyletterspassword", "1234567890123", "short1"):
        r = api.post(f"/admin/users/{target}/password", json={"password": weak}, headers=auth(admin))
        assert r.status_code == 422 and r.json()["detail"]["code"] == "weak_password", weak
    same = api.post(f"/admin/users/{target}/password", json={"password": PW}, headers=auth(admin))
    assert same.status_code == 422  # not equal to the current password
    assert user_row(api, OFF2).must_change_password is False
    body = {
        "email": "weak.new@example.org",
        "password": "onlyletterspassword",
        "full_name": "Weak New",
        "role": "dept_officer",
        "office_code": "EDU",
    }
    r = api.post("/admin/users", json=body, headers=auth(admin))
    assert 400 <= r.status_code < 500, r.text
    with api.world.Session() as s:
        assert s.scalar(sa.select(User).where(User.email == "weak.new@example.org")) is None


def test_admin_email_change_edge_cases(world):
    class NoticeFails(RecordingMailer):
        def send(self, to, subject, text, html=None):
            if "e-mail was changed" in subject:
                raise MailError("down")
            return super().send(to, subject, text, html)

    api = make(world)
    try:
        api.app.state.mailer = NoticeFails()
        officer = sign_in(api, EDU_OFF, PW)
        admin = sign_in(api, USERS["edu_admin"][0], PW)
        uid = str(user_row(api, EDU_OFF).id)
        bad = api.patch(f"/admin/users/{uid}", json={"email": "not-an-email"}, headers=auth(admin))
        assert bad.status_code == 422
        # the same address (any case) is no change: no audit row, sessions kept
        same = api.patch(f"/admin/users/{uid}", json={"email": EDU_OFF.upper()}, headers=auth(admin))
        assert same.status_code == 200 and same.json()["email"] == EDU_OFF
        assert "user.email_changed" not in actions(api, EDU_OFF)
        assert api.post("/auth/refresh", json={"refresh_token": officer["refresh_token"]}).status_code == 200
        # a failing notice never blocks the change
        ok = api.patch(f"/admin/users/{uid}", json={"email": "moved.off1@example.org"}, headers=auth(admin))
        assert ok.status_code == 200 and ok.json()["email"] == "moved.off1@example.org"
        assert user_row(api, "moved.off1@example.org").password_changed_at is not None
        # the old address no longer signs in; codes go to the new one
        assert api.post("/auth/login", json={"email": EDU_OFF, "password": PW}).status_code == 401
        step = start(api, "moved.off1@example.org", PW)
        assert step.status_code == 200 and last_code(api, "moved.off1@example.org")
        before = audit_after(api, "user.email_changed")
        assert before == [{"email": "moved.off1@example.org"}]
    finally:
        api.__exit__(None, None, None)


def test_admin_cannot_set_a_login_out_of_scope_or_unknown(api):
    admin = sign_in(api, USERS["edu_admin"][0], PW)
    health = str(user_row(api, USERS["health_off"][0]).id)
    r = api.post(f"/admin/users/{health}/password", json={"password": NEW_PW}, headers=auth(admin))
    assert r.status_code == 404
    assert user_row(api, USERS["health_off"][0]).must_change_password is False
    r = api.post(
        "/admin/users/0192b3c4-0000-7000-8000-000000000000/password",
        json={"password": NEW_PW},
        headers=auth(admin),
    )
    assert r.status_code == 404


# ------------------------------------------------------------------------------------------------ creation paths


def test_every_creation_path_makes_a_login_that_must_change_and_confirm(world):
    with world.Session() as s:
        goa = s.scalar(sa.select(Office).where(Office.code == "GOA"))
        dept = Office(
            code="LAW", name="Law", kind=OfficeKind.DEPARTMENT, parent_id=goa.id, path=f"{goa.path}/LAW"
        )
        s.add(dept)
        s.flush()
        plain = create_user(
            s,
            Actor.system("test"),
            email="plain@example.org",
            password="given-by-admin-1",
            full_name="Plain Person",
            role=Role.DEPT_OFFICER,
            office=dept,
        )
        assert plain.must_change_password is True and plain.must_confirm_profile is True
        root = world.user(s, "root")
        first = offices.add_department_admin(
            s,
            access_actor(s, root),
            root,
            dept,
            email="first.admin@example.org",
            password="first-admin-pw-1",
            full_name="First Admin",
        )
        assert first.must_change_password is True and first.must_confirm_profile is True
        assert first.profile_confirmed_at is None and first.password_changed_at is None
        s.rollback()


def access_actor(s, user):
    from aslms.services import access

    return access.actor_for(user)


def test_seed_super_admin_must_change_and_confirm(world, monkeypatch):
    """The `.env` password is a bootstrap secret (design decision 14): the seeded super admin changes it first."""
    from pydantic import SecretStr

    from aslms.services import access_seed
    from aslms.services.seed import SeedReport

    fake = SimpleNamespace(
        aslms_superadmin_email="boot.root@example.org",
        aslms_superadmin_password=SecretStr("bootstrap-pass-1"),
    )
    monkeypatch.setattr(access_seed, "get_settings", lambda: fake)
    with world.Session() as s:
        # a system with no super admin: the world's one is moved to another role inside this rolled-back session
        s.execute(sa.text("UPDATE user_memberships SET role = 'dept_officer' WHERE role = 'super_admin'"))
        holder = access_seed.seed_super_admin(s, SeedReport(), world.office(s, "GOA"))
        assert holder.must_change_password is True and holder.must_confirm_profile is True
        s.rollback()
