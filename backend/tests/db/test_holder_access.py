"""The holder's working access (design custody-workflow, decision 9): a holder from another department sees the
case, uploads, sets a stage and writes drafts, but cannot claim, allot, transfer, take over or recall; once the
file is sent on they lose sight of it (404) and keep the leg in `GET /custody/sent`."""

from __future__ import annotations

import pytest

from tests import samplefiles as sf
from tests.db import docs_support as ds
from tests.db import workflow_support as w


@pytest.fixture()
def api(world, tmp_path):
    w.widen(world)
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture()
def held(api, world):
    """An EDU case sent by the EDU officer to the HEALTH officer."""
    with world.Session() as s:
        case = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", case, "health_off", pending_action_="report")
        s.commit()
        return case.id


def test_holder_from_another_department_works_on_the_case(api, world, held):
    hh = w.login(api, "health_off")
    r = api.get(f"/cases/{held}", headers=hh)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "custody" in body["access_basis"]
    assert body["custody"]["holder_user"]["id"] == str(w.uid(world, "health_off"))
    assert body["custody"]["can_send"] is True and body["custody"]["can_recall"] is False
    assert body["custody"]["remark"]  # a working basis sees the remark
    r = ds.upload(api, hh, held, sf.text_pdf(["parawise comments"]), doc_type="correspondence")
    assert r.status_code == 201, r.text
    r = api.post(f"/cases/{held}/stages", headers=hh, json={"stage": "parawise_comments_received"})
    assert r.status_code == 201, r.text
    r = api.post(
        f"/cases/{held}/notes",
        headers=hh,
        data={"kind": "general", "body": "draft", "visibility": "case_scope"},
    )
    assert r.status_code == 201 and r.json()["draft"] is True
    # no ownership action and no recall
    assert api.post(f"/cases/{held}/claim", headers=hh, json={}).status_code in (403, 404, 409)
    assert api.post(
        f"/cases/{held}/allot", headers=hh, json={"officer_user_id": str(w.uid(world, "health_off"))}
    ).status_code in (403, 404)
    assert api.post(f"/cases/{held}/take-over", headers=hh, json={}).status_code in (403, 404)
    r = api.post(f"/cases/{held}/custody/recall", headers=hh, json={"remark": "mine now"})
    assert r.status_code == 403


def test_after_sending_on_the_previous_holder_loses_sight(api, world, held):
    hh = w.login(api, "health_off")
    with world.Session() as s:
        target = world.membership(s, "fin_off").id
    r = api.post(
        f"/cases/{held}/custody/send",
        headers=hh,
        json={"to_membership": str(target), "pending_action": "opinion", "remark": "for opinion"},
    )
    assert r.status_code == 201, r.text
    assert len(r.json()["finalised_notes"]) == 0
    assert r.json()["card"] is None  # the sender no longer sees the case
    assert api.get(f"/cases/{held}", headers=hh).status_code == 404
    sent = api.get("/custody/sent", headers=hh).json()
    assert sent["total"] == 1 and sent["items"][0]["leg"]["holder_office"]["code"] == "FIN"
    assert sent["items"][0]["leg"]["remark"] == "for opinion"
    # the EDU officer who sent it first still sees the case through the allotment
    assert api.get(f"/cases/{held}", headers=w.login(api, "edu_off1")).status_code == 200
