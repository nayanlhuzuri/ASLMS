"""The virus scanner behind every upload (design `documents-uploads`, decisions 1, 2). `ClamdScanner` speaks
the `clamd` `zINSTREAM` protocol over TCP with the standard library: a null-terminated command, chunks
prefixed by a 4-byte big-endian length, a zero-length chunk to finish, and a null-terminated reply of
`stream: OK`, `stream: <signature> FOUND` or `... ERROR`. Anything but a verdict (unreachable, timed out,
an error reply, a closed socket) is `ScannerUnavailable`: the upload fails closed. There is no "scan
disabled" setting. `FakeScanner` is the test double."""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass, field
from typing import Protocol

from aslms.core.config import Settings

CHUNK = 64 * 1024

# built at run time from two halves so no antivirus quarantines this source file
_EICAR_HALVES = (r"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR", r"-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*")


def eicar_test_string() -> bytes:
    return "".join(_EICAR_HALVES).encode("ascii")


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    signature: str | None = None


class ScannerUnavailable(RuntimeError):
    """No verdict could be obtained (HTTP 503 `scanner_unavailable`)."""


class Scanner(Protocol):
    def scan(self, data: bytes) -> ScanResult: ...


def _parse_reply(reply: bytes) -> ScanResult:
    text = reply.rstrip(b"\0\n").decode("utf-8", "replace").strip()
    if text.endswith("OK"):
        return ScanResult(True)
    if text.endswith("FOUND"):
        body = text.split(":", 1)[1] if ":" in text else text
        signature = body.strip().removesuffix("FOUND").strip() or "unknown"
        return ScanResult(False, signature)
    raise ScannerUnavailable(f"clamd answered: {text[:200] or '(nothing)'}")


class ClamdScanner:
    def __init__(self, host: str, port: int, timeout: float = 30.0):
        self.host, self.port, self.timeout = host, port, timeout

    def scan(self, data: bytes) -> ScanResult:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                sock.sendall(b"zINSTREAM\0")
                for i in range(0, len(data), CHUNK):
                    chunk = data[i : i + CHUNK]
                    sock.sendall(struct.pack(">I", len(chunk)) + chunk)
                sock.sendall(struct.pack(">I", 0))
                reply = b""
                while not reply.endswith(b"\0"):
                    part = sock.recv(4096)
                    if not part:
                        break
                    reply += part
                    if len(reply) > 65536:
                        break
        except (OSError, TimeoutError) as exc:
            raise ScannerUnavailable(f"clamd at {self.host}:{self.port}: {exc}") from exc
        if not reply:
            raise ScannerUnavailable(f"clamd at {self.host}:{self.port} closed the connection")
        return _parse_reply(reply)

    def version(self) -> str:
        """clamd's `zVERSION` answer, `ClamAV 1.5.4/27795/Sun Oct 18 08:26:03 2026` (engine / signature version /
        signature date), for the operations exporter (design deployment-checklist, decision 23)."""
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                sock.sendall(b"zVERSION\0")
                reply = b""
                while not reply.endswith(b"\0"):
                    part = sock.recv(4096)
                    if not part:
                        break
                    reply += part
                    if len(reply) > 4096:
                        break
        except (OSError, TimeoutError) as exc:
            raise ScannerUnavailable(f"clamd at {self.host}:{self.port}: {exc}") from exc
        text = reply.rstrip(b"\0\n").decode("utf-8", "replace").strip()
        if not text:
            raise ScannerUnavailable(f"clamd at {self.host}:{self.port} closed the connection")
        return text


@dataclass
class FakeScanner:
    """Flags the EICAR test string (and any `infected` marker bytes); `fail=True` behaves as an unreachable
    scanner. Records every scanned size."""

    fail: bool = False
    marker: bytes = b"__ASLMS_INFECTED__"
    seen: list[int] = field(default_factory=list)

    def scan(self, data: bytes) -> ScanResult:
        if self.fail:
            raise ScannerUnavailable("fake scanner is down")
        self.seen.append(len(data))
        if eicar_test_string() in data:
            return ScanResult(False, "Eicar-Signature")
        if self.marker in data:
            return ScanResult(False, "Aslms-Test-Signature")
        return ScanResult(True)


def get_scanner(settings: Settings) -> Scanner:
    return ClamdScanner(settings.clamav_host, settings.clamav_port, settings.clamav_timeout_seconds)
