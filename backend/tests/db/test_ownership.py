"""Ownership actions (recommend-and-claim, decisions 6-11, 20, 22): claim, the concurrent claim, claim with
allotment, dismiss, suggest, allot, no return to the pool, take over, transfers, the audit rows each action
leaves, the seed of the new functions, and migration 0004's objects."""

from __future__ import annotations

import threading
import uuid

import pytest
import sqlalchemy as sa

from aslms.domain.events import AuditLog, Event
from aslms.domain.org import RolePermission
from aslms.domain.ownership import (
    CaseOwnership,
    OwnershipRole,
    OwnershipStatus,
    OwnershipTransfer,
    Recommendation,
    RecommendationOrigin,
    RecommendationStatus,
    ScoreBand,
    TransferStatus,
)
from aslms.domain.reference import EventType, Permission, Role
from aslms.domain.workflow import Custody, CustodyHistory
from aslms.services import access
from aslms.services import ownership as own
from aslms.services.access_seed import PERMISSION_LABELS
from tests.db.world import make_case


def recommend(s, world, case, code, *, score=0.95, band=ScoreBand.HIGH):
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


def audits(s, case_id) -> list[str]:
    return list(
        s.scalars(
            sa.select(AuditLog.action)
            .where(AuditLog.case_id == case_id)
            .order_by(AuditLog.created_at, AuditLog.id)
        )
    )


def events(s, case_id, kind) -> list[Event]:
    return list(
        s.scalars(
            sa.select(Event)
            .where(Event.case_id == case_id, Event.type == kind)
            .order_by(Event.occurred_at, Event.id)
        )
    )


def custody(s, case_id):
    c = s.get(Custody, case_id)
    s.refresh(c)
    return c


def legs(s, case_id) -> list[CustodyHistory]:
    return list(
        s.scalars(
            sa.select(CustodyHistory).where(CustodyHistory.case_id == case_id).order_by(CustodyHistory.seq_no)
        )
    )


# ------------------------------------------------------------------------------------------------ claim


def test_claim_primary_then_watcher_then_conflicts(world):
    with world.Session() as s:
        case = make_case(s)
        rec = recommend(s, world, case, "EDU")
        actor, admin = world.actor(s, "edu_admin")
        row = own.claim(s, actor, admin, case)
        assert row.role == OwnershipRole.PRIMARY and rec.status == RecommendationStatus.CLAIMED
        assert audits(s, case.id) == ["ownership.claim"]
        assert len(events(s, case.id, EventType.CLAIMED)) == 1
        c = custody(s, case.id)
        assert c.holder_office_id == world.offices["EDU"].id and c.holder_user_id is None
        assert [lg.reason for lg in legs(s, case.id)] == ["claimed"]
        recommend(s, world, case, "HEALTH")
        h_actor, h_admin = world.actor(s, "health_admin")
        watcher = own.claim(s, h_actor, h_admin, case)
        assert watcher.role == OwnershipRole.WATCHER
        assert custody(s, case.id).holder_office_id == world.offices["EDU"].id
        with pytest.raises(own.OwnershipConflict):
            own.claim(s, actor, admin, case)
        other = make_case(s)
        own.claim(s, actor, admin, other)  # pool claim by EDU
        with pytest.raises(own.NotVisible):
            own.claim(s, h_actor, h_admin, other)  # HEALTH has no recommendation on an owned case
        assert audits(s, case.id) == ["ownership.claim", "ownership.claim"]


def test_concurrent_claims_end_with_one_primary(world):
    with world.Session() as s:
        case = make_case(s)
        s.commit()
        case_id = case.id
    barrier = threading.Barrier(2)
    results: list[str] = []

    def worker(key):
        with world.Session() as s:
            actor, user = world.actor(s, key)
            c = s.get(type(case), case_id)
            barrier.wait()
            try:
                own.claim(s, actor, user, c)
                s.commit()
                results.append("ok")
            except (own.OwnershipConflict, own.NotVisible):
                s.rollback()
                results.append("refused")

    threads = [threading.Thread(target=worker, args=(k,)) for k in ("edu_admin", "health_admin")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["ok", "refused"]
    with world.Session() as s:
        primaries = s.scalars(
            sa.select(CaseOwnership).where(
                CaseOwnership.case_id == case_id, CaseOwnership.role == OwnershipRole.PRIMARY
            )
        ).all()
        assert len(primaries) == 1


def test_claim_with_allotment(world):
    with world.Session() as s:
        case = make_case(s)
        actor, admin = world.actor(s, "edu_admin")
        off1 = world.user(s, "edu_off1")
        row = own.claim(s, actor, admin, case, unit_code="EDU-DSE", officer_user_id=off1.id)
        assert row.unit_office_id == world.offices["EDU-DSE"].id and row.officer_user_id == off1.id
        assert row.allotted_by_user_id == admin.id and row.allotted_at is not None
        assert audits(s, case.id) == ["ownership.claim", "ownership.allot"]
        c = custody(s, case.id)
        assert (c.holder_office_id, c.holder_user_id) == (world.offices["EDU-DSE"].id, off1.id)
        other = make_case(s)
        with pytest.raises(own.OwnershipError):
            own.claim(s, actor, admin, other, unit_code="HEALTH")


def test_super_admin_names_the_department(world):
    with world.Session() as s:
        case = make_case(s)
        actor, root = world.actor(s, "root")
        with pytest.raises(own.OwnershipError):
            own.claim(s, actor, root, case)
        row = own.claim(s, actor, root, case, office_code="HEALTH")
        assert row.office_id == world.offices["HEALTH"].id


# ------------------------------------------------------------------------------------------------ dismiss / suggest


def test_dismiss(world):
    with world.Session() as s:
        case = make_case(s)
        actor, admin = world.actor(s, "edu_admin")
        with pytest.raises(own.NotVisible):
            own.dismiss(s, actor, admin, case)
        rec = recommend(s, world, case, "EDU")
        own.dismiss(s, actor, admin, case, reason="a revenue matter")
        assert rec.status == RecommendationStatus.DISMISSED and rec.reason == "a revenue matter"
        assert audits(s, case.id) == ["recommendation.dismiss"]
        assert len(events(s, case.id, EventType.DISMISSED)) == 1


def test_suggest(world):
    with world.Session() as s:
        case = make_case(s)
        rec = recommend(s, world, case, "EDU")
        h_rec = recommend(s, world, case, "HEALTH", score=0.6, band=ScoreBand.MEDIUM)
        h_actor, h_admin = world.actor(s, "health_admin")
        own.dismiss(s, h_actor, h_admin, case)
        actor, admin = world.actor(s, "edu_admin")
        out = own.suggest(s, actor, admin, case, office_code="HEALTH", reason="hospital staff")
        assert rec.status == RecommendationStatus.SUGGESTED_ELSEWHERE
        assert rec.suggested_office_id == world.offices["HEALTH"].id
        assert out.target.origin == RecommendationOrigin.SUGGESTION and out.target.id != h_rec.id
        assert out.target.status == RecommendationStatus.RECOMMENDED and out.target.actor_user_id == admin.id
        assert not out.target_already_recommended
        # the central operator routes a pool case; a target already recommended is left alone
        pool = make_case(s)
        recommend(s, world, pool, "HEALTH")
        c_actor, op = world.actor(s, "central_op")
        out = own.suggest(s, c_actor, op, pool, office_code="HEALTH", reason="routing")
        assert out.target_already_recommended and out.own is None
        n = s.scalar(sa.select(sa.func.count()).where(Recommendation.case_id == pool.id))
        assert n == 1
        own.claim(s, h_actor, h_admin, pool)
        with pytest.raises(own.OwnershipConflict):
            own.suggest(s, c_actor, op, pool, office_code="HEALTH", reason="again")
        assert "recommendation.suggest" in audits(s, pool.id)


# ------------------------------------------------------------------------------------------------ allot


def test_allot_by_watcher_and_clearing(world):
    with world.Session() as s:
        case = make_case(s)
        h_actor, h_admin = world.actor(s, "health_admin")
        own.claim(s, h_actor, h_admin, case)
        recommend(s, world, case, "EDU")
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, case)
        n_legs = len(legs(s, case.id))
        off1 = world.user(s, "edu_off1")
        row = own.allot(s, actor, admin, case, officer_user_id=off1.id)
        assert row.role == OwnershipRole.WATCHER and row.officer_user_id == off1.id
        assert len(legs(s, case.id)) == n_legs  # watcher rows move no custody
        own.allot(s, actor, admin, case, officer_user_id=None)
        assert row.officer_user_id is None
        auditor = world.user(s, "edu_auditor")
        with pytest.raises(own.OwnershipError):
            own.allot(s, actor, admin, case, officer_user_id=auditor.id)


# ------------------------------------------------------------------------------------------------ no return to the pool


def test_no_release_of_primary_and_watcher_stops_watching(world):
    with world.Session() as s:
        case = make_case(s)
        actor, admin = world.actor(s, "edu_admin")
        primary = own.claim(s, actor, admin, case)
        n_audit = len(audits(s, case.id))
        with pytest.raises(own.OwnershipConflict) as exc:
            own.stop_watching(s, actor, admin, case, reason="done")
        assert exc.value.code == "primary_cannot_release"
        assert len(audits(s, case.id)) == n_audit and primary.status == OwnershipStatus.ACTIVE
        recommend(s, world, case, "HEALTH")
        h_actor, h_admin = world.actor(s, "health_admin")
        watcher = own.claim(s, h_actor, h_admin, case)
        holder = custody(s, case.id).holder_office_id
        own.stop_watching(s, h_actor, h_admin, case, reason="not ours after all")
        assert watcher.status == OwnershipStatus.RELEASED and watcher.release_reason == "not ours after all"
        assert audits(s, case.id)[-1] == "ownership.unwatch"
        assert len(events(s, case.id, EventType.OWNERSHIP_RELEASED)) == 1
        assert primary.status == OwnershipStatus.ACTIVE and custody(s, case.id).holder_office_id == holder
        s.commit()
        with pytest.raises(sa.exc.IntegrityError, match="ck_case_ownership_release_watcher"):
            s.execute(
                sa.update(CaseOwnership).where(CaseOwnership.id == primary.id).values(status="released")
            )
        s.rollback()


# ------------------------------------------------------------------------------------------------ take over


def _allotted_case(s, world, *, unit="EDU-DSE", officer="edu_off1", primary=True):
    case = make_case(s)
    actor, admin = world.actor(s, "edu_admin")
    if not primary:
        h_actor, h_admin = world.actor(s, "health_admin")
        own.claim(s, h_actor, h_admin, case)
        recommend(s, world, case, "EDU")
    own.claim(s, actor, admin, case, unit_code=unit, officer_user_id=world.users[officer].id)
    return case


def test_take_over_by_a_colleague(world):
    with world.Session() as s:
        case = _allotted_case(s, world, unit=None)
        actor, off2 = world.actor(s, "edu_off2")
        out = own.take_over(s, actor, off2, case, reason="holder on leave")
        row = out.ownership
        assert row.officer_user_id == off2.id and row.allotted_by_user_id == off2.id
        assert out.previous.id == world.users["edu_off1"].id
        assert audits(s, case.id)[-1] == "ownership.take_over"
        log = s.scalar(sa.select(AuditLog).where(AuditLog.action == "ownership.take_over"))
        assert log.before["officer_user_id"] == str(world.users["edu_off1"].id)
        assert log.after["officer_user_id"] == str(off2.id)
        (ev,) = events(s, case.id, EventType.CASE_TAKEN_OVER)
        assert ev.payload["from_user_id"] == str(world.users["edu_off1"].id)
        assert ev.payload["to_user_id"] == str(off2.id)
        c = custody(s, case.id)
        assert c.holder_user_id == off2.id and legs(s, case.id)[-1].reason == "taken_over"


def test_take_over_unit_follows_the_taker(world):
    with world.Session() as s:
        case = _allotted_case(s, world, unit="EDU-DSE")
        actor, dhe = world.actor(s, "dhe_user")
        row = own.take_over(s, actor, dhe, case).ownership
        assert row.unit_office_id == world.offices["EDU-DHE"].id
        assert custody(s, case.id).holder_office_id == world.offices["EDU-DHE"].id
        case2 = _allotted_case(s, world, unit="EDU-DSE")
        actor, dse = world.actor(s, "dse_user")
        assert own.take_over(s, actor, dse, case2).ownership.unit_office_id == world.offices["EDU-DSE"].id
        case3 = _allotted_case(s, world, unit="EDU-DSE")
        actor, off2 = world.actor(s, "edu_off2")
        assert own.take_over(s, actor, off2, case3).ownership.unit_office_id is None


def test_take_over_refusals(world):
    with world.Session() as s:
        case = _allotted_case(s, world)
        for key in ("health_off", "root"):
            actor, user = world.actor(s, key)
            with pytest.raises(own.NotVisible):
                own.take_over(s, actor, user, case)
        actor, off1 = world.actor(s, "edu_off1")
        with pytest.raises(own.OwnershipConflict) as exc:
            own.take_over(s, actor, off1, case)
        assert exc.value.code == "already_holder"
        actor, off2 = world.actor(s, "edu_off2")
        with pytest.raises(own.OwnershipConflict) as exc:
            own.take_over(s, actor, off2, case, expected_officer_user_id=uuid.uuid4())
        assert exc.value.code == "stale"
        actor, reviewer = world.actor(s, "edu_reviewer")
        with pytest.raises(access.Forbidden):
            own.take_over(s, actor, reviewer, case)
        bare = make_case(s)
        a_actor, admin = world.actor(s, "edu_admin")
        own.claim(s, a_actor, admin, bare)
        with pytest.raises(own.OwnershipConflict) as exc:
            own.take_over(s, world.actor(s, "edu_off2")[0], off2, bare)
        assert exc.value.code == "not_allotted"
        assert "ownership.take_over" not in audits(s, case.id) + audits(s, bare.id)


def test_take_over_on_watcher_row_moves_no_custody(world):
    with world.Session() as s:
        case = _allotted_case(s, world, primary=False)
        before = len(legs(s, case.id))
        actor, off2 = world.actor(s, "edu_off2")
        row = own.take_over(s, actor, off2, case).ownership
        assert row.role == OwnershipRole.WATCHER and len(legs(s, case.id)) == before


# ------------------------------------------------------------------------------------------------ transfers


def test_transfers(world):
    with world.Session() as s:
        case = make_case(s)
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, case)
        recommend(s, world, case, "HEALTH")
        h_actor, h_admin = world.actor(s, "health_admin")
        own.claim(s, h_actor, h_admin, case)  # HEALTH watches
        with pytest.raises(own.OwnershipConflict):
            own.request_transfer(s, h_actor, h_admin, case, to_office_code="EDU", reason="x")
        t = own.request_transfer(
            s, actor, admin, case, to_office_code="HEALTH", reason="a hospital case", stay_as_watcher=True
        )
        assert t.ref_no.startswith("ASLMS/EDU/TRF/") and t.ref_no.endswith("/000001")
        with pytest.raises(own.OwnershipConflict):
            own.request_transfer(s, actor, admin, case, to_office_code="HEALTH", reason="again")
        c_actor, op = world.actor(s, "central_op")
        access.set_override(
            s, *world.actor(s, "root"), op, Permission.CASES_TRANSFER_DECIDE, access.PermissionEffect.GRANT
        )
        with pytest.raises(own.NotVisible):
            own.decide_transfer(s, c_actor, op, t, accept=True)
        own.decide_transfer(s, h_actor, h_admin, t, accept=True, note="agreed")
        rows = {(r.office_id, r.role, r.status) for r in s.scalars(sa.select(CaseOwnership))}
        assert (world.offices["EDU"].id, OwnershipRole.PRIMARY, OwnershipStatus.TRANSFERRED) in rows
        assert (world.offices["HEALTH"].id, OwnershipRole.PRIMARY, OwnershipStatus.ACTIVE) in rows
        assert (world.offices["EDU"].id, OwnershipRole.WATCHER, OwnershipStatus.ACTIVE) in rows
        assert custody(s, case.id).holder_office_id == world.offices["HEALTH"].id
        assert t.status == TransferStatus.ACCEPTED and t.decided_by_user_id == h_admin.id
        assert own.ever_owned(s, case)  # never back to the pool
        assert audits(s, case.id)[-1] == "transfer.accept"

        other = make_case(s)
        own.claim(s, actor, admin, other)
        t2 = own.request_transfer(s, actor, admin, other, to_office_code="HEALTH", reason="maybe")
        own.decide_transfer(s, h_actor, h_admin, t2, accept=False, note="not ours")
        assert t2.status == TransferStatus.DECLINED and t2.decision_note == "not ours"
        primary = s.scalar(
            sa.select(CaseOwnership).where(
                CaseOwnership.case_id == other.id, CaseOwnership.role == OwnershipRole.PRIMARY
            )
        )
        assert primary.office_id == world.offices["EDU"].id
        t3 = own.request_transfer(s, actor, admin, other, to_office_code="HEALTH", reason="once more")
        with pytest.raises(own.NotVisible):
            own.withdraw_transfer(s, h_actor, h_admin, t3)
        own.withdraw_transfer(s, actor, admin, t3)
        assert t3.status == TransferStatus.WITHDRAWN and t3.withdrawn_at is not None
        assert audits(s, other.id) == [
            "ownership.claim",
            "transfer.request",
            "transfer.decline",
            "transfer.request",
            "transfer.withdraw",
        ]
        assert s.scalar(sa.select(sa.func.count()).select_from(OwnershipTransfer)) == 3


# ------------------------------------------------------------------------------------------------ seed and migration


def test_seed_has_the_new_functions_and_event(world):
    with world.Session() as s:
        labels = dict(
            s.execute(
                sa.text(
                    "select code, label from ref_permission where code in "
                    "('admin.scoring', 'cases.take_over', 'cases.release')"
                )
            ).all()
        )
        assert labels == {
            "admin.scoring": "Scoring Weights and Bands",
            "cases.take_over": "Take Over a Case",
            "cases.release": "Stop Watching",
        }
        assert PERMISSION_LABELS[Permission.CASES_RELEASE][0] == "Stop Watching"
        enabled = set(
            s.scalars(
                sa.select(RolePermission.role).where(
                    RolePermission.permission == Permission.CASES_TAKE_OVER,
                    RolePermission.is_enabled.is_(True),
                )
            )
        )
        assert {Role(r) for r in enabled} == {
            Role.DEPT_HEAD,
            Role.DEPT_ADMIN,
            Role.DEPT_OFFICER,
            Role.DIRECTORATE_USER,
        }
        assert not s.scalars(
            sa.select(RolePermission).where(
                RolePermission.permission == Permission.ADMIN_SCORING, RolePermission.is_enabled.is_(True)
            )
        ).all()
        assert (
            s.execute(
                sa.text("select is_tracking_card from ref_event_type where code = 'case_taken_over'")
            ).scalar()
            is True
        )


def test_seed_refreshes_a_stale_permission_label(session):
    from aslms.services.seed import SeedReport, seed_ref_tables

    session.execute(sa.text("update ref_permission set label = 'Release cases' where code = 'cases.release'"))
    report = SeedReport()
    seed_ref_tables(session, report)
    assert session.execute(
        sa.text("select label from ref_permission where code='cases.release'")
    ).scalar() == ("Stop Watching")


def test_migration_0004_objects(engine):
    with engine.connect() as c:
        idx = set(
            c.execute(
                sa.text(
                    "select indexname from pg_indexes where indexname in ('ix_scoring_settings_current', "
                    "'ix_recommendations_active', 'ix_case_ownership_active_primary', "
                    "'ix_case_ownership_active_office', 'ix_ownership_transfers_open')"
                )
            ).scalars()
        )
        assert len(idx) == 5
        checks = set(
            c.execute(
                sa.text("select conname from pg_constraint where contype = 'c' and conname like 'ck_%'")
            ).scalars()
        )
        assert {
            "ck_scoring_settings_weights",
            "ck_scoring_settings_thresholds",
            "ck_scoring_settings_current",
            "ck_counsel_codes_weight",
            "ck_office_keywords_weight",
            "ck_office_name_patterns_weight",
            "ck_office_watchlist_weight",
            "ck_recommendations_score_range",
            "ck_case_ownership_release_watcher",
        } <= checks
        nullable = dict(
            c.execute(
                sa.text(
                    "select table_name, is_nullable from information_schema.columns where column_name = 'weight' "
                    "and table_name in ('counsel_codes','office_keywords','office_name_patterns','office_watchlist')"
                )
            ).all()
        )
        assert set(nullable.values()) == {"YES"} and len(nullable) == 4
