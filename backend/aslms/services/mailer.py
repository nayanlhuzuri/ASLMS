"""Mail delivery through one interface (design `alerts-notifications`, decision 19; the 27 Sep decision
"Mail service: Mailtrap"). `get_mailer(settings)` chooses by `MAIL_BACKEND`: `auto` prefers the Mailtrap API
token, then SMTP, then the console; `api`, `smtp` and `console` force one. A `MailError` carries the
exception class and a message, never the token or the SMTP password; the console backend logs the masked
recipient and the subject only. `RecordingMailer` is the test double; tests never reach the network."""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any, Protocol

import httpx

from aslms.core.config import Settings

log = logging.getLogger(__name__)


class MailError(RuntimeError):
    """The message was not delivered (the sender job retries)."""


class Mailer(Protocol):
    name: str

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None: ...


def mask_address(address: str) -> str:
    """`n***@example.org`: enough to recognise, not enough to harvest."""
    local, _, domain = (address or "").partition("@")
    if not domain:
        return "***"
    return f"{local[:1]}***@{domain}"


def _scrub(message: str, secrets: list[str | None]) -> str:
    for s in secrets:
        if s:
            message = message.replace(s, "***")
    return message


@dataclass
class MailtrapApiMailer:
    """HTTPS POST to the Mailtrap sending or sandbox API with the bearer token."""

    url: str
    token: str
    from_email: str
    from_name: str = "ASLMS"
    timeout: float = 20.0
    transport: httpx.BaseTransport | None = None
    name: str = "api"

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None:
        payload: dict[str, Any] = {
            "from": {"email": self.from_email, "name": self.from_name},
            "to": [{"email": to}],
            "subject": subject,
            "text": text,
        }
        if html:
            payload["html"] = html
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                r = client.post(self.url, json=payload, headers={"Authorization": f"Bearer {self.token}"})
        except httpx.HTTPError as exc:
            raise MailError(_scrub(f"{exc.__class__.__name__}: {exc}", [self.token])) from exc
        if r.status_code >= 400:
            body = _scrub(r.text[:200].replace("\n", " "), [self.token])
            raise MailError(f"mailtrap api answered {r.status_code}: {body}")


@dataclass
class SmtpMailer:
    host: str
    port: int = 587
    user: str | None = None
    password: str | None = None
    starttls: bool = True
    from_email: str = ""
    from_name: str = "ASLMS"
    timeout: float = 20.0
    name: str = "smtp"

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None:
        msg = EmailMessage()
        msg["From"] = f"{self.from_name} <{self.from_email}>" if self.from_name else self.from_email
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        if html:
            msg.add_alternative(html, subtype="html")
        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
                if self.starttls:
                    smtp.starttls()
                if self.user:
                    smtp.login(self.user, self.password or "")
                smtp.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            raise MailError(_scrub(f"{exc.__class__.__name__}: {exc}", [self.password])) from exc


@dataclass
class ConsoleMailer:
    """Logs the masked recipient and the subject; the body is never logged."""

    name: str = "console"

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None:
        log.info("mail to %s: %s", mask_address(to), subject)


@dataclass
class UnconfiguredMailer:
    """Stands in when the configured backend cannot be built (a missing sender or token): every send fails, and
    the sign-in code path answers 503 `mail_not_configured` before trying (design `otp-and-profile`)."""

    reason: str = "mail is not configured"
    name: str = "unconfigured"

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None:
        raise MailError(self.reason)


@dataclass
class Mail:
    to: str
    subject: str
    text: str
    html: str | None = None


@dataclass
class RecordingMailer:
    """The test double: records what would be sent; `fail_with` makes every send raise."""

    sent: list[Mail] = field(default_factory=list)
    fail_with: Exception | None = None
    name: str = "recording"

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append(Mail(to, subject, text, html))


def get_mailer(settings: Settings, transport: httpx.BaseTransport | None = None) -> Mailer:
    backend = (settings.mail_backend or "auto").strip().lower()
    token = settings.mailtrap_api_token.get_secret_value() if settings.mailtrap_api_token else None
    api_ready = bool(token and settings.mailtrap_api_url)
    smtp_ready = bool(settings.smtp_host)
    if backend == "auto":
        backend = "api" if api_ready else "smtp" if smtp_ready else "console"
    if backend == "console":
        return ConsoleMailer()
    if not settings.smtp_from:
        raise MailError(f"MAIL_BACKEND={backend} needs SMTP_FROM (the sender address)")
    if backend == "api":
        if not api_ready:
            raise MailError("MAIL_BACKEND=api needs MAILTRAP_API_TOKEN and MAILTRAP_API_URL")
        return MailtrapApiMailer(
            url=settings.mailtrap_api_url,
            token=token,
            from_email=settings.smtp_from,
            from_name=settings.smtp_from_name,
            timeout=settings.mail_timeout_seconds,
            transport=transport,
        )
    if backend == "smtp":
        if not smtp_ready:
            raise MailError("MAIL_BACKEND=smtp needs SMTP_HOST")
        return SmtpMailer(
            host=settings.smtp_host,
            port=settings.smtp_port,
            user=settings.smtp_user,
            password=settings.smtp_password.get_secret_value() if settings.smtp_password else None,
            starttls=settings.smtp_starttls,
            from_email=settings.smtp_from,
            from_name=settings.smtp_from_name,
            timeout=settings.mail_timeout_seconds,
        )
    raise MailError(f"unknown MAIL_BACKEND {backend!r} (auto, api, smtp or console)")
