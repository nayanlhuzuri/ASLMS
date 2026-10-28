"""`GET /admin/access/defaults` and `GET /admin/access/overview` (design case-workspace-admin, decisions 24 and 27): the
defaults equal `DEFAULT_MATRIX` over the active functions with the super admin all on; `users` counts distinct logins in
the caller's scope (a department admin only their subtree, the super admin everyone); `changed_from_default` counts a
matrix change; both need `users.view`."""

from __future__ import annotations

import pytest

from aslms.domain.reference import Role
from aslms.services import access
from aslms.services.access import ACTIVE_FUNCTIONS
from aslms.services.access_seed import DEFAULT_MATRIX
from tests.db import docs_support as ds
from tests.db import workflow_support as w


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


def test_defaults_equal_the_seed_matrix(api):
    r = api.get("/admin/access/defaults", headers=w.login(api, "root"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {role.value for role in Role}
    active = {p.value for p in ACTIVE_FUNCTIONS}
    assert len(active) == 53  # next-date-direct: two functions
    for role, enabled in DEFAULT_MATRIX.items():
        assert set(body[role.value]) == active, role
        assert {p for p, on in body[role.value].items() if on} == {p.value for p in enabled} & active, role
    assert all(body[Role.SUPER_ADMIN.value].values())
    assert set(body[Role.SUPER_ADMIN.value]) == active


def _cards(r) -> dict[str, dict]:
    assert r.status_code == 200, r.text
    return {c["code"]: c for c in r.json()}


def test_overview_counts_users_in_scope(api, world):
    root = _cards(api.get("/admin/access/overview", headers=w.login(api, "root")))
    assert len(root) == 10
    assert root["dept_admin"]["users"] == 2
    assert root["dept_officer"]["users"] == 3
    assert root["super_admin"]["users"] == 1
    assert root["super_admin"]["functions_on"] == root["super_admin"]["functions_total"] == 53
    edu = _cards(api.get("/admin/access/overview", headers=w.login(api, "edu_admin")))
    assert edu["dept_admin"]["users"] == 1  # the HEALTH admin is outside the subtree
    assert edu["dept_officer"]["users"] == 2
    assert edu["super_admin"]["users"] == 0
    assert edu["directorate_user"]["users"] == 2
    with world.Session() as s:
        expected = access.overview(s, world.user(s, "root"))
    assert [c["code"] for c in expected] == list(root)


def test_changed_from_default_counts_one_change(api):
    h = w.login(api, "root")
    before = _cards(api.get("/admin/access/overview", headers=h))["dept_officer"]
    on = before["functions_on"]
    r = api.put("/admin/access/types/dept_officer/custody.track", json={"enabled": True}, headers=h)
    assert r.status_code == 200, r.text
    after = _cards(api.get("/admin/access/overview", headers=h))["dept_officer"]
    assert after["changed_from_default"] == before["changed_from_default"] + 1
    assert after["functions_on"] == on + 1
    assert after["functions_total"] == 53


def test_permissions_carry_the_groups_in_order(api):
    from aslms.domain.reference import RETIRED_PERMISSIONS
    from aslms.services.access_seed import PERMISSION_GROUPS

    r = api.get("/admin/permissions", headers=w.login(api, "edu_off1"))
    assert r.status_code == 200, r.text
    rows = {p["code"]: p for p in r.json()}
    for code, label, members in PERMISSION_GROUPS:
        for i, p in enumerate(members, start=1):
            assert (rows[p.value]["group"], rows[p.value]["group_label"], rows[p.value]["sort_in_group"]) == (
                code,
                label,
                i,
            )
    for p in RETIRED_PERMISSIONS:
        assert rows[p.value]["group"] is None and rows[p.value]["sort_in_group"] is None


def test_users_view_is_required(api):
    h = w.login(api, "edu_off1")
    assert api.get("/admin/access/defaults", headers=h).status_code == 403
    assert api.get("/admin/access/overview", headers=h).status_code == 403
