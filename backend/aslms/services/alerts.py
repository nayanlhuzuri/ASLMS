"""Alerts, recipients and notification delivery (plan §5.5, §5.12).

Alerts raised (idempotent via dedupe_key):
  hearing             tracked case listed / next hearing within 7 days; critical within 48 h, high this week
  next_date           a next date from an order needs manual review (period or unclear direction)
  order_received      a new order for a tracked case
  unclaimed_followup  an unclaimed case listed within 7 days (central operator)
  data_health         open source failures (central operator)
Recipients: the allotted officer, users of the allotted unit, and the admins/heads of every owning or watching
department (Phase 2 adds the custody holder). Delivery: in-app always; e-mail unless the user chose the daily
digest; SMS only for critical alerts and only once the gateway is configured (Phase 2)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from aslms.core.config import get_settings
from aslms.core.logging import get_logger
from aslms.core.time import IST, now_utc, today_ist
from aslms.domain.alerts import (
    Alert,
    AlertKind,
    AlertStatus,
    Digest,
    NextDate,
    Notification,
    NotificationStatus,
    ReviewStatus,
    Severity,
)
from aslms.domain.cases import Case, CaseStatus
from aslms.domain.documents import Order
from aslms.domain.events import EventType
from aslms.domain.ops import SourceFailure
from aslms.domain.org import Channel, DigestMode, Office, Role, User, UserNotificationPreference
from aslms.domain.ownership import CaseOwnership, OwnershipStatus
from aslms.integration.email import get_mailer
from aslms.integration.sms import get_sms
from aslms.services import events

log = get_logger(__name__)
HEARING_TIME = time(10, 30)
DEPT_ALERT_ROLES = (Role.DEPT_ADMIN, Role.DEPT_HEAD)


def severity_for(due: date, today: date) -> Severity:
    days = (due - today).days
    if days <= 2:
        return Severity.CRITICAL
    if days <= 7:
        return Severity.HIGH
    return Severity.NORMAL


def _due(d: date) -> datetime:
    return datetime.combine(d, HEARING_TIME, tzinfo=IST)


def _upsert_alert(
    session: Session,
    *,
    dedupe_key: str,
    kind: AlertKind,
    case_id: uuid.UUID | None,
    title: str,
    body: str | None,
    due_at: datetime | None,
    severity: Severity,
) -> uuid.UUID | None:
    stmt = (
        insert(Alert)
        .values(
            dedupe_key=dedupe_key,
            kind=kind,
            case_id=case_id,
            title=title[:300],
            body=body,
            due_at=due_at,
            severity=severity,
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(Alert.id)
    )
    aid = session.execute(stmt).scalar_one_or_none()
    if aid is None:
        # already raised: keep severity current as the date approaches
        a = session.scalar(select(Alert).where(Alert.dedupe_key == dedupe_key))
        if a and a.status == AlertStatus.OPEN and a.severity != severity:
            a.severity = severity
        return None
    events.emit(
        session,
        EventType.ALERT_RAISED,
        f"alert:{dedupe_key}",
        case_id=case_id,
        payload={"alert_id": str(aid), "kind": kind.value, "severity": severity.value, "title": title[:200]},
    )
    return aid


def _case_title(c: Case) -> str:
    return c.case_no_text or c.filing_no_text or c.cnr or "case"


def generate(session: Session, today: date | None = None) -> dict[str, int]:
    today = today or today_ist()
    horizon = today + timedelta(days=7)
    counts = {
        "hearing": 0,
        "next_date": 0,
        "order_received": 0,
        "unclaimed_followup": 0,
        "data_health": 0,
        "expired": 0,
    }
    new_ids: list[uuid.UUID] = []

    for c in session.scalars(
        select(Case).where(
            Case.is_tracked.is_(True),
            Case.status != CaseStatus.DISPOSED,
            Case.next_hearing_date.between(today, horizon),
        )
    ):
        sev = severity_for(c.next_hearing_date, today)
        aid = _upsert_alert(
            session,
            dedupe_key=f"hearing:{c.id}:{c.next_hearing_date}",
            kind=AlertKind.HEARING,
            case_id=c.id,
            title=f"{_case_title(c)} listed on {c.next_hearing_date:%d-%m-%Y}",
            body=f"{c.petitioner_summary or ''} vs {c.respondent_summary or ''}. Purpose: {c.next_purpose or '-'}",
            due_at=_due(c.next_hearing_date),
            severity=sev,
        )
        if aid:
            counts["hearing"] += 1
            new_ids.append(aid)

    for nd, c in session.execute(
        select(NextDate, Case)
        .join(Case, Case.id == NextDate.case_id)
        .where(
            NextDate.needs_review.is_(True),
            NextDate.review_status == ReviewStatus.PENDING,
            Case.is_tracked.is_(True),
        )
    ):
        aid = _upsert_alert(
            session,
            dedupe_key=f"review:{nd.id}",
            kind=AlertKind.NEXT_DATE,
            case_id=c.id,
            title=f"{_case_title(c)}: confirm the next date from the latest order",
            body=nd.note,
            due_at=_due(nd.next_date),
            severity=Severity.HIGH,
        )
        if aid:
            counts["next_date"] += 1
            new_ids.append(aid)

    since = now_utc() - timedelta(days=3)
    for o, c in session.execute(
        select(Order, Case)
        .join(Case, Case.id == Order.case_id)
        .where(Case.is_tracked.is_(True), Order.created_at >= since)
    ):
        aid = _upsert_alert(
            session,
            dedupe_key=f"order:{o.id}",
            kind=AlertKind.ORDER_RECEIVED,
            case_id=c.id,
            title=f"New {o.kind.value} order in {_case_title(c)} dated {o.order_date:%d-%m-%Y}",
            body=None,
            due_at=None,
            severity=Severity.NORMAL,
        )
        if aid:
            counts["order_received"] += 1
            new_ids.append(aid)

    owned = exists().where(
        and_(CaseOwnership.case_id == Case.id, CaseOwnership.status == OwnershipStatus.ACTIVE)
    )
    for c in session.scalars(
        select(Case).where(
            ~owned, Case.status != CaseStatus.DISPOSED, Case.next_hearing_date.between(today, horizon)
        )
    ):
        aid = _upsert_alert(
            session,
            dedupe_key=f"unclaimed:{c.id}:{c.next_hearing_date}",
            kind=AlertKind.UNCLAIMED_FOLLOWUP,
            case_id=c.id,
            title=f"Unclaimed case {_case_title(c)} listed on {c.next_hearing_date:%d-%m-%Y}",
            body=f"{c.petitioner_summary or ''} vs {c.respondent_summary or ''}",
            due_at=_due(c.next_hearing_date),
            severity=Severity.NORMAL,
        )
        if aid:
            counts["unclaimed_followup"] += 1

    open_failures = (
        session.scalar(
            select(func.count()).select_from(SourceFailure).where(SourceFailure.resolved_at.is_(None))
        )
        or 0
    )
    if open_failures:
        if _upsert_alert(
            session,
            dedupe_key=f"health:{today}",
            kind=AlertKind.DATA_HEALTH,
            case_id=None,
            title=f"{open_failures} data collection failure(s) need attention",
            body="See Administration → Data collection health.",
            due_at=None,
            severity=Severity.HIGH,
        ):
            counts["data_health"] += 1

    expired = session.execute(
        Alert.__table__.update()
        .where(Alert.status == AlertStatus.OPEN, Alert.due_at < now_utc() - timedelta(hours=12))
        .values(status=AlertStatus.EXPIRED)
    )
    counts["expired"] = expired.rowcount or 0
    session.flush()
    fan_out(session)
    return counts


# ------------------------------------------------------------------------------------------ recipients
def recipients_for_case(session: Session, case_id: uuid.UUID) -> list[User]:
    owns = session.scalars(
        select(CaseOwnership).where(
            CaseOwnership.case_id == case_id, CaseOwnership.status == OwnershipStatus.ACTIVE
        )
    ).all()
    users: dict[uuid.UUID, User] = {}
    for own in owns:
        dept = session.get(Office, own.office_id)
        for u in session.scalars(
            select(User)
            .join(Office, Office.id == User.office_id)
            .where(
                User.is_active.is_(True),
                User.role.in_(DEPT_ALERT_ROLES),
                or_(Office.path == dept.path, Office.path.like(dept.path + "/%")),
            )
        ):
            users[u.id] = u
        if own.officer_user_id:
            u = session.get(User, own.officer_user_id)
            if u and u.is_active:
                users[u.id] = u
        if own.unit_office_id:
            for u in session.scalars(
                select(User).where(User.office_id == own.unit_office_id, User.is_active.is_(True))
            ):
                users[u.id] = u
    return list(users.values())


def central_operators(session: Session) -> list[User]:
    return list(
        session.scalars(select(User).where(User.role == Role.CENTRAL_OPERATOR, User.is_active.is_(True)))
    )


def _prefs(session: Session, user_id: uuid.UUID) -> dict[Channel, UserNotificationPreference]:
    return {
        p.channel: p
        for p in session.scalars(
            select(UserNotificationPreference).where(UserNotificationPreference.user_id == user_id)
        )
    }


def fan_out(session: Session) -> int:
    """Creates notification rows for open alerts that have none yet."""
    n = 0
    has_notes = exists().where(Notification.alert_id == Alert.id)
    for a in session.scalars(select(Alert).where(Alert.status == AlertStatus.OPEN, ~has_notes)):
        if a.kind in (AlertKind.UNCLAIMED_FOLLOWUP, AlertKind.DATA_HEALTH):
            users = central_operators(session)
        else:
            users = recipients_for_case(session, a.case_id) if a.case_id else []
        for u in users:
            prefs = _prefs(session, u.id)
            channels = [Channel.IN_APP]
            email = prefs.get(Channel.EMAIL)
            if (email is None or (email.enabled and email.digest == DigestMode.NONE)) and not (
                email and email.critical_only and a.severity != Severity.CRITICAL
            ):
                channels.append(Channel.EMAIL)
            sms = prefs.get(Channel.SMS)
            if a.severity == Severity.CRITICAL and u.mobile and (sms is None or sms.enabled):
                channels.append(Channel.SMS)
            for ch in channels:
                session.execute(
                    insert(Notification)
                    .values(
                        alert_id=a.id,
                        user_id=u.id,
                        channel=ch,
                        title=a.title,
                        body=a.body,
                        status=NotificationStatus.SENT if ch == Channel.IN_APP else NotificationStatus.QUEUED,
                        sent_at=now_utc() if ch == Channel.IN_APP else None,
                        dedupe_key=f"{a.id}:{u.id}:{ch.value}",
                    )
                    .on_conflict_do_nothing(index_elements=["dedupe_key"])
                )
                n += 1
    return n


def deliver_pending(session: Session, limit: int = 500) -> dict[str, int]:
    counts = {"email_sent": 0, "sms_sent": 0, "failed": 0}
    mailer, sms = get_mailer(), get_sms()
    base = get_settings().public_base_url.rstrip("/")
    for n in session.scalars(
        select(Notification)
        .where(Notification.status == NotificationStatus.QUEUED)
        .order_by(Notification.created_at)
        .limit(limit)
    ):
        user = session.get(User, n.user_id)
        alert = session.get(Alert, n.alert_id) if n.alert_id else None
        link = f"{base}/cases/{alert.case_id}" if alert and alert.case_id else f"{base}/alerts"
        try:
            if n.channel == Channel.EMAIL:
                mailer.send(
                    to=user.email,
                    subject=f"[ASLMS] {n.title}",
                    body=f"{n.title}\n\n{n.body or ''}\n\nOpen: {link}\n",
                )
                counts["email_sent"] += 1
            elif n.channel == Channel.SMS:
                sms.send(to=user.mobile, text=f"ASLMS: {n.title}")
                counts["sms_sent"] += 1
            n.status, n.sent_at = NotificationStatus.SENT, now_utc()
        except Exception as e:  # noqa: BLE001 — a failed delivery is recorded on the row
            n.status, n.error = NotificationStatus.FAILED, str(e)[:500]
            counts["failed"] += 1
    return counts


def send_digests(session: Session, today: date | None = None) -> int:
    """Daily 08:00 digest for users who chose it: open alerts addressed to them."""
    today = today or today_ist()
    mailer = get_mailer()
    sent = 0
    for pref in session.scalars(
        select(UserNotificationPreference).where(
            UserNotificationPreference.channel == Channel.EMAIL,
            UserNotificationPreference.digest == DigestMode.DAILY,
            UserNotificationPreference.enabled.is_(True),
        )
    ):
        exists_ = session.scalar(
            select(Digest).where(Digest.user_id == pref.user_id, Digest.digest_date == today)
        )
        if exists_:
            continue
        user = session.get(User, pref.user_id)
        rows = (
            session.execute(
                select(Alert)
                .join(Notification, Notification.alert_id == Alert.id)
                .where(
                    Notification.user_id == user.id,
                    Notification.channel == Channel.IN_APP,
                    Alert.status == AlertStatus.OPEN,
                )
                .order_by(Alert.due_at.asc().nulls_last())
            )
            .scalars()
            .unique()
            .all()
        )
        if not rows:
            continue
        lines = [
            f"- [{a.severity.value}] {a.title}"
            + (f" (due {a.due_at.astimezone(IST):%d-%m-%Y})" if a.due_at else "")
            for a in rows
        ]
        mailer.send(
            to=user.email,
            subject=f"[ASLMS] Daily digest {today:%d-%m-%Y}: {len(rows)} item(s)",
            body="\n".join(lines),
        )
        session.add(
            Digest(user_id=user.id, digest_date=today, sent_at=now_utc(), alert_ids=[a.id for a in rows])
        )
        sent += 1
    return sent
