"""Shared helpers for the alert tests over `tests/db/world.py`: claims and allotments through the ownership
service, events written the way the pipeline writes them, custody and request rows, and readers of the
alerts and notifications a run produced."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aslms.domain.alerts import Alert, Notification
from aslms.domain.cases import Case
from aslms.domain.events import AuditLog, Event, EventVisibility
from aslms.domain.org import Channel, User
from aslms.domain.ownership import Recommendation, RecommendationOrigin, ScoreBand
from aslms.domain.reference import EventType, RequestKind
from aslms.domain.workflow import Custody, Request, RequestStatus
from aslms.services import ownership as own
from aslms.services.refno import allocate_ref_no


def now_utc() -> datetime:
    return datetime.now(UTC)


def claim(s: Session, world, key: str, case: Case, **kw):
    actor, user = world.actor(s, key)
    return own.claim(s, actor, user, case, **kw)


def allot(s: Session, world, key: str, case: Case, **kw):
    actor, user = world.actor(s, key)
    return own.allot(s, actor, user, case, **kw)


def recommend(s: Session, world, case: Case, code: str, *, score=0.95, band=ScoreBand.HIGH) -> Recommendation:
    rec = Recommendation(
        case_id=case.id,
        office_id=world.offices[code].id,
        score=score,
        band=band,
        origin=RecommendationOrigin.CAUSE_LIST,
        actor_name="matching",
    )
    s.add(rec)
    s.flush()
    return rec


def event(
    s: Session,
    case: Case | None,
    kind: EventType,
    payload: dict,
    *,
    actor_user_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
    scoped: bool = False,
) -> Event:
    ev = Event(
        case_id=case.id if case else None,
        type=kind,
        payload=json.loads(json.dumps(payload, default=str)),
        dedupe_key=f"test:{kind.value}:{uuid.uuid4()}",
        actor_user_id=actor_user_id,
        visibility=EventVisibility.SCOPED if scoped else EventVisibility.TRACKING_CARD,
    )
    if created_at is not None:
        ev.created_at = created_at
    s.add(ev)
    s.flush()
    return ev


def order_stored_event(s: Session, case: Case, *, order_no="1", order_date: date, document_id=None) -> Event:
    return event(
        s,
        case,
        EventType.ORDER_STORED,
        {"cnr": case.cnr, "order_no": order_no, "order_date": order_date, "document_id": document_id},
    )


def next_date_event(s: Session, case: Case, old: date | None, new: date | None) -> Event:
    return event(
        s,
        case,
        EventType.NEXT_DATE_CHANGED,
        {"cnr": case.cnr, "next_hearing_date": [str(old) if old else None, str(new) if new else None]},
    )


def custody_at(s: Session, case: Case, office, user: User | None = None) -> Custody:
    row = s.get(Custody, case.id)
    if row is None:
        row = Custody(case_id=case.id, holder_office_id=office.id)
        s.add(row)
    row.holder_office_id = office.id
    row.holder_user_id = user.id if user else None
    s.flush()
    return row


def request_to(
    s: Session,
    case: Case,
    *,
    from_office,
    to_office,
    to_user: User | None = None,
    due: date | None = None,
    status=RequestStatus.OPEN,
) -> Request:
    row = Request(
        case_id=case.id,
        kind=RequestKind.REPORT,
        from_office_id=from_office.id,
        to_office_id=to_office.id,
        to_user_id=to_user.id if to_user else None,
        subject="report please",
        due_date=due,
        status=status,
        ref_no=allocate_ref_no(s, from_office.code, "REQ"),
        actor_name="test",
    )
    s.add(row)
    s.flush()
    return row


def alerts_of(s: Session, case: Case | None = None, kind=None) -> list[Alert]:
    stmt = sa.select(Alert).order_by(Alert.created_at, Alert.ref_no)
    if case is not None:
        stmt = stmt.where(Alert.case_id == case.id)
    if kind is not None:
        stmt = stmt.where(Alert.kind == kind)
    return list(s.scalars(stmt).all())


def notifications_of(s: Session, alert: Alert, channel: Channel | None = None) -> list[Notification]:
    stmt = sa.select(Notification).where(Notification.alert_id == alert.id).order_by(Notification.created_at)
    if channel is not None:
        stmt = stmt.where(Notification.channel == channel)
    return list(s.scalars(stmt).all())


def recipient_emails(s: Session, alert: Alert, channel: Channel = Channel.IN_APP) -> set[str]:
    rows = notifications_of(s, alert, channel)
    users = {
        u.id: u.email for u in s.scalars(sa.select(User).where(User.id.in_({n.user_id for n in rows}))).all()
    }
    return {users[n.user_id] for n in rows}


def audit_actions(s: Session, entity_id) -> list[str]:
    return list(
        s.scalars(
            sa.select(AuditLog.action).where(AuditLog.entity_id == entity_id).order_by(AuditLog.created_at)
        ).all()
    )


def days(n: int) -> date:
    return date.today() + timedelta(days=n)
