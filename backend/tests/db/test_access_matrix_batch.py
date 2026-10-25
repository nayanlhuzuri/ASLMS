"""`PUT /admin/access/types/{role}` (design case-workspace-admin, decision 27): one transaction; each changed function
writes its own `access.matrix` audit row and `access_changed` event; unchanged entries write nothing; `admin.tickets`
or a retired function refuses the whole batch (400) and saves none of it; the super admin type 403; a caller without
`access.manage_types` 403; duplicates or more than 60 changes 422; the one-cell PUT still works."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.events import AuditLog, Event
from aslms.domain.reference import EventType
from tests.db import docs_support as ds
from tests.db import workflow_support as w

URL = "/admin/access/types/dept_officer"


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


def _counts(world) -> tuple[int, int]:
    with world.Session() as s:
        audits = s.scalar(
            sa.select(sa.func.count()).select_from(AuditLog).where(AuditLog.action == "access.matrix")
        )
        events = s.scalar(
            sa.select(sa.func.count()).select_from(Event).where(Event.type == EventType.ACCESS_CHANGED)
        )
        return int(audits), int(events)


def _row(api, h) -> dict[str, bool]:
    r = api.get(URL, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_three_changes_write_three_audits_and_events(api, world):
    h = w.login(api, "root")
    row = _row(api, h)
    picks = ["custody.track", "custody.recall", "reports.department"]
    changes = [{"permission": p, "enabled": not row[p]} for p in picks]
    before = _counts(world)
    r = api.put(URL, json={"changes": changes}, headers=h)
    assert r.status_code == 200, r.text
    assert all(r.json()[p] is (not row[p]) for p in picks)
    assert _counts(world) == (before[0] + 3, before[1] + 3)
    with world.Session() as s:
        rows = s.scalars(sa.select(AuditLog).where(AuditLog.action == "access.matrix")).all()
        assert {a.after["permission"] for a in rows} >= set(picks)


def test_unchanged_entries_write_nothing(api, world):
    h = w.login(api, "root")
    row = _row(api, h)
    before = _counts(world)
    r = api.put(URL, json={"changes": [{"permission": "notes.add", "enabled": row["notes.add"]}]}, headers=h)
    assert r.status_code == 200, r.text
    assert _counts(world) == before
    # a mixed batch writes only the changed one
    r = api.put(
        URL,
        json={
            "changes": [
                {"permission": "notes.add", "enabled": row["notes.add"]},
                {"permission": "custody.track", "enabled": not row["custody.track"]},
            ]
        },
        headers=h,
    )
    assert r.status_code == 200
    assert _counts(world) == (before[0] + 1, before[1] + 1)


@pytest.mark.parametrize(
    ("refused", "code"), [("admin.tickets", "reserved_function"), ("requests.send", "retired_function")]
)
def test_a_refused_function_saves_nothing(api, world, refused, code):
    h = w.login(api, "root")
    row = _row(api, h)
    before = _counts(world)
    r = api.put(
        URL,
        json={
            "changes": [
                {"permission": "custody.track", "enabled": not row["custody.track"]},
                {"permission": refused, "enabled": True},
            ]
        },
        headers=h,
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["code"] == code and refused in detail["message"]
    assert _row(api, h) == row
    assert _counts(world) == before


def test_super_admin_type_and_callers_without_the_function_get_403(api, world):
    h = w.login(api, "root")
    r = api.put(
        "/admin/access/types/super_admin",
        json={"changes": [{"permission": "notes.add", "enabled": False}]},
        headers=h,
    )
    assert r.status_code == 403
    before = _counts(world)
    r = api.put(
        URL,
        json={"changes": [{"permission": "notes.add", "enabled": False}]},
        headers=w.login(api, "edu_admin"),
    )
    assert r.status_code == 403
    assert _counts(world) == before


def test_duplicates_empty_and_too_many_get_422(api):
    h = w.login(api, "root")
    dup = [{"permission": "notes.add", "enabled": True}, {"permission": "notes.add", "enabled": False}]
    assert api.put(URL, json={"changes": dup}, headers=h).status_code == 422
    assert api.put(URL, json={"changes": []}, headers=h).status_code == 422
    many = [{"permission": "notes.add", "enabled": True}] * 61
    assert api.put(URL, json={"changes": many}, headers=h).status_code == 422
    assert (
        api.put(URL, json={"changes": [{"permission": "nope", "enabled": True}]}, headers=h).status_code
        == 422
    )


def test_one_cell_put_still_works(api, world):
    h = w.login(api, "root")
    row = _row(api, h)
    before = _counts(world)
    r = api.put(f"{URL}/custody.track", json={"enabled": not row["custody.track"]}, headers=h)
    assert r.status_code == 200
    assert r.json()["custody.track"] is (not row["custody.track"])
    assert _counts(world) == (before[0] + 1, before[1] + 1)
