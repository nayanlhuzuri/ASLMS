"""The membership and ticket endpoints end to end (design `user-memberships`, API table): function checks,
scope errors and shapes; `/me` with each membership's functions and the union; `/inbox/counts` per department;
`office_code` honoured for a second department; the head-change multipart request (202 / 201); the membership
endpoints refusing to make a head; exit preview and end; the ticket panel; `reserved_function`."""

from __future__ import annotations

import json
import uuid

import pytest

from aslms.domain.reference import Role
from tests import samplefiles as sf
from tests.db.docs_support import login, make_api
from tests.db.world import add_membership, make_case


@pytest.fixture()
def api(world, tmp_path):
    return make_api(world, tmp_path)


def ids(world, key, code=None):
    with world.Session() as s:
        u = world.user(s, key)
        return str(u.id), str(world.membership(s, key, code).id)


def test_lookup_add_me_counts_password_and_end(world, api):
    """Verification steps 3 and 4: a HEALTH membership for an EDU officer, `/me` and the inbox counts, the
    HEALTH admin cannot reset the password but ends the HEALTH membership."""
    health, root = login(api, "health_admin"), login(api, "root")
    uid, _ = ids(world, "edu_off1")
    assert (
        api.get("/admin/users/lookup?email=OFF1.EDU@example.org", headers=login(api, "edu_off1")).status_code
        == 403
    )
    r = api.get("/admin/users/lookup?email=OFF1.EDU@example.org", headers=health)
    assert r.status_code == 200 and r.json() == {
        "id": uid,
        "full_name": "Edu Off1",
        "memberships": [{"office_code": "EDU", "designation": None, "role": "dept_officer"}],
    }
    assert api.get("/admin/users/lookup?email=off1.edu", headers=health).status_code == 404
    r = api.post(
        f"/admin/users/{uid}/memberships",
        json={"office": "HEALTH", "role": "dept_officer", "designation": "SO"},
        headers=health,
    )
    assert r.status_code == 201, r.text
    hm = r.json()
    assert (
        hm["office"]["code"] == "HEALTH" and hm["department_code"] == "HEALTH" and hm["is_primary"] is False
    )
    # 409 one_per_department, 403 another department, 409 use_head_change, 403 super_admin_cli_only
    r = api.post(
        f"/admin/users/{uid}/memberships", json={"office": "HEALTH", "role": "dept_officer"}, headers=health
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "one_per_department"
    assert (
        api.post(
            f"/admin/users/{uid}/memberships",
            json={"office": "EDU-DSE", "role": "directorate_user"},
            headers=health,
        ).status_code
        == 403
    )
    r = api.post(
        f"/admin/users/{uid}/memberships", json={"office": "CENTRAL", "role": "dept_head"}, headers=root
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "use_head_change"
    r = api.post(
        f"/admin/users/{uid}/memberships", json={"office": "GOA", "role": "super_admin"}, headers=root
    )
    assert r.status_code == 403 and r.json()["detail"]["code"] == "super_admin_cli_only"
    person = login(api, "edu_off1")
    me = api.get("/me", headers=person).json()
    assert [m["office"]["code"] for m in me["memberships"]] == ["EDU", "HEALTH"]
    assert all("notes.add" in m["functions"] for m in me["memberships"]) and "notes.add" in me["functions"]
    assert [m["office"]["code"] for m in me["user"]["memberships"]] == ["EDU", "HEALTH"]
    assert me["user"]["memberships"][0]["functions"] is None  # functions only on `/me`'s own list
    counts = api.get("/inbox/counts", headers=person).json()["departments"]
    assert [c["office_code"] for c in counts] == ["EDU", "HEALTH"]
    # a HEALTH-owned case: the person cannot allot it
    with world.Session() as s:
        h_actor, h_admin = world.actor(s, "health_admin")
        case = make_case(s)
        from aslms.services import ownership as own

        own.claim(s, h_actor, h_admin, case)
        s.commit()
        case_ref = case.ref_no.replace("/", "-")
    assert (
        api.post(f"/cases/{case_ref}/allot", json={"officer_user_id": uid}, headers=person).status_code == 403
    )
    # login-level actions follow the primary office (EDU): the HEALTH admin is refused
    r = api.post(f"/admin/users/{uid}/password", json={"password": "another-long-password-8"}, headers=health)
    assert r.status_code == 403
    p = api.get(f"/admin/users/{uid}/memberships/{hm['id']}/exit-preview", headers=health).json()
    assert p["items"] == [] and p["counts"]["files"] == 0 and len(p["items_fingerprint"]) == 64
    r = api.post(
        f"/admin/users/{uid}/memberships/{hm['id']}/end",
        json={"reason": "back to Education", "items_fingerprint": p["items_fingerprint"], "assignments": []},
        headers=health,
    )
    assert r.status_code == 200, r.text
    assert r.json()["membership"]["is_active"] is False and r.json()["reassigned"] == []
    assert [m["office"]["code"] for m in api.get("/me", headers=person).json()["memberships"]] == ["EDU"]


def test_patch_primary_permissions_and_reserved_function(world, api):
    admin, root = login(api, "edu_admin"), login(api, "root")
    uid, mid = ids(world, "edu_off1")
    r = api.patch(
        f"/admin/users/{uid}/memberships/{mid}", json={"designation": "Section Officer"}, headers=admin
    )
    assert r.status_code == 200 and r.json()["designation"] == "Section Officer"
    r = api.patch(f"/admin/users/{uid}/memberships/{mid}", json={"role": "dept_head"}, headers=admin)
    assert r.status_code == 403  # dept_head is not a delegable type
    r = api.patch(f"/admin/users/{uid}/memberships/{mid}", json={"role": "dept_head"}, headers=root)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "use_head_change"
    head_uid, head_mid = ids(world, "edu_head")
    r = api.patch(
        f"/admin/users/{head_uid}/memberships/{head_mid}", json={"role": "dept_officer"}, headers=root
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "head_required"
    r = api.post(
        f"/admin/users/{head_uid}/memberships/{head_mid}/end",
        json={"reason": "moving on", "assignments": []},
        headers=root,
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "head_required"
    r = api.post(f"/admin/users/{head_uid}/disable", headers=root)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "head_required"
    root_uid, _ = ids(world, "root")
    r = api.post(f"/admin/users/{root_uid}/disable", headers=root)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "super_admin_cli_only"
    # per-membership functions
    r = api.put(
        f"/admin/users/{uid}/memberships/{mid}/permissions/cases.claim",
        json={"effect": "grant"},
        headers=admin,
    )
    assert (
        r.status_code == 200
        and "cases.claim" in r.json()["effective"]
        and "cases.claim" not in r.json()["type_functions"]
    )
    r = api.put(
        f"/admin/users/{uid}/memberships/{mid}/permissions/admin.tickets",
        json={"effect": "grant"},
        headers=root,
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "reserved_function"
    r = api.put("/admin/access/types/dept_admin/admin.tickets", json={"enabled": True}, headers=root)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "reserved_function"
    assert (
        api.get(f"/admin/users/{uid}/memberships/{mid}/permissions", headers=admin).json()["membership_id"]
        == mid
    )
    # make primary: a second membership, then the switch rewrites the mirror shown on the login
    with world.Session() as s:
        m2 = add_membership(s, world.user(s, "edu_off1"), world.office(s, "HEALTH"), Role.DEPT_OFFICER, "SO")
        s.commit()
        m2_id = str(m2.id)
    assert (
        api.put(
            f"/admin/users/{uid}/primary-membership", json={"membership": m2_id}, headers=admin
        ).status_code
        == 403
    )
    r = api.put(f"/admin/users/{uid}/primary-membership", json={"membership": m2_id}, headers=root)
    assert (
        r.status_code == 200
        and r.json()["office"]["code"] == "HEALTH"
        and r.json()["memberships"][0]["id"] == m2_id
    )
    listed = api.get("/admin/users", headers=admin).json()
    person = next(u for u in listed if u["id"] == uid)
    assert {m["office"]["code"] for m in person["memberships"]} == {"EDU", "HEALTH"}


def test_office_code_names_a_second_department(world, api):
    with world.Session() as s:
        person = world.user(s, "edu_admin")
        hm = add_membership(s, person, world.office(s, "HEALTH"), Role.DEPT_OFFICER)
        h_actor, h_admin = world.actor(s, "health_admin")
        from aslms.domain.org import PermissionEffect
        from aslms.domain.reference import Permission
        from aslms.services import access

        access.set_override(s, h_actor, h_admin, hm, Permission.CASES_CLAIM, PermissionEffect.GRANT)
        c1, c2 = make_case(s), make_case(s)
        s.commit()
        r1, r2 = c1.ref_no.replace("/", "-"), c2.ref_no.replace("/", "-")
    admin = login(api, "edu_admin")
    r = api.post(f"/cases/{r1}/claim", json={"office_code": "HEALTH"}, headers=admin)
    assert r.status_code == 201 and r.json()["office_code"] == "HEALTH"
    r = api.post(f"/cases/{r2}/claim", json={}, headers=admin)  # the primary membership qualifies: EDU
    assert r.status_code == 201 and r.json()["office_code"] == "EDU"


def test_head_change_and_the_ticket_panel(world, api):
    admin, root, health = login(api, "edu_admin"), login(api, "root"), login(api, "health_admin")
    _, off1_mid = ids(world, "edu_off1")
    _, off2_mid = ids(world, "edu_off2")

    def request(mid, headers, files=None):
        body = {
            "department": "EDU",
            "operation": "replace",
            "incoming": {"membership_id": mid},
            "outgoing": {"mode": "retype"},
        }
        return api.post(
            "/admin/tickets/head-change", data={"request": json.dumps(body)}, files=files, headers=headers
        )

    r = request(off1_mid, admin, files=[("files", ("go.pdf", sf.text_pdf(["GO"])))])
    assert r.status_code == 202 and r.json()["status"] == "open" and r.json()["can_withdraw"] is True
    t1 = r.json()
    assert request(off2_mid, admin).json()["detail"]["code"] == "ticket_open"
    assert (
        api.post("/admin/tickets/head-change", data={"request": "not json"}, headers=admin).status_code == 400
    )
    r = api.post(
        "/admin/tickets/head-change",
        data={
            "request": json.dumps({"department": "EDU", "operation": "end", "outgoing": {"mode": "retype"}})
        },
        headers=admin,
    )
    assert r.status_code == 403 and r.json()["detail"]["code"] == "super_admin_only"
    assert request(off1_mid, login(api, "edu_off1")).status_code == 403
    # the panel
    listed = api.get("/admin/tickets", headers=root).json()
    assert (
        listed["total"] == 1
        and listed["counts"]["open"] == 1
        and listed["items"][0]["ref_no"] == t1["ref_no"]
    )
    assert api.get("/admin/tickets?status=all&department=EDU&mine=true", headers=admin).json()["total"] == 1
    assert api.get("/admin/tickets?status=approved", headers=root).json()["total"] == 0
    assert api.get("/admin/tickets", headers=health).json()["total"] == 0
    assert api.get("/admin/tickets", headers=login(api, "edu_off1")).status_code == 403
    counts = api.get("/admin/tickets/counts", headers=root).json()
    assert counts["open_by_kind"] == {"head_change": 1} and counts["oldest_open_at"]
    ref = t1["ref_no"].replace("/", "-")
    assert api.post(f"/admin/tickets/{ref}/approve", json={}, headers=admin).status_code == 403
    assert api.post(f"/admin/tickets/{ref}/withdraw", json={}, headers=root).status_code == 403
    # the super admin's direct change: 201, applied, the open ticket superseded
    r = request(off2_mid, root)
    assert r.status_code == 201 and r.json()["status"] == "approved" and r.json()["result"]["incoming"]
    old = api.get(f"/admin/tickets/{ref}", headers=root).json()
    assert old["status"] == "rejected" and "superseded" in old["decision_remark"]
    assert (
        api.post(f"/admin/tickets/{ref}/approve", json={}, headers=root).json()["detail"]["code"]
        == "ticket_closed"
    )
    me = api.get("/me", headers=login(api, "edu_off2")).json()
    assert me["memberships"][0]["role"] == "dept_head"
    doc_id = old["documents"][0]["id"]
    assert (
        api.get(f"/admin/tickets/{ref}/documents/{doc_id}/file?disposition=inline", headers=root).status_code
        == 200
    )


def test_department_admin_cannot_revive_a_disabled_login(world, api):
    """Review finding: a disabled login with no active membership (for example the replaced super admin) is the
    super admin's only. A department admin cannot add or reactivate a membership on it (409 `login_inactive`),
    so it never becomes primary in their office and they never gain enable or password control; the super
    admin can."""
    from aslms.domain.org import UserMembership
    from aslms.services import memberships as ms
    from aslms.services.access import Conflict

    admin, root = login(api, "edu_admin"), login(api, "root")
    uid, mid = ids(world, "edu_off1")
    with world.Session() as s:
        u = world.user(s, "edu_off1")
        ms._close(s, world.membership(s, "edu_off1"), "left")
        u.is_active = False
        s.commit()
    r = api.post(
        f"/admin/users/{uid}/memberships", json={"office": "EDU", "role": "dept_officer"}, headers=admin
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "login_inactive"
    # the route hides the login from the admin (404); the service refuses it as well (409)
    assert api.post(f"/admin/users/{uid}/memberships/{mid}/reactivate", headers=admin).status_code == 404
    with world.Session() as s:
        a_actor, a_user = world.actor(s, "edu_admin")
        with pytest.raises(Conflict) as exc:
            ms.reactivate(s, a_actor, a_user, s.get(UserMembership, uuid.UUID(mid)))
        assert exc.value.code == "login_inactive"
    assert api.post(f"/admin/users/{uid}/enable", headers=admin).status_code in (403, 404)
    r = api.post(f"/admin/users/{uid}/password", json={"password": "another-long-password-8"}, headers=admin)
    assert r.status_code in (403, 404)
    r = api.post(f"/admin/users/{uid}/memberships/{mid}/reactivate", headers=root)
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is True and r.json()["is_primary"] is True
