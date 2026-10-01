"""A fake NAPIX gateway behind httpx.MockTransport: it decrypts `request_str` with the test key, checks the
HMAC, and answers with whatever the test scripted (an encrypted envelope by default)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from aslms.integration.napix.client import NapixClient, NapixResult
from aslms.integration.napix.crypto import NapixCrypto

KEY = "test-key-16bytes"
TOKEN_URL = "https://gw.test/nic/ecourts//oauth2/token"


@dataclass
class Gateway:
    crypto: NapixCrypto
    responses: list[Callable[[str, dict[str, Any], httpx.Request], httpx.Response]] = field(
        default_factory=list
    )
    seen: list[dict[str, Any]] = field(default_factory=list)  # one per API call: path, plain, method, headers
    token_calls: int = 0
    rate_headers: dict[str, str] = field(default_factory=dict)

    def envelope(self, data: Any, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
        text = json.dumps(data, separators=(",", ":"))
        body = {
            "response_str": self.crypto.encrypt(text),
            "response_token": self.crypto.token(text),
            "version": "v1.0",
        }
        return httpx.Response(
            status, text=json.dumps(body), headers={"content-type": "text/html", **(headers or {})}
        )

    def envelope_text(self, text: str) -> httpx.Response:
        """An envelope whose decrypted content is not JSON (e.g. a Base64 PDF)."""
        body = {
            "response_str": self.crypto.encrypt(text),
            "response_token": self.crypto.token(text),
            "version": "v1.0",
        }
        return httpx.Response(200, text=json.dumps(body), headers={"content-type": "text/html"})

    def encrypted_status(self, code: int) -> httpx.Response:
        text = json.dumps({"status": code})
        return httpx.Response(200, json={"status": self.crypto.encrypt(text)})

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == TOKEN_URL:
            self.token_calls += 1
            assert request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded")
            assert request.headers.get("authorization", "").startswith("Basic ")
            assert request.content == b"grant_type=client_credentials&scope=napix"
            return httpx.Response(200, json={"access_token": f"tok{self.token_calls}", "expires_in": 3600})
        if request.method == "POST":
            q = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        else:
            q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        plain = self.crypto.decrypt(q["request_str"])
        assert q["request_token"] == self.crypto.token(plain), (
            "request_token must be the HMAC of the plain text"
        )
        assert q["dept_id"] == "dept-test" and q["version"] == "v1.0"
        path = urlparse(url).path.split("/nic/ecourts/", 1)[1]
        self.seen.append(
            {
                "path": path,
                "plain": plain,
                "method": request.method,
                "auth": request.headers.get("authorization"),
            }
        )
        handler = self.responses.pop(0) if self.responses else (lambda p, q, r: self.envelope({"ok": True}))
        resp = handler(path, q, request)
        if self.rate_headers:
            resp.headers.update(self.rate_headers)
        return resp


@pytest.fixture()
def gateway() -> Gateway:
    return Gateway(NapixCrypto(KEY))


@pytest.fixture()
def calls() -> list[NapixResult]:
    return []


@pytest.fixture()
def client(gateway: Gateway, calls: list[NapixResult]) -> NapixClient:
    return NapixClient(
        base_url="https://gw.test/nic/ecourts",
        client_id="key-test",
        client_secret="secret-test",
        dept_id="dept-test",
        crypto=NapixCrypto(KEY),
        transport=httpx.MockTransport(gateway.handle),
        on_call=calls.append,
        backoff_base=0.0,
    )
