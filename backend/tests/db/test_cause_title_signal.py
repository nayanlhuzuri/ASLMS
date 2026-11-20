"""The cause-title signal against the database (design `state-insights`, round 3, decisions 36 to 40): the engine reads
`insight_case_facts`, a possible match alone with the source and reason, never an ownership row, every guard kept
(claimed, dismissed), the Insights jobs rescoring the cases whose readings changed (a build and a mapping's
re-derivation), and the dry run counting new rows by signal kind while writing nothing. The scripted gateway is never
called."""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa
import typer
from typer.testing import CliRunner

from aslms.domain.events import Event
from aslms.domain.ownership import (
    CaseOfficeScore,
    CaseOwnership,
    OfficeKeyword,
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


def test_refresh_rescores_the_cases_whose_readings_changed(world):
    with world.Session() as s:
        edu = world.office(s, "EDU")
        c = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        other = ins.case(s, respondents=("THE STATE OF ASSAM",))
        _score(s, c, other)  # scored before its readings exist: nothing
        assert _recs(s, c) == []
        report = insights_facts.refresh(s)
        s.commit()
        assert report.named_changed_ids == [c.id] and report.as_dict()["named_changed"] == 1
        out = insights_facts.rescore_changed(world.Session, report.named_changed_ids)
        assert out.cases == 1 and out.recommended_new == 1
    with world.Session() as s:
        (rec,) = _recs(s, c)
        assert rec.office_id == edu.id and rec.origin == RecommendationOrigin.RESCORE
        # nothing waits and an unchanged build lists nothing
        assert insights_facts.refresh(s).named_changed_ids == []
        assert insights_facts.build(s, [c.id, other.id])["named_changed"] == []
        s.rollback()


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
        assert report.rederived == 1 and report.named_changed_ids == [c.id]
        insights_facts.rescore_changed(world.Session, report.named_changed_ids)
    with world.Session() as s:
        (rec,) = _recs(s, c)
        assert rec.office_id == health.id and rec.band == ScoreBand.MEDIUM
        _, (sig,) = _named(s, c, health)
        assert sig["phrase"] == "MEDICAL SERVICES"


def test_rebuild_rescores_changed_cases(world):
    with world.Session() as s:
        c = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        s.commit()
    report = insights_facts.rebuild(world.Session, batch=10)
    assert report.named_changed_ids == [c.id]
    with world.Session() as s:
        assert len(_recs(s, c)) == 1  # rescored after the rebuild committed
    assert insights_facts.rebuild(world.Session, batch=10).named_changed_ids == []


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
