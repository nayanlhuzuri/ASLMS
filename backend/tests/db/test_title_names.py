"""The cause-title names (design `state-insights`, decision 9, "Tests", `test_title_names.py`): audited CRUD with the
event, the `admin.keywords` office scope, normalised and unique phrases, the unmapped list counted over visible cases
only, and the save's dispatch of `insights-refresh`."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.events import AuditLog, Event
from aslms.domain.reference import EventType
from aslms.services import matching_rules
from aslms.services.access import Forbidden
from aslms.services.matching_rules import BadPhrase, PhraseTaken
from tests.db import insights_support as ins


def test_crud_audited_with_event(world):
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        row = matching_rules.create_title_name(
            s, actor, root, office=world.office(s, "EDU"), phrase="the  secondary education"
        )
        assert row.phrase == "SECONDARY EDUCATION"
        matching_rules.update_title_name(s, actor, root, row, office=world.office(s, "EDU-DSE"))
        matching_rules.update_title_name(s, actor, root, row, office=world.office(s, "EDU-DSE"))  # no change
        matching_rules.set_title_name_active(s, actor, root, row, False)
        matching_rules.create_title_name(
            s, actor, root, office=world.office(s, "EDU"), phrase="Secondary Education"
        )
        # created_at is the transaction's now() and equal for all four rows; the UUID v7 id is monotonic in-process
        actions = [
            a.action
            for a in s.scalars(
                sa.select(AuditLog).where(AuditLog.entity_type == "title_name").order_by(AuditLog.id)
            )
        ]
        assert actions == [
            "title_name.create",
            "title_name.update",
            "title_name.deactivate",
            "title_name.reactivate",
        ]
        events = s.scalars(sa.select(Event).where(Event.type == EventType.CONFIG_CHANGED)).all()
        assert sum(1 for e in events if e.payload.get("entity") == "title_name") == 4
        s.rollback()


def test_scope_admin_keywords_subtree(world):
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        row = matching_rules.create_title_name(
            s, actor, admin, office=world.office(s, "EDU-DSE"), phrase="DSE"
        )
        with pytest.raises(Forbidden):
            matching_rules.create_title_name(
                s, actor, admin, office=world.office(s, "HEALTH"), phrase="HEALTH SERVICES"
            )
        with pytest.raises(Forbidden):
            matching_rules.update_title_name(s, actor, admin, row, office=world.office(s, "HEALTH"))
        o_actor, officer = world.actor(s, "edu_off1")
        with pytest.raises(Forbidden):
            matching_rules.create_title_name(
                s, o_actor, officer, office=world.office(s, "EDU"), phrase="SOMETHING"
            )
        h_actor, health = world.actor(s, "health_admin")
        assert [i["phrase"] for i in matching_rules.list_title_names(s, admin)] == ["DSE"]
        assert matching_rules.list_title_names(s, health) == []
        assert len(matching_rules.list_title_names(s, world.user(s, "root"))) == 1
        with pytest.raises(Forbidden):  # the root is outside the admin's subtree
            matching_rules.create_title_name(
                s, actor, admin, office=world.office(s, "GOA"), phrase="ROOT NAME"
            )
        s.rollback()


def test_phrase_normalised_and_unique(world):
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        matching_rules.create_title_name(
            s, actor, root, office=world.office(s, "HEALTH"), phrase="Health & Family Welfare"
        )
        with pytest.raises(PhraseTaken) as exc:
            matching_rules.create_title_name(
                s, actor, root, office=world.office(s, "EDU"), phrase="HEALTH AND FAMILY WELFARE"
            )
        assert exc.value.code == "phrase_taken"
        for bad in ("AB", "", ";;", "'A'"):
            with pytest.raises(BadPhrase) as exc:
                matching_rules.create_title_name(s, actor, root, office=world.office(s, "EDU"), phrase=bad)
            assert exc.value.code == "bad_phrase"
        # decision 4 of state-insights-review-advisories: a refused character folds to a space (or, for a quote,
        # to nothing), so the phrase stored is the one the reader lists
        row = matching_rules.create_title_name(
            s, actor, root, office=world.office(s, "EDU"), phrase="Finance; Drop Table"
        )
        assert row.phrase == "FINANCE DROP TABLE"
        row = matching_rules.create_title_name(
            s, actor, root, office=world.office(s, "EDU"), phrase="P.W.D.'S DEPARTMENT"
        )
        assert row.phrase == "P.W.D.S DEPARTMENT"
        s.rollback()


def test_unmapped_list_counts_visible_cases_only(world):
    with world.Session() as s:
        a = ins.case(s, respondents=("THE SECRETARY, TEA TRIBES WELFARE DEPARTMENT",))
        b = ins.case(s, respondents=("THE SECRETARY, TEA TRIBES WELFARE DEPARTMENT",))
        mapped = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        ins.build(s, a, b, mapped)
        from tests.db.report_support import claim

        claim(s, world, a, by="health_admin")
        items, total = matching_rules.unmapped_title_names(s, world.user(s, "root"))
        assert total == 1 and items[0]["phrase"] == "TEA TRIBES WELFARE" and items[0]["cases"] == 2
        assert items[0]["example_case_no"] in (a.case_no_text, b.case_no_text)
        # the EDU admin sees `b` (the unclaimed pool) but not HEALTH's claimed `a`
        items, _ = matching_rules.unmapped_title_names(s, world.user(s, "edu_admin"))
        assert items[0]["cases"] == 1
        actor, root = world.actor(s, "root")
        matching_rules.create_title_name(
            s, actor, root, office=world.office(s, "HEALTH"), phrase="TEA TRIBES WELFARE"
        )
        assert matching_rules.unmapped_title_names(s, root)[1] == 0
        listed = matching_rules.list_title_names(s, root)
        assert listed[0]["cases"] == 2 and listed[0]["department_code"] == "HEALTH"
        s.rollback()


def test_save_dispatches_refresh(world, monkeypatch):
    from aslms.api.routers import matching as router

    sent: list[str] = []

    class FakeCelery:
        def send_task(self, name, retry=False):
            sent.append(name)

    import aslms.jobs.celery_app as celery_app

    monkeypatch.setattr(celery_app, "app", FakeCelery())

    class Settings:
        redis_url = "redis://example"

    assert router.dispatch_insights_refresh(Settings()) is True
    assert sent == ["aslms.insights_refresh"]

    class NoBroker:
        redis_url = None

    assert router.dispatch_insights_refresh(NoBroker()) is False
