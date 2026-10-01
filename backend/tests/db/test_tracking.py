"""Stages 4–5 against the test database: Current Status batches (a changed next date updates the case, writes
next_dates and an event, and queues a dossier re-fetch), order PDFs (stored, or not available), and what the
schedules enqueue."""

from __future__ import annotations

import asyncio
from datetime import date

import httpx
import sqlalchemy as sa

from aslms.domain.alerts import NextDate
from aslms.domain.cases import Case, FirstSeenSource
from aslms.domain.courts import Court
from aslms.domain.documents import Document, Order
from aslms.domain.events import Event
from aslms.domain.ops import FetchKind, FetchQueueItem, FetchStatus
from aslms.services import queue, schedules
from aslms.services.cases import apply_dossier, get_or_create_case
from aslms.services.napix_store import NapixRecorder
from aslms.services.orders import enqueue_order_pdfs
from aslms.services.runner import QueueRunner
from aslms.services.storage import LocalStore
from aslms.services.tracking import enqueue_status_batches
from tests.db.conftest import SAMPLES, sample

ORDER_PDF = (SAMPLES / "order_pending.pdf").read_bytes()
CNR = "GAHC010129772026"


def with_orders(gw, base):
    import base64
    import json

    def handle(path, q, request: httpx.Request):
        if path == "hc-order-api/order":
            plain = gw.crypto.decrypt(q["request_str"])
            params = dict(kv.split("=", 1) for kv in plain.split("|") if "=" in kv)
            if params["order_no"] == "1":
                return gw.envelope_text(json.dumps(base64.b64encode(ORDER_PDF).decode()))
            return gw.encrypted_status(628)
        return base(path, q, request)

    return handle


def seeded_case(Session):
    with Session() as s:
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        case, _ = get_or_create_case(s, court, cnr=CNR, case_no=None, source=FirstSeenSource.SEARCH)
        apply_dossier(s, case, sample("cnr_pending.json"))
        s.commit()
        return case.id


def runner_for(Session, client, hc, tmp_path):
    rec = NapixRecorder()
    client.on_call = rec.on_call
    store = LocalStore(tmp_path / "store")
    return QueueRunner(Session, hc, store=store, causelist_dir=tmp_path / "lists", recorder=rec, reserve=0)


def run(client, runner, **kw):
    async def go():
        async with client:
            return await runner.run(**kw)

    return asyncio.run(go())


def test_status_batch_updates_and_requeues(clean_db, napix, tmp_path):
    gw, client, hc = napix
    Session = clean_db
    case_id = seeded_case(Session)
    with Session() as s:
        assert enqueue_status_batches(s, date(2026, 10, 1)) == 1
        enqueue_status_batches(s, date(2026, 10, 1))  # idempotent: still one row
        assert s.scalar(sa.select(sa.func.count()).select_from(FetchQueueItem)) == 1
        s.commit()
    runner = runner_for(Session, client, hc, tmp_path)
    rep = run(client, runner, kinds=[FetchKind.STATUS_BATCH])
    assert rep.done == 1 and rep.failed == 0, rep.items
    assert rep.items[0]["outcome"] == "done"
    with Session() as s:
        case = s.get(Case, case_id)
        assert (
            case.next_hearing_date == date(2026, 10, 20)
            and case.next_purpose == "HEARING"
            and case.dossier_stale
        )
        assert case.last_status_refresh_at is not None
        nd = s.scalar(sa.select(NextDate).where(NextDate.case_id == case_id))
        assert nd.next_date == date(2026, 10, 20) and nd.source.value == "current_status"
        ev = s.scalars(
            sa.select(Event).where(Event.case_id == case_id, Event.type == "next_date_changed")
        ).all()
        assert len(ev) == 1 and ev[0].payload["next_hearing_date"] == [None, "2026-10-20"]
        item = s.scalar(
            sa.select(FetchQueueItem).where(
                FetchQueueItem.kind == FetchKind.DOSSIER, FetchQueueItem.ref == CNR
            )
        )
        assert item.status == FetchStatus.PENDING and item.priority == queue.PRIORITY["dossier_refetch"]
        batch = s.scalar(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.STATUS_BATCH))
        assert batch.result["changed"] == 1 and batch.result["answered"] == 1
    # the same status again: no new rows
    with Session() as s:
        queue.enqueue(s, FetchKind.STATUS_BATCH, "2026-10-01:0", 30, requeue=True)
        s.commit()
    rep = run(client, runner, kinds=[FetchKind.STATUS_BATCH])
    assert rep.done == 1
    with Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(NextDate)) == 1
        assert (
            s.scalar(sa.select(sa.func.count()).select_from(Event).where(Event.type == "next_date_changed"))
            == 1
        )
        assert (
            s.scalar(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.STATUS_BATCH)).result[
                "changed"
            ]
            == 0
        )


def test_order_pdfs_stored_or_not_available(clean_db, napix, tmp_path):
    gw, client, hc = napix
    gw.responses = [with_orders(gw, gw.responses[0])] * 1000
    Session = clean_db
    case_id = seeded_case(Session)
    with Session() as s:
        case = s.get(Case, case_id)
        assert enqueue_order_pdfs(s, case) == 3
        enqueue_order_pdfs(s, case)  # idempotent
        assert s.scalar(sa.select(sa.func.count()).select_from(FetchQueueItem)) == 3
        s.commit()
    runner = runner_for(Session, client, hc, tmp_path)
    rep = run(client, runner, kinds=[FetchKind.ORDER_PDF])
    assert rep.done == 1 and rep.skipped == 2 and rep.failed == 0, rep.items
    with Session() as s:
        orders = s.scalars(sa.select(Order).where(Order.case_id == case_id).order_by(Order.order_no)).all()
        assert [o.download_status.value for o in orders] == ["stored", "not_available", "not_available"]
        doc = s.get(Document, orders[0].document_id)
        assert doc.kind.value == "order" and doc.doc_type.value == "order" and doc.case_id == case_id
        assert doc.sourcetrace_status.value == "pending" and doc.text_status.value == "pending"
        assert (tmp_path / "store" / doc.storage_key).read_bytes() == ORDER_PDF
        assert (
            s.scalar(sa.select(sa.func.count()).select_from(Event).where(Event.type == "order_stored")) == 1
        )
        assert s.scalar(sa.select(sa.func.count()).select_from(Event).where(Event.type == "order_found")) == 3
        # the weekly sweep retries the two not-available PDFs and re-fetches the pending dossier
        out = schedules.enqueue_weekly(s)
        assert out == {"dossiers": 1, "orders_retried": 2, "orders_queued": 2}
        s.rollback()


def test_daily_schedule_enqueues(clean_db):
    Session = clean_db
    with Session() as s:
        assert schedules.enqueue_daily_lists(s, date(2026, 10, 1)) == 3
        assert schedules.enqueue_masters(s)
        refs = sorted(
            r for (r,) in s.execute(sa.text("select ref from fetch_queue where kind = 'causelist_day'"))
        )
        assert refs == ["2026-09-30", "2026-10-01", "2026-10-02"]
        s.rollback()
