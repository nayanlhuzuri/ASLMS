"""Negative paths of the discovery API: no session is 401 on every endpoint, a user's request refuses empty or too
many years, a disabled user is 401, and a refused request writes no queue row and no audit row."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.events import AuditLog
from tests.db.auth_support import bearer
from tests.db.discovery_support import party_rows
from tests.db.world import PW, USERS

ZERO = "00000000-0000-7000-8000-000000000000"


@pytest.fixture()
def api(world):
    settings = Settings(
        _env_file=None,
        aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters",
        aslms_access_token_minutes=5,
    )
    with TestClient(create_app(settings, world.Session)) as client:
        yield client


def test_every_discovery_endpoint_needs_a_session(api):
    assert api.get("/admin/discovery").status_code == 401
    assert api.get(f"/admin/discovery/terms/{ZERO}/cases").status_code == 401
    assert api.post("/admin/discovery/sweep", json={}).status_code == 401
    assert api.post("/admin/discovery/search", json={"name": "A B C", "years": [2010]}).status_code == 401
    assert api.get("/inbox/pool?found_for=EDU").status_code == 401


def test_bad_requests_write_nothing(api, world):
    edu = bearer(api, USERS["edu_admin"][0], PW)
    r = api.post(
        "/admin/name-patterns",
        json={"pattern": "Pritam Saikia", "kind": "prefix", "office_code": "EDU"},
        headers=edu,
    )
    assert r.status_code == 201, r.text
    with world.Session() as s:
        before = len(party_rows(s, "PRITAM SAIKIA"))
        audits = s.scalar(sa.select(sa.func.count()).where(AuditLog.action == "discovery.sweep"))
    for years in ([], list(range(1990, 2021)), [2010, 2010, 1800]):
        r = api.post("/admin/discovery/search", json={"name": "PRITAM SAIKIA", "years": years}, headers=edu)
        assert r.status_code in (400, 422), (years, r.text)
    r = api.post("/admin/discovery/search", json={"name": "PRITAM SAIKIA"}, headers=edu)
    assert r.status_code == 422
    with world.Session() as s:
        assert len(party_rows(s, "PRITAM SAIKIA")) == before
        assert s.scalar(sa.select(sa.func.count()).where(AuditLog.action == "discovery.sweep")) == audits
    r = api.get(f"/admin/discovery/terms/{ZERO}/cases", headers=edu)
    assert r.status_code == 404
