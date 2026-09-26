"""Virus scanning of uploads through clamd (plan §8.1). If CLAMAV_HOST is not set the scan result is `failed`
and the upload is refused in production; in dev the upload is accepted and marked `failed` for visibility."""

from __future__ import annotations

import io

from aslms.core.config import get_settings
from aslms.core.logging import get_logger

log = get_logger(__name__)
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class ClamdScanner:
    def __init__(self, host: str, port: int):
        self.host, self.port = host, port

    def scan(self, content: bytes) -> tuple[str, str | None]:
        try:
            import clamd

            cd = clamd.ClamdNetworkSocket(self.host, self.port, timeout=60)
            result = cd.instream(io.BytesIO(content))
            status, detail = result.get("stream", ("ERROR", "no result"))
        except Exception as e:  # noqa: BLE001 — scanner down must not crash the upload path
            log.warning("clamd scan failed", error=str(e))
            return "failed", f"scanner unavailable: {e}"[:300]
        if status == "OK":
            return "clean", None
        if status == "FOUND":
            return "infected", detail
        return "failed", f"{status}: {detail}"


class NoScanner:
    """Used when CLAMAV_HOST is empty. Detects the EICAR test string so the refusal path can be tested."""

    def scan(self, content: bytes) -> tuple[str, str | None]:
        if EICAR in content:
            return "infected", "Eicar-Test-Signature"
        return "failed", "virus scanner not configured"


def get_scanner() -> ClamdScanner | NoScanner:
    s = get_settings()
    return ClamdScanner(s.clamav_host, s.clamav_port) if s.clamav_host else NoScanner()
