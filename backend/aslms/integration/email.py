"""E-mail delivery. Three backends, chosen by MAIL_BACKEND (default `auto`):
  mailtrap  Mailtrap Email Sending API over HTTPS (MAILTRAP_API_TOKEN; MAILTRAP_API_URL for the sandbox)
  smtp      any SMTP server, including Mailtrap SMTP (live.smtp.mailtrap.io:587, user `api`, token as password)
  console   written to the log (development); OTPs can then be read from the console
`auto` picks Mailtrap when a token is set, SMTP when SMTP_HOST is set, otherwise the console."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

import httpx

from aslms.core.config import get_settings
from aslms.core.logging import get_logger

log = get_logger(__name__)


class ConsoleMailer:
    sent: list[dict[str, str]] = []  # kept for tests

    def send(self, *, to: str, subject: str, body: str) -> None:
        ConsoleMailer.sent.append({"to": to, "subject": subject, "body": body})
        log.info("email (console mailer)", to=to, subject=subject, body=body)


class SmtpMailer:
    def __init__(self) -> None:
        s = get_settings()
        self.host, self.port, self.user = s.smtp_host, s.smtp_port, s.smtp_user
        self.password = s.smtp_password.get_secret_value() if s.smtp_password else None
        self.sender = s.smtp_from

    def send(self, *, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = (
            formataddr((get_settings().smtp_from_name, self.sender)),
            to,
            subject,
        )
        msg.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
            if get_settings().smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if self.user and self.password:
                smtp.login(self.user, self.password)
            smtp.send_message(msg)


class MailtrapApiMailer:
    """Mailtrap Email Sending API. The sender address (SMTP_FROM) must be on a domain verified in Mailtrap;
    the testing sandbox URL accepts any sender. The token is never logged."""

    def __init__(self) -> None:
        s = get_settings()
        self.token = _mailtrap_token()
        if not self.token:
            raise ValueError("MAILTRAP_API_TOKEN is not set")
        self.url = s.mailtrap_api_url
        self.sender, self.sender_name = s.smtp_from, s.smtp_from_name

    def send(self, *, to: str, subject: str, body: str) -> None:
        payload = {
            "from": {"email": self.sender, "name": self.sender_name},
            "to": [{"email": to}],
            "subject": subject,
            "text": body,
            "category": "aslms",
        }
        try:
            r = httpx.post(
                self.url, json=payload, headers={"Authorization": f"Bearer {self.token}"}, timeout=20
            )
        except httpx.HTTPError as e:
            raise RuntimeError(f"Mailtrap unreachable: {type(e).__name__}") from e
        if r.status_code >= 300:
            # Mailtrap answers {"success": false, "errors": [...]}; keep the reason, never the request
            raise RuntimeError(f"Mailtrap HTTP {r.status_code}: {r.text[:300]}")


def _mailtrap_token() -> str:
    """An empty `MAILTRAP_API_TOKEN=` line in .env means "not set"."""
    t = get_settings().mailtrap_api_token
    return t.get_secret_value().strip() if t else ""


def get_mailer() -> ConsoleMailer | SmtpMailer | MailtrapApiMailer:
    s = get_settings()
    backend = (s.mail_backend or "auto").lower()
    if backend == "mailtrap" or (backend == "auto" and _mailtrap_token()):
        return MailtrapApiMailer()
    if backend == "smtp" or (backend == "auto" and s.smtp_host):
        return SmtpMailer()
    return ConsoleMailer()
