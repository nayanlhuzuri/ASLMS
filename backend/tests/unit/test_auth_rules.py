"""The rules of design `otp-and-profile` without a database: code format and the HMAC check, e-mail and IP masks,
the password policy, mobile normalisation, the order of the first-sign-in steps, the access-token age check at
whole seconds, and the mail readiness rule."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from aslms.api.security import issued_before
from aslms.core.config import Settings
from aslms.services import otp
from aslms.services.auth import mask_ip, next_step
from aslms.services.mailer import ConsoleMailer, RecordingMailer, UnconfiguredMailer
from aslms.services.passwords import WeakPassword, check_policy, hash_password, verify_password
from aslms.services.profile import ProfileError, normalise_mobile

SETTINGS = Settings(_env_file=None, aslms_jwt_secret="unit-secret-of-at-least-thirty-two-chars")


def test_codes_are_six_digits_and_vary():
    codes = {otp.new_code() for _ in range(200)}
    assert all(re.fullmatch(r"[0-9]{6}", c) for c in codes)
    assert len(codes) > 150  # from secrets.randbelow, not a fixed sequence


def test_code_hash_is_keyed_and_checked_in_constant_time():
    h = otp.code_hash("123456", SETTINGS)
    assert len(h) == 64 and "123456" not in h
    import hashlib

    assert h != hashlib.sha256(b"123456").hexdigest()  # not a plain hash: needs the secret
    assert otp.code_matches("123456", h, SETTINGS)
    assert not otp.code_matches("123457", h, SETTINGS)
    other = Settings(_env_file=None, aslms_jwt_secret="another-secret-of-at-least-thirty-two-chars")
    assert not otp.code_matches("123456", h, other)


def test_masks():
    assert otp.mask_email("nayan.semt@gmail.com") == "n***@gmail.com"
    assert otp.mask_email("broken") == "***"
    assert mask_ip("10.2.3.4") == "10.2.*.*"
    assert mask_ip("2001:db8::1") == "2001:0db8:*"
    assert mask_ip("testclient") == "unknown" and mask_ip(None) == "unknown"


@pytest.mark.parametrize(
    "password",
    ["short1", "onlyletterslong", "1234567890123", "", "x" * 201 + "1"],
)
def test_password_policy_refuses(password):
    with pytest.raises(WeakPassword):
        check_policy(password)


def test_password_policy_accepts_and_refuses_the_current_one():
    check_policy("long-enough-9")
    check_policy("पासवर्ड-लंबा-है-1")  # any letter counts
    current = hash_password("long-enough-9")
    assert verify_password(current, "long-enough-9")
    with pytest.raises(WeakPassword, match="differ"):
        check_policy("long-enough-9", current)
    check_policy("long-enough-10", current)
    with pytest.raises(WeakPassword):
        hash_password("no-digits-here")


@pytest.mark.parametrize(
    "raw",
    ["9864012345", "+91 98640 12345", "+91-9864012345", "919864012345", "09864012345", "(986) 401-2345"],
)
def test_mobile_normalised(raw):
    assert normalise_mobile(raw) == "9864012345"


@pytest.mark.parametrize(
    "raw", ["", None, "5864012345", "98640123", "98640123456", "+1 9864012345", "abcdefghij"]
)
def test_mobile_refused(raw):
    with pytest.raises(ProfileError) as e:
        normalise_mobile(raw)
    assert e.value.code == "invalid_mobile"


def test_first_sign_in_order_password_then_profile():
    u = SimpleNamespace(must_change_password=True, must_confirm_profile=True)
    assert next_step(u) == "change_password"
    u.must_change_password = False
    assert next_step(u) == "confirm_profile"
    u.must_confirm_profile = False
    assert next_step(u) == "ready"


def test_access_token_age_check_at_whole_seconds():
    changed = datetime(2026, 10, 7, 12, 0, 0, 700_000, tzinfo=UTC)
    second = int(datetime(2026, 10, 7, 12, 0, 0, tzinfo=UTC).timestamp())
    assert issued_before(second - 1, changed)  # the second before: refused
    assert not issued_before(second, changed)  # the same second: kept (the fresh pair of a self-change)
    assert not issued_before(second + 5, changed)
    assert not issued_before(0, None)  # never changed


def test_mail_readiness():
    otp.ensure_mail_ready(RecordingMailer(), SETTINGS)
    otp.ensure_mail_ready(ConsoleMailer(), SETTINGS)  # dev: allowed (no code arrives; use the sandbox)
    prod = Settings(
        _env_file=None, aslms_jwt_secret="unit-secret-of-at-least-thirty-two-chars", app_env="prod"
    )
    with pytest.raises(otp.MailNotConfigured):
        otp.ensure_mail_ready(ConsoleMailer(), prod)
    with pytest.raises(otp.MailNotConfigured):
        otp.ensure_mail_ready(UnconfiguredMailer("MAIL_BACKEND=api needs SMTP_FROM"), SETTINGS)


def test_no_device_trust_setting():
    """The owner's answer of 7 Oct 2026: a code at every sign-in; no setting lets a device skip it."""
    assert not any("trust" in name for name in Settings.model_fields)
    assert SETTINGS.otp_ttl_minutes == 10 and SETTINGS.otp_max_attempts == 5
    assert SETTINGS.otp_resend_seconds == 120 and SETTINGS.otp_max_per_hour == 10
    assert SETTINGS.login_max_failures == 10 and SETTINGS.login_lock_minutes == 15
