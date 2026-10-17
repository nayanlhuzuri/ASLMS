"""Firm only when two sources agree (design `next-date-extraction`, the owner's second decision of 17 Oct 2026,
option B): a date read from an order is `not_needed` only when it equals the court's own date for the case
(`cases.next_hearing_date` or a cause-list listing); otherwise it is a suggestion to confirm. A suggestion becomes
firm by itself when a matching court date arrives later (Current Status, the dossier, a cause list, or the next
reader run), and its review alert is closed `done`, reason `matched`. Confirm refuses a date already passed."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa

from aslms.domain.alerts import AlertStatus, NextDate, NextDateSource, ReviewStatus
from aslms.domain.causelists import Causelist, CauselistEntry, EntrySource, ListSource, ListType
from aslms.domain.courts import Court
from aslms.domain.ops import SourceFailure
from aslms.services import alerts, calendar, cases, next_dates
from aslms.services.workflow_common import WorkflowError
from tests.db import next_dates_support as h
from tests.db.conftest import sample
from tests.db.test_matching import entry, load_list
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


def test_a_written_date_without_the_courts_date_waits_for_confirmation(world):
    with world.Session() as s:
        _, admin = world.actor(s, "edu_admin")
        alone = h.claimed(s, world)
        order = h.order_with_text(
            s, alone, f"List this matter on {h.dmy(h.days(10))}.", order_date=h.days(-1)
        )
        other = h.claimed(s, world, next_hearing=h.days(11))  # the court gives another date
        h.order_with_text(s, other, f"List this matter on {h.dmy(h.days(10))}.", order_date=h.days(-1))
        c = h.read(s)
        assert c["specific"] == 2 and c["rows_written"] == 2 and c["review_items"] == 2
        for case in (alone, other):
            (row,) = h.rows(s, case)
            assert (row.source, row.review_status, row.needs_review, float(row.confidence)) == (
                NextDateSource.ORDER_SPECIFIC,
                ReviewStatus.PENDING,
                True,
                1.0,
            )
            assert _calendar_dates(s, case) == []
        (ev,) = h.events(s, alone)
        assert ev.payload["review"] is True and ev.payload["rule"] == "list_on_date"
        s.refresh(order)
        assert order.next_date_rule == "list_on_date" and order.next_date_found == h.days(10)
        items = [i for i in next_dates.review_items(s, admin).items if i["case"]["id"] == alone.id]
        assert [(i["kind"], i["next_date"]) for i in items] == [("confirm", h.days(10))]
        s.rollback()


@pytest.mark.parametrize(
    ("text", "court"),
    [
        ("List this matter on {d}.", "status"),
        ("List this matter on {d}.", "causelist"),
        ("List the matter after {d}.", "status"),  # a not-before date the court then gives
        ("List this matter after four weeks.", "status"),  # a period counted to the court's date
    ],
)
def test_any_reading_equal_to_the_courts_date_is_firm_at_once(world, text, court):
    with world.Session() as s:
        order_date = h.days(-1)
        on = order_date + timedelta(weeks=4)
        case = h.claimed(s, world, next_hearing=on if court == "status" else None)
        if court == "causelist":
            _listed(s, case, on)
        h.order_with_text(s, case, text.format(d=h.dmy(on)), order_date=order_date)
        c = h.read(s)
        assert c["rows_written"] == 1 and c["review_items"] == 0
        (row,) = h.rows(s, case)
        assert (row.review_status, row.needs_review, row.next_date) == (ReviewStatus.NOT_NEEDED, False, on)
        (ev,) = h.events(s, case)
        assert ev.payload["review"] is False
        # the calendar shows the date once (from the cause list when the case is listed: it ranks first)
        assert _calendar_dates(s, case, None) == [on]
        assert next_dates.effective_for_case(s, case).id == row.id
        s.rollback()


def test_current_status_makes_a_suggestion_firm_and_closes_its_alert(world):
    with world.Session() as s:
        _, admin = world.actor(s, "edu_admin")
        case = h.claimed(s, world)
        h.order_with_text(s, case, f"List this matter on {h.dmy(h.days(6))}.", order_date=h.days(-1))
        h.read(s)
        alerts.scan_events(s)
        (alert,) = h.review_alerts(s, case)
        assert alert.status == AlertStatus.OPEN
        (row,) = h.rows(s, case)
        # another date from the court changes nothing
        cases.apply_status(s, case, _status_block(case, h.days(7)))
        assert h.refreshed(s, row).review_status == ReviewStatus.PENDING
        # the court's date agrees: firm, no person needed
        rep = cases.apply_status(s, case, _status_block(case, h.days(6)))
        assert "next_hearing_date" in rep.status_changes
        row = h.refreshed(s, row)
        assert (row.review_status, row.needs_review, row.reviewed_by_user_id, row.reviewed_at) == (
            ReviewStatus.NOT_NEEDED,
            True,
            None,
            None,
        )
        (alert,) = h.review_alerts(s, case)
        assert alert.status == AlertStatus.DONE and alert.data["closed_reason"] == "matched"
        assert next_dates.review_items(s, admin).total == 0
        assert _calendar_dates(s, case) == [h.days(6)]
        assert next_dates.effective_for_case(s, case).id == row.id
        actor, admin = world.actor(s, "edu_admin")
        with pytest.raises(WorkflowError) as exc:
            next_dates.confirm(s, actor, admin, row.id)
        assert exc.value.code == "not_pending"
        s.rollback()


def test_the_dossier_makes_a_suggestion_firm(world):
    with world.Session() as s:
        case = make_case(s, cnr="GAHC010129772026", case_no="WP(C)/3600/2026")
        h.order_with_text(s, case, "List the matter after 3 (three weeks).", order_date=h.days(-2))
        h.read(s)
        (row,) = h.rows(s, case)
        assert (row.source, row.review_status) == (NextDateSource.ORDER_PERIOD, ReviewStatus.PENDING)
        assert row.next_date == h.days(19)
        data = {**sample("cnr_pending.json"), "date_next_list": h.days(19).isoformat()}
        cases.apply_dossier(s, case, data)
        assert h.refreshed(s, row).review_status == ReviewStatus.NOT_NEEDED
        s.rollback()


def test_a_cause_list_listing_makes_a_suggestion_firm(world):
    with world.Session() as s:
        case = h.claimed(s, world)
        h.order_with_text(s, case, f"List the matter on {h.dmy(h.days(8))}.", order_date=h.days(-1))
        h.read(s)
        alerts.scan_events(s)
        (row,) = h.rows(s, case)
        # a list of another day changes nothing
        load_list(s, [entry(1, case.cnr, case.case_no_text)], list_date=h.days(9))
        assert h.refreshed(s, row).review_status == ReviewStatus.PENDING
        load_list(s, [entry(1, case.cnr, case.case_no_text)], list_date=h.days(8))
        assert h.refreshed(s, row).review_status == ReviewStatus.NOT_NEEDED
        (alert,) = h.review_alerts(s, case)
        assert alert.status == AlertStatus.DONE and alert.data["closed_reason"] == "matched"
        s.rollback()


def test_the_reader_run_matches_and_the_sweep_closes_a_matched_alert_done(world):
    with world.Session() as s:
        case = h.claimed(s, world)
        h.order_with_text(s, case, f"List the matter on {h.dmy(h.days(5))}.", order_date=h.days(-1))
        h.read(s)
        alerts.scan_events(s)
        (row,) = h.rows(s, case)
        _listed(s, case, h.days(5))  # no hook: the next reader run matches it
        c = h.read(s)
        assert c["matched"] == 1 and c["claimed"] == 0
        assert h.refreshed(s, row).review_status == ReviewStatus.NOT_NEEDED
        (alert,) = h.review_alerts(s, case)
        assert alert.status == AlertStatus.DONE and alert.data["closed_reason"] == "matched"
        assert h.read(s)["matched"] == 0  # once
        # a match whose alert was left open (written directly here) is closed done by the hourly sweep
        other = h.claimed(s, world)
        h.order_with_text(s, other, f"List the matter on {h.dmy(h.days(4))}.", order_date=h.days(-1))
        h.read(s)
        alerts.scan_events(s)
        (row2,) = h.rows(s, other)
        s.execute(
            sa.update(NextDate).where(NextDate.id == row2.id).values(review_status=ReviewStatus.NOT_NEEDED)
        )
        alerts.sweep_dates(s, now=datetime.now(UTC))
        (alert2,) = h.review_alerts(s, other)
        assert alert2.status == AlertStatus.DONE and alert2.data["closed_reason"] == "matched"
        s.rollback()


def test_a_past_suggestion_is_not_matched(world):
    with world.Session() as s:
        case = h.claimed(s, world, next_hearing=h.days(-1))
        order = h.order_with_text(s, case, "x", order_date=h.days(-5))
        stale = NextDate(
            case_id=case.id,
            next_date=h.days(-1),
            source=NextDateSource.ORDER_SPECIFIC,
            order_id=order.id,
            needs_review=True,
            review_status=ReviewStatus.PENDING,
        )
        s.add(stale)
        s.flush()
        assert next_dates.match_court_dates(s, case_ids=[case.id]) == 0
        assert h.refreshed(s, stale).review_status == ReviewStatus.PENDING
        s.rollback()


def test_a_match_failure_never_fails_the_court_data(world, monkeypatch):
    with world.Session() as s:
        case = h.claimed(s, world)
        h.order_with_text(s, case, f"List the matter on {h.dmy(h.days(6))}.", order_date=h.days(-1))
        h.read(s)
        (row,) = h.rows(s, case)

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


def test_confirm_refuses_a_date_already_passed(world):
    with world.Session() as s:
        case = h.claimed(s, world)
        order = h.order_with_text(s, case, "x", order_date=h.days(-5))
        stale = NextDate(
            case_id=case.id,
            next_date=h.days(-1),
            source=NextDateSource.ORDER_PERIOD,
            order_id=order.id,
            needs_review=True,
            review_status=ReviewStatus.PENDING,
        )
        s.add(stale)
        s.flush()
        actor, admin = world.actor(s, "edu_admin")
        with pytest.raises(WorkflowError) as exc:
            next_dates.confirm(s, actor, admin, stale.id)
        assert (exc.value.code, exc.value.http_status) == ("date_passed", 409)
        assert h.refreshed(s, stale).review_status == ReviewStatus.PENDING
        # reject is still allowed (a person may say the reading was wrong)
        rejected, _ = next_dates.reject(s, actor, admin, stale.id)
        assert rejected.review_status == ReviewStatus.REJECTED
        s.rollback()


def test_another_cases_listing_on_the_same_day_does_not_match(world):
    with world.Session() as s:
        case = h.claimed(s, world)
        other = make_case(s)
        h.order_with_text(s, case, f"List the matter on {h.dmy(h.days(8))}.", order_date=h.days(-1))
        h.read(s)
        (row,) = h.rows(s, case)
        _listed(s, other, h.days(8))
        s.flush()
        h.read(s)
        assert h.refreshed(s, row).review_status == ReviewStatus.PENDING
        s.rollback()
