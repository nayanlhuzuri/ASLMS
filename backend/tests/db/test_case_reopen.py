"""Reopening a closed case (design close-case, decisions 10-14 and 18): automatically when the court's status reads
pending again (a dossier or the Current Status batch; `unknown` never reopens; idempotent), by hand with a reason by
the owning department or the super admin, the reopen leg, note, event, audit row and the one department alert, a
second closure after a manual reopen, and a closed case found on a cause list queued for a court refresh."""

from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa

from aslms.domain.alerts import Alert
from aslms.domain.cases import CaseStatus
from aslms.domain.documents import Visibility
from aslms.domain.ops import FetchKind, FetchQueueItem
from aslms.domain.org import PermissionEffect
from aslms.domain.reference import AlertKind, EventType, NoteKind, Permission, Role
from aslms.domain.workflow import CaseNote, PendingAction
from aslms.services import alerts, case_closure, custody, queue, tracking, workflow_actions
from aslms.services.cases import apply_dossier, apply_status
from aslms.services.visibility import NotVisibleCase
from aslms.services.workflow_common import WorkflowError
from tests.db import alerts_support as h
from tests.db import closure_support as c
from tests.db import workflow_support as w
from tests.db.conftest import sample


@pytest.fixture()
def wide(world):
    return w.widen(world)


def _dossier(case, name: str = "cnr_pending.json") -> dict:
    data = sample(name)
    data["cino"] = case.cnr
    return data


def _status_block(case, pend: str = "P") -> dict:
    block = dict(sample("current_status_pending.json")["cases1"])
    block["cino"] = case.cnr
    block["pend_disp"] = pend
    return block


def _closed(s, world, key: str = "edu_off1"):
    case = c.disposed_case(s, world)
    c.close(s, world, key, case)
    return case


def _reopen_alerts(s, case, kind: AlertKind) -> list[Alert]:
    return [a for a in h.alerts_of(s, case, kind) if (a.data or {}).get("event") == "reopened"]


# ------------------------------------------------------------------------------------------------ automatic


def test_dossier_restoration_reopens(wide):
    with wide.Session() as s:
        case = _closed(s, wide)
        apply_dossier(s, case, _dossier(case))
        assert case.status == CaseStatus.PENDING
        [closure] = c.closures(s, case)
        assert closure.reopen_kind == "automatic" and closure.reopened_status == CaseStatus.PENDING
        assert closure.reopened_at is not None and closure.reopen_note_id is None
        assert closure.reopened_by_name is None
        leg = w.legs(s, case)[-1]
        assert leg.reason == "reopened" and leg.holder_office_code == "EDU" and leg.holder_user_id is None
        assert leg.pending_action == PendingAction.EXAMINE and leg.due_date is None
        assert leg.actor_name == "court status" and leg.actor_user_id is None
        assert closure.reopen_leg_id == leg.id
        [ev] = w.events(s, case.id, EventType.CASE_REOPENED)
        assert ev.payload["reopen_kind"] == "automatic" and ev.payload["status"] == ["disposed", "pending"]
        assert ev.actor_user_id is None
        [audit] = w.audits(s, "case.reopened", case.id)
        assert audit.actor_name == "court status" and audit.actor_user_id is None
        assert audit.entity_id == closure.id and audit.after["reopen_kind"] == "automatic"
        [restored] = w.events(s, case.id, EventType.STATUS_CHANGED)
        assert restored.payload["reopened"] is True
        assert not case_closure.is_closed(s, case)
        s.rollback()


def test_status_batch_reopens(wide):
    with wide.Session() as s:
        case = _closed(s, wide)
        report = apply_status(s, case, _status_block(case))
        tracking.record_status_change(s, case, report.status_changes)
        [closure] = c.closures(s, case)
        assert closure.reopen_kind == "automatic"
        ev = [e for e in w.events(s, case.id, EventType.STATUS_CHANGED) if "status" in e.payload][-1]
        assert ev.payload["reopened"] is True
        assert w.events(s, case.id, EventType.CASE_REOPENED)[0].payload["status"] == ["disposed", "pending"]
        s.rollback()


def test_unknown_does_not_reopen(wide):
    with wide.Session() as s:
        case = _closed(s, wide)
        report = apply_status(s, case, _status_block(case, pend="X"))
        tracking.record_status_change(s, case, report.status_changes)
        assert case.status == CaseStatus.UNKNOWN
        assert case_closure.is_closed(s, case)
        report = apply_status(s, case, _status_block(case))
        tracking.record_status_change(s, case, report.status_changes)
        assert not case_closure.is_closed(s, case)
        [ev] = w.events(s, case.id, EventType.CASE_REOPENED)
        assert ev.payload["status"] == ["unknown", "pending"]
        s.rollback()


def test_reopen_idempotent(wide):
    with wide.Session() as s:
        case = _closed(s, wide)
        apply_dossier(s, case, _dossier(case))
        assert case_closure.reopen_on_court_status(s, case) is None
        apply_dossier(s, case, _dossier(case))
        assert len(c.closures(s, case)) == 1
        assert len(w.events(s, case.id, EventType.CASE_REOPENED)) == 1
        assert [leg.reason for leg in w.legs(s, case)].count("reopened") == 1
        s.rollback()


def test_automatic_alert_once(wide):
    with wide.Session() as s:
        case = _closed(s, wide)
        s.commit()
        apply_dossier(s, case, _dossier(case))
        s.commit()
        counters = alerts.scan_events(s, config=alerts.AlertConfig())
        s.commit()
        [alert] = _reopen_alerts(s, case, AlertKind.STATUS_CHANGED)
        assert alert.data["reopened"] is True and alert.severity.value == "high"
        assert alert.title.startswith("Case reopened: ")
        assert "pending again" in alert.body and "with the department for action" in alert.body
        emails = h.recipient_emails(s, alert)
        assert {w.email_of("edu_admin"), w.email_of("edu_head"), w.email_of("edu_off1")} <= emails
        restorations = [
            a
            for a in h.alerts_of(s, case, AlertKind.STATUS_CHANGED)
            if (a.data or {}).get("previous_status") == "disposed"
            and (a.data or {}).get("event") != "reopened"
        ]
        assert restorations == [] and counters["skipped_reopened"] == 1
        # a restoration of an open case still raises its usual alert
        other = c.disposed_case(s, wide)
        other.cnr = "ASHC019999992025"
        s.commit()
        apply_dossier(s, other, _dossier(other))
        s.commit()
        alerts.scan_events(s, config=alerts.AlertConfig())
        s.commit()
        usual = [
            a
            for a in h.alerts_of(s, other, AlertKind.STATUS_CHANGED)
            if (a.data or {}).get("previous_status") == "disposed"
        ]
        assert len(usual) == 1 and usual[0].data.get("event") is None


# ------------------------------------------------------------------------------------------------ manual


def test_manual_reopen_by_head_and_admin(wide):
    with wide.Session() as s:
        for key in ("edu_head", "edu_admin"):
            case = _closed(s, wide)
            result = c.reopen(s, wide, key, case, reason=f"reopened by {key} for compliance")
            [closure] = c.closures(s, case)
            assert closure.reopen_kind == "manual" and closure.reopened_status == CaseStatus.DISPOSED
            assert (
                closure.reopened_by_user_id == w.uid(wide, key) and closure.reopened_by_office_code == "EDU"
            )
            assert closure.reopened_by_name == wide.users[key].full_name
            note = s.get(CaseNote, closure.reopen_note_id)
            assert note.kind == NoteKind.REOPENING and note.visibility == Visibility.CASE_SCOPE
            leg = w.legs(s, case)[-1]
            assert note.custody_leg_id == leg.id and leg.reason == "reopened"
            assert leg.actor_user_id == w.uid(wide, key) and leg.pending_action == PendingAction.EXAMINE
            assert result.note.id == note.id
            [ev] = w.events(s, case.id, EventType.CASE_REOPENED)
            assert ev.payload["reopen_kind"] == "manual" and ev.payload["note_ref_no"] == note.ref_no
            assert "for compliance" not in str(ev.payload)
            [audit] = w.audits(s, "case.reopened", case.id)
            assert audit.actor_user_id == w.uid(wide, key)
            assert audit.after["reason"]["length"] == len(f"reopened by {key} for compliance")
            assert "for compliance" not in str(audit.after)
            # the head sees it under "With My Offices" with Examine pending
            _, head = wide.actor(s, "edu_head")
            page = custody.held(s, head, scope="office")
            item = next(i for i in page.items if i["case"]["id"] == case.id)
            assert item["card"]["pending_action"] == "examine"
            # still disposed: the head may close it again
            assert workflow_actions.available(s, head, case)["close"] is True
        s.rollback()


def test_manual_reopen_super_admin_any_case(wide):
    with wide.Session() as s:
        case = _closed(s, wide)
        c.reopen(s, wide, "root", case)
        [closure] = c.closures(s, case)
        assert closure.reopen_kind == "manual" and closure.reopened_by_office_code == "GOA"
        s.rollback()


def test_manual_reopen_refusals(wide):
    with wide.Session() as s:
        open_case = c.disposed_case(s, wide)
        with pytest.raises(WorkflowError) as e:
            c.reopen(s, wide, "edu_head", open_case)
        assert e.value.code == "not_closed"
        case = _closed(s, wide)
        # the head of another department, who can open the case as a watcher
        c.add_login(s, wide, "health_head", Role.DEPT_HEAD, "HEALTH", "Commissioner")
        c.watch(s, wide, case, "HEALTH")
        with pytest.raises(WorkflowError) as e:
            c.reopen(s, wide, "health_head", case)
        assert e.value.code == "not_reopener"
        # a department officer of the owning department without the function
        with pytest.raises(WorkflowError) as e:
            c.reopen(s, wide, "edu_off1", case)
        assert e.value.code == "function_missing"
        with pytest.raises(WorkflowError) as e:
            c.reopen(s, wide, "edu_head", case, reason="no")
        assert e.value.code == "bad_field"
        with pytest.raises(NotVisibleCase):
            c.reopen(s, wide, "fin_off", case)
        assert c.closures(s, case)[0].reopened_at is None
        assert w.events(s, case.id, EventType.CASE_REOPENED) == []
        # a department officer given the function may reopen
        c.set_function(s, wide, "edu_off1", Permission.CASES_REOPEN, PermissionEffect.GRANT)
        c.reopen(s, wide, "edu_off1", case)
        assert c.closures(s, case)[0].reopen_kind == "manual"
        s.rollback()


def test_manual_reopen_alert(wide):
    with wide.Session() as s:
        case = _closed(s, wide)
        s.commit()
        c.reopen(s, wide, "edu_admin", case, reason="The order requires further compliance.")
        s.commit()
        counters = alerts.scan_events(s, config=alerts.AlertConfig())
        s.commit()
        [alert] = _reopen_alerts(s, case, AlertKind.WORKFLOW)
        assert alert.severity.value == "high" and alert.title.startswith("Case reopened: ")
        note = s.get(CaseNote, c.closures(s, case)[0].reopen_note_id)
        assert note.ref_no in alert.body and "Edu Admin" in alert.body
        assert "further compliance" not in alert.body
        emails = h.recipient_emails(s, alert)
        assert w.email_of("edu_admin") not in emails
        assert {w.email_of("edu_head"), w.email_of("edu_off1")} <= emails
        assert h.alerts_of(s, case, AlertKind.NEW_NOTE) and not [
            a for a in h.alerts_of(s, case, AlertKind.NEW_NOTE) if a.data.get("kind") == "reopening"
        ]
        assert counters["skipped_reopening_note"] == 1


def test_close_again_after_manual_reopen(wide):
    with wide.Session() as s:
        case = _closed(s, wide)
        c.reopen(s, wide, "edu_head", case)
        c.close(s, wide, "edu_head", case)
        rows = c.closures(s, case)
        assert len(rows) == 2 and rows[0].reopened_at is not None and rows[1].reopened_at is None
        assert rows[1].closed_as == "head"
        s.rollback()


def test_closed_case_listed_queues_refresh(wide):
    from aslms.domain.causelists import Causelist, ListSource, ListType
    from aslms.services.causelists import DayReport, apply_entries
    from tests.db.test_court_data_freshness import _entry, court_of, parsed

    with wide.Session() as s:
        case = _closed(s, wide)
        # a fetch of the case was done before (a closed case was always fetched): the listing revives it once
        queue.enqueue(s, FetchKind.DOSSIER, case.cnr, 50)
        s.execute(sa.update(FetchQueueItem).where(FetchQueueItem.ref == case.cnr).values(status="done"))
        other = c.disposed_case(s, wide)
        other_rows = [
            (r.id, r.status)
            for r in s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.ref == other.cnr)).all()
        ]
        court = court_of(s)
        day = date(2026, 11, 3)
        listing = Causelist(
            court_id=court.id, list_date=day, list_type=ListType.DAILY, source=ListSource.NAPIX
        )
        s.add(listing)
        s.flush()
        report = DayReport(list_date=day)
        apply_entries(
            s,
            court,
            listing,
            parsed(day, [_entry(1, case, court_no="3"), _entry(2, other, court_no="3")]),
            report=report,
        )
        rows = s.scalars(
            sa.select(FetchQueueItem).where(
                FetchQueueItem.kind == FetchKind.DOSSIER, FetchQueueItem.ref == case.cnr
            )
        ).all()
        assert len(rows) == 1 and rows[0].status.value == "pending"
        # an open case on the same list queues nothing (its claim's refresh row stays as it was)
        assert other_rows == [
            (r.id, r.status)
            for r in s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.ref == other.cnr)).all()
        ]
        assert report.queued == 1
        s.rollback()
