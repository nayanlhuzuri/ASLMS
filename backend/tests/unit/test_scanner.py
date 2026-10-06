"""`ClamdScanner` against an in-process fake `clamd` (design documents-uploads, decision 2): the zINSTREAM
framing, OK / FOUND / ERROR replies, a closed socket and a time-out; the EICAR string is built at run time."""

from __future__ import annotations

import socketserver
import struct
import threading
import time
from collections.abc import Iterator

import pytest

from aslms.services.scanner import (
    ClamdScanner,
    FakeScanner,
    ScannerUnavailable,
    ScanResult,
    eicar_test_string,
)


class FakeClamd:
    """Replies with `reply` (bytes) after reading the whole stream; `mode` = reply | close | hang."""

    def __init__(self):
        self.reply = b"stream: OK\0"
        self.mode = "reply"
        self.received: list[bytes] = []
        self.commands: list[bytes] = []
        fake = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                buf = b""
                while b"\0" not in buf:
                    buf += self.request.recv(1024)
                command, rest = buf.split(b"\0", 1)
                fake.commands.append(command)
                data = rest
                chunks = []
                while True:
                    while len(data) < 4:
                        data += self.request.recv(65536)
                    (n,) = struct.unpack(">I", data[:4])
                    data = data[4:]
                    if n == 0:
                        break
                    while len(data) < n:
                        data += self.request.recv(65536)
                    chunks.append(data[:n])
                    data = data[n:]
                fake.received.append(b"".join(chunks))
                if fake.mode == "close":
                    return
                if fake.mode == "hang":
                    time.sleep(1.5)
                    return
                self.request.sendall(fake.reply)

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def clamd() -> Iterator[FakeClamd]:
    fake = FakeClamd()
    yield fake
    fake.stop()


def test_clean_reply_and_chunk_framing(clamd):
    data = b"x" * (64 * 1024 * 2 + 17)  # three chunks
    assert ClamdScanner("127.0.0.1", clamd.port, timeout=2).scan(data) == ScanResult(True, None)
    assert clamd.commands == [b"zINSTREAM"] and clamd.received == [data]


def test_found_reply_carries_the_signature(clamd):
    clamd.reply = b"stream: Eicar-Signature FOUND\0"
    out = ClamdScanner("127.0.0.1", clamd.port, timeout=2).scan(eicar_test_string())
    assert out == ScanResult(False, "Eicar-Signature")


def test_error_reply_closed_socket_and_timeout_are_unavailable(clamd):
    scanner = ClamdScanner("127.0.0.1", clamd.port, timeout=0.5)
    clamd.reply = b"INSTREAM size limit exceeded. ERROR\0"
    with pytest.raises(ScannerUnavailable, match="ERROR"):
        scanner.scan(b"abc")
    clamd.mode = "close"
    with pytest.raises(ScannerUnavailable, match="closed"):
        scanner.scan(b"abc")
    clamd.mode = "hang"
    with pytest.raises(ScannerUnavailable):
        scanner.scan(b"abc")


def test_unreachable_host_is_unavailable():
    with pytest.raises(ScannerUnavailable):
        ClamdScanner("127.0.0.1", 1, timeout=0.5).scan(b"abc")


def test_fake_scanner_flags_eicar_and_can_fail():
    fake = FakeScanner()
    assert fake.scan(b"hello").clean is True
    assert fake.scan(b"--" + eicar_test_string() + b"--") == ScanResult(False, "Eicar-Signature")
    assert fake.seen == [5, 72]
    with pytest.raises(ScannerUnavailable):
        FakeScanner(fail=True).scan(b"x")
