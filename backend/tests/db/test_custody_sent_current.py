"""`current` on `GET /custody/sent` (design case-workspace-admin, decisions 20 and 23): true for the case's current leg,
false once the case moved on or was recalled, null when the sender can no longer open the case; `visible` unchanged."""

from __future__ import annotations

from aslms.services import custody
from tests.db import docs_support as ds
from tests.db import workflow_support as w


def _rows(s, world, key):
    _, user = world.actor(s, key)
    return custody.sent(s, user).items


def test_current_true_then_false_after_a_move_and_a_recall(world):
    with world.Session() as s:
        case = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", case, "edu_off2")  # off1 keeps sight as the allottee
        [row] = _rows(s, world, "edu_off1")
        assert row["visible"] is True and row["current"] is True
        w.send(s, world, "edu_off2", case, "edu_counsel")
        [row] = _rows(s, world, "edu_off1")
        assert row["visible"] is True and row["current"] is False
        [row] = _rows(s, world, "edu_off2")  # an officer loses sight of a case sent on
        assert row["visible"] is False and row["current"] is None
        w.recall(s, world, "edu_admin", case)
        [recall_row] = _rows(s, world, "edu_admin")
        assert recall_row["leg"]["reason"] == "recalled" and recall_row["current"] is True
        s.rollback()


def test_current_is_null_when_the_sender_cannot_open_the_case(world, tmp_path):
    w.widen(world)
    with world.Session() as s:
        case = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", case, "fin_off")
        w.send(s, world, "fin_off", case, "edu_off2")
        s.commit()
        [row] = _rows(s, world, "fin_off")
        assert row["visible"] is False and row["current"] is None
    api = ds.make_api(world, tmp_path)
    try:
        r = api.get("/custody/sent", headers=w.login(api, "fin_off"))
        assert r.status_code == 200, r.text
        [item] = r.json()["items"]
        assert item["visible"] is False and item["current"] is None
        r = api.get("/custody/sent", headers=w.login(api, "edu_off1"))
        [item] = r.json()["items"]
        assert item["visible"] is True and item["current"] is False
    finally:
        api.__exit__(None, None, None)
