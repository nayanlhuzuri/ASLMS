"""The next-dates API (design `next-date-extraction`, "API", as changed by `next-date-direct`, decisions 2, 6, 9 and
11): the review queue (enter items only, with their reason) with its function, membership rule, filters, kind and
paging; enter with its errors; confirm and reject refused with 409 `court_date_fixed`; a case's next dates; the
overview, Orders tab and dashboard additions."""

from __future__ import annotations

import pytest

from aslms.domain.alerts import NextDate, NextDateSource, ReviewStatus
from aslms.domain.documents import TextStatus
from aslms.domain.org import PermissionEffect
from aslms.domain.reference import Permission, Role
from tests.db import docs_support as ds
from tests.db import next_dates_support as h
from tests.db import workflow_support as w
from tests.db.report_support import override
from tests.db.world import add_membership, make_case

UNCLEAR = "List the matter after vacation."
NONE = "Issue notice. Steps within a week."


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


def _enter_item(s, world, text=UNCLEAR, **kw):
    case = h.claimed(s, world, **kw)
    order = h.order_with_text(s, case, text, order_date=h.days(-1))
    h.read(s)
    return case, order


def test_queue(api, world):
    with world.Session() as s:
        case, order = _enter_item(s, world)
        unit_case, unit_order = _enter_item(s, world, text=NONE, unit_code="EDU-DSE")
        scanned = h.claimed(s, world)
        scan_order = h.order_with_text(s, scanned, None, order_date=h.days(-2), text_status=TextStatus.NONE)
        dated = h.claimed(s, world)  # a period: shown directly, no item
        h.order_with_text(s, dated, "List the matter after 2 (two) weeks.", order_date=h.days(-1))
        # the EDU admin also works in HEALTH, where a HEALTH case is allotted to them and the function is denied
        admin = world.user(s, "edu_admin")
        add_membership(s, admin, world.office(s, "HEALTH"), Role.DEPT_OFFICER)
        override(s, world, "edu_admin", Permission.NEXT_DATES_REVIEW, PermissionEffect.DENY, office="HEALTH")
        health_case, health_order = _enter_item(s, world, key="health_admin", officer_user_id=admin.id)
        h.read(s)
        s.commit()
    headers = w.login(api, "edu_admin")
    r = api.get("/next-dates/review", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert {(i["id"], i["reason"]) for i in body["items"]} == {
        (str(order.id), "unclear"),
        (str(unit_order.id), "none"),
        (str(scan_order.id), "no_text"),
    }
    assert {i["kind"] for i in body["items"]} == {"enter"}
    first = body["items"][0]
    assert first["id"] == str(scan_order.id) and first["departments"] == ["EDU"]
    assert first["next_date"] is None and first["act_by"] == str(h.days(28))
    unclear = next(i for i in body["items"] if i["id"] == str(order.id))
    assert unclear["order"]["order_no"] and unclear["phrase"] and unclear["rule"] == "no_countable_date"
    assert unclear["case"]["id"] == str(case.id)
    assert str(health_order.id) not in {i["id"] for i in body["items"]}
    r = api.get("/next-dates/review", headers=headers, params={"kind": "confirm"})
    assert r.json() == {"items": [], "total": 0}  # decision 9: no confirm item
    r = api.get("/next-dates/review", headers=headers, params={"limit": 1, "offset": 2})
    assert r.json()["total"] == 3 and len(r.json()["items"]) == 1
    # the shared case filters: no enter item has a next hearing, none differs
    for params in ({"next_from": str(h.days(1))}, {"next_differs": "true"}):
        assert api.get("/next-dates/review", headers=headers, params=params).json()["total"] == 0
    assert api.get("/next-dates/review", headers=headers, params={"next_differs": "maybe"}).status_code == 422
    assert api.get("/next-dates/review", headers=headers, params={"kind": "x"}).status_code == 400
    r = api.get("/next-dates/review", headers=w.login(api, "dse_user"))
    assert [i["id"] for i in r.json()["items"]] == [str(unit_order.id)]
    r = api.get("/next-dates/review", headers=w.login(api, "health_admin"))
    assert [i["id"] for i in r.json()["items"]] == [str(health_order.id)]
    assert api.get("/next-dates/review", headers=w.login(api, "oversight")).status_code == 403
    with world.Session() as s:  # the HEALTH membership with the function lists the HEALTH item too
        override(s, world, "edu_admin", Permission.NEXT_DATES_REVIEW, None, office="HEALTH")
        s.commit()
    r = api.get("/next-dates/review", headers=headers)
    assert r.json()["total"] == 4
    item = next(i for i in r.json()["items"] if i["id"] == str(health_order.id))
    assert item["departments"] == ["HEALTH"] and item["case"]["id"] == str(health_case.id)
    del unit_case


def test_confirm_and_reject_answer_court_date_fixed(api, world):
    """Decision 6: a reading of an order is a court-given date."""
    with world.Session() as s:
        case = h.claimed(s, world)
        order = h.order_with_text(s, case, "x", order_date=h.days(-1))
        row = NextDate(
            case_id=case.id,
            next_date=h.days(12),
            source=NextDateSource.ORDER_PERIOD,
            order_id=order.id,
            needs_review=True,
            review_status=ReviewStatus.PENDING,
        )
        s.add(row)
        s.commit()
    headers = w.login(api, "edu_admin")
    for path, body in (
        (f"/next-dates/{row.id}/confirm", {}),
        (f"/next-dates/{row.id}/reject", {}),
        (f"/next-dates/{row.id}/reject", {"note": "wrong", "next_date": str(h.days(20))}),
        (f"/cases/{case.id}/next-dates", {"next_date": str(h.days(20))}),
    ):
        r = api.post(path, headers=headers, json=body)
        assert (r.status_code, r.json()["detail"]["code"]) == (409, "court_date_fixed"), (path, r.text)
        assert "cannot be changed" in r.json()["detail"]["message"]
    # 404 and 403 still come first
    assert (
        api.post("/next-dates/0190a000-0000-7000-8000-000000000000/confirm", headers=headers).status_code
        == 404
    )
    assert api.post(f"/next-dates/{row.id}/confirm", headers=w.login(api, "health_off")).status_code == 404
    assert api.post(f"/next-dates/{row.id}/confirm", headers=w.login(api, "edu_reviewer")).status_code in (
        403,
        404,
    )
    r = api.post(f"/next-dates/{row.id}/reject", headers=headers, json={"next_date": str(h.days(-3))})
    assert r.status_code == 400  # the field check before the lock, as before
    wf = api.get(f"/cases/{case.id}", headers=headers).json()["workflow"]
    assert wf["next_dates"] is False and wf["next_dates_blocked"] == "court_date_fixed"


def test_enter(api, world):
    with world.Session() as s:
        case, order = _enter_item(s, world)
        pool = make_case(s)
        s.commit()
    headers = w.login(api, "edu_admin")
    wf = api.get(f"/cases/{case.id}", headers=headers).json()["workflow"]
    assert wf["next_dates"] is True and wf["next_dates_blocked"] is None
    r = api.post(
        f"/cases/{case.id}/next-dates",
        headers=headers,
        json={"next_date": str(h.days(30)), "note": "n", "order": str(order.id)},
    )
    assert r.status_code == 201, r.text
    assert r.json()["note"] == "n" and r.json()["created_by"]["name"] == "Edu Admin"
    r = api.post(
        f"/cases/{case.id}/next-dates",
        headers=headers,
        json={"next_date": str(h.days(30)), "note": "n", "order": str(order.id)},
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
    assert [i["source"] for i in items] == ["manual"] and items[0]["effective"] is True
    assert api.get(f"/cases/{case.id}/next-dates", headers=w.login(api, "health_off")).status_code == 404
    detail = api.get(f"/cases/{case.id}", headers=headers).json()
    assert detail["next_date_from_orders"]["next_date"] == str(h.days(30))
    assert detail["next_dates_to_review"] == 0
    assert detail["next_hearing"]["date"] == str(h.days(30)) and detail["next_hearing"]["basis"] == "manual"
    r = api.get(f"/cases/{case.id}/orders", headers=headers)
    (o,) = r.json()["items"]
    assert o["next_date_status"] == "unclear" and o["next_date_found"] is None
    assert o["next_date_rule"] == "no_countable_date" and o["next_date_phrase"]
    r = api.get("/dashboard", headers=headers)
    assert r.status_code == 200
