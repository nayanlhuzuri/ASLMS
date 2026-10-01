"""The queue runner: pulls `fetch_queue` rows in priority order and dispatches them to the pipeline stages,
spending the gateway budget (`NAPIX_RATE_RESERVE` calls are kept for the daily cycle). One `job_runs` row per
invocation; every NAPIX attempt is logged and every response kept by the recorder. Survives restarts: a row
is only `done` when its transaction committed."""

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
from aslms.domain.courts import CaseType, Court
from aslms.domain.ops import FetchKind, FetchQueueItem, JobRun, JobStatus
from aslms.integration.napix.client import NapixClient
from aslms.integration.napix.hc import NapixHighCourt
from aslms.services import queue
from aslms.services.cases import apply_dossier, get_or_create_case
from aslms.services.causelists import load_causelist_day
from aslms.services.masters import sync_masters
from aslms.services.napix_store import NapixRecorder
from aslms.services.napix_values import as_int, as_text
from aslms.services.orders import enqueue_order_pdfs, fetch_order_pdf
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

    def budget_ok(self) -> bool:
        rem = self.recorder.last_remaining
        return rem is None or rem >= self.reserve

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
            while max_items is None or report.processed < max_items:
                if not self.budget_ok():
                    report.stopped_reason = (
                        f"rate budget: {self.recorder.last_remaining} remaining < reserve {self.reserve}"
                    )
                    break
                with self.session_factory() as s:
                    item = queue.claim(s, kinds)
                    if item is None:
                        s.commit()
                        report.stopped_reason = report.stopped_reason or "queue empty"
                        break
                    kind, ref, item_id = item.kind, item.ref, item.id
                    s.commit()
                report.processed += 1
                await self._process(item_id, kind, ref, report)
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

    async def _process(self, item_id: uuid.UUID, kind: FetchKind, ref: str, report: RunReport) -> None:
        calls_before = self.recorder.calls
        with self.session_factory() as s:
            item = s.get(FetchQueueItem, item_id)
            assert item is not None
            try:
                result, skipped = await self.dispatch(s, kind, ref)
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
    async def dispatch(self, s: Session, kind: FetchKind, ref: str) -> tuple[dict[str, Any] | None, bool]:
        if kind == FetchKind.MASTERS:
            return await self._masters(s), False
        if kind == FetchKind.CAUSELIST_DAY:
            return await self._causelist_day(s, date.fromisoformat(ref))
        if kind == FetchKind.DOSSIER:
            return await self._dossier(s, ref)
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

    async def _causelist_day(self, s: Session, list_date: date) -> tuple[dict[str, Any], bool]:
        court = self._court(s)
        today = date.today()
        priority = (
            queue.PRIORITY["dossier_new"]
            if (today - list_date).days <= 2
            else queue.PRIORITY["dossier_new"] + 5
        )
        rep = await load_causelist_day(
            s,
            self.hc,
            court,
            list_date,
            store=self.store,
            causelist_dir=self.causelist_dir,
            dossier_priority=priority,
        )
        return rep.as_dict(), rep.skipped_reason is not None

    async def _dossier(self, s: Session, ref: str) -> tuple[dict[str, Any], bool]:
        if self.hc is None:
            raise RuntimeError("NAPIX is off: dossiers cannot be fetched")
        court = self._court(s)
        cnr: str | None
        case: Case | None
        if "|" in ref:
            est, case_no = ref.split("|", 1)
            if est != court.est_code:
                court = s.scalar(select(Court).where(Court.est_code == est)) or court
            case = s.scalar(
                select(Case)
                .where(Case.court_id == court.id, Case.case_no_text == case_no)
                .order_by(Case.cnr.desc().nulls_last())
                .limit(1)
            )
            cnr = case.cnr if case and case.cnr else await self._resolve_cnr(court, case_no, s)
            if cnr is None:
                return {"error": "not found by case number"}, True
            if case is None:
                case, _ = get_or_create_case(
                    s, court, cnr=cnr, case_no=case_no, source=FirstSeenSource.SEARCH
                )
            elif case.cnr is None:
                case.cnr = cnr
        else:
            cnr = ref.upper()
            case = s.scalar(select(Case).where(Case.cnr == cnr))
            if case is None:
                case, _ = get_or_create_case(s, court, cnr=cnr, case_no=None, source=FirstSeenSource.SEARCH)
        data = await self.hc.case_by_cnr(cnr)
        if not data or not as_text(data.get("cino")):
            return {"error": "empty dossier"}, True
        rep = apply_dossier(s, case, data)
        queued = enqueue_order_pdfs(s, case)
        return {
            "cnr": cnr,
            "changed": rep.changed,
            "snapshot_new": rep.snapshot_new,
            "counts": rep.counts,
            "order_pdfs_queued": queued,
        }, False

    async def _resolve_cnr(self, court: Court, case_no: str, s: Session) -> str | None:
        """`WP(C)/4326/2025` → Search by Case Number with the type code from the case-type master."""
        parts = case_no.rsplit("/", 2)
        if len(parts) != 3:
            return None
        short, no, year = parts[0].strip(), as_int(parts[1]), as_int(parts[2])
        ct = s.scalar(select(CaseType).where(CaseType.court_id == court.id, CaseType.short_name == short))
        if ct is None or no is None or year is None:
            return None
        rows = await self.hc.search_case_number(ct.case_type_code, no, year)
        for row in rows:
            cino = as_text(row.get("cino"), 16)
            if cino and as_int(row.get("reg_no")) == no and as_int(row.get("reg_year")) == year:
                return cino.upper()
        return None


# ------------------------------------------------------------------------------------------------ helpers


def enqueue_days(
    s: Session, start: date, end: date, *, priority: int | None = None, requeue: bool = False
) -> int:
    """One `causelist_day` row per calendar day (the court simply has no list on holidays)."""
    today = date.today()
    n = 0
    d = start
    while d <= end:
        pr = (
            priority
            if priority is not None
            else (queue.PRIORITY["list_today"] if (today - d).days <= 1 else queue.PRIORITY["list_history"])
        )
        if queue.enqueue(s, FetchKind.CAUSELIST_DAY, d.isoformat(), pr, requeue=requeue):
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
