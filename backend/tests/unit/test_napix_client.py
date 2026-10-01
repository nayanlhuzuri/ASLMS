"""Transport behaviour against the fake gateway (docs/napix_integration_design.md §3–§7)."""

from __future__ import annotations

import httpx
import pytest

from aslms.core.errors import (
    NapixAuthError,
    NapixGatewayError,
    NapixInputError,
    NapixNotFound,
    NapixProtocolError,
    NapixUnavailable,
)
from aslms.integration.napix.client import NapixClient, RateLimiter, TokenCache, nested_list
from tests.unit.conftest import Gateway


async def test_get_roundtrip_token_and_hook(client: NapixClient, gateway: Gateway, calls) -> None:
    gateway.responses.append(
        lambda p, q, r: gateway.envelope({"case1": {"bench_id": 2048}, "case2": {"bench_id": 1854}})
    )
    async with client:
        res = await client.call(
            "hc-causelist-bench-api/causelistbench", {"est_code": "GAHC01", "causelist_date": "2026-09-03"}
        )
    assert res.ok and res.token_verified is True and res.http_status == 200
    assert nested_list(res.data) == [{"bench_id": 2048}, {"bench_id": 1854}]
    assert gateway.seen[0]["plain"] == "est_code=GAHC01|causelist_date=2026-09-03"
    assert gateway.seen[0]["auth"] == "Bearer tok1" and gateway.token_calls == 1
    assert calls[0] is res and res.duration_ms >= 0 and res.params_sha256


async def test_query_string_percent_encodes_base64_for_get_and_post(
    client: NapixClient, gateway: Gateway
) -> None:
    raws: list[str] = []
    gateway.responses.append(lambda p, q, r: (raws.append(str(r.url)), gateway.envelope({"ok": 1}))[1])
    gateway.responses.append(lambda p, q, r: (raws.append(str(r.url)), gateway.envelope({"ok": 1}))[1])
    async with client:
        await client.call("hc-cnr-api/CNR", {"cino": "GAHC010153612024"})
        await client.call("hc-current-status-api/currentStatus", {"cino": "A,B"}, method="POST")
    value = raws[0].split("request_str=")[1].split("&")[0]
    assert all(ch not in value for ch in "+/=") and "%3D" in value  # Base64 padding is always present
    # Current Status is a POST, but its four parameters travel in the query string (verified live)
    assert gateway.seen[1]["method"] == "POST" and "request_str=" in raws[1].split("?", 1)[1]


async def test_no_input_api_encrypts_the_empty_string(client: NapixClient, gateway: Gateway) -> None:
    async with client:
        await client.call("overview/overview")
    assert gateway.seen[0]["plain"] == ""  # the gateway decrypted a non-blank request_str to ""


async def test_token_is_cached_and_refreshed_once_on_401(client: NapixClient, gateway: Gateway) -> None:
    gateway.responses.append(lambda p, q, r: httpx.Response(401, text="Unauthorized"))
    gateway.responses.append(lambda p, q, r: gateway.envelope({"after": "refresh"}))
    async with client:
        res = await client.call("overview/overview")
        await client.call("overview/overview")
    assert res.data == {"after": "refresh"}
    assert gateway.token_calls == 2  # first token, one refresh; the third call reused the cache
    assert [s["auth"] for s in gateway.seen] == ["Bearer tok1", "Bearer tok2", "Bearer tok2"]


async def test_second_401_is_an_auth_error(client: NapixClient, gateway: Gateway) -> None:
    gateway.responses += [lambda p, q, r: httpx.Response(401), lambda p, q, r: httpx.Response(401)]
    async with client:
        with pytest.raises(NapixAuthError):
            await client.call("overview/overview")


async def test_print_r_626_is_auth_error_not_retried(client: NapixClient, gateway: Gateway, calls) -> None:
    gateway.responses.append(
        lambda p, q, r: httpx.Response(
            200, text="Array\n(\n    [status_code] => 626\n    [status] => INVALID_TOKEN\n)\n"
        )
    )
    async with client:
        with pytest.raises(NapixAuthError) as e:
            await client.call("hc-bench-master-api/bench", {"state_code": "6"})
    assert e.value.napix_status == 626 and len(calls) == 1 and calls[0].napix_status == 626
    assert calls[0].error_family == "NapixAuthError"


async def test_encrypted_status_codes_map_to_families(client: NapixClient, gateway: Gateway) -> None:
    gateway.responses += [
        lambda p, q, r: gateway.encrypted_status(628),
        lambda p, q, r: gateway.encrypted_status(603),
        lambda p, q, r: gateway.encrypted_status(631),
    ]
    async with client:
        with pytest.raises(NapixNotFound):
            await client.call("hc-cnr-api/CNR", {"cino": "X"})
        with pytest.raises(NapixInputError):
            await client.call("hc-cnr-api/CNR", {"cino": "X"})
        with pytest.raises(NapixGatewayError):
            await client.call("hc-cnr-api/CNR", {"cino": "X"})


async def test_gateway_httpcode_body_is_a_gateway_error(client: NapixClient, gateway: Gateway) -> None:
    gateway.responses.append(
        lambda p, q, r: httpx.Response(
            200,
            json={
                "httpCode": "404",
                "httpMessage": "Not Found",
                "moreInformation": "No resources match requested URI",
            },
        )
    )
    async with client:
        with pytest.raises(NapixGatewayError, match="404"):
            await client.call("hc-cnr-api/cnr", {"cino": "X"})


async def test_5xx_and_629_are_retried_then_raised(client: NapixClient, gateway: Gateway, calls) -> None:
    gateway.responses += [lambda p, q, r: httpx.Response(503)] * 3
    async with client:
        with pytest.raises(NapixUnavailable):
            await client.call("overview/overview")
    assert len(calls) == 3
    gateway.responses += [
        lambda p, q, r: gateway.encrypted_status(629),
        lambda p, q, r: gateway.envelope({"ok": 1}),
    ]
    async with client:
        res = await client.call("overview/overview")
    assert res.ok and len(calls) == 5


async def test_tolerant_json_and_token_mismatch_warns_only(client: NapixClient, gateway: Gateway) -> None:
    env = gateway.envelope({"a": 1})
    body = env.text
    gateway.responses.append(lambda p, q, r: httpx.Response(200, text="<br/>" + body + "\n"))
    tampered = body.replace('"response_token": "', '"response_token": "0000')
    gateway.responses.append(lambda p, q, r: httpx.Response(200, text=tampered))
    async with client:
        a = await client.call("overview/overview")
        b = await client.call("overview/overview")
    assert a.data == {"a": 1} and a.token_verified is True
    assert b.data == {"a": 1} and b.token_verified is False


async def test_undecryptable_envelope_is_a_protocol_error(client: NapixClient, gateway: Gateway) -> None:
    gateway.responses.append(
        lambda p, q, r: httpx.Response(200, json={"response_str": "AAAA", "response_token": "x"})
    )
    async with client:
        with pytest.raises(NapixProtocolError):
            await client.call("overview/overview")


async def test_pdf_raw_and_base64_inside_envelope(client: NapixClient, gateway: Gateway) -> None:
    import base64

    pdf = b"%PDF-1.4 fake"
    gateway.responses.append(
        lambda p, q, r: httpx.Response(200, content=pdf, headers={"content-type": "application/pdf"})
    )
    gateway.responses.append(lambda p, q, r: gateway.envelope_text(base64.b64encode(pdf).decode()))
    async with client:
        a = await client.call(
            "hc-order-api/order", {"cino": "X", "order_no": "1", "order_date": "2026-01-01"}
        )
        b = await client.call(
            "hc-order-api/order", {"cino": "X", "order_no": "1", "order_date": "2026-01-01"}
        )
    gateway.responses.append(lambda p, q, r: gateway.envelope(base64.b64encode(pdf).decode()))  # JSON string
    async with client:
        c = await client.call("hc-show-causelist-api/showcauselist", {"est_code": "GAHC01"})
    assert a.pdf == pdf and b.pdf == pdf and c.pdf == pdf


async def test_rate_limit_headers_are_read(client: NapixClient, gateway: Gateway) -> None:
    gateway.rate_headers = {
        "X-RateLimit-Limit": "name=default,1000;",
        "X-RateLimit-Remaining": "name=default,999;",
    }
    async with client:
        res = await client.call("overview/overview")
    assert res.rate_limit == (1000, 999) and client.limiter.limit == 1000


def test_limiter_slows_down_near_the_limit() -> None:
    lim = RateLimiter(60, window_seconds=60)
    lim.observe({"x-ratelimit-limit": "name=default,1000;", "x-ratelimit-remaining": "name=default,500;"})
    assert lim._header_delay() == 0
    lim.observe({"x-ratelimit-remaining": "name=default,5;"})
    assert 0 < lim._header_delay() <= 60
    lim.observe({"x-ratelimit-remaining": "0"})
    assert lim._header_delay() == 60


def test_token_cache_without_redis() -> None:
    c = TokenCache()
    assert c.get() is None
    c.set("t", 120)
    assert c.get() == "t"
    assert c.get(margin=200) is None  # about to expire within the margin
    c.clear()
    assert c.get() is None


def test_nested_list_orders_numeric_keys() -> None:
    assert nested_list({"case10": {"n": 10}, "case2": {"n": 2}, "case1": {"n": 1}}) == [
        {"n": 1},
        {"n": 2},
        {"n": 10},
    ]
    assert nested_list([{"a": 1}, "junk"]) == [{"a": 1}]
    assert nested_list(None) == [] and nested_list({"not": "rows"}) == []
