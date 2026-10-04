"""The offices and designations endpoints end to end: scope-filtered reads, the tree, creation and the 409 on a
duplicate code, the first department admin who then signs in and creates a directorate user, deactivation
refused with counts, designations for a department officer, and the audit rows every write leaves."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.events import AuditLog
from aslms.domain.org import Office
from aslms.domain.reference import OfficeKind, Role
from aslms.services.audit import Actor
from aslms.services.seed import seed_all
from aslms.services.users import create_user
from tests.db.conftest import wipe

PW = "correct-horse-battery"


@pytest.fixture()
def world(engine):
    """GOA > EDU > EDU-DSE, HEALTH; a super admin (GOA), a dept admin (EDU), a dept officer (EDU-DSE)."""
    with engine.begin() as conn:
        wipe(conn)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        seed_all(s)
        goa = s.scalar(sa.select(Office).where(Office.code == "GOA"))
        edu = Office(
            code="EDU", name="Education", kind=OfficeKind.DEPARTMENT, parent_id=goa.id, path="GOA/EDU"
        )
        health = Office(
            code="HEALTH", name="Health", kind=OfficeKind.DEPARTMENT, parent_id=goa.id, path="GOA/HEALTH"
        )
        s.add_all([edu, health])
        s.flush()
        dse = Office(
            code="EDU-DSE",
            name="Secondary Education",
            kind=OfficeKind.DIRECTORATE,
            parent_id=edu.id,
            path="GOA/EDU/EDU-DSE",
        )
        s.add(dse)
        s.flush()
        sys = Actor.system("test")
        create_user(
            s, sys, email="root@example.org", password=PW, full_name="Root", role=Role.SUPER_ADMIN, office=goa
        )
        create_user(
            s,
            sys,
            email="admin.edu@example.org",
            password=PW,
            full_name="EDU Admin",
            role=Role.DEPT_ADMIN,
            office=edu,
        )
        create_user(
            s,
            sys,
            email="officer@example.org",
            password=PW,
            full_name="Officer",
            role=Role.DEPT_OFFICER,
            office=dse,
        )
        s.commit()
    settings = Settings(
        _env_file=None,
        aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters",
        aslms_access_token_minutes=5,
    )
    app = create_app(settings, Session)
    with TestClient(app) as client:
        yield client, Session


def login(client: TestClient, email: str) -> dict:
    r = client.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def audit_actions(Session, entity_id=None) -> list[str]:
    with Session() as s:
        stmt = sa.select(AuditLog.action).order_by(AuditLog.created_at)
        if entity_id is not None:
            stmt = stmt.where(AuditLog.entity_id == entity_id)
        return list(s.scalars(stmt).all())


def test_reads_are_scoped(world):
    api, _ = world
    root = login(api, "root@example.org")
    admin = login(api, "admin.edu@example.org")
    tree = api.get("/admin/offices/tree", headers=root).json()
    assert (
        [n["code"] for n in tree] == ["GOA"] and tree[0]["tier"] == "state" and tree[0]["users_active"] == 1
    )
    kids = {n["code"]: n for n in tree[0]["children"]}
    assert set(kids) == {"EDU", "HEALTH"} and kids["EDU"]["tier"] == "department"
    assert [n["code"] for n in kids["EDU"]["children"]] == ["EDU-DSE"]
    assert kids["EDU"]["children"][0]["users_active"] == 1 and kids["EDU"]["children"][0]["depth"] == 2
    # the department admin's tree is rooted at EDU and never contains HEALTH
    tree = api.get("/admin/offices/tree", headers=admin).json()
    assert [n["code"] for n in tree] == ["EDU"] and "HEALTH" not in str(tree)
    assert [o["code"] for o in api.get("/admin/offices", headers=admin).json()] == ["EDU", "EDU-DSE"]
    assert [o["code"] for o in api.get("/admin/offices", headers=root).json()] == [
        "GOA",
        "EDU",
        "EDU-DSE",
        "HEALTH",
    ]
    assert [o["code"] for o in api.get("/admin/offices?kind=directorate", headers=root).json()] == ["EDU-DSE"]
    assert api.get("/admin/offices/HEALTH", headers=admin).status_code == 404
    assert api.get("/admin/offices/NOPE", headers=root).status_code == 404
    detail = api.get("/admin/offices/edu", headers=admin).json()
    assert detail["code"] == "EDU" and detail["parent_code"] == "GOA" and detail["tier"] == "department"
    assert detail["counts"] == {"children": 1, "users": 1, "ownership": 0, "custody": 0}
    assert detail["is_active"] is True and detail["valid_to"] is None
    # include_inactive needs offices.manage
    assert api.get("/admin/offices?include_inactive=true", headers=admin).status_code == 403
    assert api.get("/admin/offices/tree?include_inactive=true", headers=admin).status_code == 403
    assert api.get("/admin/offices?include_inactive=true", headers=root).status_code == 200
    # an officer without users.view sees nothing here
    officer = login(api, "officer@example.org")
    assert api.get("/admin/offices", headers=officer).status_code == 403
    me = api.get("/me", headers=officer).json()
    assert me["user"]["office"]["is_active"] is True and me["user"]["office"]["code"] == "EDU-DSE"


def test_create_patch_deactivate_reactivate(world):
    api, Session = world
    root = login(api, "root@example.org")
    admin = login(api, "admin.edu@example.org")
    body = {"code": "fin", "name": "Finance", "kind": "department", "parent_code": "goa"}
    r = api.post("/admin/offices", json=body, headers=root)
    assert r.status_code == 201, r.text
    fin = r.json()
    assert fin["code"] == "FIN" and fin["path"] == "GOA/FIN" and fin["tier"] == "department"
    assert api.post("/admin/offices", json=body, headers=root).status_code == 409
    assert (
        api.post(
            "/admin/offices", json={**body, "code": "X1", "parent_code": "NOPE"}, headers=root
        ).status_code
        == 400
    )
    r = api.post("/admin/offices", json={**body, "code": "X2", "kind": "directorate"}, headers=root)
    assert r.status_code == 400 and "cannot be placed" in r.json()["detail"]
    assert api.post("/admin/offices", json={**body, "code": "bad code"}, headers=root).status_code == 400
    assert (
        api.post("/admin/offices", json={**body, "code": "X3", "kind": "state"}, headers=root).status_code
        == 400
    )
    # the department admin lacks offices.manage → 403; with it they may add a unit inside EDU, not a department
    assert api.post("/admin/offices", json={**body, "code": "X4"}, headers=admin).status_code == 403
    admin_id = api.get("/me", headers=admin).json()["user"]["id"]
    r = api.put(f"/admin/users/{admin_id}/permissions/offices.manage", json={"effect": "grant"}, headers=root)
    assert r.status_code == 200
    assert api.post("/admin/offices", json={**body, "code": "X5"}, headers=admin).status_code == 403
    unit = {"code": "EDU-LEGAL", "name": "Legal cell", "kind": "unit", "parent_code": "EDU"}
    r = api.post("/admin/offices", json=unit, headers=admin)
    assert r.status_code == 201 and r.json()["path"] == "GOA/EDU/EDU-LEGAL"
    assert (
        api.post(
            "/admin/offices", json={**unit, "code": "H-X", "parent_code": "HEALTH"}, headers=admin
        ).status_code
        == 403
    )
    assert api.patch("/admin/offices/EDU", json={"name": "Mine"}, headers=admin).status_code == 403
    # patch: name, notes, valid_from only; code and kind are not accepted
    r = api.patch(
        "/admin/offices/FIN",
        json={"name": "Finance Department", "notes": "Dispur", "valid_from": "2001-04-01", "code": "ZZZ"},
        headers=root,
    )
    assert r.status_code == 200 and r.json()["name"] == "Finance Department" and r.json()["code"] == "FIN"
    assert r.json()["notes"] == "Dispur" and r.json()["valid_from"] == "2001-04-01"
    # deactivate FIN (no dependants), then it is hidden from the default list and shown with the flag
    r = api.post("/admin/offices/FIN/deactivate", headers=root)
    assert r.status_code == 200 and r.json()["is_active"] is False and r.json()["valid_to"] is not None
    codes = [o["code"] for o in api.get("/admin/offices", headers=root).json()]
    assert "FIN" not in codes
    codes = [o["code"] for o in api.get("/admin/offices?include_inactive=true", headers=root).json()]
    assert "FIN" in codes
    assert (
        api.post(
            "/admin/offices", json={**unit, "code": "FIN-X", "parent_code": "FIN"}, headers=root
        ).status_code
        == 400
    )
    assert api.get("/admin/offices/FIN", headers=admin).status_code == 404
    assert api.get("/admin/offices/FIN", headers=root).json()["is_active"] is False
    r = api.post("/admin/offices/FIN/reactivate", headers=root)
    assert r.status_code == 200 and r.json()["is_active"] is True and r.json()["valid_to"] is None
    assert api.post("/admin/offices/GOA/deactivate", headers=root).status_code == 400
    # audit rows per entity
    assert audit_actions(Session, fin["id"]) == [
        "office.create",
        "office.update",
        "office.deactivate",
        "office.reactivate",
    ]
    assert audit_actions(Session, r.json()["id"]).count("office.create") == 1


def test_first_department_admin_then_deactivation_with_counts(world):
    api, Session = world
    root = login(api, "root@example.org")
    admin = login(api, "admin.edu@example.org")
    r = api.post(
        "/admin/offices",
        json={"code": "FIN", "name": "Finance", "kind": "department", "parent_code": "GOA"},
        headers=root,
    )
    fin_id = r.json()["id"]
    nodal = {
        "email": "nodal.fin@example.org",
        "password": PW,
        "full_name": "Nodal Officer",
        "designation": "Joint Secretary",
    }
    assert (
        api.post("/admin/offices/FIN/admins", json=nodal, headers=admin).status_code == 404
    )  # outside scope
    assert (
        api.post(
            "/admin/offices/EDU/admins", json={**nodal, "email": "a2@example.org"}, headers=admin
        ).status_code
        == 403
    )
    assert (
        api.post("/admin/offices/EDU-DSE/admins", json=nodal, headers=root).status_code == 400
    )  # directorate tier
    r = api.post("/admin/offices/FIN/admins", json=nodal, headers=root)
    assert r.status_code == 201, r.text
    new_admin = r.json()
    assert new_admin["role"] == "dept_admin" and new_admin["office"]["code"] == "FIN"
    assert new_admin["must_confirm_profile"] is True
    assert (
        api.post("/admin/offices/FIN/admins", json=nodal, headers=root).status_code == 400
    )  # duplicate e-mail
    assert [u["email"] for u in api.get("/admin/offices/FIN/admins", headers=root).json()] == [
        "nodal.fin@example.org"
    ]
    assert api.get("/admin/offices/FIN/admins", headers=admin).status_code == 404
    # the new admin signs in, sees a tree rooted at FIN, and creates a directorate and its user
    fin_admin = login(api, "nodal.fin@example.org")
    me = api.get("/me", headers=fin_admin).json()
    assert me["user"]["role"] == "dept_admin" and "users.create" in me["functions"]
    assert [n["code"] for n in api.get("/admin/offices/tree", headers=fin_admin).json()] == ["FIN"]
    assert (
        api.post(
            "/admin/offices",
            json={"code": "FIN-X", "name": "x", "kind": "unit", "parent_code": "FIN"},
            headers=fin_admin,
        ).status_code
        == 403
    )
    r = api.post(
        "/admin/offices",
        json={"code": "FIN-DT", "name": "Treasuries", "kind": "directorate", "parent_code": "FIN"},
        headers=root,
    )
    assert r.status_code == 201
    r = api.post(
        "/admin/users",
        json={
            "email": "dt@example.org",
            "password": PW,
            "full_name": "DT User",
            "role": "directorate_user",
            "office_code": "FIN-DT",
        },
        headers=fin_admin,
    )
    assert r.status_code == 201, r.text
    # deactivating FIN is refused with the counts; after disabling the users and the directorate it succeeds
    r = api.post("/admin/offices/FIN/deactivate", headers=root)
    assert r.status_code == 409 and r.json()["detail"]["counts"] == {
        "children": 1,
        "users": 1,
        "ownership": 0,
        "custody": 0,
    }
    r = api.post("/admin/offices/FIN-DT/deactivate", headers=root)
    assert r.status_code == 409 and r.json()["detail"]["counts"]["users"] == 1
    dt_id = [
        u for u in api.get("/admin/users?office=FIN", headers=root).json() if u["email"] == "dt@example.org"
    ][0]["id"]
    assert api.post(f"/admin/users/{dt_id}/disable", headers=root).status_code == 200
    assert api.post("/admin/offices/FIN-DT/deactivate", headers=root).status_code == 200
    assert api.post(f"/admin/users/{new_admin['id']}/disable", headers=root).status_code == 200
    r = api.post("/admin/offices/FIN/deactivate", headers=root)
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert api.get("/me", headers=fin_admin).status_code == 401
    assert audit_actions(Session, fin_id) == ["office.create", "office.admin_added", "office.deactivate"]
    assert audit_actions(Session, new_admin["id"]) == ["user.create", "auth.login", "user.disable"]


def test_designations(world):
    api, Session = world
    root = login(api, "root@example.org")
    officer = login(api, "officer@example.org")
    rows = api.get("/admin/designations", headers=officer).json()
    assert len(rows) == 18 and rows[0]["code"] == "CS" and all(d["is_active"] for d in rows)
    assert api.get("/admin/designations?include_inactive=true", headers=officer).status_code == 403
    assert (
        api.post(
            "/admin/designations", json={"code": "OSD", "name": "Officer on Special Duty"}, headers=officer
        ).status_code
        == 403
    )
    r = api.post("/admin/designations", json={"code": "osd", "name": "Officer on Special Duty"}, headers=root)
    assert r.status_code == 201 and r.json()["code"] == "OSD" and r.json()["sort_order"] == 190
    osd_id = r.json()["id"]
    assert (
        api.post("/admin/designations", json={"code": "OSD", "name": "again"}, headers=root).status_code
        == 409
    )
    assert (
        api.post("/admin/designations", json={"code": "O S D", "name": "x"}, headers=root).status_code == 400
    )
    assert len(api.get("/admin/designations", headers=officer).json()) == 19
    r = api.patch("/admin/designations/osd", json={"name": "OSD (Legal)", "sort_order": 5}, headers=root)
    assert r.status_code == 200 and r.json()["name"] == "OSD (Legal)"
    assert api.get("/admin/designations", headers=officer).json()[0]["code"] == "OSD"
    assert api.patch("/admin/designations/NOPE", json={"name": "x"}, headers=root).status_code == 404
    r = api.post("/admin/designations/OSD/deactivate", headers=root)
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert len(api.get("/admin/designations", headers=officer).json()) == 18
    assert len(api.get("/admin/designations?include_inactive=true", headers=root).json()) == 19
    assert api.post("/admin/designations/OSD/deactivate", headers=root).status_code == 400
    assert api.post("/admin/designations/OSD/reactivate", headers=root).status_code == 200
    assert audit_actions(Session, osd_id) == [
        "designation.create",
        "designation.update",
        "designation.deactivate",
        "designation.reactivate",
    ]


# --- added by the tester: negative paths the first pass did not cover -------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/admin/offices"),
        ("get", "/admin/offices/tree"),
        ("get", "/admin/offices/EDU"),
        ("post", "/admin/offices"),
        ("patch", "/admin/offices/EDU"),
        ("post", "/admin/offices/EDU/deactivate"),
        ("post", "/admin/offices/EDU/reactivate"),
        ("get", "/admin/offices/EDU/admins"),
        ("post", "/admin/offices/EDU/admins"),
        ("get", "/admin/designations"),
        ("post", "/admin/designations"),
    ],
)
def test_unauthenticated_requests_get_401(world, method, path):
    api, _ = world
    assert getattr(api, method)(path).status_code == 401


def test_dept_officer_cannot_write_offices_or_see_inactive(world):
    api, Session = world
    officer = login(api, "officer@example.org")
    body = {"code": "NEW", "name": "New", "kind": "unit", "parent_code": "EDU-DSE"}
    assert api.post("/admin/offices", json=body, headers=officer).status_code == 403
    assert api.patch("/admin/offices/EDU-DSE", json={"name": "x"}, headers=officer).status_code in (403, 404)
    assert api.post("/admin/offices/EDU-DSE/deactivate", headers=officer).status_code in (403, 404)
    assert api.get("/admin/offices?include_inactive=true", headers=officer).status_code == 403
    assert "office.create" not in audit_actions(Session)


def test_dept_admin_cannot_add_admin_to_directorate_or_other_department(world):
    api, Session = world
    admin = login(api, "admin.edu@example.org")
    root = login(api, "root@example.org")
    body = {"email": "x@example.org", "full_name": "Xavier", "password": PW, "designation": "Joint Secretary"}
    assert api.post("/admin/offices/EDU/admins", json=body, headers=admin).status_code == 403
    assert api.post("/admin/offices/HEALTH/admins", json=body, headers=admin).status_code == 404
    assert api.post("/admin/offices/EDU-DSE/admins", json=body, headers=root).status_code in (400, 409)
    assert "office.admin_added" not in audit_actions(Session)


def test_failed_writes_leave_no_audit_rows(world):
    api, Session = world
    root = login(api, "root@example.org")
    before = audit_actions(Session)
    bad = {"code": "x y", "name": "Bad", "kind": "department", "parent_code": "GOA"}
    assert api.post("/admin/offices", json=bad, headers=root).status_code in (400, 422)
    assert api.post("/admin/offices/NOPE/deactivate", headers=root).status_code == 404
    assert api.patch("/admin/offices/NOPE", json={"name": "x"}, headers=root).status_code == 404
    assert audit_actions(Session) == before
