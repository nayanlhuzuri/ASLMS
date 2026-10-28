"""The owner's scenario (design `next-date-direct`, Tests): the next hearing decided by the court in its latest order is
visible directly in the case header and every list, with no confirmation; an old pending suggestion is shown at once
and retired by `aslms next-dates direct --apply`; where the court gave no date, an entered date shows at once."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from typer.testing import CliRunner

from aslms.domain.alerts import Alert, AlertStatus, NextDate, NextDateSource, ReviewStatus
from aslms.domain.events import AuditLog
from aslms.services import alerts, next_dates
from tests.db import docs_support as ds
from tests.db import next_dates_support as h
from tests.db import workflow_support as w


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


def _inbox_hearing(api, headers, case_id):
    r = api.get("/inbox/mine", headers=headers, params={"view": "working", "limit": 200})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    found = [i for i in items if i["case"]["id"] == str(case_id)]
    assert found, items
    return found[0]["case"]["next_hearing"]


def test_order_date_shows_in_header_and_inbox_without_confirm(api, world):
    with world.Session() as s:
        admin = world.user(s, "edu_admin")
        case = h.claimed(s, world, officer_user_id=admin.id)
        order = h.order_with_text(s, case, "Heard. List the matter after 3 weeks.", order_date=h.days(-4))
        h.read(s)
        s.commit()
    headers = w.login(api, "edu_admin")
    detail = api.get(f"/cases/{case.id}", headers=headers).json()
    nh = detail["next_hearing"]
    counted = str(h.days(-4) + __import__("datetime").timedelta(weeks=3))
    assert (nh["date"], nh["basis"], nh["approximate"]) == (counted, "around", True)
    assert nh["basis_words"] == "after 3 weeks" and nh["order"]["id"] == str(order.id)
    assert "List the matter after 3 weeks" in nh["phrase"] and nh["court_date"] is None
    assert detail["status"]["next_hearing_date"] is None  # the court's verbatim value is untouched
    assert (
        detail["workflow"]["next_dates"] is False
        and detail["workflow"]["next_dates_blocked"] == "court_date_fixed"
    )
    listed = _inbox_hearing(api, headers, case.id)
    assert {k: listed[k] for k in ("date", "basis", "approximate", "basis_words")} == {
        "date": counted,
        "basis": "around",
        "approximate": True,
        "basis_words": "after 3 weeks",
    }
    assert "phrase" not in listed  # the list form
    cal = api.get(
        "/me/calendar", headers=headers, params={"from": str(h.days(0)), "to": str(h.days(30))}
    ).json()
    (item,) = [i for i in cal["items"] if i["case"]["id"] == str(case.id)]
    assert (item["date"], item["basis"], item["approximate"]) == (counted, "around", True)


def _scope(world):
    @contextmanager
    def scope():
        s = world.Session()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    return scope


def test_legacy_pending_row_shown_and_retired(api, world, monkeypatch):
    with world.Session() as s:
        admin = world.user(s, "edu_admin")
        case = h.claimed(s, world, officer_user_id=admin.id)
        order = h.order_with_text(
            s, case, f"List the matter after {h.dmy(h.days(9))}.", order_date=h.days(-1)
        )
        h.read(s)
        (row,) = h.rows(s, case)
        # as written before migration 0034: a pending suggestion with its review alert
        s.execute(
            sa.update(NextDate)
            .where(NextDate.id == row.id)
            .values(review_status=ReviewStatus.PENDING, needs_review=True)
        )
        s.add(
            Alert(
                case_id=case.id,
                kind="next_date_review",
                office_id=world.office(s, "EDU").id,
                severity="normal",
                status=AlertStatus.OPEN,
                title="Next date to confirm",
                body="",
                data={"order_id": str(order.id), "next_date_id": str(row.id), "hearing_date": str(h.days(9))},
                dedupe_key=next_dates.review_alert_key(order.id),
                ref_no="ASLMS/GOA/ALR/2026/990001",
            )
        )
        s.commit()
    headers = w.login(api, "edu_admin")
    # decision 4 counts a pending row: the header and the inbox already show it
    assert api.get(f"/cases/{case.id}", headers=headers).json()["next_hearing"]["date"] == str(h.days(9))
    assert _inbox_hearing(api, headers, case.id)["date"] == str(h.days(9))
    from aslms.cli import next_dates as cli
    from aslms.cli.main import app

    monkeypatch.setattr(cli, "session_scope", _scope(world))  # this run's database, never the dev one
    runner = CliRunner()
    dry = runner.invoke(app, ["next-dates", "direct"])
    assert dry.exit_code == 0, dry.output
    assert "'pending_shown_directly': 1" in dry.output and "dry run" in dry.output
    with world.Session() as s:
        assert s.get(NextDate, row.id).review_status == ReviewStatus.PENDING  # the dry run wrote nothing
    first = runner.invoke(app, ["next-dates", "direct", "--apply"])
    assert first.exit_code == 0, first.output
    with world.Session() as s:
        got = s.get(NextDate, row.id)
        assert (got.review_status, got.needs_review, got.updated_by) == (ReviewStatus.NOT_NEEDED, False, None)
        alert = s.scalar(sa.select(Alert).where(Alert.dedupe_key == next_dates.review_alert_key(order.id)))
        assert alert.status == AlertStatus.DONE and alert.data["closed_reason"] == "shown_directly"
        (audit,) = s.scalars(sa.select(AuditLog).where(AuditLog.action == "next_dates.direct_apply")).all()
        assert audit.actor_name == "cli" and audit.after["pending_shown_directly"] == 1
    second = runner.invoke(app, ["next-dates", "direct", "--apply"])
    assert second.exit_code == 0 and "'pending_shown_directly': 0" in second.output
    with world.Session() as s:
        assert (
            s.scalar(
                sa.select(sa.func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "next_dates.direct_apply")
            )
            == 2
        )
        assert (
            s.scalar(
                sa.select(sa.func.count())
                .select_from(NextDate)
                .where(NextDate.review_status == ReviewStatus.PENDING)
            )
            == 0
        )


def test_enter_where_court_gave_none_updates_header_at_once(api, world):
    with world.Session() as s:
        admin = world.user(s, "edu_admin")
        case = h.claimed(s, world, officer_user_id=admin.id)
        order = h.order_with_text(
            s, case, "List the matter after the ensuing vacation.", order_date=h.days(-2)
        )
        h.read(s)
        alerts.scan_events(s)
        s.commit()
    headers = w.login(api, "edu_admin")
    detail = api.get(f"/cases/{case.id}", headers=headers).json()
    assert detail["next_hearing"] is None and detail["workflow"]["next_dates"] is True
    r = api.post(
        f"/cases/{case.id}/next-dates",
        headers=headers,
        json={"next_date": str(h.days(25)), "order": str(order.id)},
    )
    assert r.status_code == 201, r.text
    nh = api.get(f"/cases/{case.id}", headers=headers).json()["next_hearing"]
    assert (nh["date"], nh["basis"], nh["approximate"]) == (str(h.days(25)), "manual", False)
    listed = _inbox_hearing(api, headers, case.id)
    assert (listed["date"], listed["basis"]) == (str(h.days(25)), "manual")
    with world.Session() as s:
        got = s.get(type(s.get(NextDate, r.json()["id"])), r.json()["id"])
        assert got.source == NextDateSource.MANUAL
