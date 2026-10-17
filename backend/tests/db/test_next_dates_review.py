"""Confirm, reject and manual next dates (design `next-date-extraction`, decisions 10-15) and the review alert
(decision 13): the function, visibility and working-basis rules, the claim, `not_pending`, the `NXT` ref on the
acting office, supersession, events and audit rows without note text, the alert raised by the event scan and
closed by the review or expired by the sweep."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from aslms.domain.alerts import AlertStatus, ReviewStatus, Severity
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

NOTE = "the order says twelfth november; not to be audited"


def _pending(s, world, *, text="List the matter after 2 (two) weeks.", order_date=None, **kw):
    case = h.claimed(s, world, **kw)
    order = h.order_with_text(s, case, text, order_date=order_date or h.days(-1))
    h.read(s)
    (row,) = h.rows(s, case)
    assert row.review_status == ReviewStatus.PENDING
    return case, order, row


def _audits(s, action, case):
    return list(
        s.scalars(
            sa.select(AuditLog)
            .where(AuditLog.action == action, AuditLog.case_id == case.id)
            .order_by(AuditLog.id)
        ).all()
    )


def test_confirm(world):
    with world.Session() as s:
        case, order, row = _pending(s, world)
        alerts.scan_events(s)
        (alert,) = h.review_alerts(s, case)
        assert alert.data["order_id"] == str(order.id) and alert.data["next_date_id"] == str(row.id)
        actor, admin = world.actor(s, "edu_admin")
        out = next_dates.confirm(s, actor, admin, row.id)
        assert out.review_status == ReviewStatus.CONFIRMED and out.reviewed_by_user_id == admin.id
        assert out.reviewed_at is not None and out.updated_by == admin.id
        (ev,) = h.events(s, case, EventType.NEXT_DATE_REVIEWED)
        assert ev.payload == {
            "next_date_id": str(row.id),
            "action": "confirm",
            "next_date": str(row.next_date),
            "office_code": "EDU",
        }
        (audit,) = _audits(s, "next_date.confirm", case)
        assert audit.before["review_status"] == "pending" and audit.after["review_status"] == "confirmed"
        assert audit.entity_type == "next_date" and audit.entity_id == row.id
        (alert,) = h.review_alerts(s, case)
        assert alert.status == AlertStatus.DONE and alert.data["closed_reason"] == "confirmed"
        with pytest.raises(WorkflowError) as e:
            next_dates.confirm(s, actor, admin, row.id)
        assert (e.value.code, e.value.http_status) == ("not_pending", 409)
        # the ref form of {id} is the uuid for read rows (they have no ref_no)
        assert next_dates.resolve_next_date(s, str(row.id)).id == row.id
        with pytest.raises(next_dates.NextDateNotFound):
            next_dates.resolve_next_date(s, "ASLMS-EDU-NXT-2026-999999")
        s.rollback()


def test_refusals(world):
    with world.Session() as s:
        case, _, row = _pending(s, world)
        # a State reader with the function granted sees the case but does not work on it
        override(s, world, "oversight", Permission.NEXT_DATES_REVIEW, PermissionEffect.GRANT)
        actor, oversight = world.actor(s, "oversight")
        with pytest.raises(WorkflowError) as e:
            next_dates.confirm(s, actor, oversight, row.id)
        assert (e.value.code, e.value.http_status) == ("not_working_on_case", 403)
        # another department's officer does not see the case
        actor, health = world.actor(s, "health_off")
        with pytest.raises(NotVisibleCase):
            next_dates.confirm(s, actor, health, row.id)
        # without the function
        override(s, world, "edu_off1", Permission.NEXT_DATES_REVIEW, PermissionEffect.DENY)
        actor, off1 = world.actor(s, "edu_off1")
        with pytest.raises(WorkflowError) as e:
            next_dates.reject(s, actor, off1, row.id)
        assert (e.value.code, e.value.http_status) == ("forbidden", 403)
        # an unclaimed case (seen from the pool)
        pool = make_case(s)
        h.order_with_text(s, pool, "List after 3 weeks.", order_date=h.days(-1))
        h.read(s)
        (prow,) = h.rows(s, pool)
        actor, admin = world.actor(s, "edu_admin")
        with pytest.raises(WorkflowError) as e:
            next_dates.confirm(s, actor, admin, prow.id)
        assert (e.value.code, e.value.http_status) == ("not_owned", 409)
        with pytest.raises(WorkflowError) as e:
            next_dates.enter(s, actor, admin, pool, next_date=h.days(9))
        assert e.value.code == "not_owned"
        # the refusals wrote nothing
        assert not s.scalar(
            sa.select(sa.func.count()).select_from(AuditLog).where(AuditLog.action.like("next_date.%"))
        )
        s.refresh(row)
        assert (
            row.review_status == ReviewStatus.PENDING
            and h.events(s, case, EventType.NEXT_DATE_REVIEWED) == []
        )
        s.rollback()


def test_visibility_comes_before_field_checks(world):
    """Review advisory: a caller who cannot see the case gets 404, never a field error (400) that would confirm the
    case or the order exists."""
    with world.Session() as s:
        case, order, row = _pending(s, world)
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


def test_reject_with_a_replacement_date(world):
    with world.Session() as s:
        case, order, row = _pending(s, world)
        other_case, _, other_row = _pending(s, world)
        actor, admin = world.actor(s, "edu_admin")
        with pytest.raises(WorkflowError) as e:
            next_dates.reject(s, actor, admin, row.id, replacement=h.days(-1))
        assert e.value.http_status == 400
        with pytest.raises(WorkflowError):
            next_dates.reject(s, actor, admin, row.id, note="x" * 301)
        rejected, entered = next_dates.reject(s, actor, admin, row.id, note=NOTE, replacement=h.days(26))
        assert rejected.review_status == ReviewStatus.REJECTED and rejected.note == NOTE
        assert rejected.reviewed_at is not None
        year = h.days(0).year
        assert entered.ref_no == f"ASLMS/EDU/NXT/{year}/000001"
        assert (entered.source.value, entered.review_status, entered.order_id, entered.next_date) == (
            "manual",
            ReviewStatus.NOT_NEEDED,
            order.id,
            h.days(26),
        )
        assert entered.created_by == admin.id and float(entered.confidence) == 1.0
        s.refresh(other_row)
        assert other_row.review_status == ReviewStatus.PENDING  # another case is untouched
        reject_audit, enter_audit = _audits(s, "next_date.reject", case) + _audits(s, "next_date.enter", case)
        assert NOTE not in str(reject_audit.after) and reject_audit.after["note"]["length"] == len(NOTE)
        assert enter_audit.after["ref_no"] == entered.ref_no
        assert {e.payload["action"] for e in h.events(s, case, EventType.NEXT_DATE_REVIEWED)} == {"reject"}
        (ev,) = h.events(s, case, EventType.NEXT_DATE_ENTERED)
        assert ev.payload["ref_no"] == entered.ref_no and "note" not in ev.payload
        assert next_dates.effective_for_case(s, case).id == entered.id
        s.rollback()


def test_enter(world):
    with world.Session() as s:
        case, order, row = _pending(s, world, unit_code="EDU-DSE")
        alerts.scan_events(s)
        assert len(h.review_alerts(s, case)) == 1
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
        nd = next_dates.enter(
            s, actor, dse, case, next_date=h.days(548), note="as told by counsel", order_id=order.id
        )
        year = h.days(0).year
        assert nd.ref_no == f"ASLMS/EDU-DSE/NXT/{year}/000001" and nd.note == "as told by counsel"
        s.refresh(row)
        assert row.review_status == ReviewStatus.SUPERSEDED and row.reviewed_by_user_id is None
        (alert,) = h.review_alerts(s, case)
        assert alert.status == AlertStatus.DONE and alert.data["closed_reason"] == "entered"
        with pytest.raises(WorkflowError) as e:
            next_dates.enter(s, actor, dse, case, next_date=h.days(548), order_id=order.id)
        assert (e.value.code, e.value.http_status) == ("already_entered", 409)
        nd2 = next_dates.enter(s, actor, dse, case, next_date=h.days(548))  # no order link: another row
        assert nd2.ref_no == f"ASLMS/EDU-DSE/NXT/{year}/000002"
        actor, admin = world.actor(s, "edu_admin")
        nd3 = next_dates.enter(s, actor, admin, case, next_date=h.days(7))
        assert nd3.ref_no == f"ASLMS/EDU/NXT/{year}/000001"  # per office
        (audit, *_) = _audits(s, "next_date.enter", case)
        assert "as told by counsel" not in str(audit.after)
        # the timeline shows the entry to every reader of the case
        health = world.user(s, "health_admin")
        types = [i["type"] for i in case_detail.timeline(s, health, case).items]
        assert types.count("next_date_entered") == 3
        page = next_dates.case_next_dates(s, health, case)
        assert page.total == 4 and [i["effective"] for i in page.items] == [True, False, False, False]
        assert page.items[1]["note"] is None and page.items[2]["note"] == "as told by counsel"
        with pytest.raises(NotVisibleCase):
            next_dates.case_next_dates(s, world.user(s, "health_off"), make_case(s))
        s.rollback()


def test_the_review_alert(world):
    with world.Session() as s:
        soon_case, soon_order, soon_row = _pending(s, world, text="List the matter after a week.")
        far_case, _, _ = _pending(s, world, text="List the matter after 4 (four) weeks.")
        old_case, _, _ = _pending(s, world, text="List after 4 weeks.", order_date=h.days(-20))
        unclaimed = make_case(s)
        h.order_with_text(s, unclaimed, "List after 3 weeks.", order_date=h.days(-1))
        enter_case = h.claimed(s, world)
        h.order_with_text(s, enter_case, "List the matter after vacation.", order_date=h.days(-1))
        h.read(s)
        c = alerts.scan_events(s)
        assert c["alerts_new"] == 3, c
        (soon,) = h.review_alerts(s, soon_case)
        assert soon.severity == Severity.HIGH and soon.data["hearing_date"] == str(h.days(6))
        assert (
            soon.data["source"] == "order_period" and soon.dedupe_key == f"next_date_review:{soon_order.id}"
        )
        assert "Next date to confirm" in soon.title and "counted from the order of" in soon.body
        (far,) = h.review_alerts(s, far_case)
        assert far.severity == Severity.NORMAL
        (enter,) = h.review_alerts(s, enter_case)
        assert enter.data["hearing_date"] is None and enter.title.startswith("Enter the next date")
        assert h.review_alerts(s, old_case) == [] and h.review_alerts(s, unclaimed) == []
        assert alerts.scan_events(s)["alerts_new"] == 0  # a re-scan raises nothing new
        # the sweep expires an alert whose order has no queue item left
        s.execute(
            sa.update(next_dates.NextDate)
            .where(next_dates.NextDate.id == soon_row.id)
            .values(review_status=ReviewStatus.SUPERSEDED)
        )
        c = alerts.sweep_dates(s, now=datetime.now(UTC))
        assert c["closed_next_date"] == 1
        s.refresh(soon)
        s.refresh(far)
        assert soon.status == AlertStatus.EXPIRED and soon.data["closed_reason"] == "no_review_item"
        assert far.status == AlertStatus.OPEN
        s.rollback()


def test_queue_and_counts(world):
    with world.Session() as s:
        from aslms.services import dashboard

        case, order, row = _pending(s, world)
        unit_case, _, unit_row = _pending(s, world, unit_code="EDU-DSE")
        enter_case = h.claimed(s, world)
        enter_order = h.order_with_text(s, enter_case, "List after vacation.", order_date=h.days(-1))
        h.read(s)
        actor, admin = world.actor(s, "edu_admin")
        page = next_dates.review_items(s, admin)
        assert page.total == 3
        assert [i["kind"] for i in page.items] == ["confirm", "confirm", "enter"]  # by act_by
        assert {i["id"] for i in page.items} == {row.id, unit_row.id, enter_order.id}
        assert next_dates.review_items(s, admin, kind="enter").total == 1
        assert next_dates.review_items(s, admin, limit=1, offset=1).items[0]["kind"] == "confirm"
        with pytest.raises(WorkflowError):
            next_dates.review_items(s, admin, kind="other")
        dse = world.user(s, "dse_user")
        assert [i["id"] for i in next_dates.review_items(s, dse).items] == [unit_row.id]
        assert next_dates.review_items(s, dse).items[0]["departments"] == ["EDU"]
        # the dashboard counts the department's items; the overview the caller's for the case
        edu = world.office(s, "EDU")
        att = dashboard.department_block(s, admin, edu)["attention"]
        assert att["next_dates_to_review"] == 3
        assert {i["case"]["id"] for i in att["recent_order_next_dates"]} == {case.id, unit_case.id}
        next_dates.reject(s, actor, admin, row.id)
        att = dashboard.department_block(s, admin, edu)["attention"]
        assert att["next_dates_to_review"] == 2
        assert {i["case"]["id"] for i in att["recent_order_next_dates"]} == {
            unit_case.id
        }  # rejected left out
        assert case_detail.overview(s, dse, unit_case)["next_dates_to_review"] == 1
        over = case_detail.overview(s, admin, case)
        assert over["next_dates_to_review"] == 0 and over["next_date_from_orders"] is None
        next_dates.confirm(s, actor, admin, unit_row.id)
        over = case_detail.overview(s, admin, unit_case)
        assert over["next_date_from_orders"]["id"] == unit_row.id
        assert over["next_date_from_orders"]["order"]["rule"] == "list_after_period"
        (item,) = case_detail.orders(s, admin, enter_case).items
        assert item["next_date_status"] == "unclear" and item["next_date_rule"] == "no_countable_date"
        assert item["next_date_phrase"].startswith("List after vacation")
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
