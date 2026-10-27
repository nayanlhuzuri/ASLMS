"""Edit Name for user types (design portal-ui-polish-2, decision 12): `PATCH /admin/access/types/{role}/name` behind
`access.manage_types`. A rename writes one `access.type_edited` audit row with before and after and leaves the code,
the memberships and the matrix untouched; an unchanged save writes nothing; a name taken without regard to case is
409 `label_taken` (also under a race, from `uq_ref_role_label_lower`); the limits are 422 with their codes."""

from __future__ import annotations

import threading
import time

import pytest
import sqlalchemy as sa

from aslms.domain.events import AuditLog, Event
from aslms.domain.org import RolePermission, UserMembership
from aslms.domain.reference import EventType, RefRole
from aslms.services import access
from tests.db import docs_support as ds
from tests.db import workflow_support as w

URL = "/admin/access/types/dept_officer/name"


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


def _audits(world) -> list[AuditLog]:
    with world.Session() as s:
        return list(s.scalars(sa.select(AuditLog).where(AuditLog.action == "access.type_edited")).all())


def _snapshot(world) -> tuple[list, list, int]:
    with world.Session() as s:
        matrix = sorted(
            (str(r.role), str(r.permission), r.is_enabled)
            for r in s.scalars(sa.select(RolePermission).where(RolePermission.role == "dept_officer")).all()
        )
        members = sorted(
            (str(m.id), str(m.role))
            for m in s.scalars(sa.select(UserMembership).where(UserMembership.role == "dept_officer")).all()
        )
        events = s.scalar(
            sa.select(sa.func.count()).select_from(Event).where(Event.type == EventType.ACCESS_CHANGED)
        )
        return matrix, members, int(events)


def test_rename_writes_one_audit_row_and_changes_nothing_else(api, world):
    h = w.login(api, "root")
    before = _snapshot(world)
    r = api.patch(
        URL, json={"label": "  Department   Officer (Legal) ", "description": " Works on cases. "}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "code": "dept_officer",
        "label": "Department Officer (Legal)",
        "description": "Works on cases.",
        "changed": True,
    }
    rows = _audits(world)
    assert len(rows) == 1
    row = rows[0]
    assert row.entity_type == "ref_role" and row.entity_id is None
    assert row.before["code"] == "dept_officer" and row.before["label"] == "Department Officer"
    assert row.before["description"].startswith("Works on cases assigned to them")
    assert row.after == {
        "code": "dept_officer",
        "label": "Department Officer (Legal)",
        "description": "Works on cases.",
    }
    assert _snapshot(world) == before  # the matrix, the memberships, no access_changed event
    # the new name is what every screen reads
    labels = api.get("/reference/labels", headers=h).json()["user_types"]
    mine = next(t for t in labels if t["code"] == "dept_officer")
    assert mine["label"] == "Department Officer (Legal)" and mine["description"] == "Works on cases."


def test_an_unchanged_save_is_not_audited(api, world):
    h = w.login(api, "root")
    with world.Session() as s:
        row = s.get(RefRole, "dept_officer")
        label, description = row.label, row.description
    r = api.patch(URL, json={"label": label, "description": description}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["changed"] is False
    assert _audits(world) == []


def test_an_empty_description_is_stored_as_null(api, world):
    h = w.login(api, "root")
    r = api.patch(URL, json={"label": "Department Officer", "description": "   "}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["description"] is None and r.json()["changed"] is True
    with world.Session() as s:
        assert s.get(RefRole, "dept_officer").description is None


def test_a_name_taken_without_regard_to_case_is_409(api, world):
    h = w.login(api, "root")
    r = api.patch(URL, json={"label": "auditor", "description": None}, headers=h)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "label_taken"
    assert _audits(world) == []
    # inactive rows count too
    with world.Session() as s:
        s.get(RefRole, "referral_reviewer").is_active = False
        s.commit()
    r = api.patch(URL, json={"label": "REFERRAL reviewer", "description": None}, headers=h)
    assert r.status_code == 409


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"label": "", "description": None}, "label_required"),
        ({"label": "   ", "description": None}, "label_required"),
        ({"label": "x" * 81, "description": None}, "label_too_long"),
        ({"label": "Officer", "description": "d" * 201}, "description_too_long"),
        ({"label": "Dept\x07Officer", "description": None}, "label_bad_characters"),
        ({"label": "Dept\nOfficer", "description": None}, "label_bad_characters"),
    ],
)
def test_limits_are_422_with_their_codes(api, world, body, code):
    h = w.login(api, "root")
    r = api.patch(URL, json=body, headers=h)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == code
    assert _audits(world) == []


def test_eighty_characters_and_two_hundred_are_accepted(api):
    h = w.login(api, "root")
    r = api.patch(URL, json={"label": "L" * 80, "description": "d" * 200}, headers=h)
    assert r.status_code == 200, r.text


def test_super_admin_can_be_renamed(api, world):
    h = w.login(api, "root")
    r = api.patch(
        "/admin/access/types/super_admin/name",
        json={"label": "Chief Administrator", "description": None},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["code"] == "super_admin" and r.json()["label"] == "Chief Administrator"


def test_access_without_the_function_and_an_unknown_role(api, world):
    r = api.patch(URL, json={"label": "Officer", "description": None}, headers=w.login(api, "edu_admin"))
    assert r.status_code == 403
    h = w.login(api, "root")
    r = api.patch(
        "/admin/access/types/nobody/name", json={"label": "Officer", "description": None}, headers=h
    )
    assert r.status_code == 422
    assert _audits(world) == []


def test_put_name_is_not_a_function(api):
    """The PATCH route never collides with `PUT /admin/access/types/{role}/{permission}`."""
    h = w.login(api, "root")
    r = api.put(URL, json={"enabled": True}, headers=h)
    assert r.status_code == 422


def test_two_concurrent_renames_to_one_name_end_with_one_conflict(world):
    """Two sessions: the first renames and holds its transaction; the second's clash check cannot see it, so the
    unique index waits for the first and refuses the second with `label_taken`."""
    outcome: dict[str, object] = {}

    def second() -> None:
        with world.Session() as s:
            actor, user = world.actor(s, "root")
            try:
                access.rename_type(s, actor, user, "auditor", "Case Reader", None)
                s.commit()
                outcome["second"] = "saved"
            except access.TypeLabelTaken:
                s.rollback()
                outcome["second"] = "label_taken"

    with world.Session() as first:
        actor, user = world.actor(first, "root")
        access.rename_type(first, actor, user, "dept_officer", "case reader", None)
        thread = threading.Thread(target=second)
        thread.start()
        time.sleep(0.5)
        first.commit()
    thread.join(timeout=20)
    assert outcome == {"second": "label_taken"}
    with world.Session() as s:
        assert s.get(RefRole, "dept_officer").label == "case reader"
        assert s.get(RefRole, "auditor").label == "Auditor"
