"""The live data-health view (design `audit-screens`, decisions 5 and 7): every figure of the snapshot equals the
seeded rows; the NAPIX block's hour, last failure and last check; the queue and call lists; the failure list
through the document visibility rule; the period report unchanged by the shared daily-cycle helper."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa

from aslms.core.config import Settings
from aslms.domain.alerts import Alert, Digest, Notification, NotificationStatus
from aslms.domain.causelists import Causelist, ListSource, ListType, ParseStatus
from aslms.domain.courts import Court, MasterKind, MasterSyncRun
from aslms.domain.documents import DocGroup, DocKind, Visibility
from aslms.domain.ops import (
    FetchKind,
    FetchQueueItem,
    FetchStatus,
    JobRun,
    JobStatus,
    NapixCallLog,
    SourceFailure,
)
from aslms.domain.org import Channel, PermissionEffect
from aslms.domain.reference import AlertKind, Permission, RecordType
from aslms.services import access, data_health, reports
from aslms.services.audit_search import AuditInputError
from aslms.services.court_search import latest_remaining_this_hour
from aslms.services.refno import allocate_ref_no
from aslms.services.reporting_common import IST_ZONE
from aslms.services.storage import LocalStore
from tests.db import st_support as h
from tests.db.world import make_case

# a fixed "now" in the past: 15 Sep 2026, 10:20 IST
NOW = datetime(2026, 9, 15, 4, 50, tzinfo=UTC)
TODAY = date(2026, 9, 15)
SETTINGS = Settings(_env_file=None, redis_url=None)
OLDEST_QUEUED = NOW - timedelta(hours=3)
FIRST_SEEN = NOW - timedelta(days=3)


def _q(s, kind, ref, status, **kw):
    row = FetchQueueItem(kind=kind, ref=ref, status=status, priority=kw.pop("priority", 50), **kw)
    s.add(row)
    s.flush()
    return row


def _call(s, at, *, ok=True, api="hc-cnr-api/CNR", family=None, verified=True, remaining=None, **kw):
    row = NapixCallLog(
        api=api,
        params_sha256="0" * 64,
        ok=ok,
        error_family=family,
        token_verified=verified,
        rate_limit_remaining=remaining,
        called_at=at,
        duration_ms=kw.pop("duration_ms", 100),
        http_status=kw.pop("http_status", 200 if ok else 503),
        **kw,
    )
    s.add(row)
    s.flush()
    return row


def _seed(s, world) -> None:
    D = FetchKind
    S = FetchStatus
    _q(s, D.MASTERS, "all", S.DONE)
    _q(s, D.CAUSELIST_DAY, "2026-09-14", S.DONE, attempts=1, finished_at=NOW - timedelta(hours=10))
    _q(s, D.CAUSELIST_DAY, "2026-09-15", S.FAILED, attempts=5, last_error="gateway down")
    _q(s, D.CAUSELIST_DAY, "2026-09-16", S.PENDING, created_at=NOW - timedelta(days=2))  # oldest runnable
    _q(s, D.CAUSELIST_DAY, "2025-01-06", S.PENDING, not_before=NOW + timedelta(hours=1))  # waiting
    _q(s, D.DOSSIER, "ASHC010000012025", S.RUNNING, started_at=NOW - timedelta(minutes=31))  # stale
    _q(s, D.DOSSIER, "ASHC010000022025", S.RUNNING, started_at=NOW - timedelta(minutes=5))
    _q(s, D.DOSSIER, "ASHC010000032025", S.SKIPPED)
    _q(s, D.DOSSIER, "ASHC010000042025", S.FAILED)
    _q(s, D.STATUS_BATCH, "2026-09-14:1", S.DONE)
    _q(s, D.STATUS_BATCH, "2026-09-15:1", S.DONE)
    _q(s, D.STATUS_BATCH, "2026-09-15:2", S.FAILED)
    _q(s, D.STATUS_BATCH, "2026-09-15:3", S.PENDING)
    _q(s, D.ORDER_PDF, "ASHC010000012025|1|2025-01-10", S.PENDING)
    _q(s, D.ORDER_PDF, "ASHC010000012025|2|2025-01-11", S.DONE)
    court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
    for bench, n, parse in ((1, 10, ParseStatus.PARSED), (2, 5, ParseStatus.FAILED)):
        s.add(
            Causelist(
                court_id=court.id,
                list_date=date(2026, 9, 14),
                bench_id=bench,
                list_type=ListType.DAILY,
                source=ListSource.NAPIX,
                parse_status=parse,
                entry_count=n,
            )
        )
    hour = NOW.replace(minute=0)
    _call(s, hour + timedelta(minutes=1), remaining=900)
    _call(s, hour + timedelta(minutes=2), verified=False)
    _call(s, hour + timedelta(minutes=3), ok=False, family="NapixUnavailable")
    _call(s, datetime(2026, 9, 14, 20, 0, tzinfo=UTC), ok=False, family="NapixProtocolError")  # 01:30 IST
    _call(s, datetime(2026, 9, 14, 19, 0, tzinfo=UTC), api="overview/overview")  # 00:30 IST: the last check
    _call(s, datetime(2026, 9, 14, 10, 0, tzinfo=UTC), ok=False, family="NapixAuthError")  # yesterday
    s.add(JobRun(job="daily_cycle", started_at=NOW - timedelta(days=1), status=JobStatus.SUCCEEDED))
    s.add(
        JobRun(
            job="daily_cycle",
            started_at=NOW - timedelta(hours=2),
            status=JobStatus.PARTIAL,
            counters={"n": 2},
        )
    )
    s.add(JobRun(job="old_job", started_at=NOW - timedelta(days=40), status=JobStatus.FAILED))
    s.add(MasterSyncRun(master=MasterKind.STATE, fetched_at=NOW - timedelta(days=8), row_count=30))
    s.add(MasterSyncRun(master=MasterKind.STATE, fetched_at=NOW - timedelta(days=1), row_count=31))
    s.add(MasterSyncRun(master=MasterKind.BENCH, fetched_at=NOW - timedelta(days=1), row_count=80))
    case = make_case(s)
    alert = Alert(
        case_id=case.id,
        kind=AlertKind.HEARING_DUE,
        office_id=world.office(s, "EDU").id,
        title="Hearing",
        dedupe_key="dh-test",
        ref_no=allocate_ref_no(s, "GOA", RecordType.ALR.value),
    )
    s.add(alert)
    s.flush()
    off1, off2 = world.users["edu_off1"].id, world.users["edu_off2"].id
    for n, (user_id, channel, status, created) in enumerate(
        (
            (off1, Channel.EMAIL, NotificationStatus.QUEUED, OLDEST_QUEUED),
            (off2, Channel.EMAIL, NotificationStatus.QUEUED, NOW - timedelta(hours=1)),
            (off1, Channel.EMAIL, NotificationStatus.FAILED, NOW),
            (off2, Channel.EMAIL, NotificationStatus.SENT, NOW),
            (off1, Channel.IN_APP, NotificationStatus.SENT, NOW),
        )
    ):
        s.add(
            Notification(
                alert_id=alert.id,
                user_id=user_id,
                channel=channel,
                status=status,
                created_at=created,
                title="Hearing",
                dedupe_key=f"dh-test:{n}",
            )
        )
    s.add(Digest(user_id=off1, digest_date=TODAY, status=NotificationStatus.QUEUED))
    s.add(Digest(user_id=off2, digest_date=TODAY, status=NotificationStatus.FAILED))
    s.add(Digest(user_id=off2, digest_date=TODAY - timedelta(days=1), status=NotificationStatus.SENT))
    s.add(SourceFailure(kind="scoring", ref="x1", first_seen=FIRST_SEEN, last_seen=NOW))
    s.add(SourceFailure(kind="scoring", ref="x2", first_seen=NOW, last_seen=NOW))
    s.add(SourceFailure(kind="scoring", ref="x3", first_seen=NOW, last_seen=NOW, resolved_at=NOW))
    s.add(SourceFailure(kind="document_missing", ref="nothing", first_seen=NOW, last_seen=NOW))
    s.flush()


def _ist(dt: datetime) -> datetime:
    return dt.astimezone(IST_ZONE)


def test_snapshot_counts_exact(world):
    with world.Session() as s:
        _seed(s, world)
        snap = data_health.snapshot(s, world.user(s, "central_op"), SETTINGS, now=NOW)
        by_kind = {k["kind"]: k for k in snap["queue"]["by_kind"]}
        zero = dict.fromkeys(
            ("pending", "runnable", "waiting", "running", "stale", "failed", "skipped", "done"), 0
        )
        assert by_kind["masters"] == {**zero, "kind": "masters", "done": 1}
        assert by_kind["causelist_day"] == {
            **zero,
            "kind": "causelist_day",
            "pending": 2,
            "runnable": 1,
            "waiting": 1,
            "failed": 1,
            "done": 1,
        }
        assert by_kind["dossier"] == {
            **zero,
            "kind": "dossier",
            "running": 2,
            "stale": 1,
            "skipped": 1,
            "failed": 1,
        }
        assert by_kind["status_batch"] == {
            **zero,
            "kind": "status_batch",
            "pending": 1,
            "runnable": 1,
            "failed": 1,
            "done": 2,
        }
        assert by_kind["order_pdf"] == {**zero, "kind": "order_pdf", "pending": 1, "runnable": 1, "done": 1}
        assert snap["queue"]["failed_total"] == 3
        assert snap["queue"]["oldest_runnable_at"] == _ist(NOW - timedelta(days=2))
        # the daily cycle
        cycle = {d["label"]: d for d in snap["daily_cycle"]}
        assert [d["date"] for d in snap["daily_cycle"]] == [date(2026, 9, 14), TODAY, date(2026, 9, 16)]
        assert cycle["yesterday"]["causelist_day"]["status"] == "done"
        assert cycle["yesterday"]["causelist_day"]["attempts"] == 1
        assert cycle["yesterday"]["causelist_day"]["finished_at"] == _ist(NOW - timedelta(hours=10))
        assert (cycle["yesterday"]["lists_stored"], cycle["yesterday"]["entries_parsed"]) == (2, 15)
        assert cycle["yesterday"]["lists_parse_failed"] == 1
        assert cycle["today"]["causelist_day"] == {
            "status": "failed",
            "attempts": 5,
            "finished_at": None,
            "last_error": "gateway down",
        }
        assert cycle["today"]["lists_stored"] == 0
        assert cycle["tomorrow"]["causelist_day"]["status"] == "pending"
        assert snap["status_batches"] == {"date": TODAY, "done": 1, "failed": 1, "pending": 1, "running": 0}
        # NAPIX
        napix = snap["napix"]
        assert (napix["hour"]["calls"], napix["hour"]["failed"]) == (3, 1)
        assert napix["today"] == {
            "calls": 5,
            "failed": 2,
            "by_family": {"NapixProtocolError": 1, "NapixUnavailable": 1},
            "token_unverified": 1,
        }
        assert napix["hour"]["latest_remaining"] == latest_remaining_this_hour(s)
        assert napix["enabled"] is False and napix["est_code"] == "GAHC01"
        # masters, jobs, mail, failures
        assert {m["master"]: m["row_count"] for m in snap["masters"]} == {"state": 31, "bench": 80}
        assert [(j["job"], j["status"], j["counters"]) for j in snap["jobs"]] == [
            ("daily_cycle", "partial", {"n": 2})
        ]
        assert snap["mail"] == {
            "email_queued": 2,
            "email_failed": 1,
            "email_oldest_queued_at": _ist(OLDEST_QUEUED),
            "digests_queued": 1,
            "digests_failed": 1,
        }
        assert snap["failures"] == [
            {"kind": "document_missing", "open": 1, "oldest_first_seen": _ist(NOW)},
            {"kind": "scoring", "open": 2, "oldest_first_seen": _ist(FIRST_SEEN)},
        ]
        assert set(snap["sourcetrace"]) >= {"state", "counts", "waiting_cnr", "due_now"}
        assert snap["as_of"] == _ist(NOW)
        s.rollback()


def test_napix_health_hour_and_last_failure(world):
    now = datetime.now(UTC)
    hour = now.replace(minute=0, second=0, microsecond=0)
    with world.Session() as s:
        _call(s, hour - timedelta(seconds=1), remaining=10)  # last hour: not this hour's remaining
        _call(s, hour, remaining=640)
        _call(s, hour, ok=False, family="NapixUnavailable", napix_status=None)
        fail = _call(s, hour - timedelta(minutes=30), ok=False, family="NapixProtocolError", napix_status=628)
        check = _call(
            s, hour - timedelta(minutes=40), api="overview/overview", verified=True, duration_ms=321
        )
        block = data_health.napix_health(s, SETTINGS, now)
        assert block["hour"]["latest_remaining"] == 640
        assert block["hour"]["calls"] == 2 and block["hour"]["failed"] == 1
        assert block["hour"]["reserve"] == SETTINGS.napix_rate_reserve
        assert block["hour"]["search_floor"] == SETTINGS.napix_search_floor
        assert 1 <= block["hour"]["seconds_to_next_hour"] <= 3600
        # the latest failure is this hour's (same time, newest id)
        assert block["last_failure"]["error_family"] == "NapixUnavailable"
        assert block["last_check"] == {
            "called_at": _ist(check.called_at),
            "ok": True,
            "duration_ms": 321,
            "token_verified": True,
            "error_family": None,
        }
        assert block["last_call_at"] == _ist(hour) and block["last_ok_at"] == _ist(hour)
        assert fail.napix_status == 628
        s.rollback()


def test_queue_list_filters_and_total(world):
    with world.Session() as s:
        _seed(s, world)
        items, total = data_health.queue_rows(s, kind=FetchKind.DOSSIER)
        assert total == 4 and {i["ref"] for i in items} == {f"ASHC0100000{n}2025" for n in range(1, 5)}
        items, total = data_health.queue_rows(s, status=FetchStatus.FAILED)
        assert total == 3 and {i["kind"] for i in items} == {"causelist_day", "dossier", "status_batch"}
        items, total = data_health.queue_rows(s, kind=FetchKind.STATUS_BATCH, ref_prefix="2026-09-15:")
        assert total == 3
        items, total = data_health.queue_rows(s, ref_prefix="ASHC010000012025|", limit=1, offset=1)
        assert total == 2 and len(items) == 1
        items, total = data_health.queue_rows(s, ref_prefix="%")  # a literal percent sign
        assert total == 0
        s.rollback()


def test_calls_list_never_returns_params(world):
    with world.Session() as s:
        _seed(s, world)
        items, cursor = data_health.call_rows(s, now=NOW)  # default: today (IST)
        assert len(items) == 5 and cursor is None
        assert all("params" not in i and "params_sha256" not in i for i in items)
        assert [i["called_at"] for i in items] == sorted((i["called_at"] for i in items), reverse=True)
        failed, _ = data_health.call_rows(s, from_=date(2026, 9, 14), to=TODAY, ok=False, now=NOW)
        assert {i["error_family"] for i in failed} == {
            "NapixUnavailable",
            "NapixProtocolError",
            "NapixAuthError",
        }
        overview, _ = data_health.call_rows(s, api="overview", now=NOW)
        assert [i["api"] for i in overview] == ["overview/overview"]
        page1, cur = data_health.call_rows(s, limit=2, now=NOW)
        page2, cur2 = data_health.call_rows(s, limit=2, cursor=cur, now=NOW)
        page3, cur3 = data_health.call_rows(s, limit=2, cursor=cur2, now=NOW)
        ids = [i["id"] for i in page1 + page2 + page3]
        assert len(ids) == len(set(ids)) == 5 and cur3 is None
        with pytest.raises(AuditInputError):
            data_health.call_rows(s, from_=TODAY, to=date(2026, 9, 1), now=NOW)
        s.rollback()


def test_failures_document_kinds_follow_document_visibility(world, tmp_path):
    store = LocalStore(tmp_path / "store")
    with world.Session() as s:
        case = make_case(s)
        actor, admin = world.actor(s, "edu_admin")
        from aslms.services import ownership as own

        own.claim(s, actor, admin, case)
        private = h.upload_row(
            s, store, case, world.office(s, "EDU"), visibility=Visibility.PRIVATE_TO_OFFICE
        )
        caseless = h.upload_row(
            s,
            store,
            case,
            world.office(s, "EDU"),
            kind=DocKind.ADMIN,
            group=DocGroup.INTERNAL,
            visibility=Visibility.PRIVATE_TO_OFFICE,
            text="admin paper",
        )
        for kind, ref in (
            ("text_extraction", str(private.id)),
            ("sourcetrace_ingestion", str(caseless.id)),
            ("scoring", "not-a-document"),
        ):
            s.add(SourceFailure(kind=kind, ref=ref))
        root_actor, root = world.actor(s, "root")
        access.set_override(
            s,
            root_actor,
            root,
            world.user(s, "health_off"),
            Permission.REPORTS_STATE,
            PermissionEffect.GRANT,
            reason="t",
        )
        s.flush()
        refs = lambda key: {i["ref"] for i in data_health.failure_rows(s, world.user(s, key))[0]}  # noqa: E731
        assert refs("root") == {str(private.id), str(caseless.id), "not-a-document"}
        assert refs("health_off") == {"not-a-document"}
        # the EDU admin sees the private filing of the EDU office; never the case-less document
        assert refs("edu_admin") == {str(private.id), "not-a-document"}
        # central operator: State-wide, every document that has a case
        assert refs("central_op") == {str(private.id), "not-a-document"}
        items, total = data_health.failure_rows(s, world.user(s, "health_off"), kind="text_extraction")
        assert (items, total) == ([], 0)
        s.rollback()


def test_reports_data_health_unchanged(world):
    """The shared daily-cycle helper: the report's per-day causelist columns are exactly the seeded figures."""
    with world.Session() as s:
        _seed(s, world)
        report, _scope = reports.build(
            s,
            world.user(s, "central_op"),
            "data-health",
            from_=date(2026, 9, 14),
            to=TODAY,
            settings=SETTINGS,
        )
        rows = {r["date"]: r for r in report.to_dict()["sections"][0]["rows"]}
        y, t = rows[date(2026, 9, 14)], rows[TODAY]
        assert (y["causelist_day_status"], y["causelist_day_attempts"]) == ("done", 1)
        assert (y["lists_stored"], y["entries_parsed"], y["lists_parse_failed"]) == (2, 15, 1)
        assert (t["causelist_day_status"], t["causelist_day_attempts"]) == ("failed", 5)
        assert (t["lists_stored"], t["entries_parsed"], t["lists_parse_failed"]) == (0, 0, 0)
        assert (t["status_batches_done"], t["status_batches_failed"]) == (1, 1)
        s.rollback()


def test_cli_data_health_prints_the_snapshot(world, monkeypatch):
    import json
    from contextlib import contextmanager

    import typer
    from typer.testing import CliRunner

    from aslms.cli import audit as cli

    with world.Session() as s:
        _seed(s, world)
        s.commit()

    @contextmanager
    def scope():
        s = world.Session()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr(cli, "session_scope", scope)
    monkeypatch.setattr(cli, "get_settings", lambda: SETTINGS)
    app = typer.Typer()
    app.command("data-health")(cli.data_health_cmd)
    app.command("search")(cli.search)
    r = CliRunner().invoke(app, ["data-health"])
    assert r.exit_code == 0, r.output
    snap = json.loads(r.output)
    assert {k["kind"]: k["failed"] for k in snap["queue"]["by_kind"]}["dossier"] == 1
    r = CliRunner().invoke(app, ["search", "--action", "napix.", "--limit", "5"])
    assert r.exit_code == 0, r.output
