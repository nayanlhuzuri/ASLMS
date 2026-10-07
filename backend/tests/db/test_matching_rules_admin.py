"""Rule administration (recommend-and-claim, decisions 13, 14, 21): audit rows and config events for each
rule's lifecycle, duplicates and reactivation, scope, generic codes, weight overrides behind `admin.scoring`,
the weight CHECK, and the watchlist (CNR format, dossier queueing, inline scoring)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.events import AuditLog, Event
from aslms.domain.ops import FetchKind, FetchQueueItem
from aslms.domain.ownership import (
    CounselCode,
    OfficeWatchlist,
    PatternKind,
    Recommendation,
    RecommendationOrigin,
)
from aslms.domain.reference import EventType
from aslms.services import access
from aslms.services import matching_rules as mr
from tests.db.world import make_case


def audit_actions(s, entity_id) -> list[str]:
    return list(
        s.scalars(
            sa.select(AuditLog.action)
            .where(AuditLog.entity_id == entity_id)
            .order_by(AuditLog.created_at, AuditLog.id)
        ).all()
    )


def config_events(s, entity: str) -> int:
    return sum(
        1
        for e in s.scalars(sa.select(Event).where(Event.type == EventType.CONFIG_CHANGED)).all()
        if e.payload.get("entity") == entity
    )


def test_counsel_code_lifecycle(world):
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        edu = world.office(s, "EDU")
        row = mr.create_counsel_code(s, actor, admin, code="sc,edu", office=edu)
        assert row.code == "SC, EDU" and row.weight is None
        with pytest.raises(mr.DuplicateRule):
            mr.create_counsel_code(s, actor, admin, code="SC, EDU", office=edu)
        mr.update_counsel_code(s, actor, admin, row, office=world.office(s, "EDU-DSE"), notes="DSE cases")
        mr.update_counsel_code(s, actor, admin, row, notes="DSE cases")  # no change, nothing written
        mr.set_counsel_code_active(s, actor, admin, row, False)
        again = mr.create_counsel_code(s, actor, admin, code="SC, EDU", office=edu)
        assert again.id == row.id and again.is_active
        assert audit_actions(s, row.id) == [
            "counsel_code.create",
            "counsel_code.update",
            "counsel_code.deactivate",
            "counsel_code.reactivate",
        ]
        assert config_events(s, "counsel_code") == 4


def test_keyword_and_pattern_lifecycle(world):
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        edu = world.office(s, "EDU")
        kw = mr.create_keyword(s, actor, admin, keyword="Secondary  Education.", office=edu)
        assert kw.keyword == "SECONDARY EDUCATION"
        with pytest.raises(mr.DuplicateRule):
            mr.create_keyword(s, actor, admin, keyword="secondary education", office=edu)
        mr.set_keyword_active(s, actor, admin, kw, False)
        assert mr.create_keyword(s, actor, admin, keyword="secondary education", office=edu).id == kw.id
        assert audit_actions(s, kw.id) == ["keyword.create", "keyword.deactivate", "keyword.reactivate"]
        pat = mr.create_name_pattern(s, actor, admin, pattern="Director of Sec", kind="prefix", office=edu)
        assert pat.pattern == "DIRECTOR OF SEC" and PatternKind(pat.kind) == PatternKind.PREFIX
        rx = mr.create_name_pattern(s, actor, admin, pattern=r"COMMISSIONER.*EDU", kind="regex", office=edu)
        assert rx.pattern == r"COMMISSIONER.*EDU"
        for bad in ("(unclosed", ".*", "A" * 301):
            with pytest.raises(mr.RuleError):
                mr.create_name_pattern(s, actor, admin, pattern=bad, kind="regex", office=edu)
        mr.set_name_pattern_active(s, actor, admin, pat, False)
        mr.set_name_pattern_active(s, actor, admin, pat, True)
        assert audit_actions(s, pat.id) == [
            "name_pattern.create",
            "name_pattern.deactivate",
            "name_pattern.reactivate",
        ]
        assert config_events(s, "keyword") == 3 and config_events(s, "name_pattern") == 4


def test_scope_and_generic_codes(world):
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        with pytest.raises(access.Forbidden):
            mr.create_counsel_code(s, actor, admin, code="SC, HEALTH", office=world.office(s, "HEALTH"))
        row = mr.create_counsel_code(s, actor, admin, code="SC, DSE", office=world.office(s, "EDU-DSE"))
        assert row.office_id == world.offices["EDU-DSE"].id
        with pytest.raises(access.Forbidden):
            mr.create_counsel_code(
                s, actor, admin, code="GA, ASSAM", office=world.office(s, "GOA"), is_generic_state=True
            )
        o_actor, officer = world.actor(s, "edu_off1")
        with pytest.raises(access.Forbidden):
            mr.create_counsel_code(s, o_actor, officer, code="SC, X", office=world.office(s, "EDU"))
        r_actor, root = world.actor(s, "root")
        generic = mr.create_counsel_code(
            s, r_actor, root, code="GA, ASSAM", office=world.office(s, "GOA"), is_generic_state=True
        )
        assert generic.is_generic_state
        with pytest.raises(mr.RuleError):
            mr.create_counsel_code(s, r_actor, root, code="SC, Y", office=world.office(s, "GOA"))
        listed = {c.code for c in mr.list_counsel_codes(s, admin)}
        assert listed == {"SC, DSE", "GA, ASSAM"}


def test_weight_overrides_need_admin_scoring(world):
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        edu = world.office(s, "EDU")
        row = mr.create_keyword(s, actor, admin, keyword="SCHOOL", office=edu)
        assert row.weight is None
        with pytest.raises(access.Forbidden):
            mr.create_keyword(s, actor, admin, keyword="COLLEGE", office=edu, weight=0.6)
        with pytest.raises(access.Forbidden):
            mr.update_keyword(s, actor, admin, row, weight=0.6)
        r_actor, root = world.actor(s, "root")
        mr.update_keyword(s, r_actor, root, row, weight=0.6)
        assert float(row.weight) == 0.6
        mr.update_keyword(s, r_actor, root, row, weight=None)
        assert row.weight is None
        for bad in (0, 1.2):
            with pytest.raises(mr.RuleError):
                mr.update_keyword(s, r_actor, root, row, weight=bad)
        s.commit()
        code = mr.create_counsel_code(s, r_actor, root, code="SC, EDU", office=edu)
        s.commit()
        with pytest.raises(sa.exc.IntegrityError, match="ck_counsel_codes_weight"):
            s.execute(sa.update(CounselCode).where(CounselCode.id == code.id).values(weight=1.5))
        s.rollback()


def test_watchlist(world):
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        with pytest.raises(mr.RuleError):
            mr.add_watch(s, actor, admin, cnr="ASHC0100001")
        row, queued = mr.add_watch(s, actor, admin, cnr="ashc010009992025", reason="contempt risk")
        assert queued and row.case_id is None and row.office_id == world.offices["EDU"].id
        items = s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.DOSSIER)).all()
        assert [i.ref for i in items] == ["ASHC010009992025"] and items[0].priority == 40
        case = make_case(s, cnr="ASHC010008882025")
        held, queued = mr.add_watch(s, actor, admin, cnr="ASHC010008882025")
        assert not queued and held.case_id == case.id
        (rec,) = s.scalars(sa.select(Recommendation).where(Recommendation.case_id == case.id)).all()
        assert rec.origin == RecommendationOrigin.WATCHLIST and float(rec.score) == 0.75
        with pytest.raises(mr.DuplicateRule):
            mr.add_watch(s, actor, admin, cnr="ASHC010008882025")
        mr.set_watch_active(s, actor, admin, held, False)
        assert (
            s.scalar(sa.select(Recommendation.status).where(Recommendation.id == rec.id)).value == "expired"
        )
        assert audit_actions(s, held.id) == ["watchlist.create", "watchlist.deactivate"]
        assert s.scalar(sa.select(sa.func.count()).select_from(OfficeWatchlist)) == 2
