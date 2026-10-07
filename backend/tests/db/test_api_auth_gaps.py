"""Design `otp-and-profile`, the cases the first two test files leave open: a refused request that still changes
something (the sign-in routes return their refusals, so the transaction commits), codes that outlive a change of
the credentials or of the mailbox they were sent to, replay, the hourly cap across purposes, the audit set of
decision 17, and the e-mail change that changes nothing."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.org import OtpCode, User
from aslms.services.audit import Actor
from aslms.services.users import set_password
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


@pytest.fixture()
def api(world):
    client = make(world)
    yield client
    client.__exit__(None, None, None)


def pending(api, email: str, **flags) -> None:
    """Puts a fixture login back into a first-sign-in state."""
    with api.world.Session() as s:
        s.execute(sa.update(User).where(User.email == email).values(**flags))
        s.commit()


def audit_count(api, action: str, email: str) -> int:
    with api.world.Session() as s:
        return s.scalar(
            sa.text(
                "select count(*) from audit_log a join users u on u.id = a.entity_id "
                "where a.action = :a and u.email = :e"
            ),
            {"a": action, "e": email},
        )


# ------------------------------------------------------------------------------------ refused but changed


def test_a_refused_profile_patch_changes_nothing(api):
    """`PATCH /me/profile` with a good name and a bad mobile answers 422: the name must not be saved (the refusal
    is returned, not raised, so a half-applied change would be committed without an audit row)."""
    tok = sign_in(api, EDU_OFF, PW)
    before = user_row(api, EDU_OFF)
    r = api.patch("/me/profile", json={"full_name": "Renamed Officer", "mobile": "12345"}, headers=auth(tok))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_mobile"
    after = user_row(api, EDU_OFF)
    assert after.full_name == before.full_name and after.mobile == before.mobile
    assert audit_count(api, "profile.updated", EDU_OFF) == 0


def test_a_refused_confirmation_changes_nothing(api):
    """A confirmation with a bad preference answers 422 and leaves the profile unconfirmed and the preferences
    as they were (the e-mail switch before the bad digest must not stick)."""
    pending(api, EDU_OFF, must_confirm_profile=True, profile_confirmed_at=None)
    tok = sign_in(api, EDU_OFF, PW)
    h = auth(tok)
    prefs_before = api.get("/me/notification-preferences", headers=h).json()
    r = api.post(
        "/me/profile/confirm",
        json={
            "full_name": "Officer One",
            "mobile": "9864012345",
            "notification_preferences": {"email": {"enabled": False, "digest": "weekly"}},
        },
        headers=h,
    )
    assert r.status_code == 422, r.text
    assert api.get("/me/notification-preferences", headers=h).json() == prefs_before
    u = user_row(api, EDU_OFF)
    assert u.must_confirm_profile is True and u.profile_confirmed_at is None
    assert audit_count(api, "profile.confirmed", EDU_OFF) == 0
    # and the same confirmation without the bad preference still works
    ok = api.post("/me/profile/confirm", json={"full_name": "Officer One", "mobile": "9864012345"}, headers=h)
    assert ok.status_code == 200, ok.text


# ------------------------------------------------------------------------------------ codes outliving a change


def test_an_email_change_ends_a_reset_code_sent_to_the_old_mailbox(api):
    """The reset code mailed to the old address must stop working when an administrator corrects the e-mail:
    otherwise whoever holds the old mailbox can still set the password."""
    challenge = api.post("/auth/password-reset/request", json={"email": EDU_OFF}).json()["challenge_id"]
    code = last_code(api, EDU_OFF)
    admin = sign_in(api, USERS["edu_admin"][0], PW)
    uid = str(user_row(api, EDU_OFF).id)
    ok = api.patch(f"/admin/users/{uid}", json={"email": "off1.moved@example.org"}, headers=auth(admin))
    assert ok.status_code == 200, ok.text
    r = api.post(
        "/auth/password-reset/confirm",
        json={"challenge_id": challenge, "code": code, "new_password": "taken-over-pass-1"},
    )
    assert r.status_code == 401, "a code sent to the old mailbox still resets the password"
    assert sign_in(api, "off1.moved@example.org", PW)["next_step"] == "ready"


def test_an_email_change_ends_a_sign_in_code_sent_to_the_old_mailbox(api):
    step = start(api, EDU_OFF, PW).json()
    code = last_code(api, EDU_OFF)
    admin = sign_in(api, USERS["edu_admin"][0], PW)
    uid = str(user_row(api, EDU_OFF).id)
    assert (
        api.patch(
            f"/admin/users/{uid}", json={"email": "off1.moved2@example.org"}, headers=auth(admin)
        ).status_code
        == 200
    )
    r = api.post("/auth/otp/verify", json={"challenge_id": step["challenge_id"], "code": code})
    assert r.status_code == 401, "a sign-in code sent to the old mailbox still gives tokens"


def test_a_password_reset_ends_a_sign_in_challenge_begun_with_the_old_password(api, monkeypatch):
    """Step one passed with the old password; the owner then resets it. The pending code must not complete the
    sign-in (the credential it vouched for no longer exists)."""
    step = start(api, EDU_OFF, PW).json()
    sign_code = last_code(api, EDU_OFF)
    reset = api.post("/auth/password-reset/request", json={"email": EDU_OFF}).json()
    reset_code = last_code(api, EDU_OFF)
    assert reset_code
    from datetime import timedelta

    from aslms.services import users as users_service

    real_now = users_service._now
    monkeypatch.setattr(users_service, "_now", lambda: real_now() + timedelta(seconds=2))
    ok = api.post(
        "/auth/password-reset/confirm",
        json={"challenge_id": reset["challenge_id"], "code": reset_code, "new_password": "brand-new-pass-1"},
    )
    assert ok.status_code == 204, ok.text
    r = api.post("/auth/otp/verify", json={"challenge_id": step["challenge_id"], "code": sign_code})
    assert r.status_code == 401, "a challenge begun with the old password signs in after the reset"


def test_an_administrator_password_reset_ends_a_pending_sign_in_challenge(api):
    step = start(api, EDU_OFF, PW).json()
    sign_code = last_code(api, EDU_OFF)
    admin = sign_in(api, USERS["edu_admin"][0], PW)
    uid = str(user_row(api, EDU_OFF).id)
    r = api.post(f"/admin/users/{uid}/password", json={"password": "reset-by-admin-1"}, headers=auth(admin))
    assert r.status_code == 204
    v = api.post("/auth/otp/verify", json={"challenge_id": step["challenge_id"], "code": sign_code})
    assert v.status_code == 401, "a challenge begun with the replaced password signs in"


def test_a_reset_code_of_a_login_disabled_afterwards_resets_nothing(api):
    challenge = api.post("/auth/password-reset/request", json={"email": EDU_OFF}).json()["challenge_id"]
    code = last_code(api, EDU_OFF)
    admin = sign_in(api, USERS["edu_admin"][0], PW)
    uid = str(user_row(api, EDU_OFF).id)
    assert api.post(f"/admin/users/{uid}/disable", headers=auth(admin)).status_code == 200
    hash_before = user_row(api, EDU_OFF).password_hash
    r = api.post(
        "/auth/password-reset/confirm",
        json={"challenge_id": challenge, "code": code, "new_password": "brand-new-pass-1"},
    )
    assert r.status_code == 401
    assert user_row(api, EDU_OFF).password_hash == hash_before


# ------------------------------------------------------------------------------------ replay and caps


def test_a_used_sign_in_code_cannot_be_used_twice(api):
    step = start(api, EDU_OFF, PW).json()
    code = last_code(api, EDU_OFF)
    body = {"challenge_id": step["challenge_id"], "code": code}
    assert api.post("/auth/otp/verify", json=body).status_code == 200
    again = api.post("/auth/otp/verify", json=body)
    assert again.status_code == 401 and again.json()["detail"]["code"] == "otp_expired"
    assert live_tokens(api, EDU_OFF) == 1


def test_an_unknown_challenge_id_is_refused_alike(api):
    r = api.post(
        "/auth/otp/verify",
        json={"challenge_id": "01a117a4-0000-7000-8000-000000000000", "code": "123456"},
    )
    assert r.status_code == 401 and r.json()["detail"]["code"] == "otp_expired"


def test_the_hourly_cap_counts_codes_of_every_purpose(api, monkeypatch):
    """Ten codes an hour per login across purposes: five sign-in codes and five reset codes, then the next of
    either kind is refused with a wait."""
    clock = Clock(monkeypatch)
    for _ in range(5):
        assert start(api, EDU_OFF, PW).status_code == 200
        r = api.post("/auth/password-reset/request", json={"email": EDU_OFF})
        assert r.status_code == 202
        clock.move(seconds=130)
    assert len(codes(api, EDU_OFF)) == 10
    sent = len(api.mailer.sent)
    refused = api.post("/auth/login", json={"email": EDU_OFF, "password": PW})
    assert refused.status_code == 429 and refused.json()["detail"]["code"] == "too_many_codes"
    assert refused.json()["detail"]["retry_after"] > 0
    api.post("/auth/password-reset/request", json={"email": EDU_OFF})  # neutral, nothing sent
    assert len(api.mailer.sent) == sent and len(codes(api, EDU_OFF)) == 10
    clock.move(hours=1)
    assert api.post("/auth/login", json={"email": EDU_OFF, "password": PW}).status_code == 200


def test_codes_are_stored_hashed_never_plain(api):
    start(api, EDU_OFF, PW)
    code = last_code(api, EDU_OFF)
    with api.world.Session() as s:
        row = s.scalars(sa.select(OtpCode)).first()
        assert row.code_hash != code and len(row.code_hash) == 64 and code not in row.code_hash


# ------------------------------------------------------------------------------------ audit set (decision 17)


def test_every_action_of_decision_17_leaves_an_audit_row(api, monkeypatch):
    from datetime import timedelta

    from aslms.services import users as users_service

    clock = Clock(monkeypatch)
    real_now = users_service._now
    monkeypatch.setattr(users_service, "_now", lambda: real_now() + clock.offset + timedelta(seconds=2))
    # sign in (otp_sent, new_device, login), a wrong password (login_failed), a wrong code (otp_failed)
    tok = sign_in(api, EDU_OFF, PW, device_label="Desk")
    api.post("/auth/login", json={"email": EDU_OFF, "password": "wrong-password-1"})
    clock.move(seconds=130)
    step = start(api, EDU_OFF, PW).json()
    right = last_code(api, EDU_OFF)
    bad = "000000" if right != "000000" else "111111"
    api.post("/auth/otp/verify", json={"challenge_id": step["challenge_id"], "code": bad})
    # profile update, device revoke, logout, refresh reuse
    h = auth(tok)
    assert api.patch("/me/profile", json={"mobile": "7002012345"}, headers=h).status_code == 200
    second = sign_in(api, EDU_OFF, PW, device_label="Phone")
    devices = api.get("/me/devices", headers=h).json()
    phone = next(d for d in devices if d["label"] == "Phone")
    assert api.post(f"/me/devices/{phone['id']}/revoke", headers=h).status_code == 204
    third = sign_in(api, EDU_OFF, PW, device_token=tok["device_token"])
    rotated = api.post("/auth/refresh", json={"refresh_token": third["refresh_token"]}).json()
    api.post("/auth/refresh", json={"refresh_token": third["refresh_token"]})  # reuse
    assert second["refresh_token"] and rotated["refresh_token"]
    tok4 = sign_in(api, EDU_OFF, PW, device_token=tok["device_token"])
    assert (
        api.post(
            "/auth/logout", json={"refresh_token": tok4["refresh_token"]}, headers=auth(tok4)
        ).status_code
        == 204
    )
    # own password change, reset request and reset
    tok5 = sign_in(api, EDU_OFF, PW, device_token=tok["device_token"])
    ch = api.post(
        "/me/password",
        json={"current_password": PW, "new_password": "changed-pass-2", "device_token": tok["device_token"]},
        headers=auth(tok5),
    )
    assert ch.status_code == 200, ch.text
    clock.move(seconds=130)
    reset = api.post("/auth/password-reset/request", json={"email": EDU_OFF}).json()
    rc = last_code(api, EDU_OFF)
    ok = api.post(
        "/auth/password-reset/confirm",
        json={"challenge_id": reset["challenge_id"], "code": rc, "new_password": "reset-pass-3"},
    )
    assert ok.status_code == 204, ok.text
    # administrator: set password, e-mail change
    admin = sign_in(api, USERS["edu_admin"][0], PW)
    uid = str(user_row(api, EDU_OFF).id)
    assert (
        api.post(
            f"/admin/users/{uid}/password", json={"password": "by-admin-pass-4"}, headers=auth(admin)
        ).status_code
        == 204
    )
    assert (
        api.patch(
            f"/admin/users/{uid}", json={"email": "off1.final@example.org"}, headers=auth(admin)
        ).status_code
        == 200
    )
    # the lock: ten more wrong passwords
    for _ in range(10):
        api.post("/auth/login", json={"email": "off1.final@example.org", "password": "wrong-password-1"})
    with api.world.Session() as s:
        seen = set(
            s.scalars(
                sa.text("select distinct action from audit_log where action ~ '^(auth|profile)\\.|^user\\.'")
            )
        )
    expected = {
        "auth.otp_sent",
        "auth.new_device",
        "auth.login",
        "auth.login_failed",
        "auth.otp_failed",
        "auth.locked",
        "auth.refresh_reused",
        "auth.logout",
        "auth.device_revoked",
        "auth.password_changed",
        "auth.password_reset_requested",
        "auth.password_reset",
        "profile.updated",
        "user.email_changed",
        "user.set_password",
    }
    assert expected <= seen, sorted(expected - seen)


def test_the_cli_style_set_password_by_the_system_actor_marks_must_change(world):
    with world.Session() as s:
        user = s.scalar(sa.select(User).where(User.email == EDU_OFF))
        set_password(s, Actor.system("test"), user, "system-set-pass-1")
        s.commit()
    with world.Session() as s:
        user = s.scalar(sa.select(User).where(User.email == EDU_OFF))
        assert user.must_change_password is True and user.password_changed_at is not None


# ------------------------------------------------------------------------------------ e-mail change edge


def test_an_email_change_to_the_same_address_changes_nothing(api):
    officer = sign_in(api, EDU_OFF, PW)
    admin = sign_in(api, USERS["edu_admin"][0], PW)
    uid = str(user_row(api, EDU_OFF).id)
    sent = len(api.mailer.sent)
    r = api.patch(f"/admin/users/{uid}", json={"email": EDU_OFF.upper()}, headers=auth(admin))
    assert r.status_code == 200 and r.json()["email"] == EDU_OFF
    assert live_tokens(api, EDU_OFF) == 1
    assert api.get("/me", headers=auth(officer)).status_code == 200
    assert "user.email_changed" not in actions(api, EDU_OFF)
    assert len(api.mailer.sent) == sent
    assert user_row(api, EDU_OFF).password_changed_at is None


def test_an_email_change_that_is_not_an_address_is_refused(api):
    admin = sign_in(api, USERS["edu_admin"][0], PW)
    uid = str(user_row(api, EDU_OFF).id)
    r = api.patch(f"/admin/users/{uid}", json={"email": "not-an-address"}, headers=auth(admin))
    assert r.status_code == 422
    assert user_row(api, EDU_OFF).email == EDU_OFF


# ------------------------------------------------------------------------------------ logout ownership


def test_logout_with_another_logins_refresh_token_does_not_end_that_session(api):
    mine = sign_in(api, EDU_OFF, PW)
    theirs = sign_in(api, USERS["edu_off2"][0], PW)
    r = api.post("/auth/logout", json={"refresh_token": theirs["refresh_token"]}, headers=auth(mine))
    assert r.status_code == 204
    assert live_tokens(api, USERS["edu_off2"][0]) == 1
    assert api.post("/auth/refresh", json={"refresh_token": theirs["refresh_token"]}).status_code == 200
