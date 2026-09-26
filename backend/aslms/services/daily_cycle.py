"""The daily data cycle (plan §6.1), run the evening before and again in the morning for a cause-list date:

  1. NAPIX (when configured): Cause List Bench → Cause List Details per bench → rows (if the API returns rows)
     and the Show Cause List PDF (parsed as a cross-check).
  2. Cause-list PDFs from the local folder and, when its URL template is configured, the GHC website.
  3. Reconcile NAPIX rows against PDF rows (per CNR).
  4. First sight: fetch the full CNR record for new cases (NAPIX).
  5. Download new orders of tracked cases and read next dates (NAPIX).
  6. Raise alerts and queue notifications.

Each list is ingested in its own transaction, so one bad PDF never loses a day. Steps that need NAPIX are
skipped (and reported in the job counters) until the credentials are configured."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from aslms.core.errors import IntegrationError
from aslms.core.logging import get_logger
from aslms.domain.causelists import CauseListSource, EntrySource, ListType
from aslms.domain.ops import FailureKind, JobKind
from aslms.integration.factory import napix_source
from aslms.integration.ghc.website import LocalDirSource, WebsiteSource
from aslms.services import alerts, causelists, ops, orders, tracking
from aslms.services import cases as case_svc
from aslms.services.causelists import IngestStats

log = get_logger(__name__)
SessionFactory = Callable[[], AbstractContextManager[Session]]


def _napix_lists(
    session_factory: SessionFactory, list_date: date, run_id, counters: dict[str, Any]
) -> IngestStats:
    total = IngestStats()
    built = napix_source(run_id)
    if built is None:
        counters["napix"] = "not configured"
        return total
    hc, recorder = built
    try:
        benches = asyncio.run(hc.causelist_benches(list_date))
    except IntegrationError as e:
        with session_factory() as s:
            ops.record_failure(s, FailureKind.NAPIX, f"causelist_bench:{list_date}", str(e))
            recorder.flush(s)
        counters["failures"] = counters.get("failures", 0) + 1
        return total
    counters["napix_benches"] = len(benches)
    for b in benches:
        try:
            refs = asyncio.run(hc.causelists_for_bench(list_date, b.bench_id))
            for ref in refs:
                rows = asyncio.run(hc.causelist_rows(ref))
                pdf = asyncio.run(hc.causelist_pdf(ref)) if ref.causelist_id else None
                with session_factory() as s:
                    court = case_svc.default_court(s)
                    lt = (
                        ListType(ref.list_type)
                        if ref.list_type in ListType._value2member_map_
                        else ListType.OTHER
                    )
                    if rows:
                        cl = causelists.upsert_causelist(
                            s,
                            court=court,
                            list_date=list_date,
                            list_type=lt,
                            source=CauseListSource.NAPIX,
                            bench_id=ref.bench_id,
                            napix_causelist_id=ref.causelist_id or "details",
                            label=ref.label or b.judge_names,
                            raw=ref.raw if not ref.raw.get("rows") else {"bench": b.raw},
                        )
                        total.merge(causelists.ingest_rows(s, cl, rows, EntrySource.NAPIX_DETAILS))
                    if pdf:
                        st, _ = causelists.ingest_pdf(
                            s,
                            pdf,
                            source=CauseListSource.NAPIX,
                            filename=f"napix_{list_date}_{ref.bench_id}_{ref.causelist_id}.pdf",
                            court=court,
                            list_date=list_date,
                        )
                        total.merge(st)
                    recorder.flush(s)
        except IntegrationError as e:
            with session_factory() as s:
                ops.record_failure(s, FailureKind.NAPIX, f"causelist:{list_date}:{b.bench_id}", str(e))
                recorder.flush(s)
            counters["failures"] = counters.get("failures", 0) + 1
    return total


def _pdf_lists(session_factory: SessionFactory, list_date: date, counters: dict[str, Any]) -> IngestStats:
    total = IngestStats()
    for src, kind in (
        (LocalDirSource(), CauseListSource.LOCAL_DIR),
        (WebsiteSource(), CauseListSource.GHC_WEBSITE),
    ):
        for ref in src.list(list_date):
            try:
                data = src.fetch(ref)
            except IntegrationError as e:
                if kind == CauseListSource.GHC_WEBSITE and "not published" in str(e):
                    continue
                with session_factory() as s:
                    ops.record_failure(s, FailureKind.GHC_PDF, f"{kind.value}:{ref.name}", str(e))
                counters["failures"] = counters.get("failures", 0) + 1
                continue
            try:
                with session_factory() as s:
                    st, _ = causelists.ingest_pdf(
                        s, data, source=kind, filename=ref.name, list_date=list_date
                    )
                    ops.resolve_failure(s, FailureKind.GHC_PDF, f"{kind.value}:{ref.name}")
                total.merge(st)
            except Exception as e:  # noqa: BLE001 — one unreadable PDF must not stop the cycle
                log.exception("cause list ingestion failed", file=ref.name)
                with session_factory() as s:
                    ops.record_failure(
                        s, FailureKind.GHC_PDF, f"{kind.value}:{ref.name}", f"{type(e).__name__}: {e}"
                    )
                counters["failures"] = counters.get("failures", 0) + 1
    return total


def run_daily_cycle(
    session_factory: SessionFactory,
    list_date: date,
    *,
    fetch_cases: bool = True,
    download_orders: bool = True,
    raise_alerts: bool = True,
) -> dict[str, Any]:
    with ops.job(session_factory, JobKind.DAILY_CYCLE, list_date) as (run_id, counters):
        stats = _napix_lists(session_factory, list_date, run_id, counters)
        stats.merge(_pdf_lists(session_factory, list_date, counters))
        counters["ingest"] = stats.as_dict()
        with session_factory() as s:
            counters["reconciliation"] = causelists.reconcile(s, list_date)

        built = napix_source(run_id) if (fetch_cases or download_orders) else None
        if built:
            hc, recorder = built
            if fetch_cases:
                with session_factory() as s:
                    counters["first_sight"] = tracking.first_sight(s, hc)
                    recorder.flush(s)
            if download_orders:
                with session_factory() as s:
                    counters["orders"] = orders.download_pending(s, hc)
                    recorder.flush(s)
        elif fetch_cases or download_orders:
            counters["first_sight"] = counters["orders"] = "skipped: NAPIX not configured"

        if raise_alerts:
            with session_factory() as s:
                counters["alerts"] = alerts.generate(s)
            with session_factory() as s:
                counters["delivery"] = alerts.deliver_pending(s)
        log.info(
            "daily cycle finished",
            list_date=str(list_date),
            **{k: v for k, v in counters.items() if k != "ingest"},
        )
        return dict(counters)


def run_status_refresh(session_factory: SessionFactory) -> dict[str, Any]:
    with ops.job(session_factory, JobKind.STATUS_REFRESH) as (run_id, counters):
        built = napix_source(run_id)
        if built is None:
            counters["skipped"] = "NAPIX not configured"
            return dict(counters)
        hc, recorder = built
        with session_factory() as s:
            counters.update(tracking.status_refresh(s, hc))
            recorder.flush(s)
        return dict(counters)


def run_full_refresh(session_factory: SessionFactory) -> dict[str, Any]:
    with ops.job(session_factory, JobKind.FULL_REFRESH) as (run_id, counters):
        built = napix_source(run_id)
        if built is None:
            counters["skipped"] = "NAPIX not configured"
            return dict(counters)
        hc, recorder = built
        with session_factory() as s:
            counters.update(tracking.full_refresh(s, hc))
            recorder.flush(s)
        with session_factory() as s:
            counters["orders"] = orders.download_pending(s, hc)
            recorder.flush(s)
        return dict(counters)
