"""The code and session services of design `otp-and-profile` against the database: one live code per login and
purpose, purposes kept apart, the hash never the code, the password set by someone else and by the person, and
the CLI's sign-out."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from aslms.core.config import Settings
from aslms.domain.org import OtpPurpose, RefreshToken, UserDevice
from aslms.services import auth, otp
from aslms.services.audit import Actor
from aslms.services.mailer import RecordingMailer
from aslms.services.passwords import WeakPassword
from aslms.services.users import set_password
from tests.db.world import PW

SETTINGS = Settings(_env_file=None, aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters")
CLIENT = auth.Client(ip="10.1.2.3", user_agent="pytest")


def test_one_live_code_per_purpose_and_purposes_apart(world, monkeypatch):
    offset = {"s": 0}
    monkeypatch.setattr(otp, "utcnow", lambda: datetime.now(UTC) + timedelta(seconds=offset["s"]))
    mailer = RecordingMailer()
    with world.Session() as s:
        user = world.user(s, "edu_off1")
        first = otp.issue(s, user, OtpPurpose.LOGIN, mailer, SETTINGS)
        reset = otp.issue(s, user, OtpPurpose.PASSWORD_RESET, mailer, SETTINGS)  # another purpose: no wait
        offset["s"] = 121
        second = otp.issue(s, user, OtpPurpose.LOGIN, mailer, SETTINGS)
        s.refresh(first)
        assert first.consumed_at is not None and second.consumed_at is None and reset.consumed_at is None
        code = re.search(r"\b(\d{6})\b", mailer.sent[-1].text).group(1)
        assert code not in second.code_hash and len(second.code_hash) == 64
        # a sign-in code does not reset a password, and the other way round
        wrong_purpose = otp.verify(s, second.id, code, (OtpPurpose.PASSWORD_RESET,), SETTINGS)
        assert not wrong_purpose.ok and wrong_purpose.reason == "unknown"
        ok = otp.verify(s, second.id, code, (OtpPurpose.LOGIN,), SETTINGS)
        assert ok.ok and ok.user.id == user.id
        again = otp.verify(s, second.id, code, (OtpPurpose.LOGIN,), SETTINGS)
        assert not again.ok and again.reason == "spent"
        assert otp.verify(s, "not-a-uuid", code, (OtpPurpose.LOGIN,), SETTINGS).reason == "unknown"
        s.rollback()


def test_set_password_by_someone_else_and_by_self(world):
    with world.Session() as s:
        user = world.user(s, "edu_off1")
        s.add(
            RefreshToken(
                user_id=user.id, token_hash="a" * 64, expires_at=datetime.now(UTC) + timedelta(days=1)
            )
        )
        s.flush()
        set_password(s, Actor.system("test"), user, "someone-else-1")
        assert user.must_change_password is True and user.password_changed_at is not None
        live = s.scalar(
            sa.select(sa.func.count())
            .select_from(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        )
        assert live == 0
        set_password(s, Actor.system("test"), user, "my-own-choice-2", by_self=True)
        assert user.must_change_password is False
        with pytest.raises(WeakPassword):
            set_password(s, Actor.system("test"), user, "my-own-choice-2", by_self=True)  # same as current
        s.rollback()


def test_cli_sign_out_revokes_tokens_and_devices(world):
    mailer = RecordingMailer()
    with world.Session() as s:
        user = world.user(s, "edu_off1")
        step = auth.start_login(s, user.email, PW, CLIENT, mailer, SETTINGS)
        code = re.search(r"\b(\d{6})\b", mailer.sent[-1].text).group(1)
        signed = auth.complete_login(s, step.challenge_id, code, CLIENT, mailer, SETTINGS)
        assert signed.device_token and signed.device_id
        counts = auth.sign_out_everywhere(s, Actor.system("cli"), user)
        assert counts == {"tokens_revoked": 1, "devices_revoked": 1}
        device = s.get(UserDevice, signed.device_id)
        s.refresh(device)
        assert device.revoked_at is not None and device.first_ip == "10.1.2.3"
        with pytest.raises(auth.RefreshInvalid):
            auth.refresh(s, signed.refresh_token, CLIENT, SETTINGS)
        assert s.scalar(sa.text("select count(*) from audit_log where action = 'auth.signed_out'")) == 1
        s.rollback()
