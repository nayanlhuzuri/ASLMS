"""Helpers shared by the API integration tests."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from aslms.integration.email import ConsoleMailer

PW = "Test-pass-2026"


def login(client: TestClient, email: str) -> dict[str, str]:
    ConsoleMailer.sent.clear()
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    code = re.search(r"\b(\d{6})\b", ConsoleMailer.sent[-1]["body"]).group(1)
    r = client.post("/api/v1/auth/verify", json={"challenge_id": r.json()["challenge_id"], "code": code})
    assert r.status_code == 200, r.text
    return r.json()


def auth(tokens: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}
