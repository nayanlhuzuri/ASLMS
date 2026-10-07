"""The hearing calendar (design `alerts-notifications`, decisions 6 and 20). A case's hearing dates are the
union of `cases.next_hearing_date`, its listings in cause lists (`causelist_entries` → `causelists.list_date`)
and its latest `next_dates` row of source `manual`, `order_specific` or `order_period` whose review status is
`not_needed` or `confirmed`. `hearing_rows` is shared by the date sweep (owned cases) and
`calendar_for_user` (the caller's working cases, or one department's owned cases for a State-wide reader);
one row per (case, date), the cause-list listing preferred because it names the court and the item."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, exists, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from aslms.domain.alerts import NextDate, NextDateSource, ReviewStatus
from aslms.domain.cases import Case
from aslms.domain.causelists import Causelist, CauselistEntry
from aslms.domain.org import Office, User
from aslms.domain.ownership import CaseOwnership, OwnershipStatus
from aslms.services import alert_rules as rules
from aslms.services import visibility
from aslms.services.access import Forbidden
from aslms.services.offices import find_office

MAX_RANGE_DAYS = 62
DEFAULT_RANGE_DAYS = 7
SOURCE_RANK = {"causelist": 0, "next_date": 1, "current_status": 2}
NEXT_DATE_SOURCES = (NextDateSource.MANUAL, NextDateSource.ORDER_SPECIFIC, NextDateSource.ORDER_PERIOD)
NEXT_DATE_REVIEW = (ReviewStatus.NOT_NEEDED, ReviewStatus.CONFIRMED)


class CalendarError(ValueError):
    """A bad range (HTTP 422)."""


@dataclass
class HearingRow:
    case_id: uuid.UUID
    date: date
    source: str
    court_no: str | None = None
    item_no: str | None = None
    purpose: str | None = None


def owned_case_condition() -> ColumnElement[bool]:
    """Decision 5: the case has an active primary owner or watcher."""
    return exists().where(CaseOwnership.case_id == Case.id, CaseOwnership.status == OwnershipStatus.ACTIVE)


def department_owned_condition(department: Office) -> ColumnElement[bool]:
    return exists().where(
        CaseOwnership.case_id == Case.id,
        CaseOwnership.office_id == department.id,
        CaseOwnership.status == OwnershipStatus.ACTIVE,
    )


def hearing_rows(
    session: Session, *, from_: date, to: date, case_condition: ColumnElement[bool]
) -> list[HearingRow]:
    """Decision 6's union over the cases matching `case_condition` (a condition on `Case`), one row per
    (case, date), merged in Python (three small queries, no typed UNION)."""
    live = Case.merged_into_case_id.is_(None)
    found: dict[tuple[uuid.UUID, date], HearingRow] = {}

    def keep(row: HearingRow) -> None:
        key = (row.case_id, row.date)
        cur = found.get(key)
        if cur is None or SOURCE_RANK[row.source] < SOURCE_RANK[cur.source]:
            if cur is not None:
                row.purpose = row.purpose or cur.purpose
            found[key] = row

    for case_id, d, purpose in session.execute(
        select(Case.id, Case.next_hearing_date, Case.next_purpose).where(
            Case.next_hearing_date.between(from_, to), live, case_condition
        )
    ).all():
        keep(HearingRow(case_id, d, "current_status", purpose=purpose))
    for case_id, d, court_no, printed, sr_no, section in session.execute(
        select(
            CauselistEntry.case_id,
            Causelist.list_date,
            CauselistEntry.court_no,
            CauselistEntry.printed_sr_no,
            CauselistEntry.sr_no,
            CauselistEntry.section,
        )
        .join(Causelist, Causelist.id == CauselistEntry.causelist_id)
        .join(Case, Case.id == CauselistEntry.case_id)
        .where(Causelist.list_date.between(from_, to), live, case_condition)
        .order_by(Causelist.list_date, CauselistEntry.sr_no)
    ).all():
        keep(
            HearingRow(
                case_id, d, "causelist", court_no=court_no, item_no=printed or str(sr_no), purpose=section
            )
        )
    latest = (
        select(NextDate.case_id, NextDate.next_date)
        .where(NextDate.source.in_(NEXT_DATE_SOURCES), NextDate.review_status.in_(NEXT_DATE_REVIEW))
        .ext(distinct_on(NextDate.case_id))
        .order_by(NextDate.case_id, NextDate.created_at.desc(), NextDate.id.desc())
        .subquery()
    )
    for case_id, d in session.execute(
        select(latest.c.case_id, latest.c.next_date)
        .join(Case, Case.id == latest.c.case_id)
        .where(latest.c.next_date.between(from_, to), live, case_condition)
    ).all():
        keep(HearingRow(case_id, d, "next_date"))
    return sorted(found.values(), key=lambda r: (r.date, str(r.case_id)))


def working_condition(session: Session, user: User) -> ColumnElement[bool] | None:
    """The OR of the caller's working bases (owner, allotted, custody, counsel); None when the
    caller has none."""
    conds = [c for name, c in visibility.visibility_bases(session, user) if name in visibility.WORKING_BASES]
    if not conds:
        return None
    return conds[0] if len(conds) == 1 else or_(*conds)


def flags(d: date, now: datetime, *, critical_hours: int, sitting_time: str) -> tuple[bool, bool]:
    today = rules.today_ist(now)
    due = rules.hearing_due_at(d, sitting_time)
    critical = d >= today and due - now <= timedelta(hours=critical_hours)
    this_week = today <= d <= today + timedelta(days=DEFAULT_RANGE_DAYS)
    return critical, this_week


def calendar_for_user(
    session: Session,
    user: User,
    *,
    from_: date | None = None,
    to: date | None = None,
    office: str | None = None,
    now: datetime | None = None,
    critical_hours: int = 48,
    sitting_time: str = "10:30",
) -> list[dict[str, Any]]:
    """Decision 20. A State-wide reader passes `office` (a department code) and gets that department's owned
    cases' hearings; without it the list is empty. Anyone else gets the hearings of their working cases;
    `office` from them is refused (403)."""
    now = now or datetime.now(UTC)
    today = rules.today_ist(now)
    from_ = from_ or today
    to = to or from_ + timedelta(days=DEFAULT_RANGE_DAYS)
    if to < from_:
        raise CalendarError("`to` is before `from`")
    if (to - from_).days > MAX_RANGE_DAYS:
        raise CalendarError(f"the range is at most {MAX_RANGE_DAYS} days")
    if visibility.state_wide(session, user):
        if not office:
            return []
        dept = find_office(session, office)
        if dept is None:
            raise CalendarError(f"no office {office!r}")
        cond = department_owned_condition(dept)
    else:
        if office:
            raise Forbidden("cases.view_all is needed to read another office's calendar")
        cond = working_condition(session, user)
        if cond is None:
            return []
    rows = hearing_rows(session, from_=from_, to=to, case_condition=cond)
    cases = (
        {c.id: c for c in session.scalars(select(Case).where(Case.id.in_({r.case_id for r in rows}))).all()}
        if rows
        else {}
    )
    items = []
    for r in rows:
        case = cases.get(r.case_id)
        if case is None:
            continue
        critical, this_week = flags(r.date, now, critical_hours=critical_hours, sitting_time=sitting_time)
        items.append(
            {
                "date": r.date,
                "case": case_ref(case),
                "source": r.source,
                "court_no": r.court_no,
                "item_no": r.item_no,
                "purpose": r.purpose,
                "critical": critical,
                "this_week": this_week,
            }
        )
    return items


def case_ref(case: Case) -> dict[str, Any]:
    return {"id": case.id, "ref_no": case.ref_no, "cnr": case.cnr, "case_no_text": case.case_no_text}
