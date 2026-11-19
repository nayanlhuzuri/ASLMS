"""The per-case readings of State Insights (design `state-insights`, "Tests", database, `test_insights_facts.py`): one
row per case never deleted, the State bases, the cause-title source, the department attribution and its re-derivation,
the IA's main case, the original writ, the subject of a contempt case, new categories, the dirty rules, the reader
version, idempotence and the job's counters. The scripted gateway is never called."""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from aslms.domain.cases import Case, CaseLink
from aslms.domain.courts import CaseType
from aslms.domain.documents import DocumentText
from aslms.domain.events import AuditLog
from aslms.domain.insights import (
    InsightCaseFact,
    InsightCaseTypeGroup,
    InsightGroup,
    InsightSubjectCategory,
    OfficeTitleName,
)
from aslms.domain.ops import JobRun
from aslms.domain.ownership import CounselCode
from aslms.services import insights, insights_facts, insights_groups, matching_rules
from aslms.services import insights_filters as F
from aslms.services import insights_rules as R
from aslms.services import insights_scope as sc
from aslms.services import order_sections as order_svc
from tests.db import insights_support as ins
from tests.db.report_support import claim


def test_build_one_row_per_case_never_deletes(world):
    with world.Session() as s:
        a = ins.case(s, respondents=("THE STATE OF ASSAM",))
        b = ins.case(s)
        ins.build(s, a, b)
        ins.build(s, a, b)
        assert s.scalar(sa.select(sa.func.count()).select_from(InsightCaseFact)) == 2
        b.merged_into_case_id = a.id
        s.flush()
        report = insights_facts.refresh(s)
        assert report.built == 0  # a merged case is never rebuilt
        assert s.scalar(sa.select(sa.func.count()).select_from(InsightCaseFact)) == 2  # and keeps its row
        s.rollback()


def test_state_bases_party_officer_counsel_title_writ(world):
    with world.Session() as s:
        party = ins.case(s, respondents=("THE STATE OF ASSAM AND 3 ORS",))
        officer = ins.case(s, respondents=("SRI A. B. SARMA, IAS",))
        counsel = ins.case(s, codes=("GA, ASSAM",))
        union = ins.case(s, codes=("SC, GAUHATI UNIVERSITY",))
        title = ins.case(s)
        ins.order_read(s, title, respondents="THE GOVERNMENT OF ASSAM, REP. BY THE SECRETARY")
        writ = ins.case(s, type_code=111, reg_no=4326, reg_year=2025, respondents=("THE STATE OF ASSAM",))
        contempt = ins.case(s, type_code=142, category=ins.CONTEMPT_CATEGORY)
        ins.order_read(s, contempt, respondents="SRI X", linked=["WP(C)/4326/2025"])
        f = ins.build(s, party, officer, counsel, union, title, writ, contempt)
        assert f[party.id].state_basis == ["party"]
        assert f[officer.id].state_basis == ["officer"]
        assert f[counsel.id].state_basis == ["counsel"] and f[counsel.id].government_codes == ["GA, ASSAM"]
        assert f[union.id].state_basis == [] and f[union.id].counsel_codes == ["SC, GAUHATI UNIVERSITY"]
        assert f[title.id].state_basis == ["title"]
        assert f[contempt.id].original_writ_case_id == writ.id
        assert f[contempt.id].state_basis == ["writ"]
        s.rollback()


def test_claimed_basis_live_not_stored(world):
    with world.Session() as s:
        c = ins.case(s)
        claim(s, world, c)
        f = ins.build(s, c)[c.id]
        assert f.state_basis == []
        scope = sc.resolve(s, world.user(s, "root"), "state", None)
        item = insights.case_items(s, [c.id], scope, F.InsightFilters(), today=datetime.now(UTC).date())[0]
        assert item["state_basis"] == ["claimed"] and item["state_case"] is True
        s.rollback()


def test_title_source_from_order_sections_else_parties(world):
    with world.Session() as s:
        c = ins.case(s, respondents=("THE SECRETARY, IRRIGATION DEPARTMENT",))
        order = ins.order_read(
            s, c, respondents="THE COMMISSIONER AND SECRETARY TO THE GOVT. OF ASSAM, FINANCE DEPARTMENT"
        )
        f = ins.build(s, c)[c.id]
        assert f.title_order_id == order.id
        assert f.title_phrases == ["FINANCE", "IRRIGATION"]
        assert (
            "principal_secretary" not in f.posts
            and "commissioner_secretary" in f.posts
            and "secretary" in f.posts
        )
        # a changed text is no reading: the title is not read, the party names still are
        dt = s.get(DocumentText, order.document_id)
        dt.full_text = dt.full_text + "\nchanged"
        s.flush()
        f = ins.build(s, c)[c.id]
        assert f.title_order_id is None and f.title_phrases == ["IRRIGATION"]
        s.rollback()


def test_named_departments_explicit_and_automatic(world):
    with world.Session() as s:
        edu = world.office(s, "EDU")
        health = world.office(s, "HEALTH")
        auto = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        explicit = ins.case(s, respondents=("THE DIRECTOR, SECONDARY EDUCATION DEPARTMENT",))
        actor, root = world.actor(s, "root")
        matching_rules.create_title_name(
            s, actor, root, office=world.office(s, "EDU-DSE"), phrase="secondary education"
        )
        other = ins.case(s, respondents=("THE SECRETARY, HEALTH DEPTT.",))
        f = ins.build(s, auto, explicit, other)
        assert f[auto.id].named_title_department_ids == [edu.id]
        assert f[explicit.id].named_title_department_ids == [
            edu.id
        ]  # the directorate counts for its department
        assert f[other.id].named_title_department_ids == [health.id]
        s.rollback()


def test_deactivated_title_name_rederived(world):
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        row = matching_rules.create_title_name(s, actor, root, office=world.office(s, "HEALTH"), phrase="PWD")
        c = ins.case(s, respondents=("THE CHIEF ENGINEER, PWD DEPARTMENT",))
        insights_facts.refresh(s)
        assert ins.fact(s, c).named_title_department_ids == [world.office(s, "HEALTH").id]
        matching_rules.set_title_name_active(s, actor, root, row, False)
        s.flush()
        assert insights_facts.attribution_dirty(s)
        report = insights_facts.refresh(s)
        assert report.built == 0 and report.rederived == 1
        assert ins.fact(s, c).named_title_department_ids == []
        assert not insights_facts.attribution_dirty(s)
        s.rollback()


def test_named_counsel_exact_active_non_generic_only(world):
    with world.Session() as s:
        edu = world.office(s, "EDU")
        s.add(CounselCode(code="SC, EDU", office_id=world.office(s, "EDU-SC").id))
        s.add(CounselCode(code="SC, GOA", office_id=world.office(s, "GOA").id, is_generic_state=True))
        s.add(
            CounselCode(code="SC, OLD", office_id=edu.id, is_active=False, deactivated_at=datetime.now(UTC))
        )
        s.flush()
        mapped = ins.case(s, codes=("sc,edu",))
        generic = ins.case(s, codes=("SC, GOA",))
        inactive = ins.case(s, codes=("SC, OLD",))
        partial = ins.case(s, codes=("SC, EDU (R-1), ASSAM",))
        f = ins.build(s, mapped, generic, inactive, partial)
        assert f[mapped.id].named_counsel_department_ids == [edu.id] and f[mapped.id].state_basis == [
            "counsel"
        ]
        assert f[generic.id].named_counsel_department_ids == [] and f[generic.id].state_basis == ["counsel"]
        assert f[inactive.id].named_counsel_department_ids == [] and f[inactive.id].state_basis == []
        assert f[partial.id].named_counsel_department_ids == []  # partial matches are never firm attribution
        s.rollback()


def test_department_ids_exist_in_offices(world):
    """The deviation's guard (decision 13): every stored department id is a Department-tier office."""
    with world.Session() as s:
        s.add(CounselCode(code="SC, HEALTH", office_id=world.office(s, "HEALTH").id))
        s.flush()
        cases = [
            ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",), codes=("SC, HEALTH",)),
            ins.case(s, respondents=("THE SECRETARY, HEALTH DEPARTMENT",)),
        ]
        ins.build(s, *cases)
        dangling = s.execute(
            sa.text(
                "SELECT count(*) FROM insight_case_facts f "
                "CROSS JOIN LATERAL unnest(f.named_title_department_ids || f.named_counsel_department_ids) d "
                "LEFT JOIN offices o ON o.id = d WHERE o.id IS NULL OR o.kind NOT IN ('department', 'central', "
                "'advocate_general') OR o.path NOT LIKE 'GOA/%' OR o.path LIKE 'GOA/%/%'"
            )
        ).scalar()
        assert dangling == 0
        s.rollback()


def test_ia_main_case_resolved_and_unresolved(world):
    with world.Session() as s:
        main = ins.case(s)
        ia = ins.case(s, type_code=220)
        lost = ins.case(s, type_code=220)
        ins.main_matter(s, ia, main)
        ins.main_matter(s, lost, None, text="WP(C)/77/2019")
        f = ins.build(s, ia, lost)
        assert f[ia.id].main_case_id == main.id and f[lost.id].main_case_id is None
        s.rollback()


def test_original_writ_resolved_only_when_held_never_in_case_links(world):
    with world.Session() as s:
        held = ins.case(s, reg_no=55, reg_year=2024)
        c1 = ins.case(s, type_code=142, category=ins.CONTEMPT_CATEGORY)
        ins.order_read(
            s, c1, respondents="SRI X", body="Heard. The order in WP(C) 55/2024 is not complied with.\n"
        )
        c2 = ins.case(s, type_code=142, category=ins.CONTEMPT_CATEGORY)
        ins.order_read(
            s, c2, respondents="SRI Y", body="Heard. The order in W.P.(C) No. 999 of 2023 is not complied.\n"
        )
        links_before = s.scalar(sa.select(sa.func.count()).select_from(CaseLink))
        f = ins.build(s, c1, c2)
        assert f[c1.id].original_writ_text == "WP(C) 55/2024" and f[c1.id].original_writ_case_id == held.id
        assert f[c2.id].original_writ_text == "WP(C) 999/2023" and f[c2.id].original_writ_case_id is None
        assert s.scalar(sa.select(sa.func.count()).select_from(CaseLink)) == links_before
        s.rollback()


def test_contempt_subject_from_writ(world):
    with world.Session() as s:
        writ = ins.case(s, reg_no=56, reg_year=2024, category="10039 - Retirement benefits. ( 1 )")
        c = ins.case(s, type_code=142, category=ins.CONTEMPT_CATEGORY)
        ins.order_read(s, c, respondents="SRI X", linked=["WP(C)/56/2024"])
        alone = ins.case(s, type_code=142, category=ins.CONTEMPT_CATEGORY)
        f = ins.build(s, writ, c, alone)
        assert f[c.id].category_code == 10200 and f[c.id].subject_category_code == 10039
        assert f[alone.id].subject_category_code == 10200 and f[alone.id].original_writ_text is None
        s.rollback()


def test_new_category_inserted_not_grouped(world):
    with world.Session() as s:
        c = ins.case(s, category="12345 - A category the court added later ( 1 )")
        ins.build(s, c)
        row = s.scalar(sa.select(InsightSubjectCategory).where(InsightSubjectCategory.category_code == 12345))
        assert row is not None and row.group_id is None and row.label == "A category the court added later"
        bad = ins.case(s, category="( 20240 )")
        assert ins.build(s, bad)[bad.id].category_code is None
        s.rollback()


def test_dirty_rules_each_trigger(world):
    """Each step commits, so the database clock moves as it does between the job's runs."""

    def dirty(case_id) -> bool:
        with world.Session() as s:
            return case_id in insights_facts.dirty_case_ids(s, 100)

    def refresh() -> None:
        with world.Session() as s:
            insights_facts.refresh(s)
            s.commit()

    with world.Session() as s:
        c = ins.case(s)
        s.commit()
    assert dirty(c.id)  # no row
    refresh()
    assert not dirty(c.id)
    with world.Session() as s:
        s.get(type(c), c.id).next_purpose = "HEARING"
        s.commit()
    assert dirty(c.id)  # the case changed
    refresh()
    assert not dirty(c.id)
    with world.Session() as s:
        ins.order_read(s, s.get(type(c), c.id))
        s.commit()
    assert dirty(c.id)  # a new order and its reading
    refresh()
    assert not dirty(c.id)
    from tests.db.report_support import listing

    with world.Session() as s:
        listing(s, s.get(type(c), c.id), datetime.now(UTC).date())
        s.commit()
    assert dirty(c.id)  # a new cause-list entry
    refresh()
    assert not dirty(c.id)


def test_reader_version_change_marks_all_dirty(world, monkeypatch):
    with world.Session() as s:
        cases = [ins.case(s) for _ in range(3)]
        insights_facts.refresh(s)
        assert insights_facts.dirty_case_ids(s, 100) == []
        monkeypatch.setattr(R, "READER_VERSION", "3")
        assert set(insights_facts.dirty_case_ids(s, 100)) == {c.id for c in cases}
        insights_facts.refresh(s)
        assert {ins.fact(s, c).reader_version for c in cases} == {"3"}
        s.rollback()


def test_rebuild_idempotent(world):
    with world.Session() as s:
        for _ in range(3):
            ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        s.commit()
    first = insights_facts.rebuild(world.Session, batch=2)
    with world.Session() as s:
        before = {
            r.case_id: (r.state_basis, r.named_title_department_ids, r.title_phrases)
            for r in s.scalars(sa.select(InsightCaseFact))
        }
    second = insights_facts.rebuild(world.Session, batch=2)
    with world.Session() as s:
        after = {
            r.case_id: (r.state_basis, r.named_title_department_ids, r.title_phrases)
            for r in s.scalars(sa.select(InsightCaseFact))
        }
    assert before == after and first.built == second.built == 3


def test_job_runs_counters(world):
    with world.Session() as s:
        ins.case(s, respondents=("THE SECRETARY, UNKNOWN THINGS DEPARTMENT",))
        report = insights_facts.refresh(s)
        run = s.scalar(
            sa.select(JobRun).where(JobRun.job == "insights-refresh").order_by(JobRun.started_at.desc())
        )
        assert run.status.value == "succeeded"
        for key in ("checked", "built", "new_categories", "rederived", "unmapped_phrases", "seconds"):
            assert key in run.counters, key
        assert run.counters["built"] == report.built == 1 and run.counters["unmapped_phrases"] == 1
        assert insights_facts.refresh_if_free(s) is not None  # the lock is the transaction's own
        status = insights_facts.status(s)
        assert (
            status["unmapped_phrases"] == 1
            and status["unmapped_phrase_cases"] == 1
            and status["waiting"] == 0
        )
        assert s.scalar(sa.select(sa.func.count()).select_from(OfficeTitleName)) == 0
        s.rollback()


# ------------------------------------------------------------------------------------------------ review advisories
# design state-insights-review-advisories: the watermark (decision 1), the rebuild's maps (decision 2) and the seed
# case-type lines (decision 5)


def _dirty(world, case_id) -> bool:
    with world.Session() as s:
        return case_id in insights_facts.dirty_case_ids(s, 100)


def _refresh(world) -> insights_facts.RunReport:
    with world.Session() as s:
        report = insights_facts.refresh(s)
        s.commit()
        return report


@contextmanager
def _open_writer(world):
    """A second connection under the application role whose transaction stays open (not committed) until the block
    ends, then commits."""
    conn = world.Session.kw["bind"].connect()
    trans = conn.begin()
    conn.execute(sa.text("SET LOCAL ROLE aslms_app"))
    s = Session(bind=conn)
    try:
        yield s
        s.flush()
        trans.commit()
    finally:
        s.close()
        conn.close()


def _committed_case(world, **kw):
    with world.Session() as s:
        c = ins.case(s, **kw)
        s.commit()
        return c


@pytest.mark.parametrize("change", ["case", "order", "reading", "listing"])
def test_change_in_transaction_open_during_build_is_dirty(world, change):
    """Advisory 1: a writer open while the build reads, committing after it, leaves its case dirty."""
    from tests.db import next_dates_support as nd
    from tests.db import order_sections_support as o
    from tests.db.report_support import listing

    c = _committed_case(world)
    order_id = None
    if change == "reading":
        with world.Session() as s:
            cc = s.get(Case, c.id)
            text_ = o.order_text(cnr=cc.cnr, case_no=cc.case_no_text, day="28.01.2026")
            order_id = nd.order_with_text(s, cc, text_, order_date=date(2026, 1, 28)).id
            s.commit()
    assert _dirty(world, c.id)  # no row yet: the refresh below builds the case while the writer is open
    with _open_writer(world) as w:
        if change == "case":
            w.get(Case, c.id).next_purpose = "HEARING"
        elif change == "order":
            ins.order_read(w, w.get(Case, c.id))
        elif change == "reading":
            order_svc.read_batch(w, order_id=order_id)
        else:
            listing(w, w.get(Case, c.id), datetime.now(UTC).date() + timedelta(days=3))
        w.flush()
        assert _refresh(world).built == 1  # the writer is still open: the build does not see its change
        assert not _dirty(world, c.id)  # not yet committed, so nothing newer than the row is visible
    assert _dirty(world, c.id), change
    assert _refresh(world).built == 1
    assert not _dirty(world, c.id)


def test_watermark_now_without_other_transactions(world):
    with world.Session() as s:
        assert insights_facts.watermark(s) == s.scalar(sa.select(sa.func.now()))
        s.rollback()


def test_watermark_before_oldest_open_transaction(world):
    with _open_writer(world) as w:
        started = w.scalar(sa.select(sa.func.now()))
        with world.Session() as s:
            mark = insights_facts.watermark(s)
            assert mark == started - timedelta(microseconds=1)
            assert mark < s.scalar(sa.select(sa.func.now()))
            s.rollback()
    with world.Session() as s:  # the writer gone, the mark is the build's own start again
        assert insights_facts.watermark(s) == s.scalar(sa.select(sa.func.now()))
        s.rollback()


def test_watermark_never_older_than_lookback(world):
    with _open_writer(world) as w:
        w.scalar(sa.select(sa.func.now()))
        time.sleep(1.2)
        with world.Session() as s:
            now = s.scalar(sa.select(sa.func.now()))
            assert insights_facts.watermark(s, lookback_minutes=0) == now  # 0 = the build's own start
            assert insights_facts.watermark(s, lookback_minutes=0.5 / 60) == now - timedelta(seconds=0.5)
            assert insights_facts.watermark(s, lookback_minutes=60) < now - timedelta(seconds=1)
            s.rollback()


def test_change_in_build_transaction_not_dirty(world):
    with world.Session() as s:
        c = ins.case(s)
        insights_facts.refresh(s)
        s.get(Case, c.id).next_purpose = "HEARING"
        s.flush()
        insights_facts.refresh(s)  # the change is seen by the build in the same transaction
        assert c.id not in insights_facts.dirty_case_ids(s, 100)
        s.commit()
    assert not _dirty(world, c.id)


def _tea_cases(world, n: int = 3) -> list:
    with world.Session() as s:
        cases = [ins.case(s, respondents=("THE SECRETARY, TEA TRIBES DEPARTMENT",)) for _ in range(n)]
        s.commit()
        return sorted(cases, key=lambda c: c.id)


def _map_tea(world, office: str) -> None:
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        row = s.scalar(sa.select(OfficeTitleName).where(OfficeTitleName.phrase == "TEA TRIBES"))
        if row is None:
            matching_rules.create_title_name(
                s, actor, root, office=world.office(s, office), phrase="TEA TRIBES"
            )
        else:
            matching_rules.update_title_name(s, actor, root, row, office=world.office(s, office))
        s.commit()


def test_rebuild_reloads_maps_between_batches(world, monkeypatch):
    cases = _tea_cases(world)
    calls = []

    def echo(msg):
        calls.append(msg)
        if len(calls) == 1:
            _map_tea(world, "HEALTH")

    # the end step's re-derivation is switched off, so the later rows can only name HEALTH through the reload
    monkeypatch.setattr(insights_facts, "rederive_departments", lambda s, maps=None: 0)
    insights_facts.rebuild(world.Session, batch=1, echo=echo)
    with world.Session() as s:
        health = world.office(s, "HEALTH").id
        names = [ins.fact(s, c).named_title_department_ids for c in cases]
        s.rollback()
    assert names[0] == [] and names[1:] == [[health], [health]]


def test_rebuild_rederives_when_fingerprint_moved(world):
    cases = _tea_cases(world)
    calls = []

    def echo(msg):
        calls.append(msg)
        if len(calls) == 1:  # a mapping changed and a refresh run between two batches
            _map_tea(world, "HEALTH")
            with world.Session() as s:
                assert insights_facts.refresh_if_free(s) is not None
                s.commit()
        if len(calls) == len(cases):  # and a change after the last batch, seen only by the end step
            _map_tea(world, "EDU")

    report = insights_facts.rebuild(world.Session, batch=1, echo=echo)
    assert report.rederived == len(cases)
    with world.Session() as s:
        edu = world.office(s, "EDU").id
        assert {tuple(ins.fact(s, c).named_title_department_ids) for c in cases} == {(edu,)}
        assert insights_facts.rederive_departments(s) == 0  # every row equals a fresh re-derivation
        # the fingerprint the rebuild records is the current one (true of every row it wrote)
        assert report.attribution_fingerprint == insights_facts.attribution_fingerprint(s)
        s.rollback()
    assert _refresh(world).rederived == 0  # a stale "last" fingerprint costs a pass that changes no row


def _case_type(s, code: int, short: str) -> CaseType:
    ct = CaseType(
        court_id=ins.court(s).id,
        case_type_code=code,
        type_name=f"{short} : {short}",
        short_name=short,
        full_name=short,
    )
    s.add(ct)
    s.flush()
    return ct


def _line_group(s, type_id) -> str | None:
    return s.scalar(
        sa.select(InsightGroup.code)
        .join(InsightCaseTypeGroup, InsightCaseTypeGroup.group_id == InsightGroup.id)
        .where(InsightCaseTypeGroup.case_type_id == type_id)
    )


def test_place_seed_case_types_after_masters_sync(world):
    with world.Session() as s:
        # the seed ran (init); `ins.case` runs it each time, so the cases come before the new types
        writ = ins.case(s, reg_no=57, reg_year=2024)
        c = ins.case(s, category=ins.CONTEMPT_CATEGORY)
        # then the court masters sync creates three seeded types
        cont = _case_type(s, 174, "Cont.Cas(Crl)").id
        bail = _case_type(s, 49, "Bail").id
        chosen = _case_type(s, 229, "Cont.App").id
        actor, root = world.actor(s, "root")
        insights_groups.set_case_types(s, actor, root, [(chosen, None)])  # a person chose Other
        audits = s.scalar(sa.select(sa.func.count()).select_from(AuditLog))
        c.case_type_id = cont
        s.flush()
        ins.order_read(s, c, respondents="SRI X", linked=["WP(C)/57/2024"])
        assert ins.build(s, writ, c)[c.id].original_writ_text is None  # read as Other: no contempt reading
        assert insights_groups.count_seed_case_types_missing(s) == 2
        s.commit()
    report = _refresh(world)
    assert report.case_type_lines == 2 and report.as_dict()["case_type_lines"] == 2
    with world.Session() as s:
        assert _line_group(s, cont) == "contempt" and _line_group(s, bail) == "bail"
        assert _line_group(s, chosen) == "other"  # a person's choice is untouched
        f = ins.fact(s, c)
        assert f.original_writ_text == "WP(C) 57/2024" and f.original_writ_case_id == writ.id
        assert s.scalar(sa.select(sa.func.count()).select_from(AuditLog)) == audits  # reference data
        s.rollback()
    assert _refresh(world).case_type_lines == 0


def test_case_type_line_change_marks_its_cases_dirty(world):
    c = _committed_case(world, type_code=112)
    other = _committed_case(world, type_code=111)
    _refresh(world)
    assert not _dirty(world, c.id) and not _dirty(world, other.id)
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        insights_groups.set_case_types(s, actor, root, [(s.get(Case, c.id).case_type_id, "review")])
        s.commit()
    assert _dirty(world, c.id) and not _dirty(world, other.id)
    _refresh(world)
    assert not _dirty(world, c.id)


def test_rebuild_counts_case_type_lines(world):
    with world.Session() as s:
        ins.case_types(s)
        _case_type(s, 174, "Cont.Cas(Crl)")
        s.commit()
    report = insights_facts.rebuild(world.Session, batch=10)
    assert report.case_type_lines == 1
    with world.Session() as s:
        assert insights_facts.status(s)["last_rebuild"]["counters"]["case_type_lines"] == 1
        s.rollback()


# ------------------------------------------------------------------------------------------------ the CLI


def _cli_scope(world):
    @contextmanager
    def scope():
        s = world.Session()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    return scope


def test_groups_check_reports_seedable_types(world, monkeypatch):
    from aslms.cli import insights as cli

    with world.Session() as s:
        ins.case_types(s)
        _case_type(s, 174, "Cont.Cas(Crl)")
        _case_type(s, 9999, "Unknown Type")
        s.commit()
    monkeypatch.setattr(cli, "session_scope", _cli_scope(world))
    r = CliRunner().invoke(cli.insights_app, ["groups", "check"])
    assert r.exit_code == 0, r.output
    assert "'case_types_seed_would_place': 1" in r.output and "'case_types_without_line': 2" in r.output
    assert "seed line to place: case type 174 (Cont.Cas(Crl)) in contempt" in r.output
    with world.Session() as s:  # read-only
        assert insights_groups.count_seed_case_types_missing(s) == 1
        s.rollback()


def test_refresh_dry_run_counts_case_type_lines(world, monkeypatch):
    from aslms.cli import insights as cli

    with world.Session() as s:
        ins.case_types(s)
        _case_type(s, 174, "Cont.Cas(Crl)")
        _case_type(s, 49, "Bail")
        s.commit()
        runs = s.scalar(sa.select(sa.func.count()).select_from(JobRun))
    monkeypatch.setattr(cli, "session_scope", _cli_scope(world))
    r = CliRunner().invoke(cli.insights_app, ["refresh", "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "'case_type_lines': 2" in r.output and "'dry_run': True" in r.output
    with world.Session() as s:  # nothing written
        assert insights_groups.count_seed_case_types_missing(s) == 2
        assert s.scalar(sa.select(sa.func.count()).select_from(JobRun)) == runs
        s.rollback()
