"""The load pipeline against the test database and a scripted NAPIX gateway that answers from the recorded
samples: masters sync, one cause-list day (two benches of 2025-01-06), the dossier queue, and the dossier
mapper. Everything is applied twice and the second pass changes nothing."""

from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa

from aslms.core.config import Settings
from aslms.domain.cases import Case, CaseAdvocate, CaseHearing, CaseParty, CaseSnapshot, FirstSeenSource
from aslms.domain.causelists import Causelist, CauselistBenchDay, CauselistEntry
from aslms.domain.courts import Act, Bench, CaseType, Court, District, HighCourt
from aslms.domain.documents import Document, Order
from aslms.domain.ops import FetchKind, FetchQueueItem, FetchStatus
from aslms.services import queue
from aslms.services.cases import apply_dossier, apply_status, get_or_create_case
from aslms.services.masters import sync_masters
from aslms.services.napix_store import NapixRecorder
from aslms.services.runner import QueueRunner, enqueue_days
from aslms.services.storage import LocalStore
from tests.db.conftest import SAMPLES, sample  # noqa: F401


def counts(engine, *tables: str) -> dict[str, int]:
    with engine.connect() as c:
        return {t: c.execute(sa.text(f"select count(*) from {t}")).scalar() for t in tables}


def test_masters_sync_is_idempotent_and_deactivates(clean_db, napix, engine):
    gw, client, hc = napix
    Session = clean_db

    async def go(sess):
        async with client:
            return await sync_masters(sess, hc)

    import asyncio

    with Session() as s:
        rep = asyncio.run(go(s))
        s.commit()
    assert rep.counts["state"]["rows"] >= 1 and rep.counts["district"]["rows"] == 40
    assert rep.counts["case_type"]["rows"] == 222 and rep.counts["act"]["rows"] == 4677
    with Session() as s:
        hc_row = s.scalar(sa.select(HighCourt).where(HighCourt.napix_state_code == 18))
        assert hc_row is not None and hc_row.name
        kamrup_m = s.scalar(sa.select(District).where(District.name == "Kamrup Metropolitan"))
        assert kamrup_m.ecourts_code == 117 and kamrup_m.ecourts_name == "Kamrup(M)"
        assert s.scalar(sa.select(District).where(District.ecourts_name == "CBI")).kind.value == "agency"
        baska = s.scalar(sa.select(District).where(District.ecourts_name == "Baska"))
        assert baska is not None and baska.ecourts_code == 122
        assert s.scalar(sa.select(sa.func.count()).select_from(Court)) == 4
        wa = s.scalar(sa.select(CaseType).where(CaseType.short_name == "WA"))
        assert wa.case_type_code == 112 and wa.full_name.startswith("Appeal before Division Bench")
        n_acts = s.scalar(sa.select(sa.func.count()).select_from(Act))
    before = counts(engine, "districts", "case_types", "acts", "courts", "master_sync_runs")
    with Session() as s:
        rep2 = asyncio.run(go(s))
        s.commit()
    after = counts(engine, "districts", "case_types", "acts", "courts", "master_sync_runs")
    assert rep2.counts["act"]["inserted"] == 0 and rep2.counts["district"]["inserted"] == 0
    assert {k: v for k, v in after.items() if k != "master_sync_runs"} == {
        k: v for k, v in before.items() if k != "master_sync_runs"
    }
    assert after["master_sync_runs"] == before["master_sync_runs"] + 5
    assert n_acts == 4652 and rep.counts["act"]["duplicates"] == 25  # 4,677 rows, 4,652 distinct pairs


def test_causelist_day_and_dossiers(clean_db, napix, engine, tmp_path):
    gw, client, hc = napix
    Session = clean_db
    settings = Settings(
        _env_file=None,
        storage_dir=str(tmp_path / "store"),
        causelist_dir=str(tmp_path / "lists"),
        napix_rate_reserve=0,
    )
    recorder = NapixRecorder()
    client.on_call = recorder.on_call

    async def run(max_items, kinds=None):
        async with client:
            runner = QueueRunner(
                Session,
                hc,
                settings=settings,
                store=LocalStore(settings.storage_dir),
                causelist_dir=tmp_path / "lists",
                recorder=recorder,
                reserve=0,
            )
            return await runner.run(max_items=max_items, kinds=kinds)

    import asyncio

    with Session() as s:
        queue.enqueue(s, FetchKind.MASTERS, "all", queue.PRIORITY["masters"])
        assert enqueue_days(s, date(2025, 1, 5), date(2025, 1, 6)) == 2  # Sunday (no list) and Monday
        s.commit()
    rep = asyncio.run(run(3, [FetchKind.MASTERS, FetchKind.CAUSELIST_DAY]))
    assert rep.processed == 3 and rep.failed == 0, rep.items
    assert rep.skipped == 1  # 2025-01-05: no list
    c1 = counts(
        engine,
        "causelist_bench_days",
        "causelists",
        "documents",
        "causelist_entries",
        "cases",
        "benches",
        "fetch_queue",
        "napix_call_log",
        "napix_responses",
    )
    assert c1["causelist_bench_days"] == 2 and c1["causelists"] == 2 and c1["documents"] == 1
    assert c1["causelist_entries"] == 18 and c1["cases"] == 9 and c1["benches"] == 2
    assert c1["napix_call_log"] >= 8 and c1["napix_responses"] >= 7
    with Session() as s:
        pending = s.scalars(
            sa.select(FetchQueueItem).where(
                FetchQueueItem.kind == FetchKind.DOSSIER, FetchQueueItem.status == FetchStatus.PENDING
            )
        ).all()
        assert len(pending) == 9 and all(len(p.ref) == 16 for p in pending)
        entry = s.scalar(sa.select(CauselistEntry).where(CauselistEntry.cnr == "GAHC010020342016"))
        assert (
            entry.case_no_text == "WP(C)/4189/2016"
            and entry.section == "ORDERS"
            and entry.counsel_codes == ["GA, ASSAM"]
        )
        assert entry.case_id is not None
        case = s.get(Case, entry.case_id)
        assert (
            case.is_provisional
            and case.ref_no.startswith("ASLMS/GOA/CASE/")
            and case.case_type_text == "WP(C)"
        )
        assert case.reg_no == 4189 and case.reg_year == 2016 and case.case_type_id is not None
        day = s.scalar(sa.select(CauselistBenchDay).where(CauselistBenchDay.bench_id == 2110))
        assert day.judge_names_as_listed.startswith("JOINT REGISTRAR (VIGILANCE)")
        cl = s.scalar(sa.select(Causelist).where(Causelist.bench_id == 2048))
        assert cl.napix_causelist_id == 1007 and cl.list_type.value == "lawazima" and cl.entry_count == 9

    # the same day again: nothing new
    with Session() as s:
        queue.enqueue(s, FetchKind.CAUSELIST_DAY, "2025-01-06", 20, requeue=True)
        s.commit()
    rep = asyncio.run(run(1, [FetchKind.CAUSELIST_DAY]))
    assert rep.done == 1
    c2 = counts(
        engine, "causelist_bench_days", "causelists", "documents", "causelist_entries", "cases", "benches"
    )
    assert {k: c2[k] for k in c2} == {k: c1[k] for k in c2}

    # dossiers
    rep = asyncio.run(run(None, [FetchKind.DOSSIER]))
    assert rep.done == 9 and rep.failed == 0, rep.items
    c3 = counts(
        engine,
        "case_parties",
        "case_advocates",
        "case_acts",
        "case_hearings",
        "orders",
        "case_snapshots",
        "case_links",
        "case_lower_courts",
        "events",
    )
    assert (
        c3["case_parties"] == 9 * (67 + 14)
        and c3["case_acts"] == 9
        and c3["case_hearings"] == 27
        and c3["orders"] == 27
    )
    assert c3["case_snapshots"] == 9 and c3["case_links"] == 0 and c3["case_lower_courts"] == 0
    with Session() as s:
        case = s.scalar(sa.select(Case).where(Case.cnr == "GAHC010020342016"))
        assert (
            not case.is_provisional
            and case.status.value == "pending"
            and case.last_full_refresh_at is not None
        )
        assert case.filing_date == date(2026, 6, 22) and case.registration_date == date(2026, 7, 9)
        assert case.filing_no == 7451 and case.filing_no_text == "WP(C)/7451/2026"
        assert case.bench_name == "Single Bench" and case.bench_type_code == 1 and case.napix_bench_id == 1854
        assert case.coram.startswith("HONOURABLE MR. JUSTICE MANISH") and case.coram_designation == "JUDGE"
        assert (
            case.category_code == 10160 and case.filing_state_code == 18 and case.filing_district_code == 100
        )
        assert (
            case.district_name_as_listed == "Dima Hasao"
            and case.district_id is not None
            and case.state_id is not None
        )
        assert case.petitioner_summary == "PROSANJIT NUNISA AND 66 ORS" and case.res_advocate == "DY.S.G.I."
        assert (
            case.last_hearing_date == date(2026, 9, 23)
            and case.next_hearing_date is None
            and case.next_purpose == "ORDERS"
        )
        assert case.short_order == "Order Passed" and case.main_matter_text is None
        bench = s.get(Bench, case.bench_id)
        assert bench.bench_id == 1854 and bench.bench_name == "Single Bench"
        advs = s.scalars(sa.select(CaseAdvocate).where(CaseAdvocate.case_id == case.id)).all()
        assert {(a.side.value, a.name_as_listed, a.counsel_code) for a in advs} == {
            ("petitioner", "MR. A I KATHAR", None),
            ("respondent", "DY.S.G.I.", "DY.S.G.I."),
        }
        p1 = s.scalar(
            sa.select(CaseParty).where(
                CaseParty.case_id == case.id, CaseParty.role == "petitioner", CaseParty.party_no == 1
            )
        )
        assert p1.name == "PROSANJIT NUNISA AND 66 ORS" and p1.has_legal_heir is False
        p67 = s.scalar(
            sa.select(CaseParty).where(
                CaseParty.case_id == case.id, CaseParty.role == "petitioner", CaseParty.party_no == 67
            )
        )
        assert p67.name == "SRI MOJARI RONGHI"
        hearing = s.scalar(
            sa.select(CaseHearing).where(
                CaseHearing.case_id == case.id, CaseHearing.business_date == date(2026, 9, 23)
            )
        )
        assert (
            hearing.hearing_date is None and hearing.purpose == "ORDERS" and hearing.causelist_type == "Daily"
        )
        orders = s.scalars(sa.select(Order).where(Order.case_id == case.id).order_by(Order.order_date)).all()
        assert [o.order_no for o in orders] == ["1", "2", "3"] and all(
            o.kind.value == "interim" for o in orders
        )
        snap = s.scalar(sa.select(CaseSnapshot).where(CaseSnapshot.case_id == case.id))
        assert snap.payload["cino"] == "GAHC010020342016" and snap.source.value == "cnr"
        doc = s.scalar(sa.select(Document))
        assert (tmp_path / "store" / doc.storage_key).exists()

    # the same dossiers again: nothing new
    with Session() as s:
        for cnr in s.scalars(sa.select(Case.cnr)).all():
            queue.enqueue(s, FetchKind.DOSSIER, cnr, 40, requeue=True)
        s.commit()
    rep = asyncio.run(run(None, [FetchKind.DOSSIER]))
    assert rep.done == 9
    assert counts(engine, *c3.keys()) == c3


def test_apply_status_marks_changes(clean_db, engine):
    Session = clean_db
    with Session() as s:
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        case, created = get_or_create_case(
            s, court, cnr="GAHC010129772026", case_no="WP(C)/3600/2026", source=FirstSeenSource.SEARCH
        )
        assert created
        rep = apply_dossier(s, case, sample("cnr_pending.json"))
        assert rep.snapshot_new and rep.counts["case_parties"] == 81
        block = sample("current_status_pending.json")["cases1"]
        rep2 = apply_status(s, case, block)
        assert rep2.snapshot_new and not rep2.changed and case.goshwara_no == "0" and not case.dossier_stale
        block2 = {**block, "date_next_list": "2026-10-20", "purpose_name": "HEARING"}
        rep3 = apply_status(s, case, block2)
        assert rep3.changed and set(rep3.status_changes) == {"next_hearing_date", "next_purpose"}
        assert case.next_hearing_date == date(2026, 10, 20) and case.dossier_stale
        with pytest.raises(ValueError):
            apply_status(s, case, {**block, "cino": "GAHC010000000000"})
        s.rollback()


def test_queue_claim_order_and_failure_backoff(clean_db):
    Session = clean_db
    with Session() as s:
        assert queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000000001", 50)
        assert queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000000002", 20)
        assert queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000000001", 10)  # better priority wins
        first = queue.claim(s)
        assert first.ref == "GAHC010000000001" and first.priority == 10 and first.attempts == 1
        queue.fail(s, first, "boom")
        assert first.status == FetchStatus.PENDING and first.not_before is not None
        second = queue.claim(s)
        assert second.ref == "GAHC010000000002"
        queue.complete(s, second, {"ok": True})
        assert queue.claim(s) is None  # the failed one waits for not_before
        assert not queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000000002", 20)  # done stays done
        assert queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000000002", 20, requeue=True)
        s.rollback()
