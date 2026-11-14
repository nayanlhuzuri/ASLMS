"""Design `rolling-case-refresh` (database): the nightly refresh (claimed cases first at 56 and 57, oldest first; a
case refreshed within 7 days skipped; a clump levelled at 58 and 59; disposed, merged, never-fetched and CNR-less cases
left out; a recently failed case left out and an old failure revived; finished rows revived at their refresh priority,
a pending row keeping its better one), the hearing follow-ups (3, 7, 14 and 30 days until an order dated on or after
the hearing is stored; one row with the routine refresh), the cap, the `job_runs` row and the dry run, the Sunday job
(first fetches and missing orders only), the runner (a routine row already fresh ends done without a call, a row raised
by a status change is fetched, a routine row before a new order PDF), the two slots and the schedule's facts."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta

import sqlalchemy as sa
from typer.testing import CliRunner

from aslms.core.clock import IST, today_ist
from aslms.core.config import Settings
from aslms.domain.cases import Case, CaseStatus, FirstSeenSource
from aslms.domain.courts import Court
from aslms.domain.documents import DownloadStatus, Order, OrderKind
from aslms.domain.ops import FetchKind, FetchLane, FetchQueueItem, FetchStatus, JobRun, JobStatus
from aslms.domain.ownership import CaseOwnership, OwnershipRole, OwnershipStatus
from aslms.services import queue, schedules, tracking
from aslms.services.cases import apply_dossier, get_or_create_case
from aslms.services.napix_store import NapixRecorder
from aslms.services.orders import enqueue_order_pdfs
from aslms.services.runner import SLOT_KINDS, QueueRunner
from aslms.services.storage import LocalStore
from tests.db.conftest import sample
from tests.db.world import make_case

D = today_ist()
SETTINGS = Settings(_env_file=None, app_env="test", redis_url=None)


def _cfg(cap: int = 12000) -> Settings:
    return Settings(_env_file=None, app_env="test", redis_url=None, rolling_refresh_daily_max=cap)


def _on(day: date, hour: int = 12) -> datetime:
    """`hour`:00 IST of `day` as a UTC datetime."""
    return datetime.combine(day, time(hour, 0), tzinfo=IST).astimezone(UTC)


def _case(
    s, age: int | None, *, status=CaseStatus.PENDING, claimed_by=None, heard: date | None = None
) -> Case:
    c = make_case(s, status=status)
    c.last_full_refresh_at = _on(D - timedelta(days=age)) if age is not None else None
    c.last_hearing_date = heard
    s.flush()
    if claimed_by is not None:
        s.add(
            CaseOwnership(
                case_id=c.id,
                office_id=claimed_by.id,
                role=OwnershipRole.PRIMARY,
                status=OwnershipStatus.ACTIVE,
            )
        )
        s.flush()
    return c


def _dossiers(s) -> dict[str, FetchQueueItem]:
    return {
        r.ref: r
        for r in s.scalars(
            sa.select(FetchQueueItem)
            .where(FetchQueueItem.kind == FetchKind.DOSSIER)
            .execution_options(populate_existing=True)
        ).all()
    }


def _order(s, case: Case, on: date, no: str = "1", status=DownloadStatus.PENDING) -> Order:
    o = Order(case_id=case.id, order_no=no, order_date=on, kind=OrderKind.INTERIM, download_status=status)
    s.add(o)
    s.flush()
    return o


# ------------------------------------------------------------------------------------------------ the routine refresh


def test_nightly_queues_claimed_before_unclaimed(world):
    with world.Session() as s:
        edu = world.office(s, "EDU")
        old_free = _case(s, 9)
        free = _case(s, 7)
        claimed = _case(s, 7, claimed_by=edu)
        old_claimed = _case(s, 8, claimed_by=edu)
        plan = tracking.rolling_quota(tracking.counts_by_age(s, D), 12000)
        pairs = tracking.rolling_refresh_refs(s, D, plan)
        assert pairs == [(old_claimed.cnr, 56), (claimed.cnr, 56), (old_free.cnr, 57), (free.cnr, 57)]
        out = tracking.enqueue_nightly_refresh(s, D, _cfg())
        assert out["due_claimed"] == 2 and out["due_unclaimed"] == 2 and out["queued"] == 4
        rows = _dossiers(s)
        assert {c: rows[c].priority for c in rows} == {
            old_claimed.cnr: 56,
            claimed.cnr: 56,
            old_free.cnr: 57,
            free.cnr: 57,
        }
        assert {r.lane for r in rows.values()} == {FetchLane.DAILY}
        # every claimed case is claimed by the worker before any unclaimed one
        first_two = {queue.claim(s).ref, queue.claim(s).ref}
        assert first_two == {old_claimed.cnr, claimed.cnr}
        s.rollback()


def test_nightly_skips_a_case_refreshed_within_7_days(world):
    with world.Session() as s:
        six = _case(s, 6)
        seven = _case(s, 7)
        out = tracking.enqueue_nightly_refresh(s, D, _cfg())
        assert out["quota"] == 1 and out["early_unclaimed"] == 0
        assert set(_dossiers(s)) == {seven.cnr}
        assert six.cnr not in _dossiers(s)
        s.rollback()


def test_nightly_levels_a_clump_at_58_and_59(world):
    with world.Session() as s:
        edu = world.office(s, "EDU")
        due = _case(s, 7)
        early_claimed = _case(s, 5, claimed_by=edu)
        clump = [_case(s, 4) for _ in range(10)]
        out = tracking.enqueue_nightly_refresh(s, D, _cfg())
        # N_0 = 1, N_2 = 2, N_3 = 12: Q = max(1, 1, 1, 3) = 3
        assert out["quota"] == 3 and out["due"] == 1
        assert (out["due_unclaimed"], out["early_claimed"], out["early_unclaimed"]) == (1, 1, 1)
        rows = _dossiers(s)
        assert rows[due.cnr].priority == 57 and rows[early_claimed.cnr].priority == 58
        early = [c for c in clump if c.cnr in rows]
        assert len(early) == 1 and rows[early[0].cnr].priority == 59
        assert early[0].cnr == min(c.cnr for c in clump), "oldest refresh first, then CNR"
        s.rollback()


def test_nightly_leaves_out_disposed_merged_never_fetched_and_cnrless(world):
    with world.Session() as s:
        disposed = _case(s, 10, status=CaseStatus.DISPOSED)
        merged = _case(s, 10)
        merged.merged_into_case_id = disposed.id
        never = _case(s, None)
        cnrless = _case(s, 10, status=CaseStatus.UNKNOWN)
        cnrless.cnr, cnrless.is_provisional = None, True
        unknown = _case(s, 10, status=CaseStatus.UNKNOWN)
        s.flush()
        out = tracking.enqueue_nightly_refresh(s, D, _cfg())
        assert out["eligible"] == 1 and out["queued"] == 1
        assert set(_dossiers(s)) == {unknown.cnr}
        assert never.cnr not in _dossiers(s)
        s.rollback()


def test_nightly_leaves_out_a_recently_failed_case_and_revives_an_old_failure(world):
    now = datetime.now(UTC)
    with world.Session() as s:
        fresh_fail = _case(s, 8)
        old_fail = _case(s, 8)
        for case, finished in ((fresh_fail, now - timedelta(days=1)), (old_fail, now - timedelta(days=8))):
            s.add(
                FetchQueueItem(
                    kind=FetchKind.DOSSIER,
                    ref=case.cnr,
                    status=FetchStatus.FAILED,
                    priority=44,
                    lane=FetchLane.LOAD,
                    attempts=queue.MAX_ATTEMPTS,
                    finished_at=finished,
                )
            )
        s.flush()
        out = tracking.enqueue_nightly_refresh(s, D, _cfg())
        assert out["queued"] == 1
        rows = _dossiers(s)
        assert rows[fresh_fail.cnr].status == FetchStatus.FAILED
        revived = rows[old_fail.cnr]
        assert revived.status == FetchStatus.PENDING and revived.attempts == 0
        assert revived.priority == 57 and revived.lane == FetchLane.DAILY
        s.rollback()


def test_nightly_revives_a_done_row_at_its_refresh_priority(world):
    old = datetime.now(UTC) - timedelta(days=10)
    with world.Session() as s:
        case = _case(s, 7, claimed_by=world.office(s, "EDU"))
        s.add(
            FetchQueueItem(
                kind=FetchKind.DOSSIER,
                ref=case.cnr,
                status=FetchStatus.DONE,
                priority=44,
                lane=FetchLane.LOAD,
                created_at=old,
                finished_at=old,
            )
        )
        s.flush()
        tracking.enqueue_nightly_refresh(s, D, _cfg())
        row = _dossiers(s)[case.cnr]
        assert (row.status, row.priority, row.lane) == (FetchStatus.PENDING, 56, FetchLane.DAILY)
        assert row.created_at > old + timedelta(days=9)
        s.rollback()


def test_pending_row_keeps_its_better_priority(world):
    with world.Session() as s:
        case = _case(s, 8)
        queue.enqueue(s, FetchKind.DOSSIER, case.cnr, 40, lane=FetchLane.DAILY)
        out = tracking.enqueue_nightly_refresh(s, D, _cfg())
        assert out["queued"] == 1
        row = _dossiers(s)[case.cnr]
        assert row.status == FetchStatus.PENDING and row.priority == 40
        s.rollback()


# ------------------------------------------------------------------------------------------------ the follow-ups


def test_followup_queued_at_3_7_14_30_until_the_order_is_stored(world):
    heard = D - timedelta(days=40)  # any fixed date: the run dates below are relative to it
    with world.Session() as s:
        case = _case(s, 0, heard=heard)
        case.last_full_refresh_at = _on(heard - timedelta(days=2))
        s.flush()
        assert tracking.followup_refs(s, heard + timedelta(days=2)) == []  # day 2: too early
        for step in (3, 7, 14, 30):
            day = heard + timedelta(days=step)
            assert tracking.followup_refs(s, day) == [case.cnr], step
            case.last_full_refresh_at = _on(
                day, 23
            )  # refreshed on the step's day (23:00 IST is still that date)
            s.flush()
            assert tracking.followup_refs(s, day) == [], step
            assert tracking.followup_refs(s, day + timedelta(days=1)) == [], step
        assert tracking.followup_refs(s, heard + timedelta(days=38)) == []
        # the 14-day step missed and the case refreshed on day 10: due again on day 14; then the order arrives
        case.last_full_refresh_at = _on(heard + timedelta(days=10))
        s.flush()
        assert tracking.followup_refs(s, heard + timedelta(days=14)) == [case.cnr]
        _order(s, case, heard)
        assert tracking.followup_refs(s, heard + timedelta(days=14)) == []
        assert tracking.followup_refs(s, heard + timedelta(days=30)) == []
        s.rollback()


def test_followup_stops_on_an_order_dated_on_or_after_the_hearing(world):
    heard = D - timedelta(days=3)
    with world.Session() as s:
        case = _case(s, 5, heard=heard)
        _order(s, case, heard - timedelta(days=1), no="1")  # an earlier hearing's order
        out = tracking.enqueue_nightly_refresh(s, D, _cfg())
        assert out["followups"] == 1
        assert _dossiers(s)[case.cnr].priority == queue.PRIORITY["dossier_refetch"] == 50
        assert tracking.heard_waiting_count(s, D) == 1
        _order(s, case, heard + timedelta(days=1), no="2")
        assert tracking.followup_refs(s, D) == []
        assert tracking.heard_waiting_count(s, D) == 0
        s.rollback()


def test_followup_and_routine_share_one_row(world):
    with world.Session() as s:
        case = _case(s, 8, heard=D - timedelta(days=3))
        out = tracking.enqueue_nightly_refresh(s, D, _cfg())
        assert out["followups"] == 1 and out["due"] == 1 and out["due_unclaimed"] == 0 and out["queued"] == 1
        rows = _dossiers(s)
        assert list(rows) == [case.cnr] and rows[case.cnr].priority == 50
        s.rollback()


# ------------------------------------------------------------------------------------------------ cap, run, dry run


def test_cap_records_over_cap(world):
    with world.Session() as s:
        oldest, older, old = _case(s, 12), _case(s, 10), _case(s, 8)
        out = tracking.enqueue_nightly_refresh(s, D, _cfg(cap=2))
        assert (out["due"], out["quota"], out["cap"], out["over_cap"], out["queued"]) == (3, 2, 2, True, 2)
        assert set(_dossiers(s)) == {oldest.cnr, older.cnr}
        assert old.cnr not in _dossiers(s)
        assert tracking.not_refreshed_count(s, D) == 3
        s.rollback()


def test_cap_zero_queues_nothing(world):
    with world.Session() as s:
        _case(s, 9)
        _case(s, 9, heard=D - timedelta(days=3))
        out = tracking.enqueue_nightly_refresh(s, D, _cfg(cap=0))
        assert (out["quota"], out["cap"], out["followups"], out["queued"]) == (0, 0, 0, 0)
        assert _dossiers(s) == {}
        s.rollback()


def test_nightly_job_run_counters(world):
    with world.Session() as s:
        _case(s, 7)
        _case(s, 5, heard=D - timedelta(days=7))
        counters = schedules.run_nightly_refresh(s, _cfg(), today=D)
        (run,) = s.scalars(sa.select(JobRun).where(JobRun.job == "nightly-refresh")).all()
        assert JobStatus(run.status) == JobStatus.SUCCEEDED and run.finished_at is not None
        assert run.counters == counters and run.run_date == D
        assert counters["followups"] == 1 and counters["due_unclaimed"] == 1 and counters["queued"] == 2
        assert set(counters) >= {
            "eligible",
            "due_claimed",
            "due_unclaimed",
            "early_claimed",
            "early_unclaimed",
            "quota",
            "cap",
            "over_cap",
            "followups",
            "queued",
        }
        s.rollback()


def test_nightly_job_run_failed_and_reraised(world, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("no")

    monkeypatch.setattr(tracking, "enqueue_nightly_refresh", boom)
    with world.Session() as s:
        try:
            schedules.run_nightly_refresh(s, _cfg(), today=D)
        except RuntimeError:
            pass
        else:  # pragma: no cover
            raise AssertionError("not re-raised")
        (run,) = s.scalars(sa.select(JobRun).where(JobRun.job == "nightly-refresh")).all()
        assert JobStatus(run.status) == JobStatus.FAILED and "RuntimeError: no" in run.error
        s.rollback()


def _scope(world):
    @contextmanager
    def scope():
        s = world.Session()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    return scope


def test_daily_cycle_nightly_dry_run_writes_nothing(world, monkeypatch):
    import typer

    from aslms.cli import pipeline

    with world.Session() as s:
        _case(s, 9)
        _case(s, 9, heard=D - timedelta(days=3))
        s.commit()
        dry = tracking.enqueue_nightly_refresh(s, D, _cfg(), dry_run=True)
        assert dry["dry_run"] is True and dry["queued"] == 2 and dry["followups"] == 1
    monkeypatch.setattr(pipeline, "session_scope", _scope(world))
    app = typer.Typer()
    app.command(name="daily-cycle")(pipeline.daily_cycle)
    app.command(name="noop")(lambda: None)
    runner = CliRunner()
    r = runner.invoke(app, ["daily-cycle", "nightly", "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "dry_run" in r.output
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(FetchQueueItem)) == 0
        assert s.scalar(sa.select(sa.func.count()).select_from(JobRun)) == 0
    r = runner.invoke(app, ["daily-cycle", "status", "--dry-run"])
    assert r.exit_code != 0
    r = runner.invoke(app, ["daily-cycle", "nightly"])
    assert r.exit_code == 0, r.output
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(FetchQueueItem)) == 2
        assert (
            s.scalar(sa.select(sa.func.count()).select_from(JobRun).where(JobRun.job == "nightly-refresh"))
            == 1
        )


# ------------------------------------------------------------------------------------------------ the Sunday job


def test_weekly_queues_first_fetches_and_missing_orders_only(world):
    with world.Session() as s:
        fetched = _case(s, 10)
        never = _case(s, None)
        gone = _case(s, 3, status=CaseStatus.DISPOSED)
        missing = _order(s, gone, D - timedelta(days=20), no="1", status=DownloadStatus.NOT_AVAILABLE)
        waiting = _order(s, gone, D - timedelta(days=21), no="2")
        queue.enqueue(s, FetchKind.ORDER_PDF, f"{gone.cnr}|2|{waiting.order_date.isoformat()}", 80)
        out = schedules.enqueue_weekly(s)
        assert out["dossiers"] == 1 and out["orders_retried"] == 1 and out["orders_queued"] == 1
        rows = _dossiers(s)
        assert set(rows) == {never.cnr} and rows[never.cnr].priority == 50
        assert fetched.cnr not in rows
        pdfs = {
            r.ref: r.priority
            for r in s.scalars(
                sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.ORDER_PDF)
            ).all()
        }
        assert pdfs == {
            f"{gone.cnr}|1|{missing.order_date.isoformat()}": 60,
            f"{gone.cnr}|2|{waiting.order_date.isoformat()}": 80,  # a disposed case's other PDF keeps its 80
        }
        s.rollback()


# ------------------------------------------------------------------------------------------------ the runner

CNR = "GAHC010129772026"


def _seeded(Session) -> None:
    with Session() as s:
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        case, _ = get_or_create_case(s, court, cnr=CNR, case_no=None, source=FirstSeenSource.SEARCH)
        apply_dossier(s, case, sample("cnr_pending.json"))
        s.commit()


def _runner(Session, client, hc, tmp_path) -> QueueRunner:
    rec = NapixRecorder()
    client.on_call = rec.on_call
    return QueueRunner(
        Session,
        hc,
        store=LocalStore(tmp_path / "store"),
        causelist_dir=tmp_path / "lists",
        recorder=rec,
        reserve=0,
    )


def _run(client, runner, **kw):
    async def go():
        async with client:
            return await runner.run(**kw)

    return asyncio.run(go())


def _cnr_calls(gw) -> int:
    return sum(1 for x in gw.seen if "hc-cnr-api" in x["path"])


def test_routine_row_already_fresh_ends_done_without_a_call(clean_db, napix, tmp_path):
    gw, client, hc = napix
    _seeded(clean_db)
    with clean_db() as s:
        queue.enqueue(s, FetchKind.DOSSIER, CNR, queue.PRIORITY["dossier_routine"], lane=FetchLane.DAILY)
        s.commit()
    with clean_db() as s:  # the portal's own court fetch refreshed the case after queueing
        s.scalar(sa.select(Case).where(Case.cnr == CNR)).last_full_refresh_at = datetime.now(UTC) + timedelta(
            seconds=5
        )
        s.commit()
    rep = _run(client, _runner(clean_db, client, hc, tmp_path), kinds=[FetchKind.DOSSIER])
    assert rep.done == 1 and rep.items[0]["calls"] == 0, rep.items
    assert _cnr_calls(gw) == 0
    with clean_db() as s:
        row = queue.get_state(s, FetchKind.DOSSIER, CNR)
        assert row.status == FetchStatus.DONE and row.result == {"cnr": CNR, "fresh_since_queued": True}


def test_routine_row_raised_by_a_status_change_is_fetched(clean_db, napix, tmp_path):
    gw, client, hc = napix
    _seeded(clean_db)
    with clean_db() as s:
        queue.enqueue(s, FetchKind.DOSSIER, CNR, queue.PRIORITY["dossier_routine"], lane=FetchLane.DAILY)
        queue.enqueue(
            s,
            FetchKind.DOSSIER,
            CNR,
            queue.PRIORITY["dossier_refetch"],
            requeue=True,
            lane=FetchLane.DAILY,
            as_new=True,
        )
        s.scalar(sa.select(Case).where(Case.cnr == CNR)).last_full_refresh_at = datetime.now(UTC) + timedelta(
            seconds=5
        )
        s.commit()
        assert queue.get_state(s, FetchKind.DOSSIER, CNR).priority == 50
    rep = _run(client, _runner(clean_db, client, hc, tmp_path), kinds=[FetchKind.DOSSIER])
    assert rep.done == 1 and rep.items[0]["calls"] >= 1, rep.items
    assert _cnr_calls(gw) == 1
    with clean_db() as s:
        row = queue.get_state(s, FetchKind.DOSSIER, CNR)
        assert row.status == FetchStatus.DONE and "fresh_since_queued" not in (row.result or {})


def test_status_change_refetch_revives_at_50(clean_db, napix, tmp_path):
    gw, client, hc = napix
    _seeded(clean_db)
    old = datetime.now(UTC) - timedelta(days=30)
    with clean_db() as s:
        s.add(
            FetchQueueItem(
                kind=FetchKind.DOSSIER,
                ref=CNR,
                status=FetchStatus.DONE,
                priority=44,
                lane=FetchLane.LOAD,
                created_at=old,
                finished_at=old,
            )
        )
        tracking.enqueue_status_batches(s, D)
        s.commit()
    rep = _run(client, _runner(clean_db, client, hc, tmp_path), kinds=[FetchKind.STATUS_BATCH])
    assert rep.done == 1, rep.items
    with clean_db() as s:
        row = queue.get_state(s, FetchKind.DOSSIER, CNR)
        assert (row.status, row.priority, row.lane) == (FetchStatus.PENDING, 50, FetchLane.DAILY)
        assert row.created_at > old + timedelta(days=29)


def test_routine_refresh_is_claimed_before_a_new_order_pdf(world):
    """Decision 11 (owner, 12 Nov 2026): case details always first. A pending case's new order PDF waits at 60 behind
    every routine refresh row (56 to 59), even one queued later."""
    with world.Session() as s:
        live = _case(s, 2)
        _order(s, live, D - timedelta(days=1))
        assert enqueue_order_pdfs(s, live) == 1
        due = _case(s, 7)
        queue.enqueue(s, FetchKind.DOSSIER, due.cnr, queue.PRIORITY["dossier_early"], lane=FetchLane.DAILY)
        first, second = queue.claim(s), queue.claim(s)
        assert (first.kind, first.ref, first.priority) == (FetchKind.DOSSIER, due.cnr, 59)
        assert (second.kind, second.priority) == (FetchKind.ORDER_PDF, 60)
        s.rollback()


def test_pdfs_after_details_keeps_pending_order_pdfs_at_60(world):
    """Decision 15: `pdfs-after-details` is unchanged; a pending case's order PDF at 60 and the routine rows are left
    as they are, and a second run moves nothing."""
    from aslms.services import data_load

    with world.Session() as s:
        live = _case(s, 2)
        _order(s, live, D - timedelta(days=1))
        enqueue_order_pdfs(s, live)
        queue.enqueue(s, FetchKind.DOSSIER, live.cnr, 56)
        s.commit()
        actor, user = world.actor(s, "root")
    for _ in range(2):
        out = data_load.pdfs_after_details(world.Session, actor, user, apply=True)
        assert out["found"]["rows"] == 0
    with world.Session() as s:
        prio = {(FetchKind(r.kind), r.priority) for r in s.scalars(sa.select(FetchQueueItem)).all()}
        assert prio == {(FetchKind.ORDER_PDF, 60), (FetchKind.DOSSIER, 56)}


# ------------------------------------------------------------------------------------------------ the two slots


def test_two_slots_never_claim_the_same_row_and_second_skips_status_batches(world):
    with world.Session() as s:
        queue.enqueue(s, FetchKind.STATUS_BATCH, f"{D.isoformat()}:0", 30)
        queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000001112025", 57)
        queue.enqueue(s, FetchKind.ORDER_PDF, "GAHC010000001112025|1|2025-01-10", 60)
        s.commit()
    second_a, main, second_b = world.Session(), world.Session(), world.Session()
    try:
        a = queue.claim(second_a, SLOT_KINDS["second"])
        assert a.kind == FetchKind.DOSSIER, "the second slot passes over the status batch"
        m = queue.claim(main, SLOT_KINDS["main"])
        assert m.kind == FetchKind.STATUS_BATCH
        b = queue.claim(second_b, SLOT_KINDS["second"])
        assert b.kind == FetchKind.ORDER_PDF, "the row the other slot holds is skipped"
        assert len({a.id, m.id, b.id}) == 3
        assert queue.claim(second_b, SLOT_KINDS["second"]) is None
    finally:
        for s in (second_a, main, second_b):
            s.rollback()
            s.close()


# ------------------------------------------------------------------------------------------------ the schedule


def test_schedule_view_nightly_facts(world):
    with world.Session() as s:
        _case(s, 9)  # not refreshed in 7 days (age 8 or more)
        _case(s, 2, heard=D - timedelta(days=5))  # heard, awaiting its order
        _case(s, None)  # not disposed, never fully fetched
        _case(s, 30, status=CaseStatus.DISPOSED)
        view = schedules.schedule_view(s, SETTINGS)
        entry = next(e for e in view["entries"] if e["key"] == "nightly-refresh")
        assert entry["when"] == "22:00" and entry["result"] is None
        assert entry["facts"] == {"pending": 3, "not_refreshed_7d": 1, "heard_waiting": 1}
        weekly = next(e for e in view["entries"] if e["key"] == "weekly")
        assert (
            weekly["what"]
            == "Fetch cases never fully fetched, and try again for orders the court had not published"
        )
        s.rollback()
