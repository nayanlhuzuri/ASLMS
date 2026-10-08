"""Shared helpers for the dashboard and report tests over `tests/db/world.py`: function overrides granted by the
super admin, claims with allotment, files with a due date (made overdue directly: the service refuses a past
date), hearings, compliance alerts and next dates written the way the jobs write them, and a table row
counter for the "writes nothing" checks."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aslms.domain.alerts import Alert, AlertStatus, NextDate, NextDateSource, ReviewStatus, Severity
from aslms.domain.cases import Case, CaseStatus
from aslms.domain.causelists import Causelist, CauselistEntry, EntrySource, ListSource, ListType
from aslms.domain.courts import Court
from aslms.domain.org import PermissionEffect
from aslms.domain.ownership import CaseOwnership, OwnershipRole, OwnershipStatus
from aslms.domain.reference import AlertKind, Permission
from aslms.domain.workflow import Custody
from aslms.services import access
from aslms.services import ownership as own
from aslms.services.refno import allocate_ref_no
from aslms.services.workflow_common import today_ist
from tests.db.world import World, make_case

TABLES = (
    "audit_log",
    "events",
    "alerts",
    "notifications",
    "case_ownership",
    "custody",
    "custody_history",
    "case_notes",
    "case_note_drafts",
    "recommendations",
    "cases",
    "documents",
)


def today() -> date:
    return today_ist()


def override(
    s: Session, world: World, key: str, perm: Permission, effect: PermissionEffect | None, office=None
):
    """The super admin grants or denies one function on the user's membership (at `office`'s department)."""
    actor, root = world.actor(s, "root")
    access.set_override(s, actor, root, world.membership(s, key, office), perm, effect)
    s.flush()


def claim(
    s: Session, world: World, case: Case, *, by: str = "edu_admin", officer: str | None = None, unit=None
):
    actor, user = world.actor(s, by)
    kw: dict = {}
    if officer:
        kw["officer_user_id"] = world.user(s, officer).id
    if unit:
        kw["unit_code"] = unit
    return own.claim(s, actor, user, case, **kw)


def own_directly(
    s: Session, world: World, case: Case, code: str, role=OwnershipRole.PRIMARY
) -> CaseOwnership:
    """An ownership row written as the service writes it, for an office with no members (tests only)."""
    row = CaseOwnership(
        case_id=case.id,
        office_id=world.office(s, code).id,
        role=role,
        status=OwnershipStatus.ACTIVE,
        actor_name="test",
    )
    s.add(row)
    s.flush()
    return row


def set_due(s: Session, case: Case, days: int) -> None:
    """Moves the file's due date to today + `days` (negative: overdue)."""
    row = s.get(Custody, case.id)
    row.due_date = today() + timedelta(days=days)
    s.flush()


def dispose(s: Session, case: Case, on: date | None = None) -> None:
    case.status = CaseStatus.DISPOSED
    case.disposal_date = on or today()
    s.flush()


def listing(
    s: Session, case: Case | None, on: date, *, sr_no: int = 1, court_no: str = "1"
) -> CauselistEntry:
    court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
    cl = s.scalar(
        sa.select(Causelist).where(Causelist.list_date == on, Causelist.source == ListSource.GHC_WEBSITE)
    )
    if cl is None:
        cl = Causelist(
            court_id=court.id,
            list_date=on,
            list_type=ListType.DAILY,
            source=ListSource.GHC_WEBSITE,
            entry_count=0,
        )
        s.add(cl)
        s.flush()
    e = CauselistEntry(
        causelist_id=cl.id,
        sr_no=sr_no,
        court_no=court_no,
        case_id=case.id if case else None,
        source=EntrySource.PDF_PARSE,
    )
    s.add(e)
    cl.entry_count += 1
    s.flush()
    return e


def compliance_alert(
    s: Session, world: World, case: Case, by: date, *, office: str = "EDU", status=AlertStatus.OPEN
) -> Alert:
    a = Alert(
        case_id=case.id,
        kind=AlertKind.COMPLIANCE_DUE,
        office_id=world.office(s, office).id,
        severity=Severity.HIGH,
        status=status,
        title="Compliance due",
        data={"compliance_by_date": by.isoformat(), "scrutiny_date": (by - timedelta(days=30)).isoformat()},
        dedupe_key=f"test:compliance:{uuid.uuid4()}",
        ref_no=allocate_ref_no(s, "GOA", "ALR"),
    )
    if status in (AlertStatus.DONE, AlertStatus.EXPIRED):
        from datetime import UTC, datetime

        a.closed_at = datetime.now(UTC)
    s.add(a)
    s.flush()
    return a


def next_date(
    s: Session,
    case: Case,
    on: date,
    *,
    source=NextDateSource.ORDER_SPECIFIC,
    review=ReviewStatus.PENDING,
    needs_review: bool = True,
) -> NextDate:
    nd = NextDate(
        case_id=case.id, next_date=on, source=source, needs_review=needs_review, review_status=review
    )
    s.add(nd)
    s.flush()
    return nd


def row_counts(s: Session) -> dict[str, int]:
    return {t: s.execute(sa.text(f"select count(*) from {t}")).scalar() for t in TABLES}


def new_case(s: Session, **kw) -> Case:
    return make_case(s, **kw)
