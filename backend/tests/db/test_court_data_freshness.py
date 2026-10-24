"""Design `court-data-freshness`, "Tests / Database": the monthly refresh of disposed cases, a restored case, the evening
recheck of held cause lists (unchanged, fresh, re-issued, same entries, unparsable, 628), how cases, recommendations,
alerts and the timeline react to a corrected list, the readers, the date lock, the schedules and the operator's
recheck, and the call-log purge. The scripted gateway answers (`NAPIX_ENABLED` is never set); the re-issue tests swap
the parser for the stored-form rows they need (deviation recorded in the design note)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import threading
import time
import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from aslms.core.clock import IST, ist_midnight, today_ist
from aslms.core.config import Settings
from aslms.domain.alerts import Alert, AlertKind, AlertStatus, Notification
from aslms.domain.cases import Case, CaseStatus
from aslms.domain.causelists import (
    Causelist,
    CauselistEntry,
    FetchStatus,
    ListSource,
    ListType,
)
from aslms.domain.documents import Document
from aslms.domain.events import AuditLog, Event
from aslms.domain.ops import (
    FetchKind,
    FetchLane,
    FetchQueueItem,
    JobRun,
    NapixCallLog,
    NapixResponse,
    SourceFailure,
)
from aslms.domain.ownership import Recommendation, RecommendationOrigin, RecommendationStatus, ScoreBand
from aslms.domain.reference import EventType
from aslms.integration.napix.client import NapixClient
from aslms.integration.napix.crypto import NapixCrypto
from aslms.integration.napix.hc import NapixHighCourt
from aslms.parsing.causelist_pdf import Entry, ParsedCauseList
from aslms.services import (
    access,
    alert_rules,
    alerts,
    case_detail,
    causelist_view,
    napix_admin,
    napix_window,
    retention,
    schedules,
    system_health,
    tracking,
)
from aslms.services import causelists as cl_store
from aslms.services import ownership as own
from aslms.services.audit import Actor
from aslms.services.cases import apply_dossier
from aslms.services.load_policy import QueueOrigin
from aslms.services.matching import normalise_counsel_code
from aslms.services.napix_store import NapixRecorder
from aslms.services.storage import LocalStore
from aslms.services.visibility import codes_condition
from aslms.services.workflow_common import primary_owner
from tests.db.conftest import FIXTURES, TEST_URL, router, sample
from tests.db.world import make_case
from tests.unit.conftest import KEY, Gateway

SHOW = "hc-show-causelist-api/showcauselist"
BENCH = "hc-causelist-bench-api/causelistbench"
DETAILS = "hc-causelist-details-api/causelistdetails"


def pdf_bytes(tag: str) -> bytes:
    return b"%PDF-1.4\n% court-data-freshness " + tag.encode() + b"\n%%EOF\n"


def settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def court_of(s):
    from aslms.domain.courts import Court

    return s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))


# ================================================================================================ disposed refresh

NOW = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)  # 11:30 IST
TODAY = today_ist(NOW)


def disposed(
    s, *, refreshed_days: int | None, disposed_days: int | None, closed_days: int | None = None, **kw
):
    case = make_case(s, status=CaseStatus.DISPOSED, **kw)
    case.last_full_refresh_at = NOW - timedelta(days=refreshed_days) if refreshed_days is not None else None
    case.disposal_date = TODAY - timedelta(days=disposed_days) if disposed_days is not None else None
    case.closed_at = (
        NOW - timedelta(days=closed_days) if closed_days is not None else NOW - timedelta(days=500)
    )
    s.flush()
    return case


def test_disposed_refresh_selection(clean_db):
    with clean_db() as s:
        due = disposed(s, refreshed_days=29, disposed_days=100)
        disposed(s, refreshed_days=10, disposed_days=100)  # refreshed recently
        disposed(s, refreshed_days=40, disposed_days=400)  # disposed too long ago
        disposed(s, refreshed_days=None, disposed_days=100)  # never fully fetched: the Sunday sweep's
        merged_into = make_case(s)
        merged = disposed(s, refreshed_days=40, disposed_days=100)
        merged.merged_into_case_id = merged_into.id
        pending = make_case(s)
        pending.last_full_refresh_at = NOW - timedelta(days=40)
        s.flush()
        refs = tracking.disposed_refresh_refs(s, TODAY, keep_days=365, every_days=28, now=NOW)
        assert refs == [due.cnr]
        out = tracking.enqueue_disposed_refresh(s, TODAY, settings(), now=NOW)
        assert out == {"eligible": 2, "due": 1, "cap": 1, "queued": 1}
        row = s.scalar(
            sa.select(FetchQueueItem).where(
                FetchQueueItem.kind == FetchKind.DOSSIER, FetchQueueItem.ref == due.cnr
            )
        )
        assert row.priority == 55 and FetchLane(row.lane) == FetchLane.DAILY
        assert s.scalar(sa.select(sa.func.count()).select_from(FetchQueueItem)) == 1


def test_disposed_refresh_revives_held_rows_at_55(clean_db, monkeypatch):
    """A disposed case's earlier dossier row (done at 40 from a list, done at 45 from the load, failed) is revived at
    55 in the daily lane with a fresh created_at, so the weekly sweep (50) and a new dossier (40) run first; a pending
    row keeps its better priority (decision 2)."""
    from aslms.domain.ops import FetchStatus as QueueStatus
    from aslms.services import queue

    with clean_db() as s:
        from_list = disposed(s, refreshed_days=40, disposed_days=100)
        from_load = disposed(s, refreshed_days=39, disposed_days=100)
        failed = disposed(s, refreshed_days=38, disposed_days=100)
        still_pending = disposed(s, refreshed_days=37, disposed_days=100)
        old = datetime(2026, 1, 5, tzinfo=UTC)
        for case, prio, lane, status in (
            (from_list, 40, FetchLane.DAILY, QueueStatus.DONE),
            (from_load, 45, FetchLane.LOAD, QueueStatus.DONE),
            (failed, 40, FetchLane.DAILY, QueueStatus.FAILED),
            (still_pending, 40, FetchLane.DAILY, QueueStatus.PENDING),
        ):
            s.add(
                FetchQueueItem(
                    kind=FetchKind.DOSSIER,
                    ref=case.cnr,
                    priority=prio,
                    lane=lane,
                    status=status,
                    created_at=old,
                )
            )
        s.flush()
        monkeypatch.setattr(tracking, "disposed_refresh_cap", lambda *_: 10)  # the cap has its own test
        out = tracking.enqueue_disposed_refresh(s, TODAY, settings(), now=NOW)
        assert out["queued"] == 4
        rows = {
            r.ref: r
            for r in s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.DOSSIER))
        }
        for case in (from_list, from_load, failed):
            row = rows[case.cnr]
            assert row.priority == 55 and FetchLane(row.lane) == FetchLane.DAILY
            assert QueueStatus(row.status) == QueueStatus.PENDING and row.created_at > old
        assert rows[still_pending.cnr].priority == 40 and rows[still_pending.cnr].created_at == old
        # claim order: the pending live dossier (40), a new dossier (40), the weekly sweep (50), then the 55s
        queue.enqueue(s, FetchKind.DOSSIER, "ASHC010099992026", queue.PRIORITY["dossier_new"])
        queue.enqueue(
            s, FetchKind.DOSSIER, "ASHC010099982026", queue.PRIORITY["dossier_refetch"], requeue=True
        )
        s.flush()
        order = [queue.claim(s, [FetchKind.DOSSIER]).ref for _ in range(6)]
        assert order[:3] == [still_pending.cnr, "ASHC010099992026", "ASHC010099982026"]
        assert set(order[3:]) == {from_list.cnr, from_load.cnr, failed.cnr}


def test_disposed_refresh_fallback_date_and_future_date(clean_db):
    with clean_db() as s:
        by_closed = disposed(s, refreshed_days=30, disposed_days=None, closed_days=50)
        disposed(
            s, refreshed_days=30, disposed_days=None, closed_days=500
        )  # first seen disposed too long ago
        future = disposed(
            s, refreshed_days=30, disposed_days=-5
        )  # a disposal date after today counts as today
        refs = tracking.disposed_refresh_refs(s, TODAY, keep_days=365, every_days=28, now=NOW)
        assert set(refs) == {by_closed.cnr, future.cnr}


def test_disposed_refresh_order_cap_and_job_run(clean_db):
    with clean_db() as s:
        cases = [disposed(s, refreshed_days=29 + i, disposed_days=50) for i in range(30)]
        cap_settings = settings(disposed_refresh_daily_max=1)
        out = schedules.run_disposed_refresh(s, cap_settings, today=TODAY, now=NOW)
        # 30 eligible -> ceil(30 / 28) = 2, capped at 1: the oldest refresh goes first
        assert out["eligible"] == 30 and out["cap"] == 1 and out["queued"] == 1
        queued = s.scalars(
            sa.select(FetchQueueItem.ref).where(FetchQueueItem.kind == FetchKind.DOSSIER)
        ).all()
        assert queued == [cases[-1].cnr]
        run = s.scalar(sa.select(JobRun).where(JobRun.job == "disposed-refresh"))
        assert run.counters == out and run.status.value == "succeeded" and run.run_date == TODAY
        off = tracking.enqueue_disposed_refresh(s, TODAY, settings(disposed_refresh_daily_max=0), now=NOW)
        assert off["cap"] == 0 and off["queued"] == 0


def test_restored_case_rejoins_the_daily_cycle(world):
    with world.Session() as s:
        a_edu, u_edu = world.actor(s, "edu_admin")
        case = make_case(s, cnr="ASHC010000012025")
        own.claim(s, a_edu, u_edu, case)
        case.status = CaseStatus.DISPOSED
        case.closed_at = datetime.now(UTC) - timedelta(days=40)
        case.disposal_date = today_ist() - timedelta(days=40)
        case.last_full_refresh_at = datetime.now(UTC) - timedelta(days=30)
        s.commit()
        assert case.cnr in tracking.disposed_refresh_refs(s, today_ist(), keep_days=365, every_days=28)
        data = sample("cnr_pending.json")
        data["cino"] = case.cnr
        assert data["pend_disp"] == "P"
        apply_dossier(s, case, data)
        s.commit()
        s.refresh(case)
        assert case.status == CaseStatus.PENDING and case.closed_at is None
        ev = s.scalar(
            sa.select(Event).where(Event.case_id == case.id, Event.type == EventType.STATUS_CHANGED)
        )
        assert ev.payload["status"] == ["disposed", "pending"]
        assert ev.dedupe_key == f"status_changed:{case.cnr}:pending:{today_ist()}"
        assert case.cnr in tracking.non_disposed_cnrs(s)
        assert case.cnr not in tracking.disposed_refresh_refs(s, today_ist(), keep_days=365, every_days=0 + 7)
        assert tracking.enqueue_status_batches(s) >= 1
        alerts.scan_events(s, config=alerts.AlertConfig())
        s.commit()
        alert = s.scalar(
            sa.select(Alert).where(Alert.case_id == case.id, Alert.kind == AlertKind.STATUS_CHANGED)
        )
        assert alert is not None and alert.data["status"] == "pending"
        assert alert.data["previous_status"] == "disposed" and alert.office_id == world.offices["EDU"].id


def test_each_restoration_raises_its_own_alert(world, monkeypatch):
    """Review finding (decision 4): restored, disposed again, restored again: two restoration alerts."""
    from aslms.services import cases as cases_service

    def dossier(name: str, cnr: str) -> dict:
        data = sample(name)
        data["cino"] = cnr
        return data

    def restorations(s, case_id) -> list[Alert]:
        return [
            a
            for a in s.scalars(
                sa.select(Alert).where(Alert.case_id == case_id, Alert.kind == AlertKind.STATUS_CHANGED)
            ).all()
            if a.data.get("status") == "pending" and a.data.get("previous_status") == "disposed"
        ]

    with world.Session() as s:
        a_edu, u_edu = world.actor(s, "edu_admin")
        case = make_case(s, cnr="ASHC010000022025")
        own.claim(s, a_edu, u_edu, case)
        case.status = CaseStatus.DISPOSED
        case.closed_at = datetime.now(UTC) - timedelta(days=40)
        case.disposal_date = today_ist() - timedelta(days=40)
        s.commit()
        apply_dossier(s, case, dossier("cnr_pending.json", case.cnr))
        alerts.scan_events(s, config=alerts.AlertConfig())
        s.commit()
        assert len(restorations(s, case.id)) == 1
        disposal = dossier("cnr_2026-09-03.json", case.cnr)
        assert disposal["pend_disp"] == "D"
        apply_dossier(s, case, disposal)
        s.commit()
        assert CaseStatus(case.status) == CaseStatus.DISPOSED
        later = today_ist() + timedelta(days=30)  # the next monthly refresh finds it restored again
        monkeypatch.setattr(cases_service, "today_ist", lambda *_: later)
        apply_dossier(s, case, dossier("cnr_pending.json", case.cnr))
        alerts.scan_events(s, config=alerts.AlertConfig())
        s.commit()
        events = s.scalars(
            sa.select(Event).where(Event.case_id == case.id, Event.type == EventType.STATUS_CHANGED)
        ).all()
        assert len(events) == 2
        found = restorations(s, case.id)
        assert len(found) == 2 and {a.source_event_id for a in found} == {e.id for e in events}


# ================================================================================================ the recheck


def _entry(
    seq: int, case: Case | None, *, court_no: str, printed: str | None = None, codes=(), **kw
) -> Entry:
    base = dict(
        seq=seq,
        printed_sr_no=printed or str(seq),
        case_no_text=case.case_no_text if case is not None else kw.pop("case_no", None),
        cnr=case.cnr if case is not None else kw.pop("cnr", None),
        page=1,
        court_no=court_no,
        bench_text="JOINT REGISTRAR (JUDL.) MR. CHINMOY BARUAH",
        section="FOR ORDERS",
        is_connected=False,
        parent_case_no=None,
        is_filing_number=False,
        remarks=None,
        petitioner_text=(case.petitioner_summary if case is not None else None) or "PETITIONER",
        respondent_text="THE STATE OF ASSAM",
        pet_advocate_text="MR. X",
        res_advocate_text=", ".join(codes) or None,
        pet_advocates=["MR. X"],
        res_advocates=list(codes),
        pet_counsel_codes=[],
        res_counsel_codes=list(codes),
        raw_lines=[f"{seq} line"],
    )
    base.update(kw)
    return Entry(**base)


def parsed(d: date, entries: list[Entry]) -> ParsedCauseList:
    return ParsedCauseList("lawazima", "LAWAZIMA", d, 1, [], entries, [])


class Court:
    """The scripted Show Cause List answer and the parser stand-in of one test."""

    def __init__(self, monkeypatch):
        self.answer: bytes | int = b""
        self.parses: dict[bytes, ParsedCauseList | Exception] = {}
        monkeypatch.setattr(cl_store, "parse_causelist_pdf", self.parse)

    def parse(self, data: bytes) -> ParsedCauseList:
        out = self.parses[data]
        if isinstance(out, Exception):
            raise out
        return out


def make_hc(handler):
    gw = Gateway(NapixCrypto(KEY))
    base = router(gw)

    def handle(path, q, request):
        out = handler(gw, path)
        return out if out is not None else base(path, q, request)

    gw.responses = [handle] * 1000
    client = NapixClient(
        base_url="https://gw.test/nic/ecourts",
        client_id="key-test",
        client_secret="secret-test",
        dept_id="dept-test",
        crypto=NapixCrypto(KEY),
        transport=httpx.MockTransport(gw.handle),
        backoff_base=0.0,
    )
    return gw, client, NapixHighCourt(client, "GAHC01", "18")


def court_answer(court: Court):
    def handler(gw: Gateway, path: str):
        if path != SHOW:
            return None
        if isinstance(court.answer, int):
            return gw.encrypted_status(court.answer)
        return gw.envelope_text(json.dumps(base64.b64encode(court.answer).decode()))

    return handler


def recheck(Session, court: Court, d: date, store: LocalStore, *, now: datetime | None = None, s=None):
    gw, client, hc = make_hc(court_answer(court))

    async def go(sess):
        async with client:
            return await cl_store.recheck_day(
                sess, hc, court_of(sess), d, store, now=now, fresh_minutes=180, origin=QueueOrigin()
            )

    if s is not None:
        return asyncio.run(go(s)), gw
    with Session() as sess:
        rep = asyncio.run(go(sess))
        sess.commit()
    return rep, gw


def build_list(
    s,
    store: LocalStore,
    d: date,
    entries: list[Entry],
    *,
    tag="v1",
    fetched_ago=timedelta(days=1),
    list_id: int = 1007,
):
    court = court_of(s)
    cl = Causelist(
        court_id=court.id,
        list_date=d,
        bench_id=2048,
        napix_causelist_id=list_id,
        list_type=ListType.LAWAZIMA,
        list_type_text="LAWAZIMA",
        bench_label="JOINT REGISTRAR (JUDL.) MR. CHINMOY BARUAH",
        source=ListSource.NAPIX,
    )
    s.add(cl)
    s.flush()
    doc, _ = cl_store.store_pdf(s, store, pdf_bytes(tag), doc_date=d, description="test list")
    cl.document_id, cl.fetch_status, cl.fetched_at = (
        doc.id,
        FetchStatus.FETCHED,
        datetime.now(UTC) - fetched_ago,
    )
    cl_store.apply_entries(s, court, cl, parsed(d, entries), report=cl_store.DayReport(list_date=d))
    s.flush()
    return cl


def entry_rows(s, causelist_id) -> list[dict]:
    return [
        {c.name: getattr(e, c.name) for c in CauselistEntry.__table__.columns}
        for e in s.scalars(
            sa.select(CauselistEntry)
            .where(CauselistEntry.causelist_id == causelist_id)
            .order_by(CauselistEntry.sr_no)
        ).all()
    ]


def calls_to(gw: Gateway, path: str) -> int:
    return sum(1 for x in gw.seen if x["path"] == path)


@pytest.fixture()
def store(tmp_path):
    return LocalStore(str(tmp_path / "store"))


def simple_list(world, store, d, *, fetched_ago=timedelta(days=1)):
    with world.Session() as s:
        a = make_case(s, pet="ANIL")
        cl = build_list(s, store, d, [_entry(1, a, court_no="10")], fetched_ago=fetched_ago)
        s.commit()
        return cl.id, a.id


def test_recheck_unchanged(world, store, monkeypatch):
    court = Court(monkeypatch)
    d = today_ist()
    v1_id, _ = simple_list(world, store, d)
    court.answer = pdf_bytes("v1")
    rep, gw = recheck(world.Session, court, d, store)
    assert (rep.candidates, rep.called, rep.unchanged, rep.versions_new) == (1, 1, 1, 0)
    assert calls_to(gw, SHOW) == 1 and calls_to(gw, BENCH) == 0 and calls_to(gw, DETAILS) == 0
    with world.Session() as s:
        v1 = s.get(Causelist, v1_id)
        assert v1.last_checked_at is not None and v1.superseded_at is None and v1.entries_sha256
        assert s.scalar(sa.select(sa.func.count()).select_from(Causelist)) == 1


def test_recheck_freshness(world, store, monkeypatch):
    court = Court(monkeypatch)
    d = today_ist()
    simple_list(world, store, d, fetched_ago=timedelta(minutes=10))
    court.answer = pdf_bytes("v1")
    rep, gw = recheck(world.Session, court, d, store)
    assert rep.skipped_fresh == 1 and rep.called == 0 and gw.seen == []


def test_recheck_retried_item_calls_nothing_for_checked_lists(world, store, monkeypatch):
    court = Court(monkeypatch)
    d = today_ist()
    simple_list(world, store, d)
    court.answer = pdf_bytes("v1")
    first, _ = recheck(world.Session, court, d, store)
    again, gw = recheck(world.Session, court, d, store)
    assert first.called == 1 and again.called == 0 and again.skipped_fresh == 1 and gw.seen == []


def test_recheck_same_entries_different_bytes(world, store, monkeypatch):
    court = Court(monkeypatch)
    d = today_ist()
    with world.Session() as s:
        a = make_case(s, pet="ANIL")
        entries = [_entry(1, a, court_no="10")]
        build_list(s, store, d, entries)
        s.commit()
        docs = s.scalar(sa.select(sa.func.count()).select_from(Document))
    court.answer = pdf_bytes("v1-regenerated")
    court.parses[court.answer] = parsed(d, [_entry(1, a, court_no="10", raw_lines=["1   line  "])])
    rep, _ = recheck(world.Session, court, d, store)
    assert rep.same_entries == 1 and rep.versions_new == 0
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Causelist)) == 1
        assert s.scalar(sa.select(sa.func.count()).select_from(Document)) == docs


def test_real_list_stored_and_read_back_keeps_its_fingerprint(world, store):
    """Review finding on deviation 14: a fixture cause-list PDF through the real parser, stored by `apply_entries` and
    read back, has `stored_fingerprint == parsed_fingerprint`; so the same list in different bytes makes no version."""
    pdf = (FIXTURES / "napix_lawazima_bench2048_2026-09-03.pdf").read_bytes()
    parsed_list = cl_store.parse_causelist_pdf(pdf)
    assert parsed_list.entries
    d = parsed_list.list_date
    with world.Session() as s:
        court = court_of(s)
        cl = Causelist(
            court_id=court.id,
            list_date=d,
            bench_id=2048,
            napix_causelist_id=1007,
            list_type=ListType.LAWAZIMA,
            list_type_text="LAWAZIMA",
            source=ListSource.NAPIX,
        )
        s.add(cl)
        s.flush()
        doc, _ = cl_store.store_pdf(s, store, pdf, doc_date=d, description="fixture list")
        cl.document_id, cl.fetch_status = doc.id, FetchStatus.FETCHED
        cl.fetched_at = datetime.now(UTC) - timedelta(days=1)
        cl_store.apply_entries(s, court, cl, parsed_list, report=cl_store.DayReport(list_date=d))
        s.commit()
        cl_id, written = cl.id, cl.entries_sha256
    with world.Session() as s:
        rows = cl_store.stored_entries(s, cl_id)
        assert len(rows) == len(parsed_list.entries)
        assert cl_store.entries_fingerprint(rows) == cl_store.parsed_fingerprint(parsed_list) == written
        cl = s.get(Causelist, cl_id)
        cl.entries_sha256 = None  # a row parsed before 0023: computed from its stored entries
        assert cl_store.stored_fingerprint(s, cl) == cl_store.parsed_fingerprint(parsed_list)
        s.rollback()
    regenerated = pdf + b"\n% the same list, generated again\n"
    assert hashlib.sha256(regenerated).hexdigest() != hashlib.sha256(pdf).hexdigest()

    def answer(gw: Gateway, path: str):
        if path != SHOW:
            return None
        return gw.envelope_text(json.dumps(base64.b64encode(regenerated).decode()))

    _gw, client, hc = make_hc(answer)

    async def go(sess):
        async with client:
            return await cl_store.recheck_day(sess, hc, court_of(sess), d, store, fresh_minutes=180)

    with world.Session() as s:
        rep = asyncio.run(go(s))
        s.commit()
    assert (rep.called, rep.same_entries, rep.versions_new, rep.unparsed) == (1, 1, 0, 0)
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Causelist)) == 1


def test_recheck_unparsable_then_resolved(world, store, monkeypatch):
    court = Court(monkeypatch)
    d = today_ist()
    v1_id, _ = simple_list(world, store, d)
    with world.Session() as s:
        docs = s.scalar(sa.select(sa.func.count()).select_from(Document))
    bad = pdf_bytes("broken")
    court.answer = bad
    court.parses[bad] = ValueError("no table found")
    rep, _ = recheck(world.Session, court, d, store)
    assert rep.unparsed == 1 and rep.versions_new == 0
    ref = f"{v1_id}|{hashlib.sha256(bad).hexdigest()}"
    with world.Session() as s:
        v1 = s.get(Causelist, v1_id)
        assert v1.superseded_at is None
        assert s.scalar(sa.select(sa.func.count()).select_from(Document)) == docs
        failure = s.scalar(sa.select(SourceFailure).where(SourceFailure.kind == "causelist_reissue"))
        assert failure.ref == ref and failure.resolved_at is None
    empty = pdf_bytes("empty")
    court.answer, court.parses[empty] = empty, parsed(d, [])
    rep, _ = recheck(world.Session, court, d, store, now=datetime.now(UTC) + timedelta(hours=4))
    assert rep.unparsed == 1
    court.answer = pdf_bytes("v1")
    rep, _ = recheck(world.Session, court, d, store, now=datetime.now(UTC) + timedelta(hours=8))
    assert rep.unchanged == 1
    with world.Session() as s:
        open_ = s.scalar(
            sa.select(sa.func.count())
            .select_from(SourceFailure)
            .where(SourceFailure.kind == "causelist_reissue", SourceFailure.resolved_at.is_(None))
        )
        assert open_ == 0


def test_recheck_628_changes_nothing(world, store, monkeypatch):
    court = Court(monkeypatch)
    d = today_ist()
    v1_id, _ = simple_list(world, store, d)
    with world.Session() as s:
        before = entry_rows(s, v1_id)
    court.answer = 628
    rep, _ = recheck(world.Session, court, d, store)
    assert rep.not_available == 1 and rep.versions_new == 0
    with world.Session() as s:
        v1 = s.get(Causelist, v1_id)
        assert v1.superseded_at is None and FetchStatus(v1.fetch_status) == FetchStatus.FETCHED
        assert entry_rows(s, v1_id) == before


def test_reissue_and_reactions(world, store, monkeypatch):
    """A re-issue: one case removed (engine recommendation, a counsel code), one claimed case removed, one claimed case
    removed but its next hearing date still says the date, one claimed case moved, one case added."""
    court = Court(monkeypatch)
    d = today_ist() + timedelta(days=3)
    with world.Session() as s:
        a_edu, u_edu = world.actor(s, "edu_admin")
        a = make_case(s, pet="ANIL")  # removed; engine recommendation; code only in v1
        b = make_case(s, pet="BINA")  # claimed, moved from court 10 to court 11
        c = make_case(s, pet="CHANDAN")  # claimed, removed
        e = make_case(s, pet="ELA", next_hearing=d)  # claimed, removed, the court still gives the date
        for case in (b, c, e):
            own.claim(s, a_edu, u_edu, case)
        v1 = build_list(
            s,
            store,
            d,
            [
                _entry(1, a, court_no="10", codes=["SC, XYZ"]),
                _entry(2, b, court_no="10"),
                _entry(3, c, court_no="10"),
                _entry(4, e, court_no="10"),
            ],
        )
        rec = Recommendation(
            case_id=a.id,
            office_id=world.offices["EDU"].id,
            score=0.9,
            band=ScoreBand.HIGH,
            origin=RecommendationOrigin.CAUSE_LIST,
            actor_name="matching",
        )
        s.add(rec)
        s.commit()
        ids = {"a": a.id, "b": b.id, "c": c.id, "e": e.id, "v1": v1.id, "rec": rec.id}
        assert a.id in s.scalars(
            sa.select(Case.id).where(codes_condition([normalise_counsel_code("SC, XYZ")]))
        )
        v1_rows = entry_rows(s, v1.id)
    with world.Session() as s:
        alerts.sweep_dates(s, config=alerts.AlertConfig())
        s.commit()
        hearing = {
            r.case_id: r for r in s.scalars(sa.select(Alert).where(Alert.kind == AlertKind.HEARING_DUE)).all()
        }
        assert {ids["b"], ids["c"], ids["e"]} <= set(hearing)
        assert hearing[ids["b"]].data["court_no"] == "10"
        b_notes = s.scalar(
            sa.select(sa.func.count())
            .select_from(Notification)
            .where(Notification.alert_id == hearing[ids["b"]].id)
        )

    new_cnr = "ASHC019999992026"
    court.answer = pdf_bytes("v2")
    with world.Session() as s:
        b, case_d_no = s.get(Case, ids["b"]), "WP(C)/9999/2026"
        court.parses[court.answer] = parsed(
            d,
            [
                _entry(1, b, court_no="11", printed="7"),
                _entry(2, None, court_no="11", cnr=new_cnr, case_no=case_d_no, petitioner_text="DEEPA"),
            ],
        )
    rep, gw = recheck(world.Session, court, d, store)
    assert rep.versions_new == 1 and rep.cases_changed == 5 and calls_to(gw, SHOW) == 1

    with world.Session() as s:
        v1 = s.get(Causelist, ids["v1"])
        v2 = s.scalar(sa.select(Causelist).where(Causelist.supersedes_id == v1.id))
        # version 2 replaces version 1; version 1's entries are untouched and still there
        assert v2.version == 2 and v2.superseded_at is None and v1.superseded_at is not None
        assert entry_rows(s, v1.id) == v1_rows
        assert len(entry_rows(s, v2.id)) == 2 and v2.entries_sha256 and v2.document_id != v1.document_id
        current = s.scalars(
            sa.select(Causelist.id).where(Causelist.list_date == d, Causelist.superseded_at.is_(None))
        ).all()
        assert current == [v2.id]
        # cases: the added case is created, provisional, and its dossier queued
        d_case = s.scalar(sa.select(Case).where(Case.cnr == new_cnr))
        assert d_case is not None
        assert s.scalar(
            sa.select(FetchQueueItem).where(
                FetchQueueItem.kind == FetchKind.DOSSIER, FetchQueueItem.ref == new_cnr
            )
        )
        # recommendations: the engine one whose only signal was in v1 expires; claims are untouched
        assert RecommendationStatus(s.get(Recommendation, ids["rec"]).status) == RecommendationStatus.EXPIRED
        for key in ("b", "c", "e"):
            assert primary_owner(s, s.get(Case, ids[key])) is not None
        # the standing-counsel basis follows the current version only
        assert (
            ids["a"]
            not in s.scalars(
                sa.select(Case.id).where(codes_condition([normalise_counsel_code("SC, XYZ")]))
            ).all()
        )
        # timeline
        changes = {
            ev.case_id: ev.payload
            for ev in s.scalars(sa.select(Event).where(Event.type == EventType.LISTING_CHANGED)).all()
        }
        assert changes[ids["a"]]["change"] == "removed" and changes[ids["c"]]["change"] == "removed"
        assert changes[d_case.id]["change"] == "added"
        moved = changes[ids["b"]]
        assert moved["change"] == "moved" and moved["version_from"] == 1 and moved["version_to"] == 2
        assert moved["before"][0]["court_no"] == "10" and moved["after"][0]["court_no"] == "11"
        assert moved["causelist_id"] == str(v2.id)
        # readers
        rows = cl_store_hearing_cases(s, d)
        assert ids["c"] not in rows and ids["b"] in rows and ids["a"] not in rows
        root = world.user(s, "root")
        day = causelist_view.day(s, d)
        listed = [x for b_ in day["benches"] for x in b_["lists"]]
        assert [x["id"] for x in listed] == [v2.id] and listed[0]["version"] == 2
        assert listed[0]["supersedes_id"] == v1.id and listed[0]["corrected_at"] is not None
        old = causelist_view.entries(s, root, d, list_id=v1.id)
        assert old["list"]["superseded"] is True and old["total"] == 4
        assert causelist_view.entries(s, root, d)["total"] == 2
        b_case = s.get(Case, ids["b"])
        listings = case_detail.listings(s, root, b_case)
        assert [(x["superseded"], x["list_version"]) for x in listings.items] == [(False, 2), (True, 1)]
        assert case_detail._counts(s, root, b_case)["listings"] == 1

    # alerts: the next sweep closes the removed listing, keeps the one the court still dates, refreshes the moved one
    with world.Session() as s:
        out = alerts.sweep_dates(s, config=alerts.AlertConfig())
        s.commit()
        assert out["refreshed_hearing"] >= 1
        hearing = {
            r.case_id: r for r in s.scalars(sa.select(Alert).where(Alert.kind == AlertKind.HEARING_DUE)).all()
        }
        c_alert, e_alert, b_alert = hearing[ids["c"]], hearing[ids["e"]], hearing[ids["b"]]
        assert (
            AlertStatus(c_alert.status) == AlertStatus.EXPIRED
            and c_alert.data["closed_reason"] == "date_changed"
        )
        assert AlertStatus(e_alert.status) == AlertStatus.OPEN
        assert AlertStatus(b_alert.status) == AlertStatus.OPEN
        assert b_alert.data["court_no"] == "11" and b_alert.data["item_no"] == "7"
        assert (b_alert.title, b_alert.body) == alert_rules.render_alert(
            AlertKind.HEARING_DUE, s.get(Case, ids["b"]), b_alert.data
        )
        assert (
            s.scalar(
                sa.select(sa.func.count())
                .select_from(Notification)
                .where(Notification.alert_id == b_alert.id)
            )
            == b_notes
        )
    # a second current version of the same list is refused by the partial unique index
    with world.Session() as s:
        v2 = s.scalar(sa.select(Causelist).where(Causelist.version == 2))
        s.add(
            Causelist(
                court_id=v2.court_id,
                list_date=v2.list_date,
                bench_id=v2.bench_id,
                napix_causelist_id=v2.napix_causelist_id,
                list_type=v2.list_type,
                source=v2.source,
                version=3,
                supersedes_id=uuid.UUID(str(ids["v1"])),
            )
        )
        with pytest.raises(sa.exc.IntegrityError):
            s.flush()


def test_reissue_corrects_listed_tomorrow_alerts(world, store, monkeypatch):
    """Decision 13 for the evening listing alert (review finding): a re-issue of tomorrow's list moves one claimed case
    (its `listed_tomorrow` alert shows the new court and item, in place, with no notification), removes one (its alert
    closes `date_changed`) and removes one the court still dates (its alert closes and the hearing alert the listing
    had closed is reopened, so the date is not lost)."""
    court = Court(monkeypatch)
    today = today_ist()
    d = today + timedelta(days=1)
    afternoon = datetime.combine(today, datetime.min.time().replace(hour=14), tzinfo=IST)
    evening = datetime.combine(today, datetime.min.time().replace(hour=19, minute=10), tzinfo=IST)
    cfg = alerts.AlertConfig()
    with world.Session() as s:
        a_edu, u_edu = world.actor(s, "edu_admin")
        b = make_case(s, pet="BINA")  # moved from court 10 item 2 to court 11 item 7
        c = make_case(s, pet="CHANDAN")  # removed
        e = make_case(s, pet="ELA", next_hearing=d)  # removed, the court still gives the date
        for case in (b, c, e):
            own.claim(s, a_edu, u_edu, case)
        build_list(
            s,
            store,
            d,
            [_entry(2, b, court_no="10"), _entry(3, c, court_no="10"), _entry(4, e, court_no="10")],
        )
        s.commit()
        ids = {"b": b.id, "c": c.id, "e": e.id}

    def of(s, kind, key):
        return s.scalar(sa.select(Alert).where(Alert.kind == kind, Alert.case_id == ids[key]))

    def notes(s, alert) -> int:
        return s.scalar(
            sa.select(sa.func.count()).select_from(Notification).where(Notification.alert_id == alert.id)
        )

    with world.Session() as s:
        alerts.sweep_dates(s, now=afternoon, config=cfg)  # hearing alerts first, then the evening listing
        s.commit()
        out = alerts.sweep_dates(s, now=evening, config=cfg)
        s.commit()
        assert out["listed_alerts_new"] == 3 and out["listed_hearing_closed"] == 3
        b_listed = of(s, AlertKind.LISTED_TOMORROW, "b")
        assert (
            b_listed.data["entries"][0]["court_no"] == "10" and b_listed.data["entries"][0]["item_no"] == "2"
        )
        b_notes = notes(s, b_listed)
        assert AlertStatus(of(s, AlertKind.HEARING_DUE, "e").status) == AlertStatus.DONE

    court.answer = pdf_bytes("v2")
    with world.Session() as s:
        court.parses[court.answer] = parsed(d, [_entry(1, s.get(Case, ids["b"]), court_no="11", printed="7")])
    rep, _ = recheck(world.Session, court, d, store)
    assert rep.versions_new == 1

    with world.Session() as s:
        out = alerts.sweep_dates(s, now=evening + timedelta(hours=1), config=cfg)
        s.commit()
        assert (out["refreshed_listed"], out["closed_listed_removed"], out["reopened_hearing"]) == (1, 2, 1)
        b_listed = of(s, AlertKind.LISTED_TOMORROW, "b")
        assert AlertStatus(b_listed.status) == AlertStatus.OPEN
        assert b_listed.data["entries_total"] == 1
        assert (b_listed.data["entries"][0]["court_no"], b_listed.data["entries"][0]["item_no"]) == (
            "11",
            "7",
        )
        assert (b_listed.title, b_listed.body) == alert_rules.render_alert(
            AlertKind.LISTED_TOMORROW, s.get(Case, ids["b"]), b_listed.data
        )
        assert "court 11, item 7" in b_listed.body and "court 10" not in b_listed.title + b_listed.body
        assert notes(s, b_listed) == b_notes
        for key in ("c", "e"):
            listed = of(s, AlertKind.LISTED_TOMORROW, key)
            assert AlertStatus(listed.status) == AlertStatus.EXPIRED
            assert listed.data["closed_reason"] == "date_changed"
        # the court still gives the date for e: its hearing alert speaks again, without the old court and item
        e_hearing = of(s, AlertKind.HEARING_DUE, "e")
        assert AlertStatus(e_hearing.status) == AlertStatus.OPEN and e_hearing.closed_at is None
        assert "closed_reason" not in e_hearing.data and e_hearing.data["court_no"] is None
        # c is dated by nothing now: its hearing alert stays closed
        assert AlertStatus(of(s, AlertKind.HEARING_DUE, "c").status) == AlertStatus.DONE

    with world.Session() as s:  # the next sweep changes nothing
        out = alerts.sweep_dates(s, now=evening + timedelta(hours=2), config=cfg)
        s.commit()
        assert (out["refreshed_listed"], out["closed_listed_removed"], out["reopened_hearing"]) == (0, 0, 0)
        assert out["listed_alerts_new"] == 0
        assert AlertStatus(of(s, AlertKind.HEARING_DUE, "e").status) == AlertStatus.OPEN


def cl_store_hearing_cases(s, d: date) -> set:
    from aslms.services import calendar

    return {
        r.case_id
        for r in calendar.hearing_rows(s, from_=d, to=d, case_condition=sa.true())
        if r.source == "causelist"
    }


def test_day_lock_serialises_a_day_run_and_a_recheck(world, store, monkeypatch, engine):
    court = Court(monkeypatch)
    d = today_ist()
    with world.Session() as s:
        a = make_case(s, pet="ANIL")
        build_list(s, store, d, [_entry(1, a, court_no="10")])
        s.commit()
    court.answer = pdf_bytes("v2")
    court.parses[court.answer] = parsed(d, [_entry(1, a, court_no="12")])
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    holder = Session()
    rep, _ = recheck(Session, court, d, store, s=holder)  # version 2 written, the lock held until commit
    assert rep.versions_new == 1
    done: dict = {}

    def other():
        with Session() as s2:
            done["day"] = asyncio.run(
                cl_store.load_causelist_day(s2, None, court_of(s2), d, store=store, causelist_dir=None)
            )
            done["at"] = time.monotonic()
            s2.commit()

    t = threading.Thread(target=other)
    t.start()
    time.sleep(0.5)
    assert t.is_alive() and "day" not in done  # waits on the date's lock
    released = time.monotonic()
    holder.commit()
    holder.close()
    t.join(10)
    assert done["at"] >= released
    second, gw = recheck(Session, court, d, store)  # the current version was just fetched: nothing to call
    assert second.versions_new == 0 and gw.seen == []
    with Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Causelist).where(Causelist.version == 2)) == 1


def test_runner_dispatches_the_recheck(world, store, monkeypatch):
    from aslms.services.runner import QueueRunner

    court = Court(monkeypatch)
    d = today_ist()
    simple_list(world, store, d)
    court.answer = pdf_bytes("v1")
    gw, client, hc = make_hc(court_answer(court))
    recorder = NapixRecorder()
    client.on_call = recorder.on_call
    with world.Session() as s:
        schedules.enqueue_rechecks(s, [d])
        s.commit()

    async def go():
        async with client:
            runner = QueueRunner(
                world.Session,
                hc,
                settings=settings(napix_rate_reserve=0, napix_live_reserve=0, napix_search_floor=0),
                store=store,
                recorder=recorder,
                reserve=0,
            )
            return await runner.run(max_items=1, kinds=[FetchKind.CAUSELIST_RECHECK])

    rep = asyncio.run(go())
    assert rep.done == 1, rep.items
    with world.Session() as s:
        row = s.scalar(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.CAUSELIST_RECHECK))
        assert row.result["unchanged"] == 1 and row.result["called"] == 1
        logged = s.scalars(sa.select(NapixCallLog.api)).all()
        assert logged and all("show" in api.lower() or "overview" in api.lower() for api in logged)


def test_recheck_failure_keeps_earlier_lists_and_the_retry_calls_only_the_rest(world, store, monkeypatch):
    """Review finding (decision 8): a gateway failure on list 2 of 3 keeps list 1's new version and stamp (each list is
    its own transaction); the retried item calls lists 2 and 3 only, never list 1 again."""
    from aslms.services.runner import QueueRunner

    court = Court(monkeypatch)
    d = today_ist()
    with world.Session() as s:
        a, b, c = (make_case(s, pet=p) for p in ("ANIL", "BINA", "CHANDAN"))
        lists = {
            str(n): build_list(s, store, d, [_entry(1, case, court_no="10")], tag=f"l{n}", list_id=n).id
            for n, case in ((1001, a), (1002, b), (1003, c))
        }
        schedules.enqueue_rechecks(s, [d])
        s.commit()
    reissued = pdf_bytes("l1001-corrected")
    court.parses[reissued] = parsed(d, [_entry(1, a, court_no="12")])
    answers: dict[str, bytes | None] = {"1001": reissued, "1002": None, "1003": pdf_bytes("l1003")}
    shows: list[str] = []

    def handler(gw: Gateway, path: str):
        if path != SHOW:
            return None
        params = dict(kv.split("=", 1) for kv in gw.seen[-1]["plain"].split("|") if "=" in kv)
        shows.append(params["causelist_id"])
        out = answers[params["causelist_id"]]
        if out is None:
            return httpx.Response(503, text="gateway down")
        return gw.envelope_text(json.dumps(base64.b64encode(out).decode()))

    def run_once():
        _gw, client, hc = make_hc(handler)
        recorder = NapixRecorder()
        client.on_call = recorder.on_call

        async def go():
            async with client:
                runner = QueueRunner(
                    world.Session,
                    hc,
                    settings=settings(napix_rate_reserve=0, napix_live_reserve=0, napix_search_floor=0),
                    store=store,
                    recorder=recorder,
                    reserve=0,
                )
                return await runner.run(max_items=1, kinds=[FetchKind.CAUSELIST_RECHECK])

        return asyncio.run(go())

    first = run_once()
    assert first.failed == 1, first.items
    assert shows[0] == "1001" and set(shows) == {"1001", "1002"}  # list 3 never reached
    with world.Session() as s:
        v1 = s.get(Causelist, lists["1001"])
        assert v1.superseded_at is not None and v1.last_checked_at is not None
        v2 = s.scalar(sa.select(Causelist).where(Causelist.supersedes_id == v1.id))
        assert v2 is not None and v2.version == 2 and v2.superseded_at is None
        v2_courts = s.scalars(sa.select(CauselistEntry.court_no).where(CauselistEntry.causelist_id == v2.id))
        assert list(v2_courts) == ["12"]
        changed = sa.select(sa.func.count()).select_from(Event).where(Event.type == EventType.LISTING_CHANGED)
        assert s.scalar(changed) == 1
        for n in ("1002", "1003"):
            assert s.get(Causelist, lists[n]).last_checked_at is None
        row = s.scalar(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.CAUSELIST_RECHECK))
        assert row.status.value == "pending" and row.attempts == 1 and row.not_before > datetime.now(UTC)
        row.not_before = datetime.now(UTC) - timedelta(seconds=1)  # the ladder's wait, skipped
        s.commit()
    shows.clear()
    answers["1002"] = pdf_bytes("l1002")
    again = run_once()
    assert again.done == 1, again.items
    assert shows == ["1002", "1003"]
    with world.Session() as s:
        row = s.scalar(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.CAUSELIST_RECHECK))
        assert row.result["called"] == 2 and row.result["unchanged"] == 2 and row.result["skipped_fresh"] == 1
        assert all(s.get(Causelist, lists[n]).last_checked_at is not None for n in ("1002", "1003"))
        assert s.scalar(sa.select(sa.func.count()).select_from(Causelist)) == 4


# ================================================================================================ schedules


def test_evening_and_morning_schedules(clean_db):
    today = date(2026, 10, 23)
    with clean_db() as s:
        out = schedules.enqueue_evening_lists(s, today)
        assert out == {"days": 3, "rechecks": 2}
        rows = s.scalars(
            sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.CAUSELIST_RECHECK)
        ).all()
        assert sorted(r.ref for r in rows) == ["2026-10-23", "2026-10-24"]
        assert all(r.priority == 21 and FetchLane(r.lane) == FetchLane.DAILY for r in rows)
        days = s.scalars(
            sa.select(FetchQueueItem.ref).where(FetchQueueItem.kind == FetchKind.CAUSELIST_DAY)
        ).all()
        assert sorted(days) == ["2026-10-22", "2026-10-23", "2026-10-24"]
    with clean_db() as s:
        assert schedules.enqueue_morning_lists(s, today, settings(causelist_recheck_morning=True)) == {
            "days": 3,
            "rechecks": 1,
        }
    with clean_db() as s:
        assert schedules.enqueue_morning_lists(s, today, settings(causelist_recheck_morning=False)) == {
            "days": 3,
            "rechecks": 0,
        }


def test_operator_recheck(world):
    today = today_ist()
    with world.Session() as s:
        root = world.user(s, "root")
        member = access.super_admin_member(s, root)
        actor = access.actor_for(root)
        napix_admin.refetch_day(s, actor, member, today, settings(), today=today, recheck=True)
        s.commit()
        row = s.scalar(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.CAUSELIST_RECHECK))
        assert (
            row.ref == today.isoformat() and row.priority == 20 and FetchLane(row.lane) == FetchLane.REQUEST
        )
        assert row.requested_by == member.id
        audit = s.scalar(sa.select(AuditLog).where(AuditLog.action == "napix.refetch_requested"))
        assert audit.after["kind"] == "causelist_recheck"
        with pytest.raises(napix_admin.AdminInputError) as e:
            napix_admin.refetch_day(
                s, actor, member, today - timedelta(days=2), settings(), today=today, recheck=True
            )
        assert e.value.code == "date_out_of_range"
        officer = world.user(s, "edu_off1")
        with pytest.raises(Exception):  # noqa: B017 — without admin.napix_refetch
            napix_admin.refetch_day(
                s, Actor.system("t"), officer, today, settings(), today=today, recheck=True
            )


def test_system_revival_of_an_operator_recheck(world):
    """Review finding: the evening run reviving an operator's done recheck takes the system's lane and priority (daily,
    21) with no person; an operator's pending recheck keeps its person, lane and priority."""
    from aslms.domain.ops import FetchStatus as QueueStatus

    today = today_ist()

    def recheck_row(s):
        return s.scalar(
            sa.select(FetchQueueItem)
            .where(
                FetchQueueItem.kind == FetchKind.CAUSELIST_RECHECK, FetchQueueItem.ref == today.isoformat()
            )
            .execution_options(populate_existing=True)
        )

    with world.Session() as s:
        root = world.user(s, "root")
        member = access.super_admin_member(s, root)
        actor = access.actor_for(root)
        napix_admin.refetch_day(s, actor, member, today, settings(), today=today, recheck=True)
        s.flush()
        schedules.enqueue_evening_lists(s, today)  # pending: the operator's request stands
        row = recheck_row(s)
        assert (row.priority, FetchLane(row.lane), row.requested_by) == (20, FetchLane.REQUEST, member.id)
        row.status = QueueStatus.DONE
        s.flush()
        schedules.enqueue_evening_lists(s, today)  # done: revived as the system's
        row = recheck_row(s)
        assert QueueStatus(row.status) == QueueStatus.PENDING
        assert (row.priority, FetchLane(row.lane), row.requested_by) == (21, FetchLane.DAILY, None)
        row.status = QueueStatus.DONE
        s.flush()
        napix_admin.refetch_day(s, actor, member, today, settings(), today=today, recheck=True)
        row = recheck_row(s)  # the operator reviving the system's row: request lane, 20, the person
        assert (row.priority, FetchLane(row.lane), row.requested_by) == (20, FetchLane.REQUEST, member.id)


# ================================================================================================ the purge

PURGE_NOW = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)  # 23 Oct 2026, 11:30 IST


def ist(y, m, d, hh=12, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST).astimezone(UTC)


def add_calls(s, *stamps: datetime, remaining: int | None = None) -> None:
    for at in stamps:
        s.add(
            NapixCallLog(
                api="overview/overview",
                params_sha256="0" * 64,
                http_status=200,
                ok=True,
                called_at=at,
                rate_limit_remaining=remaining,
            )
        )
    s.flush()


class CountingFactory:
    """A session factory that counts the commits made through it."""

    def __init__(self, Session):
        self.Session = Session
        self.commits = 0

    def __call__(self):
        sess = self.Session()
        original = sess.commit

        def commit():
            self.commits += 1
            original()

        sess.commit = commit
        return sess


def purge_settings(**kw) -> Settings:
    return settings(**kw)


def test_purge_cutoff_batches_job_and_audit(clean_db):
    cutoff = ist_midnight(date(2024, 10, 23))  # 730 IST days before 23 Oct 2026
    assert retention.cutoff_for(730, PURGE_NOW) == cutoff
    with clean_db() as s:
        old = [
            ist(2024, 10, 22, 12),
            ist(2024, 10, 22, 23, 59),
            ist(2024, 10, 21),
            ist(2024, 1, 1),
            ist(2023, 5, 5),
        ]
        add_calls(s, *old)
        add_calls(s, ist(2024, 10, 23, 0, 1), ist(2024, 10, 24))  # 730 and 729 days old: kept
        add_calls(s, PURGE_NOW - timedelta(hours=1), remaining=500)
        s.add(
            NapixResponse(
                api="overview/overview", params_sha256="0" * 64, payload_sha256="1" * 64, payload={}
            )
        )
        s.commit()
    factory = CountingFactory(clean_db)
    rep = retention.purge_call_log(factory, purge_settings(), now=PURGE_NOW, batch=2)
    assert rep.deleted == 5 and rep.batches == 3 and rep.more is False and rep.status == "succeeded"
    assert factory.commits >= 3 + 2  # one per batch, plus the job row's start and finish
    with clean_db() as s:
        kept = s.scalars(sa.select(NapixCallLog.called_at).order_by(NapixCallLog.called_at)).all()
        assert len(kept) == 3 and min(kept) >= cutoff
        assert (
            s.scalar(sa.select(sa.func.count()).select_from(NapixResponse)) == 1
        )  # responses are never purged
        run = s.scalar(sa.select(JobRun).where(JobRun.job == "napix-log-purge"))
        assert run.counters["deleted"] == 5 and run.counters["batches"] == 3 and run.counters["more"] is False
        assert run.counters["keep_days"] == 730 and run.status.value == "succeeded"
        audit = s.scalar(sa.select(AuditLog).where(AuditLog.action == "napix.call_log_purged"))
        assert audit.actor_name == "napix-log-purge" and audit.entity_type == "napix_call_log"
        assert audit.entity_id is None and audit.after["deleted"] == 5 and audit.after["keep_days"] == 730
    again = retention.purge_call_log(clean_db, purge_settings(), now=PURGE_NOW)
    assert again.deleted == 0
    with clean_db() as s:
        assert (
            s.scalar(
                sa.select(sa.func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "napix.call_log_purged")
            )
            == 1
        )
        assert (
            s.scalar(sa.select(sa.func.count()).select_from(JobRun).where(JobRun.job == "napix-log-purge"))
            == 2
        )


def test_purge_dry_run_writes_nothing(clean_db):
    with clean_db() as s:
        add_calls(s, ist(2024, 1, 1), ist(2026, 10, 1))
        s.commit()
    rep = retention.purge_call_log(clean_db, purge_settings(), now=PURGE_NOW, dry_run=True)
    assert rep.deleted == 1 and rep.dry_run
    with clean_db() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(NapixCallLog)) == 2
        assert s.scalar(sa.select(sa.func.count()).select_from(JobRun)) == 0
        assert (
            s.scalar(
                sa.select(sa.func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "napix.call_log_purged")
            )
            == 0
        )


def test_purge_time_limit_ends_partial(clean_db):
    with clean_db() as s:
        add_calls(s, *[ist(2024, 1, i + 1) for i in range(6)])
        s.commit()
    ticks = iter(range(0, 100_000, 1000))
    rep = retention.purge_call_log(
        clean_db, purge_settings(), now=PURGE_NOW, batch=2, max_seconds=60, monotonic=lambda: next(ticks)
    )
    assert rep.deleted == 2 and rep.more is True and rep.status == "partial"
    with clean_db() as s:
        run = s.scalar(sa.select(JobRun).where(JobRun.job == "napix-log-purge"))
        assert run.status.value == "partial" and run.counters["more"] is True


def test_purge_leaves_the_window_and_system_health_unchanged(clean_db):
    now = datetime.now(UTC)
    with clean_db() as s:
        add_calls(s, ist(2023, 1, 1), ist(2023, 6, 1))
        add_calls(s, now - timedelta(hours=2), remaining=900)
        add_calls(s, now - timedelta(hours=1), remaining=880)
        s.commit()
        cfg = settings()
        window_before = napix_window.current(s, cfg, now)
        figures_before = system_health._figures(s, now)
    retention.purge_call_log(clean_db, settings(), now=now)
    with clean_db() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(NapixCallLog)) == 2
        assert napix_window.current(s, settings(), now) == window_before
        assert system_health._figures(s, now) == figures_before


def test_purge_runs_as_aslms_app(clean_db):
    eng = sa.create_engine(TEST_URL, poolclass=sa.pool.NullPool)

    @sa.event.listens_for(eng, "connect")
    def as_app(dbapi_conn, _record):
        with dbapi_conn.cursor() as cur:
            cur.execute("SET ROLE aslms_app")
        dbapi_conn.commit()

    try:
        with clean_db() as s:
            add_calls(s, ist(2023, 1, 1))
            s.commit()
        AppSession = sessionmaker(bind=eng, expire_on_commit=False)
        with AppSession() as s:
            assert s.execute(sa.text("select current_user")).scalar() == "aslms_app"
        rep = retention.purge_call_log(AppSession, settings(), now=PURGE_NOW)
        assert rep.deleted == 1 and rep.status == "succeeded"
    finally:
        eng.dispose()


def test_retention_report_and_data_health_block(clean_db):
    from aslms.services import data_health

    with clean_db() as s:
        add_calls(s, ist(2025, 3, 1), ist(2026, 10, 1))
        s.commit()
        r = retention.retention_report(s)
        assert r["call_log"]["rows"] == 2 and r["call_log"]["bytes"] > 0 and r["responses"]["bytes"] >= 0
        assert {(x["year"], x["rows"]) for x in r["call_log"]["by_api_year"]} == {(2025, 1), (2026, 1)}
        block = data_health.retention(s, settings())
        assert block["call_log_keep_days"] == 730 and block["call_log_bytes"] > 0
        assert block["disposed_refresh"]["eligible"] == 0 and block["last_purge_at"] is None
