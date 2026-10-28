"""Next dates entered by hand and the review alert (design `next-date-extraction`, decisions 10-15, as changed by
`next-date-direct`, decisions 2, 6 and 9): a person enters a date only where the court gave none (an unclear order, an
order with no next date, a scanned order); the function, visibility and working-basis rules, the claim, the `NXT`
ref on the acting office, events and audit rows without note text; the alert raised by the event scan for enter items
only and closed by the entry or expired by the sweep; confirm and reject refused for every reading."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from aslms.domain.alerts import AlertStatus, NextDate, NextDateSource, ReviewStatus, Severity
from aslms.domain.cases import CaseStatus
from aslms.domain.documents import TextStatus
from aslms.domain.events import AuditLog
from aslms.domain.org import PermissionEffect
from aslms.domain.reference import EventType, Permission
from aslms.services import alerts, case_detail, next_dates
from aslms.services.visibility import NotVisibleCase
from aslms.services.workflow_common import WorkflowError
from tests.db import alerts_support as ah
from tests.db import next_dates_support as h
from tests.db.report_support import override
from tests.db.world import make_case

NOTE = "the bench clerk said twelfth november; not to be audited"
UNCLEAR = "On the prayer of the parties, list the matter after the ensuing vacation."
NONE = "Issue notice. Steps within a week."


def _enter_item(s, world, *, text=UNCLEAR, order_date=None, **kw):
    case = h.claimed(s, world, **kw)
    order = h.order_with_text(s, case, text, order_date=order_date or h.days(-1))
    h.read(s)
    assert h.rows(s, case) == []
    return case, order


def _legacy_pending(s, case, on, order=None) -> NextDate:
    order = order or h.order_with_text(s, case, "x", order_date=h.days(-1))
    row = NextDate(
        case_id=case.id,
        next_date=on,
        source=NextDateSource.ORDER_PERIOD,
        order_id=order.id,
        needs_review=True,
        review_status=ReviewStatus.PENDING,
    )
    s.add(row)
    s.flush()
    return row


def _audits(s, action, case):
    return list(
        s.scalars(
            sa.select(AuditLog)
            .where(AuditLog.action == action, AuditLog.case_id == case.id)
            .order_by(AuditLog.id)
        ).all()
    )


def test_enter_where_the_court_gave_none(world):
    with world.Session() as s:
        case, order = _enter_item(s, world, unit_code="EDU-DSE")
        alerts.scan_events(s)
        (alert,) = h.review_alerts(s, case)
        assert alert.status == AlertStatus.OPEN and alert.data["next_date_id"] is None
        ah.recommend(s, world, case, "HEALTH")  # HEALTH reads the case as a recommended department
        actor, dse = world.actor(s, "dse_user")
        for bad in (h.days(-1), h.days(549)):
            with pytest.raises(WorkflowError) as e:
                next_dates.enter(s, actor, dse, case, next_date=bad)
            assert e.value.http_status == 400
        with pytest.raises(WorkflowError) as e:
            next_dates.enter(
                s, actor, dse, case, next_date=h.days(5), order_id=h.order_with_text(s, make_case(s), "x").id
            )
        assert (e.value.code, e.value.http_status) == ("bad_field", 400)
        nd = next_dates.enter(s, actor, dse, case, next_date=h.days(20), note=NOTE, order_id=order.id)
        year = h.days(0).year
        assert nd.ref_no == f"ASLMS/EDU-DSE/NXT/{year}/000001" and nd.note == NOTE
        (alert,) = h.review_alerts(s, case)
        assert alert.status == AlertStatus.DONE and alert.data["closed_reason"] == "entered"
        # the header reads it at once (decision 12)
        s.refresh(case)
        assert (case.next_hearing_on, case.next_hearing_basis.value, case.next_hearing_next_date_id) == (
            h.days(20),
            "manual",
            nd.id,
        )
        with pytest.raises(WorkflowError) as e:
            next_dates.enter(s, actor, dse, case, next_date=h.days(20), order_id=order.id)
        assert (e.value.code, e.value.http_status) == ("already_entered", 409)
        # a manual date is no court-given date: another holder may enter a different one (owner check J)
        actor, admin = world.actor(s, "edu_admin")
        nd2 = next_dates.enter(s, actor, admin, case, next_date=h.days(7))
        assert nd2.ref_no == f"ASLMS/EDU/NXT/{year}/000001"  # per office
        (audit, *_) = _audits(s, "next_date.enter", case)
        assert NOTE not in str(audit.after) and audit.after["note"]["length"] == len(NOTE)
        (ev, _) = h.events(s, case, EventType.NEXT_DATE_ENTERED)
        assert ev.payload["ref_no"] == nd.ref_no and "note" not in ev.payload
        # the timeline shows the entries to every reader of the case
        health = world.user(s, "health_admin")
        types = [i["type"] for i in case_detail.timeline(s, health, case).items]
        assert types.count("next_date_entered") == 2
        page = next_dates.case_next_dates(s, health, case)
        assert page.total == 2 and [i["effective"] for i in page.items] == [True, False]
        assert page.items[1]["note"] == NOTE
        with pytest.raises(NotVisibleCase):
            next_dates.case_next_dates(s, world.user(s, "health_off"), make_case(s))
        s.rollback()


def test_refusals(world):
    with world.Session() as s:
        case, _ = _enter_item(s, world)
        # a State reader with the function granted sees the case but does not work on it
        override(s, world, "oversight", Permission.NEXT_DATES_REVIEW, PermissionEffect.GRANT)
        actor, oversight = world.actor(s, "oversight")
        with pytest.raises(WorkflowError) as e:
            next_dates.enter(s, actor, oversight, case, next_date=h.days(9))
        assert (e.value.code, e.value.http_status) == ("not_working_on_case", 403)
        # another department's officer does not see the case
        actor, health = world.actor(s, "health_off")
        with pytest.raises(NotVisibleCase):
            next_dates.enter(s, actor, health, case, next_date=h.days(9))
        # without the function
        override(s, world, "edu_off1", Permission.NEXT_DATES_REVIEW, PermissionEffect.DENY)
        actor, off1 = world.actor(s, "edu_off1")
        with pytest.raises(WorkflowError) as e:
            next_dates.enter(s, actor, off1, case, next_date=h.days(9))
        assert (e.value.code, e.value.http_status) == ("forbidden", 403)
        # an unclaimed case (seen from the pool)
        pool = make_case(s)
        h.order_with_text(s, pool, UNCLEAR, order_date=h.days(-1))
        h.read(s)
        actor, admin = world.actor(s, "edu_admin")
        with pytest.raises(WorkflowError) as e:
            next_dates.enter(s, actor, admin, pool, next_date=h.days(9))
        assert (e.value.code, e.value.http_status) == ("not_owned", 409)
        # the refusals wrote nothing
        assert not s.scalar(
            sa.select(sa.func.count()).select_from(AuditLog).where(AuditLog.action.like("next_date.%"))
        )
        assert h.events(s, case, EventType.NEXT_DATE_ENTERED) == []
        s.rollback()


def test_visibility_comes_before_field_checks(world):
    """Review advisory: a caller who cannot see the case gets 404, never a field error (400) that would confirm the
    case or the order exists."""
    with world.Session() as s:
        case, _ = _enter_item(s, world)
        row = _legacy_pending(s, case, h.days(9))
        actor, health = world.actor(s, "health_off")
        with pytest.raises(NotVisibleCase):
            next_dates.reject(s, actor, health, row.id, replacement=h.days(-1))
        with pytest.raises(NotVisibleCase):
            next_dates.reject(s, actor, health, row.id, note="x" * 301)
        with pytest.raises(NotVisibleCase):
            next_dates.enter(s, actor, health, case, next_date=h.days(-1))
        with pytest.raises(NotVisibleCase):
            next_dates.enter(
                s,
                actor,
                health,
                case,
                next_date=h.days(5),
                order_id=h.order_with_text(s, make_case(s), "x").id,
            )
        # a reader who sees the case gets the field error
        actor, admin = world.actor(s, "edu_admin")
        with pytest.raises(WorkflowError) as e:
            next_dates.enter(s, actor, admin, case, next_date=h.days(-1))
        assert e.value.http_status == 400
        s.rollback()


def test_confirm_and_reject_of_a_reading_are_refused(world):
    """Decision 6: a reading of an order is a court-given date; nobody confirms, rejects or replaces it."""
    with world.Session() as s:
        case = h.claimed(s, world)
        row = _legacy_pending(s, case, h.days(12))
        actor, admin = world.actor(s, "edu_admin")
        for call in (
            lambda: next_dates.confirm(s, actor, admin, row.id),
            lambda: next_dates.reject(s, actor, admin, row.id),
            lambda: next_dates.reject(s, actor, admin, row.id, note=NOTE, replacement=h.days(26)),
            lambda: next_dates.enter(s, actor, admin, case, next_date=h.days(26)),
        ):
            with pytest.raises(WorkflowError) as e:
                call()
            assert (e.value.code, e.value.http_status) == ("court_date_fixed", 409)
        assert h.refreshed(s, row).review_status == ReviewStatus.PENDING
        assert not s.scalar(
            sa.select(sa.func.count()).select_from(AuditLog).where(AuditLog.action.like("next_date.%"))
        )
        # the ref form of {id} is the uuid for read rows (they have no ref_no)
        assert next_dates.resolve_next_date(s, str(row.id)).id == row.id
        with pytest.raises(next_dates.NextDateNotFound):
            next_dates.resolve_next_date(s, "ASLMS-EDU-NXT-2026-999999")
        s.rollback()


def test_the_review_alert(world):
    with world.Session() as s:
        vacation, vac_order = _enter_item(s, world)
        none_case, _ = _enter_item(s, world, text=NONE)
        scanned = h.claimed(s, world)
        h.order_with_text(s, scanned, None, order_date=h.days(-1), text_status=TextStatus.NONE)
        old_case, _ = _enter_item(s, world, order_date=h.days(-20))
        listed = h.claimed(s, world, next_hearing=h.days(9))  # the court's record gives a date
        h.order_with_text(s, listed, NONE, order_date=h.days(-1))
        disposed = h.claimed(s, world)
        disposed.status = CaseStatus.DISPOSED
        h.order_with_text(s, disposed, "The writ petition is disposed of.", order_date=h.days(-1))
        unclaimed = make_case(s)
        h.order_with_text(s, unclaimed, NONE, order_date=h.days(-1))
        dated = h.claimed(s, world)
        h.order_with_text(s, dated, "List the matter after 3 weeks.", order_date=h.days(-1))
        h.read(s)
        c = alerts.scan_events(s)
        assert c["alerts_new"] == 3, c
        (vac,) = h.review_alerts(s, vacation)
        assert vac.severity == Severity.NORMAL and vac.dedupe_key == f"next_date_review:{vac_order.id}"
        assert vac.title.startswith("Enter the next date") and "gives no next date" in vac.body
        assert len(h.review_alerts(s, none_case)) == 1 and len(h.review_alerts(s, scanned)) == 1
        for case in (old_case, listed, disposed, unclaimed, dated):
            assert h.review_alerts(s, case) == []
        assert alerts.scan_events(s)["alerts_new"] == 0  # a re-scan raises nothing new
        # the sweep expires an alert whose order has no item left (a date was entered elsewhere)
        actor, admin = world.actor(s, "edu_admin")
        s.add(
            NextDate(
                ref_no=f"T/NXT/{uuid.uuid4().hex[:10]}",
                case_id=vacation.id,
                next_date=h.days(30),
                source=NextDateSource.MANUAL,
                order_id=vac_order.id,
            )
        )
        s.flush()
        c = alerts.sweep_dates(s, now=datetime.now(UTC))
        assert c["closed_next_date"] == 1
        s.refresh(vac)
        assert vac.status == AlertStatus.EXPIRED and vac.data["closed_reason"] == "no_review_item"
        del actor, admin
        s.rollback()


def test_queue_and_counts(world):
    with world.Session() as s:
        from aslms.services import dashboard

        case, order = _enter_item(s, world)
        unit_case, unit_order = _enter_item(s, world, text=NONE, unit_code="EDU-DSE")
        scanned = h.claimed(s, world)
        scan_order = h.order_with_text(s, scanned, None, order_date=h.days(-2), text_status=TextStatus.NONE)
        dated = h.claimed(s, world)
        h.order_with_text(s, dated, "List the matter after 3 weeks.", order_date=h.days(-1))
        h.read(s)
        actor, admin = world.actor(s, "edu_admin")
        page = next_dates.review_items(s, admin)
        assert page.total == 3
        assert {i["kind"] for i in page.items} == {"enter"}
        assert {(i["id"], i["reason"]) for i in page.items} == {
            (order.id, "unclear"),
            (unit_order.id, "none"),
            (scan_order.id, "no_text"),
        }
        assert page.items[0]["id"] == scan_order.id  # by act_by: the oldest order first
        assert next_dates.review_items(s, admin, kind="confirm").total == 0  # decision 9: no confirm item
        assert next_dates.review_items(s, admin, kind="enter").total == 3
        assert next_dates.review_items(s, admin, limit=1, offset=1).total == 3
        with pytest.raises(WorkflowError):
            next_dates.review_items(s, admin, kind="other")
        dse = world.user(s, "dse_user")
        assert [i["id"] for i in next_dates.review_items(s, dse).items] == [unit_order.id]
        assert next_dates.review_items(s, dse).items[0]["departments"] == ["EDU"]
        # the dashboard counts the department's items; the overview the caller's for the case
        edu = world.office(s, "EDU")
        att = dashboard.department_block(s, admin, edu)["attention"]
        assert att["next_dates_to_review"] == 3
        assert {i["case"]["id"] for i in att["recent_order_next_dates"]} == {dated.id}
        next_dates.enter(s, actor, admin, case, next_date=h.days(15), order_id=order.id)
        att = dashboard.department_block(s, admin, edu)["attention"]
        assert att["next_dates_to_review"] == 2
        assert case_detail.overview(s, dse, unit_case)["next_dates_to_review"] == 1
        over = case_detail.overview(s, admin, case)
        assert over["next_dates_to_review"] == 0
        assert over["next_date_from_orders"]["source"] == "manual"
        assert over["next_hearing"]["basis"] == "manual" and over["next_hearing"]["date"] == h.days(15)
        over = case_detail.overview(s, admin, dated)
        assert over["next_date_from_orders"]["order"]["rule"] == "list_after_period"
        assert over["next_hearing"]["basis"] == "around" and over["next_hearing"]["approximate"] is True
        assert over["next_hearing"]["basis_words"] == "after 3 weeks"
        (item,) = case_detail.orders(s, admin, case).items
        assert item["next_date_status"] == "unclear" and item["next_date_rule"] == "no_countable_date"
        s.rollback()


def test_times_are_ist_days(world):
    with world.Session() as s:
        assert next_dates.today_ist(datetime(2026, 10, 16, 19, 0, tzinfo=UTC)) == (
            datetime(2026, 10, 17).date()
        )
        assert (
            next_dates.today_ist(datetime(2026, 10, 16, 18, 0, tzinfo=UTC)) == datetime(2026, 10, 16).date()
        )
        assert timedelta(days=548) == timedelta(days=next_dates.NextDateConfig.from_settings().max_ahead_days)
        s.rollback()
