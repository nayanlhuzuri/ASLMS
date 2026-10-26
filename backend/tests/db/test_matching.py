"""The matching engine against the database: inline scoring from a cause list and a dossier, idempotence, the
pool for weak cases, failures recorded in `source_failures`, the batch and dirty rescore, the never-again rule,
the linked-case signal and the unmapped-codes report."""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa

from aslms.domain.cases import AdvocateSide, CaseAdvocate, CaseLink, LinkKind
from aslms.domain.causelists import Causelist, ListSource, ListType
from aslms.domain.courts import Court
from aslms.domain.events import Event
from aslms.domain.ops import JobRun, SourceFailure
from aslms.domain.ownership import (
    CaseOfficeScore,
    CounselCode,
    OfficeKeyword,
    OfficeNamePattern,
    PatternKind,
    Recommendation,
    RecommendationOrigin,
    RecommendationStatus,
    ScoreBand,
)
from aslms.domain.reference import EventType
from aslms.parsing.causelist_pdf import Entry, ParsedCauseList
from aslms.services import matching, matching_rules, ownership
from aslms.services.cases import apply_dossier
from aslms.services.causelists import DayReport, apply_entries
from tests.db.world import make_case


def entry(seq, cnr, case_no, *, codes=(), pet="RAM KUMAR", res="THE STATE OF ASSAM") -> Entry:
    return Entry(
        seq=seq,
        printed_sr_no=str(seq),
        case_no_text=case_no,
        cnr=cnr,
        page=1,
        court_no="1",
        bench_text="HON'BLE JUSTICE X",
        section="ADMISSION",
        is_connected=False,
        parent_case_no=None,
        is_filing_number=False,
        remarks=None,
        petitioner_text=pet,
        respondent_text=res,
        pet_advocate_text=None,
        res_advocate_text=None,
        pet_advocates=[],
        res_advocates=[],
        pet_counsel_codes=[],
        res_counsel_codes=list(codes),
        raw_lines=[],
    )


def load_list(s, entries, list_date=date(2025, 1, 6)):
    court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
    cl = s.scalar(
        sa.select(Causelist).where(
            Causelist.list_date == list_date, Causelist.source == ListSource.GHC_WEBSITE
        )
    )
    if cl is None:
        cl = Causelist(
            court_id=court.id, list_date=list_date, list_type=ListType.DAILY, source=ListSource.GHC_WEBSITE
        )
        s.add(cl)
        s.flush()
    parsed = ParsedCauseList("daily", "DAILY", list_date, 1, [], entries, [])
    apply_entries(s, court, cl, parsed, report=DayReport(list_date))
    return cl


def recs(s, case_id=None):
    stmt = sa.select(Recommendation)
    if case_id is not None:
        stmt = stmt.where(Recommendation.case_id == case_id)
    return s.scalars(stmt).all()


def made_events(s):
    return s.scalars(sa.select(Event).where(Event.type == EventType.RECOMMENDATION_MADE)).all()


def test_cause_list_scores_and_recommends_idempotently(world):
    with world.Session() as s:
        s.add(CounselCode(code="SC, EDU", office_id=world.offices["EDU"].id))
        s.add(CounselCode(code="GA, ASSAM", office_id=world.offices["GOA"].id, is_generic_state=True))
        s.flush()
        load_list(s, [entry(1, "ASHC010000012025", "WP(C)/1/2025", codes=["SC,EDU", "GA, ASSAM"])])
        s.commit()
        (rec,) = recs(s)
        assert rec.office_id == world.offices["EDU"].id and rec.band == ScoreBand.HIGH
        assert rec.origin == RecommendationOrigin.CAUSE_LIST and rec.actor_name == "matching"
        score = s.scalar(sa.select(CaseOfficeScore).where(CaseOfficeScore.case_id == rec.case_id))
        assert float(score.score) == 0.95 and score.engine_version == "2.1"
        assert score.signals[0]["ref"] == {"list_date": "2025-01-06", "sr_no": 1}
        assert len(made_events(s)) == 1
        load_list(s, [entry(1, "ASHC010000012025", "WP(C)/1/2025", codes=["SC,EDU", "GA, ASSAM"])])
        s.commit()
        assert len(recs(s)) == 1 and len(made_events(s)) == 1
        assert s.scalar(sa.select(sa.func.count()).select_from(CaseOfficeScore)) == 1


def test_keyword_only_case_stays_in_the_pool(world):
    with world.Session() as s:
        s.add(OfficeKeyword(keyword="EDUCATION", office_id=world.offices["EDU"].id))
        s.flush()
        load_list(s, [entry(1, "ASHC010000022025", "WP(C)/2/2025", res="DIRECTOR OF EDUCATION")])
        s.commit()
        assert float(s.scalar(sa.select(CaseOfficeScore.score))) == 0.4
        assert recs(s) == []


def test_dossier_name_pattern_alone_and_with_keyword(world):
    with world.Session() as s:
        s.add(
            OfficeNamePattern(
                pattern="THE DIRECTOR OF SECONDARY EDUCATION",
                kind=PatternKind.EXACT,
                office_id=world.offices["EDU"].id,
            )
        )
        case = make_case(s, cnr="ASHC010000032025")
        apply_dossier(
            s, case, {"cino": "ASHC010000032025", "res_name": "The Director of Secondary Education"}
        )
        s.commit()
        (rec,) = recs(s, case.id)
        assert float(rec.score) == 0.8 and rec.band == ScoreBand.MEDIUM
        s.add(OfficeKeyword(keyword="SECONDARY EDUCATION", office_id=world.offices["EDU"].id))
        s.flush()
        apply_dossier(
            s, case, {"cino": "ASHC010000032025", "res_name": "The Director of Secondary Education"}
        )
        s.commit()
        (rec,) = recs(s, case.id)
        assert float(rec.score) == 0.88 and rec.band == ScoreBand.HIGH


def test_scoring_failure_is_recorded_and_the_list_commits(world, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("engine broke")

    monkeypatch.setattr(matching, "score_case", boom)
    with world.Session() as s:
        load_list(s, [entry(1, "ASHC010000042025", "WP(C)/4/2025")])
        s.commit()
        failure = s.scalar(sa.select(SourceFailure).where(SourceFailure.kind == "scoring"))
        assert failure is not None and "engine broke" in failure.error
        assert s.scalar(sa.text("select count(*) from causelist_entries")) == 1


def _code_case(world, s):
    s.add(CounselCode(code="SC, EDU", office_id=world.offices["EDU"].id))
    case = make_case(s)
    s.add(
        CaseAdvocate(
            case_id=case.id, side=AdvocateSide.RESPONDENT, name_as_listed="SC, EDU", counsel_code="SC, EDU"
        )
    )
    s.flush()
    matching.score_cases(s, [case.id], origin=RecommendationOrigin.CAUSE_LIST)
    return case


def test_rescore_all_expires_and_deletes(world):
    with world.Session() as s:
        case = _code_case(world, s)
        s.add(
            Recommendation(
                case_id=case.id,
                office_id=world.offices["HEALTH"].id,
                score=0,
                band=ScoreBand.MEDIUM,
                origin=RecommendationOrigin.SUGGESTION,
            )
        )
        s.commit()
        actor, admin = world.actor(s, "edu_admin")
        code = s.scalar(sa.select(CounselCode))
        matching_rules.set_counsel_code_active(s, actor, admin, code, False)
        s.commit()
    report = matching.rescore_all(world.Session)
    assert report.expired == 1 and report.cases >= 1
    with world.Session() as s:
        by_origin = {r.origin: r.status for r in recs(s, case.id)}
        assert by_origin == {
            RecommendationOrigin.CAUSE_LIST: RecommendationStatus.EXPIRED,
            RecommendationOrigin.SUGGESTION: RecommendationStatus.RECOMMENDED,
        }
        assert s.scalar(sa.select(sa.func.count()).select_from(CaseOfficeScore)) == 0
        run = s.scalar(sa.select(JobRun).where(JobRun.job == "rescore"))
        assert run.status.value == "succeeded" and run.counters["expired"] == 1


def test_rescore_if_dirty_follows_rule_edits(world):
    assert matching.rescore_if_dirty(world.Session) is not None
    assert matching.rescore_if_dirty(world.Session) is None
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        matching_rules.create_keyword(s, actor, admin, keyword="School", office=world.office(s, "EDU"))
        s.commit()
    assert matching.rescore_if_dirty(world.Session) is not None
    assert matching.rescore_if_dirty(world.Session) is None


def test_never_re_recommended_after_dismissal_or_unwatch(world):
    with world.Session() as s:
        case = _code_case(world, s)
        s.add(CounselCode(code="SC, HEALTH", office_id=world.offices["HEALTH"].id))
        s.add(
            CaseAdvocate(
                case_id=case.id,
                side=AdvocateSide.RESPONDENT,
                name_as_listed="SC, HEALTH",
                counsel_code="SC, HEALTH",
            )
        )
        s.flush()
        matching.score_cases(s, [case.id], origin=RecommendationOrigin.CAUSE_LIST)
        actor, admin = world.actor(s, "edu_admin")
        ownership.dismiss(s, actor, admin, case, reason="not ours")
        h_actor, h_admin = world.actor(s, "health_admin")
        ownership.claim(s, h_actor, h_admin, case)  # pool → HEALTH primary
        s.commit()
    matching.rescore_all(world.Session)
    with world.Session() as s:
        statuses = {(r.office_id, r.status) for r in recs(s, case.id)}
        assert statuses == {
            (world.offices["EDU"].id, RecommendationStatus.DISMISSED),
            (world.offices["HEALTH"].id, RecommendationStatus.CLAIMED),
        }
        # EDU is suggested by a human, claims as watcher, stops watching: the engine stays away
        h_actor, h_admin = world.actor(s, "health_admin")
        case = s.merge(case)
        ownership.suggest(s, h_actor, h_admin, case, office_code="EDU", reason="also education")
        actor, admin = world.actor(s, "edu_admin")
        row = ownership.claim(s, actor, admin, case)
        assert row.role.value == "watcher"
        ownership.stop_watching(s, actor, admin, case, reason="claimed by mistake")
        s.commit()
    matching.rescore_all(world.Session)
    with world.Session() as s:
        active = [r for r in recs(s, case.id) if r.status == RecommendationStatus.RECOMMENDED]
        assert active == []


def test_pool_claim_without_recommendation_blocks_the_engine_after_transfer(world):
    """Review finding on decision 5: EDU claims a pool case that no rule matched (so no recommendation row
    exists), hands it to HEALTH by an accepted transfer, then adds a code that matches. The engine must not
    recommend the case to EDU again: any `case_ownership` row, whatever its status, blocks the office."""
    with world.Session() as s:
        case = make_case(s)
        s.add(
            CaseAdvocate(
                case_id=case.id,
                side=AdvocateSide.RESPONDENT,
                name_as_listed="SC, EDU",
                counsel_code="SC, EDU",
            )
        )
        s.flush()
        matching.score_cases(s, [case.id], origin=RecommendationOrigin.CAUSE_LIST)
        assert recs(s, case.id) == []  # no rules yet: the case sits in the pool
        actor, admin = world.actor(s, "edu_admin")
        ownership.claim(s, actor, admin, case)
        t = ownership.request_transfer(s, actor, admin, case, to_office_code="HEALTH", reason="theirs")
        h_actor, h_admin = world.actor(s, "health_admin")
        ownership.decide_transfer(s, h_actor, h_admin, t, accept=True)
        s.add(CounselCode(code="SC, EDU", office_id=world.offices["EDU"].id))
        s.commit()
    matching.rescore_all(world.Session)
    with world.Session() as s:
        edu = world.offices["EDU"].id
        score = s.scalar(
            sa.select(CaseOfficeScore).where(
                CaseOfficeScore.case_id == case.id, CaseOfficeScore.office_id == edu
            )
        )
        assert (
            score is not None and float(score.score) >= 0.85
        )  # the score is kept, the recommendation is not
        assert [r for r in recs(s, case.id) if r.office_id == edu] == []
        assert [e for e in made_events(s) if e.case_id == case.id] == []


def test_linked_case_signal_after_claim(world):
    with world.Session() as s:
        main = _code_case(world, s)
        linked = make_case(s)
        s.add(
            CaseLink(
                from_case_id=linked.id,
                to_case_id=main.id,
                to_case_no_text=main.case_no_text,
                kind=LinkKind.MAIN_MATTER,
            )
        )
        s.flush()
        actor, admin = world.actor(s, "edu_admin")
        ownership.claim(s, actor, admin, main)
        s.commit()
        score = s.scalar(
            sa.select(CaseOfficeScore).where(
                CaseOfficeScore.case_id == linked.id, CaseOfficeScore.office_id == world.offices["EDU"].id
            )
        )
        assert float(score.score) == 0.7
        assert score.signals[0]["kind"] == "linked_case" and score.signals[0]["ref"] == main.ref_no
        (rec,) = recs(s, linked.id)
        assert rec.band == ScoreBand.MEDIUM and rec.origin == RecommendationOrigin.RESCORE


def test_unmapped_codes(world):
    with world.Session() as s:
        s.add(CounselCode(code="SC, EDU", office_id=world.offices["EDU"].id))
        s.add(CounselCode(code="GA, ASSAM", office_id=world.offices["GOA"].id, is_generic_state=True))
        s.flush()
        load_list(
            s,
            [
                entry(1, "ASHC010000052025", "WP(C)/5/2025", codes=["SC,REVENUE", "GA, ASSAM"]),
                entry(2, "ASHC010000062025", "WP(C)/6/2025", codes=["SC, REVENUE", "SC, EDU"]),
            ],
        )
        s.commit()
        out = matching.unmapped_codes(s)
        assert [u.code for u in out] == ["SC, REVENUE"]
        assert out[0].entries == 2 and out[0].last_listed == date(2025, 1, 6)
        assert out[0].example_case_ref.startswith("ASLMS/GHC/CASE/")


# ------------------------------------------------------------------------------------------------ ownership-refinements


def _health_code(world, s, case):
    s.add(CounselCode(code="SC, HEALTH", office_id=world.offices["HEALTH"].id))
    s.add(
        CaseAdvocate(
            case_id=case.id,
            side=AdvocateSide.RESPONDENT,
            name_as_listed="SC, HEALTH",
            counsel_code="SC, HEALTH",
        )
    )
    s.flush()


def test_engine_never_recommends_a_claimed_case(world):
    """Design ownership-refinements, decision 13: a strong score for another department on a claimed case creates no
    recommendation and no event."""
    with world.Session() as s:
        case = make_case(s)
        actor, admin = world.actor(s, "edu_admin")
        ownership.claim(s, actor, admin, case)
        _health_code(world, s, case)
        before = len(made_events(s))
        matching.score_cases(s, [case.id], origin=RecommendationOrigin.RESCORE)
        assert [r for r in recs(s, case.id) if r.office_id == world.offices["HEALTH"].id] == []
        assert len(made_events(s)) == before


def test_engine_changes_no_band_on_a_claimed_case(world):
    with world.Session() as s:
        case = make_case(s)
        actor, admin = world.actor(s, "edu_admin")
        ownership.claim(s, actor, admin, case)
        # an engine row left open on the claimed case (before the change), at a band the score no longer gives
        rec = Recommendation(
            case_id=case.id,
            office_id=world.offices["HEALTH"].id,
            score=0.6,
            band=ScoreBand.MEDIUM,
            origin=RecommendationOrigin.CAUSE_LIST,
            actor_name="matching",
        )
        s.add(rec)
        _health_code(world, s, case)  # the score is now 0.95 (strong)
        before = len(made_events(s))
        matching.score_cases(s, [case.id], origin=RecommendationOrigin.RESCORE)
        s.refresh(rec)
        assert rec.band == ScoreBand.MEDIUM and float(rec.score) == 0.6
        assert rec.status == RecommendationStatus.RECOMMENDED
        assert len(made_events(s)) == before


def test_scores_are_still_written_for_a_claimed_case(world):
    with world.Session() as s:
        case = make_case(s)
        actor, admin = world.actor(s, "edu_admin")
        ownership.claim(s, actor, admin, case)
        _health_code(world, s, case)
        matching.score_cases(s, [case.id], origin=RecommendationOrigin.RESCORE)
        score = s.scalar(
            sa.select(CaseOfficeScore).where(
                CaseOfficeScore.case_id == case.id, CaseOfficeScore.office_id == world.offices["HEALTH"].id
            )
        )
        assert score is not None and float(score.score) == 0.95 and score.signals[0]["kind"] == "counsel_code"


def test_claimed_elsewhere_is_never_reopened(world):
    """A closed engine row is in NEVER_AGAIN; the engine also leaves the expiry of open engine rows as before."""
    assert RecommendationStatus.CLAIMED_ELSEWHERE in matching.NEVER_AGAIN
    with world.Session() as s:
        case = make_case(s)
        _health_code(world, s, case)
        matching.score_cases(s, [case.id], origin=RecommendationOrigin.CAUSE_LIST)
        (rec,) = recs(s, case.id)
        assert rec.office_id == world.offices["HEALTH"].id
        actor, admin = world.actor(s, "edu_admin")
        ownership.claim(s, actor, admin, case)  # a pool claim by EDU closes HEALTH's row
        s.refresh(rec)
        assert rec.status == RecommendationStatus.CLAIMED_ELSEWHERE
        s.commit()
    matching.rescore_all(world.Session)
    with world.Session() as s:
        rows = recs(s, case.id)
        assert [(r.office_id, r.status) for r in rows] == [
            (world.offices["HEALTH"].id, RecommendationStatus.CLAIMED_ELSEWHERE)
        ]


# ------------------------------------------------------------------------------------------------ partial-code-match


def test_partial_match_writes_medium_recommendation_never_ownership(world):
    """Design partial-code-match, decisions 2, 14 and 19: a case listed with `SC, EDU, DSE` against EDU's mapped
    `SC, EDU` gets the partial signal and an engine `medium` recommendation; no ownership and no audit row."""
    from aslms.domain.events import AuditLog
    from aslms.domain.ownership import CaseOwnership

    with world.Session() as s:
        s.add(CounselCode(code="SC, EDU", office_id=world.offices["EDU"].id))
        s.flush()
        audits = s.scalar(sa.select(sa.func.count()).select_from(AuditLog))
        load_list(s, [entry(1, "ASHC010000712025", "WP(C)/71/2025", codes=["SC, EDU, DSE"])])
        s.commit()
        (rec,) = recs(s)
        assert rec.office_id == world.offices["EDU"].id and rec.band == ScoreBand.MEDIUM
        assert float(rec.score) == 0.6 and rec.status == RecommendationStatus.RECOMMENDED
        score = s.scalar(sa.select(CaseOfficeScore).where(CaseOfficeScore.case_id == rec.case_id))
        (signal,) = score.signals
        assert signal["kind"] == "counsel_code_partial" and signal["relation"] == "contained"
        assert signal["matched"] == "SC, EDU" and signal["printed"] == "SC, EDU, DSE"
        assert signal["reason"] == "Code SC, EDU found inside SC, EDU, DSE on the cause list of 6 Jan 2025"
        assert score.engine_version == "2.1"
        assert s.scalar(sa.select(sa.func.count()).select_from(CaseOwnership)) == 0
        assert s.scalar(sa.select(sa.func.count()).select_from(AuditLog)) == audits
        (made,) = made_events(s)
        assert made.payload["band"] == "medium"


def test_partial_match_respects_claimed_and_dismissed(world):
    with world.Session() as s:
        s.add(CounselCode(code="SC, EDU", office_id=world.offices["EDU"].id))
        claimed = make_case(s)
        dismissed = make_case(s)
        for case in (claimed, dismissed):
            s.add(
                CaseAdvocate(
                    case_id=case.id,
                    side=AdvocateSide.RESPONDENT,
                    name_as_listed="EDU",
                    counsel_code="EDU",
                )
            )
        s.flush()
        h_actor, h_admin = world.actor(s, "health_admin")
        ownership.claim(s, h_actor, h_admin, claimed)  # ever owned: no engine recommendation
        matching.score_cases(s, [dismissed.id], origin=RecommendationOrigin.CAUSE_LIST)
        (rec,) = recs(s, dismissed.id)
        assert rec.band == ScoreBand.MEDIUM
        actor, admin = world.actor(s, "edu_admin")
        ownership.dismiss(s, actor, admin, dismissed, reason="not ours")
        s.commit()
    matching.rescore_all(world.Session)
    with world.Session() as s:
        assert [r for r in recs(s, claimed.id) if r.office_id == world.offices["EDU"].id] == []
        assert (
            s.scalar(
                sa.select(CaseOfficeScore.score).where(
                    CaseOfficeScore.case_id == claimed.id,
                    CaseOfficeScore.office_id == world.offices["EDU"].id,
                )
            )
            is not None
        ), "the score is still written"
        assert [r.status for r in recs(s, dismissed.id)] == [RecommendationStatus.DISMISSED]


def test_rescore_all_applies_partial_after_settings_version(world):
    """After a new settings version (as migration 0027 inserts), the full rescore writes the partial rows and a
    `job_runs` `rescore` naming the new version; the dirty rescore then runs once and stops."""
    from aslms.domain.ownership import ScoringSettings
    from aslms.services import scoring_settings as ss

    assert matching.rescore_if_dirty(world.Session) is not None
    with world.Session() as s:
        s.add(CounselCode(code="SC, EDU", office_id=world.offices["EDU"].id))
        case = make_case(s)
        s.add(
            CaseAdvocate(
                case_id=case.id,
                side=AdvocateSide.RESPONDENT,
                name_as_listed="SC, EDU (R-2, 3)",
                counsel_code="SC, EDU (R-2, 3)",
            )
        )
        s.flush()
        cur = ss.current_row(s)
        cur.is_current = False
        cur.valid_to = sa.func.now()
        s.flush()
        s.add(
            ScoringSettings(
                version=2,
                weight_counsel_code=0.95,
                weight_name_pattern=0.8,
                weight_watchlist=0.75,
                weight_linked_case=0.7,
                weight_keyword=0.4,
                weight_counsel_code_partial=0.6,
                threshold_strong=0.85,
                threshold_possible=0.5,
                reason="Partial counsel-code match added (design partial-code-match), partial weight 0.600",
                is_current=True,
            )
        )
        s.commit()
    report = matching.rescore_all(world.Session)
    assert report.settings_version == 2 and report.recommended_new == 1
    with world.Session() as s:
        score = s.scalar(sa.select(CaseOfficeScore).where(CaseOfficeScore.case_id == case.id))
        assert score.engine_version == "2.2" and score.signals[0]["relation"] == "same_parts"
        run = s.scalars(sa.select(JobRun).where(JobRun.job == "rescore").order_by(JobRun.started_at)).all()[
            -1
        ]
        assert run.counters["settings_version"] == 2 and run.status.value == "succeeded"
    assert matching.rescore_if_dirty(world.Session) is None


def test_unmapped_codes_carry_partial_matches(world):
    with world.Session() as s:
        s.add(CounselCode(code="SC, EDU", office_id=world.offices["EDU-DSE"].id))
        s.add(CounselCode(code="SC, HEALTH", office_id=world.offices["HEALTH"].id))
        s.flush()
        load_list(
            s,
            [
                entry(1, "ASHC010000722025", "WP(C)/72/2025", codes=["SC, EDU, DSE", "SC, EDU"]),
                entry(2, "ASHC010000732025", "WP(C)/73/2025", codes=["SC, REVENUE"]),
            ],
        )
        s.commit()
        out = {u.code: u.partial_matches for u in matching.unmapped_codes(s)}
        assert out == {
            "SC, EDU, DSE": [{"code": "SC, EDU", "office_code": "EDU-DSE", "relation": "contained"}],
            "SC, REVENUE": [],
        }
        health = world.offices["HEALTH"].id
        scoped = {
            u.code: u.partial_matches for u in matching.unmapped_codes(s, scope=lambda oid: oid == health)
        }
        assert scoped == {"SC, EDU, DSE": [], "SC, REVENUE": []}
