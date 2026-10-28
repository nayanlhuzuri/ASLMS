"""No user may edit a court-given date (design `next-date-direct`, decision 6, owner's answer 4): with the court's
record, an exact reading or an around reading, enter, confirm and reject answer 409 `court_date_fixed` for a
department officer, admin and head; the super admin never works on a department's case, so meets the 403 first and
cannot edit it either; 404 and 403 still come first; a refusal writes no audit row; the workflow block says why;
holding `next_dates.correct` never lifts the rule."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.alerts import NextDate, NextDateSource, ReviewStatus
from aslms.domain.events import AuditLog
from aslms.domain.org import PermissionEffect
from aslms.domain.reference import Permission
from tests.db import docs_support as ds
from tests.db import next_dates_support as h
from tests.db import workflow_support as w
from tests.db.report_support import override

WORKERS = ("edu_off1", "edu_admin", "edu_head")


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


def _pending(s, case, order):
    """A legacy suggestion of the current order, so confirm and reject have a row to act on."""
    row = NextDate(
        case_id=case.id,
        next_date=h.days(40),
        source=NextDateSource.ORDER_PERIOD,
        order_id=order.id,
        needs_review=True,
        review_status=ReviewStatus.PENDING,
    )
    s.add(row)
    s.flush()
    return row


def _calls(case, row):
    return (
        (f"/cases/{case.id}/next-dates", {"next_date": str(h.days(20))}),
        (f"/next-dates/{row.id}/confirm", {}),
        (f"/next-dates/{row.id}/reject", {}),
        (f"/next-dates/{row.id}/reject", {"note": "wrong", "next_date": str(h.days(21))}),
    )


@pytest.mark.parametrize("kind", ["court", "exact", "around"])
def test_every_type_gets_court_date_fixed(api, world, kind):
    with world.Session() as s:
        off1 = world.user(s, "edu_off1")
        case = h.claimed(
            s, world, officer_user_id=off1.id, next_hearing=h.days(9) if kind == "court" else None
        )
        text = {
            "court": "Issue notice.",
            "exact": f"List this matter on {h.dmy(h.days(12))}.",
            "around": "List the matter after 3 weeks.",
        }[kind]
        order = h.order_with_text(s, case, text, order_date=h.days(-1))
        h.read(s)
        row = _pending(s, case, order)
        s.commit()
    for key in WORKERS:
        headers = w.login(api, key)
        for path, body in _calls(case, row):
            r = api.post(path, headers=headers, json=body)
            assert (r.status_code, r.json()["detail"]["code"]) == (409, "court_date_fixed"), (
                key,
                path,
                r.text,
            )
        wf = api.get(f"/cases/{case.id}", headers=headers).json()["workflow"]
        assert (wf["next_dates"], wf["next_dates_blocked"]) == (False, "court_date_fixed"), key
    headers = w.login(api, "root")
    for path, body in _calls(case, row):
        r = api.post(path, headers=headers, json=body)
        assert (r.status_code, r.json()["detail"]["code"]) == (403, "not_working_on_case"), (path, r.text)
    wf = api.get(f"/cases/{case.id}", headers=headers).json()["workflow"]
    assert (wf["next_dates"], wf["next_dates_blocked"]) == (False, "court_date_fixed")
    with world.Session() as s:
        assert not s.scalar(
            sa.select(sa.func.count()).select_from(AuditLog).where(AuditLog.action.like("next_date.%"))
        )
        assert s.get(NextDate, row.id).review_status == ReviewStatus.PENDING
        assert (
            s.scalar(
                sa.select(sa.func.count())
                .select_from(NextDate)
                .where(NextDate.source == NextDateSource.MANUAL)
            )
            == 0
        )


def test_404_and_403_come_first(api, world):
    with world.Session() as s:
        case = h.claimed(s, world, next_hearing=h.days(9))
        h.order_with_text(s, case, "Issue notice.", order_date=h.days(-1))
        h.read(s)
        s.commit()
    body = {"next_date": str(h.days(20))}
    # another department cannot see the case; an officer it is not allotted to neither
    for key in ("health_off", "edu_off2"):
        r = api.post(f"/cases/{case.id}/next-dates", headers=w.login(api, key), json=body)
        assert r.status_code == 404, key
    # without the function
    r = api.post(f"/cases/{case.id}/next-dates", headers=w.login(api, "oversight"), json=body)
    assert r.status_code == 403


def test_holding_correct_never_lifts_the_rule(api, world):
    """Decision 6's exception is only `next_dates.correct` on a reading; it never permits enter, confirm or reject."""
    with world.Session() as s:
        override(s, world, "edu_admin", Permission.NEXT_DATES_CORRECT, PermissionEffect.GRANT)
        case = h.claimed(s, world)
        order = h.order_with_text(s, case, "List the matter after 3 weeks.", order_date=h.days(-1))
        h.read(s)
        row = _pending(s, case, order)
        s.commit()
    headers = w.login(api, "edu_admin")
    for path, body in _calls(case, row):
        assert api.post(path, headers=headers, json=body).json()["detail"]["code"] == "court_date_fixed", path
    wf = api.get(f"/cases/{case.id}", headers=headers).json()["workflow"]
    assert wf["next_date_correct"] is True and wf["next_dates"] is False
