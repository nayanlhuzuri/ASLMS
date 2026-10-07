"""Notifications (design `alerts-notifications`, decisions 16–19): one in-app row per recipient (the in-app
list is the delivery), an e-mail row when the preferences ask for one at once, the sender job over the
e-mail outbox and the digests (`FOR UPDATE SKIP LOCKED`, attempts and backoff, the error text never holds a
secret), the daily digest built once per user per day, and the self-service preferences (in-app always on;
e-mail enabled / digest / critical-only; SMS refused until a gateway exists). A mail carries the alert
title, the case number, CNR, court, the date and a link — never note text or document names."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from aslms.domain.alerts import Alert, Digest, Notification, NotificationStatus, Severity
from aslms.domain.cases import Case
from aslms.domain.courts import Court
from aslms.domain.ops import JobRun, JobStatus
from aslms.domain.org import Channel, DigestMode, User, UserNotificationPreference
from aslms.domain.ownership import Recommendation, RecommendationStatus, ScoreBand
from aslms.domain.reference import AlertKind, RefAlertKind
from aslms.services import alert_rules as rules
from aslms.services import calendar, visibility
from aslms.services.audit import Actor, write_audit
from aslms.services.mailer import Mailer

log = logging.getLogger(__name__)

JOB_SEND = "notifications_send"
JOB_DIGESTS = "digests"
BACKOFF_MINUTES = (5, 30, 120)
DIGEST_HEARINGS_CAP = 50
DIGEST_LOOKAHEAD_DAYS = 7


def _now() -> datetime:
    return datetime.now(UTC)


def preference_rows(session: Session, user_id: uuid.UUID) -> list[UserNotificationPreference]:
    return list(
        session.scalars(
            select(UserNotificationPreference).where(UserNotificationPreference.user_id == user_id)
        ).all()
    )


def prefs_for(session: Session, user: User) -> rules.Prefs:
    return rules.effective_preferences(preference_rows(session, user.id))


# ------------------------------------------------------------------------------------------------ notify


def notify(
    session: Session, alert: Alert, users: list[User], severity: Severity, *, now: datetime | None = None
) -> int:
    """Decision 16: per recipient an in-app row (`sent` at once) and, when the preferences allow an
    immediate e-mail, an e-mail row (`queued`). Keys include the severity, so an upgrade notifies again and
    nothing else does. Returns the rows written."""
    now = now or _now()
    written = 0
    for user in users:
        prefs = prefs_for(session, user)
        channels: list[tuple[Channel, NotificationStatus]] = [(Channel.IN_APP, NotificationStatus.SENT)]
        if rules.immediate_email(prefs, severity):
            channels.append((Channel.EMAIL, NotificationStatus.QUEUED))
        for channel, status in channels:
            key = rules.notification_key(alert.id, user.id, channel, severity)
            if session.scalar(select(Notification.id).where(Notification.dedupe_key == key)) is not None:
                continue
            session.add(
                Notification(
                    alert_id=alert.id,
                    user_id=user.id,
                    channel=channel,
                    status=status,
                    severity=severity,
                    title=alert.title,
                    body=alert.body,
                    sent_at=now if channel == Channel.IN_APP else None,
                    next_attempt_at=now if channel == Channel.EMAIL else None,
                    dedupe_key=key,
                )
            )
            written += 1
    session.flush()
    return written


# ------------------------------------------------------------------------------------------------ sender


def _deliver(
    mailer: Mailer, row: Any, to: str, subject: str, text: str, *, now: datetime, max_attempts: int
) -> bool:
    row.attempts = int(row.attempts or 0) + 1
    try:
        mailer.send(to, subject, text)
    except Exception as exc:  # noqa: BLE001 — recorded on the row; the mailer scrubs its secrets
        row.status = NotificationStatus.FAILED
        row.error = f"{exc.__class__.__name__}: {exc}"[:2000]
        if row.attempts < max_attempts:
            minutes = BACKOFF_MINUTES[min(row.attempts - 1, len(BACKOFF_MINUTES) - 1)]
            row.next_attempt_at = now + timedelta(minutes=minutes)
        else:
            row.next_attempt_at = None
        return False
    row.status = NotificationStatus.SENT
    row.sent_at = now
    row.error = None
    row.next_attempt_at = None
    return True


def _due(model, now: datetime, max_attempts: int):
    return [
        model.status.in_([NotificationStatus.QUEUED, NotificationStatus.FAILED]),
        model.attempts < max_attempts,
        or_(model.next_attempt_at.is_(None), model.next_attempt_at <= now),
    ]


def send_pending(
    session: Session,
    mailer: Mailer,
    *,
    now: datetime | None = None,
    batch: int = 200,
    max_attempts: int = 3,
    portal_base_url: str = "http://localhost:3000",
    record_run: bool = True,
) -> dict[str, int]:
    """Queued and due-for-retry e-mail notifications and digests, one mail per row."""
    now = now or _now()
    counters = {"sent": 0, "failed": 0, "skipped": 0, "digests_sent": 0, "digests_failed": 0}
    run = None
    if record_run:
        run = JobRun(job=JOB_SEND, run_date=rules.today_ist(now), started_at=now)
        session.add(run)
        session.flush()
    rows = session.scalars(
        select(Notification)
        .where(Notification.channel == Channel.EMAIL, *_due(Notification, now, max_attempts))
        .order_by(Notification.next_attempt_at.nulls_first(), Notification.created_at)
        .limit(batch)
        .with_for_update(skip_locked=True)
    ).all()
    for n in rows:
        user = session.get(User, n.user_id)
        alert = session.get(Alert, n.alert_id)
        case = session.get(Case, alert.case_id) if alert is not None and alert.case_id is not None else None
        if alert is not None and case is None and AlertKind(alert.kind) == AlertKind.ADMIN_TICKET:
            if user is None or not user.is_active:
                n.status, n.error, n.attempts, n.next_attempt_at = (
                    NotificationStatus.FAILED,
                    "recipient no longer available",
                    max_attempts,
                    None,
                )
                counters["skipped"] += 1
                continue
            subject, text = rules.render_ticket_mail(alert, portal_base_url)
            ok = _deliver(mailer, n, user.email, subject, text, now=now, max_attempts=max_attempts)
            counters["sent" if ok else "failed"] += 1
            continue
        if user is None or not user.is_active or alert is None or case is None:
            n.status, n.error, n.attempts, n.next_attempt_at = (
                NotificationStatus.FAILED,
                "recipient or alert no longer available",
                max_attempts,
                None,
            )
            counters["skipped"] += 1
            continue
        court = session.get(Court, case.court_id)
        subject, text = rules.render_mail(
            alert, case, court.name if court else None, portal_base_url, case.ref_no.replace("/", "-")
        )
        ok = _deliver(mailer, n, user.email, subject, text, now=now, max_attempts=max_attempts)
        counters["sent" if ok else "failed"] += 1
    digests = session.scalars(
        select(Digest)
        .where(*_due(Digest, now, max_attempts))
        .order_by(Digest.next_attempt_at.nulls_first(), Digest.created_at)
        .limit(batch)
        .with_for_update(skip_locked=True)
    ).all()
    for d in digests:
        user = session.get(User, d.user_id)
        if user is None or not user.is_active or not d.body:
            d.status, d.error, d.attempts, d.next_attempt_at = (
                NotificationStatus.FAILED,
                "recipient no longer available",
                max_attempts,
                None,
            )
            counters["skipped"] += 1
            continue
        subject = f"ASLMS daily digest - {d.digest_date.strftime('%d %b %Y')}"
        ok = _deliver(mailer, d, user.email, subject, d.body, now=now, max_attempts=max_attempts)
        counters["digests_sent" if ok else "digests_failed"] += 1
    session.flush()
    if run is not None:
        run.counters = counters
        run.status = (
            JobStatus.PARTIAL if counters["failed"] or counters["digests_failed"] else JobStatus.SUCCEEDED
        )
        run.finished_at = _now()
    return counters


# ------------------------------------------------------------------------------------------------ digests


def _emailed_at_once():
    """An e-mail notification exists for the same alert, user and severity (so the in-app row was already
    told by mail)."""
    e = Notification.__table__.alias("e")
    return exists(
        select(1).where(
            e.c.alert_id == Notification.alert_id,
            e.c.user_id == Notification.user_id,
            e.c.severity == Notification.severity,
            e.c.channel == Channel.EMAIL.value,
        )
    )


def _notification_visible(session: Session, user: User):
    from aslms.services.alerts import notification_visible_condition

    return notification_visible_condition(session, user)


def build_digests(
    session: Session,
    *,
    today: date | None = None,
    now: datetime | None = None,
    portal_base_url: str = "http://localhost:3000",
    record_run: bool = True,
) -> dict[str, int]:
    """Decision 18: for each user whose preferences ask for the daily digest, the in-app notifications
    since the previous digest (or the last 24 hours) that were not e-mailed at once, grouped by kind, plus
    the hearings of the next seven days and the department's open possible matches. Nothing to say → no
    row. One row per (user, date): a second run adds nothing."""
    now = now or _now()
    today = today or rules.today_ist(now)
    counters = {"users": 0, "built": 0, "skipped_existing": 0, "skipped_empty": 0, "skipped_prefs": 0}
    run = None
    if record_run:
        run = JobRun(job=JOB_DIGESTS, run_date=today, started_at=now)
        session.add(run)
        session.flush()
    labels = {r.code: r.label for r in session.scalars(select(RefAlertKind)).all()}
    users = session.scalars(select(User).where(User.is_active.is_(True)).order_by(User.email)).all()
    for user in users:
        counters["users"] += 1
        if not rules.wants_digest(prefs_for(session, user)):
            counters["skipped_prefs"] += 1
            continue
        if (
            session.scalar(select(Digest.id).where(Digest.user_id == user.id, Digest.digest_date == today))
            is not None
        ):
            counters["skipped_existing"] += 1
            continue
        previous = session.scalar(
            select(func.max(Digest.created_at)).where(Digest.user_id == user.id, Digest.digest_date < today)
        )
        since = previous if previous is not None else now - timedelta(hours=24)
        rows = session.execute(
            select(Notification, Alert, Case)
            .join(Alert, Alert.id == Notification.alert_id)
            .join(Case, Case.id == Alert.case_id, isouter=True)
            .where(
                Notification.user_id == user.id,
                Notification.channel == Channel.IN_APP,
                Notification.created_at > since,
                ~_emailed_at_once(),
                _notification_visible(session, user),
            )
            .order_by(Alert.kind, Notification.created_at)
        ).all()
        groups: dict[str, list[dict[str, Any]]] = {}
        alert_ids: list[uuid.UUID] = []
        for n, a, c in rows:
            kind = a.kind.value if hasattr(a.kind, "value") else str(a.kind)
            if c is None:
                ref = rules.ticket_url_ref((a.data or {}).get("ticket_ref"))
                item = {
                    "title": n.title,
                    "case_ref": None,
                    "link": f"{portal_base_url.rstrip('/')}/admin/tickets/{ref}",
                }
            else:
                item = {"title": n.title, "case_ref": c.ref_no.replace("/", "-")}
            groups.setdefault(labels.get(kind, kind), []).append(item)
            alert_ids.append(a.id)
        hearings = calendar.calendar_for_user(
            session, user, from_=today, to=today + timedelta(days=DIGEST_LOOKAHEAD_DAYS), now=now
        )
        hearing_items = [
            {
                "date": h["date"],
                "case_label": h["case"]["case_no_text"] or h["case"]["cnr"] or h["case"]["ref_no"],
                "source": h["source"],
                "case_ref": h["case"]["ref_no"].replace("/", "-"),
            }
            for h in hearings[:DIGEST_HEARINGS_CAP]
        ]
        medium = None
        claim_depts = visibility.claim_departments(session, user)
        if claim_depts:
            medium = int(
                session.scalar(
                    select(func.count(Recommendation.id)).where(
                        Recommendation.office_id.in_([d.id for d in claim_depts]),
                        Recommendation.status == RecommendationStatus.RECOMMENDED,
                        Recommendation.band == ScoreBand.MEDIUM,
                    )
                )
                or 0
            )
        if not rows and not hearings and not medium:
            counters["skipped_empty"] += 1
            continue
        _subject, text = rules.render_digest(
            today, list(groups.items()), hearing_items, len(hearings), medium, portal_base_url
        )
        result = session.execute(
            insert(Digest)
            .values(
                user_id=user.id,
                digest_date=today,
                status=NotificationStatus.QUEUED,
                item_count=len(rows) + len(hearings),
                alert_ids=alert_ids,
                body=text,
                next_attempt_at=now,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "digest_date"])
        )
        if result.rowcount:
            counters["built"] += 1
        else:
            counters["skipped_existing"] += 1
    session.flush()
    if run is not None:
        run.counters = counters
        run.status = JobStatus.SUCCEEDED
        run.finished_at = _now()
    return counters


# ------------------------------------------------------------------------------------------------ preferences


class PreferenceError(ValueError):
    """A refused preference change (HTTP 422 with a code)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def get_preferences(session: Session, user: User) -> dict[str, Any]:
    p = prefs_for(session, user)
    return {
        "in_app": {"enabled": True},
        "email": {"enabled": p.email_enabled, "digest": p.digest.value, "critical_only": p.critical_only},
        "sms": {"available": False},
    }


def set_preferences(session: Session, actor: Actor, user: User, changes: dict[str, Any]) -> dict[str, Any]:
    """Decision 17: `in_app` cannot be switched off (422 `in_app_required`); `sms` is refused (422
    `channel_not_available`); the e-mail row is upserted; a change writes an audit row with before / after."""
    changes = changes or {}
    if changes.get("sms") is not None:
        raise PreferenceError("channel_not_available", "SMS notifications are not available yet")
    in_app = changes.get("in_app")
    if isinstance(in_app, dict) and in_app.get("enabled") is False:
        raise PreferenceError("in_app_required", "in-app notifications are always on")
    before = get_preferences(session, user)
    email = changes.get("email") or {}
    if not isinstance(email, dict):
        raise PreferenceError("invalid", "email must be an object")
    row = session.scalar(
        select(UserNotificationPreference).where(
            UserNotificationPreference.user_id == user.id,
            UserNotificationPreference.channel == Channel.EMAIL,
        )
    )
    if row is None:
        defaults = rules.Prefs()
        row = UserNotificationPreference(
            user_id=user.id,
            channel=Channel.EMAIL,
            enabled=defaults.email_enabled,
            digest=defaults.digest,
            critical_only=defaults.critical_only,
        )
        session.add(row)
    if "enabled" in email and email["enabled"] is not None:
        row.enabled = bool(email["enabled"])
    if "digest" in email and email["digest"] is not None:
        try:
            row.digest = DigestMode(str(email["digest"]).strip().lower())
        except ValueError as exc:
            raise PreferenceError("invalid", "digest is none or daily") from exc
    if "critical_only" in email and email["critical_only"] is not None:
        row.critical_only = bool(email["critical_only"])
    session.flush()
    after = get_preferences(session, user)
    if after != before:
        write_audit(
            session,
            actor,
            "notification_preferences.changed",
            "user_notification_preference",
            row.id,
            before=before,
            after=after,
        )
    return after
