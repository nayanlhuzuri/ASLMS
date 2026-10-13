"""The cause-list world of the Cause list screen tests (design `portal-causelist`, Tests), on top of the committed
recommend-and-claim world (`tests/db/world.py`; its second department HEALTH stands for the design's FIN):

13 Oct 2026 (D2):
- bench 1854, a division bench, court `10`: a Daily list (PDF stored) with sections ORDERS / FOR ADMISSION, a
  connected row, a row without a case and a row of a merged case; a Supplementary list without a PDF;
- bench 2048, a registrar bench, court `111`: a Lawazima list (PDF stored);
- bench 777, court `2`: a Daily list (PDF stored);
- bench 3000: sat (in `causelist_bench_days`) but published no list.
12 Oct 2026 (D1): bench 1854's Daily list, one row. 20 Oct 2026 (D3): one court-wide website file, no PDF.

Cases: `pool` (never owned), `rec_both` (recommended to EDU strong 0.95 and HEALTH possible 0.62), `edu_owned`
(claimed by EDU), `health_rec_edu` (owned by HEALTH, recommended to EDU), `survivor` and `merged` (a provisional
case merged into `survivor`, its row not re-pointed), `pool2`, `other`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aslms.domain.cases import Case
from aslms.domain.causelists import (
    Causelist,
    CauselistBenchDay,
    CauselistEntry,
    EntrySource,
    FetchStatus,
    ListSource,
    ListType,
    ParseStatus,
    ResolutionStatus,
)
from aslms.domain.courts import Court
from aslms.domain.ownership import Recommendation, RecommendationOrigin, ScoreBand
from aslms.services import causelists as cl_store
from aslms.services import ownership as own
from aslms.services.storage import LocalStore
from tests.db.world import DIVISION_BENCH, SINGLE_BENCH, make_case

D1, D2, D3 = date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 20)
REGISTRAR_BENCH = "JOINT REGISTRAR (JUDL.) MR. CHINMOY BARUAH"
SAT_ONLY = "HONOURABLE MR. JUSTICE MANISH CHOUDHURY"


@dataclass
class CL:
    cases: dict[str, uuid.UUID] = field(default_factory=dict)
    lists: dict[str, uuid.UUID] = field(default_factory=dict)
    entries: dict[str, uuid.UUID] = field(default_factory=dict)
    docs: dict[str, uuid.UUID] = field(default_factory=dict)


def pdf_bytes(tag: str) -> bytes:
    return b"%PDF-1.4\n% cause list " + tag.encode() + b"\n%%EOF\n"


def recommend(s: Session, world, case: Case, code: str, score: float, band: ScoreBand) -> Recommendation:
    rec = Recommendation(
        case_id=case.id,
        office_id=world.offices[code].id,
        score=score,
        band=band,
        origin=RecommendationOrigin.CAUSE_LIST,
        actor_name="matching",
    )
    s.add(rec)
    s.flush()
    return rec


def build(world, store: LocalStore) -> CL:
    out = CL()
    with world.Session() as s:
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        a_edu, u_edu = world.actor(s, "edu_admin")
        a_health, u_health = world.actor(s, "health_admin")

        pool = make_case(s, pet="RAM KUMAR DAS", res="STATE OF ASSAM")
        rec_both = make_case(s, pet="ANIMA BORAH", res="EDUCATION DEPARTMENT")
        recommend(s, world, rec_both, "EDU", 0.95, ScoreBand.HIGH)
        recommend(s, world, rec_both, "HEALTH", 0.62, ScoreBand.MEDIUM)
        edu_owned = make_case(s, pet="BIMAL SAIKIA")
        own.claim(s, a_edu, u_edu, edu_owned)
        health_rec_edu = make_case(s, pet="HEALTH WORKERS UNION")
        own.claim(s, a_health, u_health, health_rec_edu)
        recommend(s, world, health_rec_edu, "EDU", 0.88, ScoreBand.HIGH)
        survivor = make_case(s, pet="MERGED PARTY")
        merged = make_case(s, pet="MERGED PARTY", cnr="")
        merged.cnr, merged.is_provisional = None, True
        s.flush()
        merged.merged_into_case_id = survivor.id
        pool2 = make_case(s, pet="SUPPLEMENTARY PARTY")
        other = make_case(s, pet="COURT TWO PARTY")
        s.flush()
        out.cases.update(
            pool=pool.id,
            rec_both=rec_both.id,
            edu_owned=edu_owned.id,
            health_rec_edu=health_rec_edu.id,
            survivor=survivor.id,
            merged=merged.id,
            pool2=pool2.id,
            other=other.id,
        )

        def pdf(tag: str, d: date):
            doc, _ = cl_store.store_pdf(s, store, pdf_bytes(tag), doc_date=d, description=f"cause list {tag}")
            out.docs[tag] = doc.id
            return doc.id

        def make_list(key, d, bench_id, napix_id, lt, label, *, source=ListSource.NAPIX, with_pdf=True):
            row = Causelist(
                court_id=court.id,
                list_date=d,
                bench_id=bench_id,
                napix_causelist_id=napix_id,
                list_type=lt,
                list_type_text=lt.value.upper(),
                bench_label=label,
                source=source,
                document_id=pdf(key, d) if with_pdf else None,
                fetch_status=FetchStatus.FETCHED if with_pdf else FetchStatus.NOT_AVAILABLE,
                parse_status=ParseStatus.PARSED if with_pdf else ParseStatus.PENDING,
            )
            s.add(row)
            s.flush()
            out.lists[key] = row.id
            return row

        def entry(key, cl, sr, case, *, court_no, section=None, printed=None, **kw):
            e = CauselistEntry(
                causelist_id=cl.id,
                sr_no=sr,
                printed_sr_no=printed,
                court_no=court_no,
                bench_text=cl.bench_label,
                section=section,
                cnr=kw.pop("cnr", case.cnr if case is not None else None),
                case_id=case.id if case is not None else None,
                case_no_text=kw.pop("case_no_text", case.case_no_text if case is not None else None),
                petitioner_text=kw.pop("pet", case.petitioner_summary if case is not None else None),
                source=EntrySource.PDF_PARSE,
                resolution_status=ResolutionStatus.RESOLVED
                if case is not None
                else ResolutionStatus.UNRESOLVED,
                **kw,
            )
            s.add(e)
            s.flush()
            out.entries[key] = e.id
            return e

        daily = make_list("daily", D2, 1854, 11, ListType.DAILY, DIVISION_BENCH)
        entry(
            "e_pool",
            daily,
            1,
            pool,
            court_no="10",
            section="ORDERS",
            printed="1",
            respondent_text="STATE OF ASSAM",
            pet_advocate_text="MR. A. BORA",
            res_advocate_text="SC, REVENUE\nMS. R. DEKA",
            counsel_codes=["SC, REVENUE"],
        )
        entry("e_rec_both", daily, 2, rec_both, court_no="10", section="ORDERS", printed="2")
        entry(
            "e_connected",
            daily,
            3,
            edu_owned,
            court_no="10",
            section="ORDERS",
            is_connected=True,
            with_text="with WP(C) 2087/2025",
        )
        entry("e_health", daily, 4, health_rec_edu, court_no="10", section="FOR ADMISSION", printed="3")
        entry(
            "e_nocase",
            daily,
            5,
            None,
            court_no="10",
            section="FOR ADMISSION",
            printed="4",
            case_no_text="WP(C)/999/2026",
            pet="NO CASE PETITIONER",
        )
        entry("e_merged", daily, 6, merged, court_no="10", section="FOR ADMISSION", printed="5")
        supp = make_list("supp", D2, 1854, 12, ListType.SUPPLEMENTARY, DIVISION_BENCH, with_pdf=False)
        entry("e_supp", supp, 1, pool2, court_no="10", section="ORDERS", printed="1")
        lawazima = make_list("lawazima", D2, 2048, 13, ListType.LAWAZIMA, REGISTRAR_BENCH)
        entry("e_lawazima", lawazima, 1, pool, court_no="111", printed="1")
        court2 = make_list("court2", D2, 777, 14, ListType.DAILY, SINGLE_BENCH)
        entry("e_court2", court2, 1, other, court_no="2", section="ORDERS", printed="1")
        for bench_id, names in (
            (1854, DIVISION_BENCH),
            (2048, REGISTRAR_BENCH),
            (777, SINGLE_BENCH),
            (3000, SAT_ONLY),
        ):
            s.add(
                CauselistBenchDay(
                    court_id=court.id, list_date=D2, bench_id=bench_id, judge_names_as_listed=names
                )
            )
        prev = make_list("prev", D1, 1854, 21, ListType.DAILY, DIVISION_BENCH)
        entry("e_prev", prev, 1, pool, court_no="10", printed="1")
        website = make_list(
            "website", D3, None, None, ListType.DAILY, None, source=ListSource.GHC_WEBSITE, with_pdf=False
        )
        entry("e_website", website, 1, pool, court_no="5", printed="1")
        s.commit()
    return out
