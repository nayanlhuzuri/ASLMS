"""The queue runner: pulls `fetch_queue` rows in priority order and dispatches them to the pipeline stages,
spending the gateway budget by bands (design `data-load-console`, decision 4): any lane while the window's remaining
quota is at least `NAPIX_RATE_RESERVE`; only the daily and request lanes between `NAPIX_LIVE_RESERVE` and it; nothing
below `NAPIX_LIVE_RESERVE`. The discovery lane (design `department-discovery`, decision 6) is claimed in the top band
only and while its calls in the current window are below `NAPIX_DISCOVERY_SHARE`; once the share is spent the pass
claims the other lanes only, and when they hold nothing runnable it ends as a load-only block.

A person's "now" request (design `data-collection-redesign`, decision 24) is claimed before the bands: a row at
priority 5 or less whenever the window's remaining count is unknown or at least 1, whatever the reserves and the
discovery share. Only the court's own limit stops it. The claimed row's priority goes into `QueueOrigin.now_priority`,
so what it spawns runs at the same priority.

The window is detected, not assumed (design `napix-window`, decisions 3-4): each pass seeds the remaining count from
`napix_window.current`. When that count is unknown (the reset is due, overdue or the timing not known yet) and work is
waiting, the pass first makes one **probe** (an Overview call, lane and user NULL, the pass's `job_run_id`), at most one
per pass. When the bands block, the pass stops with `resume_at`: the expected reset plus the margin in a `current`
window, else the latest reading plus the probe interval; the worker sleeps until then.

A gateway fault pauses the pass (design `safety-fixes`, decision 8): after `NAPIX_FAULT_STREAK` items in a row failed
with `NapixUnavailable` (any cause, the empty HTTP 200 included) the pass stops with `fault_pause` and `resume_at` =
now + `NAPIX_FAULT_PAUSE_SECONDS`; a done or skipped item resets the count. Failed rows wait on the queue's ladder.
`search_rows` rows make no NAPIX call and are never claimed here (`queue.LOCAL_KINDS`).

One `job_runs` row per invocation (counters include `probes`); every NAPIX attempt is logged with the lane of its item
and the person who asked for it (`requested_by`), and every response kept by the recorder. Work an item spawns
inherits its lane, `list_date` and person (`QueueOrigin`). Survives restarts: a row is only `done` when its
transaction committed.

Two worker slots (design `rolling-case-refresh`, decisions 16-18): `aslms queue-worker --slot main` claims every kind
and writes `queue-run` passes; `--slot second` claims every NAPIX kind except `status_batch` (`SLOT_KINDS`) and writes
`queue-run-second` passes, so a slow Current Status call never holds up order PDFs and other short calls. Both read the
same window and bands. A routine nightly `dossier` row (56 to 59) whose case was fully refreshed after the row was
queued ends `done` with `fresh_since_queued` and makes no call (decision 6)."""

from __future__ import annotations

import asyncio
import traceback
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from aslms.core.clock import today_ist
from aslms.core.config import Settings, get_settings
from aslms.core.errors import IntegrationError, NapixInputError, NapixNotFound, NapixUnavailable
from aslms.domain.cases import Case, FirstSeenSource
from aslms.domain.courts import Court
from aslms.domain.ops import FetchKind, FetchLane, FetchQueueItem, JobRun, JobStatus
from aslms.integration.napix.client import NapixClient
from aslms.integration.napix.hc import NapixHighCourt
from aslms.services import case_dedupe, court_search, discovery, napix_window, queue
from aslms.services.cases import find_case, get_or_create_case
from aslms.services.causelists import load_causelist_day, recheck_day
from aslms.services.job_repair import SLOT_JOBS
from aslms.services.load_policy import NOW_BULK, QueueOrigin, current_settings, load_priority, now_priority_of
from aslms.services.masters import sync_masters
from aslms.services.napix_store import NapixRecorder
from aslms.services.orders import fetch_order_pdf
from aslms.services.storage import LocalStore
from aslms.services.tracking import run_status_batch

log = structlog.get_logger(__name__)


class BudgetExhausted(Exception):
    """The gateway's remaining quota is below the reserve; wait for the next window."""


@dataclass
class RunReport:
    job_run_id: uuid.UUID | None = None
    processed: int = 0
    done: int = 0
    failed: int = 0
    skipped: int = 0
    calls: int = 0
    stopped_reason: str | None = None
    items: list[dict[str, Any]] = field(default_factory=list)
    # design napix-window, decision 4: when the bands stopped the pass, when to run again; the probes made
    resume_at: datetime | None = None
    probes: int = 0
    load_only: bool = False  # only the load lane was blocked: daily and request rows may still arrive
    window: napix_window.WindowState | None = None
    # design safety-fixes, decision 8: the pass stopped on a run of gateway faults; `resume_at` says when to go on
    fault_pause: bool = False
    # design data-collection-redesign, decision 24: the remaining count when the pass ended (None = unknown) and
    # whether its window probe failed; the sleeping worker wakes for a "now" row only when neither forbids it
    remaining: int | None = None
    probe_failed: bool = False

    def now_may_wake(self) -> bool:
        """A "now" row may cut the sleep short unless the pass stopped on a fault pause, a failed probe or the court's
        own limit (no call left in the window): those waits hold for every row."""
        if self.fault_pause or self.probe_failed:
            return False
        return self.remaining is None or self.remaining >= 1


@dataclass(frozen=True)
class Claimed:
    """The fields of a claimed row the pass needs after its session closed."""

    id: uuid.UUID
    kind: FetchKind
    ref: str
    lane: FetchLane
    list_date: date | None
    requested_by: uuid.UUID | None
    priority: int

    @classmethod
    def of(cls, item: FetchQueueItem) -> Claimed:
        return cls(
            item.id,
            FetchKind(item.kind),
            item.ref,
            FetchLane(item.lane),
            item.list_date,
            item.requested_by,
            int(item.priority),
        )


class QueueRunner:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        hc: NapixHighCourt | None,
        *,
        settings: Settings | None = None,
        store: LocalStore | None = None,
        causelist_dir: Path | None = None,
        recorder: NapixRecorder | None = None,
        reserve: int | None = None,
    ):
        self.settings = settings or get_settings()
        self.session_factory = session_factory
        self.hc = hc
        self.store = store or LocalStore(self.settings.storage_dir)
        self.causelist_dir = causelist_dir if causelist_dir is not None else Path(self.settings.causelist_dir)
        self.recorder = recorder or NapixRecorder()
        self.reserve = self.settings.napix_rate_reserve if reserve is None else reserve
        self.live_reserve = min(self.settings.napix_live_reserve, self.reserve)
        self.window: napix_window.WindowState | None = None
        self.discovery_share = self.settings.napix_discovery_share
        self.discovery_used = (
            0  # discovery-lane calls in the current window (log + this pass since the last read)
        )
        self.fault_streak = self.settings.napix_fault_streak
        self.fault_pause_seconds = self.settings.napix_fault_pause_seconds

    # ------------------------------------------------------------------ lifecycle
    def start_job(self, job: str) -> uuid.UUID:
        with self.session_factory() as s:
            run = JobRun(job=job, run_date=today_ist())
            s.add(run)
            s.commit()
            self.recorder.job_run_id = run.id
            return run.id

    def finish_job(self, job_run_id: uuid.UUID, report: RunReport, status: JobStatus) -> None:
        with self.session_factory() as s:
            run = s.get(JobRun, job_run_id)
            if run is not None:
                run.finished_at = datetime.now(UTC)
                run.status = status
                run.counters = {
                    "processed": report.processed,
                    "done": report.done,
                    "failed": report.failed,
                    "skipped": report.skipped,
                    "calls": report.calls,
                    "probes": report.probes,
                    "stopped": report.stopped_reason,
                }
            self.recorder.flush(s)
            s.commit()

    def share_left(self) -> int:
        """Discovery calls still allowed in the current window (design `department-discovery`, decision 6)."""
        return max(0, self.discovery_share - self.discovery_used)

    def budget_lanes(self) -> tuple[bool, list[FetchLane] | None]:
        """Decision 4: (may claim, lanes). Any lane at or above the rate reserve, the discovery lane only while its
        share of the window is not spent; the daily and request lanes between the live reserve and it; nothing below
        the live reserve."""
        rem = self.recorder.last_remaining
        if rem is None or rem >= self.reserve:
            if self.share_left() > 0:
                return True, None
            return True, [FetchLane.REQUEST, FetchLane.DAILY, FetchLane.LOAD]
        if rem >= self.live_reserve:
            return True, [FetchLane.REQUEST, FetchLane.DAILY]
        return False, None

    def read_share(self, s: Session, now: datetime | None = None) -> int:
        """Discovery calls logged since the window's start (the last 3,600 s when unknown); replaces the count."""
        window = self.window or napix_window.current(s, self.settings, now)
        self.discovery_used = discovery.discovery_calls(s, window, now)
        return self.discovery_used

    def budget_ok(self) -> bool:
        return self.budget_lanes()[0]

    def seed_remaining(self, now: datetime | None = None) -> napix_window.WindowState:
        """The detected window from the call log (design `napix-window`, decision 6): its remaining count seeds the
        recorder (None = unknown: the next call will tell), so a fresh pass does not spend the reserve on its first
        item."""
        with self.session_factory() as s:
            self.window = napix_window.current(s, self.settings, now)
            self.read_share(s, now)
        self.recorder.last_remaining = self.window.remaining
        return self.window

    def _claim_now(self, kinds: list[FetchKind] | None) -> Claimed | None:
        """Design `data-collection-redesign`, decision 24: before the bands, a row at a "now" priority (5 or less)
        whenever the window's remaining count is unknown or at least 1. It ignores both reserves and the discovery
        share; only the court's own limit stops it (the bands then stop the pass until the reset)."""
        rem = self.recorder.last_remaining
        if rem is not None and rem < 1:
            return None
        with self.session_factory() as s:
            item = queue.claim(s, kinds, max_priority=NOW_BULK)
            claimed = Claimed.of(item) if item is not None else None
            s.commit()
        return claimed

    def has_runnable(self, kinds: list[FetchKind] | None) -> bool:
        with self.session_factory() as s:
            return queue.has_runnable(s, kinds)

    async def probe(self, report: RunReport) -> bool:
        """One Overview call through the integration layer to read the window (decision 4): lane and user NULL, the
        pass's `job_run_id`, flushed and committed in its own session. False when the call failed."""
        assert self.hc is not None
        lane, user_id = self.recorder.lane, self.recorder.user_id
        self.recorder.lane, self.recorder.user_id = None, None
        report.probes += 1
        ok = True
        try:
            await self.hc.overview()
        except IntegrationError as exc:
            ok = False
            log.warning("napix window probe failed", error=str(exc)[:300])
        finally:
            with self.session_factory() as s:
                self.recorder.flush(s)
                s.commit()
            self.recorder.lane, self.recorder.user_id = lane, user_id
            report.calls = self.recorder.calls
        return ok

    def _blocked(
        self, report: RunReport, reason: str, *, load_only: bool, read_at: int, share: bool = False
    ) -> bool:
        """The bands block. When items ran since the window was read, it is read again (their calls are in the log):
        an unknown remaining (the reset fell due meanwhile) lets the pass go on, to probe or to claim, and so does a
        discovery share that a new window freed (`share`). Otherwise the pass stops with `resume_at`. True when the
        pass stops."""
        now = datetime.now(UTC)
        if self.window is None or report.processed > read_at:
            with self.session_factory() as s:
                self.window = napix_window.current(s, self.settings, now)
                self.read_share(s, now)
            if self.window.remaining is None:
                self.recorder.last_remaining = None
                return False
            if share and self.share_left() > 0:
                return False
        window = self.window
        report.window = window
        report.resume_at = window.resume_at(now)
        report.load_only = load_only
        report.stopped_reason = f"{reason}; {window.describe()}"
        return True

    # ------------------------------------------------------------------ the loop
    async def run(
        self, *, max_items: int | None = None, kinds: list[FetchKind] | None = None, job: str = "queue-run"
    ) -> RunReport:
        report = RunReport()
        report.job_run_id = self.start_job(job)
        status = JobStatus.SUCCEEDED
        try:
            with self.session_factory() as s:
                queue.requeue_stale(s)
                s.commit()
            report.window = self.seed_remaining()
            read_at = 0  # items processed when the window was last read
            faults = 0  # items in a row that failed with NapixUnavailable (decision 8)
            while max_items is None or report.processed < max_items:
                if (
                    self.recorder.last_remaining is None
                    and report.probes == 0
                    and self.hc is not None
                    and self.has_runnable(kinds)
                ):
                    if not await self.probe(report):
                        report.probe_failed = True
                        report.resume_at = datetime.now(UTC) + timedelta(
                            seconds=self.settings.napix_window_probe_seconds
                        )
                        report.stopped_reason = "window probe failed; probing again later"
                        break
                    report.window = self.seed_remaining()
                    read_at = report.processed
                claimed = self._claim_now(kinds)
                if claimed is None:
                    allowed, lanes = self.budget_lanes()
                    if not allowed:
                        reason = f"rate budget: {self.recorder.last_remaining} left < live reserve {self.live_reserve}"
                        if self._blocked(report, reason, load_only=False, read_at=read_at):
                            break
                        read_at = report.processed
                        continue
                    with self.session_factory() as s:
                        item = queue.claim(s, kinds, lanes=lanes)
                        share_waits = (
                            item is None
                            and lanes is not None
                            and FetchLane.LOAD in lanes
                            and queue.has_runnable(s, kinds, [FetchLane.DISCOVERY])
                        )
                        claimed = Claimed.of(item) if item is not None else None
                        s.commit()
                    if claimed is None:
                        if lanes is None or (FetchLane.LOAD in lanes and not share_waits):
                            report.stopped_reason = report.stopped_reason or "queue empty"
                            break
                        if share_waits:
                            reason = f"discovery share spent: {self.discovery_used} of {self.discovery_share}"
                        else:
                            reason = (
                                f"load waits: {self.recorder.last_remaining} left < reserve {self.reserve}"
                            )
                        if self._blocked(report, reason, load_only=True, read_at=read_at, share=share_waits):
                            break
                        read_at = report.processed
                        continue
                kind, ref, item_id = claimed.kind, claimed.ref, claimed.id
                lane = claimed.lane
                report.processed += 1
                calls_before = self.recorder.calls
                error = await self._process(
                    item_id,
                    kind,
                    ref,
                    report,
                    lane=lane,
                    list_date=claimed.list_date,
                    requested_by=claimed.requested_by,
                    priority=claimed.priority,
                )
                if lane == FetchLane.DISCOVERY:
                    self.discovery_used += self.recorder.calls - calls_before
                if error is None:
                    faults = 0
                elif isinstance(error, NapixUnavailable):
                    faults += 1
                    if faults >= self.fault_streak:
                        report.fault_pause = True
                        report.resume_at = datetime.now(UTC) + timedelta(seconds=self.fault_pause_seconds)
                        report.stopped_reason = (
                            f"gateway fault: {faults} failures in a row; pausing {self.fault_pause_seconds} s"
                        )
                        break
        except BudgetExhausted as exc:
            report.stopped_reason = str(exc)
        except Exception:  # noqa: BLE001
            status = JobStatus.FAILED
            report.stopped_reason = traceback.format_exc()[-2000:]
            raise
        finally:
            report.remaining = self.recorder.last_remaining
            if report.failed and status == JobStatus.SUCCEEDED:
                status = JobStatus.PARTIAL
            self.finish_job(report.job_run_id, report, status)
        return report

    async def _process(
        self,
        item_id: uuid.UUID,
        kind: FetchKind,
        ref: str,
        report: RunReport,
        *,
        lane: FetchLane = FetchLane.DAILY,
        list_date: date | None = None,
        requested_by: uuid.UUID | None = None,
        priority: int | None = None,
    ) -> Exception | None:
        """One item; returns the exception that failed it (None when it ended done or skipped)."""
        calls_before = self.recorder.calls
        error: Exception | None = None
        self.recorder.lane = lane.value
        self.recorder.user_id = requested_by
        with self.session_factory() as s:
            item = s.get(FetchQueueItem, item_id)
            assert item is not None
            try:
                origin = QueueOrigin(
                    lane,
                    list_date,
                    current_settings(s) if lane == FetchLane.LOAD else None,
                    requested_by=requested_by,
                    now_priority=now_priority_of(priority),
                    parent_id=item_id,  # order PDFs re-read its priority and requests when spawned
                )
                result, skipped = await self.dispatch(s, kind, ref, origin)
                queue.complete(s, item, result, skipped=skipped)
                report.done += int(not skipped)
                report.skipped += int(skipped)
                outcome = "skipped" if skipped else "done"
            except (NapixNotFound, NapixInputError) as exc:
                # the gateway answered: nothing to fetch for this ref (recorded, not retried)
                queue.complete(s, item, {"error": str(exc)[:500]}, skipped=True)
                report.skipped += 1
                outcome = f"skipped: {exc}"
            except Exception as exc:  # noqa: BLE001 — recorded on the row and retried later
                s.rollback()
                item = s.get(FetchQueueItem, item_id)
                queue.fail(s, item, f"{exc.__class__.__name__}: {exc}", family=type(exc).__name__)
                error = exc
                report.failed += 1
                outcome = f"failed: {exc.__class__.__name__}: {str(exc)[:200]}"
                log.warning("queue item failed", kind=kind.value, ref=ref, error=str(exc)[:300])
            self.recorder.flush(s)
            s.commit()
        self.recorder.lane = None
        self.recorder.user_id = None
        report.calls = self.recorder.calls
        report.items.append(
            {"kind": kind.value, "ref": ref, "outcome": outcome, "calls": self.recorder.calls - calls_before}
        )
        log.info(
            "queue item",
            kind=kind.value,
            ref=ref,
            outcome=outcome[:120],
            calls=self.recorder.calls - calls_before,
        )
        return error

    # ------------------------------------------------------------------ handlers
    async def dispatch(
        self, s: Session, kind: FetchKind, ref: str, origin: QueueOrigin | None = None
    ) -> tuple[dict[str, Any] | None, bool]:
        origin = origin or QueueOrigin()
        if kind in queue.LOCAL_KINDS:
            # decision 13: stored by the Celery task `aslms.store_search_rows`, never by the NAPIX runner
            raise RuntimeError(f"queue kind {kind.value} is not run by the queue runner")
        if kind == FetchKind.MASTERS:
            return await self._masters(s), False
        if kind == FetchKind.CAUSELIST_DAY:
            return await self._causelist_day(s, date.fromisoformat(ref), origin)
        if kind == FetchKind.CAUSELIST_RECHECK:
            return await self._causelist_recheck(s, date.fromisoformat(ref), origin)
        if kind == FetchKind.DOSSIER:
            return await self._dossier(s, ref, origin)
        if kind == FetchKind.STATUS_BATCH:
            if self.hc is None:
                raise RuntimeError("NAPIX is off: status batches cannot run")
            rep = await run_status_batch(s, self.hc, ref)
            return rep.as_dict(), rep.requested == 0
        if kind == FetchKind.ORDER_PDF:
            if self.hc is None:
                raise RuntimeError("NAPIX is off: order PDFs cannot be fetched")
            return await fetch_order_pdf(s, self.hc, self.store, ref)
        if kind == FetchKind.PARTY_SEARCH:
            if self.hc is None:
                raise RuntimeError("NAPIX is off: party-name searches cannot run")
            return await discovery.run_party_search(s, self.hc, self._court(s), ref, origin)
        raise NotImplementedError(f"queue kind {kind.value} is not handled yet")

    def _court(self, s: Session) -> Court:
        est = self.hc.est_code if self.hc else self.settings.napix_est_code
        court = s.scalar(select(Court).where(Court.est_code == est))
        if court is None:
            raise RuntimeError(f"court {est} is not seeded")
        return court

    async def _masters(self, s: Session) -> dict[str, Any]:
        if self.hc is None:
            raise RuntimeError("NAPIX is off: masters cannot be synced")
        rep = await sync_masters(s, self.hc, job_run_id=self.recorder.job_run_id)
        return rep.counts

    async def _causelist_day(
        self, s: Session, list_date: date, origin: QueueOrigin
    ) -> tuple[dict[str, Any], bool]:
        court = self._court(s)
        if origin.list_date is None:
            origin = replace(origin, list_date=list_date)
        rep = await load_causelist_day(
            s,
            self.hc,
            court,
            list_date,
            store=self.store,
            causelist_dir=self.causelist_dir,
            origin=origin,
        )
        return rep.as_dict(), rep.skipped_reason is not None

    async def _causelist_recheck(
        self, s: Session, list_date: date, origin: QueueOrigin
    ) -> tuple[dict[str, Any], bool]:
        """Show Cause List again for the date's held NAPIX lists (design court-data-freshness, decision 8); `skipped`
        when the date has no candidate list."""
        if self.hc is None:
            raise RuntimeError("NAPIX is off: cause lists cannot be rechecked")
        if origin.list_date is None:
            origin = replace(origin, list_date=list_date)
        rep = await recheck_day(
            s,
            self.hc,
            self._court(s),
            list_date,
            self.store,
            fresh_minutes=self.settings.causelist_recheck_fresh_minutes,
            origin=origin,
        )
        return rep.as_dict(), rep.candidates == 0

    async def _dossier(self, s: Session, ref: str, origin: QueueOrigin) -> tuple[dict[str, Any], bool]:
        """A dossier by CNR, or by `<est>|<case number>` through Search by Case Number; the fetch itself is
        `court_search.fetch_dossier`, shared with the user-facing court search. A provisional row whose number
        resolves to a CNR another row holds is merged into that row (design `data-load-console`, decision 13); when
        it holds portal records the pair is listed for review and the row ends `skipped`."""
        if self.hc is None:
            raise RuntimeError("NAPIX is off: dossiers cannot be fetched")
        fresh = self._fresh_since_queued(s, ref, origin)
        if fresh is not None:
            return fresh, False
        court = self._court(s)
        merged: dict[str, Any] | None = None
        if "|" in ref:
            est, case_no = ref.split("|", 1)
            if est != court.est_code:
                court = s.scalar(select(Court).where(Court.est_code == est)) or court
            exact = s.scalar(
                select(Case)
                .where(
                    Case.court_id == court.id,
                    Case.case_no_text == case_no,
                    Case.cnr.isnot(None),
                    Case.merged_into_case_id.is_(None),
                )
                .order_by(Case.created_at)
                .limit(1)
            )
            cnr = (
                exact.cnr if exact is not None else await court_search.resolve_cnr(s, self.hc, court, case_no)
            )
            if cnr is None:
                return {"error": "not found by case number"}, True
            provisional = find_case(s, court, cnr=None, case_no=case_no)
            holder = s.scalar(select(Case).where(Case.cnr == cnr))
            if provisional is not None and holder is not None and holder.id != provisional.id:
                out = case_dedupe.merge_provisional(s, provisional, holder)
                if isinstance(out, case_dedupe.NeedsReview):
                    return {
                        "cnr": cnr,
                        "needs_review": True,
                        "provisional": provisional.ref_no,
                        "holder": holder.ref_no,
                        "reason": out.reason,
                    }, True
                merged = {"merged": provisional.ref_no, "into": holder.ref_no}
            elif provisional is not None and holder is None:
                case_dedupe.adopt(s, provisional, cnr)
            elif holder is None:
                get_or_create_case(s, court, cnr=cnr, case_no=case_no, source=FirstSeenSource.SEARCH)
        else:
            cnr = ref.upper()
        fetched = await court_search.fetch_dossier(
            s, self.hc, court, cnr, source=FirstSeenSource.SEARCH, origin=origin
        )
        result: dict[str, Any] = {
            "cnr": cnr,
            "changed": fetched.report.changed,
            "snapshot_new": fetched.report.snapshot_new,
            "counts": fetched.report.counts,
            "order_pdfs_queued": fetched.order_pdfs_queued,
        }
        if merged:
            result.update(merged)
        return result, False

    def _fresh_since_queued(self, s: Session, ref: str, origin: QueueOrigin) -> dict[str, Any] | None:
        """Design `rolling-case-refresh`, decision 6: a claimed `dossier` row at a routine priority (56 to 59) whose
        case's last full record is later than the row's `created_at` (the portal's own court fetch refreshed it after
        queueing) needs no call: `{"cnr", "fresh_since_queued": True}`. A row raised to 50 or better is fetched."""
        if origin.parent_id is None or "|" in ref:
            return None
        item = s.get(FetchQueueItem, origin.parent_id)
        if item is None or int(item.priority) not in queue.ROUTINE_PRIORITIES:
            return None
        cnr = ref.upper()
        refreshed = s.scalar(select(Case.last_full_refresh_at).where(Case.cnr == cnr))
        if refreshed is not None and item.created_at is not None and refreshed > item.created_at:
            return {"cnr": cnr, "fresh_since_queued": True}
        return None


# ------------------------------------------------------------------------------------------------ helpers

# design rolling-case-refresh, decision 16: the kinds each worker slot claims (None = every NAPIX kind); the second
# slot never takes a Current Status batch
SLOT_KINDS: dict[str, list[FetchKind] | None] = {
    "main": None,
    "second": [k for k in FetchKind if k != FetchKind.STATUS_BATCH and k not in queue.LOCAL_KINDS],
}


def slot_job(slot: str) -> str:
    """The `job_runs.job` of a slot's passes: `queue-run` or `queue-run-second` (decision 18)."""
    if slot not in SLOT_JOBS:
        raise ValueError(f"unknown worker slot {slot!r}")
    return SLOT_JOBS[slot]


def enqueue_days(
    s: Session,
    start: date,
    end: date,
    *,
    priority: int | None = None,
    requeue: bool = False,
    lane: FetchLane | None = None,
) -> int:
    """One `causelist_day` row per calendar day (the court simply has no list on holidays). Without a lane, days
    from yesterday on belong to the daily cycle (priority 20) and older days to the load (its policy priority, with
    `list_date` = the day). The console's start goes through `services/data_load.py::start`."""
    today = today_ist()
    settings = current_settings(s)
    n = 0
    d = start
    while d <= end:
        day_lane = lane or (FetchLane.DAILY if (today - d).days <= 1 else FetchLane.LOAD)
        if priority is not None:
            pr = priority
        elif day_lane == FetchLane.LOAD:
            pr = load_priority(settings, FetchKind.CAUSELIST_DAY, d)
        else:
            pr = queue.PRIORITY["list_today"]
        if queue.enqueue(
            s, FetchKind.CAUSELIST_DAY, d.isoformat(), pr, requeue=requeue, lane=day_lane, list_date=d
        ):
            n += 1
        d += timedelta(days=1)
    return n


def open_hc(settings: Settings | None = None) -> tuple[NapixClient, NapixHighCourt]:
    s = settings or get_settings()
    client = NapixClient.from_settings(s)
    return client, NapixHighCourt(client, s.napix_est_code, s.napix_state_code)


def claim_kinds(settings: Settings, kinds: list[FetchKind] | None) -> list[FetchKind] | None:
    """The kinds a pass can claim: those asked (every NAPIX kind when None) with the gateway configured; with it off,
    only cause-list days (read from the stored PDFs). The worker's wake check asks for these only (row 174 review), so
    a "now" row the pass could not claim never wakes it."""
    if settings.napix_configured:
        return kinds
    if kinds is None or FetchKind.CAUSELIST_DAY in kinds:
        # a slot's list of kinds narrows to what can run without the gateway (the second slot never claims a
        # dossier it could only fail)
        return [FetchKind.CAUSELIST_DAY]
    return kinds


async def run_queue_once(
    session_factory: sessionmaker[Session],
    *,
    max_items: int | None,
    kinds: list[FetchKind] | None,
    settings: Settings | None = None,
    job: str = "queue-run",
) -> RunReport:
    s = settings or get_settings()
    if s.napix_configured:
        client, hc = open_hc(s)
        recorder = NapixRecorder()
        client.on_call = recorder.on_call
        async with client:
            runner = QueueRunner(session_factory, hc, settings=s, recorder=recorder)
            return await runner.run(max_items=max_items, kinds=kinds, job=job)
    runner = QueueRunner(session_factory, None, settings=s)
    return await runner.run(max_items=max_items, kinds=claim_kinds(s, kinds), job=job)


def run_queue(session_factory: sessionmaker[Session], **kw: Any) -> RunReport:
    return asyncio.run(run_queue_once(session_factory, **kw))
