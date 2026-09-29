"""Mail backends: selection and the Mailtrap Sending API request (no network)."""

from __future__ import annotations

import httpx
import pytest

from aslms.core.config import get_settings
from aslms.integration import email


@pytest.fixture()
def settings_env(monkeypatch: pytest.MonkeyPatch):
    def apply(**env: str) -> None:
        # a developer's .env may hold a real token or backend; environment variables override the file,
        # so every key is pinned (empty = "not set") unless the test sets it
        defaults = {"MAIL_BACKEND": "auto", "MAILTRAP_API_TOKEN": "", "SMTP_HOST": "", "MAILTRAP_API_URL": ""}
        for k, v in {**defaults, **env}.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()

    yield apply
    get_settings.cache_clear()


def test_backend_selection(settings_env) -> None:
    settings_env(SMTP_HOST="")
    assert isinstance(email.get_mailer(), email.ConsoleMailer)
    settings_env(SMTP_HOST="", MAILTRAP_API_TOKEN="")  # an empty line in .env is "not set"
    assert isinstance(email.get_mailer(), email.ConsoleMailer)
    settings_env(SMTP_HOST="smtp.example.org")
    assert isinstance(email.get_mailer(), email.SmtpMailer)
    settings_env(SMTP_HOST="smtp.example.org", MAILTRAP_API_TOKEN="tok")
    assert isinstance(email.get_mailer(), email.MailtrapApiMailer)  # auto prefers the API token
    settings_env(MAILTRAP_API_TOKEN="tok", MAIL_BACKEND="console")
    assert isinstance(email.get_mailer(), email.ConsoleMailer)


def test_mailtrap_request_shape(settings_env, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_env(
        MAILTRAP_API_TOKEN="secret-token", MAILTRAP_API_URL="https://sandbox.api.mailtrap.io/api/send/123"
    )
    seen: dict = {}

    def fake_post(url, json, headers, timeout):
        seen.update(url=url, json=json, headers=headers)
        return httpx.Response(200, json={"success": True, "message_ids": ["x"]})

    monkeypatch.setattr(email.httpx, "post", fake_post)
    email.get_mailer().send(to="officer@assam.gov.in", subject="ASLMS one-time password", body="code 123456")
    assert seen["url"] == "https://sandbox.api.mailtrap.io/api/send/123"
    assert seen["headers"]["Authorization"] == "Bearer secret-token"
    assert seen["json"]["to"] == [{"email": "officer@assam.gov.in"}]
    assert seen["json"]["from"]["email"] == get_settings().smtp_from
    assert seen["json"]["text"] == "code 123456"


def test_mailtrap_error_is_raised_without_the_token(settings_env, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_env(MAILTRAP_API_TOKEN="secret-token")
    monkeypatch.setattr(
        email.httpx,
        "post",
        lambda *a, **k: httpx.Response(401, json={"success": False, "errors": ["Unauthorized"]}),
    )
    with pytest.raises(RuntimeError) as exc:
        email.get_mailer().send(to="a@b.in", subject="s", body="b")
    assert "401" in str(exc.value) and "secret-token" not in str(exc.value)
