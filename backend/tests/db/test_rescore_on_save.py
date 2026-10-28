"""Recommendations start when a mapping is saved (design list-search, decision 41): every counsel-code, keyword,
name-pattern and watchlist save dispatches the rescore once after its commit and never on a refused save; one rescore
at a time; a rule changed during a run dispatches exactly one follow-up; with no broker the beat picks it up."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from aslms.api.routers import matching as matching_router
from aslms.core.config import Settings
from aslms.domain.ops import JobRun, JobStatus
from aslms.domain.ownership import CounselCode, OfficeKeyword
from aslms.services import matching, matching_rules
from tests.db.test_api_inbox import api, login  # noqa: F401  (the `api` fixture)


@pytest.fixture()
def dispatched(monkeypatch, world):
    """Records each dispatch with what a separate session sees at that moment (so "after the commit" is checked)."""
    calls: list[dict] = []

    def fake(settings) -> bool:
        with world.Session() as s:
            calls.append(
                {
                    "codes": set(s.scalars(sa.select(CounselCode.code)).all()),
                    "keywords": {(k.keyword, k.is_active) for k in s.scalars(sa.select(OfficeKeyword))},
                }
            )
        return True

    monkeypatch.setattr(matching_router, "dispatch_rescore", fake)
    return calls


def test_each_save_dispatches_once_after_commit(api, world, dispatched):  # noqa: F811
    edu = login(api, "edu_admin")
    r = api.post("/admin/counsel-codes", json={"code": "SC, EDU", "office_code": "EDU"}, headers=edu)
    assert r.status_code == 201 and r.json()["rescore_dispatched"] is True
    assert len(dispatched) == 1 and "SC, EDU" in dispatched[0]["codes"]
    code_id = r.json()["id"]
    assert api.post(f"/admin/counsel-codes/{code_id}/deactivate", headers=edu).status_code == 200
    r = api.post("/admin/keywords", json={"keyword": "School", "office_code": "EDU"}, headers=edu)
    assert r.status_code == 201
    assert ("SCHOOL", True) in dispatched[-1]["keywords"]
    kw = r.json()["id"]
    assert api.patch(f"/admin/keywords/{kw}", json={"discover": False}, headers=edu).status_code == 200
    assert api.post(f"/admin/keywords/{kw}/deactivate", headers=edu).status_code == 200
    assert ("SCHOOL", False) in dispatched[-1]["keywords"]
    assert api.post(f"/admin/keywords/{kw}/reactivate", headers=edu).status_code == 200
    r = api.post(
        "/admin/name-patterns",
        json={"pattern": "Ram Das", "kind": "prefix", "office_code": "EDU"},
        headers=edu,
    )
    assert r.status_code == 201
    r = api.post("/admin/watchlist", json={"cnr": "ASHC010000992025", "office_code": "EDU"}, headers=edu)
    assert r.status_code == 201, r.text
    assert (
        api.patch(f"/admin/watchlist/{r.json()['id']}", json={"reason": "watch"}, headers=edu).status_code
        == 200
    )
    assert len(dispatched) == 9


def test_a_refused_save_dispatches_nothing(api, world, dispatched):  # noqa: F811
    edu = login(api, "edu_admin")
    assert (
        api.post(
            "/admin/counsel-codes", json={"code": "SC, EDU", "office_code": "EDU"}, headers=edu
        ).status_code
        == 201
    )
    before = len(dispatched)
    # a duplicate (409), another department's office (403) and a function the caller lacks (403)
    assert (
        api.post(
            "/admin/counsel-codes", json={"code": "SC, EDU", "office_code": "EDU"}, headers=edu
        ).status_code
        == 409
    )
    r = api.post("/admin/counsel-codes", json={"code": "SC, HLT", "office_code": "HEALTH"}, headers=edu)
    assert r.status_code == 403
    r = api.post(
        "/admin/keywords", json={"keyword": "X", "office_code": "EDU"}, headers=login(api, "edu_off1")
    )
    assert r.status_code == 403
    assert len(dispatched) == before


def _dirty(world) -> None:
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        matching_rules.create_keyword(
            s, actor, admin, keyword=f"Word {datetime.now(UTC).timestamp()}", office=world.office(s, "EDU")
        )
        s.commit()


def test_one_rescore_at_a_time(world):
    _dirty(world)
    first = matching.claim_rescore(world.Session)
    assert first is not None
    # a second dispatch while the first runs does nothing
    assert matching.claim_rescore(world.Session) is None
    assert matching.rescore_if_dirty(world.Session) is None
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(JobRun).where(JobRun.job == "rescore")) == 1
        # a run that died more than 30 minutes ago no longer blocks
        run = s.get(JobRun, first)
        run.started_at = datetime.now(UTC) - timedelta(minutes=31)
        s.commit()
    assert matching.rescore_if_dirty(world.Session) is not None


def test_a_change_during_a_run_dispatches_one_follow_up(world, monkeypatch):
    _dirty(world)
    calls: list[int] = []
    original = matching.rescore_all

    def changing(session_factory, **kw):
        report = original(session_factory, **kw)
        _dirty(world)  # a mapping saved while the run was going
        return report

    monkeypatch.setattr(matching, "rescore_all", changing)
    assert matching.rescore_if_dirty(world.Session, dispatch=lambda: calls.append(1)) is not None
    assert calls == [1]
    # the follow-up rescores once more; nothing changed during it, so no further dispatch
    monkeypatch.setattr(matching, "rescore_all", original)
    assert matching.rescore_if_dirty(world.Session, dispatch=lambda: calls.append(2)) is not None
    assert calls == [1]
    assert matching.rescore_if_dirty(world.Session, dispatch=lambda: calls.append(3)) is None
    with world.Session() as s:
        statuses = s.scalars(sa.select(JobRun.status).where(JobRun.job == "rescore")).all()
        assert list(statuses) == [JobStatus.SUCCEEDED, JobStatus.SUCCEEDED]


def test_no_broker_falls_back_to_the_beat(monkeypatch):
    assert matching_router.dispatch_rescore(Settings(_env_file=None, redis_url=None)) is False

    class Broken:
        def send_task(self, *a, **kw):
            raise ConnectionError("no broker")

    import aslms.jobs.celery_app as celery_app

    monkeypatch.setattr(celery_app, "app", Broken())
    assert (
        matching_router.dispatch_rescore(Settings(_env_file=None, redis_url="redis://nowhere:6379/0"))
        is False
    )
