"""The data-load console's services (design `data-load-console`, decisions 3, 6-9, 18) against the test database:
the start preview and the held-days choice, the bounds, the versioned pause and order with their audit rows, the
re-prioritising of pending load rows, the progress block with the hour's allowance by lane, and the month coverage.
Every figure is compared with the seed."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa

from aslms.core.config import Settings
from aslms.domain.cases import Case
from aslms.domain.causelists import (
    Causelist,
    CauselistEntry,
    EntrySource,
    ListSource,
    ListType,
    ParseStatus,
    ResolutionStatus,
)
from aslms.domain.courts import Court, MasterKind, MasterSyncRun
from aslms.domain.documents import DownloadStatus, Order, OrderKind
from aslms.domain.events import AuditLog
from aslms.domain.ops import (
    DataLoadSettings,
    FetchKind,
    FetchLane,
    FetchQueueItem,
    FetchStatus,
    LoadOrder,
    NapixCallLog,
)
from aslms.services import data_load
from aslms.services.causelists import store_pdf
from aslms.services.reporting_common import today_ist
from aslms.services.storage import LocalStore
from tests.db.world import make_case

CFG = Settings(_env_file=None)


def _put(s, kind: FetchKind, ref: str, status: FetchStatus, *, lane=FetchLane.LOAD, priority=46, **kw):
    row = FetchQueueItem(kind=kind, ref=ref, status=status, lane=lane, priority=priority, **kw)
    s.add(row)
    s.flush()
    return row


def _day(s, d: date, status: FetchStatus, **kw):
    return _put(s, FetchKind.CAUSELIST_DAY, d.isoformat(), status, list_date=d, **kw)


def _row(s, kind: FetchKind, ref: str) -> FetchQueueItem | None:
    return s.scalar(
        sa.select(FetchQueueItem)
        .where(FetchQueueItem.kind == kind, FetchQueueItem.ref == ref)
        .execution_options(populate_existing=True)
    )


def _audits(s, action: str) -> list[AuditLog]:
    return list(s.scalars(sa.select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at)))


def _feb(n: int) -> date:
    return date(2025, 2, n)


def _seed_february(s) -> None:
    """2025-02-01..10: done 1-2, skipped 3, pending 4, running 5, failed 6-7, nothing 8-10."""
    for n, st in (
        (1, "done"),
        (2, "done"),
        (3, "skipped"),
        (4, "pending"),
        (5, "running"),
        (6, "failed"),
        (7, "failed"),
    ):
        _day(s, _feb(n), FetchStatus(st))


def test_start_preview_counts_exact(world):
    with world.Session() as s:
        _seed_february(s)
        p = data_load.preview(s, CFG, _feb(1), _feb(10))
        assert p.as_dict() == {
            "days": 10,
            "held_with_lists": 2,
            "held_no_list": 1,
            "waiting": 2,
            "failed": 2,
            "not_queued": 3,
            "calls_estimate": None,  # no load history yet
            "masters_stale": True,
        }
        assert _audits(s, "data_load.started") == []
        s.rollback()


def test_start_refuses_without_choice_when_held(world):
    with world.Session() as s:
        actor, user = world.actor(s, "root")
        _seed_february(s)
        before = s.scalar(sa.select(sa.func.count()).select_from(FetchQueueItem))
        with pytest.raises(data_load.AlreadyHeld) as exc:
            data_load.start(s, actor, user, _feb(1), _feb(10), None)
        assert exc.value.extra == {"held_with_lists": 2, "held_no_list": 1}
        assert s.scalar(sa.select(sa.func.count()).select_from(FetchQueueItem)) == before
        assert _row(s, FetchKind.CAUSELIST_DAY, _feb(6).isoformat()).status == FetchStatus.FAILED
        assert _audits(s, "data_load.started") == []
        s.rollback()


def test_start_skip_and_refetch(world):
    with world.Session() as s:
        actor, user = world.actor(s, "root")
        _seed_february(s)
        res = data_load.start(s, actor, user, _feb(1), _feb(10), "skip")
        assert res.as_dict() == {
            "days": 10,
            "queued": 3,
            "held_skipped": 3,
            "held_requeued": 0,
            "revived": 2,
            "masters_queued": True,
        }
        assert _row(s, FetchKind.CAUSELIST_DAY, _feb(1).isoformat()).status == FetchStatus.DONE
        assert _row(s, FetchKind.CAUSELIST_DAY, _feb(3).isoformat()).status == FetchStatus.SKIPPED
        revived = _row(s, FetchKind.CAUSELIST_DAY, _feb(6).isoformat())
        assert (revived.status, revived.attempts) == (FetchStatus.PENDING, 0)
        new = _row(s, FetchKind.CAUSELIST_DAY, _feb(9).isoformat())
        assert (new.status, new.lane, new.priority, new.list_date) == (
            FetchStatus.PENDING,
            FetchLane.LOAD,
            46,
            _feb(9),
        )
        masters = _row(s, FetchKind.MASTERS, "all")
        assert (masters.lane, masters.priority) == (FetchLane.REQUEST, 10)
        (audit,) = _audits(s, "data_load.started")
        assert audit.after["held"] == "skip" and audit.after["queued"] == 3 and audit.after["revived"] == 2
        assert audit.actor_user_id == user.id
        # masters fresh: not queued again; refetch re-queues the held days
        s.add(MasterSyncRun(master=MasterKind.CASE_TYPE, row_count=1, fetched_at=datetime.now(UTC)))
        s.flush()
        res = data_load.start(s, actor, user, _feb(1), _feb(3), "refetch")
        assert res.held_requeued == 3 and res.masters_queued is False
        assert {_row(s, FetchKind.CAUSELIST_DAY, _feb(n).isoformat()).status for n in (1, 2, 3)} == {
            FetchStatus.PENDING
        }
        s.rollback()


def test_start_bounds(world):
    today = today_ist()
    with world.Session() as s:
        actor, user = world.actor(s, "root")
        for f, t in (
            (today, today),
            (today - timedelta(days=3), today + timedelta(days=1)),
            (date(2025, 2, 2), date(2025, 2, 1)),
            (date(1949, 12, 31), date(1950, 1, 2)),
        ):
            with pytest.raises(data_load.LoadInputError) as exc:
                data_load.start(s, actor, user, f, t, "skip")
            assert exc.value.code == "bad_range"
            with pytest.raises(data_load.LoadInputError):
                data_load.preview(s, CFG, f, t)
        s.rollback()


def test_pause_resume_versions_and_audit(world):
    with world.Session() as s:
        actor, user = world.actor(s, "root")
        assert data_load.current_settings(s).version == 0
        with pytest.raises(data_load.LoadInputError) as exc:
            data_load.pause(s, actor, user, "  ")
        assert exc.value.code == "bad_reason"
        with pytest.raises(data_load.NoChange):
            data_load.resume(s, actor, user)
        v1 = data_load.pause(s, actor, user, "quota needed elsewhere")
        assert (v1.version, v1.paused, v1.reason) == (1, True, "quota needed elsewhere")
        with pytest.raises(data_load.NoChange):
            data_load.pause(s, actor, user, "again")
        v2 = data_load.resume(s, actor, user)
        assert (v2.version, v2.paused) == (2, False)
        v3, n = data_load.set_order(s, actor, user, LoadOrder.LISTS_FIRST, None, None, "lists first please")
        assert (v3.version, v3.load_order, n) == (3, LoadOrder.LISTS_FIRST, 0)
        rows = s.scalars(sa.select(DataLoadSettings).order_by(DataLoadSettings.version)).all()
        assert [(r.version, r.is_current, r.valid_to is None) for r in rows] == [
            (1, False, False),
            (2, False, False),
            (3, True, True),
        ]
        assert len(_audits(s, "data_load.paused")) == 1 and len(_audits(s, "data_load.resumed")) == 1
        (order,) = _audits(s, "data_load.order_changed")
        assert order.before["load_order"] == "cases_first" and order.after["load_order"] == "lists_first"
        assert order.after["reprioritised"] == 0
        s.rollback()


def test_order_change_reprioritises_pending_load_rows_only(world):
    with world.Session() as s:
        actor, user = world.actor(s, "root")
        jan = [date(2025, 1, n) for n in (1, 10, 20, 31)]
        _day(s, jan[0], FetchStatus.DONE, priority=46)
        _day(s, jan[1], FetchStatus.PENDING, priority=46)
        _day(s, jan[3], FetchStatus.PENDING, priority=46)
        _put(s, FetchKind.DOSSIER, "GAHC010000012025", FetchStatus.PENDING, priority=44, list_date=jan[1])
        _put(s, FetchKind.DOSSIER, "GAHC010000022025", FetchStatus.RUNNING, priority=44, list_date=jan[1])
        _put(
            s,
            FetchKind.ORDER_PDF,
            "GAHC010000012025|1|2025-01-10",
            FetchStatus.PENDING,
            priority=48,
            list_date=jan[2],
        )
        _put(s, FetchKind.DOSSIER, "GAHC010000032025", FetchStatus.PENDING, lane=FetchLane.DAILY, priority=40)
        settings, n = data_load.set_order(s, actor, user, "lists_first", None, None, "lists first")
        assert n == 3  # order PDFs do not depend on the preset (owner, 24 Oct 2026)
        prio = {(r.kind, r.ref): r.priority for r in s.scalars(sa.select(FetchQueueItem)).all()}
        assert prio[(FetchKind.CAUSELIST_DAY, "2025-01-10")] == 44
        assert prio[(FetchKind.CAUSELIST_DAY, "2025-01-31")] == 44
        assert prio[(FetchKind.DOSSIER, "GAHC010000012025")] == 46
        # an order PDF does not depend on the preset: left to `pdfs-after-details`
        assert prio[(FetchKind.ORDER_PDF, "GAHC010000012025|1|2025-01-10")] == 48
        assert prio[(FetchKind.CAUSELIST_DAY, "2025-01-01")] == 46  # done: untouched
        assert prio[(FetchKind.DOSSIER, "GAHC010000022025")] == 44  # running: untouched
        assert prio[(FetchKind.DOSSIER, "GAHC010000032025")] == 40  # daily: untouched
        settings, n = data_load.set_order(
            s, actor, user, "cases_first", date(2025, 1, 1), date(2025, 1, 15), "January first half"
        )
        prio = {(r.kind, r.ref): r.priority for r in s.scalars(sa.select(FetchQueueItem)).all()}
        assert prio[(FetchKind.DOSSIER, "GAHC010000012025")] == 41
        assert prio[(FetchKind.CAUSELIST_DAY, "2025-01-10")] == 42
        assert prio[(FetchKind.CAUSELIST_DAY, "2025-01-31")] == 46
        assert prio[(FetchKind.ORDER_PDF, "GAHC010000012025|1|2025-01-10")] == 48  # not a detail kind
        for ff, ft in (
            (date(2024, 12, 1), date(2025, 1, 5)),
            (date(2025, 1, 5), None),
            (date(2025, 1, 9), date(2025, 1, 2)),
        ):
            with pytest.raises(data_load.LoadInputError) as exc:
                data_load.set_order(s, actor, user, "cases_first", ff, ft, "bad")
            assert exc.value.code == "bad_period"
        s.rollback()


def _reading(s, at, remaining, lane=None):
    s.add(
        NapixCallLog(
            api="hc-cnr-api/CNR",
            params_sha256="r" * 64,
            ok=True,
            lane=lane,
            rate_limit_remaining=remaining,
            called_at=at,
        )
    )


def test_progress_and_allowance_exact(world):
    """`test_allowance_window_based` of design napix-window: `used` counts from the observed reset S, not from the
    clock hour."""
    now = datetime.now(UTC)
    reset = now - timedelta(minutes=40)  # S: a precise reset 40 minutes ago, whatever the clock hour
    with world.Session() as s:
        _day(s, date(2025, 1, 1), FetchStatus.DONE)
        _day(s, date(2025, 1, 2), FetchStatus.SKIPPED)
        _day(s, date(2025, 1, 3), FetchStatus.PENDING)
        _day(s, date(2025, 1, 4), FetchStatus.PENDING, not_before=now + timedelta(hours=1))
        _day(s, date(2025, 1, 5), FetchStatus.FAILED, last_error="gateway 502", finished_at=now)
        _put(s, FetchKind.DOSSIER, "GAHC010000012025", FetchStatus.PENDING, priority=44)
        _put(s, FetchKind.DOSSIER, "GAHC010000022025", FetchStatus.RUNNING, priority=44)
        _put(s, FetchKind.ORDER_PDF, "GAHC010000012025|1|2025-01-01", FetchStatus.FAILED, priority=48)
        _put(s, FetchKind.DOSSIER, "GAHC010000032025", FetchStatus.PENDING, lane=FetchLane.DAILY, priority=40)
        _reading(s, reset - timedelta(minutes=5), 160, lane="load")  # the old window: not counted
        _reading(s, reset - timedelta(seconds=20), 155, lane="load")  # the old window: not counted
        _reading(s, reset, 999)  # the reset (outside the queue: a search)
        k = 0
        for lane, n in (("load", 3), ("daily", 2), ("request", 1), (None, 4)):
            for _ in range(n):
                k += 1
                _reading(s, reset + timedelta(minutes=k), 999 - k, lane=lane)
        s.flush()
        out = data_load.progress(s, CFG, now)
        assert out["settings"]["version"] == 0 and out["settings"]["paused"] is False
        assert out["period"] == {"from": date(2025, 1, 1), "to": date(2025, 1, 5)}
        assert out["totals"]["days"] == {
            "calendar": 5,
            "with_lists": 1,
            "no_list": 1,
            "waiting": 2,
            "failed": 1,
            "not_queued": 0,
        }
        work = {w["kind"]: w for w in out["work_left"]}
        assert work["causelist_day"] == {
            "kind": "causelist_day",
            "pending": 2,
            "runnable": 1,
            "waiting": 1,
            "running": 0,
            "failed": 1,
        }
        assert work["dossier"] == {
            "kind": "dossier",
            "pending": 1,
            "runnable": 1,
            "waiting": 0,
            "running": 1,
            "failed": 0,
        }
        assert work["order_pdf"]["failed"] == 1 and work["order_pdf"]["pending"] == 0
        assert {f["kind"]: f["failed"] for f in out["failures"]["by_kind"]} == {
            "causelist_day": 1,
            "order_pdf": 1,
        }
        assert len(out["failures"]["latest"]) == 2
        allowance = out["allowance"]
        assert allowance["used"] == {"load": 3, "discovery": 0, "daily": 2, "request": 1, "outside_queue": 5}
        assert sum(allowance["used"].values()) == s.scalar(
            sa.select(sa.func.count()).where(NapixCallLog.called_at >= reset)
        )
        assert (allowance["rate_reserve"], allowance["live_reserve"], allowance["search_floor"]) == (
            150,
            100,
            50,
        )
        assert allowance["remaining"] == 989 and allowance["window_status"] == "current"
        assert allowance["window_started_at"] == reset  # aware datetimes compare across zones
        assert allowance["next_reset_at"] == reset + timedelta(hours=1)
        assert allowance["seconds_to_next_reset"] == 20 * 60
        assert out["estimate"]["reason"] == "not_enough_history" and out["estimate"]["finish_at"] is None
        s.rollback()


def test_coverage_month_figures_exact(world, tmp_path):
    store = LocalStore(str(tmp_path / "store"))
    with world.Session() as s:
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        for n in range(1, 11):
            _day(s, date(2025, 1, n), FetchStatus.DONE if n <= 6 else FetchStatus.SKIPPED)
        _day(s, date(2025, 2, 3), FetchStatus.DONE)
        _day(s, date(2025, 2, 4), FetchStatus.PENDING)
        doc, _ = store_pdf(s, store, b"%PDF-1.4 jan", doc_date=date(2025, 1, 2), description="t")
        doc2, _ = store_pdf(s, store, b"%PDF-1.4 feb", doc_date=date(2025, 2, 3), description="t")
        with_details = make_case(s, cnr="GAHC010000012025", case_no="WP(C)/1/2025")
        with_details.last_full_refresh_at = datetime.now(UTC)
        bare = make_case(s, cnr="GAHC010000022025", case_no="WP(C)/2/2025")
        prov = make_case(s, cnr="GAHC010000032025", case_no="WP(C)/3/2025")
        prov.cnr, prov.is_provisional = None, True
        lists = []
        for d, document_id, parse in (
            (date(2025, 1, 2), doc.id, ParseStatus.PARSED),
            (date(2025, 1, 3), None, ParseStatus.FAILED),
            (date(2025, 2, 3), doc2.id, ParseStatus.PARSED),
        ):
            cl = Causelist(
                court_id=court.id,
                list_date=d,
                list_type=ListType.DAILY,
                source=ListSource.NAPIX,
                document_id=document_id,
                parse_status=parse,
            )
            s.add(cl)
            s.flush()
            lists.append(cl)
        for i, (cl, case) in enumerate(
            ((lists[0], with_details), (lists[0], bare), (lists[0], prov), (lists[2], bare))
        ):
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
        for no, d, status, document_id in (
            ("1", date(2025, 1, 5), DownloadStatus.STORED, doc.id),
            ("2", date(2025, 1, 6), DownloadStatus.NOT_AVAILABLE, None),
            ("3", date(2025, 1, 7), DownloadStatus.PENDING, None),
            ("4", date(2025, 2, 7), DownloadStatus.PENDING, None),
        ):
            s.add(
                Order(
                    case_id=with_details.id,
                    order_no=no,
                    order_date=d,
                    kind=OrderKind.INTERIM,
                    download_status=status,
                    document_id=document_id,
                )
            )
        _put(
            s,
            FetchKind.DOSSIER,
            "GAHC010000022025",
            FetchStatus.PENDING,
            priority=44,
            list_date=date(2025, 1, 2),
        )
        _put(
            s,
            FetchKind.ORDER_PDF,
            "GAHC010000012025|3|2025-01-07",
            FetchStatus.FAILED,
            priority=48,
            list_date=date(2025, 1, 2),
        )
        s.flush()
        jan, feb = data_load.coverage(s, CFG, "2025-01", "2025-02")
        assert jan["month"] == "2025-01" and feb["month"] == "2025-02"
        assert jan["days"] == {
            "calendar": 31,
            "with_lists": 6,
            "no_list": 4,
            "waiting": 0,
            "failed": 0,
            "not_queued": 21,
        }
        assert (jan["lists"], jan["entries"], jan["lists_parse_failed"]) == (1, 3, 1)
        assert jan["cases"] == {
            "listed": 3,
            "with_details": 1,
            "provisional": 1,
            "without_details": 2,
            "queued": 1,
            "failed": 0,
        }
        assert jan["orders"] == {
            "referenced": 3,
            "stored": 1,
            "not_available": 1,
            "waiting": 1,
            "failed": 0,
        }
        assert jan["work_left"] == {"causelist_day": 0, "dossier": 1, "order_pdf": 0}
        assert jan["failed"] == {"causelist_day": 0, "dossier": 0, "order_pdf": 1}
        assert jan["days_covered_pct"] == round(100 * 10 / 31, 1) and jan["details_pct"] == round(100 / 3, 1)
        assert (
            feb["days"]["calendar"] == 28 and feb["days"]["with_lists"] == 1 and feb["days"]["waiting"] == 1
        )
        assert (feb["lists"], feb["entries"]) == (1, 1)
        assert feb["cases"]["listed"] == 1 and feb["cases"]["with_details"] == 0
        assert feb["details_pct"] == 0.0
        assert feb["orders"]["waiting"] == 1 and feb["work_left"]["causelist_day"] == 1
        # the default range runs from the load period's first month to this month (design data-collection-redesign,
        # decision 19); at most 36 months; months must be ordered
        default = [m["month"] for m in data_load.coverage(s, CFG, today=date(2025, 4, 10))]
        assert default == ["2025-01", "2025-02", "2025-03", "2025-04"]
        for f, t in (("2025-01", "2028-01"), ("2025-03", "2025-01"), ("2025-13", "2025-12")):
            with pytest.raises(data_load.LoadInputError) as exc:
                data_load.coverage(s, CFG, f, t)
            assert exc.value.code == "bad_period"
        s.rollback()
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Case)) == 0


def _scope(world):
    from contextlib import contextmanager

    @contextmanager
    def scope():
        s = world.Session()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    return scope


def test_cli_data_load_is_audited(world, monkeypatch):
    import typer
    from typer.testing import CliRunner

    from aslms.cli import data_load as cli
    from aslms.cli import pipeline

    monkeypatch.setattr(cli, "session_scope", _scope(world))
    monkeypatch.setattr(pipeline, "session_scope", _scope(world))
    monkeypatch.setattr(cli, "get_settings", lambda: CFG)
    app = typer.Typer()
    app.add_typer(cli.data_load_app, name="data-load")
    app.command("load")(pipeline.load)
    runner = CliRunner()
    for args in (
        ["data-load", "start", "--from", "2025-03-01", "--to", "2025-03-05"],
        ["data-load", "pause", "--reason", "verification"],
        ["data-load", "resume"],
        ["data-load", "order", "--preset", "lists_first", "--reason", "verification"],
        ["data-load", "dedupe", "--dry-run"],
        ["data-load", "status"],
        ["load", "--from", "2025-03-04", "--to", "2025-03-07"],
    ):
        r = runner.invoke(app, args)
        assert r.exit_code == 0, (args, r.output)
    r = runner.invoke(app, ["data-load", "pause", "--reason", "x"])
    assert r.exit_code != 0 and "bad_reason" in r.output
    r = runner.invoke(app, ["data-load", "order", "--preset", "newest", "--reason", "verification"])
    assert r.exit_code != 0
    with world.Session() as s:
        actions = [
            a.action for a in s.scalars(sa.select(AuditLog).order_by(AuditLog.created_at, AuditLog.id)).all()
        ]
        assert actions == [
            "data_load.started",
            "data_load.paused",
            "data_load.resumed",
            "data_load.order_changed",
            "data_load.started",
        ]
        root = world.users["root"].id
        assert all(a.actor_user_id == root for a in s.scalars(sa.select(AuditLog)).all())
        days = {
            r.ref: (r.lane, r.priority)
            for r in s.scalars(
                sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.CAUSELIST_DAY)
            )
        }
        # `aslms load` went through the same service: the held days 4-5 kept, 6-7 new, all in the load lane
        assert sorted(days) == [f"2025-03-0{n}" for n in range(1, 8)]
        assert {lane for lane, _ in days.values()} == {FetchLane.LOAD}
        assert days["2025-03-07"][1] == 44  # lists_first: days rank first
        started = sa.select(AuditLog).where(AuditLog.action == "data_load.started")
        (second,) = list(s.scalars(started.order_by(AuditLog.created_at, AuditLog.id)))[1:]
        assert second.after["held"] == "skip" and second.after["queued"] == 2


def test_dedupe_sweep_job_writes_a_run_and_an_audit_row(world, monkeypatch):
    from aslms.domain.ops import JobRun
    from aslms.jobs import celery_app

    monkeypatch.setattr(celery_app, "session_scope", _scope(world))
    with world.Session() as s:
        make_case(s, cnr="GAHC010000712025", case_no="WA/71/2025")
        make_case(s, cnr="GAHC010000722025", case_no="WA/71/2025")
        s.commit()
    assert celery_app.dedupe_sweep() == {"merged": 0, "needs_review": 0, "court_linked": 1}
    with world.Session() as s:
        run = s.scalar(sa.select(JobRun).where(JobRun.job == "dedupe-sweep"))
        assert run.counters == {"merged": 0, "needs_review": 0, "court_linked": 1} and run.finished_at
        (audit,) = s.scalars(sa.select(AuditLog).where(AuditLog.action == "data_load.dedupe_scan")).all()
        assert audit.actor_name == "dedupe-sweep" and audit.after["court_linked"] == 1
    assert celery_app.dedupe_sweep()["court_linked"] == 0
