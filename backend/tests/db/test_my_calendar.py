"""My calendar (design portal-ui-redesign, decision 8 and A6, as changed by next-date-direct, decision 10): `GET
/me/calendar` — the kinds for an officer (a hearing of an allotted case, a hearing counted from an order shown
directly as around, a due date of a held file; no next date to confirm any more), a colleague's and an unseen case
absent, the range limits (422), the default month grid, the order (date, kind, case) and that reading writes
nothing."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
import sqlalchemy as sa

from aslms.domain.alerts import ReviewStatus
from aslms.domain.cases import Case
from aslms.domain.events import AuditLog, Event
from aslms.domain.org import PermissionEffect
from aslms.domain.reference import Permission
from aslms.domain.workflow import Custody, PendingAction
from aslms.services import calendar
from aslms.services import ownership as own
from aslms.services.workflow_common import today_ist
from tests.db import docs_support as ds
from tests.db import next_dates_support as h
from tests.db import workflow_support as w
from tests.db.report_support import override
from tests.db.world import make_case

TEXT = "List the matter after 2 (two) weeks."


@pytest.fixture()
def api(world, tmp_path):
    w.widen(world)
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


def d(n: int) -> date:
    return today_ist() + timedelta(days=n)


def _due(s, case, days: int, action=PendingAction.PARAWISE_COMMENTS):
    row = s.get(Custody, case.id)
    row.pending_action, row.due_date = action, d(days)


@pytest.fixture()
def dates(world, api):
    """EDU cases claimed by the EDU admin:
    - `a`: allotted to off1 (who holds its file), hearing in 3 days, action due in 5 days;
    - `p`: allotted to off1, an order read into a period shown directly (around);
    - `c`: a colleague's (off2), hearing in 3 days, action due in 5 days on off2's file;
    - `u`: HEALTH's case, hearing in 3 days (unseen by off1)."""
    with world.Session() as s:
        a = w.claimed_case(s, world, officer="edu_off1")
        a.next_hearing_date = d(3)
        _due(s, a, 5)
        p = w.claimed_case(s, world, officer="edu_off1")
        h.order_with_text(s, p, TEXT, order_date=d(-1))
        h.read(s)
        (row,) = h.rows(s, p)
        assert row.review_status == ReviewStatus.NOT_NEEDED
        c = w.claimed_case(s, world, officer="edu_off2")
        c.next_hearing_date = d(3)
        _due(s, c, 5)
        u = make_case(s, next_hearing=d(3))
        ha, health = world.actor(s, "health_admin")
        own.claim(s, ha, health, u)
        s.commit()
        return {
            "a": str(a.id),
            "p": str(p.id),
            "c": str(c.id),
            "u": str(u.id),
            "next_date_id": str(row.id),
            "proposed": row.next_date,
        }


def get(api, headers, query=""):
    r = api.get(f"/me/calendar?{query}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def rng(lo: date, hi: date) -> str:
    return f"from={lo}&to={hi}"


def test_the_kinds_for_an_officer(api, world, dates):
    off1 = w.login(api, "edu_off1")
    items = get(api, off1, rng(d(-1), d(40)))
    by_kind = {(i["kind"], i["case"]["id"]): i for i in items}
    hearing = by_kind[("hearing", dates["a"])]
    assert hearing["date"] == str(d(3)) and hearing["source"] == "current_status"
    assert hearing["this_week"] is True and hearing["critical"] is False
    due = by_kind[("action_due", dates["a"])]
    assert due["date"] == str(d(5)) and due["pending_action"] == "parawise_comments"
    assert due["pending_action_label"] and due["overdue"] is False and due["critical"] is False
    around = by_kind[("hearing", dates["p"])]
    assert around["date"] == str(dates["proposed"]) and around["source"] == "next_date"
    assert (
        around["basis"] == "around"
        and around["approximate"] is True
        and around["basis_words"] == "after 2 weeks"
    )
    assert hearing["basis"] == "court" and hearing["approximate"] is False
    assert set(by_kind) == {("hearing", dates["a"]), ("action_due", dates["a"]), ("hearing", dates["p"])}
    # the fields of the other kinds are null
    assert hearing["next_date_id"] is None and due["court_no"] is None and around["pending_action"] is None


def test_a_colleagues_case_and_an_unseen_case_are_absent(api, world, dates):
    off1 = w.login(api, "edu_off1")
    ids = {i["case"]["id"] for i in get(api, off1, rng(d(-1), d(40)))}
    assert dates["c"] not in ids and dates["u"] not in ids
    # the colleague sees their own
    off2 = {(i["kind"], i["case"]["id"]) for i in get(api, w.login(api, "edu_off2"), rng(d(-1), d(40)))}
    assert off2 == {("hearing", dates["c"]), ("action_due", dates["c"])}
    # another department's officer sees nothing of EDU's
    health = {i["case"]["id"] for i in get(api, w.login(api, "health_off"), rng(d(-1), d(40)))}
    assert not health & {dates["a"], dates["p"], dates["c"]}


def test_an_overdue_or_near_due_date_is_critical(api, world, dates):
    with world.Session() as s:
        _due(s, _case(s, dates["a"]), -2)
        s.commit()
    items = get(api, w.login(api, "edu_off1"), rng(d(-5), d(5)))
    (due,) = [i for i in items if i["kind"] == "action_due"]
    assert due["overdue"] is True and due["critical"] is True and due["date"] == str(d(-2))
    with world.Session() as s:
        _due(s, _case(s, dates["a"]), 0)
        s.commit()
    (due,) = [i for i in get(api, w.login(api, "edu_off1"), rng(d(-5), d(5))) if i["kind"] == "action_due"]
    assert due["overdue"] is False and due["critical"] is True
    # a file with no pending action has no due item
    with world.Session() as s:
        _due(s, _case(s, dates["a"]), 2, PendingAction.NONE)
        s.commit()
    assert not [i for i in get(api, w.login(api, "edu_off1"), rng(d(-5), d(5))) if i["kind"] == "action_due"]


def _case(s, case_id):
    return s.get(Case, case_id)


def test_no_confirm_items_without_next_dates_review(api, world, dates):
    with world.Session() as s:
        override(s, world, "edu_off1", Permission.NEXT_DATES_REVIEW, PermissionEffect.DENY)
        s.commit()
    kinds = {i["kind"] for i in get(api, w.login(api, "edu_off1"), rng(d(-1), d(40)))}
    assert kinds == {"hearing", "action_due"}


def test_range_limits(api, world, dates):
    off1 = w.login(api, "edu_off1")
    assert api.get(f"/me/calendar?{rng(d(0), d(63))}", headers=off1).status_code == 422
    assert api.get(f"/me/calendar?{rng(d(5), d(1))}", headers=off1).status_code == 422
    assert api.get(f"/me/calendar?{rng(d(0), d(62))}", headers=off1).status_code == 200
    assert api.get("/me/calendar?from=nope", headers=off1).status_code == 422
    assert api.get("/me/calendar").status_code == 401


def test_the_default_range_covers_the_month_grid(api, world, dates):
    lo, hi = calendar.month_grid(today_ist())
    assert (
        lo.weekday() == 0
        and hi.weekday() == 6
        and lo <= today_ist().replace(day=1)
        and hi.month
        in (
            today_ist().month,
            (today_ist().month % 12) + 1,
        )
    )
    with world.Session() as s:
        first = w.claimed_case(s, world, officer="edu_off1")
        first.next_hearing_date = lo
        last = w.claimed_case(s, world, officer="edu_off1")
        last.next_hearing_date = hi
        outside = w.claimed_case(s, world, officer="edu_off1")
        outside.next_hearing_date = hi + timedelta(days=1)
        s.commit()
        first_id, last_id, outside_id = str(first.id), str(last.id), str(outside.id)
    hearings = {i["case"]["id"] for i in get(api, w.login(api, "edu_off1")) if i["kind"] == "hearing"}
    assert {first_id, last_id} <= hearings and outside_id not in hearings


def test_month_grid_and_range_rules():
    assert calendar.month_grid(date(2026, 10, 20)) == (date(2026, 9, 28), date(2026, 11, 1))
    assert calendar.month_grid(date(2026, 2, 1)) == (date(2026, 1, 26), date(2026, 3, 1))
    today = date(2026, 10, 20)
    assert calendar.my_range(None, None, today) == (date(2026, 9, 28), date(2026, 11, 1))
    assert calendar.my_range(date(2026, 11, 3), None, today) == (date(2026, 11, 3), date(2026, 12, 6))
    assert calendar.my_range(None, date(2026, 11, 3), today) == (date(2026, 10, 26), date(2026, 11, 3))
    with pytest.raises(calendar.CalendarError):
        calendar.my_range(date(2026, 10, 1), date(2026, 12, 31), today)


def test_the_order_is_date_then_kind_then_case(api, world, dates):
    with world.Session() as s:
        # on the proposed date of `p`: a hearing of `a` and an action due on `a` too
        _case(s, dates["a"]).next_hearing_date = dates["proposed"]
        row = s.get(Custody, dates["a"])
        row.due_date = dates["proposed"]
        # an earlier hearing of `p` itself, from the court: it replaces the date counted from the order
        _case(s, dates["p"]).next_hearing_date = dates["proposed"] - timedelta(days=1)
        from aslms.services import next_hearing

        next_hearing.refresh(s, [_case(s, dates["p"]).id])
        s.commit()
    items = get(api, w.login(api, "edu_off1"), rng(d(-1), dates["proposed"] + timedelta(days=1)))
    assert [(i["date"], i["kind"]) for i in items] == [
        (str(dates["proposed"] - timedelta(days=1)), "hearing"),
        (str(dates["proposed"]), "hearing"),
        (str(dates["proposed"]), "action_due"),
    ]
    dates_only = [i["date"] for i in items]
    assert dates_only == sorted(dates_only)


def test_reading_writes_nothing(api, world, dates):
    def counts():
        with world.Session() as s:
            return (
                s.scalar(sa.select(sa.func.count()).select_from(AuditLog)),
                s.scalar(sa.select(sa.func.count()).select_from(Event)),
            )

    off1 = w.login(api, "edu_off1")
    before = counts()
    get(api, off1)
    get(api, off1, rng(d(-1), d(40)))
    assert counts() == before


def test_without_a_view_function_the_calendar_is_forbidden(api, world, dates):
    with world.Session() as s:
        override(s, world, "edu_off1", Permission.CASES_VIEW_SCOPE, PermissionEffect.DENY)
        override(s, world, "edu_off1", Permission.CASES_VIEW_ALL, PermissionEffect.DENY)
        s.commit()
    r = api.get(f"/me/calendar?{rng(d(-1), d(40))}", headers=w.login(api, "edu_off1"))
    assert r.status_code == 403


def test_a_merged_away_case_is_not_listed(api, world, dates):
    with world.Session() as s:
        keep = w.claimed_case(s, world, officer="edu_off1")
        _case(s, dates["a"]).merged_into_case_id = keep.id
        s.commit()
    ids = {i["case"]["id"] for i in get(api, w.login(api, "edu_off1"), rng(d(-1), d(40)))}
    assert dates["a"] not in ids
