"""The sight-only `transfer_in` basis (design portal-ui-redesign, A5; the owner's answer to question 1): while a
transfer to a department is requested, that department's whole-department memberships read the case and its
ownership (with `decide_transfer`), never write through it, and lose sight on decline or withdraw. An officer of
the department without `cases.claim` or `cases.allot` does not see it."""

from __future__ import annotations

import pytest

from aslms.domain.cases import Case
from aslms.domain.org import PermissionEffect
from aslms.domain.ownership import OwnershipTransfer
from aslms.domain.reference import Permission, Role
from aslms.services import ownership as own
from aslms.services import visibility
from aslms.services.workflow_common import WorkflowError
from tests.db import docs_support as ds
from tests.db import workflow_support as w
from tests.db.report_support import override, row_counts
from tests.db.world import add_membership, make_case


@pytest.fixture()
def api(world, tmp_path):
    w.widen(world)
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture()
def transfer(world, api):
    """A HEALTH case (allotted to the HEALTH officer, who holds the file) with a transfer to EDU requested."""
    with world.Session() as s:
        case = make_case(s)
        ha, health = world.actor(s, "health_admin")
        own.claim(s, ha, health, case, officer_user_id=world.users["health_off"].id)
        t = own.request_transfer(s, ha, health, case, to_office_code="EDU", reason="an education matter")
        s.commit()
        return str(case.id), str(case.id), str(t.id)


def test_the_receiving_admin_reads_the_case_while_requested(api, world, transfer):
    ref, case_id, transfer_id = transfer
    for key in ("edu_admin", "edu_head"):
        headers = w.login(api, key)
        r = api.get(f"/cases/{ref}", headers=headers)
        assert r.status_code == 200, (key, r.text)
        assert "transfer_in" in r.json()["access_basis"]
        for tab in ("parties", "hearings", "listings", "orders", "links"):
            assert api.get(f"/cases/{ref}/{tab}", headers=headers).status_code == 200, (key, tab)
        o = api.get(f"/cases/{ref}/ownership", headers=headers)
        assert o.status_code == 200, (key, o.text)
        assert o.json()["actions"]["decide_transfer"] is True
        assert o.json()["open_transfer"]["id"] == transfer_id
    # not a working basis
    with world.Session() as s:
        assert not visibility.works_on_case(
            s, world.user(s, "edu_admin"), s.get(OwnershipTransfer, transfer_id).case_id
        )


def test_an_officer_without_claim_or_allot_does_not_see_it(api, world, transfer):
    ref, _case_id, _ = transfer
    headers = w.login(api, "edu_off1")
    assert api.get(f"/cases/{ref}", headers=headers).status_code == 404
    assert api.get(f"/cases/{ref}/ownership", headers=headers).status_code == 404


@pytest.mark.parametrize("outcome", ["decline", "withdraw"])
def test_sight_is_lost_on_decline_or_withdraw(api, world, transfer, outcome):
    ref, _case_id, transfer_id = transfer
    admin = w.login(api, "edu_admin")
    assert api.get(f"/cases/{ref}", headers=admin).status_code == 200
    with world.Session() as s:
        t = s.get(OwnershipTransfer, transfer_id)
        if outcome == "decline":
            actor, user = world.actor(s, "edu_admin")
            own.decide_transfer(s, actor, user, t, accept=False)
        else:
            actor, user = world.actor(s, "health_admin")
            own.withdraw_transfer(s, actor, user, t)
        s.commit()
    assert api.get(f"/cases/{ref}", headers=admin).status_code == 404
    assert api.get(f"/cases/{ref}/ownership", headers=admin).status_code == 404


def test_no_write_through_the_basis(api, world, transfer):
    ref, case_id, _ = transfer
    with world.Session() as s:
        from aslms.domain.cases import Case

        case = s.get(Case, case_id)
        with pytest.raises(WorkflowError) as exc:
            w.note(s, world, "edu_admin", case)
        assert exc.value.http_status == 403
        s.rollback()
    admin = w.login(api, "edu_admin")
    r = api.post(f"/cases/{ref}/stages", json={"stage": "counsel_briefed"}, headers=admin)
    assert r.status_code in (403, 404), r.text
    assert r.status_code != 200
    # the request is still decided through the transfer, not the case basis
    o = api.get(f"/cases/{ref}/ownership", headers=admin).json()["actions"]
    assert o["claim"] is False and o["allot"] is False and o["take_over"] is False


# ------------------------------------------------------------------------- design portal-ui-polish, decision 8


def test_ownership_view_refuses_transfer_in_without_view_scope(api, world, transfer):
    """The receiving department admin's membership without `cases.view_scope` (a per-user override) is refused
    by the service; the login holds the function nowhere else, so the router's login-level check answers first.
    With the function restored the panel opens."""
    ref, case_id, _ = transfer
    with world.Session() as s:
        override(s, world, "edu_admin", Permission.CASES_VIEW_SCOPE, PermissionEffect.DENY)
        s.commit()
    with world.Session() as s:
        with pytest.raises(own.NotVisible):
            own.case_ownership_view(s, world.user(s, "edu_admin"), s.get(Case, case_id))
    headers = w.login(api, "edu_admin")
    assert api.get(f"/cases/{ref}/ownership", headers=headers).status_code in (403, 404)
    assert api.get(f"/cases/{ref}", headers=headers).status_code in (403, 404)
    with world.Session() as s:
        override(s, world, "edu_admin", Permission.CASES_VIEW_SCOPE, None)
        s.commit()
    assert api.get(f"/cases/{ref}/ownership", headers=headers).status_code == 200


def test_ownership_view_transfer_in_needs_scope_on_the_same_membership(api, world, transfer):
    """`cases.view_scope` held only on the login's other membership, in another department, passes the router
    but does not open the panel: 404, as `GET /cases/{ref}` (this mirrors `visibility.member_bases`)."""
    ref, _case_id, _ = transfer
    with world.Session() as s:
        add_membership(s, world.user(s, "edu_admin"), world.office(s, "FIN"), Role.DEPT_OFFICER)
        override(s, world, "edu_admin", Permission.CASES_VIEW_SCOPE, PermissionEffect.DENY, office="EDU")
        s.commit()
    headers = w.login(api, "edu_admin")
    with world.Session() as s:
        writes = row_counts(s)
    o = api.get(f"/cases/{ref}/ownership", headers=headers)
    assert o.status_code == 404, o.text
    assert o.json()["detail"] == "no such case"
    assert api.get(f"/cases/{ref}", headers=headers).status_code == 404
    with world.Session() as s:
        assert row_counts(s) == writes  # a read: no audit row
