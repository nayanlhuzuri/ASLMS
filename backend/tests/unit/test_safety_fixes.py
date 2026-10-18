"""Design `safety-fixes` (unit): the empty HTTP 200 is `NapixEmptyResponse` and is not retried in the call, a print_r
626 stays an auth error, an undecryptable envelope stays a protocol error, HTTP 500 keeps its three attempts; the
role-password refusals; the worker's fault-pause line; the advocate row extractor; the STORE_NOW <= STORE_MAX
validator."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from aslms.cli.db import validate_role_password
from aslms.cli.pipeline import worker_wait
from aslms.core.config import Settings
from aslms.core.errors import NapixAuthError, NapixEmptyResponse, NapixProtocolError, NapixUnavailable
from aslms.integration.napix.client import NapixClient
from aslms.integration.napix.hc import advocate_rows
from tests.unit.conftest import Gateway

SAMPLES = Path(__file__).resolve().parents[3] / "docs" / "specs" / "samples"


async def test_empty_200_is_napix_empty_response_and_not_retried_in_call(
    client: NapixClient, gateway: Gateway, calls
) -> None:
    gateway.responses.extend([lambda p, q, r: httpx.Response(200, text="")] * 3)
    async with client:
        with pytest.raises(NapixEmptyResponse) as info:
            await client.call("hc-cnr-api/CNR", {"cino": "GAHC010153612024"})
    assert isinstance(info.value, NapixUnavailable)
    assert len(gateway.seen) == 1 and len(calls) == 1  # one attempt, no in-call retry
    assert calls[0].error_family == "NapixEmptyResponse" and not calls[0].ok


async def test_non_json_200_is_unavailable_but_print_r_626_is_auth(
    client: NapixClient, gateway: Gateway, calls
) -> None:
    gateway.responses.append(lambda p, q, r: httpx.Response(200, text="<html>busy</html>"))
    gateway.responses.append(
        lambda p, q, r: httpx.Response(200, text="Array ( [status_code] => 626 [status] => INVALID_TOKEN )")
    )
    async with client:
        with pytest.raises(NapixEmptyResponse):
            await client.call("overview/overview")
        with pytest.raises(NapixAuthError):
            await client.call("overview/overview")
    assert [c.error_family for c in calls] == ["NapixEmptyResponse", "NapixAuthError"]
    assert calls[0].raw_text == "<html>busy</html>"


async def test_undecryptable_response_str_stays_protocol_error(client: NapixClient, gateway: Gateway) -> None:
    gateway.responses.append(
        lambda p, q, r: httpx.Response(200, json={"response_str": "AAAA", "response_token": "x"})
    )
    gateway.responses.append(lambda p, q, r: httpx.Response(418, text="<html>teapot</html>"))
    async with client:
        with pytest.raises(NapixProtocolError) as a:
            await client.call("overview/overview")
        with pytest.raises(NapixProtocolError) as b:
            await client.call("overview/overview")
    assert not isinstance(a.value, NapixUnavailable) and not isinstance(b.value, NapixUnavailable)


async def test_http_500_still_retried_three_times(client: NapixClient, gateway: Gateway, calls) -> None:
    gateway.responses.extend([lambda p, q, r: httpx.Response(500, text="oops")] * 3)
    async with client:
        with pytest.raises(NapixUnavailable) as info:
            await client.call("overview/overview")
    assert not isinstance(info.value, NapixEmptyResponse)
    assert len(gateway.seen) == 3 and [c.error_family for c in calls] == ["NapixUnavailable"] * 3


def test_validate_role_password_refusals() -> None:
    assert validate_role_password("") and validate_role_password(None)
    assert "shorter" in validate_role_password("abcDEF123")
    assert "letters, digits" in validate_role_password("abcdefghij0123456789!")
    assert "letters, digits" in validate_role_password("abcdefghij 0123456789")
    for default in ("aslms", "aslms_app", "aslms_readonly", "changeme", "password", "ASLMS_APP"):
        assert validate_role_password(default) == "the password is a known default"
    assert validate_role_password("0123456789abcdef0123456789abcdef") is None  # openssl rand -hex 16
    assert validate_role_password("Ab_-" * 4) is None


def test_reason_never_echoes_the_value() -> None:
    secret = "s3cr3t!value"
    assert secret not in (validate_role_password(secret) or "")


def test_worker_wait_prints_fault_pause() -> None:
    now = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)
    report = SimpleNamespace(
        resume_at=now + timedelta(seconds=300), load_only=False, window=None, processed=5, fault_pause=True
    )
    wait, line = worker_wait(report, 60, now)
    assert wait == 300 and line.startswith("gateway fault: pausing until about 15:35:00 IST (300 s)")
    report.fault_pause = False
    _, other = worker_wait(report, 60, now)
    assert other.startswith("reset overdue")


def test_advocate_rows_extracts_casenos_in_order() -> None:
    payload = json.loads((SAMPLES / "advocate_name_2026-10-18-p4.json").read_text("utf-8"))
    rows = advocate_rows(payload)
    keys = sorted(payload["casenos"], key=lambda k: int("".join(ch for ch in k if ch.isdigit()) or 0))
    assert rows == [payload["casenos"][k] for k in keys]
    assert rows and all("cino" in r for r in rows)
    assert advocate_rows({}) == [] and advocate_rows(None) == []


def test_settings_store_now_not_above_store_max() -> None:
    s = Settings(_env_file=None)
    assert (s.napix_advocate_store_now, s.napix_advocate_store_max) == (25, 300)
    assert (s.napix_fault_streak, s.napix_fault_pause_seconds) == (5, 300)
    Settings(_env_file=None, napix_advocate_store_now=100, napix_advocate_store_max=100)
    with pytest.raises(ValidationError, match="NAPIX_ADVOCATE_STORE_NOW"):
        Settings(_env_file=None, napix_advocate_store_now=60, napix_advocate_store_max=50)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, napix_fault_streak=2)
