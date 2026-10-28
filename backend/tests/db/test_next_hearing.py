"""The case's one next hearing (design `next-date-direct`, decisions 4, 5, 7 and Jobs): the court's record first (the
earliest of NAPIX's next date and the current listings after the latest order), else the latest order's reading
(exact or around), else the court's last given date when it has passed, else a date entered by hand; the discrepancy
flag and its event; manual rows superseded and audited when the court gives a date; the 5-minute job's rollovers,
backfill and failed refreshes; the migration's CHECKs."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import sqlalchemy as sa

from aslms.domain.alerts import NextDate, NextDateSource, ReviewStatus
from aslms.domain.cases import Case, NextHearingBasis
from aslms.domain.causelists import Causelist, CauselistEntry, EntrySource, ListSource, ListType
from aslms.domain.courts import Court
from aslms.domain.events import AuditLog, Event
from aslms.domain.ops import SourceFailure
from aslms.domain.reference import EventType
from aslms.services import cases, next_hearing
from tests.db import next_dates_support as h
from tests.db.conftest import sample
from tests.db.world import make_case


def _listed(s, case, on: date, *, superseded: bool = False) -> None:
    court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
    cl = Causelist(court_id=court.id, list_date=on, list_type=ListType.DAILY, source=ListSource.GHC_WEBSITE)
    s.add(cl)
    s.flush()
    if superseded:
        s.execute(sa.text("UPDATE causelists SET superseded_at = now() WHERE id = :i"), {"i": cl.id})
    s.add(
        CauselistEntry(
            causelist_id=cl.id, sr_no=1, case_id=case.id, cnr=case.cnr, source=EntrySource.PDF_PARSE
        )
    )
    s.flush()


def _value(s, case, today=None):
    return next_hearing.compute(s, [case.id], today=today)[case.id]


def _manual(s, case, on, *, order_id=None) -> NextDate:
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
    return row


def _stored(s, case):
    s.refresh(case)
    return (
        case.next_hearing_on,
        case.next_hearing_basis.value if case.next_hearing_basis else None,
        case.next_hearing_differs_on,
    )


# ------------------------------------------------------------------------------------------------ the court tier


def test_the_courts_record_wins_and_the_earliest_of_napix_and_listing(world):
    with world.Session() as s:
        exact = make_case(s, next_hearing=h.days(10))
        _listed(s, exact, h.days(8))
        _listed(s, exact, h.days(6), superseded=True)  # a replaced list is not the court's current record
        _listed(s, exact, h.days(-3))  # a listing before the latest order is the past
        h.order_with_text(s, exact, f"List this matter on {h.dmy(h.days(12))}.", order_date=h.days(-1))
        around = make_case(s, next_hearing=h.days(10))
        h.order_with_text(s, around, "List the matter after 2 (two) weeks.", order_date=h.days(-1))
        h.read(s)
        v = _value(s, exact)
        assert (v.date, v.basis, v.differs_on) == (h.days(8), NextHearingBasis.COURT, h.days(12))
        assert v.next_date_id is None and v.differs_id is not None
        v = _value(s, around)  # an around reading never raises the flag (decision 5)
        assert (v.date, v.basis, v.differs_on) == (h.days(10), NextHearingBasis.COURT, None)
        s.rollback()


def test_a_court_date_equal_to_the_latest_order_date_is_the_hearing_just_held(world):
    with world.Session() as s:
        case = make_case(s, next_hearing=h.days(0))
        _listed(s, case, h.days(0))
        h.order_with_text(s, case, "List the matter after 2 (two) weeks.", order_date=h.days(0))
        h.read(s)
        v = _value(s, case)
        assert (v.date, v.basis) == (h.days(14), NextHearingBasis.AROUND)
        s.rollback()


# ------------------------------------------------------------------------------------------------ the order tier


@pytest.mark.parametrize(
    ("text", "basis", "on"),
    [
        ("List the matter after 3 weeks.", NextHearingBasis.AROUND, lambda: h.days(-1) + timedelta(weeks=3)),
        ("List the matter after {d}.", NextHearingBasis.AROUND, lambda: h.days(9)),
        ("Notice returnable on {d}.", NextHearingBasis.AROUND, lambda: h.days(9)),
        ("List this matter on {d}.", NextHearingBasis.ORDER, lambda: h.days(9)),
    ],
)
def test_the_latest_orders_reading(world, text, basis, on):
    with world.Session() as s:
        case = make_case(s)
        h.order_with_text(s, case, text.format(d=h.dmy(h.days(9))), order_date=h.days(-1))
        h.read(s)
        (row,) = h.rows(s, case)
        v = _value(s, case)
        assert (v.date, v.basis, v.next_date_id, v.differs_on) == (on(), basis, row.id, None)
        s.rollback()


def test_a_past_reading_gives_nothing_and_a_newer_dateless_order_stops_an_older_one(world):
    with world.Session() as s:
        past = make_case(s)
        h.order_with_text(s, past, f"List this matter on {h.dmy(h.days(-2))}.", order_date=h.days(-9))
        older = make_case(s)
        h.order_with_text(s, older, "List the matter after 3 weeks.", order_date=h.days(-6), order_no="1")
        h.read(s)
        assert _value(s, past) is None and h.rows(s, past) == []
        assert _value(s, older).basis == NextHearingBasis.AROUND
        h.order_with_text(s, older, "Issue notice.", order_date=h.days(-1), order_no="2")
        h.read(s)
        assert _value(s, older) is None
        s.rollback()


def test_a_court_given_date_that_passed_stays_as_an_ultimatum(world):
    """Owner, 28 Oct 2026: the court's last given date stays the value once passed, until something newer."""
    with world.Session() as s:
        court = make_case(s, next_hearing=h.days(2))
        h.order_with_text(s, court, "x", order_date=h.days(-5))
        read = make_case(s)
        h.order_with_text(s, read, f"List this matter on {h.dmy(h.days(3))}.", order_date=h.days(-1))
        h.read(s)
        later = h.days(6)
        assert (_value(s, court, later).date, _value(s, court, later).basis) == (
            h.days(2),
            NextHearingBasis.COURT,
        )
        assert (_value(s, read, later).date, _value(s, read, later).basis) == (
            h.days(3),
            NextHearingBasis.ORDER,
        )
        assert next_hearing.court_given(s, read, today=later)
        # a newer order without a date ends it: nothing is given any more
        h.order_with_text(s, court, "Issue notice.", order_date=h.days(3))
        assert _value(s, court, later) is None
        s.rollback()


# ------------------------------------------------------------------------------------------------ manual dates


def test_a_manual_date_only_without_a_court_given_date_and_superseded_with_audit(world):
    with world.Session() as s:
        case = make_case(s)
        h.order_with_text(s, case, "List the matter after vacation.", order_date=h.days(-2))
        h.read(s)
        row = _manual(s, case, h.days(20), order_id=None)
        row.note = "secret words of the clerk"
        next_hearing.refresh(s, [case.id])
        assert _stored(s, case) == (h.days(20), "manual", None)
        assert case.next_hearing_next_date_id == row.id
        # the court gives a date: the manual row is superseded by a system closure, audited without its note
        case.next_hearing_date = h.days(9)
        s.flush()
        result = next_hearing.refresh(s, [case.id])
        assert result.manual_superseded == 1 and result.changed == 1
        assert _stored(s, case) == (h.days(9), "court", None)
        s.refresh(row)
        assert (row.review_status, row.updated_by) == (ReviewStatus.SUPERSEDED, None)
        (audit,) = s.scalars(
            sa.select(AuditLog).where(
                AuditLog.action == "next_date.superseded_by_court", AuditLog.case_id == case.id
            )
        ).all()
        assert audit.actor_user_id is None and audit.actor_name == "next_hearing"
        assert audit.entity_type == "next_date" and audit.entity_id == row.id
        assert audit.after["replaced_by"] == {
            "basis": "court",
            "date": str(h.days(9)),
            "court_date": str(h.days(9)),
        }
        assert "secret" not in str(audit.before) + str(audit.after)
        assert next_hearing.refresh(s, [case.id]).manual_superseded == 0  # once
        s.rollback()


def test_an_order_reading_supersedes_a_manual_date(world):
    with world.Session() as s:
        case = make_case(s)
        old = h.order_with_text(
            s, case, "List the matter after vacation.", order_date=h.days(-5), order_no="1"
        )
        h.read(s)
        row = _manual(s, case, h.days(20), order_id=old.id)
        h.order_with_text(s, case, "List the matter after 2 weeks.", order_date=h.days(-1), order_no="2")
        h.read(s)
        assert h.refreshed(s, row).review_status == ReviewStatus.SUPERSEDED
        assert _stored(s, case)[1] == "around"
        assert (
            s.scalar(
                sa.select(sa.func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "next_date.superseded_by_court", AuditLog.entity_id == row.id)
            )
            == 1
        )
        s.rollback()


# ------------------------------------------------------------------------------------------------ the flag


def test_the_discrepancy_flag_appears_once_and_clears(world):
    with world.Session() as s:
        case = make_case(s, next_hearing=h.days(12))
        h.order_with_text(s, case, f"List this matter on {h.dmy(h.days(10))}.", order_date=h.days(-1))
        h.read(s)
        assert _stored(s, case) == (h.days(12), "court", h.days(10))

        def events():
            return list(
                s.scalars(
                    sa.select(Event).where(
                        Event.case_id == case.id, Event.type == EventType.NEXT_DATE_DIFFERS
                    )
                )
            )

        (ev,) = events()
        assert ev.payload["court_date"] == str(h.days(12)) and ev.payload["order_next_date"] == str(
            h.days(10)
        )
        next_hearing.refresh(s, [case.id])
        assert len(events()) == 1  # not repeated
        # the court agrees
        case.next_hearing_date = h.days(10)
        s.flush()
        r = next_hearing.refresh(s, [case.id])
        assert r.differs_cleared == 1 and _stored(s, case) == (h.days(10), "court", None)
        # the court moves away again; then the order's date passes
        case.next_hearing_date = h.days(15)
        s.flush()
        next_hearing.refresh(s, [case.id])
        assert _stored(s, case)[2] == h.days(10)
        next_hearing.refresh(s, [case.id], today=h.days(11))
        assert _stored(s, case) == (h.days(15), "court", None)
        # a newer order is read
        next_hearing.refresh(s, [case.id])
        assert _stored(s, case)[2] == h.days(10)
        h.order_with_text(s, case, "Issue notice.", order_date=h.days(0))
        h.read(s)
        assert _stored(s, case) == (h.days(15), "court", None)
        s.rollback()


# ------------------------------------------------------------------------------------------------ the job


def test_refresh_due_rolls_over_backfills_and_retries(world, monkeypatch):
    with world.Session() as s:
        rolled = make_case(s, next_hearing=h.days(2))
        h.order_with_text(s, rolled, "List the matter after 2 (two) weeks.", order_date=h.days(-1))
        h.read(s)
        next_hearing.refresh(s, [rolled.id])
        assert _stored(s, rolled) == (h.days(2), "court", None)
        unset = make_case(s)  # the court date written directly, as before the backfill
        unset.next_hearing_date = h.days(30)
        s.flush()
        assert unset.next_hearing_set_at is None
        out = next_hearing.refresh_due(s, today=h.days(5), batch=10**6)
        assert out["hearing_refreshed"] >= 1 and out["hearing_backfilled"] >= 1
        # the passed court date gives way to the order's reading, still ahead
        assert _stored(s, rolled) == (h.days(13), "around", None)
        assert _stored(s, unset) == (h.days(30), "court", None)
        assert unset.next_hearing_set_at is not None
        s.rollback()


def test_a_refresh_failure_never_fails_the_court_data(world, monkeypatch):
    with world.Session() as s:
        case = make_case(s, cnr="GAHC010129772026", case_no="WP(C)/3600/2026")

        def boom(*a, **kw):
            raise RuntimeError("refresh broke")

        monkeypatch.setattr(next_hearing, "refresh", boom)
        data = {**sample("cnr_pending.json"), "date_next_list": h.days(19).isoformat()}
        cases.apply_dossier(s, case, data)
        assert case.next_hearing_date == h.days(19) and case.last_full_refresh_at is not None
        fail = s.scalar(sa.select(SourceFailure).where(SourceFailure.kind == "next_hearing_refresh"))
        assert fail.ref == str(case.id) and "refresh broke" in fail.error
        monkeypatch.undo()
        next_hearing.refresh_due(s, batch=10**6)
        s.refresh(fail)
        assert fail.resolved_at is not None
        assert _stored(s, case) == (h.days(19), "court", None)
        s.rollback()


def test_court_data_paths_refresh_the_value(world):
    with world.Session() as s:
        case = make_case(s, cnr="GAHC010129772026", case_no="WP(C)/3600/2026")
        cases.apply_dossier(s, case, {**sample("cnr_pending.json"), "date_next_list": h.days(19).isoformat()})
        assert _stored(s, case)[:2] == (h.days(19), "court")
        block = {
            **sample("current_status_pending.json")["cases1"],
            "cino": case.cnr,
            "date_next_list": h.days(21).isoformat(),
        }
        cases.apply_status(s, case, block)
        assert _stored(s, case)[:2] == (h.days(21), "court")
        s.rollback()


# ------------------------------------------------------------------------------------------------ the CHECKs


@pytest.mark.parametrize(
    "values",
    [
        {"next_hearing_on": "2026-11-01"},  # a date without a basis
        {"next_hearing_basis": "court"},  # a basis without a date
        {"next_hearing_on": "2026-11-01", "next_hearing_basis": "order"},  # an order basis without its row
        {"next_hearing_on": "2026-11-01", "next_hearing_basis": "court", "next_hearing_next_date_id": "row"},
        {
            "next_hearing_on": "2026-11-01",
            "next_hearing_basis": "manual",
            "next_hearing_next_date_id": "row",
            "next_hearing_differs_on": "2026-11-02",
            "next_hearing_differs_id": "row",
        },  # differs on a non-court basis
        {
            "next_hearing_on": "2026-11-01",
            "next_hearing_basis": "court",
            "next_hearing_differs_on": "2026-11-02",
        },
    ],
)
def test_the_checks_refuse_inconsistent_values(world, values):
    with world.Session() as s:
        case = make_case(s)
        order = h.order_with_text(s, case, "x")
        row = NextDate(
            case_id=case.id, next_date=h.days(3), source=NextDateSource.ORDER_SPECIFIC, order_id=order.id
        )
        s.add(row)
        s.flush()
        params = {k: (row.id if v == "row" else v) for k, v in values.items()}
        with pytest.raises(sa.exc.IntegrityError), s.begin_nested():
            s.execute(sa.update(Case).where(Case.id == case.id).values(**params))
        s.rollback()


# ------------------------------------------------------------------------------------------------ calendar and alerts


def test_a_period_drives_the_calendar_and_the_court_date_replaces_it(world):
    """Decision 10: an around date drives My Calendar and a "Hearing around" alert at once; the court's date replaces
    it (the old alert closes `date_changed`, the court's raises its own); one calendar row per case."""
    from datetime import UTC, datetime

    from aslms.domain.alerts import Alert, AlertStatus
    from aslms.domain.reference import AlertKind
    from aslms.services import alerts, calendar

    with world.Session() as s:
        off1 = world.user(s, "edu_off1")
        case = h.claimed(s, world, officer_user_id=off1.id)
        h.order_with_text(s, case, "List the matter after 1 (one) week.", order_date=h.days(-1))
        h.read(s)
        mine = [
            i
            for i in calendar.my_calendar(s, off1, from_=h.days(0), to=h.days(30))
            if i["case"]["id"] == case.id
        ]
        assert [(i["date"], i["basis"], i["approximate"]) for i in mine] == [(h.days(6), "around", True)]
        assert mine[0]["basis_words"] == "after 1 week" and mine[0]["order_date"] == h.days(-1)
        now = datetime.now(UTC)
        alerts.sweep_dates(s, now=now)

        def hearing_alerts():
            return list(
                s.scalars(
                    sa.select(Alert)
                    .where(Alert.case_id == case.id, Alert.kind == AlertKind.HEARING_DUE)
                    .order_by(Alert.created_at)
                    .execution_options(populate_existing=True)
                ).all()
            )

        (around,) = hearing_alerts()
        assert around.title.startswith("Hearing around ") and around.data["approximate"] is True
        # the court gives another date
        case.next_hearing_date = h.days(5)
        s.flush()
        next_hearing.refresh(s, [case.id])
        rows = [
            r
            for r in calendar.hearing_rows(
                s, from_=h.days(0), to=h.days(30), case_condition=calendar.owned_case_condition()
            )
            if r.case_id == case.id
        ]
        assert [(r.date, r.basis) for r in rows] == [(h.days(5), "court")]
        alerts.sweep_dates(s, now=now)
        by_date = {a.data["hearing_date"]: a for a in hearing_alerts()}
        old, court = by_date[str(h.days(6))], by_date[str(h.days(5))]
        assert old.status == AlertStatus.EXPIRED and old.data["closed_reason"] == "date_changed"
        assert court.status == AlertStatus.OPEN and court.data["hearing_date"] == str(h.days(5))
        assert court.title.startswith("Hearing on ")
        s.rollback()


def test_the_court_date_and_a_different_exact_order_date_give_one_row(world):
    from aslms.services import calendar

    with world.Session() as s:
        case = h.claimed(s, world, next_hearing=h.days(12))
        h.order_with_text(s, case, f"List this matter on {h.dmy(h.days(10))}.", order_date=h.days(-1))
        h.read(s)
        rows = [
            r
            for r in calendar.hearing_rows(
                s, from_=h.days(0), to=h.days(30), case_condition=calendar.owned_case_condition()
            )
            if r.case_id == case.id
        ]
        assert [(r.date, r.source) for r in rows] == [(h.days(12), "current_status")]
        s.rollback()


def test_hearing_refresh_command_dry_run_case_and_all(world, monkeypatch):
    """`aslms next-dates hearing-refresh`: the dry run writes nothing; --case and --all write, audit with counts; a
    second --all changes nothing; no option is refused."""
    from contextlib import contextmanager

    from typer.testing import CliRunner

    from aslms.cli import next_dates as cli
    from aslms.cli.main import app

    @contextmanager
    def _scope():
        with world.Session() as s:
            try:
                yield s
                s.commit()
            except Exception:
                s.rollback()
                raise

    with world.Session() as s:
        case = make_case(s)
        case.next_hearing_date = h.days(20)
        s.flush()
        ref, cid = case.ref_no, case.id
        s.commit()
    monkeypatch.setattr(cli, "session_scope", _scope)
    runner = CliRunner()
    assert runner.invoke(app, ["next-dates", "hearing-refresh"]).exit_code != 0
    dry = runner.invoke(app, ["next-dates", "hearing-refresh", "--case", ref, "--dry-run"])
    assert dry.exit_code == 0, dry.output
    with world.Session() as s:
        case = s.get(Case, cid)
        assert case.next_hearing_on is None
        assert not s.scalar(sa.select(AuditLog).where(AuditLog.action == "next_dates.hearing_refresh"))
    one = runner.invoke(app, ["next-dates", "hearing-refresh", "--case", ref])
    assert one.exit_code == 0, one.output
    with world.Session() as s:
        case = s.get(Case, cid)
        assert (case.next_hearing_on, case.next_hearing_basis) == (h.days(20), NextHearingBasis.COURT)
        assert (
            s.scalar(
                sa.select(sa.func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "next_dates.hearing_refresh")
            )
            == 1
        )
    assert runner.invoke(app, ["next-dates", "hearing-refresh", "--all"]).exit_code == 0
    with world.Session() as s:
        case = s.get(Case, cid)
        assert case.next_hearing_on == h.days(20)
    assert runner.invoke(app, ["next-dates", "hearing-refresh", "--case", "NOSUCH/CASE"]).exit_code != 0
