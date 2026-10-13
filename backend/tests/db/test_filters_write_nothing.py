"""Reading every filtered list writes no `audit_log` or `events` row (design portal-filters, decision 14: filtering
is reading, never audited)."""

from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa

from aslms.domain.events import AuditLog, Event
from tests.db import docs_support as ds
from tests.db import workflow_support as w
from tests.db.world import add_listing

EVERY = (
    "q=filter%20party&listed_from=2026-01-01&listed_to=2026-12-31&court_no=3&bench=saikia"
    "&next_from=2026-01-01&next_to=2026-12-31&case_type=WP(C)&year=2025&case_status=pending"
)


@pytest.fixture()
def api(world, tmp_path):
    w.widen(world)
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


def counts(world) -> tuple[int, int]:
    with world.Session() as s:
        return (
            int(s.scalar(sa.select(sa.func.count()).select_from(AuditLog)) or 0),
            int(s.scalar(sa.select(sa.func.count()).select_from(Event)) or 0),
        )


def test_filtered_lists_write_nothing(api, world):
    with world.Session() as s:
        case = w.claimed_case(s, world)
        case.petitioner_summary = "FILTER PARTY"
        add_listing(s, case, date(2026, 10, 1))
        s.commit()
    admin = w.login(api, "edu_admin")
    off1 = w.login(api, "edu_off1")
    before = counts(world)
    paths = [
        (admin, f"/inbox/recommended?{EVERY}"),
        (admin, f"/inbox/claimed?{EVERY}"),
        (admin, f"/inbox/pool?{EVERY}&scored_for=EDU&min_score=0.5"),
        (admin, f"/inbox/transfers?{EVERY}&other_office=HEALTH"),
        (off1, f"/custody/held?scope=me&{EVERY}&owner=EDU"),
        (admin, f"/custody/held?scope=owned&{EVERY}&owner=EDU"),
        (off1, f"/custody/sent?{EVERY}&owner=EDU"),
        (off1, f"/alerts?{EVERY}&owner=EDU"),
        (admin, f"/cases?{EVERY}&owner=EDU"),
        (admin, f"/cases/search?{EVERY}&owner=EDU"),
        (admin, "/reference/benches?days=400"),
    ]
    for headers, path in paths:
        r = api.get(path, headers=headers)
        assert r.status_code == 200, (path, r.text)
    assert counts(world) == before
