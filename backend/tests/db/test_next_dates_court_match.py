"""Shown directly (design `next-date-direct`, decisions 1 to 3, superseding the owner's option B of 17 Oct 2026): a date
read from the latest order is `not_needed` at once, whatever the court's record says, and becomes the case's next
hearing unless the court's record gives a later date. `pending` rows written before migration 0034 are still matched
by a court date that agrees (`match_court_dates`, kept for those rows) until `aslms next-dates direct --apply` retires
them; a match failure never fails the court data."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
import sqlalchemy as sa

from aslms.domain.alerts import AlertStatus, NextDate, NextDateSource, ReviewStatus
from aslms.domain.causelists import Causelist, CauselistEntry, EntrySource, ListSource, ListType
from aslms.domain.courts import Court
from aslms.domain.ops import SourceFailure
from aslms.services import alerts, calendar, cases, next_dates, next_hearing
from aslms.services.workflow_common import WorkflowError
from tests.db import next_dates_support as h
from tests.db.conftest import sample
from tests.db.world import make_case


def _calendar_dates(s, case, source: str | None = "next_date") -> list[date]:
    return [
        r.date
        for r in calendar.hearing_rows(
            s, from_=h.days(0), to=h.days(120), case_condition=calendar.owned_case_condition()
        )
        if r.case_id == case.id and (source is None or r.source == source)
    ]


def _listed(s, case, on: date) -> None:
    """A cause-list entry of `case` on a list of `on`, written directly (no hook runs)."""
    court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
    cl = Causelist(court_id=court.id, list_date=on, list_type=ListType.DAILY, source=ListSource.GHC_WEBSITE)
    s.add(cl)
    s.flush()
    s.add(
        CauselistEntry(
            causelist_id=cl.id, sr_no=1, case_id=case.id, cnr=case.cnr, source=EntrySource.PDF_PARSE
        )
    )
    s.flush()


def _status_block(case, on: date) -> dict:
    return {
        **sample("current_status_pending.json")["cases1"],
        "cino": case.cnr,
        "date_next_list": on.isoformat(),
    }


def _pending(s, case, on: date, *, order=None, source=NextDateSource.ORDER_SPECIFIC) -> NextDate:
    """A suggestion written as before migration 0034 (pending, needs review)."""
    order = order or h.order_with_text(s, case, "x", order_date=h.days(-1))
    row = NextDate(
        case_id=case.id,
        next_date=on,
        source=source,
        order_id=order.id,
        needs_review=True,
        review_status=ReviewStatus.PENDING,
    )
    s.add(row)
    s.flush()
    return row


def test_a_written_date_is_shown_directly_whatever_the_court_says(world):
    with world.Session() as s:
        _, admin = world.actor(s, "edu_admin")
        alone = h.claimed(s, world)
        order = h.order_with_text(
            s, alone, f"List this matter on {h.dmy(h.days(10))}.", order_date=h.days(-1)
        )
        other = h.claimed(s, world, next_hearing=h.days(11))  # the court gives another date
        h.order_with_text(s, other, f"List this matter on {h.dmy(h.days(10))}.", order_date=h.days(-1))
        c = h.read(s)
        assert c["specific"] == 2 and c["rows_written"] == 2 and c["review_items"] == 0
        for case in (alone, other):
            (row,) = h.rows(s, case)
            assert (row.source, row.review_status, row.needs_review, float(row.confidence)) == (
                NextDateSource.ORDER_SPECIFIC,
                ReviewStatus.NOT_NEEDED,
                False,
                1.0,
            )
        (ev,) = h.events(s, alone)
        assert ev.payload["review"] is False and ev.payload["rule"] == "list_on_date"
        s.refresh(order)
        assert order.next_date_rule == "list_on_date" and order.next_date_found == h.days(10)
        s.refresh(alone)
        s.refresh(other)
        assert (alone.next_hearing_on, alone.next_hearing_basis.value) == (h.days(10), "order")
        assert _calendar_dates(s, alone) == [h.days(10)]
        # the court's record wins and the difference is flagged
        assert (other.next_hearing_on, other.next_hearing_basis.value) == (h.days(11), "court")
        assert other.next_hearing_differs_on == h.days(10)
        assert _calendar_dates(s, other, None) == [h.days(11)]
        assert next_dates.review_items(s, admin).total == 0
        s.rollback()


def test_a_legacy_pending_row_is_still_matched_by_the_courts_date(world):
    with world.Session() as s:
        case = h.claimed(s, world)
        row = _pending(s, case, h.days(6))
        cases.apply_status(s, case, _status_block(case, h.days(7)))  # another date: nothing matched
        assert h.refreshed(s, row).review_status == ReviewStatus.PENDING
        rep = cases.apply_status(s, case, _status_block(case, h.days(6)))
        assert "next_hearing_date" in rep.status_changes
        row = h.refreshed(s, row)
        assert (row.review_status, row.needs_review, row.reviewed_by_user_id) == (
            ReviewStatus.NOT_NEEDED,
            True,
            None,
        )
        s.refresh(case)
        assert (case.next_hearing_on, case.next_hearing_basis.value) == (h.days(6), "court")
        s.rollback()


def test_a_legacy_pending_row_is_matched_by_a_listing_and_the_reader_run(world):
    with world.Session() as s:
        case = h.claimed(s, world)
        row = _pending(s, case, h.days(5))
        _listed(s, case, h.days(5))  # no hook: the next reader run matches it
        c = h.read(s)
        assert c["matched"] == 1
        assert h.refreshed(s, row).review_status == ReviewStatus.NOT_NEEDED
        assert h.read(s)["matched"] == 0  # once
        s.rollback()


def test_a_past_suggestion_is_not_matched(world):
    with world.Session() as s:
        case = h.claimed(s, world, next_hearing=h.days(-1))
        order = h.order_with_text(s, case, "x", order_date=h.days(-5))
        stale = _pending(s, case, h.days(-1), order=order)
        assert next_dates.match_court_dates(s, case_ids=[case.id]) == 0
        assert h.refreshed(s, stale).review_status == ReviewStatus.PENDING
        s.rollback()


def test_a_match_failure_never_fails_the_court_data(world, monkeypatch):
    with world.Session() as s:
        case = h.claimed(s, world)
        row = _pending(s, case, h.days(6))

        def boom(*a, **kw):
            raise RuntimeError("match broke")

        monkeypatch.setattr(next_dates, "match_court_dates", boom)
        cases.apply_status(s, case, _status_block(case, h.days(6)))
        assert case.next_hearing_date == h.days(6)  # the court data stays
        fail = s.scalar(sa.select(SourceFailure).where(SourceFailure.kind == "next_date_match"))
        assert fail.ref == str(case.id) and "match broke" in fail.error
        assert h.refreshed(s, row).review_status == ReviewStatus.PENDING
        monkeypatch.undo()
        assert h.read(s)["matched"] == 1  # the next reader run makes up for it
        s.rollback()


def test_a_passed_reading_of_the_latest_order_is_an_ultimatum(world):
    """Owner, 28 Oct 2026: a court date that has passed stays the value (Date Passed); nothing is confirmed, rejected
    or entered over it."""
    with world.Session() as s:
        case = h.claimed(s, world)
        order = h.order_with_text(s, case, "x", order_date=h.days(-5))
        stale = _pending(s, case, h.days(-1), order=order, source=NextDateSource.ORDER_PERIOD)
        value = next_hearing.compute(s, [case.id])[case.id]
        assert (value.date, value.basis.value) == (h.days(-1), "around")
        actor, admin = world.actor(s, "edu_admin")
        for call in (
            lambda: next_dates.confirm(s, actor, admin, stale.id),
            lambda: next_dates.reject(s, actor, admin, stale.id),
            lambda: next_dates.enter(s, actor, admin, case, next_date=h.days(3)),
        ):
            with pytest.raises(WorkflowError) as exc:
                call()
            assert (exc.value.code, exc.value.http_status) == ("court_date_fixed", 409)
        assert h.refreshed(s, stale).review_status == ReviewStatus.PENDING
        s.rollback()


def test_another_cases_listing_on_the_same_day_does_not_match(world):
    with world.Session() as s:
        case = h.claimed(s, world)
        other = make_case(s)
        row = _pending(s, case, h.days(8))
        _listed(s, other, h.days(8))
        h.read(s)
        assert h.refreshed(s, row).review_status == ReviewStatus.PENDING
        s.rollback()


def test_the_sweep_closes_a_review_alert_without_an_item(world):
    with world.Session() as s:
        case = h.claimed(s, world)
        h.order_with_text(s, case, "Notice issued. Steps within a week.", order_date=h.days(-1))
        h.read(s)
        alerts.scan_events(s)
        (alert,) = h.review_alerts(s, case)  # an order that gives no next date: Next Dates to Enter
        assert alert.status == AlertStatus.OPEN
        assert "gives no next date" in alert.body
        cases.apply_status(s, case, _status_block(case, h.days(9)))  # the court gives a date: no item left
        alerts.sweep_dates(s, now=datetime.now(UTC))
        (alert,) = h.review_alerts(s, case)
        assert alert.status == AlertStatus.EXPIRED and alert.data["closed_reason"] == "no_review_item"
        s.rollback()
