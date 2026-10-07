"""Workflow alerts (design custody-workflow, decisions 23, 24a): a send alerts the new holder only; a recall alerts
the previous holder; a due date within the window is `high` and an overdue one `critical`, to the holder and the
owning department's `custody.track` holders; the alert closes when the leg changes; no remark or note text in
the alert; no `request_due` alert."""

from __future__ import annotations

from datetime import timedelta

import pytest

from aslms.domain.alerts import AlertStatus
from aslms.domain.cases import Case
from aslms.domain.reference import AlertKind
from aslms.services import alerts
from tests.db import alerts_support as h
from tests.db import workflow_support as w

REMARK = "confidential remark about the file"


@pytest.fixture()
def wide(world):
    return w.widen(world)


def _workflow(s, case_id, event=None):
    rows = [a for a in h.alerts_of(s, kind=AlertKind.WORKFLOW) if a.case_id == case_id]
    return [a for a in rows if event is None or a.data.get("event") == event]


def test_send_alerts_the_new_holder_only_and_recall_the_previous(wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        w.send(s, wide, "edu_off1", case, "health_off", remark=REMARK, due_date=w.in_days(30))
        w.note(s, wide, "health_off", case, body="secret note body")
        s.commit()
        case_id = case.id
    with wide.Session() as s:
        alerts.scan_events(s, now=h.now_utc())
        s.commit()
        received = _workflow(s, case_id, "file_received")
        assert len(received) == 1
        assert h.recipient_emails(s, received[0]) == {w.email_of("health_off")}
        assert received[0].office_id == wide.offices["HEALTH"].id
        assert received[0].severity.value == "normal"
        text = received[0].title + received[0].body
        assert REMARK not in text and "secret note body" not in text
        assert "EDU" in received[0].title
    with wide.Session() as s:
        w.recall(s, wide, "edu_admin", s.get(Case, case_id), remark=REMARK)
        s.commit()
    with wide.Session() as s:
        alerts.scan_events(s, now=h.now_utc() + timedelta(minutes=5))
        s.commit()
        recalled = _workflow(s, case_id, "file_recalled")
        assert len(recalled) == 1
        assert h.recipient_emails(s, recalled[0]) == {w.email_of("health_off")}
        assert REMARK not in recalled[0].title + recalled[0].body
        # the recaller is not alerted about their own recall
        assert len(_workflow(s, case_id, "file_received")) == 1
        assert not h.alerts_of(s, kind=AlertKind.REQUEST_DUE)


def test_due_soon_overdue_and_closed_when_the_leg_changes(wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        w.send(s, wide, "edu_off1", case, "health_off", remark=REMARK, due_date=w.in_days(1))
        s.commit()
        case_id = case.id
    now = h.now_utc()
    with wide.Session() as s:
        alerts.sweep_dates(s, now=now)
        s.commit()
        due = _workflow(s, case_id, "due")
        assert len(due) == 1 and due[0].severity.value == "high"
        emails = h.recipient_emails(s, due[0])
        # the holder and the owning department's custody.track holders (dept head and admin by default)
        assert emails == {w.email_of("health_off"), w.email_of("edu_admin"), w.email_of("edu_head")}
        assert due[0].dedupe_key.startswith("workflow_due:")
        assert REMARK not in due[0].title + due[0].body
    with wide.Session() as s:
        alerts.sweep_dates(s, now=now + timedelta(days=3))
        s.commit()
        due = _workflow(s, case_id, "due")
        assert len(due) == 1 and due[0].severity.value == "critical"
        assert "overdue" in due[0].title.lower()
    with wide.Session() as s:
        w.send(s, wide, "health_off", s.get(Case, case_id), "fin_off", remark="onwards")
        s.commit()
    with wide.Session() as s:
        alerts.sweep_dates(s, now=now + timedelta(days=3, minutes=5))
        s.commit()
        due = _workflow(s, case_id, "due")
        assert len(due) == 1 and AlertStatus(due[0].status) == AlertStatus.DONE
        assert due[0].data.get("closed_reason") == "leg_changed"
        assert not h.alerts_of(s, kind=AlertKind.REQUEST_DUE)


def test_no_alert_beyond_the_window(wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        w.send(s, wide, "edu_off1", case, "health_off", due_date=w.in_days(20))
        s.commit()
        case_id = case.id
    with wide.Session() as s:
        alerts.sweep_dates(s, now=h.now_utc())
        s.commit()
        assert not _workflow(s, case_id, "due")
