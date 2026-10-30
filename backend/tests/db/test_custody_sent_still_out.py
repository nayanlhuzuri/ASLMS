"""`still_out` on `GET /custody/sent` (design case-inbox-simplify, decisions 6 and 7): only sends that are still the
case's current leg, on a case the sender can open now, not held by the sender; overdue first, then newest first.
Without the parameter the list and its order are unchanged. Reading writes nothing."""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa

from aslms.domain.events import AuditLog, Event
from aslms.domain.reference import Role
from aslms.domain.workflow import CustodyHistory
from aslms.services import custody
from aslms.services.workflow_common import today_ist
from tests.db import docs_support as ds
from tests.db import workflow_support as w
from tests.db.world import add_membership


def _ids(page) -> list[str]:
    return [str(i["case"]["id"]) for i in page.items]


def _sent(s, world, key, **kw):
    _, user = world.actor(s, key)
    return custody.sent(s, user, **kw)


def test_still_out_keeps_current_sends_only(world):
    with world.Session() as s:
        kept = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", kept, "edu_off2")  # still with off2: still out
        moved = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", moved, "edu_off2")
        w.send(s, world, "edu_off2", moved, "edu_counsel")  # moved on
        recalled = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", recalled, "edu_off2")
        w.recall(s, world, "edu_admin", recalled)
        # a send to the sender's own other membership is With Me, not still out
        add_membership(s, world.user(s, "edu_off1"), world.office(s, "HEALTH"), Role.DEPT_OFFICER, "SO")
        own_case = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", own_case, "edu_off2")
        w.send(s, world, "edu_off2", own_case, "edu_off1", to_office="HEALTH")
        s.flush()
        assert _ids(_sent(s, world, "edu_off1", still_out=True)) == [str(kept.id)]
        assert _ids(_sent(s, world, "edu_admin", still_out=True)) == []  # a recall leg is not a send
        page = _sent(s, world, "edu_off1", still_out=True)
        assert all(i["visible"] is True and i["current"] is True for i in page.items)
        assert all(i["leg"]["reason"] == "sent" for i in page.items)
        s.rollback()


def test_still_out_hides_cases_no_longer_visible(world, tmp_path):
    w.widen(world)
    with world.Session() as s:
        case = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", case, "edu_off2")
        w.send(s, world, "edu_off2", case, "edu_counsel")  # off2's leg moved on; off2 loses sight
        lost = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", lost, "fin_off")
        w.send(s, world, "fin_off", lost, "edu_off2")  # fin_off's leg is current, but fin_off cannot open it
        s.commit()
        lost_id = str(lost.id)
    api = ds.make_api(world, tmp_path)
    try:
        fin = w.login(api, "fin_off")
        r = api.get("/custody/sent?still_out=true", headers=fin)
        assert r.status_code == 200, r.text
        assert r.json() == {"items": [], "total": 0}
        r = api.get("/custody/sent", headers=fin)
        [item] = r.json()["items"]
        assert str(item["case"]["id"]) == lost_id
        assert item["visible"] is False and item["current"] is None
    finally:
        api.__exit__(None, None, None)


def test_still_out_order_overdue_first(world, monkeypatch):
    from aslms.services import workflow_common

    today = today_ist()
    with world.Session() as s:
        later, overdue, none_old, none_new = (w.claimed_case(s, world) for _ in range(4))
        s.commit()
        w.send(s, world, "edu_off1", later, "edu_off2", due_date=today + timedelta(days=5))
        # a send made a week ago with a due date that has now passed (legs are append-only: sent "back then")
        monkeypatch.setattr(workflow_common, "today_ist", lambda: today - timedelta(days=7))
        w.send(s, world, "edu_off1", overdue, "edu_off2", due_date=today - timedelta(days=2))
        monkeypatch.undo()
        s.commit()
        w.send(s, world, "edu_off1", none_old, "edu_off2")
        s.commit()  # created_at is the transaction's time: the next send is newer
        w.send(s, world, "edu_off1", none_new, "edu_off2")
        s.commit()
        page = _sent(s, world, "edu_off1", still_out=True)
        assert _ids(page) == [str(overdue.id), str(later.id), str(none_new.id), str(none_old.id)]
        assert page.items[0]["leg"]["due_date"] < today


def test_still_out_total_matches_items(world):
    with world.Session() as s:
        for _ in range(3):
            w.send(s, world, "edu_off1", w.claimed_case(s, world), "edu_off2")
        moved = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", moved, "edu_off2")
        w.send(s, world, "edu_off2", moved, "edu_counsel")
        page = _sent(s, world, "edu_off1", still_out=True)
        assert page.total == len(page.items) == 3
        paged = _sent(s, world, "edu_off1", still_out=True, limit=2)
        assert paged.total == 3 and len(paged.items) == 2
        assert _sent(s, world, "edu_off1").total == 4
        s.rollback()


def test_sent_default_unchanged(world):
    with world.Session() as s:
        a = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", a, "edu_off2")
        s.commit()
        w.send(s, world, "edu_off2", a, "edu_counsel")
        s.commit()
        w.recall(s, world, "edu_admin", a)
        s.commit()
        b = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", b, "edu_off2")
        s.commit()
        [newest, oldest] = _sent(s, world, "edu_off1").items
        assert str(newest["case"]["id"]) == str(b.id) and newest["current"] is True
        assert str(oldest["case"]["id"]) == str(a.id) and oldest["current"] is False
        assert [i["leg"]["reason"] for i in _sent(s, world, "edu_admin").items] == ["recalled"]
        expected = s.execute(
            sa.select(CustodyHistory.case_id, CustodyHistory.seq_no)
            .where(
                CustodyHistory.actor_user_id == w.uid(world, "edu_off2"),
                CustodyHistory.reason.in_(("sent", "recalled")),
            )
            .order_by(CustodyHistory.created_at.desc(), CustodyHistory.id.desc())
        ).all()
        got = [(str(i["case"]["id"]), i["leg"]["seq_no"]) for i in _sent(s, world, "edu_off2").items]
        assert got == [(str(c), n) for c, n in expected]
        # the moved-on send of off2 is not still out (off2 lost sight of the case)
        assert _sent(s, world, "edu_off2", still_out=True).total == 0


@pytest.mark.parametrize("still_out", ["true", "false"])
def test_still_out_writes_nothing(world, tmp_path, still_out):
    with world.Session() as s:
        w.send(s, world, "edu_off1", w.claimed_case(s, world), "edu_off2")
        s.commit()
    api = ds.make_api(world, tmp_path)
    try:
        headers = w.login(api, "edu_off1")
        with world.Session() as s:
            before = (
                s.scalar(sa.select(sa.func.count()).select_from(AuditLog)),
                s.scalar(sa.select(sa.func.count()).select_from(Event)),
            )
        r = api.get(f"/custody/sent?still_out={still_out}", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["total"] == 1
        with world.Session() as s:
            after = (
                s.scalar(sa.select(sa.func.count()).select_from(AuditLog)),
                s.scalar(sa.select(sa.func.count()).select_from(Event)),
            )
        assert after == before
    finally:
        api.__exit__(None, None, None)
