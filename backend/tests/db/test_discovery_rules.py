"""Discoverable rules (design `department-discovery`, decision 1; owner's decisions of 14 Oct 2026): `discover`
defaults on for a discoverable keyword or exact / prefix pattern and off for a regex or a refused character; asking
it for those is `not_discoverable`; a save queues the term's first sweep (2025 to the current year, newest first, lane
`discovery`, priority 43) in the same transaction and audits `discover`; a second department's identical text costs
no second term or row; unticking queues nothing; a rule on an inactive office makes no term active."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.events import AuditLog
from aslms.domain.ops import FetchLane, FetchStatus
from aslms.domain.ownership import DiscoveryTerm
from aslms.services import discovery
from aslms.services import matching_rules as mr
from tests.db.discovery_support import party_rows, ref, years


def _audit_after(s, row_id, action):
    return s.scalar(sa.select(AuditLog.after).where(AuditLog.entity_id == row_id, AuditLog.action == action))


def test_defaults_and_refusals(world):
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        edu = world.office(s, "EDU")
        kw = mr.create_keyword(s, actor, admin, keyword="director of secondary education", office=edu)
        exact = mr.create_name_pattern(s, actor, admin, pattern="Pritam Saikia", kind="exact", office=edu)
        prefix = mr.create_name_pattern(s, actor, admin, pattern="Dr. R. Das", kind="prefix", office=edu)
        rx = mr.create_name_pattern(s, actor, admin, pattern=r"^PRITAM\s+SAIKIA$", kind="regex", office=edu)
        odd = mr.create_keyword(s, actor, admin, keyword="100% PASS", office=edu)
        assert (kw.discover, exact.discover, prefix.discover) == (True, True, True)
        assert prefix.pattern == "DR R DAS"
        assert (rx.discover, odd.discover) == (False, False)
        with pytest.raises(mr.NotDiscoverable):
            mr.create_name_pattern(s, actor, admin, pattern=r"^RAJ", kind="regex", office=edu, discover=True)
        with pytest.raises(mr.NotDiscoverable):
            mr.update_name_pattern(s, actor, admin, rx, discover=True)
        with pytest.raises(mr.NotDiscoverable):
            mr.update_keyword(s, actor, admin, odd, discover=True)
        with pytest.raises(mr.NotDiscoverable):
            mr.create_keyword(s, actor, admin, keyword="AB", office=edu, discover=True)
        # chosen off on create: no term, no row
        off = mr.create_keyword(s, actor, admin, keyword="SCHOOL TEACHERS", office=edu, discover=False)
        assert off.discover is False
        assert party_rows(s, "SCHOOL TEACHERS") == []
        assert _audit_after(s, kw.id, "keyword.create")["discover"] is True
        assert _audit_after(s, rx.id, "name_pattern.create")["discover"] is False
        s.rollback()


def test_save_queues_the_first_sweep(world):
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        row = mr.create_name_pattern(
            s, actor, admin, pattern="Pritam Saikia", kind="prefix", office=world.office(s, "EDU")
        )
        rows = party_rows(s, "PRITAM SAIKIA")
        assert [r.ref for r in rows] == [ref(y, "PRITAM SAIKIA") for y in years()]  # newest year first
        assert {(r.lane, r.priority, r.status) for r in rows} == {
            (FetchLane.DISCOVERY, 43, FetchStatus.PENDING)
        }
        assert all(r.requested_by is None for r in rows)
        term = s.scalar(sa.select(DiscoveryTerm).where(DiscoveryTerm.term == "PRITAM SAIKIA"))
        assert term is not None and term.full_sweep_queued_at is not None
        assert _audit_after(s, row.id, "name_pattern.create")["discover"] is True
        # the same text in a second department: no second term, no second row
        h_actor, h_admin = world.actor(s, "health_admin")
        mr.create_keyword(s, h_actor, h_admin, keyword="PRITAM SAIKIA", office=world.office(s, "HEALTH"))
        assert s.scalar(sa.select(sa.func.count()).select_from(DiscoveryTerm)) == 1
        assert len(party_rows(s, "PRITAM SAIKIA")) == len(years())
        assert [d.code for d in discovery.term_departments(s, "PRITAM SAIKIA")] == ["EDU", "HEALTH"]
        s.rollback()


def test_untick_and_deactivate_queue_nothing(world):
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        row = mr.create_keyword(s, actor, admin, keyword="RAJIB GOGOI", office=world.office(s, "EDU-DSE"))
        n = len(party_rows(s))
        mr.update_keyword(s, actor, admin, row, discover=False)
        after = _audit_after(s, row.id, "keyword.update")
        assert after["discover"] is False
        assert not discovery.is_active(s, "RAJIB GOGOI")
        assert len(party_rows(s)) == n
        mr.update_keyword(
            s, actor, admin, row, discover=True
        )  # ticked again: the first sweep was queued already
        assert len(party_rows(s)) == n and discovery.is_active(s, "RAJIB GOGOI")
        mr.set_keyword_active(s, actor, admin, row, False)
        assert not discovery.is_active(s, "RAJIB GOGOI") and len(party_rows(s)) == n
        s.rollback()


def test_a_rule_on_an_inactive_office_makes_no_term_active(world):
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        row = mr.create_keyword(s, actor, admin, keyword="ANIL BORA", office=world.office(s, "EDU-DHE"))
        assert discovery.is_active(s, "ANIL BORA")
        world.office(s, "EDU-DHE").is_active = False
        s.flush()
        assert not discovery.is_active(s, "ANIL BORA")
        world.office(s, "EDU-DHE").is_active = True
        world.office(s, "EDU").is_active = False  # the Department-tier ancestor
        s.flush()
        assert not discovery.is_active(s, "ANIL BORA")
        assert row.discover is True
        s.rollback()


def test_list_filter_by_discover(world):
    from aslms.domain.ownership import OfficeKeyword
    from aslms.domain.reference import Permission

    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        edu = world.office(s, "EDU")
        mr.create_keyword(s, actor, admin, keyword="PRITAM SAIKIA", office=edu)
        mr.create_keyword(s, actor, admin, keyword="SCHOOL", office=edu, discover=False)
        on = mr.list_rules(s, admin, OfficeKeyword, Permission.ADMIN_KEYWORDS, discover=True)
        off = mr.list_rules(s, admin, OfficeKeyword, Permission.ADMIN_KEYWORDS, discover=False)
        assert [r.keyword for r in on] == ["PRITAM SAIKIA"] and [r.keyword for r in off] == ["SCHOOL"]
        s.rollback()
