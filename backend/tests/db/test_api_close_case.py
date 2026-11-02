"""The Close Case API (design close-case, "API"): `POST /cases/{ref}/close` and `/reopen` with their shapes and refusals,
`closure` and the five flags on `GET /cases/{ref}`, the custody card's `closed`, `closure` on `/inbox/mine` and
`/inbox/claimed` with the split counts, `closed` on the case summaries, the audit rows without the remark, and an
invisible case answering 404."""

from __future__ import annotations

import pytest

from tests.db import closure_support as c
from tests.db import docs_support as ds
from tests.db import workflow_support as w

REMARK = "Disposed of; compliance reported, nothing pending."


@pytest.fixture()
def api(world, tmp_path):
    w.widen(world)
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture()
def case_id(api, world):
    with world.Session() as s:
        case = c.disposed_case(s, world)
        s.commit()
        return case.id


def test_close_and_reopen_through_the_api(api, world, case_id):
    h1 = w.login(api, "edu_off1")
    detail = api.get(f"/cases/{case_id}", headers=h1).json()
    flags = detail["workflow"]
    assert flags["close"] is True and flags["close_as"] == "holder" and flags["close_blocked"] is None
    assert flags["reopen"] is False and detail["closure"] is None and detail["custody"]["closed"] is False
    before = api.get("/inbox/mine/counts", headers=h1).json()

    r = api.post(f"/cases/{case_id}/close", headers=h1, json={"remark": REMARK})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["visible"] is True and out["note_ref_no"].startswith("ASLMS/EDU/NOTE/")
    assert out["card"]["closed"] is True and out["card"]["holder_user"] is None
    assert out["card"]["can_send"] is False and out["card"]["can_recall"] is False
    assert out["closure"]["closed_as"] == "holder" and out["closure"]["note_ref_no"] == out["note_ref_no"]
    assert out["closure"]["closed_by"]["office_code"] == "EDU" and out["closure"]["reopened_at"] is None

    detail = api.get(f"/cases/{case_id}", headers=h1).json()
    assert detail["closure"]["note_ref_no"] == out["note_ref_no"] and detail["workflow"]["close"] is False
    after = api.get("/inbox/mine/counts", headers=h1).json()
    assert after["files"] == before["files"] - 1
    assert after["all_open"] + after["all_closed"] == after["all"] and after["all_closed"] == 1
    closed_rows = api.get("/inbox/mine?view=all&closure=closed", headers=h1).json()
    assert [i["case"]["id"] for i in closed_rows["items"]] == [str(case_id)]
    assert closed_rows["items"][0]["case"]["closed"] is True
    assert api.get("/inbox/mine?view=all&closure=open", headers=h1).json()["total"] == 0
    assert api.get("/inbox/mine?view=all&closure=bad", headers=h1).status_code == 400

    # the closing note is readable by the head and the Auditor; the audit row has the digest, never the text
    for key in ("edu_head", "edu_auditor"):
        note = api.get(f"/notes/{out['note_ref_no'].replace('/', '-')}", headers=w.login(api, key))
        assert note.status_code == 200 and note.json()["kind"] == "closing", key
    rows = api.get("/audit?action=case.closed", headers=w.login(api, "root")).json()["items"]
    assert len(rows) == 1 and REMARK not in str(rows[0])

    hh = w.login(api, "edu_head")
    claimed = api.get("/inbox/claimed?case_state=all&closure=closed", headers=hh).json()
    assert [i["case"]["id"] for i in claimed["items"]] == [str(case_id)]
    [block] = api.get("/inbox/counts", headers=hh).json()["departments"]
    assert (
        block["claimed_open"] + block["claimed_closed"] == block["claimed_active"] + block["claimed_disposed"]
    )

    # a closed case does not move and cannot be closed again
    with world.Session() as s:
        target = str(world.membership(s, "edu_off2").id)
    r = api.post(
        f"/cases/{case_id}/custody/send",
        headers=hh,
        json={"to_membership": target, "pending_action": "examine", "remark": "please look"},
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "case_closed"
    r = api.post(f"/cases/{case_id}/close", headers=hh, json={"remark": REMARK})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_closed"

    # the department admin reopens with a reason
    ha = w.login(api, "edu_admin")
    assert api.get(f"/cases/{case_id}", headers=ha).json()["workflow"]["reopen"] is True
    r = api.post(f"/cases/{case_id}/reopen", headers=ha, json={"reason": "The order needs compliance again."})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["closure"]["reopen_kind"] == "manual" and out["closure"]["reopened_status"] == "disposed"
    assert out["closure"]["reopen_note_ref_no"] == out["note_ref_no"] and out["card"]["closed"] is False
    assert out["card"]["pending_action"] == "examine" and out["card"]["holder_office"]["code"] == "EDU"
    assert api.get(f"/cases/{case_id}", headers=hh).json()["workflow"]["close"] is True
    r = api.post(f"/cases/{case_id}/reopen", headers=ha, json={"reason": "again please"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_closed"
    rows = api.get("/audit?action=case.reopened", headers=w.login(api, "root")).json()["items"]
    assert len(rows) == 1 and rows[0]["actor"]["name"] == "Edu Admin"


def test_refusals_through_the_api(api, world, case_id):
    h1 = w.login(api, "edu_off1")
    r = api.post(f"/cases/{case_id}/close", headers=h1, json={"remark": "no"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_field"
    # no function on the route
    assert (
        api.post(
            f"/cases/{case_id}/close", headers=w.login(api, "edu_admin"), json={"remark": REMARK}
        ).status_code
        == 403
    )
    assert api.post(f"/cases/{case_id}/reopen", headers=h1, json={"reason": REMARK}).status_code == 403
    # invisible case
    r = api.post(f"/cases/{case_id}/close", headers=w.login(api, "fin_off"), json={"remark": REMARK})
    assert r.status_code == 404
    # a holder from another department
    with world.Session() as s:
        case = s.get(c.Case, case_id)
        w.send(s, world, "edu_off1", case, "health_off", pending_action_="opinion")
        s.commit()
    r = api.post(f"/cases/{case_id}/close", headers=w.login(api, "health_off"), json={"remark": REMARK})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "not_closer"


def test_closer_who_loses_sight_gets_visible_false(api, world, case_id):
    with world.Session() as s:
        case = s.get(c.Case, case_id)
        w.send(s, world, "edu_off1", case, "edu_off2", pending_action_="examine")
        s.commit()
    h2 = w.login(api, "edu_off2")
    r = api.post(f"/cases/{case_id}/close", headers=h2, json={"remark": REMARK})
    assert r.status_code == 201, r.text
    assert r.json()["visible"] is False and r.json()["card"] is None
    assert api.get(f"/cases/{case_id}", headers=h2).status_code == 404
