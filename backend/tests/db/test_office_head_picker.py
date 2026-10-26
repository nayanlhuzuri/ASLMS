"""The head of a department chosen from current logins, and logins with no office yet (design `office-head-picker`,
"Tests"): `head.user_id` / `head.email` name an existing login only, checked before anything is written; one person
heads several departments; the department admin is never touched; the Super Administrator creates a login with no
office (`office_code` and `role` null), which lists in Users, signs in, sees nothing, receives nothing, and gets its
first office as head or through Add Office; `ck_users_placed` keeps the mirror pair together."""

from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from aslms.domain.alerts import Digest, Notification
from aslms.domain.cases import Case
from aslms.domain.events import AuditLog, Event
from aslms.domain.org import Designation, Office, User, UserMembership
from aslms.domain.reference import EventType, Role
from aslms.domain.tickets import AdminTicket
from aslms.services import access, alerts, memberships, notifications, tickets
from tests.db import alerts_support as h
from tests.db.auth_support import sign_in
from tests.db.docs_support import login, make_api
from tests.db.world import PW, make_case

EMPTY_FP = hashlib.sha256(b"").hexdigest()  # the exit fingerprint of a membership holding nothing
NEW_PW = "given-by-root-1"


@pytest.fixture()
def api(world, tmp_path):
    return make_api(world, tmp_path)


def auth_headers(tok: dict) -> dict:
    return {"Authorization": f"Bearer {tok['access_token']}"}


def uid(world, key: str) -> str:
    return str(world.users[key].id)


def designation_id(world, code: str = "SEC") -> str:
    with world.Session() as s:
        return str(s.scalar(sa.select(Designation.id).where(Designation.code == code)))


def department(api, headers, code: str, head: dict | None, **extra):
    body = {"code": code, "name": f"Department {code}", "kind": "department", "parent_code": "GOA", **extra}
    if head is not None:
        body["head"] = head
    return api.post("/admin/offices", json=body, headers=headers)


def new_login(api, root, email: str = "waiting@example.org", name: str = "Waiting Person") -> dict:
    r = api.post(
        "/admin/users",
        json={"email": email, "password": NEW_PW, "full_name": name, "office_code": None, "role": None},
        headers=root,
    )
    assert r.status_code == 201, r.text
    return r.json()


def actions(world, entity_id) -> list[str]:
    with world.Session() as s:
        return list(
            s.scalars(
                sa.select(AuditLog.action)
                .where(AuditLog.entity_id == entity_id)
                .order_by(AuditLog.created_at)
            ).all()
        )


def office_exists(world, code: str) -> bool:
    with world.Session() as s:
        return s.scalar(sa.select(Office.id).where(Office.code == code)) is not None


def active_memberships(world, user_id) -> list[UserMembership]:
    with world.Session() as s:
        return list(
            s.scalars(
                sa.select(UserMembership).where(
                    UserMembership.user_id == user_id, UserMembership.is_active.is_(True)
                )
            ).all()
        )


# ------------------------------------------------------------------------------------------------ picking a head


def test_create_department_with_picked_head(world, api):
    root = login(api, "root")
    r = department(
        api, root, "AGRI", {"user_id": uid(world, "edu_off1"), "designation_id": designation_id(world)}
    )
    assert r.status_code == 201, r.text
    agri_id = r.json()["id"]
    with world.Session() as s:
        agri = s.get(Office, agri_id)
        head = memberships.head_of(s, agri)
        assert head.user_id == world.users["edu_off1"].id and head.office_id == agri.id
        assert head.designation == "Secretary"  # the text filled from designation_id
        assert str(head.designation_id) == designation_id(world)
        ticket = s.scalars(sa.select(AdminTicket).where(AdminTicket.department_id == agri.id)).one()
        assert ticket.status.value == "approved" and ticket.target_membership_id == head.id
        added = s.scalars(
            sa.select(AuditLog).where(AuditLog.action == "membership.added", AuditLog.entity_id == head.id)
        ).one()
        assert added.after["ticket_ref"] == ticket.ref_no
        approved = s.scalars(
            sa.select(AuditLog).where(AuditLog.action == "ticket.approved", AuditLog.entity_id == ticket.id)
        ).one()
        assert approved.after["direct"] is True
        created = s.scalars(
            sa.select(AuditLog).where(AuditLog.action == "office.create", AuditLog.entity_id == agri.id)
        ).one()
        assert created.after["head"]["membership_id"] == str(head.id)
        assert created.after["head"]["ticket_ref"] == ticket.ref_no


def test_one_person_heads_two_departments(world, api):
    root = login(api, "root")
    person = uid(world, "edu_off1")
    for code in ("AGRI", "TRANS"):
        r = department(api, root, code, {"user_id": person, "designation": "Secretary"})
        assert r.status_code == 201, r.text
    ms = active_memberships(world, world.users["edu_off1"].id)
    heads = [m for m in ms if m.role == Role.DEPT_HEAD]
    assert len(heads) == 2 and not any(m.is_primary for m in heads)
    with world.Session() as s:
        primary = next(m for m in ms if m.is_primary)
        assert primary.office_id == world.offices["EDU"].id
        assert s.get(User, world.users["edu_off1"].id).office_id == world.offices["EDU"].id


def test_head_picked_by_email_still_works(world, api):
    root = login(api, "root")
    r = department(api, root, "AGRI", {"email": "OFF2.EDU@example.org", "designation": "Secretary"})
    assert r.status_code == 201, r.text
    with world.Session() as s:
        head = memberships.head_of(s, s.get(Office, r.json()["id"]))
        assert head.user_id == world.users["edu_off2"].id and head.designation == "Secretary"


def test_head_unknown_email_refused(world, api):
    root = login(api, "root")
    r = department(api, root, "AGRI", {"email": "nobody@example.org", "designation": "Secretary"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_field"
    assert "add the person in Users first" in r.json()["detail"]["message"]
    assert not office_exists(world, "AGRI")
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).where(AuditLog.action == "office.create")) == 0
        assert s.scalar(sa.select(User.id).where(User.email == "nobody@example.org")) is None
    r = department(api, root, "AGRI", {"user_id": "01900000-0000-7000-8000-000000000000"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_field"
    assert not office_exists(world, "AGRI")


@pytest.mark.parametrize(
    "head",
    [
        {"email": "new.head@example.org", "password": "a-long-password-1"},
        {"email": "new.head@example.org", "full_name": "New Head"},
        {"email": "off1.edu@example.org", "mobile": "9864012345"},
        {"email": "off1.edu@example.org", "user_id": "01900000-0000-7000-8000-000000000000"},
        {"designation": "Secretary"},
    ],
)
def test_head_new_login_fields_refused(world, api, head):
    r = department(api, login(api, "root"), "AGRI", head)
    assert r.status_code == 422, r.text
    retired = next((k for k in ("password", "full_name", "mobile") if k in head), None)
    if retired:
        assert any(e["loc"][-1] == retired for e in r.json()["detail"])
    assert not office_exists(world, "AGRI")


def test_head_inactive_login_refused(world, api):
    root = login(api, "root")
    assert api.post(f"/admin/users/{uid(world, 'edu_off2')}/disable", headers=root).status_code == 200
    r = department(api, root, "AGRI", {"user_id": uid(world, "edu_off2")})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "login_inactive"
    assert not office_exists(world, "AGRI")


def test_head_super_admin_refused(world, api):
    r = department(api, login(api, "root"), "AGRI", {"user_id": uid(world, "root")})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "super_admin_single"
    assert not office_exists(world, "AGRI")


def test_head_does_not_touch_department_admin(world, api):
    root = login(api, "root")
    with world.Session() as s:
        edu_admin_before = memberships.admin_of(s, world.office(s, "EDU"))
    r = department(api, root, "AGRI", {"user_id": uid(world, "edu_admin"), "designation": "Secretary"})
    assert r.status_code == 201, r.text
    with world.Session() as s:
        edu_admin = memberships.admin_of(s, world.office(s, "EDU"))
        assert (
            edu_admin.id == edu_admin_before.id and edu_admin.role == Role.DEPT_ADMIN and edu_admin.is_active
        )
        agri = world.office(s, "AGRI")
        assert memberships.head_of(s, agri).user_id == world.users["edu_admin"].id
        assert memberships.admin_of(s, agri) is None
    nodal = {"email": "nodal.agri@example.org", "password": PW, "full_name": "Nodal Agri"}
    assert api.post("/admin/offices/AGRI/admins", json=nodal, headers=root).status_code == 201
    second = {**nodal, "email": "nodal2.agri@example.org"}
    r = api.post("/admin/offices/AGRI/admins", json=second, headers=root)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "admin_exists"


def test_reactivate_with_picked_head(world, api):
    root = login(api, "root")
    r = department(api, root, "AGRI", {"user_id": uid(world, "edu_off1")})
    assert r.status_code == 201
    with world.Session() as s:
        head = memberships.head_of(s, world.office(s, "AGRI"))
        head_user, head_id = str(head.user_id), str(head.id)
    with world.Session() as s:
        root_user = world.user(s, "root")
        tickets.request_head_change(
            s,
            access.actor_for(root_user),
            root_user,
            {
                "operation": "end",
                "department_code": "AGRI",
                "outgoing": {
                    "mode": "exit",
                    "assignments": [],
                    "items_fingerprint": EMPTY_FP,
                    "reason": "abolished",
                },
            },
        )
        s.commit()
    assert api.post("/admin/offices/AGRI/deactivate", headers=root).status_code == 200
    r = api.post(
        "/admin/offices/AGRI/reactivate", json={"head": {"user_id": uid(world, "edu_off2")}}, headers=root
    )
    assert r.status_code == 200, r.text
    with world.Session() as s:
        assert memberships.head_of(s, world.office(s, "AGRI")).user_id == world.users["edu_off2"].id
    # a second head while one is still active (only possible when the office was closed with its head)
    with world.Session() as s:
        s.execute(sa.text("UPDATE offices SET is_active = false, deactivated_at = now() WHERE code = 'AGRI'"))
        s.commit()
    r = api.post("/admin/offices/AGRI/reactivate", json={"head": {"user_id": head_user}}, headers=root)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "head_exists"
    assert head_id not in {str(m.id) for m in active_memberships(world, world.users["edu_off1"].id)}


def test_department_needs_head(world, api):
    root = login(api, "root")
    r = department(api, root, "AGRI", None)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "head_required"
    with world.Session() as s:
        s.execute(
            sa.text("UPDATE offices SET is_active = false, deactivated_at = now() WHERE code = 'HEALTH'")
        )
        s.execute(
            sa.text(
                "UPDATE user_memberships SET is_active = false, deactivated_at = now(), is_primary = false "
                "WHERE office_id = (SELECT id FROM offices WHERE code = 'HEALTH')"
            )
        )
        s.commit()
    r = api.post("/admin/offices/HEALTH/reactivate", headers=root)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "head_required"
    r = api.post("/admin/offices/HEALTH/reactivate", json={}, headers=root)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "head_required"


def test_create_department_requires_function(world, api):
    officer = login(api, "edu_off1")
    r = department(api, officer, "AGRI", {"user_id": uid(world, "edu_off2")})
    assert r.status_code == 403
    r = api.put(
        f"/admin/users/{uid(world, 'edu_admin')}/permissions/offices.manage",
        json={"effect": "grant", "reason": "test"},
        headers=login(api, "root"),
    )
    assert r.status_code == 200, r.text
    admin = login(api, "edu_admin")
    with world.Session() as s:
        assert access.has(s, world.user(s, "edu_admin"), "offices.manage")
    r = department(api, admin, "AGRI", {"user_id": uid(world, "edu_off2")})
    assert r.status_code == 403
    assert api.get("/admin/users", params={"q": "edu", "limit": 20}, headers=officer).status_code == 403
    assert not office_exists(world, "AGRI")


def test_picker_scope_of_department_admin(world, api):
    root = login(api, "root")
    new_login(api, root, "waiting.edu@example.org", "Waiting Edu")
    admin = login(api, "edu_admin")
    r = api.get("/admin/users", params={"q": "example", "limit": 20}, headers=admin)
    assert r.status_code == 200
    emails = {u["email"] for u in r.json()}
    assert "waiting.edu@example.org" not in emails and "off.health@example.org" not in emails
    assert emails and all(any(m["department_code"] == "EDU" for m in u["memberships"]) for u in r.json())
    r = api.get("/admin/users", params={"q": "waiting", "limit": 20}, headers=admin)
    assert r.json() == [] and r.headers["X-Total-Count"] == "0"
    r = api.get("/admin/users", params={"q": "waiting", "include_ended": "true"}, headers=admin)
    assert r.status_code == 403


# ------------------------------------------------------------------------------------------------ no office yet


def test_create_login_without_office(world, api):
    root = login(api, "root")
    out = new_login(api, root)
    assert out["office"] is None and out["role"] is None and out["memberships"] == []
    assert out["must_change_password"] is True
    with world.Session() as s:
        user = s.get(User, out["id"])
        assert user.office_id is None and user.role is None and user.designation is None
        assert s.scalar(sa.select(sa.func.count()).where(UserMembership.user_id == user.id)) == 0
        row = s.scalars(
            sa.select(AuditLog).where(AuditLog.action == "user.create", AuditLog.entity_id == user.id)
        ).one()
        assert row.after["no_office"] is True and row.after["role"] is None and row.after["office_id"] is None
        ev = s.scalars(
            sa.select(Event).where(
                Event.type == EventType.USER_CREATED, Event.dedupe_key == f"user_created:{user.id}"
            )
        ).one()
        assert ev.payload["role"] is None and ev.payload["office"] is None
    got = api.get(f"/admin/users/{out['id']}", headers=root).json()
    assert got["office"] is None and got["role"] is None
    perms = api.get(f"/admin/users/{out['id']}/permissions", headers=root).json()
    assert perms["role"] is None and perms["functions"] == []


def test_login_without_office_refusals(world, api):
    admin = login(api, "edu_admin")
    base = {"email": "w2@example.org", "password": NEW_PW, "full_name": "W Two"}
    r = api.post("/admin/users", json={**base, "office_code": None, "role": None}, headers=admin)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "super_admin_only"
    root = login(api, "root")
    for half in ({"office_code": "EDU"}, {"role": "dept_officer"}):
        r = api.post("/admin/users", json={**base, **half}, headers=root)
        assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_field"
    for extra in (
        {"designation": "Secretary"},
        {"designation_id": designation_id(world)},
        {"functions": ["cases.view_scope"]},
    ):
        r = api.post("/admin/users", json={**base, **extra}, headers=root)
        assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_field", r.text
    with world.Session() as s:
        assert s.scalar(sa.select(User.id).where(User.email == "w2@example.org")) is None


def test_users_placed_check(world):
    with world.Session() as s:
        user = world.user(s, "edu_off1")
        with pytest.raises(IntegrityError, match="ck_users_placed"):
            with s.begin_nested():
                s.execute(sa.text("UPDATE users SET office_id = NULL WHERE id = :i"), {"i": user.id})
        with pytest.raises(IntegrityError, match="ck_users_placed"):
            with s.begin_nested():
                s.execute(sa.text("UPDATE users SET role = NULL WHERE id = :i"), {"i": user.id})


def test_login_without_office_signs_in_and_sees_nothing(world, api):
    root = login(api, "root")
    out = new_login(api, root)
    tok = sign_in(api, "waiting@example.org", NEW_PW)
    assert tok["next_step"] == "change_password"
    changed = api.post(
        "/me/password",
        json={
            "current_password": NEW_PW,
            "new_password": "my-own-pass-1",
            "device_token": tok["device_token"],
        },
        headers=auth_headers(tok),
    )
    assert changed.status_code == 200 and changed.json()["next_step"] == "confirm_profile"
    hh = auth_headers(changed.json())
    r = api.post(
        "/me/profile/confirm", json={"full_name": "Waiting Person", "mobile": "9864012345"}, headers=hh
    )
    assert r.status_code == 200, r.text
    me = api.get("/me", headers=hh).json()
    assert me["memberships"] == [] and me["functions"] == [] and me["user"]["office"] is None
    case_ref = None
    with world.Session() as s:
        case = make_case(s)
        h.claim(s, world, "edu_admin", case)
        case_ref = case.ref_no
        s.commit()
    forbidden = [
        "/cases/search?q=wp",
        f"/cases/{case_ref}",
        "/dashboard/me",
        "/alerts",
        "/causelists/dates?from=2026-10-01&to=2026-10-31",
        "/assistant/conversations",
        "/reports",
        "/audit",
    ]
    for path in forbidden:
        r = api.get(path, headers=hh)
        assert r.status_code in (403, 404), (path, r.status_code, r.text)
    for path in ("/inbox/mine?view=working", "/inbox/mine?view=files", "/me/calendar"):
        r = api.get(path, headers=hh)
        if r.status_code == 200:
            assert not r.json().get("items"), (path, r.text)
        else:
            assert r.status_code == 403, (path, r.status_code)
    r = api.get("/inbox/mine/counts", headers=hh)
    if r.status_code == 200:
        assert not any(v for v in r.json().values() if isinstance(v, int)), r.text
    else:
        assert r.status_code == 403
    # the alert scan addresses nothing to it, and the digest sends it nothing
    with world.Session() as s:
        target = s.scalars(sa.select(Case).where(Case.ref_no == case_ref)).one()
        h.order_stored_event(s, target, order_no="1", order_date=h.days(-1))
        s.commit()
        alerts.scan_events(s, now=h.now_utc())
        s.commit()
        assert h.alerts_of(s, target)
        assert s.scalar(sa.select(sa.func.count()).where(Notification.user_id == out["id"])) == 0
        notifications.build_digests(s, now=h.now_utc() + timedelta(hours=1))
        s.commit()
        assert s.scalar(sa.select(sa.func.count()).where(Digest.user_id == out["id"])) == 0


def test_users_list_no_office(world, api):
    root = login(api, "root")
    out = new_login(api, root)
    r = api.get("/admin/users", headers=root)
    listed = {u["email"]: u for u in r.json()}
    assert "waiting@example.org" in listed and listed["waiting@example.org"]["office"] is None
    assert r.headers["X-Total-Count"] == str(len(r.json()))
    r = api.get("/admin/users", params={"no_office": "true"}, headers=root)
    assert [u["id"] for u in r.json()] == [out["id"]] and r.headers["X-Total-Count"] == "1"
    r = api.get("/admin/users", params={"no_office": "true", "q": "nobody"}, headers=root)
    assert r.json() == [] and r.headers["X-Total-Count"] == "0"
    # an office or role filter leaves it out
    assert "waiting@example.org" not in {
        u["email"] for u in api.get("/admin/users", params={"role": "dept_officer"}, headers=root).json()
    }
    for bad in ({"office": "EDU"}, {"role": "dept_officer"}):
        r = api.get("/admin/users", params={"no_office": "true", **bad}, headers=root)
        assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_field"
    r = api.get("/admin/users", params={"no_office": "true"}, headers=login(api, "edu_admin"))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "scope"
    assert api.get(f"/admin/users/{out['id']}", headers=login(api, "edu_admin")).status_code == 404


def test_pick_login_without_office_as_head(world, api):
    root = login(api, "root")
    out = new_login(api, root)
    r = department(api, root, "AGRI", {"user_id": out["id"], "designation_id": designation_id(world, "PS")})
    assert r.status_code == 201, r.text
    ms = active_memberships(world, out["id"])
    assert len(ms) == 1 and ms[0].role == Role.DEPT_HEAD and ms[0].is_primary
    assert ms[0].designation == "Principal Secretary"
    with world.Session() as s:
        user = s.get(User, out["id"])
        agri = world.office(s, "AGRI")
        assert (
            user.role == Role.DEPT_HEAD
            and user.office_id == agri.id
            and user.designation == "Principal Secretary"
        )
        assert s.scalars(
            sa.select(AdminTicket).where(AdminTicket.department_id == agri.id)
        ).one().status.value == ("approved")
    got = api.get(f"/admin/users/{out['id']}", headers=root).json()
    assert got["office"]["code"] == "AGRI" and got["role"] == "dept_head"


def test_pick_exited_login_as_head(world, api):
    root = login(api, "root")
    with world.Session() as s:
        mid = str(world.membership(s, "health_off").id)
    r = api.post(
        f"/admin/users/{uid(world, 'health_off')}/memberships/{mid}/end",
        json={"reason": "transferred", "assignments": [], "items_fingerprint": EMPTY_FP},
        headers=root,
    )
    assert r.status_code == 200, r.text
    assert active_memberships(world, world.users["health_off"].id) == []
    r = department(api, root, "AGRI", {"user_id": uid(world, "health_off"), "designation": "Secretary"})
    assert r.status_code == 201, r.text
    ms = active_memberships(world, world.users["health_off"].id)
    assert len(ms) == 1 and ms[0].role == Role.DEPT_HEAD and ms[0].is_primary


def test_add_office_to_login_without_office(world, api):
    root = login(api, "root")
    first = new_login(api, root)
    r = api.post(
        f"/admin/users/{first['id']}/memberships",
        json={"office": "HEALTH", "role": "dept_officer", "designation": "Section Officer"},
        headers=root,
    )
    assert r.status_code == 201, r.text
    assert r.json()["is_primary"] is True
    with world.Session() as s:
        user = s.get(User, first["id"])
        assert user.role == Role.DEPT_OFFICER and user.office_id == world.offices["HEALTH"].id
    # a department admin, through the exact-e-mail path of New User
    second = new_login(api, root, "second@example.org", "Second Person")
    admin = login(api, "edu_admin")
    found = api.get("/admin/users/lookup", params={"email": "second@example.org"}, headers=admin)
    assert found.status_code == 200 and found.json()["memberships"] == []
    r = api.post(
        f"/admin/users/{found.json()['id']}/memberships",
        json={"office": "EDU-DSE", "role": "directorate_user"},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    assert r.json()["is_primary"] is True
    assert api.get(f"/admin/users/{second['id']}", headers=admin).status_code == 200
