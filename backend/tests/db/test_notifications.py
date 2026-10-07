"""Notifications (design alerts-notifications, decisions 16–19): the preference rules on a raised alert, the
sender over the recording mailer and a failing one (attempts, backoff, final `failed`, no secret in the
error text), the daily digest (once per user per day, nothing new → no row, e-mailed alerts excluded,
hearings listed), and the preference service (defaults, changes, refusals, audit)."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
import sqlalchemy as sa

from aslms.domain.alerts import Digest, Notification, NotificationStatus, Severity
from aslms.domain.events import AuditLog
from aslms.domain.org import Channel, DigestMode, UserNotificationPreference
from aslms.domain.ownership import ScoreBand
from aslms.domain.reference import AlertKind
from aslms.services import alert_rules as rules
from aslms.services import alerts
from aslms.services import notifications as notif
from aslms.services.mailer import MailError, MailtrapApiMailer, RecordingMailer
from tests.db import alerts_support as h
from tests.db.world import make_case

NOW = h.now_utc()
TODAY = rules.today_ist(NOW)
TOKEN = "tok-very-secret-9f8e7d"


def d(n: int):
    return TODAY + timedelta(days=n)


def set_email_prefs(s, user, *, enabled=True, digest=DigestMode.DAILY, critical_only=False):
    row = s.scalar(
        sa.select(UserNotificationPreference).where(
            UserNotificationPreference.user_id == user.id,
            UserNotificationPreference.channel == Channel.EMAIL,
        )
    )
    if row is None:
        row = UserNotificationPreference(user_id=user.id, channel=Channel.EMAIL)
        s.add(row)
    row.enabled, row.digest, row.critical_only = enabled, digest, critical_only
    s.flush()
    return row


def raise_for(s, world, case, severity, key="k", day=3):
    """A hearing-style alert to the case's recipients at the given severity."""
    alert, changed = alerts.raise_alert(
        s,
        case=case,
        kind=AlertKind.HEARING_DUE,
        key=f"hearing_due:{case.id}:{key}",
        office=world.office(s, "EDU"),
        severity=severity,
        due_at=rules.hearing_due_at(d(day)),
        data={"hearing_date": d(day), "source": "current_status"},
        recipients=lambda: [world.user(s, "edu_off1")],
        now=NOW,
    )
    assert changed
    return alert


def channels(s, alert) -> list[tuple[str, str]]:
    return [(n.channel.value, n.status.value) for n in h.notifications_of(s, alert)]


# ------------------------------------------------------------------------------------------------ preferences on notify


def test_preferences_decide_the_immediate_email(world):
    with world.Session() as s:
        case = make_case(s)
        h.claim(s, world, "edu_admin", case, officer_user_id=world.users["edu_off1"].id)
        off1 = world.user(s, "edu_off1")
        # defaults: critical by mail at once, high in-app only (the digest carries it)
        assert channels(s, raise_for(s, world, case, Severity.CRITICAL, "a")) == [
            ("in_app", "sent"),
            ("email", "queued"),
        ]
        assert channels(s, raise_for(s, world, case, Severity.HIGH, "b")) == [("in_app", "sent")]
        set_email_prefs(s, off1, digest=DigestMode.NONE)
        assert channels(s, raise_for(s, world, case, Severity.NORMAL, "c")) == [
            ("in_app", "sent"),
            ("email", "queued"),
        ]
        set_email_prefs(s, off1, digest=DigestMode.NONE, critical_only=True)
        assert channels(s, raise_for(s, world, case, Severity.HIGH, "d")) == [("in_app", "sent")]
        assert channels(s, raise_for(s, world, case, Severity.CRITICAL, "e")) == [
            ("in_app", "sent"),
            ("email", "queued"),
        ]
        set_email_prefs(s, off1, enabled=False)
        assert channels(s, raise_for(s, world, case, Severity.CRITICAL, "f")) == [("in_app", "sent")]
        n = h.notifications_of(s, h.alerts_of(s, case)[0])[1]
        assert n.severity == Severity.CRITICAL and n.title and n.dedupe_key.startswith("n:")
        s.rollback()


# ------------------------------------------------------------------------------------------------ the sender


def test_sender_marks_sent_and_retries_with_backoff(world):
    with world.Session() as s:
        case = make_case(s)
        h.claim(s, world, "edu_admin", case, officer_user_id=world.users["edu_off1"].id)
        alert = raise_for(s, world, case, Severity.CRITICAL)
        s.commit()
        mailer = RecordingMailer()
        c = notif.send_pending(s, mailer, now=NOW, portal_base_url="http://portal")
        s.commit()
        assert c["sent"] == 1 and c["failed"] == 0 and len(mailer.sent) == 1
        mail = mailer.sent[0]
        assert mail.to == "off1.edu@example.org" and mail.subject.startswith("[ASLMS CRITICAL]")
        assert case.cnr in mail.text and f"http://portal/cases/{case.ref_no.replace('/', '-')}" in mail.text
        (email,) = h.notifications_of(s, alert, Channel.EMAIL)
        assert email.status == NotificationStatus.SENT and email.sent_at and email.attempts == 1
        assert notif.send_pending(s, mailer, now=NOW)["sent"] == 0  # nothing left
        # a failing mailer: attempts 1, 2, 3 with 5, 30, 120 minutes of backoff, then it stays failed
        case2 = make_case(s)
        h.claim(s, world, "edu_admin", case2, officer_user_id=world.users["edu_off1"].id)
        alert2 = raise_for(s, world, case2, Severity.CRITICAL)
        s.commit()
        broken = RecordingMailer(fail_with=MailError("ConnectError: gateway down"))
        (row,) = h.notifications_of(s, alert2, Channel.EMAIL)
        t = NOW
        for attempt, minutes in ((1, 5), (2, 30), (3, None)):
            c = notif.send_pending(s, broken, now=t)
            s.commit()
            s.refresh(row)
            assert c["failed"] == 1 and row.attempts == attempt and row.status == NotificationStatus.FAILED
            assert "gateway down" in row.error
            if minutes is None:
                assert row.next_attempt_at is None
            else:
                assert row.next_attempt_at == t + timedelta(minutes=minutes)
                # too early for the retry: not picked up
                assert notif.send_pending(s, broken, now=t + timedelta(minutes=minutes - 1))["failed"] == 0
                t = t + timedelta(minutes=minutes)
        assert notif.send_pending(s, broken, now=t + timedelta(days=1))["failed"] == 0
        assert s.scalar(sa.select(sa.func.count(Notification.id)).where(Notification.status == "failed")) == 1


def test_error_text_never_holds_the_token(world):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"boom {request.headers['authorization']}")

    mailer = MailtrapApiMailer(
        url="https://api.test/send",
        token=TOKEN,
        from_email="aslms@example.org",
        transport=httpx.MockTransport(handler),
    )
    with world.Session() as s:
        case = make_case(s)
        h.claim(s, world, "edu_admin", case, officer_user_id=world.users["edu_off1"].id)
        alert = raise_for(s, world, case, Severity.CRITICAL)
        s.commit()
        notif.send_pending(s, mailer, now=NOW)
        s.commit()
        (row,) = h.notifications_of(s, alert, Channel.EMAIL)
        assert row.status == NotificationStatus.FAILED and "500" in row.error and TOKEN not in row.error


# ------------------------------------------------------------------------------------------------ digests


def test_digest_built_once_per_user_per_day(world):
    with world.Session() as s:
        case = make_case(s, next_hearing=d(2))
        h.claim(s, world, "edu_admin", case, officer_user_id=world.users["edu_off1"].id)
        crit = raise_for(
            s, world, case, Severity.CRITICAL, "crit", day=1
        )  # e-mailed at once → not in the digest
        high = raise_for(s, world, case, Severity.HIGH, "high")
        s.commit()
        c = notif.build_digests(s, today=TODAY, now=NOW, portal_base_url="http://portal")
        s.commit()
        # off1 has new alerts and a hearing; the department admin has the hearing of an owned case and the
        # medium-band count is zero; users without cases get nothing
        assert c["built"] >= 1 and c["skipped_empty"] >= 1
        row = s.scalar(sa.select(Digest).where(Digest.user_id == world.users["edu_off1"].id))
        assert row is not None and row.status == NotificationStatus.QUEUED and row.digest_date == TODAY
        assert high.id in row.alert_ids and crit.id not in row.alert_ids
        assert high.title in row.body and crit.title not in row.body
        assert "Hearings today and in the next 7 days (1)" in row.body and case.case_no_text in row.body
        assert row.item_count == 2
        # a second run adds nothing
        c2 = notif.build_digests(s, today=TODAY, now=NOW + timedelta(minutes=5))
        s.commit()
        assert c2["built"] == 0 and c2["skipped_existing"] >= 1
        # the sender delivers it
        mailer = RecordingMailer()
        c3 = notif.send_pending(s, mailer, now=NOW + timedelta(minutes=6))
        s.commit()
        assert c3["digests_sent"] >= 1
        digest_mail = next(m for m in mailer.sent if m.to == "off1.edu@example.org" and "digest" in m.subject)
        assert high.title in digest_mail.text
        s.refresh(row)
        assert row.status == NotificationStatus.SENT and row.sent_at is not None


def test_digest_nothing_to_say_and_medium_count(world):
    with world.Session() as s:
        # no alerts, no hearings: nobody gets a digest
        c = notif.build_digests(s, today=TODAY, now=NOW, record_run=False)
        assert c["built"] == 0 and s.scalar(sa.select(sa.func.count(Digest.id))) == 0
        # a possible match in the department's inbox counts for the holders of cases.claim
        case = make_case(s)
        h.recommend(s, world, case, "EDU", score=0.6, band=ScoreBand.MEDIUM)
        s.flush()
        c = notif.build_digests(s, today=TODAY, now=NOW, record_run=False)
        rows = {str(r.user_id): r.body for r in s.scalars(sa.select(Digest)).all()}
        assert c["built"] == 2
        assert set(rows) == {str(world.users["edu_admin"].id), str(world.users["edu_head"].id)}
        assert "Possible matches awaiting a decision in your department's inbox: 1" in next(
            iter(rows.values())
        )
        s.rollback()


# ------------------------------------------------------------------------------------------------ preferences


def test_preferences_service(world):
    with world.Session() as s:
        actor, off1 = world.actor(s, "edu_off1")
        assert notif.get_preferences(s, off1) == {
            "in_app": {"enabled": True},
            "email": {"enabled": True, "digest": "daily", "critical_only": False},
            "sms": {"available": False},
        }
        with pytest.raises(notif.PreferenceError) as exc:
            notif.set_preferences(s, actor, off1, {"sms": {"enabled": True}})
        assert exc.value.code == "channel_not_available"
        with pytest.raises(notif.PreferenceError) as exc:
            notif.set_preferences(s, actor, off1, {"in_app": {"enabled": False}})
        assert exc.value.code == "in_app_required"
        with pytest.raises(notif.PreferenceError):
            notif.set_preferences(s, actor, off1, {"email": {"digest": "weekly"}})
        out = notif.set_preferences(s, actor, off1, {"email": {"digest": "none", "critical_only": True}})
        assert out["email"] == {"enabled": True, "digest": "none", "critical_only": True}
        audits = s.scalars(
            sa.select(AuditLog).where(AuditLog.action == "notification_preferences.changed")
        ).all()
        assert len(audits) == 1
        assert audits[0].before["email"]["digest"] == "daily" and audits[0].after["email"]["digest"] == "none"
        # the same values again: no second audit row
        notif.set_preferences(s, actor, off1, {"email": {"digest": "none"}})
        assert (
            s.scalar(
                sa.select(sa.func.count(AuditLog.id)).where(
                    AuditLog.action == "notification_preferences.changed"
                )
            )
            == 1
        )
        s.rollback()
