"""The next-date reader (design `next-date-extraction`, decisions 4-8, 14, 16, 19, as changed by `next-date-direct`,
decisions 1 to 3): rows only for the case's current order with a date today or later, every one shown directly
(`not_needed`, no review), readings recorded on every order, supersede and expiry, `enter` items (unclear, none,
no text), idempotence, `--reread`, failures recorded, the CHECKs, the calendar's one value, dedupe's portal records and
no outside call."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa

from aslms.domain.alerts import Alert, NextDate, NextDateSource, ReviewStatus
from aslms.domain.documents import Order, OrderNextDateStatus, TextStatus
from aslms.domain.events import AuditLog
from aslms.domain.ops import JobRun, SourceFailure
from aslms.domain.reference import AlertKind, EventType
from aslms.services import alerts, calendar, case_dedupe, next_dates
from aslms.services import next_date_rules as rules
from aslms.services.audit import Actor
from aslms.services.workflow_common import WorkflowError
from tests.db import next_dates_support as h
from tests.db.world import make_case


def _manual(s, case, on, *, order_id=None, created=None) -> NextDate:
    """A manual next date written directly (as entered before a court-given date existed)."""
    row = NextDate(
        ref_no=f"T/NXT/{uuid.uuid4().hex[:10]}",
        case_id=case.id,
        next_date=on,
        source=NextDateSource.MANUAL,
        order_id=order_id,
        review_status=ReviewStatus.NOT_NEEDED,
    )
    s.add(row)
    s.flush()
    if created is not None:
        s.execute(sa.update(NextDate).where(NextDate.id == row.id).values(created_at=created))
    return row


def test_current_order_with_the_courts_date_gives_a_not_needed_row(world):
    """A written date in the current order is shown directly (design next-date-direct, decision 3)."""
    with world.Session() as s:
        case = make_case(s, next_hearing=h.days(10))
        old = h.order_with_text(
            s, case, f"List the matter on {h.dmy(h.days(15))}.", order_date=h.days(-20), order_no="1"
        )
        current = h.order_with_text(
            s, case, f"Heard. List this matter on {h.dmy(h.days(10))}.", order_date=h.days(-1), order_no="2"
        )
        other = make_case(s)
        bail = h.order_with_text(s, other, "The petitioner is released on bail. Disposed of.")
        past = make_case(s)
        stale = h.order_with_text(
            s, past, f"List the matter on {h.dmy(h.days(-2))}.", order_date=h.days(-9), order_no="3"
        )
        c = h.read(s)
        assert c["claimed"] == 4 and c["specific"] == 3 and c["none"] == 1 and c["rows_written"] == 1
        (row,) = h.rows(s, case)
        assert (row.source, row.review_status, row.order_id, row.next_date) == (
            NextDateSource.ORDER_SPECIFIC,
            ReviewStatus.NOT_NEEDED,
            current.id,
            h.days(10),
        )
        assert float(row.confidence) == 1.0 and row.needs_review is False and row.ref_no is None
        # every order keeps its reading
        for o, status, found in (
            (old, OrderNextDateStatus.SPECIFIC, h.days(15)),
            (current, OrderNextDateStatus.SPECIFIC, h.days(10)),
            (bail, OrderNextDateStatus.NONE, None),
            (stale, OrderNextDateStatus.SPECIFIC, h.days(-2)),
        ):
            s.refresh(o)
            assert (o.next_date_status, o.next_date_found) == (status, found)
            assert o.next_date_rules_version == rules.RULES_VERSION and o.next_date_read_at is not None
        assert current.next_date_rule == "list_on_date" and "List this matter" in current.next_date_phrase
        assert h.rows(s, other) == [] and h.rows(s, past) == []
        (ev,) = h.events(s, case)
        assert ev.payload["review"] is False and ev.payload["next_date_id"] == str(row.id)
        assert ev.payload["rule"] == "list_on_date" and ev.payload["order_no"] == "2"
        assert h.events(s, other) == [] and h.events(s, past) == []
        # nothing audited: the reading is system work
        assert (
            s.scalar(sa.select(sa.func.count()).select_from(AuditLog).where(AuditLog.case_id == case.id)) == 0
        )
        s.rollback()


def test_a_period_is_shown_directly_supersedes_and_expires(world):
    with world.Session() as s:
        case = make_case(s)
        first = h.order_with_text(
            s, case, "List this matter after four weeks.", order_date=h.days(-3), order_no="1"
        )
        h.read(s)
        (r1,) = h.rows(s, case)
        assert (r1.source, r1.review_status, float(r1.confidence), r1.needs_review) == (
            NextDateSource.ORDER_PERIOD,
            ReviewStatus.NOT_NEEDED,
            0.6,
            False,
        )
        assert r1.next_date == h.days(-3) + timedelta(weeks=4) and r1.order_id == first.id
        s.refresh(case)
        assert (case.next_hearing_on, case.next_hearing_basis.value) == (r1.next_date, "around")
        second = h.order_with_text(
            s, case, "List the matter after 2 (two) weeks.", order_date=h.days(-1), order_no="2"
        )
        c = h.read(s)
        assert c["superseded"] == 1 and c["review_items"] == 0
        r1, r2 = h.rows(s, case)
        assert r1.review_status == ReviewStatus.SUPERSEDED and r1.reviewed_by_user_id is None
        assert r1.reviewed_at is None
        assert (r2.review_status, r2.order_id, r2.next_date) == (
            ReviewStatus.NOT_NEEDED,
            second.id,
            h.days(13),
        )
        s.refresh(case)
        assert (case.next_hearing_on, case.next_hearing_next_date_id) == (h.days(13), r2.id)
        # a pending date that passed expires at the next run
        stale = NextDate(
            case_id=case.id,
            next_date=h.days(-1),
            source=NextDateSource.ORDER_PERIOD,
            needs_review=True,
            review_status=ReviewStatus.PENDING,
        )
        s.add(stale)
        s.flush()
        assert next_dates.expire_stale(s, h.days(0)) == 1
        s.refresh(stale)
        assert stale.review_status == ReviewStatus.EXPIRED
        s.rollback()


def test_a_newer_order_without_a_usable_date_closes_older_dates(world):
    """Deviation 11 (review finding): the latest order decides, so a disposal, an unclear direction or a past date
    in the newest order stops the dates of older orders (calendar, hearing alerts, confirm items)."""

    def dates(s, case):
        return [
            r.date
            for r in calendar.hearing_rows(
                s, from_=h.days(0), to=h.days(60), case_condition=calendar.owned_case_condition()
            )
            if r.case_id == case.id and r.source == "next_date"
        ]

    with world.Session() as s:
        actor, admin = world.actor(s, "edu_admin")
        # example 1: a written date, then the case is disposed of
        disposed = h.claimed(s, world)
        h.order_with_text(
            s, disposed, f"List this matter on {h.dmy(h.days(5))}.", order_date=h.days(-20), order_no="1"
        )
        h.read(s)
        assert dates(s, disposed) == [h.days(5)]
        assert next_dates.effective_for_case(s, disposed) is not None
        h.order_with_text(
            s, disposed, "The writ petition is disposed of.", order_date=h.days(-2), order_no="2"
        )
        c = h.read(s)
        assert c["none"] == 1 and c["superseded"] == 1 and c["rows_written"] == 0
        (row,) = h.rows(s, disposed)
        assert row.review_status == ReviewStatus.SUPERSEDED and row.reviewed_at is None
        assert dates(s, disposed) == [] and next_dates.effective_for_case(s, disposed) is None

        # example 2: a counted period, then "list after vacation": only the enter item is left
        vacation = h.claimed(s, world)
        h.order_with_text(s, vacation, "List this matter after 4 weeks.", order_date=h.days(-6), order_no="1")
        h.read(s)
        (pending,) = h.rows(s, vacation)
        assert pending.review_status == ReviewStatus.NOT_NEEDED
        unclear = h.order_with_text(
            s, vacation, "List the matter after vacation.", order_date=h.days(-1), order_no="2"
        )
        c = h.read(s)
        assert c["unclear"] == 1 and c["superseded"] == 1 and c["review_items"] == 1
        assert h.refreshed(s, pending).review_status == ReviewStatus.SUPERSEDED
        items = next_dates.review_items(s, admin).items
        assert [(i["kind"], i["id"]) for i in items if i["case"]["id"] == vacation.id] == [
            ("enter", unclear.id)
        ]
        with pytest.raises(WorkflowError) as exc:
            next_dates.confirm(s, actor, admin, pending.id)
        assert exc.value.code == "not_pending"

        # a confirmed date (before next-date-direct), a manual answer to the old order and an older manual date all
        # stop when a newer order is read, audited as a person's record closed by the system; a manual date the court
        # then outranks is superseded too (decision 7), and a same-date order's row stays
        mixed = h.claimed(s, world)
        old = h.order_with_text(s, mixed, "List after 3 weeks.", order_date=h.days(-10), order_no="1")
        h.read(s)
        (confirmed,) = h.rows(s, mixed)
        s.execute(
            sa.update(NextDate)
            .where(NextDate.id == confirmed.id)
            .values(
                review_status=ReviewStatus.CONFIRMED,
                reviewed_by_user_id=admin.id,
                reviewed_at=datetime.now(UTC),
            )
        )
        answer = _manual(s, mixed, h.days(30), order_id=old.id)
        early = _manual(s, mixed, h.days(31), created=datetime.now(UTC) - timedelta(days=5))
        late = _manual(s, mixed, h.days(32))
        mixed.next_hearing_date = h.days(40)  # the court's record gives a date
        s.flush()
        sibling = h.order_with_text(
            s, mixed, f"List this matter on {h.dmy(h.days(40))}.", order_date=h.days(-3), order_no="2a"
        )
        h.read(s)
        (sibling_row,) = [r for r in h.rows(s, mixed) if r.order_id == sibling.id]
        h.order_with_text(
            s, mixed, f"List this matter on {h.dmy(h.days(-1))}.", order_date=h.days(-3), order_no="2b"
        )
        h.read(s)
        status = {r.id: r.review_status for r in h.rows(s, mixed)}
        assert status[confirmed.id] == ReviewStatus.SUPERSEDED
        assert h.refreshed(s, confirmed).reviewed_by_user_id is not None
        assert status[answer.id] == ReviewStatus.SUPERSEDED and status[early.id] == ReviewStatus.SUPERSEDED
        assert status[late.id] == ReviewStatus.SUPERSEDED  # the court's record outranks it (decision 7)
        assert status[sibling_row.id] == ReviewStatus.NOT_NEEDED
        audited = {
            a.entity_id: a
            for a in s.scalars(
                sa.select(AuditLog).where(
                    AuditLog.case_id == mixed.id, AuditLog.action == "next_date.superseded_by_court"
                )
            ).all()
        }
        assert set(audited) == {confirmed.id, answer.id, early.id, late.id}
        assert all(a.actor_user_id is None and a.actor_name == "next_hearing" for a in audited.values())
        assert audited[late.id].after["replaced_by"]["basis"] == "court"
        assert audited[early.id].after["replaced_by"]["basis"] == "newer_order"
        s.rollback()


def test_unclear_current_orders_of_claimed_cases_ask_for_a_date(world):
    with world.Session() as s:
        _, admin = world.actor(s, "edu_admin")
        case = h.claimed(s, world)
        unclear = h.order_with_text(
            s,
            case,
            "On the prayer of the parties, list the matter after winter vacation.",
            order_date=h.days(-2),
        )
        unclaimed = make_case(s)
        h.order_with_text(s, unclaimed, "List the matter after the ensuing vacation.", order_date=h.days(-2))
        old_case = h.claimed(s, world)
        h.order_with_text(s, old_case, "List the matter after vacation.", order_date=h.days(-31))
        c = h.read(s)
        assert c["unclear"] == 3 and c["review_items"] == 2 and c["rows_written"] == 0
        (ev,) = h.events(s, case)
        assert ev.payload["review"] is True and ev.payload["next_date_id"] is None
        assert ev.payload["status"] == "unclear" and ev.payload["rule"] == "no_countable_date"
        assert h.events(s, old_case) == []  # older than NEXT_DATE_UNCLEAR_DAYS
        page = next_dates.review_items(s, admin)
        assert [(i["kind"], i["id"]) for i in page.items] == [("enter", unclear.id)]
        item = page.items[0]
        assert item["next_date"] is None and item["act_by"] == h.days(-2) + timedelta(days=30)
        assert item["departments"] == ["EDU"] and item["rule"] == "no_countable_date"
        # a newer order of the case takes the item away
        newer = h.order_with_text(s, case, "Disposed of.", order_date=h.days(-1))
        assert next_dates.review_items(s, admin).total == 0
        s.execute(sa.delete(Order).where(Order.id == newer.id))
        assert next_dates.review_items(s, admin).total == 1
        # a manual date answers it
        actor, admin = world.actor(s, "edu_admin")
        next_dates.enter(s, actor, admin, case, next_date=h.days(20), order_id=unclear.id)
        assert next_dates.review_items(s, admin).total == 0
        s.rollback()


def test_a_not_before_date_is_shown_directly_as_around(world):
    """Design next-date-direct, decision 1: "List the matter after <date>" is shown directly, marked around, and
    drives the calendar at once; nobody confirms it and nobody may change it (decision 6)."""
    with world.Session() as s:
        case = h.claimed(s, world)
        order = h.order_with_text(
            s, case, f"List the matter after {h.dmy(h.days(4))}.", order_date=h.days(-1), order_no="1"
        )
        c = h.read(s)
        assert c["specific"] == 1 and c["rows_written"] == 1 and c["review_items"] == 0
        s.refresh(order)
        assert order.next_date_rule == "qualified_date" and order.next_date_found == h.days(4)
        (row,) = h.rows(s, case)
        assert (row.source, row.review_status, float(row.confidence), row.needs_review) == (
            NextDateSource.ORDER_SPECIFIC,
            ReviewStatus.NOT_NEEDED,
            0.8,
            False,
        )
        (ev,) = h.events(s, case)
        assert ev.payload["review"] is False and ev.payload["rule"] == "qualified_date"

        def dates():
            return [
                r.date
                for r in calendar.hearing_rows(
                    s, from_=h.days(0), to=h.days(60), case_condition=calendar.owned_case_condition()
                )
                if r.case_id == case.id and r.source == "next_date"
            ]

        assert dates() == [h.days(4)]
        s.refresh(case)
        assert (case.next_hearing_on, case.next_hearing_basis.value) == (h.days(4), "around")
        actor, admin = world.actor(s, "edu_admin")
        assert next_dates.review_items(s, admin).total == 0
        with pytest.raises(WorkflowError) as exc:
            next_dates.confirm(s, actor, admin, row.id)
        assert exc.value.code == "court_date_fixed"
        s.rollback()


def test_another_matters_date_asks_for_a_date(world):
    """Point 3: a direction that carries another matter's date is an *enter* item, never a row."""
    with world.Session() as s:
        case = h.claimed(s, world)
        order = h.order_with_text(
            s,
            case,
            f"List this matter on {h.dmy(h.days(9))} as the writ appeal against the same order is fixed on "
            f"{h.dmy(h.days(5))}.",
            order_date=h.days(-1),
        )
        c = h.read(s)
        assert c["unclear"] == 1 and c["rows_written"] == 0 and c["review_items"] == 1
        s.refresh(order)
        assert order.next_date_rule == "conflicting_dates" and order.next_date_found is None
        _, admin = world.actor(s, "edu_admin")
        assert [(i["kind"], i["id"]) for i in next_dates.review_items(s, admin).items] == [
            ("enter", order.id)
        ]
        s.rollback()


def test_an_enter_item_stays_answered_after_a_reread(world):
    """Review advisory: a manual date linked to the order answers its *enter* item even after `--reread` puts the
    order back and reads it again (its `next_date_read_at` is then later than the manual row)."""
    with world.Session() as s:
        case = h.claimed(s, world)
        order = h.order_with_text(
            s, case, "List the matter after the ensuing vacation.", order_date=h.days(-2)
        )
        h.read(s)
        actor, admin = world.actor(s, "edu_admin")
        next_dates.enter(s, actor, admin, case, next_date=h.days(20), order_id=order.id)
        assert next_dates.review_items(s, admin).total == 0
        s.commit()
    with world.Session() as s:  # a new transaction: now() moves on
        _, admin = world.actor(s, "edu_admin")
        assert next_dates.reread(s, Actor.system("cli"), all_versions=True) >= 1
        c = h.read(s)
        assert c["unclear"] == 1 and c["review_items"] == 0
        order = s.get(Order, order.id)
        manual = s.scalar(sa.select(NextDate).where(NextDate.order_id == order.id))
        assert order.next_date_read_at > manual.created_at
        assert manual.review_status == ReviewStatus.NOT_NEEDED  # the answer stays the effective date
        assert next_dates.review_items(s, admin).total == 0
        s.rollback()


def test_no_text_pending_text_idempotence_and_reread(world):
    with world.Session() as s:
        case = h.claimed(s, world)
        scan = h.order_with_text(s, case, None, text_status=TextStatus.NONE, order_date=h.days(-1))
        waiting = h.order_with_text(
            s, case, "List on 01.01.2030", text_status=TextStatus.PENDING, order_no="w"
        )
        no_doc = Order(case_id=case.id, order_no="nd", order_date=h.days(-1), kind="interim")
        s.add(no_doc)
        s.flush()
        c = h.read(s)
        assert c["claimed"] == 1 and c["no_text"] == 1 and c["review_items"] == 1
        for o, status in ((scan, "no_text"), (waiting, "pending"), (no_doc, "pending")):
            s.refresh(o)
            assert o.next_date_status == OrderNextDateStatus(status)
        assert h.read(s)["claimed"] == 0  # a second run reads nothing
        # --reread: only orders of an older rules version go back
        other = make_case(s)
        o2 = h.order_with_text(s, other, f"List on {h.dmy(h.days(5))}.")
        h.read(s)
        s.execute(sa.update(Order).where(Order.id == o2.id).values(next_date_rules_version=0))
        n = next_dates.reread(s, Actor.system("cli"))
        assert n == 1
        s.refresh(o2)
        s.refresh(scan)
        assert o2.next_date_status == OrderNextDateStatus.PENDING and o2.next_date_read_at is None
        assert scan.next_date_status == OrderNextDateStatus.NO_TEXT
        (audit,) = s.scalars(sa.select(AuditLog).where(AuditLog.action == "next_dates.reread")).all()
        assert audit.after["orders"] == 1 and audit.actor_name == "cli"
        c = h.read(s)
        assert c["claimed"] == 1 and c["rows_written"] == 0  # the row already exists
        assert len(h.rows(s, other)) == 1 and len(h.events(s, other)) == 1  # deduplicated event
        assert next_dates.reread(s, Actor.system("cli"), all_versions=True) == 2
        s.rollback()


def test_a_failure_is_recorded_and_resolved(world, monkeypatch):
    with world.Session() as s:
        case = make_case(s)
        order = h.order_with_text(s, case, f"List on {h.dmy(h.days(5))}.")
        real = rules.read_order_text

        def boom(*a, **kw):
            raise RuntimeError("bad text")

        monkeypatch.setattr(rules, "read_order_text", boom)
        c = h.read(s)
        assert c["failed"] == 1
        s.refresh(order)
        assert order.next_date_status == OrderNextDateStatus.PENDING
        fail = s.scalar(sa.select(SourceFailure).where(SourceFailure.kind == "next_date_read"))
        assert fail.ref == str(order.id) and "bad text" in fail.error and fail.resolved_at is None
        monkeypatch.setattr(rules, "read_order_text", real)
        assert h.read(s)["specific"] == 1
        s.refresh(fail)
        assert fail.resolved_at is not None
        s.rollback()


def test_the_job_writes_a_run(world):
    with world.Session() as s:
        case = make_case(s)
        h.order_with_text(s, case, f"List on {h.dmy(h.days(5))}.")
        counters = next_dates.run_job(s, cfg=replace(next_dates.NextDateConfig.from_settings(), batch=10))
        run = s.scalar(sa.select(JobRun).where(JobRun.job == "next_dates_read"))
        assert run.status.value == "succeeded" and run.counters == counters and counters["rows_written"] == 1
        s.rollback()


def test_check_constraints(world):
    with world.Session() as s:
        case = make_case(s)
        order = h.order_with_text(s, case, "x")
        with pytest.raises(sa.exc.IntegrityError), s.begin_nested():
            s.execute(sa.update(Order).where(Order.id == order.id).values(next_date_found=h.days(3)))
        with pytest.raises(sa.exc.IntegrityError), s.begin_nested():
            s.execute(
                sa.update(Order)
                .where(Order.id == order.id)
                .values(next_date_status=OrderNextDateStatus.NONE)  # read without a read time
            )
        with pytest.raises(sa.exc.IntegrityError), s.begin_nested():
            s.add(
                NextDate(
                    case_id=case.id,
                    next_date=h.days(3),
                    source=NextDateSource.ORDER_PERIOD,
                    needs_review=False,
                    review_status=ReviewStatus.PENDING,
                )
            )
            s.flush()
        with pytest.raises(sa.exc.IntegrityError), s.begin_nested():
            s.add(NextDate(case_id=case.id, next_date=h.days(3), source=NextDateSource.MANUAL))
            s.flush()
        with pytest.raises(sa.exc.IntegrityError), s.begin_nested():
            s.add(
                NextDate(
                    case_id=case.id,
                    next_date=h.days(3),
                    source=NextDateSource.ORDER_SPECIFIC,
                    review_status=ReviewStatus.CONFIRMED,
                    needs_review=True,
                )
            )
            s.flush()
        s.rollback()


def test_the_calendar_uses_the_one_next_hearing(world):
    with world.Session() as s:
        case = h.claimed(s, world)
        h.order_with_text(s, case, f"List the matter on {h.dmy(h.days(3))}.", order_date=h.days(-6))
        h.read(s)

        def dates():
            return [
                r.date
                for r in calendar.hearing_rows(
                    s, from_=h.days(0), to=h.days(60), case_condition=calendar.owned_case_condition()
                )
                if r.case_id == case.id and r.source == "next_date"
            ]

        assert dates() == [h.days(3)]
        h.order_with_text(s, case, "List the matter after four weeks.", order_date=h.days(-2))
        h.read(s)
        (old, new) = h.rows(s, case)
        assert (old.review_status, new.review_status) == (ReviewStatus.SUPERSEDED, ReviewStatus.NOT_NEEDED)
        assert dates() == [
            h.days(-2) + timedelta(weeks=4)
        ]  # the newer order's period replaces the older date
        s.rollback()
    with world.Session() as s:
        case = h.claimed(s, world)
        h.order_with_text(s, case, "List the matter after 1 (one) week.", order_date=h.days(-1))
        h.read(s)
        now = datetime.now(UTC)
        s.commit()
        alerts.sweep_dates(s, now=now)  # a period drives the hearing alert at once, "around"
        s.commit()
        hearing = s.scalars(
            sa.select(Alert).where(Alert.case_id == case.id, Alert.kind == AlertKind.HEARING_DUE)
        ).all()
        (alert,) = hearing
        assert alert.data["hearing_date"] == str(h.days(6)) and alert.data["source"] == "next_date"
        assert alert.data["basis"] == "around" and alert.title.startswith("Hearing around ")
        assert "The court's own date will replace it" in alert.body


def test_portal_records_count_a_reviewed_row(world):
    with world.Session() as s:
        case = h.claimed(s, world)
        h.order_with_text(s, case, "List after 3 weeks.", order_date=h.days(-1))
        h.read(s)
        assert "next_dates" not in case_dedupe.portal_records(s, case)
        (row,) = h.rows(s, case)
        actor, root = world.actor(s, "root")
        next_dates.correct(s, actor, root, row.id, reason="the order says four weeks, not three")
        assert "next_dates" in case_dedupe.portal_records(s, case)
        s.rollback()


def test_no_outside_call(world, monkeypatch):
    """Nothing in the reader or the review path calls NAPIX, SourceTrace or any HTTP service."""
    import aslms.integration.sourcetrace as st

    def refuse(*a, **kw):
        raise AssertionError("no outside call is allowed")

    monkeypatch.setattr(httpx.Client, "send", refuse)
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    monkeypatch.setattr(st, "get_connector", refuse)
    with world.Session() as s:
        case = h.claimed(s, world)
        h.order_with_text(s, case, "List after 3 weeks.", order_date=h.days(-1))
        h.order_with_text(s, make_case(s), "List the matter after vacation.", order_date=h.days(-1))
        h.read(s)
        (row,) = h.rows(s, case)
        actor, admin = world.actor(s, "edu_admin")
        root_actor, root = world.actor(s, "root")
        next_dates.report_wrong(s, actor, admin, row.id, reason="the order says four weeks")
        next_dates.correct(
            s, root_actor, root, row.id, reason="the order says four weeks", next_date=h.days(30)
        )
        next_dates.enter(s, actor, admin, case, next_date=h.days(40))
        alerts.scan_events(s)
        alerts.sweep_dates(s)
        assert {e.type for e in h.events(s, case, EventType.NEXT_DATE_ENTERED)} == {
            EventType.NEXT_DATE_ENTERED
        }
        s.rollback()
