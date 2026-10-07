"""Signing in from the API tests (design `otp-and-profile`, "Tests"): `POST /auth/login`, the code read from the
`RecordingMailer` on `app.state.mailer` (installed when missing), then `POST /auth/otp/verify`.

A test that signs the same login in twice inside the two-minute resend wait would get 429; the helper then moves
that login's earlier codes back by an hour (the clock, not the rule) and asks again."""

from __future__ import annotations

import re

import sqlalchemy as sa
from fastapi.testclient import TestClient

from aslms.services.mailer import RecordingMailer

CODE_RE = re.compile(r"\b(\d{6})\b")


def mailer_of(api: TestClient) -> RecordingMailer:
    mailer = getattr(api.app.state, "mailer", None)
    if not isinstance(mailer, RecordingMailer):
        mailer = RecordingMailer()
        api.app.state.mailer = mailer
    return mailer


def last_code(api: TestClient, email: str) -> str:
    """The code of the newest code mail sent to `email`."""
    for mail in reversed(mailer_of(api).sent):
        if mail.to == email.strip().lower() and "code" in mail.subject.lower():
            m = CODE_RE.search(mail.text)
            if m:
                return m.group(1)
    raise AssertionError(f"no code mail to {email}")


def age_codes(api: TestClient, email: str, seconds: int = 3601) -> None:
    """Moves the login's codes back in time (test clock), so the resend wait and the hourly cap have passed."""
    with api.app.state.session_factory() as s:
        s.execute(
            sa.text(
                "UPDATE otp_codes SET created_at = created_at - make_interval(secs => :s) "
                "WHERE user_id = (SELECT id FROM users WHERE email = :e)"
            ),
            {"s": seconds, "e": email.strip().lower()},
        )
        s.commit()


def start(api: TestClient, email: str, password: str, **extra):
    """Step one, retried once after ageing the codes when the resend wait answers 429."""
    mailer_of(api)
    body = {"email": email, "password": password, **extra}
    r = api.post("/auth/login", json=body)
    if r.status_code == 429 and r.json()["detail"]["code"] == "too_many_codes":
        age_codes(api, email)
        r = api.post("/auth/login", json=body)
    return r


def sign_in(api: TestClient, email: str, password: str, **extra) -> dict:
    """Both steps; the verify answer (tokens, `next_step`, `device_token`)."""
    r = start(api, email, password, **extra)
    assert r.status_code == 200, r.text
    challenge = r.json()["challenge_id"]
    device = {k: v for k, v in extra.items() if k in ("device_token", "device_label")}
    v = api.post(
        "/auth/otp/verify", json={"challenge_id": challenge, "code": last_code(api, email), **device}
    )
    assert v.status_code == 200, v.text
    return v.json()


def ready_all(session) -> None:
    """Fixture logins skip the first-sign-in steps (own password, profile confirmation) unless a test is about
    them: both flags cleared for every login in the session's database."""
    session.execute(sa.text("UPDATE users SET must_change_password = false, must_confirm_profile = false"))


def ready(api: TestClient, email: str) -> None:
    """One login (e.g. created through the API during a test) skips the first-sign-in steps."""
    with api.app.state.session_factory() as s:
        s.execute(
            sa.text(
                "UPDATE users SET must_change_password = false, must_confirm_profile = false WHERE email = :e"
            ),
            {"e": email.strip().lower()},
        )
        s.commit()


def forget_devices(session) -> None:
    """Removes the sign-in records (device-bound refresh tokens, devices) so a migration test can go below 0010,
    whose downgrade refuses while `user_devices` rows exist."""
    session.execute(sa.text("DELETE FROM refresh_tokens WHERE device_id IS NOT NULL"))
    session.execute(sa.text("DELETE FROM user_devices"))


def bearer(api: TestClient, email: str, password: str) -> dict:
    return {"Authorization": f"Bearer {sign_in(api, email, password)['access_token']}"}


__all__ = [
    "age_codes",
    "bearer",
    "forget_devices",
    "last_code",
    "mailer_of",
    "ready",
    "ready_all",
    "sign_in",
    "start",
]
