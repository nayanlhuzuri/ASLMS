"""The weekly discovery job and the manual sweep (design `department-discovery`, decisions 5 and 12; owner's decision
of 14 Oct 2026: 2025 to the current year): every active term is queued again at 42 (`done` rows revived, pending
rows keep their place), a ticked rule without a term row gets one, inactive terms get nothing; the manual sweep needs
`admin.data_load`, is audited `discovery.sweep` and refuses an inactive term."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.events import AuditLog
from aslms.domain.ops import FetchStatus
from aslms.domain.ownership import DiscoveryTerm, OfficeKeyword
from aslms.services import access, discovery
from aslms.services import matching_rules as mr
from tests.db.discovery_support import party_rows, years


def test_weekly_requeues_active_terms_only(world):
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        edu = world.office(s, "EDU")
        a = mr.create_keyword(s, actor, admin, keyword="PRITAM SAIKIA", office=edu)
        b = mr.create_keyword(s, actor, admin, keyword="RAJIB GOGOI", office=edu)
        for r in party_rows(s, "PRITAM SAIKIA"):
            r.status = FetchStatus.DONE
        mr.set_keyword_active(s, actor, admin, b, False)
        # a ticked rule written before any term existed (as after the migration): the job creates its term
        s.add(OfficeKeyword(office_id=edu.id, keyword="ANIL BORA", discover=True))
        s.flush()
        out = discovery.enqueue_weekly(s)
        assert out == {"terms": 2, "rows_queued": 2 * len(years()), "years": len(years())}
        pritam = party_rows(s, "PRITAM SAIKIA")
        assert {(r.status, r.priority) for r in pritam} == {(FetchStatus.PENDING, 42)}
        assert {r.status for r in party_rows(s, "RAJIB GOGOI")} == {
            FetchStatus.PENDING
        }  # left from its first sweep
        anil = s.scalar(sa.select(DiscoveryTerm).where(DiscoveryTerm.term == "ANIL BORA"))
        assert anil.full_sweep_queued_at is not None and anil.recent_sweep_queued_at is not None
        assert len(party_rows(s, "ANIL BORA")) == len(years())
        rajib = s.scalar(sa.select(DiscoveryTerm).where(DiscoveryTerm.term == "RAJIB GOGOI"))
        assert rajib.recent_sweep_queued_at is None
        assert a.discover
        s.rollback()


def test_manual_sweep(world):
    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        mr.create_keyword(s, actor, admin, keyword="PRITAM SAIKIA", office=world.office(s, "EDU"))
        with pytest.raises(access.Forbidden):
            discovery.sweep(s, actor, admin)  # a department admin has no admin.data_load
        r_actor, root = world.actor(s, "root")
        for r in party_rows(s):
            r.status = FetchStatus.DONE
        s.flush()
        out = discovery.sweep(s, r_actor, root)
        assert out == {"terms": 1, "rows_queued": len(years())}
        audit = s.scalar(sa.select(AuditLog).where(AuditLog.action == "discovery.sweep"))
        assert audit.after["scope"] == "all" and audit.after["rows_queued"] == len(years())
        term = s.scalar(sa.select(DiscoveryTerm))
        out = discovery.sweep(s, r_actor, root, term_id=term.id)
        assert out == {"terms": 1, "rows_queued": len(years())}  # pending rows count as queued
        row = s.scalars(sa.select(OfficeKeyword)).one()
        mr.set_keyword_active(s, actor, admin, row, False)
        with pytest.raises(discovery.DiscoveryConflict) as exc:
            discovery.sweep(s, r_actor, root, term_id=term.id)
        assert exc.value.code == "term_inactive"
        import uuid

        with pytest.raises(discovery.DiscoveryNotFound):
            discovery.sweep(s, r_actor, root, term_id=uuid.uuid4())
        s.rollback()
