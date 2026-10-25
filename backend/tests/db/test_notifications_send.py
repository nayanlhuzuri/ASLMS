"""The immediate mail re-checks visibility before sending (design alerts-visibility-roles, decision 6): a recipient who
lost sight of the case between the raise and the send gets no mail (the row is `failed`, "no longer visible to the
recipient", not retried); a notice whose recipient the design names regardless of case visibility is still mailed."""

from __future__ import annotations

from datetime import timedelta

from aslms.domain.alerts import NotificationStatus
from aslms.domain.org import Channel, DigestMode, PermissionEffect
from aslms.domain.reference import AlertKind, Permission
from aslms.services import access, alerts, visibility
from aslms.services import alert_rules as rules
from aslms.services import notifications as notif
from aslms.services.mailer import RecordingMailer
from tests.db import alerts_support as h
from tests.db import workflow_support as w
from tests.db.test_notifications import set_email_prefs
from tests.db.world import USERS

NOW = h.now_utc()


def test_mail_not_sent_when_recipient_lost_sight(world):
    w.widen(world)
    with world.Session() as s:
        case = w.claimed_case(s, world)
        case.next_hearing_date = rules.today_ist(NOW) + timedelta(days=1)
        s.commit()
        alerts.sweep_dates(s, now=NOW)
        s.commit()
        [alert] = h.alerts_of(s, case, AlertKind.HEARING_DUE)
        [mail_row] = h.notifications_of(s, alert, Channel.EMAIL)  # critical: queued at once for off1
        actor, root = world.actor(s, "root")
        access.set_override(
            s,
            actor,
            root,
            world.membership(s, "edu_off1"),
            Permission.CASES_VIEW_SCOPE,
            PermissionEffect.DENY,
        )
        s.commit()
        assert not visibility.can_view_case(s, world.user(s, "edu_off1"), case)
        mailer = RecordingMailer()
        counters = notif.send_pending(s, mailer, now=NOW + timedelta(minutes=1), max_attempts=3)
        s.commit()
        assert counters["skipped"] == 1 and counters["sent"] == 0
        assert [m for m in mailer.sent if m.to == USERS["edu_off1"][0]] == []
        s.refresh(mail_row)
        assert NotificationStatus(mail_row.status) == NotificationStatus.FAILED
        assert mail_row.error == "no longer visible to the recipient" and mail_row.attempts == 3
        assert notif.send_pending(s, mailer, now=NOW + timedelta(hours=3))["skipped"] == 0  # not retried


def test_named_recipient_notice_still_mailed(world):
    w.widen(world)
    with world.Session() as s:
        case = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", case, "fin_off")
        set_email_prefs(s, world.user(s, "fin_off"), digest=DigestMode.NONE)
        s.commit()
        w.recall(s, world, "edu_admin", case)
        s.commit()
        alerts.scan_events(s, now=h.now_utc())
        s.commit()
        assert not visibility.can_view_case(s, world.user(s, "fin_off"), case)
        recalled = [
            a for a in h.alerts_of(s, case, AlertKind.WORKFLOW) if a.data.get("event") == "file_recalled"
        ]
        assert recalled and h.notifications_of(s, recalled[0], Channel.EMAIL)
        mailer = RecordingMailer()
        notif.send_pending(s, mailer, now=h.now_utc() + timedelta(minutes=1))
        s.commit()
        assert [m for m in mailer.sent if m.to == w.email_of("fin_off") and "Case recalled" in m.subject]
