"""A department always has a head unless the super admin ends it (design `user-memberships`, decision 24):
creation and reactivation name the head in the same transaction; directorates and units have none; a
department with an active head cannot be deactivated; while headless nothing is substituted and the
function holders keep receiving; the headless departments are counted and listed; the super admin is not
stopped by the delegation rule but is by the one-head rule and the head-change route."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.org import Office, PermissionEffect
from aslms.domain.ownership import Recommendation, RecommendationOrigin, ScoreBand
from aslms.domain.reference import Permission, Role
from aslms.services import access, memberships, offices, tickets
from aslms.services.access import Conflict
from aslms.services.audit import Actor
from aslms.services.recipients import Resolver
from aslms.services.users import create_user
from tests.db.docs_support import make_api
from tests.db.world import PW, make_case

NEW_HEAD = {"email": "head.agri@example.org", "designation": "Secretary"}


def add_head_login(s) -> None:
    """The head AGRI is created with, made first as a login with no office yet (design `office-head-picker`)."""
    if memberships.lookup(s, NEW_HEAD["email"]) is None:
        create_user(
            s,
            Actor.system("test"),
            email=NEW_HEAD["email"],
            password=PW,
            full_name="Head Agri",
            role=None,
            office=None,
        )


def end_head(s, root, code):
    head = memberships.head_of(s, offices.find_office(s, code))
    fp = memberships.fingerprint(memberships.exit_items(s, head))
    return tickets.request_head_change(
        s,
        access.actor_for(root),
        root,
        {
            "operation": "end",
            "department_code": code,
            "outgoing": {"mode": "exit", "assignments": [], "items_fingerprint": fp, "reason": "abolished"},
        },
    )


def test_creation_names_the_head_in_one_transaction(world, monkeypatch):
    with world.Session() as s:
        add_head_login(s)
        actor, root = world.actor(s, "root")
        goa = world.office(s, "GOA")
        with pytest.raises(offices.HeadRequired):
            offices.create_office(
                s, actor, root, code="AGRI", name="Agriculture", kind="department", parent=goa
            )
        # a login with no office yet, created first (office-head-picker)
        agri = offices.create_office(
            s, actor, root, code="AGRI", name="Agriculture", kind="department", parent=goa, head=NEW_HEAD
        )
        head = memberships.head_of(s, agri)
        assert head.office_id == agri.id and head.is_primary
        row = s.scalars(
            sa.select(tickets.AdminTicket).where(tickets.AdminTicket.department_id == agri.id)
        ).one()
        assert row.status.value == "approved" and row.result["incoming"]["membership_id"] == str(head.id)
        # an existing login keeps its other memberships
        fin = offices.create_office(
            s,
            actor,
            root,
            code="FIN",
            name="Finance",
            kind="department",
            parent=goa,
            head={"email": "off1.edu@example.org", "designation": "Secretary"},
        )
        off1 = world.user(s, "edu_off1")
        assert {m.department_id for m in access.active_memberships(s, off1)} == {
            world.office(s, "EDU").id,
            fin.id,
        }
        assert off1.office_id == world.office(s, "EDU").id  # the primary stays
        # directorates and units need none
        offices.create_office(
            s, actor, root, code="AGRI-D", name="Directorate", kind="directorate", parent=agri
        )
        offices.create_office(s, actor, root, code="AGRI-U", name="Unit", kind="unit", parent=agri)
        # a forced failure creating the head leaves no office
        monkeypatch.setattr(
            tickets, "record_direct_set", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        with pytest.raises(RuntimeError):
            with s.begin_nested():
                offices.create_office(
                    s,
                    actor,
                    root,
                    code="IRR",
                    name="Irrigation",
                    kind="department",
                    parent=goa,
                    head=NEW_HEAD,
                )
        assert s.scalar(sa.select(Office).where(Office.code == "IRR")) is None


def test_deactivation_needs_the_head_ended_first(world):
    with world.Session() as s:
        add_head_login(s)
        actor, root = world.actor(s, "root")
        agri = offices.create_office(
            s,
            actor,
            root,
            code="AGRI",
            name="Agriculture",
            kind="department",
            parent=world.office(s, "GOA"),
            head=NEW_HEAD,
        )
        with pytest.raises(offices.OfficeInUse):
            offices.deactivate_office(s, actor, root, agri)
        end_head(s, root, "AGRI")
        offices.deactivate_office(s, actor, root, agri)
        assert not agri.is_active
        with pytest.raises(offices.HeadRequired):
            offices.reactivate_office(s, actor, root, agri)
        offices.reactivate_office(s, actor, root, agri, head={"email": NEW_HEAD["email"]})
        assert memberships.head_of(s, agri) is not None


def test_while_headless_the_function_holders_receive_and_nothing_is_assigned(world):
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        health = world.office(s, "HEALTH")
        assert memberships.head_of(s, health) is None
        case = make_case(s)
        rec = Recommendation(
            case_id=case.id,
            office_id=health.id,
            score=0.95,
            band=ScoreBand.HIGH,
            origin=RecommendationOrigin.CAUSE_LIST,
            actor_name="matching",
        )
        s.add(rec)
        s.flush()
        r = Resolver(s)
        assert {u.email for u in r.for_recommendation(rec)} == {"admin.health@example.org"}
        h_actor, h_admin = world.actor(s, "health_admin")
        access.set_override(
            s,
            h_actor,
            h_admin,
            world.membership(s, "health_off"),
            Permission.CASES_CLAIM,
            PermissionEffect.GRANT,
        )
        assert {u.email for u in Resolver(s).for_recommendation(rec)} == {
            "admin.health@example.org",
            "off.health@example.org",
        }
        assert memberships.head_of(s, health) is None  # nothing substituted


def test_headless_departments_are_counted_listed_and_fixed(world, tmp_path):
    api = make_api(world, tmp_path)
    from tests.db.docs_support import login

    root = login(api, "root")
    assert (
        api.get("/admin/tickets/counts", headers=root).json()["departments_without_head"] == 2
    )  # HEALTH, CENTRAL
    codes = [o["code"] for o in api.get("/admin/offices?missing_head=true", headers=root).json()]
    assert codes == ["CENTRAL", "HEALTH"]
    assert api.get("/admin/offices?missing_head=true", headers=login(api, "edu_admin")).status_code == 403
    import json

    r = api.post(
        "/admin/tickets/head-change",
        data={
            "request": json.dumps(
                {"department": "HEALTH", "operation": "set", "incoming": {"email": "off.health@example.org"}}
            )
        },
        headers=root,
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "one_per_department"
    with world.Session() as s:
        mid = str(world.membership(s, "health_off").id)
    r = api.post(
        "/admin/tickets/head-change",
        data={
            "request": json.dumps(
                {"department": "HEALTH", "operation": "set", "incoming": {"membership_id": mid}}
            )
        },
        headers=root,
    )
    assert r.status_code == 201 and r.json()["status"] == "approved"
    assert api.get("/admin/tickets/counts", headers=root).json()["departments_without_head"] == 1


def test_super_admin_is_not_limited_by_delegation_but_by_the_head_rules(world):
    with world.Session() as s:
        r_actor, root = world.actor(s, "root")
        admin_m = world.membership(s, "health_admin")
        t = tickets.request_head_change(
            s,
            r_actor,
            root,
            {"operation": "set", "department_code": "HEALTH", "incoming": {"membership_id": str(admin_m.id)}},
        )
        assert t.status.value == "approved"
        s.refresh(admin_m)
        assert (
            admin_m.role == Role.DEPT_HEAD and offices.department_admins(s, world.office(s, "HEALTH")) == []
        )
        with pytest.raises(Conflict) as exc:
            memberships.insert_membership(
                s, r_actor, world.user(s, "edu_off2"), office=world.office(s, "HEALTH"), role=Role.DEPT_HEAD
            )
        assert exc.value.code == "one_dept_head"
        with pytest.raises(Conflict) as exc2:
            memberships.end(s, r_actor, root, admin_m, reason="x" * 5, assignments=[], items_fingerprint=None)
        assert exc2.value.code == "head_required"
