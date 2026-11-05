"""Recommendations start when a mapping is saved (design list-search, decision 41): every counsel-code, keyword,
name-pattern and watchlist save dispatches the rescore once after its commit and never on a refused save; one rescore
at a time; a rule changed during a run dispatches exactly one follow-up; with no broker the beat picks it up."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import sqlalchemy as sa

from aslms.api.routers import matching as matching_router
from aslms.core.clock import today_ist
from aslms.core.config import Settings
from aslms.domain.ops import JobRun, JobStatus
from aslms.domain.ownership import CounselCode, OfficeKeyword, OfficeNamePattern, OfficeWatchlist
from aslms.services import matching, matching_rules
from aslms.services import scoring_settings as ss
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


# ------------------------------------------------------------------------------------------------ rules fingerprint
# design list-search-followups, decision 1: "dirty" is decided by a fingerprint of the rules recorded by each run


def test_a_save_committed_after_the_run_loaded_its_rules_gets_a_follow_up(world, monkeypatch):
    _dirty(world)
    # a save whose transaction began before the claim (its timestamps precede the run's start) ...
    a = world.Session()
    actor, admin = world.actor(a, "edu_admin")
    matching_rules.create_keyword(a, actor, admin, keyword="Late Word", office=world.office(a, "EDU"))
    a.flush()
    original = matching.RuleSet.load
    committed: list[bool] = []

    def load_then_commit(session):
        rules = original(session)
        if not committed:
            a.commit()  # ... and committed right after the run loaded its rules
            a.close()
            committed.append(True)
        return rules

    monkeypatch.setattr(matching.RuleSet, "load", staticmethod(load_then_commit))
    calls: list[int] = []
    try:
        assert matching.rescore_if_dirty(world.Session, dispatch=lambda: calls.append(1)) is not None
    finally:
        if not committed:
            a.rollback()
            a.close()
    assert committed and calls == [1]
    # the follow-up runs (the next claim sees the rules differ), then nothing is left
    assert matching.rescore_if_dirty(world.Session, dispatch=lambda: calls.append(2)) is not None
    assert matching.rescore_if_dirty(world.Session, dispatch=lambda: calls.append(3)) is None
    assert calls == [1]


def _commit(world, change) -> None:
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        change(s, actor, root)
        s.commit()


def test_each_run_records_the_rules_fingerprint(world):
    report = matching.rescore_if_dirty(world.Session)
    assert report is not None and report.rules_fingerprint
    with world.Session() as s:
        run = s.get(JobRun, report.job_run_id)
        assert run.counters["rules_fingerprint"] == report.rules_fingerprint == matching.rules_fingerprint(s)
        assert matching.rules_dirty(s) is False

    ids: dict[str, object] = {}

    def code(s, actor, root):
        ids["code"] = matching_rules.create_counsel_code(
            s, actor, root, code="SC, FP", office=world.office(s, "EDU")
        ).id

    def keyword(s, actor, root):
        ids["kw"] = matching_rules.create_keyword(
            s, actor, root, keyword="Fingerprint", office=world.office(s, "EDU")
        ).id

    def pattern(s, actor, root):
        ids["pat"] = matching_rules.create_name_pattern(
            s, actor, root, pattern="Finger Print", kind="prefix", office=world.office(s, "EDU")
        ).id

    def watch(s, actor, root):
        row, _ = matching_rules.add_watch(
            s, actor, root, cnr="ASHC010000982025", office=world.office(s, "EDU")
        )
        ids["watch"] = row.id

    def settings(s, actor, root):
        weights = dict(ss.DEFAULTS.weights) | {"keyword": 0.41}
        ss.update(
            s,
            actor,
            root,
            weights=weights,
            threshold_strong=0.85,
            threshold_possible=0.5,
            reason="fingerprint",
            expected_version=1,
        )

    changes = [
        # creates
        code,
        keyword,
        pattern,
        watch,
        # updates
        lambda s, a, r: setattr(s.get(CounselCode, ids["code"]), "notes", "changed"),
        lambda s, a, r: setattr(s.get(OfficeKeyword, ids["kw"]), "weight", Decimal("0.300")),
        lambda s, a, r: setattr(s.get(OfficeNamePattern, ids["pat"]), "weight", Decimal("0.300")),
        lambda s, a, r: setattr(s.get(OfficeWatchlist, ids["watch"]), "reason", "changed"),
        lambda s, a, r: setattr(world.office(s, "EDU"), "name", "Education Department (renamed)"),
        settings,
        # deactivations
        lambda s, a, r: matching_rules.set_counsel_code_active(
            s, a, r, s.get(CounselCode, ids["code"]), False
        ),
        lambda s, a, r: matching_rules.set_keyword_active(s, a, r, s.get(OfficeKeyword, ids["kw"]), False),
        lambda s, a, r: matching_rules.set_name_pattern_active(
            s, a, r, s.get(OfficeNamePattern, ids["pat"]), False
        ),
        lambda s, a, r: matching_rules.set_watch_active(s, a, r, s.get(OfficeWatchlist, ids["watch"]), False),
    ]
    with world.Session() as s:
        seen = {matching.rules_fingerprint(s)}
    for change in changes:
        _commit(world, change)
        with world.Session() as s:
            fp = matching.rules_fingerprint(s)
            assert fp not in seen, change
            assert matching.rules_dirty(s) is True
            seen.add(fp)


def test_a_run_without_a_fingerprint_falls_back_to_timestamps(world):
    # a succeeded run from before this change: counters without a fingerprint, started after every rule
    with world.Session() as s:
        s.add(JobRun(job="rescore", run_date=today_ist(), status=JobStatus.SUCCEEDED, counters={}))
        s.commit()
    assert matching.claim_rescore(world.Session) is None
    _dirty(world)
    assert matching.claim_rescore(world.Session) is not None
