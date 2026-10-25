"""`GET /admin/offices/choices` (design `portal-ui-polish-2`, decision 29): per purpose, exactly the offices the
matching screen's filter or write accepts; 403 without the purpose's function; `audit` only State-wide, with
inactive offices; `include_inactive` only with `offices.manage`; tree order, depth, ancestors and `is_active`."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from aslms.domain.events import AuditLog
from aslms.domain.org import Office, PermissionEffect, User, UserMembership, UserPermission
from aslms.domain.reference import OfficeKind, Permission, Role
from aslms.services.audit import Actor
from aslms.services.users import create_user
from tests.db.auth_support import ready_all
from tests.db.portal_support import PW, build_api, headers

URL = "/admin/offices/choices"
ALL_ACTIVE = ["GOA", "EDU", "EDU-DSE", "HEALTH"]


def _grant(s, email: str, perm: Permission) -> None:
    user = s.scalar(sa.select(User).where(User.email == email))
    m = s.scalar(
        sa.select(UserMembership).where(UserMembership.user_id == user.id, UserMembership.is_active.is_(True))
    )
    s.add(UserPermission(user_id=user.id, membership_id=m.id, permission=perm, effect=PermissionEffect.GRANT))


@pytest.fixture()
def api(engine):
    with build_api(engine) as client:
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        with Session() as s:
            goa = s.scalar(sa.select(Office).where(Office.code == "GOA"))
            edu = s.scalar(sa.select(Office).where(Office.code == "EDU"))
            s.add(
                Office(
                    code="EDU-OLD",
                    name="Old Cell",
                    kind=OfficeKind.UNIT,
                    parent_id=edu.id,
                    path="GOA/EDU/EDU-OLD",
                    is_active=False,
                    deactivated_at=datetime.now(UTC),
                )
            )
            sys = Actor.system("test")
            create_user(
                s,
                sys,
                email="auditor@example.org",
                password=PW,
                full_name="Audit",
                role=Role.AUDITOR,
                office=goa,
            )
            s.flush()
            # an officer of HEALTH holding admin.keywords by an override, without users.view
            _grant(s, "anil.kumar@example.org", Permission.ADMIN_KEYWORDS)
            # a department admin holding audit.view outside a State-wide membership
            _grant(s, "admin.edu@example.org", Permission.AUDIT_VIEW)
            ready_all(s)
            s.commit()
        yield client


def _codes(r) -> list[str]:
    assert r.status_code == 200, r.text
    return [i["code"] for i in r.json()["items"]]


def _get(api, email: str, purpose: str, **params):
    return api.get(URL, params={"purpose": purpose, **params}, headers=headers(api, email))


def test_super_admin_gets_every_active_office_for_each_purpose(api):
    h = headers(api, "root@example.org")
    for purpose in ("users", "membership", "office_parent", "counsel_codes", "keywords", "watchlist"):
        r = api.get(URL, params={"purpose": purpose}, headers=h)
        assert _codes(r) == ALL_ACTIVE, purpose
        assert r.json()["purpose"] == purpose
    with_inactive = api.get(URL, params={"purpose": "users", "include_inactive": "true"}, headers=h)
    assert _codes(with_inactive) == ["GOA", "EDU", "EDU-DSE", "EDU-OLD", "HEALTH"]
    # the active-only purposes stay active only
    assert _codes(api.get(URL, params={"purpose": "membership", "include_inactive": "true"}, headers=h)) == (
        ALL_ACTIVE
    )


def test_department_admin_gets_their_department_subtree(api):
    for purpose in ("users", "membership", "counsel_codes", "keywords", "watchlist"):
        assert _codes(_get(api, "admin.edu@example.org", purpose)) == ["EDU", "EDU-DSE"], purpose
    assert _codes(_get(api, "admin.health@example.org", "keywords")) == ["HEALTH"]


def test_mapping_holder_without_users_view_gets_own_offices(api):
    assert _codes(_get(api, "anil.kumar@example.org", "keywords")) == ["HEALTH"]
    assert _get(api, "anil.kumar@example.org", "users").status_code == 403
    assert _get(api, "anil.kumar@example.org", "counsel_codes").status_code == 403


def test_office_parent_needs_offices_manage(api):
    assert _get(api, "admin.edu@example.org", "office_parent").status_code == 403
    assert _codes(_get(api, "root@example.org", "office_parent")) == ALL_ACTIVE


def test_audit_state_wide_auditor_gets_every_office_with_inactive(api):
    r = _get(api, "auditor@example.org", "audit")
    assert _codes(r) == ["GOA", "EDU", "EDU-DSE", "EDU-OLD", "HEALTH"]
    old = next(i for i in r.json()["items"] if i["code"] == "EDU-OLD")
    assert old["is_active"] is False
    # the Auditor holds no users.view, so the Users purpose stays closed
    assert _get(api, "auditor@example.org", "users").status_code == 403


def test_audit_department_scoped_holder_gets_audit_scope(api):
    r = _get(api, "admin.edu@example.org", "audit")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "audit_scope"
    r = _get(api, "anil.kumar@example.org", "audit")
    assert r.status_code == 403


def test_include_inactive_needs_offices_manage(api):
    r = _get(api, "admin.edu@example.org", "users", include_inactive="true")
    assert r.status_code == 403
    # audit always includes them and needs no offices.manage
    assert "EDU-OLD" in _codes(_get(api, "auditor@example.org", "audit", include_inactive="true"))


def test_shape_tree_order_depth_ancestors(api):
    r = _get(api, "root@example.org", "users", include_inactive="true")
    items = {i["code"]: i for i in r.json()["items"]}
    assert (
        items["GOA"]["depth"] == 0 and items["GOA"]["parent_code"] is None and items["GOA"]["ancestors"] == []
    )
    assert items["GOA"]["tier"] == "state"
    dse = items["EDU-DSE"]
    assert dse["depth"] == 2 and dse["parent_code"] == "EDU" and dse["tier"] == "directorate"
    assert dse["ancestors"] == [items["GOA"]["name"], "Education"]
    assert dse["kind"] == "directorate" and dse["name"] == "Secondary Education" and dse["is_active"] is True
    # ancestors outside the caller's subtree are still named, root first
    edu = _get(api, "admin.edu@example.org", "users").json()["items"]
    assert [i["ancestors"] for i in edu] == [[items["GOA"]["name"]], [items["GOA"]["name"], "Education"]]


def test_unknown_purpose_422_and_reading_writes_nothing(api, engine):
    h = headers(api, "root@example.org")
    assert api.get(URL, params={"purpose": "nonsense"}, headers=h).status_code == 422
    with engine.connect() as conn:
        before = conn.scalar(sa.select(sa.func.count()).select_from(AuditLog))
    assert api.get(URL, params={"purpose": "users"}, headers=h).status_code == 200
    with engine.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(AuditLog)) == before
