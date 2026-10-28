"""The hearing calendar (design `alerts-notifications`, decisions 6 and 20). A case's hearing dates are the
union of `cases.next_hearing_date`, its listings in cause lists (`causelist_entries` → `causelists.list_date`)
and the case's one next hearing where it comes from an order or a person (design `next-date-direct`, decision 10:
`cases.next_hearing_on` with basis `order`, `around`, `confirmed` or `manual`), so a court date replaces an order
date instead of standing beside it, and a period drives the calendar and the alerts at once. `hearing_rows` is
shared by the date sweep (owned cases) and `calendar_for_user` (the caller's working cases, or one department's
owned cases for a State-wide reader); one row per (case, date), the cause-list listing preferred because it names the
court and the item."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, exists, select
from sqlalchemy.orm import Session, aliased

from aslms.domain.alerts import NextDate, NextDateSource, ReviewStatus
from aslms.domain.cases import Case, NextHearingBasis
from aslms.domain.causelists import CURRENT_LIST, Causelist, CauselistEntry
from aslms.domain.documents import Order
from aslms.domain.org import Office, User
from aslms.domain.ownership import CaseOwnership, OwnershipStatus
from aslms.domain.reference import Permission
from aslms.domain.workflow import PENDING_ACTION_LABELS, Custody, PendingAction
from aslms.services import access, my_cases, visibility
from aslms.services import alert_rules as rules
from aslms.services.access import Forbidden
from aslms.services.offices import find_office

MAX_RANGE_DAYS = 62
DEFAULT_RANGE_DAYS = 7
SOURCE_RANK = {"causelist": 0, "next_date": 1, "current_status": 2}
NEXT_DATE_SOURCES = (NextDateSource.MANUAL, NextDateSource.ORDER_SPECIFIC, NextDateSource.ORDER_PERIOD)
NEXT_DATE_OPEN = (ReviewStatus.NOT_NEEDED, ReviewStatus.PENDING, ReviewStatus.CONFIRMED)
# next-date-direct, decision 10: the bases of the one next hearing that the calendar reads (court dates come from the
# court's own two sources above)
VALUE_BASES = (
    NextHearingBasis.ORDER,
    NextHearingBasis.AROUND,
    NextHearingBasis.CONFIRMED,
    NextHearingBasis.MANUAL,
)


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
    # next-date-direct, decision 10: rows from the case's one next hearing
    basis: str | None = None
    approximate: bool = False
    order_date: date | None = None
    order_no: str | None = None
    basis_words: str | None = None

    def value_fields(self) -> dict[str, Any]:
        return {
            "basis": self.basis,
            "approximate": self.approximate,
            "order_date": self.order_date,
            "basis_words": self.basis_words,
        }


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
        .where(Causelist.list_date.between(from_, to), CURRENT_LIST, live, case_condition)
        .order_by(Causelist.list_date, CauselistEntry.sr_no)
    ).all():
        keep(
            HearingRow(
                case_id, d, "causelist", court_no=court_no, item_no=printed or str(sr_no), purpose=section
            )
        )
    from aslms.services import next_date_rules

    for case_id, d, basis, nd, rule, phrase, order_date, order_no in session.execute(
        select(
            Case.id,
            Case.next_hearing_on,
            Case.next_hearing_basis,
            NextDate.next_date,
            Order.next_date_rule,
            Order.next_date_phrase,
            Order.order_date,
            Order.order_no,
        )
        .outerjoin(NextDate, NextDate.id == Case.next_hearing_next_date_id)
        .outerjoin(Order, Order.id == NextDate.order_id)
        .where(
            Case.next_hearing_on.between(from_, to),
            Case.next_hearing_basis.in_(VALUE_BASES),
            live,
            case_condition,
        )
    ).all():
        b = NextHearingBasis(basis)
        keep(
            HearingRow(
                case_id,
                d,
                "next_date",
                basis=b.value,
                approximate=b == NextHearingBasis.AROUND,
                order_date=order_date if b != NextHearingBasis.MANUAL else None,
                order_no=order_no if b != NextHearingBasis.MANUAL else None,
                basis_words=(
                    next_date_rules.describe(rule, phrase, order_date, nd)
                    if b == NextHearingBasis.AROUND
                    else None
                ),
            )
        )
    rows = sorted(found.values(), key=lambda r: (r.date, str(r.case_id)))
    for r in rows:
        if r.source != "next_date" and r.basis is None:
            r.basis = "court"
    return rows


def working_condition(session: Session, user: User) -> ColumnElement[bool] | None:
    """The OR of the caller's working bases (owner, allotted, custody, counsel) over every membership; None when the
    caller has none. Read per membership, so a State-wide membership does not hide a department's working cases
    (design followups-oct, decision 18)."""
    return visibility.working_condition_any(session, user)


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
                **r.value_fields(),
            }
        )
    return items


def case_ref(case: Case) -> dict[str, Any]:
    return {"id": case.id, "ref_no": case.ref_no, "cnr": case.cnr, "case_no_text": case.case_no_text}


# ------------------------------------------------------------------------------------------------ my calendar
# design `portal-ui-redesign`, decision 8 and API A6: the caller's own dates of three kinds

MY_KINDS = ("hearing", "action_due", "confirm")
_KIND_RANK = {k: i for i, k in enumerate(MY_KINDS)}


def month_grid(day: date) -> tuple[date, date]:
    """The month grid around `day`: from the Monday on or before the 1st to the Sunday on or after the last day."""
    first = day.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    last = nxt - timedelta(days=1)
    return first - timedelta(days=first.weekday()), last + timedelta(days=6 - last.weekday())


def my_range(from_: date | None, to: date | None, today: date) -> tuple[date, date]:
    """A6's range: both missing → the current month's grid; one missing → the grid of the given one's month.
    At most `MAX_RANGE_DAYS`; `CalendarError` otherwise."""
    if from_ is None and to is None:
        from_, to = month_grid(today)
    elif from_ is None:
        assert to is not None
        from_ = min(month_grid(to)[0], to)
    elif to is None:
        to = max(month_grid(from_)[1], from_)
    if to < from_:
        raise CalendarError("`to` is before `from`")
    if (to - from_).days > MAX_RANGE_DAYS:
        raise CalendarError(f"the range is at most {MAX_RANGE_DAYS} days")
    return from_, to


def _due_critical(d: date, now: datetime, critical_hours: int, overdue: bool) -> bool:
    """An action due date is critical when it is overdue or its day ends (IST) within `critical_hours`."""
    if overdue:
        return True
    ends = datetime.combine(d + timedelta(days=1), datetime.min.time(), tzinfo=rules.IST)
    return ends - now <= timedelta(hours=critical_hours)


def my_calendar(
    session: Session,
    user: User,
    *,
    from_: date | None = None,
    to: date | None = None,
    now: datetime | None = None,
    critical_hours: int = 48,
    sitting_time: str = "10:30",
    review_cfg: Any = None,
) -> list[dict[str, Any]]:
    """A6. Hearings of my cases (`my_cases.my_cases_condition`), my action due dates (custody I hold with a
    pending action), and the next dates waiting for my confirmation (the review queue's `confirm` items, dated by
    the proposed date; none without `next_dates.review`). Every row is ANDed with the visibility rule. Ordered
    by date, kind (hearing, action_due, confirm), then the case number. Writes nothing."""
    from aslms.services import next_dates  # next_dates imports this module

    now = now or datetime.now(UTC)
    today = rules.today_ist(now)
    from_, to = my_range(from_, to, today)
    visible = visibility.visible_case_condition(session, user)
    live = Case.merged_into_case_id.is_(None)
    items: list[dict[str, Any]] = []
    case_ids: set[uuid.UUID] = set()

    for r in hearing_rows(
        session, from_=from_, to=to, case_condition=and_(my_cases.my_cases_condition(session, user), visible)
    ):
        critical, this_week = flags(r.date, now, critical_hours=critical_hours, sitting_time=sitting_time)
        items.append(
            {
                "date": r.date,
                "kind": "hearing",
                "case_id": r.case_id,
                "critical": critical,
                "court_no": r.court_no,
                "item_no": r.item_no,
                "purpose": r.purpose,
                "source": r.source,
                "this_week": this_week,
                **r.value_fields(),
            }
        )
        case_ids.add(r.case_id)

    due = aliased(Custody, name="cal_due")
    for case_id, d, action in session.execute(
        select(due.case_id, due.due_date, due.pending_action)
        .join(Case, Case.id == due.case_id)
        .where(
            due.holder_user_id == user.id,
            due.pending_action != PendingAction.NONE,
            due.due_date.between(from_, to),
            live,
            visible,
        )
    ).all():
        act = PendingAction(action)
        overdue = d < today
        items.append(
            {
                "date": d,
                "kind": "action_due",
                "case_id": case_id,
                "critical": _due_critical(d, now, critical_hours, overdue),
                "pending_action": act.value,
                "pending_action_label": PENDING_ACTION_LABELS[act],
                "overdue": overdue,
            }
        )
        case_ids.add(case_id)

    if access.has(session, user, Permission.NEXT_DATES_REVIEW):
        cfg = review_cfg or next_dates.NextDateConfig.from_settings()
        q = next_dates.queue_subquery(
            session,
            and_(next_dates.review_condition(session, user), visible),
            today=today,
            cfg=cfg,
            kind="confirm",
        )
        for nd_id, case_id, d, source in session.execute(
            select(q.c.id, q.c.case_id, q.c.next_date, NextDate.source)
            .join(NextDate, NextDate.id == q.c.id)
            .where(q.c.next_date.between(from_, to))
        ).all():
            critical, _ = flags(d, now, critical_hours=critical_hours, sitting_time=sitting_time)
            items.append(
                {
                    "date": d,
                    "kind": "confirm",
                    "case_id": case_id,
                    "critical": critical,
                    "next_date_id": nd_id,
                    "source": NextDateSource(source).value,
                }
            )
            case_ids.add(case_id)

    cases = (
        {c.id: c for c in session.scalars(select(Case).where(Case.id.in_(case_ids))).all()}
        if case_ids
        else {}
    )
    out = []
    for item in items:
        case = cases.get(item.pop("case_id"))
        if case is None:
            continue
        item["case"] = case_ref(case)
        out.append(item)
    out.sort(
        key=lambda i: (
            i["date"],
            _KIND_RANK[i["kind"]],
            i["case"]["case_no_text"] or "",
            i["case"]["ref_no"],
        )
    )
    return out
