"""Data Collection redesign, round 1 (design `data-collection-redesign`, decisions 14-21 and 40): the Overview's
honest counts across every lane, where the past-months collection is, the collection's state, the problem counts,
the live pulse, the month table's additive figures by each column's own date, the two-date estimate over every lane,
the plain schedule and the `admin.data_load` description. Every figure is compared with the seed."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa

from aslms.core.config import Settings
from aslms.domain.causelists import (
    Causelist,
    CauselistEntry,
    EntrySource,
    ListSource,
    ListType,
    ParseStatus,
    ResolutionStatus,
)
from aslms.domain.courts import Court
from aslms.domain.documents import DownloadStatus, Order, OrderKind
from aslms.domain.events import AuditLog
from aslms.domain.ops import (
    FetchKind,
    FetchLane,
    FetchQueueItem,
    FetchStatus,
    JobRun,
    JobStatus,
    NapixCallLog,
    SourceFailure,
)
from aslms.domain.org import PermissionEffect
from aslms.domain.reference import Permission, RefPermission
from aslms.services import access, case_dedupe, data_load, schedules
from tests.db import docs_support as ds
from tests.db.world import make_case

CFG = Settings(_env_file=None)
NOW = datetime(2025, 1, 10, 6, 0, tzinfo=UTC)  # 11:30 IST on 10 Jan 2025


def _put(s, kind: FetchKind, ref: str, status: FetchStatus, *, lane=FetchLane.LOAD, priority=46, **kw):
    row = FetchQueueItem(kind=kind, ref=ref, status=status, lane=lane, priority=priority, **kw)
    s.add(row)
    s.flush()
    return row


def _day(s, d: date, status: FetchStatus, *, lane=FetchLane.LOAD, **kw):
    return _put(s, FetchKind.CAUSELIST_DAY, d.isoformat(), status, lane=lane, list_date=d, **kw)


def _order(s, case, no: str, d: date, status: DownloadStatus, document_id=None):
    s.add(
        Order(
            case_id=case.id,
            order_no=no,
            order_date=d,
            kind=OrderKind.INTERIM,
            download_status=status,
            document_id=document_id,
        )
    )
    s.flush()


def _stored_doc(s, tmp_path, d: date):
    from aslms.services.causelists import store_pdf
    from aslms.services.storage import LocalStore

    doc, _ = store_pdf(
        s, LocalStore(str(tmp_path / "store")), f"%PDF-1.4 {d}".encode(), doc_date=d, description="t"
    )
    return doc


def _call(s, at: datetime, *, lane=None, api="hc-cnr-api/CNR", remaining=None):
    s.add(
        NapixCallLog(
            api=api, params_sha256="c" * 64, ok=True, lane=lane, rate_limit_remaining=remaining, called_at=at
        )
    )


def _list(s, d: date, cases) -> Causelist:
    court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
    cl = Causelist(
        court_id=court.id,
        list_date=d,
        list_type=ListType.DAILY,
        source=ListSource.NAPIX,
        parse_status=ParseStatus.PARSED,
    )
    s.add(cl)
    s.flush()
    for i, case in enumerate(cases):
        s.add(
            CauselistEntry(
                causelist_id=cl.id,
                sr_no=i + 1,
                case_id=case.id,
                case_no_text=case.case_no_text,
                source=EntrySource.PDF_PARSE,
                resolution_status=ResolutionStatus.RESOLVED,
            )
        )
    s.flush()
    return cl


# ------------------------------------------------------------------------------------------------ overview


def test_overview_counts_days_cases_and_orders_of_the_period(world, tmp_path):
    with world.Session() as s:
        _day(s, date(2025, 1, 1), FetchStatus.DONE)
        _day(s, date(2025, 1, 2), FetchStatus.SKIPPED)
        _day(s, date(2025, 1, 3), FetchStatus.PENDING)
        _day(s, date(2025, 1, 4), FetchStatus.FAILED)
        _day(s, date(2025, 1, 5), FetchStatus.PENDING)
        # the daily cycle collected today's list: a day of the period up to today, whatever its lane
        _day(s, date(2025, 1, 10), FetchStatus.DONE, lane=FetchLane.DAILY)
        a = make_case(s)
        a.last_full_refresh_at = NOW
        b = make_case(s)
        merged = make_case(s)
        merged.merged_into_case_id = a.id
        prov = make_case(s)
        prov.is_provisional = True
        doc = _stored_doc(s, tmp_path, date(2025, 1, 2))
        _order(s, a, "1", date(2025, 1, 2), DownloadStatus.STORED, doc.id)
        _order(s, a, "2", date(2025, 1, 3), DownloadStatus.PENDING)
        _order(s, a, "3", date(2024, 11, 3), DownloadStatus.PENDING)  # before the period
        _order(s, b, "1", date(2025, 1, 4), DownloadStatus.NOT_AVAILABLE)
        _order(s, b, "2", date(2025, 1, 9), DownloadStatus.FAILED)  # after the load period's last day
        ov = data_load.overview(s, CFG, NOW)
        assert ov["period"] == {"from": date(2025, 1, 1), "to": date(2025, 1, 5)}
        assert ov["days"] == {
            "calendar": 10,
            "with_lists": 2,
            "no_list": 1,
            "waiting": 2,
            "failed": 1,
            "not_queued": 4,
            "collected": 3,
            "to": date(2025, 1, 10),
        }
        assert ov["cases"] == {"found": 3, "with_details": 1, "without_details": 2, "provisional": 1}
        orders = ov["orders"]
        assert {k: orders[k] for k in ("referenced", "stored", "waiting", "not_available", "failed")} == {
            "referenced": 5,
            "stored": 1,
            "waiting": 2,
            "not_available": 1,
            "failed": 1,
        }
        assert orders["in_period"] == {
            "referenced": 3,
            "stored": 1,
            "not_available": 1,
            "waiting": 1,
            "failed": 0,
        }
        assert ov["bulk"] is None and ov["napix_enabled"] is False
        s.rollback()


def test_overview_left_counts_order_pdfs_in_every_lane(world):
    with world.Session() as s:
        for i, (lane, status) in enumerate(
            (
                (FetchLane.DAILY, FetchStatus.PENDING),
                (FetchLane.DAILY, FetchStatus.PENDING),
                (FetchLane.LOAD, FetchStatus.PENDING),
                (FetchLane.REQUEST, FetchStatus.PENDING),
                (FetchLane.DAILY, FetchStatus.RUNNING),
                (FetchLane.DAILY, FetchStatus.DONE),
                (FetchLane.LOAD, FetchStatus.FAILED),
            )
        ):
            _put(s, FetchKind.ORDER_PDF, f"GAHC010000012025|{i}|2025-01-01", status, lane=lane, priority=60)
        _put(
            s, FetchKind.DOSSIER, "GAHC010000022025", FetchStatus.PENDING, lane=FetchLane.REQUEST, priority=30
        )
        _put(
            s, FetchKind.STATUS_BATCH, "2025-01-10:1", FetchStatus.PENDING, lane=FetchLane.DAILY, priority=50
        )
        _day(s, date(2025, 1, 3), FetchStatus.PENDING)
        ov = data_load.overview(s, CFG, NOW)
        assert ov["left"] == {
            "causelist_days": 1,
            "case_details": 1,
            "order_pdfs": 5,
            "other": 1,
            "total": 8,
        }
        pdf = next(r for r in ov["waiting_work"] if r["kind"] == "order_pdf")
        assert pdf == {
            "kind": "order_pdf",
            "total": 4,
            "by_lane": {"request": 1, "daily": 2, "discovery": 0, "load": 1},
            "running": 1,
            "failed": 1,
        }
        assert [r["kind"] for r in ov["waiting_work"]] == [
            "causelist_day",
            "dossier",
            "status_batch",
            "order_pdf",
        ]
        s.rollback()


def test_overview_position_is_the_earliest_waiting_load_day(world):
    with world.Session() as s:
        assert data_load.position(s) == {"working_on": None, "working_on_month": None}
        _day(s, date(2025, 3, 1), FetchStatus.DONE)
        _day(s, date(2025, 3, 5), FetchStatus.PENDING)
        _day(s, date(2025, 4, 2), FetchStatus.RUNNING)
        _day(s, date(2025, 2, 1), FetchStatus.PENDING, lane=FetchLane.DAILY)  # not the load
        _day(s, date(2025, 2, 2), FetchStatus.FAILED)  # not waiting
        assert data_load.overview(s, CFG, NOW)["position"] == {
            "working_on": date(2025, 3, 5),
            "working_on_month": "2025-03",
        }
        s.rollback()


def test_overview_states_running_paused_finished_not_started_and_gateway_off(world):
    from aslms.cli.data_load import status_lines

    with world.Session() as s:
        actor, root = world.actor(s, "root")
        ov = data_load.overview(s, CFG, NOW)
        assert ov["collection"] == "not_started" and ov["days"] is None
        assert ov["napix_enabled"] is False
        row = _day(s, date(2025, 1, 3), FetchStatus.PENDING)
        ov = data_load.overview(s, CFG, NOW)
        assert ov["collection"] == "running"
        # the connection is off: no date, with the reason
        assert ov["estimate"]["details"]["reason"] == "connection_off"
        lines = status_lines(ov)
        assert lines[0].startswith("Automatic collection: running, working on 2025-01; court connection off")
        assert "Cause lists and case details: no date: the court connection is off" in lines
        data_load.pause(s, actor, root, "verification")
        assert data_load.overview(s, CFG, NOW)["collection"] == "paused"
        data_load.resume(s, actor, root)
        row.status = FetchStatus.DONE
        s.flush()
        assert data_load.overview(s, CFG, NOW)["collection"] == "finished"
        s.rollback()


def test_overview_problem_counts(world):
    with world.Session() as s:
        _put(s, FetchKind.DOSSIER, "GAHC010000022025", FetchStatus.FAILED, lane=FetchLane.DAILY)
        _day(s, date(2025, 1, 4), FetchStatus.FAILED)
        s.add(SourceFailure(kind=case_dedupe.FAILURE_KIND, ref="a|b", error="same number"))
        s.add(SourceFailure(kind=case_dedupe.FAILURE_KIND, ref="c|d", resolved_at=NOW))
        s.add(SourceFailure(kind="order_pdf", ref="x"))
        a = make_case(s)
        a.last_full_refresh_at = NOW
        b = make_case(s)
        make_case(s)
        _order(s, b, "1", date(2025, 1, 4), DownloadStatus.NOT_AVAILABLE)
        _order(s, b, "2", date(2025, 1, 5), DownloadStatus.FAILED)
        _order(s, b, "3", date(2025, 1, 6), DownloadStatus.PENDING)
        assert data_load.overview(s, CFG, NOW)["problems"] == {
            "failed": 2,
            "duplicates_review": 1,
            "cases_without_details": 2,
            "orders_not_available": 1,
            "orders_failed": 1,
        }
        s.rollback()


def test_overview_orders_in_period_and_all_add_up(world):
    with world.Session() as s:
        _day(s, date(2025, 1, 1), FetchStatus.DONE)
        _day(s, date(2025, 2, 28), FetchStatus.PENDING)
        case = make_case(s)
        for i, (d, st) in enumerate(
            (
                (date(2024, 6, 1), DownloadStatus.PENDING),
                (date(2024, 12, 31), DownloadStatus.NOT_AVAILABLE),
                (date(2025, 1, 15), DownloadStatus.PENDING),
                (date(2025, 2, 1), DownloadStatus.FAILED),
                (date(2025, 3, 2), DownloadStatus.PENDING),
            )
        ):
            _order(s, case, str(i), d, st)
        today = date(2025, 3, 10)
        now = datetime(2025, 3, 10, 6, 0, tzinfo=UTC)
        ov = data_load.overview(s, CFG, now)
        view = data_load.coverage_view(s, CFG, today=today)
        assert [m["month"] for m in view["months"]] == ["2025-01", "2025-02", "2025-03"]
        known = ov["orders"]["referenced"]
        assert known == 5 and ov["orders"]["in_period"]["referenced"] == 2
        assert view["earlier_orders"]["referenced"] == 2
        for key in ("referenced", "waiting", "not_available", "failed", "stored"):
            months = sum(m["orders"][key] for m in view["months"])
            assert months + view["earlier_orders"][key] == ov["orders"][key], key
        s.rollback()


# ------------------------------------------------------------------------------------------------ pulse


def test_pulse_counts_the_queue_across_lanes_without_refs(world):
    now = datetime.now(UTC)
    with world.Session() as s:
        _put(
            s, FetchKind.ORDER_PDF, "GAHC010000012025|1|2025-01-01", FetchStatus.PENDING, lane=FetchLane.DAILY
        )
        _put(
            s, FetchKind.ORDER_PDF, "GAHC010000012025|2|2025-01-01", FetchStatus.PENDING, lane=FetchLane.LOAD
        )
        _put(
            s,
            FetchKind.DOSSIER,
            "GAHC010000992025",
            FetchStatus.RUNNING,
            lane=FetchLane.REQUEST,
            started_at=now - timedelta(seconds=5),
        )
        _put(s, FetchKind.DOSSIER, "GAHC010000982025", FetchStatus.DONE, lane=FetchLane.REQUEST)
        _call(s, now - timedelta(minutes=2), lane="daily", remaining=700)
        _call(s, now - timedelta(minutes=20), lane="load", remaining=799)
        s.flush()
        p = data_load.pulse(s, CFG, now)
        assert p["queue"] == [
            {"kind": "dossier", "pending": 0, "running": 1},
            {"kind": "order_pdf", "pending": 2, "running": 0},
        ]
        assert p["running"] == [
            {"kind": "dossier", "lane": "request", "started_at": p["running"][0]["started_at"]}
        ]
        assert p["calls_last_5_min"] == 1 and p["requests_active"] == 1
        assert p["window"]["hourly_limit"] == 800 and p["window"]["remaining"] == 700
        text = json.dumps(p, default=str)
        assert "GAHC0100009" not in text and "GAHC010000012025" not in text  # no reference leaves the pulse
        s.rollback()


# ------------------------------------------------------------------------------------------------ coverage


def test_coverage_left_uses_the_columns_own_dates(world):
    with world.Session() as s:
        _day(s, date(2025, 1, 1), FetchStatus.DONE)
        _day(s, date(2025, 2, 28), FetchStatus.PENDING)
        listed = make_case(s, cnr="GAHC010000112025")
        other = make_case(s, cnr="GAHC010000122025")
        _list(s, date(2025, 1, 6), [listed, other])
        # the dossier sits in the daily lane, with no listing date: still the January case's work
        _put(s, FetchKind.DOSSIER, listed.cnr, FetchStatus.PENDING, lane=FetchLane.DAILY, priority=40)
        _put(
            s,
            FetchKind.DOSSIER,
            other.cnr,
            FetchStatus.FAILED,
            lane=FetchLane.LOAD,
            list_date=date(2025, 1, 6),
        )
        # a February order queued by a January listing: February's work
        _order(s, listed, "1", date(2025, 2, 3), DownloadStatus.PENDING)
        _put(
            s,
            FetchKind.ORDER_PDF,
            f"{listed.cnr}|1|2025-02-03",
            FetchStatus.PENDING,
            lane=FetchLane.LOAD,
            list_date=date(2025, 1, 6),
        )
        jan, feb = data_load.coverage(s, CFG, "2025-01", "2025-02", today=date(2025, 3, 1))
        assert jan["left"] == {"days": 30, "cases": 1, "order_pdfs": 0}
        assert jan["cases"]["queued"] == 1 and jan["cases"]["failed"] == 1
        assert feb["left"] == {"days": 28, "cases": 0, "order_pdfs": 1}
        # the kept load-lane figures still count by listing date
        assert jan["work_left"]["order_pdf"] == 1 and feb["work_left"]["order_pdf"] == 0
        s.rollback()


def test_coverage_state_done_in_progress_not_reached_failed_days_not_in_load(world):
    with world.Session() as s:
        for n in range(1, 32):
            _day(s, date(2025, 1, n), FetchStatus.DONE)
        _day(s, date(2025, 2, 1), FetchStatus.DONE)
        _day(s, date(2025, 2, 2), FetchStatus.FAILED)
        _day(s, date(2025, 3, 4), FetchStatus.PENDING)  # the earliest waiting load day
        _day(s, date(2025, 4, 30), FetchStatus.PENDING)
        months = data_load.coverage(s, CFG, "2025-01", "2025-06", today=date(2025, 6, 20))
        assert {m["month"]: m["state"] for m in months} == {
            "2025-01": "done",
            "2025-02": "failed_days",
            "2025-03": "in_progress",
            "2025-04": "not_reached",
            "2025-05": "not_in_load",
            "2025-06": "not_in_load",
        }
        s.rollback()


def test_coverage_counts_days_only_up_to_today(world):
    with world.Session() as s:
        _day(s, date(2025, 1, 1), FetchStatus.DONE)
        jan, feb = data_load.coverage(s, CFG, "2025-01", "2025-02", today=date(2025, 1, 10))
        assert jan["days"]["calendar"] == 10 and jan["days"]["not_queued"] == 9
        assert jan["days_covered_pct"] == 10.0 and jan["left"]["days"] == 9
        assert feb["days"]["calendar"] == 0 and feb["left"]["days"] == 0 and feb["days_covered_pct"] == 0.0
        s.rollback()


def test_coverage_earlier_orders_and_months_add_up(world):
    with world.Session() as s:
        _day(s, date(2025, 1, 1), FetchStatus.DONE)
        case = make_case(s)
        _order(s, case, "1", date(2024, 12, 31), DownloadStatus.PENDING)
        _order(s, case, "2", date(2023, 5, 1), DownloadStatus.FAILED)
        _order(s, case, "3", date(2025, 1, 1), DownloadStatus.PENDING)
        _order(s, case, "4", date(2025, 2, 14), DownloadStatus.NOT_AVAILABLE)
        view = data_load.coverage_view(s, CFG, today=date(2025, 2, 20))
        assert view["position"] == {"working_on": None, "working_on_month": None}
        assert view["earlier_orders"] == {
            "referenced": 2,
            "stored": 0,
            "not_available": 0,
            "waiting": 1,
            "failed": 1,
        }
        total = s.scalar(sa.select(sa.func.count()).select_from(Order))
        assert sum(m["orders"]["referenced"] for m in view["months"]) + 2 == total
        # no load period: no months, nothing earlier
        s.rollback()
    with world.Session() as s:
        assert data_load.coverage_view(s, CFG) == {
            "months": [],
            "earlier_orders": None,
            "position": {"working_on": None, "working_on_month": None},
        }


def test_coverage_keeps_work_left_and_failed(world):
    with world.Session() as s:
        _day(s, date(2025, 1, 2), FetchStatus.PENDING)
        _day(s, date(2025, 1, 3), FetchStatus.FAILED)
        _put(s, FetchKind.DOSSIER, "GAHC010000012025", FetchStatus.PENDING, list_date=date(2025, 1, 2))
        (jan,) = data_load.coverage(s, CFG, "2025-01", "2025-01", today=date(2025, 2, 1))
        assert jan["work_left"] == {"causelist_day": 1, "dossier": 1, "order_pdf": 0}
        assert jan["failed"] == {"causelist_day": 1, "dossier": 0, "order_pdf": 0}
        assert jan["state"] == "in_progress" and jan["left"]["days"] == 31
        s.rollback()


# ------------------------------------------------------------------------------------------------ the estimate


def _basis(**kw) -> data_load.BasisAll:
    base = {
        "window_days": 7,
        "calls_per_item": {"causelist_day": 3.0, "dossier": 1.0, "order_pdf": 1.0},
        "finished": {"causelist_day": 10, "dossier": 50, "order_pdf": 100},
        "calls": {"causelist_day": 30, "dossier": 50, "order_pdf": 100},
        "dossiers_per_day": 5.0,
        "pdfs_per_dossier": 2.0,
        "calls_per_hour": 100.0,
        "pending": {"causelist_day": 10, "dossier": 20, "order_pdf": 100},
        "history_hours": 48.0,
        "calls_last_hour": 90,
        "hourly_limit": 1000,
    }
    base.update(kw)
    return data_load.BasisAll(**base)


def test_estimate_all_every_lane_details_before_order_pdfs(world):
    out = data_load.compute_two(_basis(), paused=False, gateway_on=True, now=NOW)
    # details: 10 days × 3 + 10 × 5 dossiers × 1 + 20 dossiers × 1 = 100 calls = 1 hour at 100 an hour
    assert out["details"] == {
        "finish_at": NOW + timedelta(hours=1),
        "hours": 1.0,
        "calls_needed": 100.0,
        "reason": None,
    }
    # every PDF as well: 100 waiting + (20 + 50) dossiers × 2 = 240 PDFs × 1 call, after the details
    assert out["all"]["calls_needed"] == 340.0 and out["all"]["hours"] == 3.4
    assert out["all"]["finish_at"] > out["details"]["finish_at"]
    # the measured rates come from every queue lane
    now = datetime.now(UTC)
    with world.Session() as s:
        _call(s, now - timedelta(days=3), lane="load")  # history beyond a day
        for lane, n in (("load", 12), ("daily", 24), ("request", 6), ("discovery", 6)):
            for i in range(n):
                _call(s, now - timedelta(minutes=10 + i), lane=lane, remaining=900 - i)
        _call(s, now - timedelta(minutes=5))  # a search outside the queue: not the pace
        _put(
            s, FetchKind.ORDER_PDF, "GAHC010000012025|1|2025-01-01", FetchStatus.PENDING, lane=FetchLane.DAILY
        )
        _put(
            s,
            FetchKind.ORDER_PDF,
            "GAHC010000012025|2|2025-01-01",
            FetchStatus.RUNNING,
            lane=FetchLane.REQUEST,
        )
        _put(
            s, FetchKind.DOSSIER, "GAHC010000012025", FetchStatus.DONE, lane=FetchLane.DAILY, finished_at=now
        )
        s.flush()
        b = data_load.measure_all(s, CFG, now)
        assert b.calls_per_hour == 2.0  # 48 queue calls in 24 hours
        assert b.pending == {"causelist_day": 0, "dossier": 0, "order_pdf": 2}
        assert b.finished["dossier"] == 1 and b.calls["dossier"] == 49
        assert b.hourly_limit == 901 and b.history_hours >= 72
        s.rollback()


def test_estimate_all_reasons():
    def reasons(b, **kw):
        out = data_load.compute_two(b, now=NOW, **{"paused": False, "gateway_on": True, **kw})
        return out["details"]["reason"], out["all"]["reason"]

    assert reasons(_basis(), gateway_on=False) == ("connection_off", "connection_off")
    # paused stops the details line only; the order PDFs keep their date
    assert reasons(_basis(), paused=True) == ("paused", None)
    assert reasons(_basis(history_hours=5.0)) == ("not_enough_history", "not_enough_history")
    assert reasons(_basis(calls_last_hour=0)) == ("no_recent_calls", "no_recent_calls")
    rates = {"causelist_day": None, "dossier": 1.0, "order_pdf": 1.0}
    assert reasons(_basis(calls_per_item=rates)) == ("not_enough_history", "not_enough_history")
    # nothing waiting: done, whatever else holds
    done = data_load.compute_two(
        _basis(pending={"causelist_day": 0, "dossier": 0, "order_pdf": 0}),
        paused=True,
        gateway_on=False,
        now=NOW,
    )
    assert done["details"] == {"finish_at": NOW, "hours": 0.0, "calls_needed": 0.0, "reason": None}
    assert done["all"]["calls_needed"] == 0.0


# ------------------------------------------------------------------------------------------------ the schedule


def test_schedule_view_last_runs_and_daily_cycle(world):
    now = datetime.now(UTC)
    with world.Session() as s:
        s.add(
            JobRun(
                job="napix-log-purge",
                started_at=now - timedelta(hours=5),
                status=JobStatus.SUCCEEDED,
                counters={"deleted": 0},
            )
        )
        s.add(
            JobRun(
                job="napix-log-purge",
                started_at=now - timedelta(days=1, hours=5),
                status=JobStatus.SUCCEEDED,
                counters={"deleted": 7},
            )
        )
        s.add(
            JobRun(
                job="dedupe-sweep",
                started_at=now - timedelta(hours=6),
                status=JobStatus.FAILED,
                counters={"merged": 2, "needs_review": 1},
            )
        )
        s.flush()
        view = schedules.schedule_view(s, CFG, now)
        entries = {e["key"]: e for e in view["entries"]}
        assert [e["key"] for e in view["entries"]] == [p["key"] for p in schedules.PLAIN_SCHEDULE]
        assert entries["purge"]["result"] == "succeeded" and entries["purge"]["facts"] == {"deleted": 0}
        assert entries["purge"]["last_run_at"] == now - timedelta(hours=5)
        assert entries["dedupe"]["result"] == "failed" and entries["dedupe"]["facts"]["merged"] == 2
        assert entries["masters"]["last_run_at"] is None and entries["masters"]["result"] is None
        assert set(entries["disposed-refresh"]["facts"]) == {"eligible", "due_now"}
        assert entries["load"]["when"] == "Always"
        cycle = view["daily_cycle"]
        assert len(cycle) == 7 and cycle[-1]["label"] == "today" and cycle[-2]["label"] == "yesterday"
        assert cycle[0]["date"] == cycle[-1]["date"] - timedelta(days=6)
        s.rollback()


def test_admin_data_load_description_seeded(world):
    from aslms.services.seed import SeedReport, seed_ref_tables

    want = "Start, pause and order the automatic collection, collect cases from the court at once and check duplicates."
    with world.Session() as s:
        row = s.get(RefPermission, Permission.ADMIN_DATA_LOAD.value)
        assert row.description == want and row.label == "Data Collection"
        row.description = (
            "Start, pause and order the historical load, fetch single cases and check duplicates."
        )
        s.flush()
        report = SeedReport()
        seed_ref_tables(s, report)
        assert s.get(RefPermission, Permission.ADMIN_DATA_LOAD.value).description == want
        s.rollback()


# ------------------------------------------------------------------------------------------------ the API


def _counts(world) -> tuple[int, int, int]:
    with world.Session() as s:
        return (
            s.scalar(sa.select(sa.func.count()).select_from(FetchQueueItem)),
            s.scalar(sa.select(sa.func.count()).select_from(AuditLog)),
            s.scalar(sa.select(sa.func.count()).select_from(NapixCallLog)),
        )


READS = (
    "/admin/data-load/overview",
    "/admin/data-load/pulse",
    "/admin/data-load/schedule",
)


def test_overview_pulse_schedule_need_a_reader_function(world, tmp_path):
    api = ds.make_api(world, tmp_path)
    try:
        for key in ("root", "oversight", "central_op"):
            h = ds.login(api, key)
            for path in READS:
                r = api.get(path, headers=h)
                assert r.status_code == 200, (key, path, r.text)
        h = ds.login(api, "edu_off1")
        for path in READS:
            assert api.get(path, headers=h).status_code == 403, path
        # `admin.data_load` alone reads too (`data_load.READERS`)
        with world.Session() as s:
            actor, root = world.actor(s, "root")
            access.set_override(
                s,
                actor,
                root,
                world.user(s, "edu_off1"),
                Permission.ADMIN_DATA_LOAD,
                PermissionEffect.GRANT,
                reason="t",
            )
            s.commit()
        h = ds.login(api, "edu_off1")
        for path in READS:
            assert api.get(path, headers=h).status_code == 200, path
        for path in READS:
            assert api.get(path).status_code == 401, path
    finally:
        api.__exit__(None, None, None)


def test_overview_pulse_coverage_schedule_write_nothing_and_call_no_napix(world, tmp_path):
    with world.Session() as s:
        _day(s, date(2025, 1, 3), FetchStatus.PENDING)
        _put(
            s, FetchKind.ORDER_PDF, "GAHC010000012025|1|2025-01-01", FetchStatus.PENDING, lane=FetchLane.DAILY
        )
        s.commit()
    api = ds.make_api(world, tmp_path)
    try:
        h = ds.login(api, "root")
        before = _counts(world)
        r = api.get("/admin/data-load/overview", headers=h)
        body = r.json()
        assert r.status_code == 200 and body["left"]["order_pdfs"] == 1 and body["collection"] == "running"
        assert body["position"]["working_on_month"] == "2025-01"
        assert set(body["estimate"]) == {"details", "all", "basis"}
        r = api.get("/admin/data-load/pulse", headers=h)
        assert r.status_code == 200 and {q["kind"] for q in r.json()["queue"]} == {
            "causelist_day",
            "order_pdf",
        }
        r = api.get("/admin/data-load/coverage", headers=h)
        body = r.json()
        assert r.status_code == 200 and body["position"]["working_on"] == "2025-01-03"
        assert body["months"][0]["state"] == "in_progress" and "earlier_orders" in body
        r = api.get("/admin/data-load/schedule", headers=h)
        assert r.status_code == 200 and len(r.json()["daily_cycle"]) == 7
        assert _counts(world) == before
    finally:
        api.__exit__(None, None, None)
    with world.Session() as s:
        s.execute(sa.delete(FetchQueueItem))
        s.commit()


def test_status_lines_name_both_estimates():
    from aslms.cli.data_load import status_lines

    ov = {
        "collection": "paused",
        "position": {"working_on_month": "2026-01"},
        "napix_enabled": True,
        "days": {"collected": 306, "calendar": 664, "failed": 2},
        "cases": {"found": 59033, "with_details": 58924, "without_details": 109},
        "orders": {
            "stored": 137932,
            "referenced": 320869,
            "waiting": 182929,
            "not_available": 8,
            "failed": 0,
        },
        "left": {"total": 183229, "causelist_days": 267, "case_details": 33, "order_pdfs": 182929},
        "estimate": {
            "details": {"reason": "paused"},
            "all": {"reason": None, "calls_needed": 1000.0, "finish_at": datetime(2026, 11, 8, 10, 0)},
            "basis": {"calls_per_hour": 820.4, "hourly_limit": 1000},
        },
    }
    lines = status_lines(ov)
    assert lines[0] == "Automatic collection: paused, working on 2026-01; court connection on"
    assert "Cause lists: 306 of 664 days (2 failed)" in lines
    assert "Cause lists and case details: no date: the automatic collection is paused" in lines
    assert "Every order PDF as well: about Sun 08 Nov 2026 10:00 IST (1,000 calls)" in lines
    assert lines[-1] == "Pace: about 820 court calls an hour of the 1,000 the court allows"
