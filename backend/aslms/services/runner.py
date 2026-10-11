"""The queue runner: pulls `fetch_queue` rows in priority order and dispatches them to the pipeline stages,
spending the gateway budget by bands (design `data-load-console`, decision 4): any lane while the hour's remaining
quota is at least `NAPIX_RATE_RESERVE`; only the daily and request lanes between `NAPIX_LIVE_RESERVE` and it; nothing
below `NAPIX_LIVE_RESERVE` (the worker sleeps to the next clock hour). Each pass seeds the remaining count from the
latest `napix_call_log.rate_limit_remaining` of the current hour. One `job_runs` row per invocation; every NAPIX
attempt is logged with the lane of its item and every response kept by the recorder. Work an item spawns inherits
its lane and `list_date` (`QueueOrigin`). Survives restarts: a row is only `done` when its transaction committed."""

from __future__ import annotations

import asyncio
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from aslms.core.config import Settings, get_settings
from aslms.core.errors import IntegrationError, NapixInputError, NapixNotFound
from aslms.domain.cases import Case, FirstSeenSource
from aslms.domain.courts import Court
from aslms.domain.ops import FetchKind, FetchLane, FetchQueueItem, JobRun, JobStatus
from aslms.integration.napix.client import NapixClient
from aslms.integration.napix.hc import NapixHighCourt
from aslms.services import case_dedupe, court_search, queue
from aslms.services.cases import find_case, get_or_create_case
from aslms.services.causelists import load_causelist_day
from aslms.services.load_policy import QueueOrigin, current_settings, load_priority
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

    # ------------------------------------------------------------------ lifecycle
    def start_job(self, job: str) -> uuid.UUID:
        with self.session_factory() as s:
            run = JobRun(job=job, run_date=date.today())
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
                    "stopped": report.stopped_reason,
                }
            self.recorder.flush(s)
            s.commit()

    def budget_lanes(self) -> tuple[bool, list[FetchLane] | None]:
        """Decision 4: (may claim, lanes). Any lane at or above the rate reserve; the daily and request lanes
        between the live reserve and it; nothing below the live reserve."""
        rem = self.recorder.last_remaining
        if rem is None or rem >= self.reserve:
            return True, None
        if rem >= self.live_reserve:
            return True, [FetchLane.REQUEST, FetchLane.DAILY]
        return False, None

    def budget_ok(self) -> bool:
        return self.budget_lanes()[0]

    def seed_remaining(self) -> None:
        """The latest remaining count of the current clock hour from the call log (None in a fresh hour), so a
        fresh pass does not spend the reserve on its first item."""
        with self.session_factory() as s:
            self.recorder.last_remaining = court_search.latest_remaining_this_hour(s)

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
            self.seed_remaining()
            while max_items is None or report.processed < max_items:
                allowed, lanes = self.budget_lanes()
                if not allowed:
                    report.stopped_reason = (
                        f"rate budget: {self.recorder.last_remaining} remaining < live reserve "
                        f"{self.live_reserve}"
                    )
                    break
                with self.session_factory() as s:
                    item = queue.claim(s, kinds, lanes=lanes)
                    if item is None:
                        s.commit()
                        report.stopped_reason = report.stopped_reason or (
                            f"load waits: {self.recorder.last_remaining} remaining < reserve {self.reserve}"
                            if lanes is not None
                            else "queue empty"
                        )
                        break
                    kind, ref, item_id = item.kind, item.ref, item.id
                    lane, list_date = FetchLane(item.lane), item.list_date
                    s.commit()
                report.processed += 1
                await self._process(item_id, kind, ref, report, lane=lane, list_date=list_date)
        except BudgetExhausted as exc:
            report.stopped_reason = str(exc)
        except Exception:  # noqa: BLE001
            status = JobStatus.FAILED
            report.stopped_reason = traceback.format_exc()[-2000:]
            raise
        finally:
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
    ) -> None:
        calls_before = self.recorder.calls
        self.recorder.lane = lane.value
        with self.session_factory() as s:
            item = s.get(FetchQueueItem, item_id)
            assert item is not None
            try:
                origin = QueueOrigin(lane, list_date, current_settings(s) if lane == FetchLane.LOAD else None)
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
                queue.fail(
                    s,
                    item,
                    f"{exc.__class__.__name__}: {exc}",
                    retry_in=timedelta(minutes=10) if isinstance(exc, IntegrationError) else None,
                )
                report.failed += 1
                outcome = f"failed: {exc.__class__.__name__}: {str(exc)[:200]}"
                log.warning("queue item failed", kind=kind.value, ref=ref, error=str(exc)[:300])
            self.recorder.flush(s)
            s.commit()
        self.recorder.lane = None
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

    # ------------------------------------------------------------------ handlers
    async def dispatch(
        self, s: Session, kind: FetchKind, ref: str, origin: QueueOrigin | None = None
    ) -> tuple[dict[str, Any] | None, bool]:
        origin = origin or QueueOrigin()
        if kind == FetchKind.MASTERS:
            return await self._masters(s), False
        if kind == FetchKind.CAUSELIST_DAY:
            return await self._causelist_day(s, date.fromisoformat(ref), origin)
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
            origin = QueueOrigin(origin.lane, list_date, origin.settings)
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

    async def _dossier(self, s: Session, ref: str, origin: QueueOrigin) -> tuple[dict[str, Any], bool]:
        """A dossier by CNR, or by `<est>|<case number>` through Search by Case Number; the fetch itself is
        `court_search.fetch_dossier`, shared with the user-facing court search. A provisional row whose number
        resolves to a CNR another row holds is merged into that row (design `data-load-console`, decision 13); when
        it holds portal records the pair is listed for review and the row ends `skipped`."""
        if self.hc is None:
            raise RuntimeError("NAPIX is off: dossiers cannot be fetched")
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


# ------------------------------------------------------------------------------------------------ helpers


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
    today = date.today()
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


async def run_queue_once(
    session_factory: sessionmaker[Session],
    *,
    max_items: int | None,
    kinds: list[FetchKind] | None,
    settings: Settings | None = None,
) -> RunReport:
    s = settings or get_settings()
    if s.napix_configured:
        client, hc = open_hc(s)
        recorder = NapixRecorder()
        client.on_call = recorder.on_call
        async with client:
            runner = QueueRunner(session_factory, hc, settings=s, recorder=recorder)
            return await runner.run(max_items=max_items, kinds=kinds)
    runner = QueueRunner(session_factory, None, settings=s)
    return await runner.run(max_items=max_items, kinds=kinds or [FetchKind.CAUSELIST_DAY])


def run_queue(session_factory: sessionmaker[Session], **kw: Any) -> RunReport:
    return asyncio.run(run_queue_once(session_factory, **kw))
