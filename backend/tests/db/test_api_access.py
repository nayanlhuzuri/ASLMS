"""The API slice end to end against the test database: login, tokens, `/me`, and the user and access
endpoints under the delegation rule."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.org import Office
from aslms.domain.reference import OfficeKind, Role
from aslms.services.audit import Actor
from aslms.services.seed import seed_all
from aslms.services.users import create_user
from tests.db.auth_support import last_code, mailer_of, ready_all, sign_in
from tests.db.conftest import wipe

PW = "correct-horse-battery-7"


@pytest.fixture()
def api(engine):
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
        ready_all(s)
        s.commit()
    settings = Settings(
        _env_file=None,
        aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters",
        aslms_access_token_minutes=5,
    )
    app = create_app(settings, Session)
    with TestClient(app) as client:
        yield client


def login(client: TestClient, email: str) -> dict:
    tok = sign_in(client, email, PW)
    return {"Authorization": f"Bearer {tok['access_token']}", "_refresh": tok["refresh_token"]}


def test_login_me_refresh_logout(api):
    """Two steps (design otp-and-profile): the password gives a challenge and no token; the e-mailed code gives
    the tokens; refresh rotates; a rotated token presented again ends every session; logout revokes."""
    assert api.get("/health").json()["status"] == "ok"
    assert api.get("/me").status_code == 401
    mailer = mailer_of(api)
    r = api.post("/auth/login", json={"email": "root@example.org", "password": "wrong-password-1"})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "invalid_credentials"
    step = api.post("/auth/login", json={"email": "root@example.org", "password": PW})
    assert step.status_code == 200
    body = step.json()
    assert body["step"] == "otp" and body["purpose"] == "login" and "access_token" not in body
    assert body["sent_to"] == "r***@example.org" and body["expires_in"] == 600 and body["resend_after"] == 120
    assert mailer.sent[-1].to == "root@example.org" and mailer.sent[-1].subject == "ASLMS sign-in code"
    v = api.post(
        "/auth/otp/verify",
        json={"challenge_id": body["challenge_id"], "code": last_code(api, "root@example.org")},
    )
    assert v.status_code == 200, v.text
    tok = v.json()
    assert tok["next_step"] == "ready" and tok["device_token"]
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    me = api.get("/me", headers=h).json()
    assert me["user"]["role"] == "super_admin" and me["user"]["office"]["code"] == "GOA"
    assert me["user"]["must_change_password"] is False
    assert len(me["functions"]) == 48
    r = api.post("/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 200 and r.json()["refresh_token"] != tok["refresh_token"]
    new = r.json()
    # the rotated token again: theft is assumed, every session of the login ends
    r = api.post("/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "session_ended"
    assert api.post("/auth/refresh", json={"refresh_token": new["refresh_token"]}).status_code == 401
    # a fresh sign-in, then logout
    again = sign_in(api, "root@example.org", PW, device_token=tok["device_token"])
    assert again["device_token"] is None  # a known device gets no new token
    r = api.post(
        "/auth/logout",
        json={"refresh_token": again["refresh_token"]},
        headers={"Authorization": f"Bearer {again['access_token']}"},
    )
    assert r.status_code == 204
    r = api.post("/auth/refresh", json={"refresh_token": again["refresh_token"]})
    assert r.status_code == 401
    assert api.get("/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_department_admin_creates_users_within_scope(api):
    admin = {"Authorization": login(api, "admin.edu@example.org")["Authorization"]}
    me = api.get("/me", headers=admin).json()
    assert "users.create" in me["functions"] and "access.manage_types" not in me["functions"]
    # an officer in the directorate: allowed
    body = {
        "email": "officer@example.org",
        "password": PW,
        "full_name": "Officer One",
        "role": "dept_officer",
        "office_code": "EDU-DSE",
    }
    r = api.post("/admin/users", json=body, headers=admin)
    assert r.status_code == 201, r.text
    officer_id = r.json()["id"]
    assert r.json()["office"]["path"] == "GOA/EDU/EDU-DSE"
    # outside the department: refused
    r = api.post(
        "/admin/users", json={**body, "email": "h@example.org", "office_code": "HEALTH"}, headers=admin
    )
    assert r.status_code == 403 and "outside" in r.json()["detail"]
    # an admin type: refused
    r = api.post(
        "/admin/users", json={**body, "email": "a2@example.org", "role": "dept_admin"}, headers=admin
    )
    assert r.status_code == 403
    # a function the admin does not hold: refused; one they hold: granted at creation
    r = api.post(
        "/admin/users",
        json={**body, "email": "x@example.org", "functions": ["access.manage_types"]},
        headers=admin,
    )
    assert r.status_code == 403
    r = api.post(
        "/admin/users", json={**body, "email": "y@example.org", "functions": ["cases.claim"]}, headers=admin
    )
    assert r.status_code == 201
    fx = api.get(f"/admin/users/{r.json()['id']}/permissions", headers=admin).json()
    assert "cases.claim" in fx["functions"] and fx["overrides"][0]["effect"] == "grant"
    # the officer signs in and lacks the admin functions
    officer = {"Authorization": login(api, "officer@example.org")["Authorization"]}
    assert "users.create" not in api.get("/me", headers=officer).json()["functions"]
    assert (
        api.post("/admin/users", json={**body, "email": "z@example.org"}, headers=officer).status_code == 403
    )
    assert api.get("/admin/users", headers=officer).status_code == 403
    # the admin's list shows only the department tree
    emails = {u["email"] for u in api.get("/admin/users", headers=admin).json()}
    assert emails == {"admin.edu@example.org", "officer@example.org", "y@example.org"}
    # deny a function, then disable the officer
    r = api.put(
        f"/admin/users/{officer_id}/permissions/notes.add",
        json={"effect": "deny", "reason": "on leave"},
        headers=admin,
    )
    assert r.status_code == 200 and "notes.add" not in r.json()["functions"]
    r = api.post(f"/admin/users/{officer_id}/disable", headers=admin)
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert api.post("/auth/login", json={"email": "officer@example.org", "password": PW}).status_code == 401
    assert api.get("/me", headers=officer).status_code == 401
    # the matrix is the super admin's: 403 for the admin, 200 for root
    assert (
        api.put(
            "/admin/access/types/dept_officer/notes.add", json={"enabled": False}, headers=admin
        ).status_code
        == 403
    )
    root = {"Authorization": login(api, "root@example.org")["Authorization"]}
    r = api.put("/admin/access/types/dept_officer/notes.add", json={"enabled": False}, headers=root)
    assert r.status_code == 200 and r.json()["notes.add"] is False
    assert (
        api.put(
            "/admin/access/types/super_admin/notes.add", json={"enabled": False}, headers=root
        ).status_code
        == 403
    )
    perms = api.get("/admin/permissions", headers=root).json()
    assert len(perms) == 50 and {p["module"] for p in perms} >= {"users", "cases", "notes"}
    # root sees everyone; audit rows exist for the changes
    assert len(api.get("/admin/users", headers=root).json()) == 4
    assert api.get("/admin/offices", headers=admin).json()[0]["code"] == "EDU"
    assert len(api.get("/admin/offices", headers=root).json()) == 4
