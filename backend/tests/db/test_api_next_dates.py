"""The next-dates API (design `next-date-extraction`, "API"): the review queue with its function, membership rule,
filters, kind and paging; confirm, reject and enter with their errors; a case's next dates; the overview, Orders
tab and dashboard additions."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.org import PermissionEffect
from aslms.domain.reference import Permission, Role
from tests.db import docs_support as ds
from tests.db import next_dates_support as h
from tests.db import workflow_support as w
from tests.db.report_support import override
from tests.db.world import add_membership, make_case


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


def _pending(s, world, text="List the matter after 2 (two) weeks.", **kw):
    case = h.claimed(s, world, **kw)
    order = h.order_with_text(s, case, text, order_date=h.days(-1))
    h.read(s)
    (row,) = h.rows(s, case)
    return case, order, row


def test_queue(api, world):
    with world.Session() as s:
        case, order, row = _pending(s, world)
        s.execute(sa.update(type(case)).where(type(case).id == case.id).values(next_hearing_date=h.days(3)))
        _, _, unit_row = _pending(s, world, unit_code="EDU-DSE")
        enter_case = h.claimed(s, world)
        enter_order = h.order_with_text(s, enter_case, "List after vacation.", order_date=h.days(-1))
        # the EDU admin also works in HEALTH, where a HEALTH case is allotted to them and the function is denied
        admin = world.user(s, "edu_admin")
        add_membership(s, admin, world.office(s, "HEALTH"), Role.DEPT_OFFICER)
        override(s, world, "edu_admin", Permission.NEXT_DATES_REVIEW, PermissionEffect.DENY, office="HEALTH")
        health_case, _, health_row = _pending(s, world, key="health_admin", officer_user_id=admin.id)
        h.read(s)
        s.commit()
    headers = w.login(api, "edu_admin")
    r = api.get("/next-dates/review", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert {i["id"] for i in body["items"]} == {str(row.id), str(unit_row.id), str(enter_order.id)}
    first = body["items"][0]
    assert first["kind"] == "confirm" and first["departments"] == ["EDU"]
    assert first["order"]["order_no"] and first["phrase"] and first["rule"] == "list_after_period"
    assert first["next_date"] == str(h.days(13)) and first["act_by"] == str(h.days(13))
    enter = body["items"][2]
    assert (
        enter["kind"] == "enter" and enter["next_date"] is None and enter["case"]["id"] == str(enter_case.id)
    )
    assert str(health_row.id) not in {i["id"] for i in body["items"]}
    r = api.get("/next-dates/review", headers=headers, params={"kind": "enter"})
    assert [i["id"] for i in r.json()["items"]] == [str(enter_order.id)]
    r = api.get("/next-dates/review", headers=headers, params={"limit": 1, "offset": 2})
    assert r.json()["total"] == 3 and len(r.json()["items"]) == 1
    r = api.get("/next-dates/review", headers=headers, params={"next_from": str(h.days(1))})
    assert [i["id"] for i in r.json()["items"]] == [str(row.id)]  # the shared case filters
    assert api.get("/next-dates/review", headers=headers, params={"kind": "x"}).status_code == 400
    r = api.get("/next-dates/review", headers=w.login(api, "dse_user"))
    assert [i["id"] for i in r.json()["items"]] == [str(unit_row.id)]
    r = api.get("/next-dates/review", headers=w.login(api, "health_admin"))
    assert [i["id"] for i in r.json()["items"]] == [str(health_row.id)]
    assert api.get("/next-dates/review", headers=w.login(api, "oversight")).status_code == 403
    with world.Session() as s:  # the HEALTH membership with the function lists the HEALTH item too
        override(s, world, "edu_admin", Permission.NEXT_DATES_REVIEW, None, office="HEALTH")
        s.commit()
    r = api.get("/next-dates/review", headers=headers)
    assert r.json()["total"] == 4
    item = next(i for i in r.json()["items"] if i["id"] == str(health_row.id))
    assert item["departments"] == ["HEALTH"] and item["case"]["id"] == str(health_case.id)


def test_confirm_a_date_already_passed_is_409(api, world):
    """Owner's second decision of 17 Oct 2026, point 4."""
    with world.Session() as s:
        case, _, row = _pending(s, world)
        s.execute(sa.update(type(row)).where(type(row).id == row.id).values(next_date=h.days(-1)))
        s.commit()
    r = api.post(f"/next-dates/{row.id}/confirm", headers=w.login(api, "edu_admin"), json={})
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "date_passed")


def test_confirm_reject_enter(api, world):
    with world.Session() as s:
        case, order, row = _pending(s, world)
        _, _, other_row = _pending(s, world)
        pool = make_case(s)
        s.commit()
    headers = w.login(api, "edu_admin")
    r = api.post(f"/next-dates/{row.id}/confirm", headers=headers, json={})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["review_status"] == "confirmed" and out["reviewed_by"]["name"] == "Edu Admin"
    assert out["order"]["id"] == str(order.id) and out["order"]["rule"] == "list_after_period"
    assert out["source"] == "order_period" and out["confidence"] == 0.6 and out["needs_review"] is True
    r = api.post(f"/next-dates/{row.id}/confirm", headers=headers, json={})
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "not_pending")
    assert (
        api.post("/next-dates/0190a000-0000-7000-8000-000000000000/confirm", headers=headers).status_code
        == 404
    )
    assert (
        api.post(f"/next-dates/{other_row.id}/confirm", headers=w.login(api, "health_off")).status_code == 404
    )
    assert api.post(
        f"/next-dates/{other_row.id}/confirm", headers=w.login(api, "edu_reviewer")
    ).status_code in (
        403,
        404,
    )
    r = api.post(f"/next-dates/{other_row.id}/reject", headers=headers, json={"next_date": str(h.days(-3))})
    assert r.status_code == 400
    r = api.post(
        f"/next-dates/{other_row.id}/reject",
        headers=headers,
        json={"note": "wrong", "next_date": str(h.days(20))},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rejected"]["review_status"] == "rejected" and body["rejected"]["note"] == "wrong"
    assert body["entered"]["ref_no"].startswith("ASLMS/EDU/NXT/") and body["entered"]["source"] == "manual"
    ref_dash = body["entered"]["ref_no"].replace("/", "-")
    r = api.post(f"/next-dates/{ref_dash}/confirm", headers=headers)  # a manual row is not pending
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "not_pending")
    r = api.post(
        f"/cases/{case.id}/next-dates", headers=headers, json={"next_date": str(h.days(30)), "note": "n"}
    )
    assert r.status_code == 201, r.text
    assert r.json()["note"] == "n" and r.json()["created_by"]["name"] == "Edu Admin"
    r = api.post(
        f"/cases/{case.id}/next-dates", headers=headers, json={"next_date": str(h.days(30)), "note": "n"}
    )
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "already_entered")
    r = api.post(f"/cases/{case.id}/next-dates", headers=headers, json={"next_date": str(h.days(600))})
    assert r.status_code == 400
    r = api.post(f"/cases/{pool.id}/next-dates", headers=headers, json={"next_date": str(h.days(3))})
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "not_owned")
    r = api.post(
        f"/cases/{case.id}/next-dates",
        headers=headers,
        json={"next_date": str(h.days(31)), "order": str(order.id), "extra": 1},
    )
    assert r.status_code == 422  # unknown fields refused
    r = api.post(
        f"/cases/{case.id}/next-dates", headers=w.login(api, "health_off"), json={"next_date": str(h.days(3))}
    )
    assert r.status_code == 404
    # the case's next dates, the overview and the orders tab
    r = api.get(f"/cases/{case.id}/next-dates", headers=headers)
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["source"] for i in items] == ["manual", "order_period"] and items[0]["effective"] is True
    assert api.get(f"/cases/{case.id}/next-dates", headers=w.login(api, "health_off")).status_code == 404
    r = api.get(f"/cases/{case.id}", headers=headers)
    assert r.json()["next_date_from_orders"]["next_date"] == str(h.days(30))
    assert r.json()["next_dates_to_review"] == 0
    r = api.get(f"/cases/{case.id}/orders", headers=headers)
    (o,) = r.json()["items"]
    assert o["next_date_status"] == "period" and o["next_date_found"] == str(h.days(13))
    assert o["next_date_rule"] == "list_after_period" and o["next_date_phrase"]
    r = api.get("/dashboard", headers=headers)
    assert r.status_code == 200
