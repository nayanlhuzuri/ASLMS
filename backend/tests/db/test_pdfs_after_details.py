"""Case details before order PDFs (owner, 24 Oct 2026) against the test database: `aslms data-load
pdfs-after-details` moves the order PDFs queued before the change (daily, load and discovery rows below 60, pending,
failed, skipped or done) to 60 for a pending case and 80 otherwise, never a request-lane or running row; a dry run
writes nothing; the apply runs in batches and repeated passes under a `job_runs` row with one audit row, skips locked
rows and catches a row that came back below 60 behind the keyset; a second run moves nothing; a moved failed or
skipped row is revived at 60, not its old priority. And the claim order: a load dossier at 44 is claimed before a
pending order PDF at 60."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import sqlalchemy as sa

from aslms.domain.cases import Case, CaseStatus
from aslms.domain.documents import DownloadStatus, Order, OrderKind
from aslms.domain.events import AuditLog
from aslms.domain.ops import FetchKind, FetchLane, FetchQueueItem, FetchStatus, JobRun, JobStatus
from aslms.services import data_load, napix_admin, queue
from aslms.services.access import Forbidden
from aslms.services.orders import enqueue_order_pdfs
from tests.db.world import make_case

ACTION = "data_load.pdfs_after_details"


def _put(
    s,
    ref: str,
    *,
    lane: FetchLane,
    priority: int,
    status=FetchStatus.PENDING,
    kind=FetchKind.ORDER_PDF,
    id: uuid.UUID | None = None,
):
    s.add(FetchQueueItem(id=id, kind=kind, ref=ref, status=status, lane=lane, priority=priority))


def _prio(s) -> dict[tuple[str, str], int]:
    return {
        (FetchKind(r.kind).value, r.ref): r.priority
        for r in s.scalars(sa.select(FetchQueueItem).execution_options(populate_existing=True)).all()
    }


def _audits(s) -> list[AuditLog]:
    return list(s.scalars(sa.select(AuditLog).where(AuditLog.action == ACTION).order_by(AuditLog.created_at)))


def _seed(s) -> dict[str, str]:
    """Order PDFs of a pending, a disposed and an unknown case in each lane and status, plus rows the command must
    leave alone."""
    live = make_case(s, status=CaseStatus.PENDING)
    gone = make_case(s, status=CaseStatus.DISPOSED)
    unknown = make_case(s, status=CaseStatus.UNKNOWN)
    refs = {
        "daily_live": f"{live.cnr}|1|2025-01-10",
        "daily_gone": f"{gone.cnr}|1|2025-01-10",
        "load_live": f"{live.cnr}|2|2025-01-11",
        "load_gone": f"{gone.cnr}|2|2025-01-11",
        "disc_live": f"{live.cnr}|3|2025-01-12",
        "disc_gone": f"{gone.cnr}|3|2025-01-12",
        "no_case": "ASHC019999992025|1|2025-01-13",
        "unknown": f"{unknown.cnr}|1|2025-01-13",
        "request": f"{live.cnr}|4|2025-01-14",
        "request_failed": f"{live.cnr}|9|2025-01-14",
        "running": f"{live.cnr}|5|2025-01-15",
        "done": f"{live.cnr}|6|2025-01-16",
        "failed": f"{live.cnr}|7|2025-01-16",
        "skipped": f"{live.cnr}|8|2025-01-16",
        "at_80": f"{gone.cnr}|7|2025-01-17",
    }
    _put(s, refs["daily_live"], lane=FetchLane.DAILY, priority=40)
    _put(s, refs["daily_gone"], lane=FetchLane.DAILY, priority=40)
    _put(s, refs["load_live"], lane=FetchLane.LOAD, priority=43)
    _put(s, refs["load_gone"], lane=FetchLane.LOAD, priority=48)
    _put(s, refs["disc_live"], lane=FetchLane.DISCOVERY, priority=49)
    _put(s, refs["disc_gone"], lane=FetchLane.DISCOVERY, priority=49)
    _put(s, refs["no_case"], lane=FetchLane.DAILY, priority=40)
    _put(s, refs["unknown"], lane=FetchLane.DAILY, priority=40)
    _put(s, refs["request"], lane=FetchLane.REQUEST, priority=40)
    _put(s, refs["request_failed"], lane=FetchLane.REQUEST, priority=40, status=FetchStatus.FAILED)
    _put(s, refs["running"], lane=FetchLane.DAILY, priority=40, status=FetchStatus.RUNNING)
    _put(s, refs["done"], lane=FetchLane.LOAD, priority=48, status=FetchStatus.DONE)
    _put(s, refs["failed"], lane=FetchLane.DAILY, priority=40, status=FetchStatus.FAILED)
    _put(s, refs["skipped"], lane=FetchLane.DAILY, priority=40, status=FetchStatus.SKIPPED)
    _put(s, refs["at_80"], lane=FetchLane.DAILY, priority=80)
    _put(s, live.cnr, lane=FetchLane.LOAD, priority=44, kind=FetchKind.DOSSIER)  # not a PDF: untouched
    s.flush()
    return refs


FOUND = {
    "rows": 11,
    "to_60": 6,
    "to_80": 5,
    "by_lane": {"daily": 6, "discovery": 2, "load": 3},
    "by_status": {"done": 1, "failed": 1, "pending": 8, "skipped": 1},
}


def test_dry_run_counts_and_writes_nothing(world):
    with world.Session() as s:
        _seed(s)
        s.commit()
        before = _prio(s)
        actor, user = world.actor(s, "root")
    out = data_load.pdfs_after_details(world.Session, actor, user, apply=False)
    assert out["dry_run"] is True and out["moved"] is None and out["job_run_id"] is None
    assert out["found"] == {**FOUND, "running": 1}
    assert out["request_lane_kept"] == 2
    with world.Session() as s:
        assert _prio(s) == before
        assert _audits(s) == []
        assert s.scalar(sa.select(sa.func.count()).select_from(JobRun)) == 0


def test_apply_moves_in_batches_audits_and_is_idempotent(world):
    with world.Session() as s:
        refs = _seed(s)
        s.commit()
        before = _prio(s)
        actor, user = world.actor(s, "root")
    out = data_load.pdfs_after_details(world.Session, actor, user, apply=True, batch=3)
    assert out["dry_run"] is False
    # 11 rows in batches of 3: four batches in the first pass, a second pass moves nothing; the running row is left
    assert out["moved"] == {**FOUND, "batches": 4, "passes": 2, "left": 1}
    pdf = FetchKind.ORDER_PDF.value
    with world.Session() as s:
        after = _prio(s)
        for key in ("daily_live", "load_live", "disc_live", "done", "failed", "skipped"):
            assert after[(pdf, refs[key])] == 60, key
        # the enqueue path's rule: only a pending case's PDF takes 60
        for key in ("daily_gone", "load_gone", "disc_gone", "no_case", "unknown", "at_80"):
            assert after[(pdf, refs[key])] == 80, key
        assert after[(pdf, refs["request"])] == 40  # a person's order PDF keeps its place
        assert after[(pdf, refs["request_failed"])] == 40
        assert after[(pdf, refs["running"])] == 40  # running: untouched
        dossiers = {k: v for k, v in after.items() if k[0] == FetchKind.DOSSIER.value}
        assert dossiers == {k: v for k, v in before.items() if k[0] == FetchKind.DOSSIER.value}
        (run,) = s.scalars(sa.select(JobRun).where(JobRun.job == "pdfs-after-details")).all()
        assert run.id == out["job_run_id"] and JobStatus(run.status) == JobStatus.SUCCEEDED
        assert run.finished_at is not None and run.counters["rows"] == 11 and run.counters["batches"] == 4
        assert run.counters["passes"] == 2 and run.counters["left"] == 1
        (audit,) = _audits(s)
        assert audit.entity_type == "fetch_queue" and audit.actor_user_id == user.id
        assert audit.after["rows"] == 11 and audit.after["to_60"] == 6 and audit.after["to_80"] == 5
        assert audit.after["by_lane"] == FOUND["by_lane"] and audit.after["by_status"] == FOUND["by_status"]
        assert audit.after["request_lane_kept"] == 2 and audit.after["job_run_id"] == str(run.id)

    again = data_load.pdfs_after_details(world.Session, actor, user, apply=True)
    assert again["found"]["rows"] == 0 and again["moved"]["rows"] == 0 and again["job_run_id"] is None
    assert again["found"]["running"] == 1 and again["moved"]["left"] == 1
    with world.Session() as s:
        assert _prio(s) == after
        assert len(_audits(s)) == 1  # nothing moved: no second audit row
        assert s.scalar(sa.select(sa.func.count()).select_from(JobRun)) == 1


def test_needs_admin_data_load(world):
    with world.Session() as s:
        _seed(s)
        s.commit()
        actor, user = world.actor(s, "edu_off1")
    with pytest.raises(Forbidden):
        data_load.pdfs_after_details(world.Session, actor, user, apply=True)
    with world.Session() as s:
        assert _audits(s) == [] and 40 in set(_prio(s).values())


def test_load_dossier_claimed_before_order_pdf_at_60(world):
    """An older pending order PDF at 60 waits behind a newer load dossier at 44 (the claim orders by priority)."""
    with world.Session() as s:
        case = make_case(s)
        queue.enqueue(s, FetchKind.ORDER_PDF, f"{case.cnr}|1|2025-01-10", 60)
        s.commit()
        queue.enqueue(s, FetchKind.DOSSIER, case.cnr, 44, lane=FetchLane.LOAD, list_date=date(2025, 1, 10))
        s.commit()
        first = queue.claim(s)
        assert first is not None and first.kind == FetchKind.DOSSIER and first.priority == 44
        second = queue.claim(s)
        assert second is not None and second.kind == FetchKind.ORDER_PDF and second.priority == 60
        s.rollback()


def test_moved_failed_and_skipped_rows_revive_at_60(world):
    """A failed or skipped order PDF queued at 40 before the change comes back at 60 after the command, through
    `queue-retry-failed` and the weekly path (`enqueue_order_pdfs` with the daily origin), not at its old 40."""
    with world.Session() as s:
        case = make_case(s, status=CaseStatus.PENDING)
        for no in ("1", "2"):
            s.add(
                Order(
                    case_id=case.id,
                    order_no=no,
                    order_date=date(2025, 1, 10),
                    kind=OrderKind.INTERIM,
                    download_status=DownloadStatus.PENDING,
                )
            )
        case_id = case.id
        skipped, failed = f"{case.cnr}|1|2025-01-10", f"{case.cnr}|2|2025-01-10"
        _put(s, skipped, lane=FetchLane.DAILY, priority=40, status=FetchStatus.SKIPPED)
        _put(s, failed, lane=FetchLane.DAILY, priority=40, status=FetchStatus.FAILED)
        s.commit()
        actor, user = world.actor(s, "root")
    out = data_load.pdfs_after_details(world.Session, actor, user, apply=True)
    assert out["moved"]["rows"] == 2 and out["moved"]["by_status"] == {"failed": 1, "skipped": 1}
    with world.Session() as s:
        assert napix_admin.retry_failed(s, actor, world.user(s, "root"), FetchKind.ORDER_PDF) == 1
        assert enqueue_order_pdfs(s, s.get(Case, case_id)) == 2
        s.commit()
        rows = {
            r.ref: (FetchStatus(r.status), r.priority)
            for r in s.scalars(sa.select(FetchQueueItem).execution_options(populate_existing=True))
        }
    assert rows == {skipped: (FetchStatus.PENDING, 60), failed: (FetchStatus.PENDING, 60)}


class _Hooked:
    """A session factory that runs `fn` in a session of its own just before handing out its `at`-th session."""

    def __init__(self, factory, at: int, fn):
        self.factory, self.at, self.fn, self.n = factory, at, fn, 0

    def __call__(self):
        self.n += 1
        if self.n == self.at:
            with self.factory() as s:
                self.fn(s)
                s.commit()
        return self.factory()


LOW = uuid.UUID("00000000-0000-7000-8000-000000000001")
HIGH = uuid.UUID("ffffffff-ffff-7fff-bfff-ffffffffffff")


def test_apply_catches_a_row_that_came_back_behind_the_keyset(world):
    """A row running during the first pass that fails and returns to pending at 40, behind the keyset, is moved by
    the next pass."""
    with world.Session() as s:
        case = make_case(s, status=CaseStatus.PENDING)
        _put(
            s,
            f"{case.cnr}|1|2025-01-10",
            lane=FetchLane.DAILY,
            priority=40,
            status=FetchStatus.RUNNING,
            id=LOW,
        )
        _put(s, f"{case.cnr}|2|2025-01-10", lane=FetchLane.DAILY, priority=40, id=HIGH)
        s.commit()
        actor, user = world.actor(s, "root")

    def fail_back(s):
        s.execute(
            sa.update(FetchQueueItem).where(FetchQueueItem.id == LOW).values(status=FetchStatus.PENDING)
        )

    # sessions: 1 the counts, 2 the job run, 3 pass 1 batch 1 (moves HIGH), 4 pass 1 batch 2: LOW fails back first
    out = data_load.pdfs_after_details(_Hooked(world.Session, 4, fail_back), actor, user, apply=True)
    assert out["found"]["rows"] == 1 and out["found"]["running"] == 1
    assert out["moved"]["rows"] == 2 and out["moved"]["passes"] == 3 and out["moved"]["left"] == 0
    with world.Session() as s:
        assert set(_prio(s).values()) == {60}


def test_apply_skips_a_locked_row_and_a_rerun_moves_it(world):
    """`SKIP LOCKED`: a row a runner holds does not make the command wait; it is counted as left and a re-run moves
    it once the lock is gone."""
    with world.Session() as s:
        case = make_case(s, status=CaseStatus.PENDING)
        held, free = f"{case.cnr}|1|2025-01-10", f"{case.cnr}|2|2025-01-10"
        _put(s, held, lane=FetchLane.DAILY, priority=40)
        _put(s, free, lane=FetchLane.DAILY, priority=40)
        s.commit()
        actor, user = world.actor(s, "root")
    pdf = FetchKind.ORDER_PDF.value
    with world.Session() as runner:
        runner.execute(sa.select(FetchQueueItem.id).where(FetchQueueItem.ref == held).with_for_update())
        out = data_load.pdfs_after_details(world.Session, actor, user, apply=True)
        assert out["moved"]["rows"] == 1 and out["moved"]["left"] == 1 and out["moved"]["passes"] == 2
        runner.rollback()
    with world.Session() as s:
        assert _prio(s) == {(pdf, held): 40, (pdf, free): 60}
    again = data_load.pdfs_after_details(world.Session, actor, user, apply=True)
    assert again["moved"]["rows"] == 1 and again["moved"]["left"] == 0
    with world.Session() as s:
        assert _prio(s) == {(pdf, held): 60, (pdf, free): 60}
