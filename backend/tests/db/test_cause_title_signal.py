"""The cause-title signal against the database (design `state-insights`, round 3, decisions 36 to 40): the engine reads
`insight_case_facts`, a possible match alone with the source and reason, never an ownership row, every guard kept
(claimed, dismissed), the Insights jobs marking the cases whose readings changed (a build and a mapping's
re-derivation) and the drain rescoring them, and the dry run counting new rows by signal kind while writing nothing.
Design `cause-title-signal-review-advisories`: no double counting end to end, a full rescore following a mapping saved
mid-run, the case lock before the evidence, the durable mark (kept, cleared only at the value read, left by a failed
rebuild, drained by the task), the drain's lock, cut-off and failures, the shown phrase, the first refresh after the
attribution version with `--no-rescore`, `named_withheld` and `named_rescore_waiting`. The scripted gateway is never
called."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa
import typer
from psycopg.errors import LockNotAvailable
from sqlalchemy.exc import OperationalError
from typer.testing import CliRunner

from aslms.domain.alerts import Alert
from aslms.domain.cases import Case, CaseParty, PartyRole
from aslms.domain.events import Event
from aslms.domain.insights import InsightCaseFact
from aslms.domain.ops import JobRun, SourceFailure
from aslms.domain.ownership import (
    CaseOfficeScore,
    CaseOwnership,
    OfficeKeyword,
    OfficeNamePattern,
    PatternKind,
    Recommendation,
    RecommendationOrigin,
    RecommendationStatus,
    ScoreBand,
)
from aslms.services import insights_facts, matching, matching_rules, ownership
from tests.db import insights_support as ins
from tests.db.report_support import claim


def _recs(s, case, status=RecommendationStatus.RECOMMENDED):
    return s.scalars(
        sa.select(Recommendation).where(Recommendation.case_id == case.id, Recommendation.status == status)
    ).all()


def _named(s, case, office):
    row = s.scalar(
        sa.select(CaseOfficeScore).where(
            CaseOfficeScore.case_id == case.id, CaseOfficeScore.office_id == office.id
        )
    )
    return row, [sig for sig in (row.signals if row else []) if sig["kind"] == "named_in_title"]


def _score(s, *cases):
    return matching.score_cases(s, [c.id for c in cases], origin=RecommendationOrigin.RESCORE)


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


def test_named_among_the_respondents_is_a_possible_match_and_never_an_owner(world):
    with world.Session() as s:
        edu = world.office(s, "EDU")
        c = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        ins.build(s, c)
        report = _score(s, c)
        assert report.recommended_new == 1
        (rec,) = _recs(s, c)
        assert rec.office_id == edu.id and rec.band == ScoreBand.MEDIUM and float(rec.score) == 0.6
        assert rec.actor_name == "matching"
        row, (sig,) = _named(s, c, edu)
        assert row.engine_version.startswith("3.")
        assert sig["source"] == "party" and sig["phrase"] == "EDUCATION" and "order_date" not in sig
        assert sig["reason"] == "Department named among the respondents: EDUCATION"
        assert (
            s.scalar(sa.select(sa.func.count()).select_from(CaseOwnership)) == 0
        )  # decision 39: never assigns
        s.rollback()


def test_named_in_the_cause_title_carries_the_order_date(world):
    with world.Session() as s:
        health = world.office(s, "HEALTH")
        c = ins.case(s)
        order = ins.order_read(
            s,
            c,
            respondents="THE COMMISSIONER AND SECRETARY TO THE GOVT. OF ASSAM, HEALTH DEPARTMENT",
            day=date(2026, 10, 12),
        )
        assert ins.build(s, c)[c.id].named_title_department_ids == [health.id]
        _score(s, c)
        _, (sig,) = _named(s, c, health)
        assert sig["source"] == "cause_title" and sig["order_date"] == "2026-10-12"
        assert sig["ref"] == {"order_id": str(order.id), "order_date": "2026-10-12"}
        assert sig["reason"] == "Department named in the cause title of the order of 12 Oct 2026: HEALTH"
        assert [r.office_id for r in _recs(s, c)] == [health.id]
        s.rollback()


def test_with_a_keyword_still_possible(world):
    with world.Session() as s:
        edu = world.office(s, "EDU")
        s.add(OfficeKeyword(office_id=edu.id, keyword="UNIVERSITY"))
        c = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT", "GAUHATI UNIVERSITY"))
        ins.build(s, c)
        _score(s, c)
        (rec,) = _recs(s, c)
        assert float(rec.score) == 0.76 and rec.band == ScoreBand.MEDIUM
        s.rollback()


def test_guards_kept_claimed_and_dismissed(world):
    with world.Session() as s:
        claimed = ins.case(s, respondents=("THE SECRETARY, HEALTH DEPARTMENT",))
        claim(s, world, claimed)  # EDU claims it
        dismissed = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        ins.build(s, claimed, dismissed)
        _score(s, dismissed)
        actor, user = world.actor(s, "edu_admin")
        ownership.dismiss(s, actor, user, dismissed, reason="not ours")
        _score(s, claimed, dismissed)
        assert _recs(s, claimed) == []  # a claimed case gets no engine recommendation
        assert _named(s, claimed, world.office(s, "HEALTH"))[1]  # its scores are still written
        assert _recs(s, dismissed) == []  # never re-recommended to the department that dismissed it
        assert len(_recs(s, dismissed, RecommendationStatus.DISMISSED)) == 1
        s.rollback()


def test_refresh_marks_the_cases_whose_readings_changed_and_the_drain_scores_them(world):
    with world.Session() as s:
        edu = world.office(s, "EDU")
        c = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        other = ins.case(s, respondents=("THE STATE OF ASSAM",))
        _score(s, c, other)  # scored before its readings exist: nothing
        assert _recs(s, c) == []
        report = insights_facts.refresh(s)
        s.commit()
        assert report.named_changed == 1 and report.as_dict()["named_changed"] == 1
        assert ins.fact(s, c).named_changed_at is not None and ins.fact(s, other).named_changed_at is None
        assert ins.fact(s, c).title_phrase_department_pos == [1]
    out = insights_facts.rescore_marked(world.Session)
    assert out.cases == 1 and out.recommended_new == 1
    with world.Session() as s:
        (rec,) = _recs(s, c)
        assert rec.office_id == edu.id and rec.origin == RecommendationOrigin.RESCORE
        assert ins.fact(s, c).named_changed_at is None  # the engine cleared the mark it scored
        # nothing waits and an unchanged build marks nothing
        assert insights_facts.refresh(s).named_changed == 0
        assert insights_facts.build(s, [c.id, other.id])["named_changed"] == 0
        assert ins.fact(s, c).named_changed_at is None
        s.rollback()
    assert insights_facts.rescore_marked(world.Session).cases == 0


def test_a_title_name_mapping_is_derived_again_then_rescored(world):
    with world.Session() as s:
        health = world.office(s, "HEALTH")
        c = ins.case(s, respondents=("THE DIRECTOR, MEDICAL SERVICES DEPARTMENT",))
        insights_facts.refresh(s)
        s.commit()
        actor, root = world.actor(s, "root")
        matching_rules.create_title_name(s, actor, root, office=health, phrase="medical services")
        s.commit()
        report = insights_facts.refresh(s)
        s.commit()
        assert report.rederived == 1 and report.named_changed == 1
        assert ins.fact(s, c).named_changed_at is not None
    insights_facts.rescore_marked(world.Session)
    with world.Session() as s:
        (rec,) = _recs(s, c)
        assert rec.office_id == health.id and rec.band == ScoreBand.MEDIUM
        _, (sig,) = _named(s, c, health)
        assert sig["phrase"] == "MEDICAL SERVICES"


def test_rebuild_rescores_marked_cases(world):
    with world.Session() as s:
        c = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        s.commit()
    report = insights_facts.rebuild(world.Session, batch=10)
    assert report.named_changed == 1 and report.rescored == 1
    assert report.as_dict()["rescored"] == 1
    with world.Session() as s:
        assert len(_recs(s, c)) == 1  # rescored after the rebuild committed
        assert ins.fact(s, c).named_changed_at is None
        run = s.scalar(
            sa.select(JobRun).where(JobRun.job == "insights-rebuild").order_by(JobRun.started_at.desc())
        )
        assert "rescored" not in run.counters  # the drain's count is not a stored counter
    again = insights_facts.rebuild(world.Session, batch=10)
    assert again.named_changed == 0 and again.rescored == 0


def test_dry_run_counts_new_rows_by_kind_and_writes_nothing(world):
    with world.Session() as s:
        edu = world.office(s, "EDU")
        s.add(OfficeKeyword(office_id=edu.id, keyword="UNIVERSITY"))
        alone = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        with_kw = ins.case(s, respondents=("THE SECRETARY, HEALTH DEPARTMENT", "GAUHATI UNIVERSITY"))
        claimed = ins.case(s, respondents=("THE SECRETARY, HEALTH DEPARTMENT",))
        claim(s, world, claimed)
        ins.build(s, alone, with_kw, claimed)
        s.commit()
        counts = (
            s.scalar(sa.select(sa.func.count()).select_from(Recommendation)),
            s.scalar(sa.select(sa.func.count()).select_from(CaseOfficeScore)),
            s.scalar(sa.select(sa.func.count()).select_from(Event)),
        )
    report = matching.dry_run_all(world.Session, batch=2)
    d = report.as_dict()
    assert d["cases"] == 3 and d["claimed_cases"] == 1 and d["failed"] == 0
    # alone: EDU 0.600; with_kw: HEALTH 0.600 and EDU keyword 0.400 (no band)
    assert d["new"] == {"medium": 2}
    assert d["new_by_kind"] == {"medium": {"named_in_title": 2}}
    assert d["new_only_with_named"] == {"medium": 2}
    assert d["engine_version"].startswith("3.")
    with world.Session() as s:
        assert (
            s.scalar(sa.select(sa.func.count()).select_from(Recommendation)),
            s.scalar(sa.select(sa.func.count()).select_from(CaseOfficeScore)),
            s.scalar(sa.select(sa.func.count()).select_from(Event)),
        ) == counts
    one = matching.dry_run_all(world.Session, case_ids=[alone.id]).as_dict()
    assert one["cases"] == 1 and one["new"] == {"medium": 1}


def test_dry_run_counts_band_changes_and_expiry(world):
    with world.Session() as s:
        edu = world.office(s, "EDU")
        s.add(OfficeKeyword(office_id=edu.id, keyword="UNIVERSITY", weight=0.8))
        college = OfficeKeyword(office_id=edu.id, keyword="COLLEGE", weight=0.6)
        s.add(college)
        c = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT", "GAUHATI UNIVERSITY"))
        gone = ins.case(s, respondents=("COTTON COLLEGE",))
        s.flush()
        _score(s, c, gone)  # before the readings: 0.800 and 0.600, both medium
        assert [r.band for r in _recs(s, c)] == [ScoreBand.MEDIUM]
        ins.build(s, c, gone)
        college.is_active, college.deactivated_at = False, sa.func.now()
        s.commit()
    d = matching.dry_run_all(world.Session).as_dict()
    # c: 0.800 with the cause title 0.600 gives 0.920, high only with the signal; gone: nothing left, it expires
    assert d["band_changed"] == {"medium->high": 1} and d["band_changed_by_named"] == 1
    assert d["expired"] == 1 and d["new"] == {}


def test_cli_rescore_dry_run(world, monkeypatch):
    from aslms.cli import matching as cli

    with world.Session() as s:
        c = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        ins.build(s, c)
        s.commit()
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: world.Session)
    app = typer.Typer()
    app.command()(cli.rescore)
    r = CliRunner().invoke(app, ["--all", "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "nothing written" in r.output and "'named_in_title': 1" in r.output
    with world.Session() as s:
        assert _recs(s, c) == []


# ------------------------------------------------------------------ design cause-title-signal-review-advisories
# no double counting (decisions 1 to 4), the fact row as the only source (5 to 7), the durable mark and the drain (8 to
# 12), the first refresh after the deploy (13)

FIN_LIKE = "COMMISSIONER AND SECRETARY, EDUCATION DEPARTMENT"


def _pattern(s, office, text):
    s.add(OfficeNamePattern(office_id=office.id, pattern=text, kind=PatternKind.REGEX))
    s.flush()


def _mark(s, c):
    return s.scalar(
        sa.select(InsightCaseFact.named_changed_at)
        .where(InsightCaseFact.case_id == c.id)
        .execution_options(populate_existing=True)
    )


def test_double_counting_stops_end_to_end(world):
    with world.Session() as s:
        edu = world.office(s, "EDU")
        _pattern(s, edu, "EDUCATION DEPARTMENT")
        c = ins.case(s, respondents=(FIN_LIKE,))
        assert ins.build(s, c)[c.id].named_title_department_ids == [edu.id]
        _score(s, c)
        (rec,) = _recs(s, c)
        assert float(rec.score) == 0.8 and rec.band == ScoreBand.MEDIUM  # not 0.920, strong
        row, named = _named(s, c, edu)
        assert named == [] and [sig["kind"] for sig in row.signals] == ["name_pattern"]
        events = s.scalars(
            sa.select(Event).where(Event.case_id == c.id, Event.type == "recommendation_made")
        ).all()
        assert [e.payload["band"] for e in events] == ["medium"]
        assert s.scalar(sa.select(sa.func.count()).select_from(Alert)) == 0
        assert s.scalar(sa.select(sa.func.count()).select_from(CaseOwnership)) == 0
        s.rollback()


def test_full_rescore_follows_a_title_name_saved_mid_run(world, monkeypatch):
    with world.Session() as s:
        health = world.office(s, "HEALTH")
        ins.case(s, respondents=("RAM DAS",))
        target = ins.case(s, respondents=("THE DIRECTOR, MEDICAL SERVICES DEPARTMENT",))
        insights_facts.refresh(s)
        s.commit()
        last_id = s.scalar(sa.select(Case.id).order_by(Case.id.desc()).limit(1))
        assert last_id == target.id  # the target is scored in the last batch
    real = matching.score_cases
    state = {"saved": False}

    def hooked(session, case_ids, **kw):
        out = real(session, case_ids, **kw)
        if not state["saved"]:
            state["saved"] = True
            session.commit()  # the batch commits, then a mapping is saved, the readings follow and the drain runs
            with world.Session() as s2:
                actor, root = world.actor(s2, "root")
                matching_rules.create_title_name(s2, actor, root, office=health, phrase="medical services")
                s2.commit()
                assert insights_facts.refresh(s2).named_changed == 1
                s2.commit()
            insights_facts.rescore_marked(world.Session)
        return out

    monkeypatch.setattr(matching, "score_cases", hooked)
    matching.rescore_all(world.Session, batch=1)
    assert state["saved"]
    with world.Session() as s:
        row, (sig,) = _named(s, target, health)
        assert sig["phrase"] == "MEDICAL SERVICES" and row.engine_version.startswith("3.")
        assert _mark(s, target) is None


def test_engine_locks_the_case_before_reading_evidence(world, monkeypatch):
    with world.Session() as s:
        c = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        ins.build(s, c)
        s.commit()
    real = matching.CaseEvidence.gather.__func__
    seen: list[str] = []

    def probe(cls, session, case):
        with world.Session() as other:
            try:
                other.execute(
                    sa.text("SELECT id FROM cases WHERE id = :id FOR UPDATE NOWAIT"), {"id": case.id}
                )
                seen.append("free")
            except OperationalError as exc:
                assert isinstance(exc.orig, LockNotAvailable)
                seen.append("locked")
            other.rollback()
        return real(cls, session, case)

    monkeypatch.setattr(matching.CaseEvidence, "gather", classmethod(probe))
    with world.Session() as s:
        report = _score(s, c)
        s.commit()
    assert seen == ["locked"] and report.cases == 1


def test_build_marks_changed_rows_only_and_keeps_a_pending_mark(world):
    with world.Session() as s:
        c = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        d = ins.case(s, respondents=("THE STATE OF ASSAM",))
        assert insights_facts.build(s, [c.id, d.id])["named_changed"] == 1
        first = _mark(s, c)
        assert first is not None and _mark(s, d) is None
        # an unrelated rebuild never clears the pending mark
        assert insights_facts.build(s, [c.id, d.id])["named_changed"] == 0
        assert _mark(s, c) == first and _mark(s, d) is None
        # a new respondent naming another department: the row changes and is marked again
        s.add(
            CaseParty(
                case_id=c.id,
                role=PartyRole.RESPONDENT,
                party_no=2,
                name="THE SECRETARY, HEALTH DEPARTMENT",
                name_normalised="THE SECRETARY, HEALTH DEPARTMENT",
            )
        )
        s.flush()
        assert insights_facts.build(s, [c.id])["named_changed"] == 1
        assert _mark(s, c) > first
        assert ins.fact(s, c).title_phrase_department_pos == [1, 2]
        s.rollback()


def test_failed_rebuild_leaves_marks_that_the_next_refresh_task_drains(world, monkeypatch):
    from aslms.jobs import celery_app

    with world.Session() as s:
        a = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        b = ins.case(s, respondents=("THE SECRETARY, HEALTH DEPARTMENT",))
        s.commit()
    real = insights_facts.build
    calls = {"n": 0}

    def failing(session, case_ids, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("batch 2 failed")
        return real(session, case_ids, **kw)

    monkeypatch.setattr(insights_facts, "build", failing)
    with pytest.raises(RuntimeError):
        insights_facts.rebuild(world.Session, batch=1)
    monkeypatch.setattr(insights_facts, "build", real)
    with world.Session() as s:
        assert _mark(s, a) is not None and ins.facts(s, b) == {}  # batch 1 committed with its mark
        assert _recs(s, a) == []  # nothing rescored after the failure
        s.rollback()
    monkeypatch.setattr(celery_app, "session_scope", _cli_scope(world))
    monkeypatch.setattr(celery_app, "get_sessionmaker", lambda: world.Session)
    out = celery_app.insights_refresh()
    assert out["rescored"] == 2  # batch 1's row and b, built by this refresh
    with world.Session() as s:
        assert len(_recs(s, a)) == 1 and len(_recs(s, b)) == 1
        assert _mark(s, a) is None and _mark(s, b) is None
        s.rollback()


def test_refresh_task_drains_when_another_refresh_holds_the_lock(world, monkeypatch):
    from aslms.jobs import celery_app

    with world.Session() as s:
        c = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        ins.build(s, c)
        s.commit()
    monkeypatch.setattr(celery_app, "session_scope", _cli_scope(world))
    monkeypatch.setattr(celery_app, "get_sessionmaker", lambda: world.Session)
    with world.Session() as holder:
        holder.execute(sa.select(sa.func.pg_advisory_xact_lock(insights_facts.REFRESH_LOCK)))
        assert celery_app.insights_refresh() is None
        holder.rollback()
    with world.Session() as s:
        assert len(_recs(s, c)) == 1 and _mark(s, c) is None
        s.rollback()


def test_mark_written_after_the_gather_survives_the_clear(world, monkeypatch):
    with world.Session() as s:
        c = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        ins.build(s, c)
        s.commit()
        first = _mark(s, c)
    real = matching.CaseEvidence.gather.__func__

    def remark(cls, session, case):
        ev = real(cls, session, case)
        assert ev.fact_marker == first
        with world.Session() as other:  # a refresh marks the row again after the read
            other.execute(
                sa.text(
                    "UPDATE insight_case_facts SET named_changed_at = clock_timestamp() WHERE case_id = :id"
                ),
                {"id": case.id},
            )
            other.commit()
        return ev

    monkeypatch.setattr(matching.CaseEvidence, "gather", classmethod(remark))
    with world.Session() as s:
        _score(s, c)
        s.commit()
    monkeypatch.undo()
    with world.Session() as s:
        second = _mark(s, c)
        assert second is not None and second > first
        s.rollback()
    assert insights_facts.rescore_marked(world.Session).cases == 1
    with world.Session() as s:
        assert _mark(s, c) is None
        s.rollback()


def test_drain_clears_a_failing_case_and_records_the_failure(world, monkeypatch):
    with world.Session() as s:
        bad = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        good = ins.case(s, respondents=("THE SECRETARY, HEALTH DEPARTMENT",))
        ins.build(s, bad, good)
        s.commit()
        bad_ref = bad.ref_no
    real = matching.apply_scores

    def apply(session, case, scores, **kw):
        if case.id == bad.id:
            raise RuntimeError("scoring broke")
        return real(session, case, scores, **kw)

    monkeypatch.setattr(matching, "apply_scores", apply)
    report = insights_facts.rescore_marked(world.Session)
    assert report.cases == 1 and report.failed == 1 and report.failed_case_ids == [bad.id]
    assert "failed_case_ids" not in report.as_dict()
    with world.Session() as s:
        assert _mark(s, bad) is None and _mark(s, good) is None  # a broken case cannot loop
        failure = s.scalar(sa.select(SourceFailure).where(SourceFailure.kind == "scoring"))
        assert failure is not None and failure.ref == bad_ref
        s.rollback()
    assert insights_facts.rescore_marked(world.Session).cases == 0


def test_second_drain_stops_at_the_lock(world):
    with world.Session() as s:
        c = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        ins.build(s, c)
        s.commit()
    with world.Session() as holder:
        holder.execute(sa.select(sa.func.pg_advisory_xact_lock(insights_facts.RESCORE_MARKED_LOCK)))
        report = insights_facts.rescore_marked(world.Session)
        assert report.cases == 0
        holder.rollback()
    with world.Session() as s:
        assert _mark(s, c) is not None and _recs(s, c) == []
        s.rollback()
    assert insights_facts.rescore_marked(world.Session).cases == 1


def test_drain_takes_marks_up_to_its_start_only(world):
    with world.Session() as s:
        now_case = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        later = ins.case(s, respondents=("THE SECRETARY, HEALTH DEPARTMENT",))
        ins.build(s, now_case, later)
        s.execute(
            sa.text(
                "UPDATE insight_case_facts SET named_changed_at = clock_timestamp() + interval '1 hour' "
                "WHERE case_id = :id"
            ),
            {"id": later.id},
        )
        s.commit()
        early = _mark(s, now_case)
    assert insights_facts.rescore_marked(world.Session).cases == 1
    with world.Session() as s:
        assert _mark(s, now_case) is None and _mark(s, later) is not None
        assert _recs(s, later) == []
        s.rollback()
    # `stop_at` before the mark leaves it too; after it, the drain takes it
    assert insights_facts.rescore_marked(world.Session, stop_at=early).cases == 0
    late = datetime.now(UTC) + timedelta(hours=2)
    assert insights_facts.rescore_marked(world.Session, stop_at=late).cases == 1


def test_rederive_marks_a_case_when_only_the_shown_phrase_changes(world):
    with world.Session() as s:
        health = world.office(s, "HEALTH")
        c = ins.case(
            s, respondents=("THE DIRECTOR, MEDICAL SERVICES DEPARTMENT", "THE SECRETARY, HEALTH DEPARTMENT")
        )
        insights_facts.refresh(s)
        s.commit()
        fact = ins.fact(s, c)
        assert fact.title_phrases == ["MEDICAL SERVICES", "HEALTH"] and fact.title_phrase_department_pos == [
            0,
            1,
        ]
    insights_facts.rescore_marked(world.Session)
    with world.Session() as s:
        assert _named(s, c, health)[1][0]["phrase"] == "HEALTH"
        actor, root = world.actor(s, "root")
        matching_rules.create_title_name(s, actor, root, office=health, phrase="medical services")
        s.commit()
        report = insights_facts.refresh(s)
        s.commit()
        fact = ins.fact(s, c)
        # the same departments, a new position: the row is written and marked
        assert fact.named_title_department_ids == [health.id] and fact.title_phrase_department_pos == [1, 1]
        assert report.rederived == 1 and report.named_changed == 1 and fact.named_changed_at is not None
    assert insights_facts.rescore_marked(world.Session).cases == 1
    with world.Session() as s:
        (sig,) = _named(s, c, health)[1]
        assert sig["phrase"] == "MEDICAL SERVICES"


def test_first_refresh_after_the_attribution_version_derives_every_row(world, monkeypatch):
    from aslms.cli import insights as cli

    with world.Session() as s:
        c = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        plain = ins.case(s, respondents=("RAM DAS",))
        insights_facts.refresh(s)
        # the rows as 0041 leaves them: no positions, no mark
        s.execute(
            sa.text(
                "UPDATE insight_case_facts SET title_phrase_department_pos = '{}', named_changed_at = NULL"
            )
        )
        s.commit()
        assert not insights_facts.attribution_dirty(s)
        s.commit()
    monkeypatch.setattr(insights_facts, "ATTRIBUTION_VERSION", "test-next")
    monkeypatch.setattr(cli, "session_scope", _cli_scope(world))
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: world.Session)
    r = CliRunner().invoke(cli.insights_app, ["refresh", "--no-rescore"])
    assert r.exit_code == 0, r.output
    assert "'rederived': 1" in r.output and "'named_changed': 1" in r.output
    assert "marked for rescoring: 1; a full rescore or the next insights-refresh run scores" in " ".join(
        r.output.split()
    )
    assert "rescored" not in r.output
    with world.Session() as s:
        assert ins.fact(s, c).title_phrase_department_pos == [1] and _mark(s, c) is not None
        assert ins.fact(s, plain).title_phrase_department_pos == [] and _mark(s, plain) is None
        assert s.scalar(sa.select(sa.func.count()).select_from(CaseOfficeScore)) == 0  # nothing scored
        assert insights_facts.status(s)["named_rescore_waiting"] == 1
        s.commit()
    # without --no-rescore the CLI drains
    r = CliRunner().invoke(cli.insights_app, ["refresh"])
    assert r.exit_code == 0, r.output
    assert "'rescored': 1" in r.output
    with world.Session() as s:
        assert _mark(s, c) is None and len(_recs(s, c)) == 1
        s.rollback()


def test_dry_run_reports_named_withheld_and_writes_nothing(world):
    with world.Session() as s:
        edu = world.office(s, "EDU")
        _pattern(s, edu, "EDUCATION DEPARTMENT")
        same = ins.case(s, respondents=(FIN_LIKE,))
        alone = ins.case(s, respondents=("THE SECRETARY, HEALTH DEPARTMENT",))
        ins.build(s, same, alone)
        s.commit()
        counts = (
            s.scalar(sa.select(sa.func.count()).select_from(Recommendation)),
            s.scalar(sa.select(sa.func.count()).select_from(CaseOfficeScore)),
            s.scalar(sa.select(sa.func.count()).select_from(Event)),
        )
        marks = (_mark(s, same), _mark(s, alone))
    d = matching.dry_run_all(world.Session).as_dict()
    assert d["named_withheld"] == 1
    assert d["new"] == {"medium": 2}
    assert d["new_by_kind"] == {"medium": {"name_pattern": 1, "named_in_title": 1}}
    with world.Session() as s:
        assert (
            s.scalar(sa.select(sa.func.count()).select_from(Recommendation)),
            s.scalar(sa.select(sa.func.count()).select_from(CaseOfficeScore)),
            s.scalar(sa.select(sa.func.count()).select_from(Event)),
        ) == counts
        assert (_mark(s, same), _mark(s, alone)) == marks  # the dry run clears no mark
        s.rollback()


def test_status_counts_named_rescore_waiting(world):
    with world.Session() as s:
        c = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        ins.case(s, respondents=("RAM DAS",))
        insights_facts.refresh(s)
        s.commit()
        assert insights_facts.status(s)["named_rescore_waiting"] == 1
        assert insights_facts.marked_count(s) == 1
        s.commit()
    insights_facts.rescore_marked(world.Session)
    with world.Session() as s:
        assert insights_facts.status(s)["named_rescore_waiting"] == 0
        assert _mark(s, c) is None
        s.rollback()
