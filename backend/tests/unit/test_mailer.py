"""The mailer (design alerts-notifications, decision 19): `get_mailer` by `MAIL_BACKEND`, the Mailtrap API
backend over a mock transport (bearer header, 4xx / 5xx → MailError without the token), the console backend
logging no body, and the recording double."""

from __future__ import annotations

import logging

import httpx
import pytest

from aslms.core.config import Settings
from aslms.services import mailer as m

TOKEN = "tok-secret-123456"


def settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_get_mailer_by_backend():
    assert m.get_mailer(settings()).name == "console"
    assert (
        m.get_mailer(
            settings(mailtrap_api_token=TOKEN, mailtrap_api_url="https://api.test/send", smtp_from="a@b.c")
        ).name
        == "api"
    )
    assert m.get_mailer(settings(smtp_host="smtp.test", smtp_from="a@b.c")).name == "smtp"
    # the API wins over SMTP under auto; console can always be forced
    both = settings(
        mailtrap_api_token=TOKEN,
        mailtrap_api_url="https://api.test/send",
        smtp_host="smtp.test",
        smtp_from="a@b.c",
    )
    assert m.get_mailer(both).name == "api"
    assert m.get_mailer(settings(mail_backend="console", smtp_host="smtp.test")).name == "console"
    with pytest.raises(m.MailError):
        m.get_mailer(settings(mail_backend="api", smtp_from="a@b.c"))
    with pytest.raises(m.MailError):
        m.get_mailer(settings(mail_backend="smtp", smtp_from="a@b.c"))
    with pytest.raises(m.MailError, match="SMTP_FROM"):
        m.get_mailer(settings(mail_backend="smtp", smtp_host="smtp.test"))
    with pytest.raises(m.MailError):
        m.get_mailer(settings(mail_backend="pigeon", smtp_from="a@b.c"))


def test_mailtrap_api_sends_bearer_and_maps_errors():
    seen: list[httpx.Request] = []
    status = {"code": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status.code if False else status["code"], json={"success": True, "echo": TOKEN})

    mailer = m.get_mailer(
        settings(
            mailtrap_api_token=TOKEN, mailtrap_api_url="https://api.test/send", smtp_from="aslms@example.org"
        ),
        transport=httpx.MockTransport(handler),
    )
    mailer.send("user@example.org", "Subject", "Body text")
    req = seen[-1]
    assert req.headers["authorization"] == f"Bearer {TOKEN}"
    import json

    payload = json.loads(req.content)
    assert (
        payload["to"] == [{"email": "user@example.org"}] and payload["from"]["email"] == "aslms@example.org"
    )
    assert payload["subject"] == "Subject" and payload["text"] == "Body text"
    for code in (401, 422, 500):
        status["code"] = code
        with pytest.raises(m.MailError) as exc:
            mailer.send("user@example.org", "Subject", "Body text")
        assert str(code) in str(exc.value) and TOKEN not in str(exc.value)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect with {TOKEN}")

    failing = m.MailtrapApiMailer(
        url="https://api.test/send", token=TOKEN, from_email="a@b.c", transport=httpx.MockTransport(boom)
    )
    with pytest.raises(m.MailError) as exc:
        failing.send("user@example.org", "s", "t")
    assert TOKEN not in str(exc.value) and "ConnectError" in str(exc.value)


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


def test_console_mailer_logs_masked_recipient_and_no_body():
    logger = logging.getLogger("aslms.services.mailer")
    handler = _Collect()
    logger.addHandler(handler)
    old_level, old_disabled = logger.level, logger.disabled
    # alembic's env.py (run by the database tests) calls fileConfig, which disables existing loggers
    logger.setLevel(logging.INFO)
    logger.disabled = False
    try:
        m.ConsoleMailer().send("nayan@example.org", "Hearing tomorrow", "SECRET BODY")
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        logger.disabled = old_disabled
    text = " | ".join(handler.lines)
    assert "n***@example.org" in text and "Hearing tomorrow" in text
    assert "SECRET BODY" not in text and "nayan@" not in text


def test_recording_mailer():
    rec = m.RecordingMailer()
    rec.send("a@b.c", "s", "t")
    assert rec.sent[0].to == "a@b.c"
    rec.fail_with = m.MailError("down")
    with pytest.raises(m.MailError):
        rec.send("a@b.c", "s", "t")
    assert m.mask_address("x") == "***"
