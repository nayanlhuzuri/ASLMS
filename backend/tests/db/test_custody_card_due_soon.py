"""`due_soon` on the custody card (design case-workspace-admin, decisions 19 and 23): not overdue and due within
`request_due_soon_days` (IST), the window of `GET /custody/summary`: false when overdue, false with no due date, true on
the window's last day, false the day after; it follows the setting."""

from __future__ import annotations

from types import SimpleNamespace

import sqlalchemy as sa

from aslms.domain.cases import Case
from aslms.domain.workflow import Custody
from aslms.services import custody
from tests.db import docs_support as ds
from tests.db import workflow_support as w


def _set_due(s, case_id, due) -> None:
    s.execute(sa.update(Custody).where(Custody.case_id == case_id).values(due_date=due))
    s.expire_all()


def _card(s, world, case_id):
    _, user = world.actor(s, "edu_off1")
    return custody.card(s, user, s.get(Case, case_id))


def test_due_soon_window(world):
    with world.Session() as s:
        case = w.claimed_case(s, world)
        s.flush()
        case_id = case.id
        _set_due(s, case_id, None)
        assert _card(s, world, case_id)["due_soon"] is False
        _set_due(s, case_id, w.in_days(-1))
        c = _card(s, world, case_id)
        assert c["overdue"] is True and c["due_soon"] is False
        _set_due(s, case_id, w.in_days(0))
        assert _card(s, world, case_id)["due_soon"] is True
        _set_due(s, case_id, w.in_days(2))  # the default window's last day
        assert _card(s, world, case_id)["due_soon"] is True
        _set_due(s, case_id, w.in_days(3))
        assert _card(s, world, case_id)["due_soon"] is False
        s.rollback()


def test_due_soon_follows_the_setting(world, monkeypatch):
    monkeypatch.setattr(custody, "get_settings", lambda: SimpleNamespace(request_due_soon_days=5))
    with world.Session() as s:
        case = w.claimed_case(s, world)
        s.flush()
        case_id = case.id
        _set_due(s, case_id, w.in_days(5))
        assert _card(s, world, case_id)["due_soon"] is True
        _set_due(s, case_id, w.in_days(6))
        assert _card(s, world, case_id)["due_soon"] is False
        s.rollback()


def test_held_api_carries_due_soon(world, tmp_path):
    with world.Session() as s:
        case = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", case, "edu_off2", due_date=w.in_days(1))
        s.commit()
    api = ds.make_api(world, tmp_path)
    try:
        r = api.get("/custody/held", params={"scope": "me"}, headers=w.login(api, "edu_off2"))
        assert r.status_code == 200, r.text
        [item] = r.json()["items"]
        assert item["card"]["due_soon"] is True and item["card"]["overdue"] is False
    finally:
        api.__exit__(None, None, None)
