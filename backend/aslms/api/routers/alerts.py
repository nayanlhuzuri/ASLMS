"""Alerts and hearing calendar (plan §5.5), notifications (§5.12), manual review of next dates."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update

from aslms.api import schemas as S
from aslms.api.deps import Ctx, current_ctx
from aslms.api.present import cards
from aslms.core.errors import NotFoundError
from aslms.core.time import now_utc, today_ist
from aslms.domain.alerts import Alert, AlertStatus, NextDate, NextDateSource, Notification, ReviewStatus
from aslms.domain.cases import Case, CaseStatus
from aslms.domain.org import Channel
from aslms.services import audit
from aslms.services import cases as case_svc
from aslms.services.alerts import severity_for
from aslms.services.scope import case_scope_clause, require_case_scope, require_write

router = APIRouter(tags=["alerts"])


def _my_alerts(ctx: Ctx):
    mine = select(Notification.alert_id).where(Notification.user_id == ctx.user.id)
    return select(Alert).where(Alert.id.in_(mine))


@router.get("/alerts", response_model=S.Page[S.AlertOut])
def alerts(
    status: str | None = Query("open", pattern="^(open|acknowledged|done|expired|all)$"),
    kind: str | None = None,
    severity: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    ctx: Ctx = Depends(current_ctx),
):
    stmt = _my_alerts(ctx)
    if status and status != "all":
        stmt = stmt.where(Alert.status == AlertStatus(status))
    if kind:
        stmt = stmt.where(Alert.kind == kind)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    total = ctx.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = ctx.db.scalars(
        stmt.order_by(Alert.severity, Alert.due_at.asc().nulls_last(), Alert.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    return S.Page(total=total, page=page, size=size, items=[S.AlertOut.model_validate(a) for a in rows])


def _alert(ctx: Ctx, alert_id: uuid.UUID) -> Alert:
    a = ctx.db.scalar(_my_alerts(ctx).where(Alert.id == alert_id))
    if a is None:
        raise NotFoundError("alert not found")
    return a


@router.post("/alerts/{alert_id}/ack", response_model=S.AlertOut)
def ack(alert_id: uuid.UUID, ctx: Ctx = Depends(current_ctx)) -> S.AlertOut:
    a = _alert(ctx, alert_id)
    if a.status == AlertStatus.OPEN:
        a.status, a.acknowledged_by_user_id, a.acknowledged_at = (
            AlertStatus.ACKNOWLEDGED,
            ctx.user.id,
            now_utc(),
        )
        audit.record(ctx.db, ctx.actor, "alert.ack", "alert", a.id, case_id=a.case_id)
    return S.AlertOut.model_validate(a)


@router.post("/alerts/{alert_id}/done", response_model=S.AlertOut)
def done(alert_id: uuid.UUID, ctx: Ctx = Depends(current_ctx)) -> S.AlertOut:
    a = _alert(ctx, alert_id)
    require_write(ctx.principal)
    a.status = AlertStatus.DONE
    if not a.acknowledged_at:
        a.acknowledged_by_user_id, a.acknowledged_at = ctx.user.id, now_utc()
    audit.record(ctx.db, ctx.actor, "alert.done", "alert", a.id, case_id=a.case_id)
    return S.AlertOut.model_validate(a)


@router.get("/calendar", response_model=list[S.CalendarItem])
def calendar(
    start: date | None = Query(None, alias="from"),
    end: date | None = Query(None, alias="to"),
    ctx: Ctx = Depends(current_ctx),
) -> list[S.CalendarItem]:
    """Upcoming hearings of the cases within your access (critical ≤ 48 h, high this week)."""
    today = today_ist()
    start = start or today
    end = end or start + timedelta(days=30)
    rows = list(
        ctx.db.scalars(
            select(Case)
            .where(
                case_scope_clause(ctx.principal),
                Case.status != CaseStatus.DISPOSED,
                Case.next_hearing_date.between(start, end),
            )
            .order_by(Case.next_hearing_date, Case.case_no_text)
            .limit(1000)
        )
    )
    cc = {c.id: c for c in cards(ctx.db, ctx.principal, rows)}
    return [
        S.CalendarItem(
            date=c.next_hearing_date,
            case=cc[c.id],
            purpose=c.next_purpose,
            severity=severity_for(c.next_hearing_date, today).value,
        )
        for c in rows
    ]


@router.post("/next-dates/{next_date_id}/review", response_model=S.NextDateOut)
def review_next_date(
    next_date_id: uuid.UUID, body: S.ReviewIn, ctx: Ctx = Depends(current_ctx)
) -> S.NextDateOut:
    """Confirms or rejects a next date flagged for manual review. Confirming may correct the date."""
    nd = ctx.db.get(NextDate, next_date_id)
    if nd is None:
        raise NotFoundError("next date not found")
    require_write(ctx.principal)
    require_case_scope(ctx.db, ctx.principal, nd.case_id)
    case = ctx.db.get(Case, nd.case_id)
    nd.review_status = ReviewStatus.CONFIRMED if body.confirm else ReviewStatus.REJECTED
    nd.reviewed_by_user_id, nd.reviewed_at = ctx.user.id, now_utc()
    if body.note:
        nd.note = f"{nd.note or ''}\n[review] {body.note}".strip()
    if body.confirm:
        final = body.next_date or nd.next_date
        case_svc.record_next_date(
            ctx.db,
            case,
            final,
            NextDateSource.MANUAL,
            order_id=nd.order_id,
            confidence=1.0,
            note=f"confirmed by {ctx.user.full_name}",
        )
        if final >= today_ist() and (
            case.next_hearing_date is None or case.next_hearing_date < today_ist() or body.next_date
        ):
            case.next_hearing_date = final
    ctx.db.execute(update(Alert).where(Alert.dedupe_key == f"review:{nd.id}").values(status=AlertStatus.DONE))
    audit.record(
        ctx.db,
        ctx.actor,
        "next_date.review",
        "next_date",
        nd.id,
        case_id=case.id,
        after={"confirm": body.confirm, "date": str(body.next_date or nd.next_date)},
    )
    return S.NextDateOut.model_validate(nd)


@router.get("/notifications", response_model=S.Page[S.NotificationOut])
def notifications(
    unread: bool = False,
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=200),
    ctx: Ctx = Depends(current_ctx),
):
    stmt = select(Notification).where(
        Notification.user_id == ctx.user.id, Notification.channel == Channel.IN_APP
    )
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    total = ctx.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = ctx.db.scalars(stmt.order_by(Notification.created_at.desc()).offset((page - 1) * size).limit(size))
    rows = list(rows)
    alert_cases = dict(
        ctx.db.execute(
            select(Alert.id, Alert.case_id).where(Alert.id.in_([n.alert_id for n in rows if n.alert_id]))
        ).all()
    )
    items = [
        S.NotificationOut.model_validate(n).model_copy(update={"case_id": alert_cases.get(n.alert_id)})
        for n in rows
    ]
    return S.Page(total=total, page=page, size=size, items=items)


@router.post("/notifications/{notification_id}/read", response_model=S.Ok)
def read(notification_id: uuid.UUID, ctx: Ctx = Depends(current_ctx)) -> S.Ok:
    ctx.db.execute(
        update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.user_id == ctx.user.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=now_utc())
    )
    return S.Ok()


@router.post("/notifications/read-all", response_model=S.Ok)
def read_all(ctx: Ctx = Depends(current_ctx)) -> S.Ok:
    ctx.db.execute(
        update(Notification)
        .where(Notification.user_id == ctx.user.id, Notification.read_at.is_(None))
        .values(read_at=now_utc())
    )
    return S.Ok()
