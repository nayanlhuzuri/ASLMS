"""The integration layer's part of the System health console (design `system-health-inspector`, decisions 2, 10, 13):
the preview runs the API's own `hc.py` method and never reaches the transport; the token metadata, the one-request
token renewal and the token state never carry the token."""

from __future__ import annotations

import asyncio
import json
from datetime import date

import httpx
import pytest

from aslms.core.config import Settings
from aslms.integration.napix import preview as pv
from aslms.integration.napix.client import META_KEY, REQUESTS_KEY, NapixClient, TokenCache, _ist_date
from aslms.integration.napix.crypto import NapixCrypto
from aslms.integration.napix.hc import NapixHighCourt
from aslms.services.system_health import BY_KEY, CATALOGUE
from tests.redis_stub import RedisStub
from tests.unit.conftest import KEY, TOKEN_URL, Gateway

CNR = "GAHC010277142024"  # from docs/specs/samples
VALUES: dict[str, dict] = {
    "overview": {},
    "state": {},
    "district": {"state_code": "18"},
    "bench_master": {"state_code": "18"},
    "case_type": {"est_code": "GAHC01"},
    "act": {},
    "causelist_bench": {"list_date": date(2025, 1, 6)},
    "causelist_details": {"list_date": date(2025, 1, 6), "bench_id": "2048"},
    "show_causelist": {"bench_id": "2048", "causelist_id": "1007", "list_date": date(2025, 1, 6)},
    "cnr": {"cnr": CNR},
    "current_status": {"cnr": CNR},
    "order": {"cnr": CNR, "order_no": "1", "order_date": date(2026, 7, 13)},
    "show_business": {"cnr": CNR, "business_date": date(2026, 7, 13)},
    "case_search": {"case_type": 111, "reg_no": 7714, "reg_year": 2024},
    "filing": {"case_type": 111, "fil_no": 11883, "fil_year": 2025},
    "party_name": {"name": "THE STATE OF ASSAM", "reg_year": 2024, "pend_disp": "P"},
    "advocate_name": {"name": "ANUP KUMAR", "reg_year": 2024, "pend_disp": "D"},
}


def settings(**kw) -> Settings:
    return Settings(_env_file=None, napix_base_url="https://gw.test/nic/ecourts", **kw)


class Transport(httpx.MockTransport):
    """Counts every request that reaches it."""

    def __init__(self, handler):
        self.requests = 0

        def counted(request):
            self.requests += 1
            return handler(request)

        super().__init__(counted)


def make_client(gw: Gateway, tokens: TokenCache | None = None, handler=None) -> tuple[NapixClient, Transport]:
    transport = Transport(handler or gw.handle)
    client = NapixClient(
        base_url="https://gw.test/nic/ecourts",
        client_id="key-test",
        client_secret="secret-test",
        dept_id="dept-test",
        crypto=NapixCrypto(KEY),
        transport=transport,
        backoff_base=0.0,
        max_attempts=1,
        token_cache=tokens,
    )
    return client, transport


def test_catalogue_keys_are_the_seventeen():
    assert set(VALUES) == set(BY_KEY) and len(CATALOGUE) == 17


@pytest.mark.parametrize("key", list(VALUES))
def test_preview_matches_the_real_call(key):
    entry = BY_KEY[key]
    p = pv.preview(settings(), key, entry.invoke, VALUES[key])
    gw = Gateway(NapixCrypto(KEY))
    client, transport = make_client(gw)
    hc = NapixHighCourt(client, "GAHC01", "18")

    async def go():
        async with client:
            await entry.invoke(hc, VALUES[key])

    asyncio.run(go())
    (seen,) = gw.seen
    assert (p.path, p.plain, p.method) == (seen["path"], seen["plain"], seen["method"])
    assert [k for k, _ in p.params] == list(entry.input_fields)
    assert p.url == f"https://gw.test/nic/ecourts/{entry.path}" and p.method == entry.method
    assert p.complete and p.request_token == NapixCrypto("other").token(p.plain)
    assert transport.requests == 2  # the real call's token and API request; the preview made none


def test_preview_never_reaches_a_transport(monkeypatch):
    def refuse(*a, **k):  # any attempt to open a connection fails the test
        raise AssertionError("the preview opened a connection")

    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    for key, values in VALUES.items():
        assert pv.preview(settings(), key, BY_KEY[key].invoke, values).path == BY_KEY[key].path


def test_preview_with_an_edited_est_code_reaches_the_call():
    values = {"est_code": "GAHC02", "case_type": 111, "reg_no": 7714, "reg_year": 2024}
    entry = BY_KEY["case_search"]
    p = pv.preview(settings(), "case_search", entry.invoke, values)
    assert p.plain == "est_code=GAHC02|case_type=111|reg_no=7714|reg_year=2024"
    gw = Gateway(NapixCrypto(KEY))
    client, _ = make_client(gw)
    hc = NapixHighCourt(client, "GAHC01", "18").for_codes(est_code=values["est_code"])

    async def go():
        async with client:
            await entry.invoke(hc, values)

    asyncio.run(go())
    assert gw.seen[0]["plain"] == p.plain
    district = pv.preview(settings(), "district", BY_KEY["district"].invoke, {"state_code": "6"})
    assert district.plain == "state_code=6"


def test_for_codes_keeps_the_defaults_for_other_callers():
    hc = NapixHighCourt(object(), "GAHC01", "18")  # type: ignore[arg-type]
    assert hc.for_codes() is hc and hc.for_codes(state_code="6").est_code == "GAHC01"


def test_preview_request_token_only_with_the_published_hash_key():
    entry = BY_KEY["cnr"]
    shown = pv.preview(settings(), "cnr", entry.invoke, {"cnr": CNR})
    assert shown.request_token == NapixCrypto(KEY).token(f"cino={CNR}") and len(shown.request_token) == 64
    hidden = pv.preview(settings(napix_hash_key="12345678"), "cnr", entry.invoke, {"cnr": CNR})
    assert hidden.request_token is None and hidden.plain == shown.plain


def test_placeholders_mark_an_incomplete_request():
    entry = BY_KEY["party_name"]
    values = {"name": "", "reg_year": 2024, "pend_disp": "P"}
    p = pv.preview(settings(), "party_name", entry.invoke, values, {"litigant_name": "‹type a name›"})
    assert p.plain == "est_code=GAHC01|pend_disp=P|litigant_name=‹type a name›|reg_year=2024"
    assert not p.complete and p.placeholders == ("litigant_name",) and p.request_token is None


@pytest.mark.parametrize("n", [0, 15, 16, 100])
def test_request_str_length_matches_encryption(n):
    plain = "x" * n
    assert pv.request_str_length(plain) == len(NapixCrypto(KEY).encrypt(plain))


def test_display_url_drops_user_info():
    assert pv.display_url("https://u:p@delhigw.napix.gov.in/nic/ecourts/", "hc-cnr-api/CNR") == (
        "https://delhigw.napix.gov.in/nic/ecourts/hc-cnr-api/CNR"
    )
    assert pv.token_url("https://delhigw.napix.gov.in/nic/ecourts") == (
        "https://delhigw.napix.gov.in/nic/ecourts//oauth2/token"
    )


# ------------------------------------------------------------------------------------------------ the token


def refusing_token(gw: Gateway, status: int = 401):
    def handle(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            gw.token_calls += 1
            return httpx.Response(status, text="refused")
        return gw.handle(request)

    return handle


def test_token_request_writes_metadata_without_the_token(capsys):
    redis = RedisStub()
    gw = Gateway(NapixCrypto(KEY))
    rate = {"X-RateLimit-Limit": "1000", "X-RateLimit-Remaining": "998"}

    def with_rate(request):
        resp = gw.handle(request)
        if str(request.url) == TOKEN_URL:
            body = json.loads(resp.content) | {"token_type": "Bearer", "scope": "napix"}
            return httpx.Response(200, json=body, headers=rate)
        return resp

    client, _ = make_client(gw, TokenCache(redis_client=redis), with_rate)

    async def go():
        async with client:
            await client.call("overview/overview")

    asyncio.run(go())
    meta = TokenCache(redis_client=redis).meta()
    assert meta["ok"] == "1" and meta["http_status"] == "200" and meta["expires_in"] == "3600"
    assert meta["token_type"] == "Bearer" and meta["scope"] == "napix"
    assert meta["rate_limit_limit"] == "1000" and meta["rate_limit_remaining"] == "998"
    assert meta["obtained_at"] and meta["expires_at"] and meta["requests_today"] == "1"
    assert "tok1" not in json.dumps(meta)
    assert redis.ttl(META_KEY) > 7 * 24 * 3600 and redis.ttl(REQUESTS_KEY + _ist_date()) > 0
    assert redis.get("napix:token") == b"tok1"  # the token itself stays where it always was
    # a refused renewal: recorded as a failure; the success's issue time stays
    failing, _ = make_client(gw, TokenCache(redis_client=redis), refusing_token(gw))

    async def renew():
        async with failing:
            return await failing.renew_token()

    out = asyncio.run(renew())
    assert out.ok is False and out.http_status == 401 and out.error_family == "NapixAuthError"
    meta2 = TokenCache(redis_client=redis).meta()
    assert meta2["ok"] == "0" and meta2["last_failure_family"] == "NapixAuthError"
    assert meta2["obtained_at"] == meta["obtained_at"] and meta2["requests_today"] == "2"
    assert meta2["token_type"] == "" and meta2["rate_limit_limit"] == ""
    out_text = capsys.readouterr().out  # structlog writes to stdout
    assert out_text.count("napix token requested") == 2
    assert "tok1" not in out_text and "refused" not in out_text and "secret-test" not in out_text


def test_a_redis_error_never_fails_the_call():
    redis = RedisStub()
    redis.fail = True
    gw = Gateway(NapixCrypto(KEY))
    client, _ = make_client(gw, TokenCache(redis_client=redis))

    async def go():
        async with client:
            return await client.call("overview/overview")

    assert asyncio.run(go()).ok is True
    assert TokenCache(redis_client=redis).meta() == {}
    assert TokenCache(redis_client=redis).state().held is False


def test_renew_token_is_one_request_and_returns_no_token():
    redis = RedisStub()
    gw = Gateway(NapixCrypto(KEY))
    tokens = TokenCache(redis_client=redis)
    tokens.set("old-token", 3000)
    client, transport = make_client(gw, tokens)

    async def go():
        async with client:
            return await client.renew_token()

    out = asyncio.run(go())
    assert out.ok is True and out.http_status == 200 and out.expires_in == 3600
    assert gw.token_calls == 1 and transport.requests == 1 and gw.seen == []
    assert "tok1" not in repr(out) and not hasattr(out, "token")
    assert redis.get("napix:token") == b"tok1"  # the shared token is replaced


def test_renew_token_failure_is_an_outcome():
    for status, family in ((401, "NapixAuthError"), (500, "NapixUnavailable")):
        gw = Gateway(NapixCrypto(KEY))
        client, transport = make_client(gw, TokenCache(), refusing_token(gw, status))

        async def go(c=client):
            async with c:
                return await c.renew_token()

        out = asyncio.run(go())
        assert (out.ok, out.http_status, out.error_family) == (False, status, family)
        assert transport.requests == 1


def test_unreachable_token_service_is_an_outcome():
    def down(request):
        raise httpx.ConnectError("no route")

    client, _ = make_client(Gateway(NapixCrypto(KEY)), TokenCache(), down)

    async def go():
        async with client:
            return await client.renew_token()

    out = asyncio.run(go())
    assert out.ok is False and out.http_status is None and out.error_family == "NapixUnavailable"


def test_token_state_never_exposes_the_value():
    redis = RedisStub()
    tokens = TokenCache(redis_client=redis)
    assert tokens.state().held is False and tokens.state().shared_store is True
    tokens.set("secret-token-value", 2500)
    state = tokens.state()
    assert state.held is True and 2490 <= state.ttl_seconds <= 2500
    assert "secret-token-value" not in repr(state) and "secret-token-value" not in json.dumps(tokens.meta())
    local = TokenCache()
    local.set("secret-token-value", 100)
    assert local.state().held and local.state().shared_store is False
    assert "secret-token-value" not in repr(local.state())
