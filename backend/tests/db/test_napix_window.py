"""The detected quota window and the user behind each call (design `napix-window`, decisions 4, 7, 9 and 10) against
the test database and the scripted gateway: attempt times and users in the call log, the runner waiting for the
expected reset (not the clock hour), probing only when it must and at most once a pass, `requested_by` carried from a
person's request row to its calls and spawned rows, and the queue's conflict and CHECK rules."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from aslms.core.config import Settings
from aslms.domain.ops import (
    DataLoadSettings,
    FetchKind,
    FetchLane,
    FetchQueueItem,
    FetchStatus,
    JobRun,
    NapixCallLog,
)
from aslms.services import napix_admin, queue
from aslms.services.napix_store import NapixRecorder
from aslms.services.runner import QueueRunner
from aslms.services.storage import LocalStore
from tests.db.world import make_case

CNR = "GAHC010000000001"
OTHER = "GAHC010000000002"
LOAD_CNR = "GAHC010000000003"


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        storage_dir=str(tmp_path / "store"),
        causelist_dir=str(tmp_path / "lists"),
        redis_url=None,
    )


def _runner(Session, hc, tmp_path, recorder: NapixRecorder) -> QueueRunner:
    settings = _settings(tmp_path)
    return QueueRunner(
        Session,
        hc,
        settings=settings,
        store=LocalStore(settings.storage_dir),
        causelist_dir=tmp_path / "lists",
        recorder=recorder,
    )


def _run(napix, Session, tmp_path, **kw):
    gw, client, hc = napix
    recorder = NapixRecorder()
    client.on_call = recorder.on_call

    async def go():
        async with client:
            return await _runner(Session, hc, tmp_path, recorder).run(**kw)

    return asyncio.run(go())


def _reading(s, at: datetime, remaining: int, api: str = "hc-cnr-api/CNR") -> None:
    s.add(
        NapixCallLog(api=api, params_sha256="r" * 64, ok=True, rate_limit_remaining=remaining, called_at=at)
    )


def _anchor(s, anchor: datetime) -> None:
    """A precise reset at `anchor`: the previous reading 10 s before it."""
    _reading(s, anchor - timedelta(seconds=10), 300)
    _reading(s, anchor, 999)


def _rows(s, *where):
    return s.execute(
        sa.select(
            NapixCallLog.api,
            NapixCallLog.lane,
            NapixCallLog.user_id,
            NapixCallLog.job_run_id,
            NapixCallLog.rate_limit_remaining,
            NapixCallLog.called_at,
        )
        .where(NapixCallLog.params_sha256 != "r" * 64, *where)
        .order_by(NapixCallLog.called_at, NapixCallLog.id)
    ).all()


def _load_row(s, ref: str = LOAD_CNR) -> None:
    queue.enqueue(s, FetchKind.DOSSIER, ref, 44, lane=FetchLane.LOAD, list_date=date(2025, 1, 6))


# ------------------------------------------------------------------------------------------------ decision 7 and 9


def test_recorder_writes_attempt_time_and_user(world, napix):
    gw, client, hc = napix
    with world.Session() as s:
        root = world.user(s, "root")
        recorder = NapixRecorder(user_id=root.id)
        client.on_call = recorder.on_call
        gw.responses = [lambda p, q, r: httpx.Response(503), lambda p, q, r: gw.envelope({"ok": 1})]

        async def go():
            async with client:
                await client.call("overview/overview")

        asyncio.run(go())
        attempts = list(recorder.pending)
        assert len(attempts) == 2
        recorder.flush(s)
        s.commit()
        rows = _rows(s)
    assert [r.user_id for r in rows] == [root.id, root.id]
    assert [r.called_at for r in rows] == [a.called_at for a in attempts]  # the attempts' own times
    assert rows[0].called_at < rows[1].called_at  # distinct within one item, not the transaction's now()


# ------------------------------------------------------------------------------------------------ decision 4


def test_runner_waits_for_expected_reset_not_clock_hour(world, napix, tmp_path):
    gw, _client, _hc = napix
    now = datetime.now(UTC)
    anchor = now - timedelta(minutes=56)  # the reset seen at ":34"; now is ":30" with 148 left
    with world.Session() as s:
        _anchor(s, anchor)
        _reading(s, now - timedelta(seconds=30), 148)
        _load_row(s)
        s.commit()
    rep = _run(napix, world.Session, tmp_path)
    assert rep.processed == 0 and rep.probes == 0 and gw.seen == []
    assert rep.resume_at == anchor + timedelta(seconds=3600 + 60)  # E + margin, not the next clock hour
    assert rep.load_only is True and rep.window.status == "current"
    assert rep.stopped_reason.startswith(
        "load waits: 148 left < reserve 150; window current, next reset about"
    )
    with world.Session() as s:
        assert _rows(s) == []
        assert s.scalar(sa.select(FetchQueueItem.status).where(FetchQueueItem.ref == LOAD_CNR)) == "pending"
        assert s.get(JobRun, rep.job_run_id).counters["probes"] == 0


def test_runner_probes_when_reset_due_then_runs_load(world, napix, tmp_path):
    gw, _client, _hc = napix
    gw.rate_headers = {"X-RateLimit-Limit": "1000", "X-RateLimit-Remaining": "999"}
    now = datetime.now(UTC)
    anchor = now - timedelta(minutes=65)  # E was 5 minutes ago; no reading since
    with world.Session() as s:
        _anchor(s, anchor)
        _reading(s, anchor + timedelta(minutes=20), 148)
        _load_row(s)
        s.commit()
    rep = _run(napix, world.Session, tmp_path, max_items=1)
    assert rep.probes == 1 and rep.done == 1, (rep.stopped_reason, rep.items)
    assert gw.seen[0]["path"] == "overview/overview"
    with world.Session() as s:
        rows = _rows(s)
        probe, *load = rows
        assert (probe.api, probe.lane, probe.user_id, probe.job_run_id) == (
            "overview/overview",
            None,
            None,
            rep.job_run_id,
        )
        assert load and {r.lane for r in load} == {FetchLane.LOAD}
        assert s.get(JobRun, rep.job_run_id).counters["probes"] == 1


def test_runner_overdue_probes_every_interval(world, napix, tmp_path):
    gw, _client, _hc = napix
    gw.rate_headers = {"X-RateLimit-Limit": "1000", "X-RateLimit-Remaining": "140"}  # no reset seen
    now = datetime.now(UTC)
    anchor = now - timedelta(minutes=65)
    with world.Session() as s:
        _anchor(s, anchor)
        _reading(s, anchor + timedelta(minutes=20), 148)
        _load_row(s)
        s.commit()
    rep = _run(napix, world.Session, tmp_path)
    assert rep.probes == 1 and rep.processed == 0
    assert [x["path"] for x in gw.seen] == ["overview/overview"]  # no second probe in the same pass
    assert rep.window.status == "overdue" and rep.load_only is True
    with world.Session() as s:
        (probe,) = _rows(s)
    assert rep.resume_at == probe.called_at + timedelta(seconds=180)


def test_no_probe_without_runnable_work(world, napix, tmp_path):
    gw, _client, _hc = napix
    rep = _run(napix, world.Session, tmp_path)  # empty queue, no reading: the remaining count is unknown
    assert rep.probes == 0 and rep.stopped_reason == "queue empty" and gw.seen == []
    with world.Session() as s:
        _load_row(s)
        s.add(DataLoadSettings(version=1, paused=True, is_current=True, reason="paused for the test"))
        s.commit()
    rep = _run(napix, world.Session, tmp_path)  # only a paused load: nothing runnable
    assert rep.probes == 0 and rep.processed == 0 and gw.seen == []
    with world.Session() as s:
        assert _rows(s) == []


# ------------------------------------------------------------------------------------------------ decisions 9-10


def test_request_row_user_reaches_call_log(world, napix, tmp_path):
    gw, _client, _hc = napix
    gw.rate_headers = {"X-RateLimit-Limit": "1000", "X-RateLimit-Remaining": "900"}
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        case = make_case(s, cnr=CNR)
        state = napix_admin.refetch_case(s, actor, root, case, _settings(tmp_path))
        assert state["lane"] == "request"
        queue.enqueue(s, FetchKind.DOSSIER, OTHER, 40)  # the daily cycle
        _load_row(s)
        s.commit()
        root_id = root.id
        assert queue.get_state(s, FetchKind.DOSSIER, CNR).requested_by == root_id
    rep = _run(napix, world.Session, tmp_path)
    assert rep.failed == 0, rep.items
    with world.Session() as s:
        rows = [r for r in _rows(s) if r.api != "overview/overview"]
        by_lane = {(r.lane, r.user_id) for r in rows}
        assert (FetchLane.REQUEST, root_id) in by_lane
        assert by_lane <= {(FetchLane.REQUEST, root_id), (FetchLane.DAILY, None), (FetchLane.LOAD, None)}
        assert {FetchLane.DAILY, FetchLane.LOAD} <= {lane for lane, _ in by_lane}
        pdfs = s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.ORDER_PDF)).all()
        mine = [p for p in pdfs if p.ref.startswith(CNR)]
        assert mine and {(p.lane, p.requested_by) for p in mine} == {(FetchLane.REQUEST, root_id)}
        assert all(p.requested_by is None for p in pdfs if not p.ref.startswith(CNR))


def test_requested_by_conflict_rules(world):
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        a, b = root.id, world.user(s, "central_op").id
        D = FetchKind.DOSSIER
        R = FetchLane.REQUEST

        def row(ref=CNR):
            return queue.get_state(s, D, ref)

        def set_status(status, ref=CNR):
            s.execute(
                sa.text("update fetch_queue set status = CAST(:st AS fetch_queue_status) where ref = :r"),
                {"st": status, "r": ref},
            )

        # insert: the caller's person; pending keeps the first person, whoever asks next
        queue.enqueue(s, D, CNR, 30, lane=R, requested_by=a)
        assert row().requested_by == a
        queue.enqueue(s, D, CNR, 30, lane=R, requested_by=b)
        queue.enqueue(s, D, CNR, 40)
        assert (row().requested_by, row().lane) == (a, R)
        # a pending load row asked for by a person: the lane moves to request and takes the person
        queue.enqueue(s, D, OTHER, 44, lane=FetchLane.LOAD)
        queue.enqueue(s, D, OTHER, 30, lane=R, requested_by=b)
        assert (row(OTHER).lane, row(OTHER).requested_by) == (R, b)
        # revive: the caller's value, a system caller's NULL included
        set_status("failed")
        queue.enqueue(s, D, CNR, 30, lane=R, requested_by=b)
        assert row().requested_by == b
        set_status("failed")
        queue.enqueue(s, D, CNR, 40)
        assert (row().requested_by, row().lane) == (None, R)
        # requeue of a done row takes the caller's value; without requeue nothing changes
        set_status("done")
        queue.enqueue(s, D, CNR, 30, lane=R, requested_by=a, requeue=True)
        assert row().requested_by == a
        set_status("done")
        queue.enqueue(s, D, CNR, 30, lane=R, requested_by=b)
        assert row().requested_by == a
        # a running load row asked for by a person keeps no person (the lane does not change while running)
        queue.enqueue(s, D, LOAD_CNR, 44, lane=FetchLane.LOAD)
        set_status("running", LOAD_CNR)
        queue.enqueue(s, D, LOAD_CNR, 30, lane=R, requested_by=a)
        assert (row(LOAD_CNR).lane, row(LOAD_CNR).requested_by) == (FetchLane.LOAD, None)
        # a person with another lane is refused before any SQL
        with pytest.raises(ValueError):
            queue.enqueue(s, D, "GAHC010000000009", 44, lane=FetchLane.LOAD, requested_by=a)
        assert row("GAHC010000000009") is None
        # retry-failed passes no person (it may revive load rows)
        set_status("failed")
        assert napix_admin.retry_failed(s, actor, root, D) >= 1
        assert (row().status, row().requested_by) == (FetchStatus.PENDING, None)
        s.rollback()


def test_requested_by_check_constraint(world):
    with world.Session() as s:
        root_id = world.user(s, "root").id
        _load_row(s)
        s.flush()
        with pytest.raises(IntegrityError) as exc:
            s.execute(
                sa.text("update fetch_queue set requested_by = :u where ref = :r"),
                {"u": root_id, "r": LOAD_CNR},
            )
        assert "ck_fetch_queue_requested_by" in str(exc.value)
        s.rollback()
