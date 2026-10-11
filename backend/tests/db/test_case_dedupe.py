"""One row per case (design `data-load-console`, decisions 13-16) against the test database: a dossier adopts the
provisional row of its number, the runner merges a provisional row into the row holding its CNR, a provisional row
with portal records is listed for review instead, the court's own duplicates are linked (never merged) and feed the
linked-case signal, the advisory lock keeps one row for one printed number, and the sweep."""

from __future__ import annotations

import asyncio
import threading
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from aslms.core.config import Settings
from aslms.domain.cases import Case, CaseLink, FirstSeenSource, LinkKind, LinkSource
from aslms.domain.causelists import (
    Causelist,
    CauselistEntry,
    EntrySource,
    ListSource,
    ListType,
    ResolutionStatus,
)
from aslms.domain.courts import CaseType, Court
from aslms.domain.events import AuditLog, Event
from aslms.domain.ops import FetchKind, FetchQueueItem, FetchStatus, SourceFailure
from aslms.domain.org import Office
from aslms.domain.ownership import (
    CaseOwnership,
    Recommendation,
    RecommendationStatus,
    ScoreBand,
)
from aslms.domain.reference import EventType
from aslms.services import case_dedupe, case_search, court_search, queue
from aslms.services import ownership as own
from aslms.services.cases import apply_dossier, get_or_create_case
from aslms.services.napix_store import NapixRecorder
from aslms.services.runner import QueueRunner
from aslms.services.storage import LocalStore
from tests.db.conftest import sample
from tests.db.world import make_case

CNR = "GAHC010129772026"  # the dossier sample is WP(C)/3600/2026


def _court(s) -> Court:
    return s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))


def _wpc(s) -> CaseType:
    court = _court(s)
    ct = s.scalar(sa.select(CaseType).where(CaseType.court_id == court.id, CaseType.case_type_code == 111))
    if ct is None:
        ct = CaseType(
            court_id=court.id, case_type_code=111, type_name="WP(C)", short_name="WP(C)", aliases=["WPC"]
        )
        s.add(ct)
        s.flush()
    return ct


def _entry(s, case: Case, printed: str, list_date: date = date(2025, 1, 6)) -> CauselistEntry:
    cl = Causelist(
        court_id=case.court_id, list_date=list_date, list_type=ListType.DAILY, source=ListSource.GHC_WEBSITE
    )
    s.add(cl)
    s.flush()
    e = CauselistEntry(
        causelist_id=cl.id,
        sr_no=1,
        case_id=case.id,
        case_no_text=printed,
        source=EntrySource.PDF_PARSE,
        resolution_status=ResolutionStatus.PROVISIONAL,
    )
    s.add(e)
    s.flush()
    return e


def _holder(s, cnr: str = CNR) -> Case:
    case, _ = get_or_create_case(s, _court(s), cnr=cnr, case_no=None, source=FirstSeenSource.SEARCH)
    apply_dossier(s, case, {**sample("cnr_pending.json"), "cino": cnr})
    return case


def _case_search_handler(gw, base, rows: dict):
    def handle(path, q, request):
        if path == "hc-case-search-api/casesearch":
            return gw.envelope({"establishment_name": "Principal Seat", "casenos": rows})
        return base(path, q, request)

    return handle


def _with_case_search(gw, rows: dict) -> None:
    from tests.db.conftest import router

    gw.responses = [_case_search_handler(gw, router(gw), rows)] * 10_000


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None, storage_dir=str(tmp_path / "store"), causelist_dir=str(tmp_path / "lists")
    )


def _run(Session, client, hc, tmp_path, recorder, **kw):
    async def go():
        async with client:
            settings = _settings(tmp_path)
            runner = QueueRunner(
                Session,
                hc,
                settings=settings,
                store=LocalStore(settings.storage_dir),
                causelist_dir=tmp_path / "lists",
                recorder=recorder,
            )
            return await runner.run(**kw)

    return asyncio.run(go())


def _count(s, model, *conds) -> int:
    return s.scalar(sa.select(sa.func.count()).select_from(model).where(*conds))


def test_fetch_dossier_adopts_provisional(clean_db, napix):
    gw, client, hc = napix
    Session = clean_db
    with Session() as s:
        _wpc(s)
        p, created = get_or_create_case(
            s, _court(s), cnr=None, case_no="WP(C)/3600/2026", source=FirstSeenSource.CAUSELIST
        )
        assert created and p.cnr is None
        ref_no = p.ref_no
        s.commit()

    async def go():
        async with client:
            with Session() as s:
                fetched = await court_search.fetch_dossier(
                    s, hc, _court(s), CNR, source=FirstSeenSource.SEARCH
                )
                s.commit()
                return fetched.case.id

    case_id = asyncio.run(go())
    with Session() as s:
        assert _count(s, Case) == 1
        case = s.get(Case, case_id)
        assert case.ref_no == ref_no and case.cnr == CNR and not case.is_provisional
        assert case.case_no_text == "WP(C)/3600/2026"


def test_runner_merges_provisional_into_cnr_holder(clean_db, napix, tmp_path):
    gw, client, hc = napix
    Session = clean_db
    _with_case_search(
        gw, {"case1": {"cino": CNR, "type_name": "WP(C)", "reg_no": "3600", "reg_year": "2026"}}
    )
    recorder = NapixRecorder()
    client.on_call = recorder.on_call
    with Session() as s:
        _wpc(s)
        goa = s.scalar(sa.select(Office).where(Office.code == "GOA"))
        p, _ = get_or_create_case(
            s, _court(s), cnr=None, case_no="WPC/3600/2026", source=FirstSeenSource.CAUSELIST
        )
        entry = _entry(s, p, "WPC/3600/2026")
        s.add(
            Recommendation(
                case_id=p.id, office_id=goa.id, score=0.6, band=ScoreBand.MEDIUM, actor_name="engine"
            )
        )
        holder = _holder(s)
        assert holder.case_no_text == "WP(C)/3600/2026" and p.cnr is None
        queue.enqueue(s, FetchKind.DOSSIER, "GAHC01|WPC/3600/2026", 44)
        ids = (p.id, holder.id, entry.id)
        s.commit()
    rep = _run(Session, client, hc, tmp_path, recorder, max_items=1, kinds=[FetchKind.DOSSIER])
    assert rep.done == 1 and rep.failed == 0, rep.items
    with Session() as s:
        p, holder, entry = s.get(Case, ids[0]), s.get(Case, ids[1]), s.get(CauselistEntry, ids[2])
        assert p.merged_into_case_id == holder.id and p.cnr is None
        assert entry.case_id == holder.id and entry.case_no_text == "WPC/3600/2026"
        rec = s.scalar(sa.select(Recommendation).where(Recommendation.case_id == p.id))
        assert rec.status == RecommendationStatus.EXPIRED
        ev = s.scalar(sa.select(Event).where(Event.case_id == holder.id, Event.type == EventType.CASE_MERGED))
        assert ev is not None and ev.payload["merged_ref_no"] == p.ref_no
        audit = s.scalar(sa.select(AuditLog).where(AuditLog.action == "case.merged"))
        assert audit.case_id == holder.id and audit.actor_name == "dedupe"
        row = s.scalar(sa.select(FetchQueueItem).where(FetchQueueItem.ref == "GAHC01|WPC/3600/2026"))
        assert row.status == FetchStatus.DONE and row.result["into"] == holder.ref_no


def test_provisional_with_portal_records_not_merged(world, napix, tmp_path):
    gw, client, hc = napix
    Session = world.Session
    _with_case_search(
        gw, {"case1": {"cino": CNR, "type_name": "WP(C)", "reg_no": "3600", "reg_year": "2026"}}
    )
    recorder = NapixRecorder()
    client.on_call = recorder.on_call
    with Session() as s:
        _wpc(s)
        p, _ = get_or_create_case(
            s, _court(s), cnr=None, case_no="WPC/3600/2026", source=FirstSeenSource.CAUSELIST
        )
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, p)
        holder = _holder(s)
        queue.enqueue(s, FetchKind.DOSSIER, "GAHC01|WPC/3600/2026", 44)
        ids = (p.id, holder.id)
        s.commit()
    rep = _run(Session, client, hc, tmp_path, recorder, max_items=1, kinds=[FetchKind.DOSSIER])
    assert rep.skipped == 1 and rep.failed == 0, rep.items
    with Session() as s:
        p, holder = s.get(Case, ids[0]), s.get(Case, ids[1])
        assert p.merged_into_case_id is None and p.cnr is None
        assert holder.merged_into_case_id is None
        fail = s.scalar(sa.select(SourceFailure).where(SourceFailure.kind == "case_duplicate"))
        assert fail.ref == f"{p.id}|{holder.id}" and "case_ownership" in fail.error
        row = s.scalar(sa.select(FetchQueueItem).where(FetchQueueItem.ref == "GAHC01|WPC/3600/2026"))
        assert row.status == FetchStatus.SKIPPED and row.result["needs_review"] is True
        assert _count(s, CaseOwnership, CaseOwnership.case_id == holder.id) == 0
        assert _count(s, AuditLog, AuditLog.action == "case.merged") == 0


def test_court_duplicates_linked_not_merged(world):
    with world.Session() as s:
        a = make_case(s, cnr="GAHC010000012025", case_no="WP(C)/500/2025")
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, a)
        b = make_case(s, cnr="GAHC010000022025", case_no="WP (C)/500/2025")
        report = case_dedupe.check_cases(s, [b.id])
        assert report.court_linked == 1 and report.merged == 0
        link = s.scalar(sa.select(CaseLink).where(CaseLink.kind == LinkKind.COURT_DUPLICATE))
        assert (link.from_case_id, link.to_case_id, link.to_cnr) == (b.id, a.id, a.cnr)
        assert link.source == LinkSource.DEDUPE and link.to_case_no_text == "WP(C)/500/2025"
        linked = s.scalars(sa.select(Event.case_id).where(Event.type == EventType.CASE_LINKED)).all()
        assert set(linked) == {a.id, b.id}
        assert _count(s, AuditLog, AuditLog.action == "case.court_duplicate_linked") == 1
        # idempotent, from either side
        assert case_dedupe.check_cases(s, [a.id, b.id]).court_linked == 0
        # the linked-case signal: EDU, which claimed A, is recommended B; B is never claimed automatically
        edu = world.office(s, "EDU")
        rec = s.scalar(
            sa.select(Recommendation).where(
                Recommendation.case_id == b.id, Recommendation.office_id == edu.id
            )
        )
        assert rec is not None and rec.status == RecommendationStatus.RECOMMENDED
        assert _count(s, CaseOwnership, CaseOwnership.case_id == b.id) == 0
        assert a.merged_into_case_id is None and b.merged_into_case_id is None
        s.commit()


def test_filing_number_duplicates_linked(world):
    with world.Session() as s:
        a = make_case(s, cnr="GAHC010000032025", case_no="WP(C)/600/2025")
        b = make_case(s, cnr="GAHC010000042025", case_no="WP(C)/601/2025")
        for c in (a, b):
            c.filing_case_type_text, c.filing_no, c.filing_year = "WP(C)", 7451, 2025
        c3 = make_case(s, cnr="GAHC010000052025", case_no="WP(C)/602/2025")
        c3.filing_case_type_text, c3.filing_no, c3.filing_year = "WP(C)", 7452, 2025
        s.flush()
        assert case_dedupe.check_cases(s, [a.id]).court_linked == 1
        links = s.scalars(sa.select(CaseLink).where(CaseLink.kind == LinkKind.COURT_DUPLICATE)).all()
        assert [(lk.from_case_id, lk.to_case_id) for lk in links] == [(b.id, a.id)]
        s.commit()


def test_unregistered_cases_never_court_duplicates(world):
    """Filed but unregistered cases carry reg_no 0 and reg_year 0 (`WA/0/0`); a filing number or year of 0 is as
    empty. Rows sharing such a key are different cases: no link, no merge, nothing for the sweep."""
    with world.Session() as s:
        court = _court(s)
        wa = CaseType(court_id=court.id, case_type_code=9001, type_name="WA", short_name="WA", aliases=[])
        s.add(wa)
        s.flush()
        rows = []
        for i, filing_no in enumerate((12583, 12347, 8682)):
            c = make_case(s, cnr=f"GAHC0100{i:04d}2026", case_no="WA/0/0")
            c.case_type_id, c.reg_no, c.reg_year = wa.id, 0, 0
            c.filing_case_type_id, c.filing_case_type_text = wa.id, "WA"
            c.filing_no, c.filing_year = filing_no, 2026
            rows.append(c)
        # two more registered cases whose filing numbers are both 0/0
        for i in range(2):
            c = make_case(s, cnr=f"GAHC0101{i:04d}2026", case_no=f"WA/{70 + i}/2026")
            c.case_type_id, c.reg_no, c.reg_year = wa.id, 70 + i, 2026
            c.filing_case_type_id, c.filing_case_type_text, c.filing_no, c.filing_year = wa.id, "WA", 0, 0
            rows.append(c)
        # a provisional row printed WA/0/0 is not merged into any of them
        p, created = get_or_create_case(
            s, court, cnr=None, case_no="WA/0/0", source=FirstSeenSource.CAUSELIST
        )
        assert created and p.cnr is None
        s.flush()
        before = (_count(s, AuditLog), _count(s, Event), _count(s, CaseLink))
        for c in rows:
            assert case_dedupe.court_duplicates(s, c) == []
        assert case_dedupe.check_cases(s, [c.id for c in rows] + [p.id]).counts() == {
            "merged": 0,
            "needs_review": 0,
            "court_linked": 0,
        }
        assert case_dedupe.sweep(s, dry_run=True).counts() == {
            "merged": 0,
            "needs_review": 0,
            "court_linked": 0,
        }
        assert case_dedupe.sweep(s).counts() == {"merged": 0, "needs_review": 0, "court_linked": 0}
        assert (_count(s, AuditLog), _count(s, Event), _count(s, CaseLink)) == before
        assert {c.merged_into_case_id for c in rows + [p]} == {None}
        s.commit()


def test_concurrent_provisional_creation_one_row(clean_db, engine):
    Session = sessionmaker(bind=engine)
    barrier = threading.Barrier(2)
    made: list[bool] = []
    errors: list[BaseException] = []

    def create():
        try:
            with Session() as s:
                court = _court(s)
                barrier.wait(timeout=10)
                case, created = get_or_create_case(
                    s, court, cnr=None, case_no="WP(C)/9999/2025", source=FirstSeenSource.CAUSELIST
                )
                made.append(created)
                s.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=create) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not errors, errors
    with Session() as s:
        assert _count(s, Case, Case.case_no_text == "WP(C)/9999/2025") == 1
    assert sorted(made) == [False, True]


def test_sweep_dry_run_writes_nothing_and_real_run_counts(world):
    with world.Session() as s:
        court = _court(s)
        holder = make_case(s, cnr="GAHC010000062025", case_no="WP(C)/700/2025")
        p, created = get_or_create_case(
            s, court, cnr=None, case_no="WP(C) /700/2025", source=FirstSeenSource.CAUSELIST
        )
        assert created and p.cnr is None
        twin_a = make_case(s, cnr="GAHC010000082025", case_no="WA/800/2025")
        twin_b = make_case(s, cnr="GAHC010000092025", case_no="WA/800/2025")
        s.flush()
        before = (_count(s, AuditLog), _count(s, Event), _count(s, CaseLink))
        dry = case_dedupe.sweep(s, dry_run=True)
        assert dry.counts() == {"merged": 1, "needs_review": 0, "court_linked": 1}
        assert (_count(s, AuditLog), _count(s, Event), _count(s, CaseLink)) == before
        assert p.merged_into_case_id is None
        real = case_dedupe.sweep(s)
        assert real.counts() == dry.counts()
        s.refresh(p)
        assert p.merged_into_case_id == holder.id
        assert _count(s, CaseLink, CaseLink.kind == LinkKind.COURT_DUPLICATE) == 1
        assert {twin_a.merged_into_case_id, twin_b.merged_into_case_id} == {None}
        # nothing left to do
        assert case_dedupe.sweep(s).counts() == {"merged": 0, "needs_review": 0, "court_linked": 0}
        s.commit()


def test_merged_case_leaves_lists_and_search(world):
    with world.Session() as s:
        court = _court(s)
        holder = make_case(s, cnr="GAHC010000102025", case_no="WP(C)/900/2025", pet="RAMEN DAS")
        p, _ = get_or_create_case(
            s, court, cnr=None, case_no="WP(C)/900/2025", source=FirstSeenSource.CAUSELIST
        )
        p.petitioner_summary = "RAMEN DAS"
        s.flush()
        out = case_dedupe.merge_provisional(s, p, holder)
        assert isinstance(out, case_dedupe.MergeResult)
        user = world.user(s, "root")
        page = case_search.search(s, user, q="WP(C)/900/2025")
        refs = [i["case"]["ref_no"] for i in page.items]
        assert holder.ref_no in refs and p.ref_no not in refs
        s.commit()


def _merge_in_thread(Session, ids, out: list, errors: list) -> threading.Thread:
    def go():
        try:
            with Session() as s:
                p, holder = s.get(Case, ids[0]), s.get(Case, ids[1])
                out.append(case_dedupe.merge_provisional(s, p, holder))
                s.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    return threading.Thread(target=go)


def test_merge_waits_for_concurrent_claim_and_lists_for_review(world):
    """Review finding: the merge locks the provisional row before checking its portal records, so a claim taken
    at the same time is seen and the pair is listed for review instead of merging a claimed case."""
    import time

    Session = world.Session
    with Session() as s:
        holder = make_case(s, cnr="GAHC010000112025", case_no="WP(C)/950/2025")
        p, _ = get_or_create_case(
            s, _court(s), cnr=None, case_no="WP(C)/950/2025", source=FirstSeenSource.CAUSELIST
        )
        ids = (p.id, holder.id)
        s.commit()
    out: list = []
    errors: list = []
    with Session() as a:
        actor, admin = world.actor(a, "edu_admin")
        own.claim(a, actor, admin, a.get(Case, ids[0]))
        a.flush()  # the claim holds P's row lock and its ownership row is not yet committed
        t = _merge_in_thread(Session, ids, out, errors)
        t.start()
        time.sleep(1.0)
        assert t.is_alive(), (out, errors)  # the merge waits for the claim's lock
        a.commit()
    t.join(30)
    assert not errors, errors
    assert len(out) == 1 and isinstance(out[0], case_dedupe.NeedsReview)
    assert "case_ownership" in out[0].records
    with Session() as s:
        assert s.get(Case, ids[0]).merged_into_case_id is None
        assert _count(s, CaseOwnership, CaseOwnership.case_id == ids[0]) == 1
        assert _count(s, AuditLog, AuditLog.action == "case.merged") == 0


def test_merge_of_row_adopted_meanwhile_is_stale(world):
    """A provisional row that took a CNR while the merge waited for its lock is not merged; the sweep skips it."""
    import time

    Session = world.Session
    with Session() as s:
        holder = make_case(s, cnr="GAHC010000122025", case_no="WP(C)/960/2025")
        p, _ = get_or_create_case(
            s, _court(s), cnr=None, case_no="WP(C)/960/2025", source=FirstSeenSource.CAUSELIST
        )
        ids = (p.id, holder.id)
        s.commit()
    out: list = []
    errors: list = []
    with Session() as a:
        a.execute(sa.select(Case.id).where(Case.id == ids[0]).with_for_update())
        a.get(Case, ids[0]).cnr = "GAHC010000132025"
        a.flush()
        t = _merge_in_thread(Session, ids, out, errors)
        t.start()
        time.sleep(1.0)
        assert t.is_alive(), (out, errors)
        a.commit()
    t.join(30)
    assert not out and len(errors) == 1 and isinstance(errors[0], case_dedupe.MergeStale), errors
    with Session() as s:
        assert s.get(Case, ids[0]).merged_into_case_id is None
