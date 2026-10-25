"""`/audit` (design `audit-screens`, decisions 1-3): who may read the log (`audit.view` in a State-wide membership),
the error codes, the row detail, the action list and that reading writes nothing."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from aslms.domain.events import AuditLog
from aslms.domain.org import PermissionEffect
from aslms.domain.reference import Permission
from aslms.services import access
from aslms.services import ownership as own
from tests.db import docs_support as ds
from tests.db.world import make_case


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture()
def claimed(world):
    with world.Session() as s:
        case = make_case(s)
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, case)
        s.commit()
        return {"id": case.id, "ref_no": case.ref_no, "cnr": case.cnr}


def _override(world, key: str, perm: Permission, effect: PermissionEffect) -> None:
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        access.set_override(s, actor, root, world.user(s, key), perm, effect, reason="test")
        s.commit()


def _count(world) -> int:
    with world.Session() as s:
        return s.scalar(sa.select(sa.func.count()).select_from(AuditLog))


def test_audit_scope(api, world, claimed):
    for key in ("edu_auditor", "root"):
        r = api.get("/audit", headers=ds.login(api, key))
        assert r.status_code == 200, (key, r.text)
    for key in ("edu_off1", "oversight", "central_op", "edu_admin"):
        r = api.get("/audit", headers=ds.login(api, key))
        assert r.status_code == 403, key
    # a department officer granted audit.view: not State-wide
    _override(world, "edu_off1", Permission.AUDIT_VIEW, PermissionEffect.GRANT)
    r = api.get("/audit", headers=ds.login(api, "edu_off1"))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "audit_scope"
    for path in ("/audit/actions", f"/audit/{uuid.uuid4()}"):
        assert api.get(path, headers=ds.login(api, "edu_off1")).json()["detail"]["code"] == "audit_scope"
    # an auditor whose membership is denied cases.view_all
    _override(world, "edu_auditor", Permission.CASES_VIEW_ALL, PermissionEffect.DENY)
    r = api.get("/audit", headers=ds.login(api, "edu_auditor"))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "audit_scope"


def test_search_by_case_and_detail(api, world, claimed):
    h = ds.login(api, "edu_auditor")
    r = api.get("/audit", params={"case": claimed["ref_no"].replace("/", "-")}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["next_cursor"] is None
    claim = next(i for i in body["items"] if i["action"] == "ownership.claim")
    assert claim["case"] == {
        "id": str(claimed["id"]),
        "ref_no": claimed["ref_no"],
        "cnr": claimed["cnr"],
        "case_no_text": claim["case"]["case_no_text"],
    }
    assert claim["actor"]["office_code"] == "EDU" and claim["at"].endswith("+05:30")
    one = api.get(f"/audit/{claim['id']}", headers=h)
    assert one.status_code == 200 and one.json() == claim
    missing = api.get(f"/audit/{uuid.uuid4()}", headers=h)
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "not_found"


def test_office_subtree_param(api, world, claimed):
    """Design `portal-ui-polish-2`, decision 30: `office_subtree=false` narrows to the office alone."""
    h = ds.login(api, "edu_auditor")
    params = {"office": "GOA", "action": "ownership.claim"}
    whole = api.get("/audit", params=params, headers=h)
    assert [i["actor"]["office_code"] for i in whole.json()["items"]] == ["EDU"]
    only = api.get("/audit", params={**params, "office_subtree": "false"}, headers=h)
    assert only.status_code == 200 and only.json()["items"] == []
    exact = api.get(
        "/audit", params={"office": "EDU", "action": "ownership.claim", "office_subtree": "false"}, headers=h
    )
    assert len(exact.json()["items"]) == 1


def test_paging_through_the_api(api, world):
    with world.Session() as s:
        at = datetime(2026, 10, 2, 5, 0, tzinfo=UTC)
        for _ in range(3):
            s.add(AuditLog(created_at=at, action="test.api_page", entity_type="test", actor_name="T"))
        s.commit()
    h = ds.login(api, "edu_auditor")
    first = api.get("/audit", params={"action": "test.api_page", "limit": 2}, headers=h).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = api.get(
        "/audit", params={"action": "test.api_page", "limit": 2, "cursor": first["next_cursor"]}, headers=h
    ).json()
    assert len(second["items"]) == 1 and second["next_cursor"] is None
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}
    prefix = api.get("/audit", params={"action": "test.", "limit": 200}, headers=h).json()
    assert len(prefix["items"]) == 3


def test_unknown_user_400_unknown_case_404(api, world, claimed):
    h = ds.login(api, "edu_auditor")
    cases = [
        ({"user": "nobody@example.org"}, 400, "unknown_user"),
        ({"about_user": str(uuid.uuid4())}, 400, "unknown_user"),
        ({"office": "NOWHERE"}, 400, "bad_office"),
        ({"cursor": "garbage"}, 400, "bad_cursor"),
        ({"from": "2026-10-09", "to": "2026-10-08"}, 400, "bad_period"),
        ({"case": "ASHC019999992099"}, 404, "not_found"),
    ]
    for params, code, name in cases:
        r = api.get("/audit", params=params, headers=h)
        assert r.status_code == code and r.json()["detail"]["code"] == name, (params, r.text)
    assert api.get("/audit", params={"limit": 0}, headers=h).status_code == 422
    assert api.get("/audit", params={"limit": 201}, headers=h).status_code == 422
    assert api.get("/audit", params={"actor": "x"}, headers=h).status_code == 422
    ok = api.get("/audit", params={"user": "ADMIN.edu@example.org"}, headers=h)
    assert ok.status_code == 200 and {i["action"] for i in ok.json()["items"]} >= {"ownership.claim"}


def test_actions_and_reading_writes_nothing(api, world, claimed):
    h = ds.login(api, "edu_auditor")
    before = _count(world)
    actions = api.get("/audit/actions", headers=h)
    assert actions.status_code == 200 and "ownership.claim" in actions.json()["actions"]
    page = api.get("/audit", params={"case": claimed["cnr"]}, headers=h).json()
    api.get(f"/audit/{page['items'][0]['id']}", headers=h)
    api.get("/audit", params={"from": "2026-01-01", "to": "2026-12-31", "action": "ownership."}, headers=h)
    assert _count(world) == before


def test_search_timeout_is_503(api, world, monkeypatch):
    from aslms.api.routers import audit as router
    from aslms.services import audit_search

    def boom(*a, **kw):
        raise audit_search.SearchTimeout("the search took too long; narrow the search")

    monkeypatch.setattr(router.svc, "search", boom)
    r = api.get("/audit", headers=ds.login(api, "edu_auditor"))
    assert r.status_code == 503 and r.json()["detail"]["code"] == "search_timeout"
