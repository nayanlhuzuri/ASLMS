"""E-mail delivery. With SMTP_HOST empty (dev), messages are written to the log instead of being sent,
so OTPs and alerts can be read from the console."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

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
        msg["From"], msg["To"], msg["Subject"] = self.sender, to, subject
        msg.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
            if self.port != 25:
                smtp.starttls(context=ssl.create_default_context())
            if self.user and self.password:
                smtp.login(self.user, self.password)
            smtp.send_message(msg)


def get_mailer() -> ConsoleMailer | SmtpMailer:
    return SmtpMailer() if get_settings().smtp_host else ConsoleMailer()
