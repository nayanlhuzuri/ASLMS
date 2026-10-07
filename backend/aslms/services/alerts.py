"""Alerts (design `alerts-notifications`): two generators over one table, the alert life cycle, and the
reading side with the visibility rule applied in SQL.

- `scan_events` (decisions 1a, 2, 4, 5, 7–9, 12, 13): new `events` rows inside a time window (the previous
  succeeded run's start minus the overlap; the first run starts at "now − overlap", so history is never
  back-filled) become alerts — `next_date_changed`, `new_order`, `status_changed`, `recommendation`,
  `ownership`, `new_document`. Case alerts only for cases with an active owner or watcher (joined in SQL);
  only recent court dates alert (the running historical load raises nothing).
- `sweep_dates` (decisions 1b, 6, 10, 11, 15): hearing, compliance and request alerts from dates that come
  due, upgraded in place as they approach, and the closures (dates that left the case or passed, aged
  informational alerts, recommendations decided, requests answered, compliance expired).
- `raise_alert` is idempotent through `alerts.dedupe_key` (a number is allocated only for a new key); a
  higher severity notifies the recipients again. Every new alert emits one scoped `alert_raised` event.
- `acknowledge` / `mark_done` need `alerts.acknowledge` and a recipient or working relation; each writes an
  audit row. System closures write none (they are on the row: `closed_at`, `data.closed_reason`).
- `list_for_user`, `counts_for_user`, `get_for_user`, `alerts_for_case`, `mark_read`: the caller's own
  in-app notifications joined to alerts, filtered by `visibility.visible_case_condition` in SQL."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aslms.core.config import Settings
from aslms.domain.alerts import Alert, AlertStatus, Notification, NotificationStatus, Severity
from aslms.domain.cases import Case, CaseObjection, CaseStatus
from aslms.domain.documents import Order
from aslms.domain.events import Event
from aslms.domain.ops import JobRun, JobStatus
from aslms.domain.org import Channel, Office, User
from aslms.domain.ownership import (
    CaseOwnership,
    OwnershipStatus,
    OwnershipTransfer,
    Recommendation,
    RecommendationStatus,
    ScoreBand,
)
from aslms.domain.reference import (
    AlertKind,
    EventType,
    Permission,
    RecordType,
    RefAlertKind,
    RefDocType,
    RefRequestKind,
)
from aslms.domain.workflow import Request, RequestStatus
from aslms.services import access, calendar, notifications, visibility
from aslms.services import alert_rules as rules
from aslms.services.audit import Actor, write_audit
from aslms.services.cases import CaseNotFound, emit_event, ref_no_from_url, resolve_case_ref
from aslms.services.recipients import NAMED_RECIPIENT_EVENTS, Resolver, owning_office
from aslms.services.refno import allocate_ref_no
from aslms.services.visibility import NotVisibleCase

log = logging.getLogger(__name__)

JOB_EVENTS = "alerts_events"
JOB_DATES = "alerts_dates"
REF_OFFICE = "GOA"  # DB_STANDARD §3: ALR numbers are allocated on the State root
OPEN_STATUSES = (AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED)
OWNERSHIP_EVENTS = frozenset(
    {
        EventType.ALLOTTED,
        EventType.CASE_TAKEN_OVER,
        EventType.TRANSFER_REQUESTED,
        EventType.TRANSFER_DECIDED,
    }
)
HANDLED_EVENTS = OWNERSHIP_EVENTS | {
    EventType.NEXT_DATE_CHANGED,
    EventType.ORDER_STORED,
    EventType.STATUS_CHANGED,
    EventType.CASE_DISPOSED,
    EventType.RECOMMENDATION_MADE,
    EventType.DOCUMENT_UPLOADED,
}
DEFAULT_LIMIT, MAX_LIMIT = 50, 200
MAX_NOTE = 500


@dataclass(frozen=True)
class AlertConfig:
    """The numbers of the design, from `Settings` in production and as defaults in tests."""

    hearing_lookahead_days: int = 7
    critical_hours: int = 48
    sitting_time: str = "10:30"
    event_max_age_days: int = 14
    event_overlap_minutes: int = 30
    info_expire_days: int = 14
    compliance_expire_days: int = 30
    compliance_window_days: int = 7
    request_due_soon_days: int = 2

    @classmethod
    def from_settings(cls, s: Settings) -> AlertConfig:
        return cls(
            hearing_lookahead_days=s.alert_hearing_lookahead_days,
            critical_hours=s.alert_critical_hours,
            sitting_time=s.court_sitting_time,
            event_max_age_days=s.alert_event_max_age_days,
            event_overlap_minutes=s.alert_event_overlap_minutes,
            info_expire_days=s.alert_info_expire_days,
            compliance_expire_days=s.alert_compliance_expire_days,
            request_due_soon_days=s.request_due_soon_days,
        )


class AlertError(ValueError):
    """A refused action (HTTP 400)."""


class AlertConflict(AlertError):
    """The alert is not in a state that admits the action (HTTP 409 with a code)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class AlertNotFound(LookupError):
    """No alert for the reference, or one the caller may not see (HTTP 404)."""


def _now() -> datetime:
    return datetime.now(UTC)


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _date(value: Any) -> date | None:
    if value is None or value == "None":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def default_severities(session: Session) -> dict[AlertKind, Severity]:
    out: dict[AlertKind, Severity] = {}
    for row in session.scalars(select(RefAlertKind)).all():
        try:
            out[AlertKind(row.code)] = Severity(row.default_severity)
        except ValueError:
            continue
    return out


def case_url_ref(case: Case) -> str:
    return case.ref_no.replace("/", "-")


# ------------------------------------------------------------------------------------------------ raise / close


def raise_alert(
    session: Session,
    *,
    case: Case | None,
    kind: AlertKind,
    key: str,
    office: Office,
    severity: Severity,
    due_at: datetime | None = None,
    data: dict[str, Any] | None = None,
    source_event_id: uuid.UUID | None = None,
    recipients: Callable[[], list[User]] | Iterable[User] = (),
    now: datetime | None = None,
    counters: dict[str, int] | None = None,
) -> tuple[Alert, bool]:
    """Looks the key up (`FOR UPDATE`); new → allocate `ALR` on `GOA`, insert in a savepoint (a unique race
    re-reads the winner), emit `alert_raised`, notify; existing and open with a higher severity → raise the
    severity, notify again; otherwise nothing. Returns (alert, changed). Only an `admin_ticket` alert has no
    case (design `user-memberships`, decision 19); it emits no case event."""
    if (case is None) != (AlertKind(kind) == AlertKind.ADMIN_TICKET):
        raise AlertError("only an admin_ticket alert is raised without a case")
    now = now or _now()
    counters = counters if counters is not None else {}
    data = _jsonable(data or {})
    existing = session.scalar(select(Alert).where(Alert.dedupe_key == key).with_for_update())
    title, body = rules.render_alert(kind, case, data)
    if existing is None:
        alert = Alert(
            case_id=case.id if case is not None else None,
            kind=kind,
            office_id=office.id,
            due_at=due_at,
            severity=severity,
            status=AlertStatus.OPEN,
            title=title,
            body=body,
            data=data,
            source_event_id=source_event_id,
            dedupe_key=key,
            ref_no=allocate_ref_no(session, REF_OFFICE, RecordType.ALR.value, now),
        )
        try:
            with session.begin_nested():
                session.add(alert)
                session.flush()
        except IntegrityError:
            winner = session.scalar(select(Alert).where(Alert.dedupe_key == key).with_for_update())
            if winner is None:
                raise
            return winner, False
        if case is not None:
            emit_event(
                session,
                EventType.ALERT_RAISED,
                case,
                {
                    "alert_id": str(alert.id),
                    "ref_no": alert.ref_no,
                    "kind": kind.value,
                    "severity": Severity(severity).value,
                    "office_code": office.code,
                    "title": title,
                },
                dedupe=f"alert_raised:{alert.id}",
                scoped=True,
            )
        counters["alerts_new"] = counters.get("alerts_new", 0) + 1
    elif AlertStatus(existing.status) in OPEN_STATUSES and rules.higher(severity, existing.severity):
        existing.severity = severity
        existing.title, existing.body = title, body
        existing.data = {**(existing.data or {}), **data}
        if due_at is not None:
            existing.due_at = due_at
        session.flush()
        alert = existing
        counters["alerts_upgraded"] = counters.get("alerts_upgraded", 0) + 1
    else:
        return existing, False
    users = list(recipients()) if callable(recipients) else list(recipients)
    if not users:
        counters["alerts_without_recipients"] = counters.get("alerts_without_recipients", 0) + 1
    n = notifications.notify(session, alert, users, severity, now=now)
    counters["notifications"] = counters.get("notifications", 0) + n
    return alert, True


def close_alert(
    session: Session,
    alert: Alert,
    status: AlertStatus,
    reason: str,
    *,
    actor_user_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> Alert:
    if AlertStatus(status) not in (AlertStatus.DONE, AlertStatus.EXPIRED):
        raise AlertError("close with done or expired")
    if AlertStatus(alert.status) not in OPEN_STATUSES:
        raise AlertConflict("closed", "the alert is already closed")
    alert.status = status
    alert.closed_at = now or _now()
    alert.closed_by_user_id = actor_user_id
    alert.data = {**(alert.data or {}), "closed_reason": reason}
    session.flush()
    return alert


# ------------------------------------------------------------------------------------------------ the event scan


def _start_run(session: Session, job: str, now: datetime, counters: dict[str, Any]) -> JobRun:
    run = JobRun(job=job, run_date=rules.today_ist(now), started_at=now, counters=_jsonable(counters))
    session.add(run)
    session.flush()
    return run


def _finish_run(run: JobRun, counters: dict[str, Any], *, partial: bool = False) -> None:
    run.counters = _jsonable(counters)
    run.status = JobStatus.PARTIAL if partial else JobStatus.SUCCEEDED
    run.finished_at = _now()


def last_succeeded_run(session: Session, job: str) -> JobRun | None:
    return session.scalar(
        select(JobRun)
        .where(JobRun.job == job, JobRun.status == JobStatus.SUCCEEDED)
        .order_by(JobRun.started_at.desc())
        .limit(1)
    )


def scan_events(
    session: Session, *, now: datetime | None = None, config: AlertConfig | None = None
) -> dict[str, Any]:
    now = now or _now()
    cfg = config or AlertConfig()
    today = rules.today_ist(now)
    overlap = timedelta(minutes=cfg.event_overlap_minutes)
    last = last_succeeded_run(session, JOB_EVENTS)
    window_from = (last.started_at if last is not None else now) - overlap
    counters: dict[str, Any] = {
        "window_from": window_from.isoformat(),
        "events_read": 0,
        "alerts_new": 0,
        "alerts_upgraded": 0,
        "skipped_old": 0,
        "skipped_unowned": 0,
        "skipped_other": 0,
        "alerts_without_recipients": 0,
        "notifications": 0,
        "errors": 0,
    }
    run = _start_run(session, JOB_EVENTS, now, counters)
    owned = exists().where(
        CaseOwnership.case_id == Event.case_id, CaseOwnership.status == OwnershipStatus.ACTIVE
    )
    in_window = [Event.created_at >= window_from, Event.case_id.is_not(None)]
    counters["skipped_unowned"] = int(
        session.scalar(
            select(func.count(Event.id)).where(
                *in_window,
                Event.type.in_(list(HANDLED_EVENTS - {EventType.RECOMMENDATION_MADE})),
                ~owned,
            )
        )
        or 0
    )
    events = session.scalars(
        select(Event)
        .where(
            *in_window,
            Event.type.in_(list(HANDLED_EVENTS)),
            or_(Event.type == EventType.RECOMMENDATION_MADE, owned),
        )
        .order_by(Event.created_at, Event.id)
    ).all()
    resolver = Resolver(session)
    defaults = default_severities(session)
    for ev in events:
        counters["events_read"] += 1
        try:
            with session.begin_nested():
                _handle_event(
                    session, resolver, defaults, ev, now=now, today=today, cfg=cfg, counters=counters
                )
        except Exception:  # noqa: BLE001 — one bad event must not stop the run; it is counted and logged
            counters["errors"] += 1
            log.exception("alert scan: event %s failed", ev.id)
    _finish_run(run, counters, partial=counters["errors"] > 0)
    return counters


def _handle_event(
    session: Session,
    resolver: Resolver,
    defaults: dict[AlertKind, Severity],
    ev: Event,
    *,
    now: datetime,
    today: date,
    cfg: AlertConfig,
    counters: dict[str, Any],
) -> None:
    case = session.get(Case, ev.case_id)
    if case is None:
        counters["skipped_other"] += 1
        return
    kind_of_event = EventType(ev.type)
    p = ev.payload or {}

    def case_recipients(document_id: uuid.UUID | None = None) -> Callable[[], list[User]]:
        return lambda: resolver.finalise(
            resolver.case_recipients(case),
            case,
            exclude_user_id=ev.actor_user_id,
            document_id=document_id,
        )

    def office_or_skip() -> Office | None:
        office = owning_office(session, case)
        if office is None:
            counters["skipped_unowned"] += 1
        return office

    if kind_of_event == EventType.NEXT_DATE_CHANGED:
        pair = p.get("next_hearing_date")
        if not isinstance(pair, list) or len(pair) != 2 or _date(pair[0]) is None or _date(pair[1]) is None:
            counters["skipped_other"] += 1
            return
        old, new = _date(pair[0]), _date(pair[1])
        if new < today:
            counters["skipped_old"] += 1
            return
        office = office_or_skip()
        if office is None:
            return
        raise_alert(
            session,
            case=case,
            kind=AlertKind.NEXT_DATE_CHANGED,
            key=rules.dedupe_key(AlertKind.NEXT_DATE_CHANGED, case.id, new),
            office=office,
            severity=defaults.get(AlertKind.NEXT_DATE_CHANGED, Severity.HIGH),
            due_at=rules.hearing_due_at(new, cfg.sitting_time),
            data={"hearing_date": new, "previous_date": old},
            source_event_id=ev.id,
            recipients=case_recipients(),
            now=now,
            counters=counters,
        )
    elif kind_of_event == EventType.ORDER_STORED:
        order_date = _date(p.get("order_date"))
        if not rules.is_recent(order_date, today, cfg.event_max_age_days):
            counters["skipped_old"] += 1
            return
        office = office_or_skip()
        if office is None:
            return
        order = session.scalar(
            select(Order).where(
                Order.case_id == case.id,
                Order.order_no == str(p.get("order_no")),
                Order.order_date == order_date,
            )
        )
        raise_alert(
            session,
            case=case,
            kind=AlertKind.NEW_ORDER,
            key=rules.dedupe_key(AlertKind.NEW_ORDER, case.id, p.get("order_no"), order_date),
            office=office,
            severity=defaults.get(AlertKind.NEW_ORDER, Severity.HIGH),
            data={
                "order_id": order.id if order else None,
                "document_id": p.get("document_id") or (order.document_id if order else None),
                "order_no": p.get("order_no"),
                "order_date": order_date,
            },
            source_event_id=ev.id,
            recipients=case_recipients(),
            now=now,
            counters=counters,
        )
    elif kind_of_event in (EventType.CASE_DISPOSED, EventType.STATUS_CHANGED):
        pair = p.get("status")
        if kind_of_event == EventType.CASE_DISPOSED:
            previous = pair[0] if isinstance(pair, list) and pair else None
            new_status = CaseStatus.DISPOSED.value
        else:
            if not isinstance(pair, list) or len(pair) != 2 or not pair[1]:
                counters["skipped_other"] += 1
                return
            previous, new_status = pair[0], str(pair[1])
        disposal = case.disposal_date if new_status == CaseStatus.DISPOSED.value else None
        if new_status == CaseStatus.DISPOSED.value and disposal is not None:
            if not rules.is_recent(disposal, today, cfg.event_max_age_days):
                counters["skipped_old"] += 1
                return
        office = office_or_skip()
        if office is None:
            return
        disposed = new_status == CaseStatus.DISPOSED.value
        raise_alert(
            session,
            case=case,
            kind=AlertKind.STATUS_CHANGED,
            key=rules.dedupe_key(AlertKind.STATUS_CHANGED, case.id, new_status, disposal),
            office=office,
            severity=Severity.HIGH if disposed else Severity.NORMAL,
            data={
                "status": new_status,
                "previous_status": previous,
                "disposal_date": disposal,
                "disposal_nature": case.disposal_nature if disposed else None,
            },
            source_event_id=ev.id,
            recipients=case_recipients(),
            now=now,
            counters=counters,
        )
    elif kind_of_event == EventType.RECOMMENDATION_MADE:
        rec = session.get(Recommendation, _uuid(p.get("recommendation_id")))
        if (
            rec is None
            or RecommendationStatus(rec.status) != RecommendationStatus.RECOMMENDED
            or ScoreBand(rec.band) != ScoreBand.HIGH
            or CaseStatus(case.status) != CaseStatus.PENDING
        ):
            counters["skipped_other"] += 1
            return
        office = session.get(Office, rec.office_id)
        soon = case.next_hearing_date is not None and today <= case.next_hearing_date <= today + timedelta(
            days=cfg.hearing_lookahead_days
        )
        raise_alert(
            session,
            case=case,
            kind=AlertKind.RECOMMENDATION,
            key=rules.dedupe_key(AlertKind.RECOMMENDATION, rec.id),
            office=office,
            severity=Severity.HIGH if soon else Severity.NORMAL,
            due_at=rules.hearing_due_at(case.next_hearing_date, cfg.sitting_time) if soon else None,
            data={
                "recommendation_id": rec.id,
                "office_code": office.code,
                "score": float(rec.score),
                "band": ScoreBand(rec.band).value,
            },
            source_event_id=ev.id,
            recipients=lambda: resolver.finalise(resolver.for_recommendation(rec), case),
            now=now,
            counters=counters,
        )
    elif kind_of_event in OWNERSHIP_EVENTS:
        office = _ownership_office(session, kind_of_event, p)
        if office is None:
            counters["skipped_other"] += 1
            return
        actor = session.get(User, ev.actor_user_id) if ev.actor_user_id else None
        data = {
            "event": kind_of_event.value,
            "actor_name": actor.full_name if actor else None,
            **{k: v for k, v in p.items() if k not in {"reason"}},
        }
        if kind_of_event == EventType.ALLOTTED and p.get("officer_user_id"):
            officer = resolver.user(p.get("officer_user_id"))
            data["officer_name"] = officer.full_name if officer else None
        raise_alert(
            session,
            case=case,
            kind=AlertKind.OWNERSHIP,
            key=rules.dedupe_key(AlertKind.OWNERSHIP, ev.id),
            office=office,
            severity=Severity.HIGH
            if kind_of_event == EventType.TRANSFER_REQUESTED
            else defaults.get(AlertKind.OWNERSHIP, Severity.NORMAL),
            data=data,
            source_event_id=ev.id,
            recipients=lambda: resolver.finalise(
                resolver.for_ownership_event(kind_of_event.value, p),
                case,
                exclude_user_id=ev.actor_user_id,
                require_case_access=kind_of_event.value not in NAMED_RECIPIENT_EVENTS,
            ),
            now=now,
            counters=counters,
        )
    elif kind_of_event == EventType.DOCUMENT_UPLOADED:
        office = office_or_skip()
        if office is None:
            return
        document_id = _uuid(p.get("document_id"))
        if document_id is None:
            counters["skipped_other"] += 1
            return
        doc_type = session.get(RefDocType, p.get("doc_type")) if p.get("doc_type") else None
        raise_alert(
            session,
            case=case,
            kind=AlertKind.NEW_DOCUMENT,
            key=rules.dedupe_key(AlertKind.NEW_DOCUMENT, ev.id),
            office=office,
            severity=defaults.get(AlertKind.NEW_DOCUMENT, Severity.NORMAL),
            data={
                "document_id": document_id,
                "doc_type": p.get("doc_type"),
                "doc_type_label": doc_type.label if doc_type else None,
                "office_code": p.get("office_code"),
            },
            source_event_id=ev.id,
            recipients=case_recipients(document_id),
            now=now,
            counters=counters,
        )
    else:
        counters["skipped_other"] += 1


def _ownership_office(session: Session, kind: EventType, p: dict[str, Any]) -> Office | None:
    """The office an ownership alert is addressed to (decision 13)."""
    from aslms.services.offices import find_office

    if kind in (EventType.ALLOTTED, EventType.CASE_TAKEN_OVER):
        return find_office(session, p.get("office_code") or "")
    if kind == EventType.TRANSFER_REQUESTED:
        return find_office(session, p.get("to_office_code") or "")
    if kind == EventType.TRANSFER_DECIDED:
        t = session.get(OwnershipTransfer, _uuid(p.get("transfer_id")))
        return session.get(Office, t.from_office_id) if t is not None else None
    return None


# ------------------------------------------------------------------------------------------------ the date sweep


def _open_alerts(session: Session, kind: AlertKind) -> list[Alert]:
    return list(
        session.scalars(
            select(Alert).where(Alert.kind == kind, Alert.status.in_(list(OPEN_STATUSES))).with_for_update()
        ).all()
    )


def sweep_dates(
    session: Session, *, now: datetime | None = None, config: AlertConfig | None = None
) -> dict[str, Any]:
    now = now or _now()
    cfg = config or AlertConfig()
    today = rules.today_ist(now)
    counters: dict[str, Any] = {
        "hearings_seen": 0,
        "alerts_new": 0,
        "alerts_upgraded": 0,
        "alerts_without_recipients": 0,
        "notifications": 0,
        "closed_hearing": 0,
        "closed_info": 0,
        "closed_recommendation": 0,
        "closed_request": 0,
        "closed_compliance": 0,
    }
    run = _start_run(session, JOB_DATES, now, counters)
    resolver = Resolver(session)
    cases: dict[uuid.UUID, Case] = {}

    def case_of(case_id: uuid.UUID) -> Case:
        if case_id not in cases:
            cases[case_id] = session.get(Case, case_id)
        return cases[case_id]

    def case_recipients(case: Case) -> Callable[[], list[User]]:
        return lambda: resolver.finalise(resolver.case_recipients(case), case)

    # hearings (decision 6)
    rows = calendar.hearing_rows(
        session,
        from_=today,
        to=today + timedelta(days=cfg.hearing_lookahead_days),
        case_condition=calendar.owned_case_condition(),
    )
    current_keys: set[str] = set()
    for r in rows:
        counters["hearings_seen"] += 1
        key = rules.dedupe_key(AlertKind.HEARING_DUE, r.case_id, r.date)
        current_keys.add(key)
        due_at = rules.hearing_due_at(r.date, cfg.sitting_time)
        severity = rules.severity_for_hearing(due_at, now, cfg.critical_hours)
        if severity is None:
            continue
        case = case_of(r.case_id)
        office = owning_office(session, case)
        if case is None or office is None:
            continue
        raise_alert(
            session,
            case=case,
            kind=AlertKind.HEARING_DUE,
            key=key,
            office=office,
            severity=severity,
            due_at=due_at,
            data={
                "hearing_date": r.date,
                "source": r.source,
                "court_no": r.court_no,
                "item_no": r.item_no,
                "purpose": r.purpose,
            },
            recipients=case_recipients(case),
            now=now,
            counters=counters,
        )
    for a in _open_alerts(session, AlertKind.HEARING_DUE):
        if a.due_at is not None and rules.hearing_expired(a.due_at, now):
            close_alert(session, a, AlertStatus.EXPIRED, "passed", now=now)
            counters["closed_hearing"] += 1
        elif a.dedupe_key not in current_keys:
            close_alert(session, a, AlertStatus.EXPIRED, "date_changed", now=now)
            counters["closed_hearing"] += 1

    # compliance (decision 10)
    for obj, case in session.execute(
        select(CaseObjection, Case)
        .join(Case, Case.id == CaseObjection.case_id)
        .where(
            CaseObjection.compliance_by_date.is_not(None),
            CaseObjection.compliance_by_date <= today + timedelta(days=cfg.compliance_window_days),
            CaseObjection.compliance_by_date >= today - timedelta(days=cfg.compliance_expire_days),
            Case.merged_into_case_id.is_(None),
            calendar.owned_case_condition(),
        )
        .order_by(CaseObjection.scrutiny_date, CaseObjection.seq)
    ).all():
        severity = rules.severity_for_compliance(
            obj.compliance_by_date, today, cfg.compliance_window_days, cfg.request_due_soon_days
        )
        office = owning_office(session, case)
        if severity is None or office is None:
            continue
        raise_alert(
            session,
            case=case,
            kind=AlertKind.COMPLIANCE_DUE,
            key=rules.dedupe_key(AlertKind.COMPLIANCE_DUE, case.id, obj.scrutiny_date),
            office=office,
            severity=severity,
            due_at=rules.hearing_due_at(obj.compliance_by_date, cfg.sitting_time),
            data={
                "scrutiny_date": obj.scrutiny_date,
                "compliance_by_date": obj.compliance_by_date,
                "objection_seq": obj.seq,
                "source": "registry_objection",
            },
            recipients=case_recipients(case),
            now=now,
            counters=counters,
        )
    for a in _open_alerts(session, AlertKind.COMPLIANCE_DUE):
        by = _date((a.data or {}).get("compliance_by_date"))
        if by is not None and by + timedelta(days=cfg.compliance_expire_days) < today:
            close_alert(session, a, AlertStatus.EXPIRED, "expired", now=now)
            counters["closed_compliance"] += 1

    # requests (decision 11)
    kind_labels = {r.code: r.label for r in session.scalars(select(RefRequestKind)).all()}
    for req, case in session.execute(
        select(Request, Case)
        .join(Case, Case.id == Request.case_id)
        .where(
            Request.status == RequestStatus.OPEN,
            Request.due_date.is_not(None),
            Request.due_date <= today + timedelta(days=cfg.request_due_soon_days),
        )
        .order_by(Request.due_date)
    ).all():
        severity = rules.severity_for_due(req.due_date, today, cfg.request_due_soon_days)
        if severity is None:
            continue
        office = session.get(Office, req.to_office_id)
        from_office = session.get(Office, req.from_office_id)
        kind_code = req.kind.value if hasattr(req.kind, "value") else str(req.kind)
        raise_alert(
            session,
            case=case,
            kind=AlertKind.REQUEST_DUE,
            key=rules.dedupe_key(AlertKind.REQUEST_DUE, req.id),
            office=office,
            severity=severity,
            due_at=rules.hearing_due_at(req.due_date, cfg.sitting_time),
            data={
                "request_id": req.id,
                "ref_no": req.ref_no,
                "due_date": req.due_date,
                "overdue": req.due_date < today,
                "request_kind": kind_code,
                "request_kind_label": kind_labels.get(kind_code, kind_code),
                "from_office": from_office.code if from_office else None,
            },
            recipients=lambda req=req, case=case: resolver.finalise(resolver.for_request(req), case),
            now=now,
            counters=counters,
        )
    for a in _open_alerts(session, AlertKind.REQUEST_DUE):
        req = session.get(Request, _uuid((a.data or {}).get("request_id")))
        if req is None or RequestStatus(req.status) != RequestStatus.OPEN:
            reason = f"request_{RequestStatus(req.status).value}" if req is not None else "request_missing"
            close_alert(session, a, AlertStatus.DONE, reason, now=now)
            counters["closed_request"] += 1

    # recommendations decided (decision 12)
    for a in _open_alerts(session, AlertKind.RECOMMENDATION):
        rec = session.get(Recommendation, _uuid((a.data or {}).get("recommendation_id")))
        if rec is None or RecommendationStatus(rec.status) != RecommendationStatus.RECOMMENDED:
            reason = (
                f"recommendation_{RecommendationStatus(rec.status).value}"
                if rec is not None
                else "recommendation_missing"
            )
            close_alert(session, a, AlertStatus.DONE, reason, now=now)
            counters["closed_recommendation"] += 1

    # informational alerts past their age (decision 15)
    aged = session.scalars(
        select(Alert)
        .where(
            Alert.kind.in_(list(rules.INFO_KINDS)),
            Alert.status.in_(list(OPEN_STATUSES)),
            Alert.created_at < now - timedelta(days=cfg.info_expire_days),
        )
        .with_for_update()
    ).all()
    for a in aged:
        close_alert(session, a, AlertStatus.EXPIRED, "aged", now=now)
        counters["closed_info"] += 1
    _finish_run(run, counters)
    return counters


# ------------------------------------------------------------------------------------------------ actions


def resolve_alert_ref(session: Session, ref: str) -> Alert:
    """An alert by id or `ref_no` (slash or dash form). Unknown → AlertNotFound."""
    s = (ref or "").strip()
    alert = None
    try:
        alert = session.get(Alert, uuid.UUID(s))
    except ValueError:
        ref_no = ref_no_from_url(s)
        if ref_no is not None:
            alert = session.scalar(select(Alert).where(Alert.ref_no == ref_no))
    if alert is None:
        raise AlertNotFound("no such alert")
    return alert


def is_recipient(session: Session, user: User, alert: Alert) -> bool:
    return (
        session.scalar(
            select(Notification.id)
            .where(Notification.alert_id == alert.id, Notification.user_id == user.id)
            .limit(1)
        )
        is not None
    )


def named_recipient_notice(alert: Alert) -> bool:
    """An ownership alert whose recipient the design names regardless of case visibility (decision 13:
    `case_taken_over`, `transfer_requested`, `transfer_decided`)."""
    return (
        AlertKind(alert.kind) == AlertKind.OWNERSHIP
        and (alert.data or {}).get("event") in NAMED_RECIPIENT_EVENTS
    )


def notification_visible_condition(session: Session, user: User):
    """The visibility rule for the caller's own notifications: a visible case, or an ownership notice whose
    recipient the design names (deviation 1: the case may not be visible to them); and, for `new_document`,
    the document still visible to the caller (deviation 12)."""
    case_rule = and_(
        or_(
            visibility.visible_case_condition(session, user),
            and_(
                Alert.kind == AlertKind.OWNERSHIP,
                Alert.data["event"].astext.in_(list(NAMED_RECIPIENT_EVENTS)),
            ),
        ),
        visibility.alert_document_condition(session, user),
    )
    # a case-less (`admin_ticket`) alert: the caller's own notification is the whole rule (decision 19)
    return or_(and_(Alert.case_id.is_(None), Alert.kind == AlertKind.ADMIN_TICKET), case_rule)


def _may_act_on(session: Session, user: User, alert: Alert) -> Case | None:
    """The case must be visible and the user a recipient, or working on the case with the alert addressed
    to their own department (or reading State-wide); else 404. The named recipient of an ownership notice
    may read and act on it although the case is not visible to them. A `new_document` alert is 404 unless
    the document it names is visible to the user (deviation 12). An alert addressed to another department
    is 404 for a non-recipient however they work on the case (deviation 13). A case-less `admin_ticket` alert
    is visible and actionable only to its notified recipients (design `user-memberships`, decision 19)."""
    if alert.case_id is None:
        if AlertKind(alert.kind) == AlertKind.ADMIN_TICKET and is_recipient(session, user, alert):
            return None
        raise AlertNotFound("no such alert")
    case = session.get(Case, alert.case_id)
    if case is None:
        raise AlertNotFound("no such alert")
    if named_recipient_notice(alert) and is_recipient(session, user, alert):
        return case
    try:
        visibility.require_visible(session, user, case)
    except NotVisibleCase as exc:
        raise AlertNotFound("no such alert") from exc
    if not visibility.can_view_alert_document(session, user, alert):
        raise AlertNotFound("no such alert")
    if is_recipient(session, user, alert):
        return case
    if not (
        visibility.works_on_case(session, user, case)
        and visibility.addressed_to_department(session, user, alert)
    ):
        raise AlertNotFound("no such alert")
    return case


def get_for_user(session: Session, user: User, ref: str) -> Alert:
    alert = resolve_alert_ref(session, ref)
    _may_act_on(session, user, alert)
    return alert


def recipients_count(session: Session, alert: Alert) -> int:
    return int(
        session.scalar(
            select(func.count(func.distinct(Notification.user_id))).where(
                Notification.alert_id == alert.id, Notification.channel == Channel.IN_APP
            )
        )
        or 0
    )


def _note(value: str | None) -> str | None:
    text = (value or "").strip() or None
    if text and len(text) > MAX_NOTE:
        raise AlertError(f"the note is at most {MAX_NOTE} characters")
    return text


def alert_summary(alert: Alert) -> dict[str, Any]:
    return {
        "id": str(alert.id),
        "ref_no": alert.ref_no,
        "kind": alert.kind.value if hasattr(alert.kind, "value") else str(alert.kind),
        "severity": Severity(alert.severity).value,
        "status": AlertStatus(alert.status).value,
        "acknowledged_by_user_id": str(alert.acknowledged_by_user_id)
        if alert.acknowledged_by_user_id
        else None,
        "closed_at": alert.closed_at.isoformat() if alert.closed_at else None,
    }


def acknowledge(session: Session, actor: Actor, user: User, alert: Alert, note: str | None = None) -> Alert:
    """Decision 15: `alerts.acknowledge`, a recipient or working relation, from `open` only; audited."""
    access.require(session, user, Permission.ALERTS_ACKNOWLEDGE)
    note = _note(note)
    case = _may_act_on(session, user, alert)
    session.refresh(alert, with_for_update=True)
    if AlertStatus(alert.status) != AlertStatus.OPEN:
        raise AlertConflict("not_open", "only an open alert can be acknowledged")
    before = alert_summary(alert)
    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_by_user_id = user.id
    alert.acknowledged_at = _now()
    session.flush()
    write_audit(
        session,
        actor,
        "alert.acknowledged",
        "alert",
        alert.id,
        before=before,
        after={**alert_summary(alert), "note": note},
        case_id=case.id if case is not None else None,
    )
    return alert


def mark_done(session: Session, actor: Actor, user: User, alert: Alert, note: str | None = None) -> Alert:
    access.require(session, user, Permission.ALERTS_ACKNOWLEDGE)
    note = _note(note)
    case = _may_act_on(session, user, alert)
    session.refresh(alert, with_for_update=True)
    if AlertStatus(alert.status) not in OPEN_STATUSES:
        raise AlertConflict("closed", "the alert is already closed")
    before = alert_summary(alert)
    close_alert(session, alert, AlertStatus.DONE, "user", actor_user_id=user.id)
    write_audit(
        session,
        actor,
        "alert.done",
        "alert",
        alert.id,
        before=before,
        after={**alert_summary(alert), "note": note},
        case_id=case.id if case is not None else None,
    )
    return alert


# ------------------------------------------------------------------------------------------------ reading


@dataclass
class Page:
    items: list[dict[str, Any]]
    total: int


def clamp(limit: int | None, offset: int | None) -> tuple[int, int]:
    limit = DEFAULT_LIMIT if limit is None else max(1, min(int(limit), MAX_LIMIT))
    return limit, max(0, int(offset or 0))


def parse_statuses(value: str | None) -> list[AlertStatus] | None:
    """`status=open,acknowledged` (the default), `all`, or any list of states."""
    if value is None or not value.strip():
        return list(OPEN_STATUSES)
    if value.strip().lower() == "all":
        return None
    try:
        return [AlertStatus(v.strip().lower()) for v in value.split(",") if v.strip()]
    except ValueError as exc:
        raise AlertError(f"unknown status in {value!r}") from exc


def _latest_in_app(user: User):
    return (
        select(Notification)
        .where(Notification.user_id == user.id, Notification.channel == Channel.IN_APP)
        .ext(distinct_on(Notification.alert_id))
        .order_by(Notification.alert_id, Notification.created_at.desc(), Notification.id.desc())
        .subquery()
    )


def _labels(session: Session) -> dict[str, str]:
    return {r.code: r.label for r in session.scalars(select(RefAlertKind)).all()}


def alert_item(
    session: Session,
    alert: Alert,
    case: Case | None,
    *,
    labels: dict[str, str],
    users: dict[uuid.UUID, User],
    notified_at: datetime | None = None,
    read_at: datetime | None = None,
) -> dict[str, Any]:
    kind = alert.kind.value if hasattr(alert.kind, "value") else str(alert.kind)
    ack = users.get(alert.acknowledged_by_user_id) if alert.acknowledged_by_user_id else None
    return {
        "id": alert.id,
        "ref_no": alert.ref_no,
        "kind": kind,
        "kind_label": labels.get(kind, kind),
        "severity": Severity(alert.severity).value,
        "status": AlertStatus(alert.status).value,
        "title": alert.title,
        "body": alert.body,
        "due_at": alert.due_at,
        "case": calendar.case_ref(case) if case is not None else None,
        "ticket_ref": (alert.data or {}).get("ticket_ref") if case is None else None,
        "data": alert.data or {},
        "notified_at": notified_at,
        "read_at": read_at,
        "acknowledged_by": {"id": ack.id, "full_name": ack.full_name} if ack else None,
        "acknowledged_at": alert.acknowledged_at,
        "closed_at": alert.closed_at,
        "created_at": alert.created_at,
    }


def _users_for(session: Session, alerts: list[Alert]) -> dict[uuid.UUID, User]:
    ids = {a.acknowledged_by_user_id for a in alerts if a.acknowledged_by_user_id}
    if not ids:
        return {}
    return {u.id: u for u in session.scalars(select(User).where(User.id.in_(ids))).all()}


def list_for_user(
    session: Session,
    user: User,
    *,
    status: str | None = None,
    kind: str | None = None,
    severity: str | None = None,
    unread: bool | None = None,
    case_ref: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> Page:
    """The caller's own in-app notifications (the latest per alert), newest first, their cases filtered by
    the visibility rule in SQL."""
    limit, offset = clamp(limit, offset)
    n = _latest_in_app(user)
    conds = [notification_visible_condition(session, user)]
    statuses = parse_statuses(status)
    if statuses is not None:
        conds.append(Alert.status.in_(statuses))
    if kind:
        try:
            conds.append(Alert.kind == AlertKind(kind.strip().lower()))
        except ValueError as exc:
            raise AlertError(f"unknown kind {kind!r}") from exc
    if severity:
        try:
            conds.append(Alert.severity == Severity(severity.strip().lower()))
        except ValueError as exc:
            raise AlertError(f"unknown severity {severity!r}") from exc
    if unread is True:
        conds.append(n.c.status != NotificationStatus.READ)
    elif unread is False:
        conds.append(n.c.status == NotificationStatus.READ)
    if case_ref:
        try:
            conds.append(Alert.case_id == resolve_case_ref(session, case_ref).id)
        except CaseNotFound:
            return Page([], 0)
    base = (
        select(Alert, Case, n.c.created_at, n.c.read_at)
        .join(n, n.c.alert_id == Alert.id)
        .join(Case, Case.id == Alert.case_id, isouter=True)
    )
    base = base.where(*conds)
    total = int(session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = session.execute(
        base.order_by(n.c.created_at.desc(), Alert.id.desc()).limit(limit).offset(offset)
    ).all()
    labels = _labels(session)
    users = _users_for(session, [r[0] for r in rows])
    items = [
        alert_item(session, a, c, labels=labels, users=users, notified_at=created, read_at=read)
        for a, c, created, read in rows
    ]
    return Page(items, total)


def counts_for_user(session: Session, user: User) -> dict[str, Any]:
    n = _latest_in_app(user)
    base = (
        select(Alert.severity, n.c.status)
        .join(n, n.c.alert_id == Alert.id)
        .join(Case, Case.id == Alert.case_id, isouter=True)
        .where(notification_visible_condition(session, user), Alert.status.in_(list(OPEN_STATUSES)))
    )
    unread = 0
    open_: dict[str, int] = {s.value: 0 for s in Severity}
    for sev, nstatus in session.execute(base).all():
        open_[Severity(sev).value] += 1
        if NotificationStatus(nstatus) != NotificationStatus.READ:
            unread += 1
    return {"unread": unread, "open": open_}


def alerts_for_case(
    session: Session,
    user: User,
    case: Case,
    *,
    status: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> Page:
    """Open and recent alerts of a visible case for callers who work on it or read State-wide; others get
    an empty list (an alert reveals who is responsible). A `new_document` alert is listed only when its
    document is visible to the caller (deviation 12); an alert addressed to another department only when the
    caller was notified of it (deviation 13)."""
    visibility.require_visible(session, user, case)
    limit, offset = clamp(limit, offset)
    if not (visibility.state_wide(session, user) or visibility.works_on_case(session, user, case)):
        return Page([], 0)
    conds = [
        Alert.case_id == case.id,
        visibility.alert_document_condition(session, user),
        visibility.alert_office_condition(session, user),
    ]
    statuses = parse_statuses(status)
    if statuses is not None:
        conds.append(Alert.status.in_(statuses))
    total = int(session.scalar(select(func.count(Alert.id)).where(*conds)) or 0)
    rows = session.scalars(
        select(Alert)
        .where(*conds)
        .order_by(Alert.created_at.desc(), Alert.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    labels = _labels(session)
    users = _users_for(session, list(rows))
    mine = {
        nid: (created, read)
        for nid, created, read in session.execute(
            select(Notification.alert_id, Notification.created_at, Notification.read_at)
            .where(
                Notification.user_id == user.id,
                Notification.channel == Channel.IN_APP,
                Notification.alert_id.in_([a.id for a in rows]),
            )
            .order_by(Notification.created_at)
        ).all()
    }
    items = []
    for a in rows:
        created, read = mine.get(a.id, (None, None))
        items.append(
            alert_item(session, a, case, labels=labels, users=users, notified_at=created, read_at=read)
        )
    return Page(items, total)


def detail_item(session: Session, user: User, alert: Alert) -> dict[str, Any]:
    """One alert as the caller sees it (their latest in-app notification) plus `recipients_count`."""
    case = session.get(Case, alert.case_id) if alert.case_id is not None else None
    row = session.execute(
        select(Notification.created_at, Notification.read_at)
        .where(
            Notification.user_id == user.id,
            Notification.alert_id == alert.id,
            Notification.channel == Channel.IN_APP,
        )
        .order_by(Notification.created_at.desc())
        .limit(1)
    ).first()
    item = alert_item(
        session,
        alert,
        case,
        labels=_labels(session),
        users=_users_for(session, [alert]),
        notified_at=row[0] if row else None,
        read_at=row[1] if row else None,
    )
    item["recipients_count"] = recipients_count(session, alert)
    return item


def mark_read(
    session: Session, user: User, *, alert_ids: list[uuid.UUID] | None = None, all_: bool = False
) -> int:
    """Own in-app rows only: `sent` → `read` with `read_at`."""
    if not all_ and not alert_ids:
        return 0
    stmt = (
        update(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.channel == Channel.IN_APP,
            Notification.status == NotificationStatus.SENT,
        )
        .values(status=NotificationStatus.READ, read_at=_now())
    )
    if not all_:
        stmt = stmt.where(Notification.alert_id.in_(list(alert_ids or [])))
    return int(session.execute(stmt).rowcount or 0)


# ------------------------------------------------------------------------------------------------ status


def status_report(session: Session) -> dict[str, Any]:
    """Open alerts by kind and severity, queued and failed e-mails, the last run of each job (`aslms alerts
    status`; the data-health screen reads the same rows)."""
    open_by: dict[str, dict[str, int]] = {}
    for kind, sev, n in session.execute(
        select(Alert.kind, Alert.severity, func.count(Alert.id))
        .where(Alert.status.in_(list(OPEN_STATUSES)))
        .group_by(Alert.kind, Alert.severity)
    ).all():
        k = kind.value if hasattr(kind, "value") else str(kind)
        open_by.setdefault(k, {})[Severity(sev).value] = int(n)
    mails: dict[str, int] = {}
    for st, n in session.execute(
        select(Notification.status, func.count(Notification.id))
        .where(Notification.channel == Channel.EMAIL)
        .group_by(Notification.status)
    ).all():
        mails[NotificationStatus(st).value] = int(n)
    runs = {}
    for job in (JOB_EVENTS, JOB_DATES, notifications.JOB_SEND, notifications.JOB_DIGESTS):
        run = session.scalar(
            select(JobRun).where(JobRun.job == job).order_by(JobRun.started_at.desc()).limit(1)
        )
        runs[job] = (
            None
            if run is None
            else {
                "started_at": run.started_at,
                "status": JobStatus(run.status).value,
                "counters": run.counters,
                "error": run.error,
            }
        )
    kinds = [r.code for r in session.scalars(select(RefAlertKind).order_by(RefAlertKind.sort_order)).all()]
    return {"kinds": kinds, "open": open_by, "emails": mails, "runs": runs}
