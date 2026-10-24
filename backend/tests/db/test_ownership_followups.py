"""Ownership follow-ups (design `followups-oct`, decisions 15 to 17): the backfill keeps a post-claim suggestion
open and still closes post-claim engine rows; the engine takes the case lock before reading claimed state and passes
cases in case-id order; a suggestion event without a target is skipped without a `session.get` on a null key."""

from __future__ import annotations

import threading
import time
import uuid
import warnings
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.exc import SAWarning

from aslms.domain.cases import Case
from aslms.domain.ownership import (
    CaseOfficeScore,
    CaseOwnership,
    Recommendation,
    RecommendationOrigin,
    RecommendationStatus,
    ScoreBand,
)
from aslms.services import alerts, matching
from aslms.services import ownership as own
from aslms.services import scoring_settings as ss
from tests.db.world import make_case


def _rec(s, world, case, code, *, origin, created_at, band=ScoreBand.HIGH, score=0.95):
    rec = Recommendation(
        case_id=case.id,
        office_id=world.offices[code].id,
        score=score,
        band=band,
        origin=origin,
        actor_name="matching",
        created_at=created_at,
    )
    s.add(rec)
    s.flush()
    return rec


def _claimed(s, world, key="edu_admin"):
    case = make_case(s)
    actor, user = world.actor(s, key)
    row = own.claim(s, actor, user, case)
    return case, row


def test_backfill_keeps_post_claim_suggestion_open(world):
    with world.Session() as s:
        case, row = _claimed(s, world)
        later = row.claimed_at + timedelta(minutes=5)
        sug = _rec(s, world, case, "HEALTH", origin=RecommendationOrigin.SUGGESTION, created_at=later)
        counts = own.close_claimed_backfill(s, apply=True)
        assert counts["closed"] == 0
        s.refresh(sug)
        assert sug.status == RecommendationStatus.RECOMMENDED, "the target may still claim as a watcher"
        s.rollback()


def test_backfill_still_closes_post_claim_engine_rows(world):
    with world.Session() as s:
        case, row = _claimed(s, world)
        later = row.claimed_at + timedelta(minutes=5)
        engine = _rec(s, world, case, "CENTRAL", origin=RecommendationOrigin.CAUSE_LIST, created_at=later)
        before = row.claimed_at - timedelta(days=1)
        old_sug = _rec(s, world, case, "HEALTH", origin=RecommendationOrigin.SUGGESTION, created_at=before)
        counts = own.close_claimed_backfill(s, apply=True)
        assert counts == {"closed": 2, "cases": 1, "by_department": {"CENTRAL": 1, "HEALTH": 1}}
        for r in (engine, old_sug):
            s.refresh(r)
            assert r.status == RecommendationStatus.CLAIMED_ELSEWHERE
        s.rollback()


def test_repeat_apply_closes_zero(world):
    with world.Session() as s:
        case, row = _claimed(s, world)
        later = row.claimed_at + timedelta(minutes=5)
        _rec(s, world, case, "CENTRAL", origin=RecommendationOrigin.RESCORE, created_at=later)
        sug = _rec(s, world, case, "HEALTH", origin=RecommendationOrigin.SUGGESTION, created_at=later)
        assert own.close_claimed_backfill(s, apply=True)["closed"] == 1
        s.commit()
        empty = {"closed": 0, "cases": 0, "by_department": {}}
        assert own.close_claimed_backfill(s, apply=False) == empty, "the dry run prints the same counts"
        assert own.close_claimed_backfill(s, apply=True) == empty
        s.refresh(sug)
        assert sug.status == RecommendationStatus.RECOMMENDED


def test_engine_waits_for_claim_lock(world):
    """Session A claims (holding the case lock, not yet committed); the engine in session B would recommend HEALTH.
    B blocks on the case lock, then sees the claim: no new HEALTH recommendation, and the CENTRAL row the claim
    closed stays `claimed_elsewhere`. Without the lock B would read "not claimed" and open HEALTH."""
    with world.Session() as s:
        case = make_case(s)
        _rec(s, world, case, "CENTRAL", origin=RecommendationOrigin.CAUSE_LIST, created_at=sa.func.now())
        # the scores B computes are already stored, so B writes no score row (whose FK check would wait on the
        # claim's row lock and hide the race) before it reads the claimed state
        version = matching.engine_version(ss.current(s))
        for code, score in (("HEALTH", 0.97), ("CENTRAL", 0.96)):
            s.add(
                CaseOfficeScore(
                    case_id=case.id,
                    office_id=world.offices[code].id,
                    score=score,
                    signals=[],
                    engine_version=version,
                )
            )
        s.commit()
        case_id, health_id = case.id, world.offices["HEALTH"].id
        central_id = world.offices["CENTRAL"].id
    done = threading.Event()
    errors: list[BaseException] = []

    def engine_pass():
        try:
            with world.Session() as b:
                c = b.get(Case, case_id)
                scores = {
                    health_id: matching.ScoredOffice(health_id, "HEALTH", 0.97, []),
                    central_id: matching.ScoredOffice(central_id, "CENTRAL", 0.96, []),
                }
                matching.apply_scores(
                    b, c, scores, origin=RecommendationOrigin.RESCORE, settings=ss.current(b)
                )
                b.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            done.set()

    with world.Session() as a:
        actor, user = world.actor(a, "edu_admin")
        own.claim(a, actor, user, a.get(Case, case_id))  # closes CENTRAL as claimed_elsewhere; holds the lock
        t = threading.Thread(target=engine_pass)
        t.start()
        time.sleep(1.0)
        assert not done.is_set(), "the engine waits for the claim's case lock"
        a.commit()
    t.join(timeout=30)
    assert done.is_set() and errors == []
    with world.Session() as s:
        recs = s.scalars(sa.select(Recommendation).where(Recommendation.case_id == case_id)).all()
        assert [(r.office_id, r.status) for r in recs] == [
            (central_id, RecommendationStatus.CLAIMED_ELSEWHERE)
        ]
        owners = s.scalars(sa.select(CaseOwnership).where(CaseOwnership.case_id == case_id)).all()
        assert len(owners) == 1


def test_engine_passes_lock_in_case_id_order(world, monkeypatch):
    seen: list[uuid.UUID] = []
    real = matching.apply_scores

    def spy(session, case, *args, **kwargs):
        seen.append(case.id)
        return real(session, case, *args, **kwargs)

    monkeypatch.setattr(matching, "apply_scores", spy)
    with world.Session() as s:
        ids = [make_case(s).id for _ in range(5)]
        matching.score_cases(s, list(reversed(sorted(ids))), origin=RecommendationOrigin.RESCORE)
        s.rollback()
    assert seen == sorted(ids)


def test_suggestion_event_without_target_is_skipped_without_warning(world):
    counters = {"skipped_other": 0}
    with world.Session() as s, warnings.catch_warnings():
        warnings.simplefilter("error", SAWarning)
        case = make_case(s)
        alerts._suggestion_event(s, None, None, case, {}, today=None, cfg=None, now=None, counters=counters)
        s.rollback()
    assert counters["skipped_other"] == 1
