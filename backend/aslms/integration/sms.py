"""SMS gateway (Phase 2). Until SMS_GATEWAY_URL is set, messages are logged, not sent."""

from __future__ import annotations

import httpx

from aslms.core.config import get_settings
from aslms.core.errors import SourceUnavailable
from aslms.core.logging import get_logger

log = get_logger(__name__)


class LogSms:
    def send(self, *, to: str, text: str) -> None:
        log.info("sms (not configured, logged only)", to=to, text=text)


class HttpSms:
    """Generic HTTP gateway: POST {to, text} with a bearer key. Adjust to the State gateway's contract."""

    def __init__(self) -> None:
        s = get_settings()
        self.url = s.sms_gateway_url
        self.key = s.sms_gateway_key.get_secret_value() if s.sms_gateway_key else ""

    def send(self, *, to: str, text: str) -> None:
        try:
            r = httpx.post(
                self.url,
                json={"to": to, "text": text[:480]},
                headers={"Authorization": f"Bearer {self.key}"},
                timeout=20,
            )
        except httpx.HTTPError as e:
            raise SourceUnavailable(f"SMS gateway: {e}") from e
        if r.status_code >= 300:
            raise SourceUnavailable(f"SMS gateway HTTP {r.status_code}")


def get_sms() -> LogSms | HttpSms:
    return HttpSms() if get_settings().sms_gateway_url else LogSms()
