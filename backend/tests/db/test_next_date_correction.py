"""A misread order (design `next-date-direct`, decisions 17 to 19, owner's answer 5): Report Wrong Next Date
(`next_dates.report_wrong`) tells the holders of Correct Misread Next Date (`next_dates.correct`, the Super
Administrator by default) who may see the case; Correct marks the reading wrong, with an optional right date entered
by hand; Reading Is Right keeps it. The court's own record is never changed; the seed carries both functions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from aslms.domain.alerts import Alert, AlertStatus, NextDate, NextDateSource, Notification, ReviewStatus
from aslms.domain.cases import Case
from aslms.domain.causelists import CauselistEntry
from aslms.domain.documents import Order
from aslms.domain.events import AuditLog, Event
from aslms.domain.org import PermissionEffect, RolePermission
from aslms.domain.reference import AlertKind, EventType, Permission, RefPermission, Role
from aslms.services import access, access_seed, alerts, next_dates
from aslms.services.seed import seed_all
from tests.db import docs_support as ds
from tests.db import next_dates_support as h
from tests.db import workflow_support as w
from tests.db.report_support import override

REASON = "The order says four weeks, not three; please check page 2."
PERIOD = "Heard. List the matter after 3 weeks."


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


def _read_case(s, world, text=PERIOD, **kw):
    off1 = world.user(s, "edu_off1")
    kw.setdefault("officer_user_id", off1.id)
    case = h.claimed(s, world, **kw)
    order = h.order_with_text(s, case, text, order_date=h.days(-2))
    h.read(s)
    (row,) = h.rows(s, case)
    return case, order, row


def _report_alerts(s, row):
    return list(
        s.scalars(
            sa.select(Alert)
            .where(
                Alert.kind == AlertKind.NEXT_DATE_REPORTED,
                sa.func.split_part(Alert.dedupe_key, ":", 2) == str(row.id),
            )
            .order_by(Alert.created_at, Alert.id)
            .execution_options(populate_existing=True)
        ).all()
    )


def _court_untouched(s, case_id, before):
    case = s.get(Case, case_id)
    s.refresh(case)
    assert case.next_hearing_date == before
    assert not s.scalar(
        sa.select(sa.func.count()).select_from(CauselistEntry).where(CauselistEntry.case_id == case_id)
    )


# ------------------------------------------------------------------------------------------------ report


def test_report_tells_the_correctors_who_may_see_the_case(api, world):
    with world.Session() as s:
        case, order, row = _read_case(s, world)
        override(
            s, world, "health_admin", Permission.NEXT_DATES_CORRECT, PermissionEffect.GRANT
        )  # cannot see it
        override(s, world, "edu_head", Permission.NEXT_DATES_CORRECT, PermissionEffect.GRANT)  # sees it
        s.commit()
    r = api.post(f"/next-dates/{row.id}/report", headers=w.login(api, "edu_off1"), json={"reason": REASON})
    assert r.status_code == 201, r.text
    assert r.json()["reported"] is True and r.json()["alert_ref_no"].startswith("ASLMS/GOA/ALR/")
    with world.Session() as s:
        (alert,) = _report_alerts(s, row)
        assert alert.status == AlertStatus.OPEN and alert.severity.value == "normal"
        assert alert.office_id == world.office(s, "EDU").id
        assert alert.data["reason"] == REASON and alert.data["reporter_office_code"] == "EDU"
        assert alert.data["next_date_id"] == str(row.id) and alert.data["order_id"] == str(order.id)
        assert alert.title.startswith("Next date reported as wrong:")
        notified = set(
            s.scalars(sa.select(Notification.user_id).where(Notification.alert_id == alert.id)).all()
        )
        assert world.user(s, "root").id in notified and world.user(s, "edu_head").id in notified
        assert world.user(s, "health_admin").id not in notified
        assert world.user(s, "edu_off1").id not in notified  # the reporter holds no correct function
        (audit,) = s.scalars(sa.select(AuditLog).where(AuditLog.action == "next_date.report_wrong")).all()
        assert audit.entity_id == row.id and audit.case_id == case.id
        assert REASON not in str(audit.after) and audit.after["reason"]["length"] == len(REASON)
        assert s.get(NextDate, row.id).review_status == ReviewStatus.NOT_NEEDED  # the date never changes
        _court_untouched(s, case.id, None)
    # every reader of the case sees "reported" (no name, no reason); only the recipients read the alert
    detail = api.get(f"/cases/{case.id}", headers=w.login(api, "edu_admin")).json()
    assert detail["next_hearing"]["reported_at"] is not None
    assert "reporter" not in str(detail["next_hearing"])
    ids = [
        a["id"]
        for a in api.get(f"/cases/{case.id}/alerts", headers=w.login(api, "edu_admin")).json()["items"]
    ]
    assert str(alert.id) not in ids
    root_alerts = api.get("/alerts", headers=w.login(api, "root")).json()["items"]
    assert any(a["id"] == str(alert.id) for a in root_alerts)
    # a second report waits for the correction
    r = api.post(f"/next-dates/{row.id}/report", headers=w.login(api, "edu_admin"), json={"reason": REASON})
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "already_reported")


def test_report_refusals(api, world):
    with world.Session() as s:
        case, order, row = _read_case(s, world)
        court_case = h.claimed(s, world, next_hearing=h.days(9))
        h.order_with_text(s, court_case, "Issue notice.", order_date=h.days(-1))
        h.read(s)
        manual = NextDate(
            ref_no=f"T/NXT/{uuid.uuid4().hex[:10]}",
            case_id=case.id,
            next_date=h.days(50),
            source=NextDateSource.MANUAL,
        )
        s.add(manual)
        override(s, world, "edu_off2", Permission.NEXT_DATES_REPORT_WRONG, PermissionEffect.DENY)
        s.commit()
    body = {"reason": REASON}
    for key in ("edu_off2", "edu_auditor", "oversight"):  # without the function
        r = api.post(f"/next-dates/{row.id}/report", headers=w.login(api, key), json=body)
        assert r.status_code == 403, key
    r = api.post(f"/next-dates/{row.id}/report", headers=w.login(api, "health_off"), json=body)
    assert r.status_code == 404  # the function, but not the case
    headers = w.login(api, "edu_off1")
    for short in ("too short", "x" * 301):
        r = api.post(f"/next-dates/{row.id}/report", headers=headers, json={"reason": short})
        assert r.status_code in (400, 422), short
    r = api.post(f"/next-dates/{manual.id}/report", headers=headers, json=body)
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "not_reportable")
    wf = api.get(f"/cases/{court_case.id}", headers=w.login(api, "edu_admin")).json()["workflow"]
    assert wf["next_date_report"] is False  # the court's record has no reading to report
    wf = api.get(f"/cases/{case.id}", headers=headers).json()["workflow"]
    assert (wf["next_date_report"], wf["next_date_correct"]) == (True, False)
    with world.Session() as s:
        assert not s.scalar(
            sa.select(sa.func.count()).select_from(AuditLog).where(AuditLog.action.like("next_date.%"))
        )


# ------------------------------------------------------------------------------------------------ correct


def test_correct_without_the_function_is_403_for_every_default_type(api, world):
    with world.Session() as s:
        _, _, row = _read_case(s, world)
        s.commit()
    for key in (
        "edu_head",
        "edu_admin",
        "edu_off1",
        "dse_user",
        "oversight",
        "central_op",
        "edu_auditor",
        "edu_counsel",
        "edu_reviewer",
    ):
        r = api.post(f"/next-dates/{row.id}/correct", headers=w.login(api, key), json={"reason": REASON})
        assert r.status_code == 403, key
        r = api.post(f"/next-dates/{row.id}/keep", headers=w.login(api, key), json={})
        assert r.status_code == 403, key


def test_correct_with_a_date(api, world):
    with world.Session() as s:
        case, order, row = _read_case(s, world)
        s.commit()
    api.post(f"/next-dates/{row.id}/report", headers=w.login(api, "edu_off1"), json={"reason": REASON})
    root = w.login(api, "root")
    assert api.get(f"/cases/{case.id}", headers=root).json()["workflow"]["next_date_correct"] is True
    r = api.post(
        f"/next-dates/{row.id}/correct", headers=root, json={"reason": REASON, "next_date": str(h.days(-1))}
    )
    assert r.status_code == 400  # the date is today or later
    r = api.post(
        f"/next-dates/{row.id}/correct", headers=root, json={"reason": REASON, "next_date": str(h.days(26))}
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["rejected"]["review_status"] == "rejected" and out["rejected"]["note"] == REASON
    assert out["rejected"]["reviewed_by"]["name"] and out["rejected"]["reviewed_at"]
    assert out["entered"]["source"] == "manual" and out["entered"]["order"]["id"] == str(order.id)
    assert out["entered"]["ref_no"].startswith("ASLMS/GOA/NXT/")
    assert out["next_hearing"]["date"] == str(h.days(26)) and out["next_hearing"]["basis"] == "manual"
    # the header and the Case Inbox read it at once
    off1 = w.login(api, "edu_off1")
    assert api.get(f"/cases/{case.id}", headers=off1).json()["next_hearing"]["basis"] == "manual"
    items = api.get("/inbox/mine", headers=off1, params={"view": "working"}).json()["items"]
    (mine,) = [i for i in items if i["case"]["id"] == str(case.id)]
    assert mine["case"]["next_hearing"]["date"] == str(h.days(26))
    with world.Session() as s:
        o = s.get(Order, order.id)
        assert (o.next_date_rule, o.next_date_found) == ("list_after_period", row.next_date)  # never changed
        assert "List the matter after 3 weeks" in o.next_date_phrase
        (alert,) = _report_alerts(s, row)
        assert alert.status == AlertStatus.DONE and alert.data["closed_reason"] == "corrected"
        (audit,) = s.scalars(sa.select(AuditLog).where(AuditLog.action == "next_date.correct")).all()
        assert audit.before["review_status"] == "not_needed" and audit.after["review_status"] == "rejected"
        assert "List the matter after 3 weeks" in audit.before["phrase"]
        assert REASON not in str(audit.after) and audit.after["entered_ref_no"] == out["entered"]["ref_no"]
        (ev,) = s.scalars(
            sa.select(Event).where(Event.case_id == case.id, Event.type == EventType.NEXT_DATE_REVIEWED)
        ).all()
        assert ev.payload["action"] == "corrected"
        _court_untouched(s, case.id, None)
    # a corrected date is a manual date: a holder of next_dates.review may enter a different one (owner check J)
    r = api.post(
        f"/cases/{case.id}/next-dates", headers=w.login(api, "edu_admin"), json={"next_date": str(h.days(27))}
    )
    assert r.status_code == 201, r.text
    # keep with no report open
    r = api.post(f"/next-dates/{row.id}/keep", headers=root, json={})
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "not_reported")


def test_correct_without_a_date_asks_for_one_and_a_matrix_type_may_correct(api, world):
    with world.Session() as s:
        case, order, row = _read_case(s, world)
        s.execute(
            sa.update(RolePermission)
            .where(
                RolePermission.role == Role.DEPT_HEAD,
                RolePermission.permission == Permission.NEXT_DATES_CORRECT,
            )
            .values(is_enabled=True)
        )
        s.commit()
    r = api.post(f"/next-dates/{row.id}/correct", headers=w.login(api, "edu_head"), json={"reason": REASON})
    assert r.status_code == 200, r.text
    assert r.json()["entered"] is None and r.json()["next_hearing"] is None
    with world.Session() as s:
        _, admin = world.actor(s, "edu_admin")
        items = next_dates.review_items(s, admin).items
        assert [(i["id"], i["reason"]) for i in items] == [(order.id, "marked_wrong")]
        assert (
            s.scalar(sa.select(AuditLog.actor_office_code).where(AuditLog.action == "next_date.correct"))
            == "EDU"
        )
    # the reading is gone: nothing left to correct
    r = api.post(f"/next-dates/{row.id}/correct", headers=w.login(api, "root"), json={"reason": REASON})
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "not_order_reading")


def test_correct_on_a_case_the_court_has_listed_changes_only_the_order_tier(api, world):
    with world.Session() as s:
        case, order, row = _read_case(
            s, world, text=f"List this matter on {h.dmy(h.days(10))}.", next_hearing=h.days(12)
        )
        s.refresh(case)
        assert (case.next_hearing_on, case.next_hearing_differs_on) == (h.days(12), h.days(10))
        s.commit()
    r = api.post(
        f"/next-dates/{row.id}/correct",
        headers=w.login(api, "root"),
        json={"reason": REASON, "next_date": str(h.days(12))},
    )
    assert r.status_code == 200, r.text
    nh = r.json()["next_hearing"]
    assert (nh["date"], nh["basis"], nh["differs"]) == (str(h.days(12)), "court", None)
    with world.Session() as s:
        entered = s.get(NextDate, uuid.UUID(r.json()["entered"]["id"]))
        assert entered.review_status == ReviewStatus.SUPERSEDED  # the court's record outranks it at once
        _court_untouched(s, case.id, h.days(12))


def test_keep_closes_the_report(api, world):
    with world.Session() as s:
        case, order, row = _read_case(s, world)
        s.commit()
    api.post(f"/next-dates/{row.id}/report", headers=w.login(api, "edu_off1"), json={"reason": REASON})
    r = api.post(
        f"/next-dates/{row.id}/keep", headers=w.login(api, "root"), json={"note": "the order says three"}
    )
    assert r.status_code == 200 and r.json() == {"kept": True}
    with world.Session() as s:
        (alert,) = _report_alerts(s, row)
        assert alert.status == AlertStatus.DONE and alert.data["closed_reason"] == "kept"
        (audit,) = s.scalars(sa.select(AuditLog).where(AuditLog.action == "next_date.report_kept")).all()
        assert "the order says three" not in str(audit.after)
        assert s.get(NextDate, row.id).review_status == ReviewStatus.NOT_NEEDED
    assert api.post(f"/next-dates/{row.id}/keep", headers=w.login(api, "root"), json={}).status_code == 409


def test_a_report_after_a_closed_one_raises_a_new_alert(api, world):
    """Review finding: `alerts.dedupe_key` is unique across every status, so a second report on the same reading
    after Reading Is Right must take a new key and reach the correctors again (decision 17, Deviation 16)."""
    with world.Session() as s:
        case, order, row = _read_case(s, world)
        s.commit()
    api.post(f"/next-dates/{row.id}/report", headers=w.login(api, "edu_off1"), json={"reason": REASON})
    api.post(f"/next-dates/{row.id}/keep", headers=w.login(api, "root"), json={})
    again = "Page 3 says four weeks; the reading still looks wrong to me."
    r = api.post(f"/next-dates/{row.id}/report", headers=w.login(api, "edu_admin"), json={"reason": again})
    assert r.status_code == 201, r.text
    with world.Session() as s:
        first, second = _report_alerts(s, row)
        assert first.status == AlertStatus.DONE and second.status == AlertStatus.OPEN
        assert second.dedupe_key == f"next_date_reported:{row.id}:2"
        assert r.json()["alert_ref_no"] == second.ref_no != first.ref_no
        assert second.data["reason"] == again
        notified = set(
            s.scalars(sa.select(Notification.user_id).where(Notification.alert_id == second.id)).all()
        )
        assert world.user(s, "root").id in notified
    detail = api.get(f"/cases/{case.id}", headers=w.login(api, "edu_admin")).json()
    assert detail["next_hearing"]["reported_at"] is not None
    r = api.post(f"/next-dates/{row.id}/report", headers=w.login(api, "edu_off1"), json={"reason": REASON})
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "already_reported")
    # Reading Is Right finds the numbered alert too
    assert api.post(f"/next-dates/{row.id}/keep", headers=w.login(api, "root"), json={}).status_code == 200
    with world.Session() as s:
        assert {a.status for a in _report_alerts(s, row)} == {AlertStatus.DONE}


def test_the_sweep_closes_a_report_after_a_newer_order(world):
    with world.Session() as s:
        case, order, row = _read_case(s, world)
        actor, off1 = world.actor(s, "edu_off1")
        next_dates.report_wrong(s, actor, off1, row.id, reason=REASON)
        h.order_with_text(s, case, "List the matter after 2 weeks.", order_date=h.days(-1))
        h.read(s)
        c = alerts.sweep_dates(s, now=datetime.now(UTC))
        assert c["closed_next_date_report"] == 1
        (alert,) = _report_alerts(s, row)
        assert alert.status == AlertStatus.EXPIRED and alert.data["closed_reason"] == "no_longer_used"
        s.rollback()


# ------------------------------------------------------------------------------------------------ the seed


def test_the_seed_carries_both_functions(world):
    with world.Session() as s:
        labels = {
            r.code: (r.label, r.description, r.module)
            for r in s.scalars(sa.select(RefPermission).where(RefPermission.code.like("next_dates.%"))).all()
        }
        assert labels["next_dates.report_wrong"][0] == "Report Wrong Next Date"
        assert labels["next_dates.correct"] == (
            "Correct Misread Next Date",
            "Mark a next date read from an order as wrong and enter the right date if the order shows it. "
            "Court records never change.",
            "next_dates",
        )
        assert labels["next_dates.review"][:2] == (
            "Enter Next Dates",
            "Enter the next date when the court's order gives none.",
        )
        enabled = {
            (r.role.value if hasattr(r.role, "value") else r.role): r.is_enabled
            for r in s.scalars(
                sa.select(RolePermission).where(
                    RolePermission.permission == Permission.NEXT_DATES_REPORT_WRONG
                )
            ).all()
        }
        assert {k for k, v in enabled.items() if v} == {
            "dept_head",
            "dept_admin",
            "dept_officer",
            "directorate_user",
        }
        correct = s.scalars(
            sa.select(RolePermission.is_enabled).where(
                RolePermission.permission == Permission.NEXT_DATES_CORRECT
            )
        ).all()
        assert correct and not any(correct)
        assert access.has(s, world.user(s, "root"), Permission.NEXT_DATES_CORRECT)
        group = access_seed.permission_group(Permission.NEXT_DATES_CORRECT)
        assert group[:2] == ("alerts", "Alerts")
        assert access_seed.permission_group(Permission.NEXT_DATES_REPORT_WRONG)[2] == 3
        before = s.scalar(sa.select(sa.func.count()).select_from(RolePermission))
        report = seed_all(s)
        assert s.scalar(sa.select(sa.func.count()).select_from(RolePermission)) == before
        assert not report.inserted.get("ref_permission_relabelled")
        s.rollback()


def test_overrides_and_delegation(world):
    with world.Session() as s:
        override(s, world, "edu_off1", Permission.NEXT_DATES_REPORT_WRONG, PermissionEffect.DENY)
        assert not access.has(s, world.user(s, "edu_off1"), Permission.NEXT_DATES_REPORT_WRONG)
        override(s, world, "edu_off1", Permission.NEXT_DATES_CORRECT, PermissionEffect.GRANT)
        assert access.has(s, world.user(s, "edu_off1"), Permission.NEXT_DATES_CORRECT)
        # the department admin cannot give a function they do not hold
        actor, admin = world.actor(s, "edu_admin")
        with pytest.raises(access.Forbidden, match="do not hold"):
            access.set_override(
                s,
                actor,
                admin,
                world.membership(s, "edu_off2"),
                Permission.NEXT_DATES_CORRECT,
                PermissionEffect.GRANT,
            )
        s.rollback()
