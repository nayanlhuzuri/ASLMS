"""Ownership refinements (design `ownership-refinements`): a court refresh queued on claim and on an accepted transfer
(decisions 1-3), other departments' recommendations closed by a primary claim with their event, audit and 409
(decisions 9-12), the explicit watcher route after a claim, the one-off backfill (decision 14) and migration 0021.
NAPIX is never called: the refresh only queues a row, and the switch stays off."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from alembic import command
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.cases import Case
from aslms.domain.events import AuditLog, Event
from aslms.domain.ops import FetchKind, FetchLane, FetchQueueItem, FetchStatus
from aslms.domain.ownership import (
    CaseOwnership,
    OwnershipRole,
    Recommendation,
    RecommendationOrigin,
    RecommendationStatus,
    ScoreBand,
)
from aslms.domain.reference import EventType
from aslms.services import dashboard, inbox, queue, visibility
from aslms.services import ownership as own
from aslms.services.runner import run_queue_once
from tests.db.auth_support import bearer
from tests.db.conftest import alembic_config, head_revision
from tests.db.world import PW, USERS, make_case

SETTINGS = dict(
    _env_file=None,
    aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters",
    aslms_access_token_minutes=5,
    redis_url=None,
)


def recommend(
    s, world, case, code, *, origin=RecommendationOrigin.CAUSE_LIST, band=ScoreBand.HIGH, score=0.95
):
    rec = Recommendation(
        case_id=case.id,
        office_id=world.offices[code].id,
        score=score,
        band=band,
        origin=origin,
        actor_name="matching",
    )
    s.add(rec)
    s.flush()
    return rec


def claim(s, world, key, case, **kw):
    actor, user = world.actor(s, key)
    return own.claim(s, actor, user, case, **kw)


def claim_audit(s, case) -> AuditLog:
    return s.scalars(
        sa.select(AuditLog)
        .where(AuditLog.case_id == case.id, AuditLog.action == "ownership.claim")
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    ).first()


def dossier_rows(s) -> list[FetchQueueItem]:
    return list(
        s.scalars(
            sa.select(FetchQueueItem)
            .where(FetchQueueItem.kind == FetchKind.DOSSIER)
            .execution_options(populate_existing=True)
        ).all()
    )


def events(s, case, kind) -> list[Event]:
    return list(s.scalars(sa.select(Event).where(Event.case_id == case.id, Event.type == kind)).all())


@pytest.fixture()
def api(world):
    settings = Settings(**SETTINGS)
    app = create_app(settings, world.Session)
    calls: list[int] = []

    def factory():  # the claim never opens an integration client
        calls.append(1)
        raise AssertionError("no NAPIX client may be opened by a claim")

    app.state.napix_factory = factory
    with TestClient(app) as c:
        c.napix_calls = calls
        yield c


def login(api: TestClient, key: str) -> dict:
    return bearer(api, USERS[key][0], PW)


# ------------------------------------------------------------------------------------------------ court refresh


def test_claim_of_a_case_without_a_dossier_queues_a_request_dossier(api, world):
    with world.Session() as s:
        case = make_case(s)
        recommend(s, world, case, "EDU")
        s.commit()
        cnr, ref = case.cnr, case.ref_no
    r = api.post(f"/cases/{ref.replace('/', '-')}/claim", json={}, headers=login(api, "edu_admin"))
    assert r.status_code == 201, r.text
    assert api.napix_calls == []
    with world.Session() as s:
        (row,) = dossier_rows(s)
        assert row.ref == cnr and row.status == FetchStatus.PENDING and row.lane == FetchLane.REQUEST
        assert row.priority == 30 and row.requested_by == world.users["edu_admin"].id
        a = claim_audit(s, s.scalar(sa.select(Case).where(Case.cnr == cnr)))
        assert a.after["court_refresh"] == "queued" and a.after["closed_recommendations"] == []


def test_claim_of_a_case_refreshed_within_24_hours_queues_nothing(world):
    with world.Session() as s:
        case = make_case(s)
        case.last_full_refresh_at = datetime.now(UTC) - timedelta(hours=3)
        claim(s, world, "edu_admin", case)
        assert dossier_rows(s) == []
        assert claim_audit(s, case).after["court_refresh"] == "fresh"


def test_claim_revives_a_done_dossier_row_older_than_24_hours(world):
    with world.Session() as s:
        case = make_case(s)
        case.last_full_refresh_at = datetime.now(UTC) - timedelta(days=3)
        queue.enqueue(s, FetchKind.DOSSIER, case.cnr, 50, lane=FetchLane.LOAD)
        item = queue.claim(s, [FetchKind.DOSSIER])
        queue.complete(s, item, {"ok": True})
        assert item.attempts == 1
        claim(s, world, "edu_admin", case)
        (row,) = dossier_rows(s)
        assert row.status == FetchStatus.PENDING and row.attempts == 0
        assert row.lane == FetchLane.REQUEST and row.priority == 30
        assert row.requested_by == world.users["edu_admin"].id
        assert claim_audit(s, case).after["court_refresh"] == "queued"


def test_claim_upgrades_a_pending_sweep_row(world):
    with world.Session() as s:
        case = make_case(s)
        queue.enqueue(s, FetchKind.DOSSIER, case.cnr, 50, lane=FetchLane.DAILY)
        claim(s, world, "edu_admin", case)
        (row,) = dossier_rows(s)
        assert row.status == FetchStatus.PENDING and row.priority == 30 and row.lane == FetchLane.REQUEST


def test_claim_leaves_a_running_dossier_row_alone(world):
    with world.Session() as s:
        case = make_case(s)
        queue.enqueue(s, FetchKind.DOSSIER, case.cnr, 50, lane=FetchLane.DAILY)
        item = queue.claim(s, [FetchKind.DOSSIER])
        assert item.status == FetchStatus.RUNNING
        claim(s, world, "edu_admin", case)
        (row,) = dossier_rows(s)
        assert row.status == FetchStatus.RUNNING and row.attempts == 1 and row.lane == FetchLane.DAILY
        assert claim_audit(s, case).after["court_refresh"] == "in_progress"


def test_claim_of_a_provisional_case_queues_by_case_number(world):
    with world.Session() as s:
        case = make_case(s, case_no="WP(C)/77/2025")
        case.cnr, case.is_provisional = None, True
        s.flush()
        claim(s, world, "edu_admin", case)
        (row,) = dossier_rows(s)
        assert row.ref == "GAHC01|WP(C)/77/2025"
        assert claim_audit(s, case).after["court_refresh"] == "queued"
        bare = make_case(s)
        bare.cnr, bare.case_no_text, bare.is_provisional = None, None, True
        s.flush()
        row2 = claim(s, world, "edu_admin", bare)  # claimed all the same
        assert row2.role == OwnershipRole.PRIMARY
        assert claim_audit(s, bare).after["court_refresh"] == "no_reference"
        assert len(dossier_rows(s)) == 1


def test_a_failing_enqueue_never_fails_the_claim(world, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("queue down")

    monkeypatch.setattr(queue, "enqueue", boom)
    with world.Session() as s:
        case = make_case(s)
        row = claim(s, world, "edu_admin", case)
        s.commit()
        assert s.get(CaseOwnership, row.id) is not None
        assert claim_audit(s, case).after["court_refresh"] == "failed"
        assert len(events(s, case, EventType.CLAIMED)) == 1
        assert dossier_rows(s) == []


def test_queued_refresh_waits_while_the_switch_is_off(world):
    with world.Session() as s:
        case = make_case(s)
        claim(s, world, "edu_admin", case)
        s.commit()
    settings = Settings(**SETTINGS)
    assert not settings.napix_configured
    asyncio.run(run_queue_once(world.Session, max_items=5, kinds=None, settings=settings))
    with world.Session() as s:
        (row,) = dossier_rows(s)
        assert row.status == FetchStatus.PENDING and row.attempts == 0


def _transfer(s, world, case, *, accept: bool, stay=False):
    actor, admin = world.actor(s, "edu_admin")
    t = own.request_transfer(
        s, actor, admin, case, to_office_code="HEALTH", reason="theirs", stay_as_watcher=stay
    )
    h_actor, h_admin = world.actor(s, "health_admin")
    own.decide_transfer(s, h_actor, h_admin, t, accept=accept)
    return t


def test_accepted_transfer_queues_a_refresh_for_the_accepter(world):
    with world.Session() as s:
        case = make_case(s)
        case.last_full_refresh_at = datetime.now(UTC) - timedelta(hours=1)
        claim(s, world, "edu_admin", case)
        assert dossier_rows(s) == []  # fresh at claim time
        case.last_full_refresh_at = datetime.now(UTC) - timedelta(days=2)
        s.flush()
        t = _transfer(s, world, case, accept=True)
        (row,) = dossier_rows(s)
        assert row.requested_by == world.users["health_admin"].id and row.lane == FetchLane.REQUEST
        a = s.scalar(
            sa.select(AuditLog).where(AuditLog.action == "transfer.accept", AuditLog.entity_id == t.id)
        )
        assert a.after["court_refresh"] == "queued"


def test_a_declined_transfer_queues_nothing(world):
    with world.Session() as s:
        case = make_case(s)
        case.last_full_refresh_at = datetime.now(UTC) - timedelta(hours=1)
        claim(s, world, "edu_admin", case)
        case.last_full_refresh_at = datetime.now(UTC) - timedelta(days=2)
        s.flush()
        t = _transfer(s, world, case, accept=False)
        assert dossier_rows(s) == []
        a = s.scalar(
            sa.select(AuditLog).where(AuditLog.action == "transfer.decline", AuditLog.entity_id == t.id)
        )
        assert "court_refresh" not in a.after


def test_a_watcher_claim_also_queues_a_stale_refresh(world):
    with world.Session() as s:
        case = make_case(s)
        case.last_full_refresh_at = datetime.now(UTC) - timedelta(hours=1)
        claim(s, world, "edu_admin", case)
        assert dossier_rows(s) == []
        case.last_full_refresh_at = datetime.now(UTC) - timedelta(days=2)
        s.flush()
        recommend(s, world, case, "HEALTH", origin=RecommendationOrigin.SUGGESTION)  # a post-claim suggestion
        row = claim(s, world, "health_admin", case)
        assert row.role == OwnershipRole.WATCHER
        (q,) = dossier_rows(s)
        assert q.requested_by == world.users["health_admin"].id
        assert claim_audit(s, case).after["court_refresh"] == "queued"


# ------------------------------------------------------------------------------------------------ closing on claim


def test_primary_claim_closes_other_departments_open_recommendations(world):
    with world.Session() as s:
        case = make_case(s)
        a = recommend(s, world, case, "EDU")
        b = recommend(s, world, case, "HEALTH", band=ScoreBand.MEDIUM, score=0.6)
        c = recommend(s, world, case, "CENTRAL", origin=RecommendationOrigin.SUGGESTION)
        row = claim(s, world, "edu_admin", case)
        for rec in (a, b, c):
            s.refresh(rec)
        assert a.status == RecommendationStatus.CLAIMED
        for rec in (b, c):
            assert rec.status == RecommendationStatus.CLAIMED_ELSEWHERE
            assert rec.acted_at is not None and rec.reason == "claimed by EDU"
        evs = events(s, case, EventType.RECOMMENDATION_CLOSED)
        assert len(evs) == 2
        by_office = {e.payload["office_code"]: e for e in evs}
        assert set(by_office) == {"HEALTH", "CENTRAL"}
        assert by_office["HEALTH"].payload == {
            "recommendation_id": str(b.id),
            "office_code": "HEALTH",
            "claimed_by_office_code": "EDU",
            "ownership_id": str(row.id),
            "origin": "cause_list",
            "band": "medium",
        }
        assert by_office["CENTRAL"].payload["origin"] == "suggestion"
        assert all(e.actor_user_id == world.users["edu_admin"].id for e in evs)
        assert all(e.dedupe_key == f"recommendation_closed:{e.payload['recommendation_id']}" for e in evs)
        audit = claim_audit(s, case)
        assert sorted(audit.after["closed_recommendations"], key=lambda x: x["office_code"]) == [
            {"recommendation_id": str(c.id), "office_code": "CENTRAL"},
            {"recommendation_id": str(b.id), "office_code": "HEALTH"},
        ]


def test_claim_from_the_pool_also_closes_other_recommendations(world):
    with world.Session() as s:
        case = make_case(s)
        b = recommend(s, world, case, "HEALTH")
        claim(s, world, "edu_admin", case)  # EDU had no recommendation: a pool claim
        s.refresh(b)
        assert b.status == RecommendationStatus.CLAIMED_ELSEWHERE
        assert len(events(s, case, EventType.RECOMMENDATION_CLOSED)) == 1


def test_closed_department_loses_sight(api, world):
    with world.Session() as s:
        case = make_case(s)
        recommend(s, world, case, "EDU")
        recommend(s, world, case, "HEALTH")
        s.commit()
        health = world.user(s, "health_admin")
        assert visibility.can_view_case(s, health, case)
        assert dashboard._claim_counts(s, health)["high"] == 1
        claim(s, world, "edu_admin", case)
        s.commit()
        assert not visibility.can_view_case(s, health, case)
        assert dashboard._claim_counts(s, health) == {"high": 0, "medium": 0}
        assert (
            s.scalar(
                sa.select(sa.func.count()).select_from(
                    inbox.recommended_stmt(world.office(s, "HEALTH")).subquery()
                )
            )
            == 0
        )
        ref = case.ref_no.replace("/", "-")
    headers = login(api, "health_admin")
    assert api.get(f"/cases/{ref}", headers=headers).status_code == 404
    assert api.get("/inbox/recommended", headers=headers).json()["total"] == 0


def test_stale_claim_dismiss_suggest_answer_409_claimed_elsewhere(api, world):
    with world.Session() as s:
        case = make_case(s)
        recommend(s, world, case, "EDU")
        recommend(s, world, case, "HEALTH")
        s.commit()
        claim(s, world, "edu_admin", case)
        s.commit()
        ref = case.ref_no.replace("/", "-")
        writes = s.scalar(sa.select(sa.func.count()).where(AuditLog.case_id == case.id))
        case_id = case.id
    headers = login(api, "health_admin")
    message = "EDU claimed this case; your department's recommendation is closed"
    for path, body in (
        ("claim", {}),
        ("dismiss", {"reason": "not ours"}),
        ("suggest", {"office_code": "CENTRAL", "reason": "theirs"}),
        ("suggest", {"office_code": "CENTRAL", "reason": "theirs", "from_office_code": "HEALTH"}),
        ("dismiss", {"reason": "not ours", "office_code": "HEALTH"}),
    ):
        r = api.post(f"/cases/{ref}/{path}", json=body, headers=headers)
        assert r.status_code == 409, (path, r.text)
        assert r.json()["detail"] == {"code": "claimed_elsewhere", "message": message}
    with world.Session() as s:  # refusals write nothing
        assert s.scalar(sa.select(sa.func.count()).where(AuditLog.case_id == case_id)) == writes
    # a department never recommended still gets 404 on an owned case
    with world.Session() as s:
        other = make_case(s)
        claim(s, world, "edu_admin", other)
        s.commit()
        other_ref = other.ref_no.replace("/", "-")
    assert api.post(f"/cases/{other_ref}/claim", json={}, headers=headers).status_code == 404


def test_watcher_claim_and_transfer_accept_close_no_post_claim_suggestion(world):
    with world.Session() as s:
        case = make_case(s)
        claim(s, world, "edu_admin", case)
        h = recommend(s, world, case, "HEALTH", origin=RecommendationOrigin.SUGGESTION)
        c = recommend(s, world, case, "CENTRAL", origin=RecommendationOrigin.SUGGESTION)
        row = claim(s, world, "health_admin", case)  # watcher claim
        assert row.role == OwnershipRole.WATCHER
        s.refresh(c)
        assert c.status == RecommendationStatus.RECOMMENDED
        assert claim_audit(s, case).after["closed_recommendations"] == []
        s.refresh(h)
        assert h.status == RecommendationStatus.CLAIMED
        _transfer(s, world, case, accept=True)  # HEALTH (the watcher) becomes primary
        s.refresh(c)
        assert c.status == RecommendationStatus.RECOMMENDED
        assert events(s, case, EventType.RECOMMENDATION_CLOSED) == []


def test_owner_suggestion_after_claim_still_makes_a_watcher(world):
    with world.Session() as s:
        case = make_case(s)
        claim(s, world, "edu_admin", case)
        actor, admin = world.actor(s, "edu_admin")
        res = own.suggest(s, actor, admin, case, office_code="HEALTH", reason="they should watch")
        assert res.target.status == RecommendationStatus.RECOMMENDED
        ev = events(s, case, EventType.SUGGESTED_ELSEWHERE)[-1]
        assert ev.payload["target_recommendation_id"] == str(res.target.id)
        row = claim(s, world, "health_admin", case)
        assert row.role == OwnershipRole.WATCHER
        s.refresh(res.target)
        assert res.target.status == RecommendationStatus.CLAIMED


def test_two_concurrent_claims_leave_one_primary_and_the_other_409(world):
    with world.Session() as s:
        case = make_case(s)
        recommend(s, world, case, "EDU")
        recommend(s, world, case, "HEALTH")
        s.commit()
        case_id = case.id
    barrier = threading.Barrier(2)
    results: dict[str, str] = {}

    def worker(key):
        with world.Session() as s:
            actor, user = world.actor(s, key)
            c = s.get(Case, case_id)
            barrier.wait()
            try:
                own.claim(s, actor, user, c)
                s.commit()
                results[key] = "ok"
            except own.OwnershipConflict as exc:
                s.rollback()
                results[key] = exc.code

    threads = [threading.Thread(target=worker, args=(k,)) for k in ("edu_admin", "health_admin")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results.values()) == ["claimed_elsewhere", "ok"], results
    with world.Session() as s:
        rows = s.scalars(sa.select(CaseOwnership).where(CaseOwnership.case_id == case_id)).all()
        assert [r.role for r in rows] == [OwnershipRole.PRIMARY]


# ------------------------------------------------------------------------------------------------ backfill


def _old_world(s, world):
    """Cases claimed before the change: other departments' recommendations still open."""
    case1 = make_case(s)
    claim(s, world, "edu_admin", case1)
    b1 = recommend(s, world, case1, "HEALTH")
    c1 = recommend(s, world, case1, "CENTRAL", band=ScoreBand.MEDIUM, score=0.6)
    case2 = make_case(s)
    claim(s, world, "health_admin", case2)
    e2 = recommend(s, world, case2, "EDU")
    pool = make_case(s)
    p = recommend(s, world, pool, "EDU")  # unclaimed: untouched
    return (case1, case2, pool), (b1, c1, e2, p)


def test_close_claimed_backfill_dry_run_writes_nothing(world):
    with world.Session() as s:
        _cases, recs = _old_world(s, world)
        before_events = s.scalar(sa.select(sa.func.count()).select_from(Event))
        counts = own.close_claimed_backfill(s, apply=False)
        assert counts == {"closed": 3, "cases": 2, "by_department": {"CENTRAL": 1, "EDU": 1, "HEALTH": 1}}
        for r in recs:
            s.refresh(r)
            assert r.status == RecommendationStatus.RECOMMENDED
        assert s.scalar(sa.select(sa.func.count()).select_from(Event)) == before_events
        assert (
            s.scalar(sa.select(AuditLog).where(AuditLog.action == "recommendation.close_claimed_backfill"))
            is None
        )


def test_close_claimed_backfill_apply_closes_emits_and_audits_once(world):
    with world.Session() as s:
        (case1, case2, pool), (b1, c1, e2, p) = _old_world(s, world)
        counts = own.close_claimed_backfill(s, apply=True)
        assert counts["closed"] == 3 and counts["cases"] == 2
        for r in (b1, c1, e2):
            s.refresh(r)
            assert r.status == RecommendationStatus.CLAIMED_ELSEWHERE and r.acted_at is not None
        assert b1.reason.startswith("claimed by EDU (closed on ") and e2.reason.startswith(
            "claimed by HEALTH"
        )
        s.refresh(p)
        assert p.status == RecommendationStatus.RECOMMENDED
        evs = events(s, case1, EventType.RECOMMENDATION_CLOSED) + events(
            s, case2, EventType.RECOMMENDATION_CLOSED
        )
        assert len(evs) == 3 and all(e.payload["backfill"] is True and e.actor_user_id is None for e in evs)
        (audit,) = s.scalars(
            sa.select(AuditLog).where(AuditLog.action == "recommendation.close_claimed_backfill")
        ).all()
        assert audit.actor_name == "ownership-backfill" and audit.after == counts
        s.commit()
        again = own.close_claimed_backfill(s, apply=True)
        assert again == {"closed": 0, "cases": 0, "by_department": {}}
        assert (
            s.scalar(
                sa.select(sa.func.count()).where(AuditLog.action == "recommendation.close_claimed_backfill")
            )
            == 1
        )


def test_backfill_command_dry_run_and_apply(world, monkeypatch):
    from typer.testing import CliRunner

    from aslms.cli import matching as cli_matching
    from aslms.cli.main import app

    with world.Session() as s:
        _old_world(s, world)
        s.commit()
    monkeypatch.setattr(cli_matching, "get_sessionmaker", lambda: world.Session)
    runner = CliRunner()
    r = runner.invoke(app, ["close-claimed-recommendations"])
    assert r.exit_code == 0, r.output
    assert "would close" in r.output and "3 recommendation(s) on 2 case(s)" in r.output
    with world.Session() as s:
        assert (
            s.scalar(
                sa.select(sa.func.count()).where(
                    Recommendation.status == RecommendationStatus.CLAIMED_ELSEWHERE
                )
            )
            == 0
        )
    r = runner.invoke(app, ["close-claimed-recommendations", "--apply"])
    assert r.exit_code == 0 and "closed: 3" in r.output
    r = runner.invoke(app, ["close-claimed-recommendations"])
    assert "0 recommendation(s)" in r.output


# ------------------------------------------------------------------------------------------------ migration 0021


def _scalar(engine, sql: str):
    with engine.connect() as conn:
        return conn.execute(sa.text(sql)).scalar()


@pytest.mark.migration_cycle
def test_0021_adds_the_status_and_event_type(db_url, engine):
    cfg = alembic_config(db_url)
    command.downgrade(cfg, "0020")
    try:
        assert (
            _scalar(engine, "select count(*) from ref_event_type where code = 'recommendation_closed'") == 0
        )
    finally:
        command.upgrade(cfg, "head")
    assert "claimed_elsewhere" in _scalar(engine, "select enum_range(NULL::recommendation_status)::text")
    with engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "select label, timeline_label, is_tracking_card, sort_order, is_active "
                "from ref_event_type where code = 'recommendation_closed'"
            )
        ).one()
    assert tuple(row) == ("Recommendation closed", "Recommendation closed", False, 370, True)


@pytest.mark.migration_cycle
def test_0021_downgrade_refused_with_claimed_elsewhere_rows(db_url, engine, world):
    cfg = alembic_config(db_url)
    with world.Session() as s:
        case = make_case(s)
        recommend(s, world, case, "HEALTH")
        claim(s, world, "edu_admin", case)
        s.commit()
    with pytest.raises(RuntimeError, match="0021"):
        command.downgrade(cfg, "0020")
    assert _scalar(engine, "select version_num from alembic_version") == head_revision()
    with engine.begin() as conn:
        conn.execute(
            sa.text("update recommendations set status = 'expired' where status = 'claimed_elsewhere'")
        )
    command.downgrade(cfg, "0020")  # allowed now; the reference row stays while an event uses it
    try:
        assert (
            _scalar(engine, "select count(*) from ref_event_type where code = 'recommendation_closed'") == 1
        )
        assert "claimed_elsewhere" in _scalar(engine, "select enum_range(NULL::recommendation_status)::text")
    finally:
        command.upgrade(cfg, "head")
    assert _scalar(engine, "select count(*) from ref_event_type where code = 'recommendation_closed'") == 1
