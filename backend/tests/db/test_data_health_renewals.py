"""A token renewal's 401 step is a call, never a failure (design `followups-oct`, decision 8): the data-health NAPIX
block (today, the quota window card and the per-person counts), the data-health report, the load report and the ops
metric leave it out of every failure reading and keep it in every call count, as System health already does."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa

from aslms.core.config import Settings
from aslms.domain.ops import NapixCallLog
from aslms.services import data_health, load_report, napix_window, ops_metrics, reports
from tests.db.conftest import wipe

# 15 Sep 2026, 10:20 IST
NOW = datetime(2026, 9, 15, 4, 50, tzinfo=UTC)
TODAY = date(2026, 9, 15)
SETTINGS = Settings(_env_file=None, app_env="test", redis_url=None)


def _call(s, at, *, ok, http_status, family=None, api="hc-cnr-api/CNR", **kw):
    s.add(
        NapixCallLog(
            api=api,
            params_sha256="0" * 64,
            ok=ok,
            http_status=http_status,
            error_family=family,
            called_at=at,
            duration_ms=100,
            **kw,
        )
    )
    s.flush()


def _seed(s, now, **kw):
    """Two good calls, one renewal (401 then the repeated call, which succeeded), one real 401 failure with a family,
    one gateway failure. The renewal step is the newest failure-looking row, so `last_failure` must skip it. `kw`
    (a `user_id`) goes on every row."""
    _call(s, now - timedelta(minutes=30), ok=True, http_status=200, **kw)
    _call(s, now - timedelta(minutes=20), ok=False, http_status=503, family="NapixUnavailable", **kw)
    _call(s, now - timedelta(minutes=15), ok=False, http_status=401, family="NapixAuthError", **kw)
    _call(s, now - timedelta(minutes=5), ok=False, http_status=401, **kw)  # the renewal step
    _call(s, now - timedelta(minutes=5) + timedelta(seconds=1), ok=True, http_status=200, **kw)  # its repeat


def test_renewal_step_counts_as_call_not_failure(session):
    wipe(session)
    _seed(session, NOW)
    block = data_health.napix_health(session, SETTINGS, NOW)
    assert block["today"]["calls"] == 5, "the renewal step stays a call"
    assert block["today"]["failed"] == 2
    assert block["today"]["by_family"] == {"NapixAuthError": 1, "NapixUnavailable": 1}
    assert "unknown" not in block["today"]["by_family"]
    last = block["last_failure"]
    assert (last["http_status"], last["error_family"]) == (401, "NapixAuthError")
    # equals the Verification step's SQL
    expected = session.scalar(
        sa.text(
            "SELECT count(*) FROM napix_call_log WHERE called_at >= :d AND NOT ok "
            "AND NOT (http_status = 401 AND error_family IS NULL)"
        ),
        {"d": NOW - timedelta(hours=10, minutes=20)},
    )
    assert block["today"]["failed"] == expected


def test_a_null_status_failure_is_still_counted(session):
    """`renewal_step()` is two-valued: a failure without an HTTP status (a timeout) is a failure, not dropped by a
    NULL comparison."""
    wipe(session)
    _call(session, NOW - timedelta(minutes=1), ok=False, http_status=None, family="NapixTimeout")
    block = data_health.napix_health(session, SETTINGS, NOW)
    assert block["today"]["failed"] == 1
    assert block["today"]["by_family"] == {"NapixTimeout": 1}


def test_report_failures_skip_renewals(world):
    with world.Session() as s:
        _seed(s, NOW)
        report, _scope = reports.build(
            s, world.user(s, "central_op"), "data-health", from_=TODAY, to=TODAY, settings=SETTINGS
        )
        sections = {sec["key"]: sec for sec in report.to_dict()["sections"]}
        day = {r["date"]: r for r in sections["by_date"]["rows"]}[TODAY]
        assert (day["napix_calls"], day["napix_failed"]) == (5, 2)
        assert day["napix_error_families"] == "NapixAuthError 1, NapixUnavailable 1"
        api = {r["api"]: r for r in sections["napix_by_api"]["rows"]}["hc-cnr-api/CNR"]
        assert (api["calls"], api["failed"]) == (5, 2)
        s.rollback()


def test_ops_metric_has_renewal_series_and_total_is_unchanged(session):
    wipe(session)
    now = datetime.now(UTC)
    _seed(session, now)
    session.execute(sa.text("SET LOCAL ROLE aslms_readonly"))
    samples, _ = ops_metrics.collect_database(session, SETTINGS, now)
    calls = {s.labels["outcome"]: s.value for s in samples if s.name == "aslms_napix_calls_last_hour"}
    assert calls == {"ok": 2, "failed": 2, "renewal": 1}
    assert sum(calls.values()) == 5, "ok + failed + renewal is every call"


def test_window_and_by_user_failures_skip_renewals(world):
    """The data-health window card (`napix.window.failed`) and the per-person columns (`by_user.window` and
    `by_user.today`) count the renewal step as a call and not as a failure (decision 8, owner answer 5)."""
    anchor = NOW - timedelta(minutes=50)  # a precise reset 50 minutes ago: the window is current
    with world.Session() as s:
        s.execute(sa.delete(NapixCallLog))
        op = world.user(s, "central_op")
        _call(s, anchor - timedelta(seconds=20), ok=True, http_status=200, rate_limit_remaining=160)
        _call(s, anchor, ok=True, http_status=200, rate_limit_remaining=999)
        _seed(s, NOW, user_id=op.id)
        block = data_health.napix_health(s, SETTINGS, NOW, operator=True)
        w = block["window"]
        assert w["status"] == "current"
        assert (w["calls"], w["failed"]) == (6, 2), (
            "the reset reading and the five seeded calls; renewal not failed"
        )
        assert napix_window.calls_since(s, anchor) == {"calls": 6, "failed": 2}
        person = {"user_id": op.id, "name": op.full_name, "calls": 5, "failed": 2}
        assert block["by_user"]["window"] == [person]
        assert block["by_user"]["today"] == [person]
        s.rollback()


def test_load_report_counts_renewal_apart(session):
    """The load report's calls by outcome name the renewal step `renewal`, never an `error`."""
    wipe(session)
    _seed(session, NOW)
    r = load_report.report(session, now=NOW)
    assert r["napix_calls"]["total"] == 5
    assert r["napix_calls"]["by_outcome"] == {
        "NapixAuthError": 1,
        "NapixUnavailable": 1,
        "ok": 2,
        "renewal": 1,
    }
