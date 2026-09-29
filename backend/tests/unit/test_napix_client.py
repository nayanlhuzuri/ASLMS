"""Offline tests of the NAPIX transport against a mocked gateway (httpx.MockTransport)."""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from aslms.core.errors import IntegrationError, SourceNotFound, SourceUnavailable
from aslms.integration.napix.client import NapixClient, NapixResult, nested_list
from aslms.integration.napix.crypto import NapixCrypto
from aslms.integration.napix.hc import NapixHighCourt, parse_case_record

KEY = "0123456789abcdef"
crypto = NapixCrypto(KEY)


def envelope(payload: object) -> dict[str, str]:
    text = json.dumps(payload)
    return {"response_str": crypto.encrypt(text), "response_token": crypto.token(text), "version": "v1.0"}


def make_client(handler, on_call=None) -> NapixClient:
    return NapixClient(
        base="https://gw.test/nic/ecourts",
        client_id="id",
        client_secret="secret",
        dept_id="D1",
        crypto=NapixCrypto(KEY),
        on_call=on_call,
        transport=httpx.MockTransport(handler),
    )


def gateway(routes):
    """routes: {api_path: callable(plain_params: dict, request) -> httpx.Response}"""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/oauth2/token"):
            assert request.headers["Authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer tok"
        if request.method == "POST":
            q = parse_qs(request.content.decode())
        else:
            q = parse_qs(urlparse(str(request.url)).query)
        req_str = q.get("request_str", [""])[0]
        plain = crypto.decrypt(req_str) if req_str else ""
        assert q["request_token"][0] == crypto.token(plain)
        params = dict(kv.split("=", 1) for kv in plain.split("|")) if plain else {}
        for suffix, fn in routes.items():
            if path.endswith(suffix):
                return fn(params, request)
        return httpx.Response(404)

    return handler


@pytest.mark.asyncio
async def test_get_call_roundtrip_and_hook() -> None:
    seen: list[NapixResult] = []
    client = make_client(
        gateway(
            {
                "/hc-cnr-api/CNR": lambda p, r: httpx.Response(
                    200, json=envelope({"cino": p["cino"], "pend_disp": "P"})
                )
            }
        ),
        on_call=seen.append,
    )
    res = await client.call("hc-cnr-api/CNR", {"cino": "GAHC010000012024"})
    assert res.ok and res.data == {"cino": "GAHC010000012024", "pend_disp": "P"}
    assert res.token_verified is True
    assert seen == [res] and res.duration_ms >= 0


@pytest.mark.asyncio
async def test_post_bulk_and_nested_list() -> None:
    def status(p, r):
        cnrs = p["cino"].split(",")
        return httpx.Response(
            200, json=envelope({f"case{i + 1}": {"cino": c, "pend_disp": "D"} for i, c in enumerate(cnrs)})
        )

    hc = NapixHighCourt(make_client(gateway({"/currentStatus": status})), "GAHC01", "6")
    out = await hc.current_status(["a1", "a2", "a3"])
    assert [s.cnr for s in out] == ["A1", "A2", "A3"] and all(s.status == "disposed" for s in out)


@pytest.mark.asyncio
async def test_encrypted_error_status_maps_to_typed_errors() -> None:
    def err(code):
        return lambda p, r: httpx.Response(200, json={"status": crypto.encrypt(json.dumps({"status": code}))})

    client = make_client(gateway({"/CNR": err(628), "/order": err(631)}))
    with pytest.raises(SourceNotFound):
        await client.call("hc-cnr-api/CNR", {"cino": "X"})
    with pytest.raises(IntegrationError, match="631 API_ACCESS_NOT_ALLOWED"):
        await client.call("hc-order-api/order", {"cino": "X", "order_no": "1", "order_date": "2024-01-01"})


@pytest.mark.asyncio
async def test_pdf_raw_and_base64_inside_envelope() -> None:
    pdf = b"%PDF-1.4 fake"
    import base64

    client = make_client(
        gateway(
            {
                "/showcauselist": lambda p, r: httpx.Response(
                    200, content=pdf, headers={"content-type": "application/pdf"}
                ),
                "/order": lambda p, r: httpx.Response(
                    200,
                    json={
                        "response_str": crypto.encrypt(base64.b64encode(pdf).decode()),
                        "response_token": "",
                    },
                ),
            }
        )
    )
    a = await client.call(
        "hc-show-causelist-api/showcauselist",
        {"est_code": "GAHC01", "bench_id": "1", "causelist_id": "1", "causelist_date": "2026-09-26"},
    )
    b = await client.call("hc-order-api/order", {"cino": "X", "order_no": "1", "order_date": "2024-01-01"})
    assert a.pdf == pdf and b.pdf == pdf


@pytest.mark.asyncio
async def test_http_5xx_is_retried_then_raised(monkeypatch) -> None:
    calls = {"n": 0}

    def flaky(p, r):
        calls["n"] += 1
        return httpx.Response(503)

    client = make_client(gateway({"/state": flaky}))
    client.call.retry.wait = lambda *_: 0  # type: ignore[attr-defined]
    with pytest.raises(SourceUnavailable):
        await client.call("hc-state-api/state")
    assert calls["n"] == 3


def test_nested_list_orders_numeric_keys() -> None:
    assert nested_list({"case10": {"a": 10}, "case2": {"a": 2}, "case1": {"a": 1}}) == [
        {"a": 1},
        {"a": 2},
        {"a": 10},
    ]
    assert nested_list([{"x": 1}, "junk"]) == [{"x": 1}]
    assert nested_list(None) == [] and nested_list("text") == []


def test_parse_case_record_maps_documented_fields() -> None:
    c = {
        "cino": "gahc010153612024",
        "type_name_reg": "WP(C)",
        "reg_no": "1536",
        "reg_year": "2024",
        "type_name_fil": "WP(C)",
        "fil_no": "1601",
        "fil_year": "2024",
        "date_of_filing": "2024-03-01",
        "dt_regis": "2024-03-05",
        "pend_disp": "P",
        "date_next_list": "2026-10-15",
        "purpose_name": "ADMISSION",
        "pet_name": "Ram Kumar",
        "pet_extra_party": {"party_no2": "Shyam Kumar"},
        "res_name": "The State of Assam",
        "res_extra_party": ["Director of Secondary Education"],
        "pet_adv": "A. Das",
        "res_adv": "SC, EDU",
        "interimorder": {"order1": {"order_no": "1", "order_date": "2024-04-10"}},
        "finalorder": [],
        "acts": {"act1": {"actname": "Constitution of India", "section": "226"}},
        "historyofcasehearing": {"h1": {"business_date": "2024-04-10", "purpose": "ADMISSION"}},
        "link_cases": {"l1": {"case_number": "WA/12/2025"}},
        "main_matter_cino": "GAHC010000012024",
    }
    rec = parse_case_record(c, "GAHC010153612024")
    assert rec.cnr == "GAHC010153612024" and rec.reg_no == 1536 and rec.reg_year == 2024
    assert rec.filing_no_text == "WP(C)/1601/2024" and rec.registration_date == date(2024, 3, 5)
    assert rec.status == "pending" and rec.next_hearing_date == date(2026, 10, 15)
    assert [(p.role, p.party_no, p.name) for p in rec.parties] == [
        ("petitioner", 1, "Ram Kumar"),
        ("petitioner", 2, "Shyam Kumar"),
        ("respondent", 1, "The State of Assam"),
        ("respondent", 2, "Director of Secondary Education"),
    ]
    assert [(o.order_no, o.kind) for o in rec.orders] == [("1", "interim")]
    assert rec.acts == [{"act": "Constitution of India", "section": "226", "code": None}]
    assert rec.linked_case_nos == ["WA/12/2025"] and rec.linked_cnrs == ["GAHC010000012024"]
    assert len(rec.hearings) == 1
