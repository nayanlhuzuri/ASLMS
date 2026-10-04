"""Scoring settings (recommend-and-claim, decision 21): seed, versioned updates, the audit row and event, the
function check, validation, the CHECKs and the partial index, and a full rescore that follows a change."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.events import AuditLog, Event
from aslms.domain.ops import JobRun
from aslms.domain.org import PermissionEffect
from aslms.domain.ownership import (
    CaseOfficeScore,
    CounselCode,
    Recommendation,
    RecommendationOrigin,
    RecommendationStatus,
    ScoreBand,
    ScoringSettings,
)
from aslms.domain.reference import EventType, Permission
from aslms.services import access, matching
from aslms.services import scoring_settings as ss
from aslms.services.seed import SeedReport
from tests.db.world import make_case


def _values(**over):
    weights = dict(ss.DEFAULTS.weights)
    weights.update(over.pop("weights", {}))
    return {
        "weights": weights,
        "threshold_strong": over.pop("strong", 0.85),
        "threshold_possible": over.pop("possible", 0.5),
        "reason": over.pop("reason", "tuning"),
        "expected_version": over.pop("expected", 1),
    }


def test_seed_inserts_version_one_once(world):
    with world.Session() as s:
        rows = s.scalars(sa.select(ScoringSettings)).all()
        assert len(rows) == 1
        cur = ss.current(s)
        assert cur.version == 1 and cur.weights == ss.DEFAULTS.weights
        assert (cur.threshold_strong, cur.threshold_possible) == (0.85, 0.5)
        assert rows[0].reason == "Plan §4.2 defaults" and rows[0].is_current
        report = SeedReport()
        ss.seed_default(s, report)
        assert report.total == 0


def test_current_on_empty_table_is_version_zero(session):
    session.execute(sa.text("DELETE FROM scoring_settings"))
    assert ss.current(session) == ss.DEFAULTS
    assert ss.current(session).version == 0


def test_super_admin_update_versions_audits_and_emits(world):
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        after, changed = ss.update(s, actor, root, **_values(strong=0.9))
        s.commit()
        assert changed and after.version == 2 and after.threshold_strong == 0.9
        v1 = s.scalar(sa.select(ScoringSettings).where(ScoringSettings.version == 1))
        v2 = s.scalar(sa.select(ScoringSettings).where(ScoringSettings.version == 2))
        assert not v1.is_current and v1.valid_to is not None
        assert v2.is_current and v2.valid_to is None and v2.created_by == root.id
        audits = s.scalars(sa.select(AuditLog).where(AuditLog.action == "scoring_settings.update")).all()
        assert len(audits) == 1
        assert audits[0].before["version"] == 1 and audits[0].after["version"] == 2
        assert audits[0].after["threshold_strong"] == 0.9
        events = s.scalars(sa.select(Event).where(Event.type == EventType.CONFIG_CHANGED)).all()
        assert [e.payload["entity"] for e in events] == ["scoring_settings"]
        assert events[0].payload["version"] == 2


def test_dept_admin_forbidden_unless_granted(world):
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        with pytest.raises(access.Forbidden):
            ss.update(s, actor, admin, **_values(strong=0.9))
        r_actor, root = world.actor(s, "root")
        access.set_override(s, r_actor, root, admin, Permission.ADMIN_SCORING, PermissionEffect.GRANT)
        after, changed = ss.update(s, actor, admin, **_values(strong=0.9))
        assert changed and after.version == 2


def test_stale_identical_and_invalid(world):
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        with pytest.raises(ss.StaleSettings):
            ss.update(s, actor, root, **_values(strong=0.9, expected=0))
        n_audit = s.scalar(sa.select(sa.func.count()).select_from(AuditLog))
        same, changed = ss.update(s, actor, root, **_values())
        assert not changed and same.version == 1
        assert s.scalar(sa.select(sa.func.count()).select_from(ScoringSettings)) == 1
        assert s.scalar(sa.select(sa.func.count()).select_from(AuditLog)) == n_audit
        for bad in (
            _values(weights={"keyword": 0}),
            _values(weights={"keyword": 1.2}),
            _values(strong=0.6, possible=0.6),
            _values(strong=0.9, reason="  "),
        ):
            with pytest.raises(ss.SettingsError):
                ss.update(s, actor, root, **bad)


def test_checks_and_partial_index(session):
    insert = (
        "INSERT INTO scoring_settings (version, weight_counsel_code, weight_name_pattern, weight_watchlist, "
        "weight_linked_case, weight_keyword, threshold_strong, threshold_possible, reason, is_current, valid_to) "
        "VALUES (:v, 0.9, 0.8, 0.7, 0.7, 0.4, :s, :p, 'x', :c, :vt)"
    )
    with pytest.raises(sa.exc.IntegrityError, match="ck_scoring_settings_thresholds"):
        with session.begin_nested():
            session.execute(sa.text(insert), {"v": 90, "s": 0.8, "p": 0.9, "c": False, "vt": "2026-01-01"})
    with pytest.raises(sa.exc.IntegrityError, match="ck_scoring_settings_current"):
        with session.begin_nested():
            session.execute(sa.text(insert), {"v": 91, "s": 0.9, "p": 0.5, "c": False, "vt": None})
    session.execute(sa.text("DELETE FROM scoring_settings"))
    session.execute(sa.text(insert), {"v": 92, "s": 0.9, "p": 0.5, "c": True, "vt": None})
    with pytest.raises(sa.exc.IntegrityError, match="ix_scoring_settings_current"):
        with session.begin_nested():
            session.execute(sa.text(insert), {"v": 93, "s": 0.9, "p": 0.5, "c": True, "vt": None})


def _counsel_case(world):
    """`SC, EDU` mapped to EDU; one case whose advocate code is `SC, EDU` (score 0.950, high)."""
    from aslms.domain.cases import AdvocateSide, CaseAdvocate

    with world.Session() as s:
        s.add(CounselCode(code="SC, EDU", office_id=world.offices["EDU"].id))
        case = make_case(s, pet="A PETITIONER", res="SOMEONE")
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
        s.commit()
        return case.id


def test_settings_change_rescore_changes_band_and_expires(world):
    case_id = _counsel_case(world)
    with world.Session() as s:
        rec = s.scalar(sa.select(Recommendation).where(Recommendation.case_id == case_id))
        assert rec.band == ScoreBand.HIGH and float(rec.score) == 0.95
        # a human suggestion to HEALTH, which must stay untouched by every rescore
        s.add(
            Recommendation(
                case_id=case_id,
                office_id=world.offices["HEALTH"].id,
                score=0,
                band=ScoreBand.MEDIUM,
                origin=RecommendationOrigin.SUGGESTION,
                actor_name="EDU Admin",
            )
        )
        actor, root = world.actor(s, "root")
        ss.update(s, actor, root, **_values(strong=0.96))
        s.commit()
    matching.rescore_all(world.Session)
    with world.Session() as s:
        rec = s.scalar(
            sa.select(Recommendation).where(
                Recommendation.case_id == case_id, Recommendation.office_id == world.offices["EDU"].id
            )
        )
        assert rec.band == ScoreBand.MEDIUM and rec.status == RecommendationStatus.RECOMMENDED
        made = s.scalars(sa.select(Event).where(Event.type == EventType.RECOMMENDATION_MADE)).all()
        assert len(made) == 2  # created high, then changed to medium
        assert (
            s.scalar(sa.select(CaseOfficeScore.engine_version).where(CaseOfficeScore.case_id == case_id))
            == "1.2"
        )
        actor, root = world.actor(s, "root")
        ss.update(s, actor, root, **_values(strong=0.99, possible=0.96, expected=2))
        s.commit()
    matching.rescore_all(world.Session)
    with world.Session() as s:
        recs = {
            r.origin: r for r in s.scalars(sa.select(Recommendation).where(Recommendation.case_id == case_id))
        }
        assert recs[RecommendationOrigin.CAUSE_LIST].status == RecommendationStatus.EXPIRED
        assert recs[RecommendationOrigin.SUGGESTION].status == RecommendationStatus.RECOMMENDED
        assert recs[RecommendationOrigin.SUGGESTION].band == ScoreBand.MEDIUM


def test_rescore_if_dirty_after_settings_change(world):
    assert matching.rescore_if_dirty(world.Session) is not None  # never run before
    assert matching.rescore_if_dirty(world.Session) is None
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        ss.update(s, actor, root, **_values(weights={"keyword": 0.45}))
        s.commit()
    report = matching.rescore_if_dirty(world.Session)
    assert report is not None and report.settings_version == 2
    assert matching.rescore_if_dirty(world.Session) is None
    with world.Session() as s:
        runs = s.scalars(sa.select(JobRun).where(JobRun.job == "rescore").order_by(JobRun.started_at)).all()
        assert len(runs) == 2 and runs[-1].counters["settings_version"] == 2
