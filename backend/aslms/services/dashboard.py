"""Role-dependent dashboard (plan §5.1). Everything is read from the portal database; no API calls."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session

from aslms.core.time import today_ist
from aslms.domain.alerts import Alert, AlertStatus, Notification, NotificationStatus, Severity
from aslms.domain.cases import Case, CaseStatus
from aslms.domain.org import Channel, Office, OfficeKind, Role
from aslms.domain.ownership import (
    CaseOwnership,
    OwnershipStatus,
    OwnershipTransfer,
    Recommendation,
    RecommendationStatus,
    TransferStatus,
)
from aslms.services.scope import Principal, case_scope_clause


def _count(session: Session, stmt) -> int:
    return session.scalar(select(func.count()).select_from(stmt.subquery())) or 0


def upcoming_hearings(session: Session, p: Principal, days: int = 7, limit: int = 50) -> list[Case]:
    today = today_ist()
    return list(
        session.scalars(
            select(Case)
            .where(
                case_scope_clause(p),
                Case.status != CaseStatus.DISPOSED,
                Case.next_hearing_date.between(today, today + timedelta(days=days)),
            )
            .order_by(Case.next_hearing_date, Case.case_no_text)
            .limit(limit)
        )
    )


def summary(session: Session, p: Principal) -> dict[str, Any]:
    today = today_ist()
    scoped = select(Case.id).where(case_scope_clause(p), Case.merged_into_case_id.is_(None))
    pending = scoped.where(Case.status != CaseStatus.DISPOSED)
    out: dict[str, Any] = {
        "role": p.role.value,
        "cases_in_scope": _count(session, scoped),
        "pending_cases": _count(session, pending),
        "hearings_48h": _count(
            session, pending.where(Case.next_hearing_date.between(today, today + timedelta(days=2)))
        ),
        "hearings_week": _count(
            session, pending.where(Case.next_hearing_date.between(today, today + timedelta(days=7)))
        ),
        "unread_notifications": session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == p.user_id,
                Notification.channel == Channel.IN_APP,
                Notification.read_at.is_(None),
            )
        )
        or 0,
        "open_critical_alerts": session.scalar(
            select(func.count(func.distinct(Alert.id)))
            .select_from(Alert)
            .join(Notification, Notification.alert_id == Alert.id)
            .where(
                Notification.user_id == p.user_id,
                Alert.status == AlertStatus.OPEN,
                Alert.severity == Severity.CRITICAL,
            )
        )
        or 0,
    }
    if p.department_id and p.role in (Role.DEPT_ADMIN, Role.DEPT_HEAD):
        out["recommended_high"] = (
            session.scalar(
                select(func.count())
                .select_from(Recommendation)
                .where(
                    Recommendation.office_id == p.department_id,
                    Recommendation.status == RecommendationStatus.RECOMMENDED,
                    Recommendation.band == "high",
                )
            )
            or 0
        )
        out["recommended_total"] = (
            session.scalar(
                select(func.count())
                .select_from(Recommendation)
                .where(
                    Recommendation.office_id == p.department_id,
                    Recommendation.status == RecommendationStatus.RECOMMENDED,
                )
            )
            or 0
        )
        out["transfers_incoming"] = (
            session.scalar(
                select(func.count())
                .select_from(OwnershipTransfer)
                .where(
                    OwnershipTransfer.to_office_id == p.department_id,
                    OwnershipTransfer.status == TransferStatus.REQUESTED,
                )
            )
            or 0
        )
        unit = Office.__table__.alias("unit")
        out["by_unit"] = [
            {"unit": code or "(not allotted)", "cases": n}
            for code, n in session.execute(
                select(unit.c.code, func.count())
                .select_from(CaseOwnership)
                .outerjoin(unit, unit.c.id == CaseOwnership.unit_office_id)
                .where(
                    CaseOwnership.office_id == p.department_id, CaseOwnership.status == OwnershipStatus.ACTIVE
                )
                .group_by(unit.c.code)
            )
        ]
    if p.is_state_tier:
        owned = exists().where(
            and_(CaseOwnership.case_id == Case.id, CaseOwnership.status == OwnershipStatus.ACTIVE)
        )
        out["unclaimed_pending"] = _count(
            session, select(Case.id).where(~owned, Case.status != CaseStatus.DISPOSED)
        )
        out["unclaimed_listed_week"] = _count(
            session,
            select(Case.id).where(
                ~owned,
                Case.status != CaseStatus.DISPOSED,
                Case.next_hearing_date.between(today, today + timedelta(days=7)),
            ),
        )
        out["by_department"] = [
            {"office_id": str(oid), "code": code, "name": name, "pending": n}
            for oid, code, name, n in session.execute(
                select(Office.id, Office.code, Office.name, func.count(func.distinct(Case.id)))
                .join(CaseOwnership, CaseOwnership.office_id == Office.id)
                .join(Case, Case.id == CaseOwnership.case_id)
                .where(
                    Office.kind == OfficeKind.DEPARTMENT,
                    CaseOwnership.status == OwnershipStatus.ACTIVE,
                    Case.status != CaseStatus.DISPOSED,
                )
                .group_by(Office.id, Office.code, Office.name)
                .order_by(func.count(func.distinct(Case.id)).desc())
            )
        ]
    if p.role in (Role.DEPT_OFFICER, Role.REFERRAL_REVIEWER):
        out["allotted_to_me"] = _count(
            session,
            select(CaseOwnership.id).where(
                CaseOwnership.officer_user_id == p.user_id, CaseOwnership.status == OwnershipStatus.ACTIVE
            ),
        )
    out["undelivered_email"] = (
        session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == p.user_id, Notification.status == NotificationStatus.FAILED)
        )
        or 0
    )
    return out
