"""The token cache's "requests today" counts by the IST calendar date (design `system-health-inspector`,
decision 10; `core/clock.today_ist`), with the shared store and without it, on both sides of IST midnight
(18:30 UTC) and across UTC midnight (05:30 IST), which is inside one IST day."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aslms.integration.napix.client import REQUESTS_KEY, TokenCache, TokenRenewal
from tests.redis_stub import RedisStub

IST_MIDNIGHT = datetime(2026, 10, 24, 18, 30, tzinfo=UTC)  # 25 Oct 2026 00:00 IST
UTC_MIDNIGHT = datetime(2026, 10, 25, 0, 0, tzinfo=UTC)  # 25 Oct 2026 05:30 IST
OK = TokenRenewal(
    ok=True,
    http_status=200,
    error_family=None,
    duration_ms=100,
    expires_in=3600,
    token_type="Bearer",
    scope="napix",
)


def _cache(shared: bool) -> TokenCache:
    return TokenCache(redis_client=RedisStub()) if shared else TokenCache()


def _today(cache: TokenCache, now: datetime) -> int:
    return int(cache.meta(now).get("requests_today") or 0)


@pytest.mark.parametrize("shared", [True, False])
def test_a_request_just_before_ist_midnight_is_yesterdays(shared):
    cache = _cache(shared)
    cache.note_request(OK, now=IST_MIDNIGHT - timedelta(minutes=10))  # 23:50 IST on the 24th
    assert _today(cache, IST_MIDNIGHT - timedelta(minutes=1)) == 1  # 23:59 IST: the same day
    assert _today(cache, IST_MIDNIGHT + timedelta(minutes=1)) == 0  # 00:01 IST on the 25th: a new day
    assert cache.meta(IST_MIDNIGHT + timedelta(minutes=1))["obtained_at"]  # the last request itself stays


@pytest.mark.parametrize("shared", [True, False])
def test_a_request_just_after_ist_midnight_starts_the_new_day(shared):
    cache = _cache(shared)
    cache.note_request(OK, now=IST_MIDNIGHT - timedelta(minutes=5))  # 23:55 IST on the 24th
    cache.note_request(OK, now=IST_MIDNIGHT + timedelta(minutes=1))  # 00:01 IST on the 25th
    assert _today(cache, IST_MIDNIGHT + timedelta(minutes=9)) == 1
    cache.note_request(OK, now=IST_MIDNIGHT + timedelta(minutes=9))
    assert _today(cache, IST_MIDNIGHT + timedelta(minutes=10)) == 2


@pytest.mark.parametrize("shared", [True, False])
def test_utc_midnight_is_inside_one_ist_day(shared):
    cache = _cache(shared)
    cache.note_request(OK, now=UTC_MIDNIGHT - timedelta(minutes=30))  # 05:00 IST, 24 Oct UTC
    cache.note_request(OK, now=UTC_MIDNIGHT + timedelta(minutes=30))  # 06:00 IST, 25 Oct UTC
    assert _today(cache, UTC_MIDNIGHT + timedelta(minutes=31)) == 2


def test_the_day_counter_key_is_the_ist_date():
    redis = RedisStub()
    TokenCache(redis_client=redis).note_request(OK, now=IST_MIDNIGHT + timedelta(minutes=1))
    assert redis.get(REQUESTS_KEY + "2026-10-25") == b"1" and redis.get(REQUESTS_KEY + "2026-10-24") is None
