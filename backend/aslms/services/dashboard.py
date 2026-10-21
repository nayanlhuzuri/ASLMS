"""Dashboards (design `reports-dashboards`, decisions 1-3 and 8-11): the first screen after sign-in, composed by
function and membership, never by user type.

- The *personal* block (`me_block`) for every case reader: own cases per department membership, files held,
  own alerts, own hearings in the next 7 days, open note drafts.
- A *department* block (`department_block`) for each department where a membership holds `cases.claim`,
  `cases.allot`, `custody.track` or `reports.department`; a `dashboard.state` holder may open any department.
  Each section is `None` when its gate fails (decision 9).
- The *State* block (`state_block`) for `dashboard.state`: one row per Department-tier office, the not-claimed
  row, hearings across the State, overdue files and compliance.

Every count is computed live in SQL from the tables the workflow writes (decision 2), reusing the inbox,
calendar, custody and alerts queries, under `SET LOCAL statement_timeout`. Counts carry no case text; every list
that names a case is ANDed with the caller's case visibility (decision 8). Nothing here writes: no row, no audit,
no event (decision 13)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Date, and_, cast, exists, func, select, true
from sqlalchemy.orm import Session, aliased

from aslms.domain.alerts import Alert, NextDate, NextDateSource, ReviewStatus
from aslms.domain.cases import Case
from aslms.domain.org import Office, User
from aslms.domain.ownership import (
    CaseOwnership,
    OwnershipRole,
    OwnershipStatus,
    Recommendation,
    RecommendationStatus,
    ScoreBand,
    TransferStatus,
)
from aslms.domain.reference import AlertKind, Permission, Role
from aslms.domain.workflow import PENDING_ACTION_LABELS, CaseNoteDraft, Custody, CustodyHistory, PendingAction
from aslms.services import access, alerts, calendar, custody, inbox, next_dates, visibility
from aslms.services.access import Forbidden, Member
from aslms.services.offices import find_office
from aslms.services.reporting_common import (
    BadDepartment,
    DepartmentRequired,
    ReportConfig,
    department_rows,
    ist_date,
    now_utc,
    office_ref,
    primary_owned_condition,
    today_ist,
    with_timeout,
)

ELIGIBLE_FUNCTIONS = (
    Permission.CASES_CLAIM,
    Permission.CASES_ALLOT,
    Permission.CUSTODY_TRACK,
    Permission.REPORTS_DEPARTMENT,
)
READ_FUNCTIONS = (Permission.CASES_VIEW_SCOPE, Permission.CASES_VIEW_ALL)
HEARING_DAYS = calendar.DEFAULT_RANGE_DAYS  # the calendar's default window: today .. today + 7
RECENT_ORDER_DAYS = 7
ORDER_SOURCES = (NextDateSource.ORDER_SPECIFIC, NextDateSource.ORDER_PERIOD)
ACTIVE_STATES = visibility.case_state_condition("active")


# ------------------------------------------------------------------------------------------------ helpers


def _count(session: Session, stmt) -> int:
    return int(session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)


def _cfg(config: ReportConfig | None) -> ReportConfig:
    return config or ReportConfig.from_settings()


def _require_reader(session: Session, user: User | Member) -> None:
    if not any(access.has(session, user, p) for p in READ_FUNCTIONS):
        raise Forbidden("cases.view_scope or cases.view_all is not enabled for you")


def _eligible(member: Member) -> bool:
    return member.department is not None and any(member.holds(p) for p in ELIGIBLE_FUNCTIONS)


def compliance_by_date() -> ColumnElement[date]:
    """`alerts.data.compliance_by_date` of a `compliance_due` alert, as a date."""
    return cast(Alert.data["compliance_by_date"].astext, Date)


def open_compliance_conditions() -> list[ColumnElement[bool]]:
    return [Alert.kind == AlertKind.COMPLIANCE_DUE, Alert.status.in_(list(alerts.OPEN_STATUSES))]


def compliance_flags(today: date, soon_days: int) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    """(due soon, overdue) over an open `compliance_due` alert: due today .. today + `soon_days`, or before
    today."""
    by = compliance_by_date()
    return and_(by >= today, by <= today + timedelta(days=soon_days)), by < today


def file_item(held: Custody, case_: Case, office_codes: dict[uuid.UUID, str], today: date) -> dict[str, Any]:
    overdue = held.due_date is not None and held.due_date < today
    return {
        "case": calendar.case_ref(case_),
        "pending_action": PendingAction(held.pending_action).value,
        "since": held.since,
        "due_date": held.due_date,
        "overdue_days": (today - held.due_date).days if overdue else 0,
        "holder_office_code": office_codes.get(held.holder_office_id),
    }


def _office_codes(session: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return dict(session.execute(select(Office.id, Office.code).where(Office.id.in_(ids))).all())


def hearing_summary(
    session: Session,
    user: User | Member,
    rows: list[calendar.HearingRow],
    *,
    now: datetime,
    cfg: ReportConfig,
) -> dict[str, Any]:
    """`total` and `critical` over every row; `items` the first `list_size` rows (critical first, then by date)
    whose case the caller may see (decision 8)."""
    flagged = [
        (r, calendar.flags(r.date, now, critical_hours=cfg.critical_hours, sitting_time=cfg.sitting_time)[0])
        for r in rows
    ]
    total = len(flagged)
    critical = sum(1 for _, c in flagged if c)
    ids = {r.case_id for r in rows}
    cases: dict[uuid.UUID, Case] = {}
    if ids:
        cases = {
            c.id: c
            for c in session.scalars(
                select(Case).where(Case.id.in_(ids), visibility.visible_case_condition(session, user))
            ).all()
        }
    ordered = sorted(flagged, key=lambda rc: (not rc[1], rc[0].date, str(rc[0].case_id)))
    items = [
        {
            "date": r.date,
            "case": calendar.case_ref(cases[r.case_id]),
            "court_no": r.court_no,
            "item_no": r.item_no,
            "critical": crit,
        }
        for r, crit in ordered
        if r.case_id in cases
    ][: cfg.list_size]
    return {"total": total, "critical": critical, "items": items}


# ------------------------------------------------------------------------------------------------ the index


def eligible_departments(session: Session, user: User | Member) -> list[Office]:
    """Decision 1: the departments where one of the caller's memberships holds `cases.claim`, `cases.allot`,
    `custody.track` or `reports.department` (primary membership first, each once)."""
    out: list[Office] = []
    for m in access.members(session, user):
        if _eligible(m) and all(d.id != m.department.id for d in out):
            out.append(m.department)
    return out


def _eligible_member(session: Session, user: User | Member, department: Office) -> Member | None:
    return next(
        (
            m
            for m in access.members(session, user)
            if _eligible(m) and m.department is not None and m.department.id == department.id
        ),
        None,
    )


def available(session: Session, user: User | Member) -> dict[str, Any]:
    """Decision 3's index: which blocks the caller has."""
    _require_reader(session, user)
    return {
        "me": True,
        "departments": [{"code": d.code, "name": d.name} for d in eligible_departments(session, user)],
        "state": access.has(session, user, Permission.DASHBOARD_STATE),
    }


def resolve_department(
    session: Session, user: User | Member, code: str | None
) -> tuple[Office, Member | None]:
    """Decision 3: the department block to read and the eligible membership in it (None for a
    `dashboard.state` holder reading another department). 400 `bad_department`, 400 `department_required`
    with the candidates, 403 otherwise."""
    _require_reader(session, user)
    state = access.has(session, user, Permission.DASHBOARD_STATE)
    if code:
        office = find_office(session, code)
        if office is None or not access.is_department(office):
            raise BadDepartment(code)
        member = _eligible_member(session, user, office)
        if member is not None:
            return office, member
        if state:
            return office, None
        raise Forbidden(f"the dashboard of {office.code} is not open to you")
    depts = eligible_departments(session, user)
    if len(depts) == 1:
        return depts[0], _eligible_member(session, user, depts[0])
    if len(depts) > 1:
        raise DepartmentRequired([d.code for d in depts])
    if state:
        raise DepartmentRequired([])
    raise Forbidden("no department dashboard is open to you")


# ------------------------------------------------------------------------------------------------ personal


def me_block(
    session: Session, user: User, *, now: datetime | None = None, config: ReportConfig | None = None
) -> dict[str, Any]:
    """Decision 10: own cases per department membership, files held, own alerts, own hearings, drafts."""
    cfg = _cfg(config)
    _require_reader(session, user)
    with_timeout(session, cfg.statement_timeout_seconds)
    now = now or now_utc()
    today = today_ist(now)

    own_cases = []
    for m in access.members(session, user):
        if m.department is None:
            continue
        entry: dict[str, Any] = {
            "department_code": m.department.code,
            "allotted_active": _count(
                session, inbox.claimed_stmt(session, m, m.department, case_state="active", whole=False)
            ),
            "allotted_disposed": _count(
                session, inbox.claimed_stmt(session, m, m.department, case_state="disposed", whole=False)
            ),
            "counsel_active": None,
        }
        if m.role == Role.STANDING_COUNSEL:
            codes = visibility.counsel_department_codes(session, m.department)
            entry["counsel_active"] = _count(
                session,
                select(Case.id).where(
                    Case.merged_into_case_id.is_(None), ACTIVE_STATES, visibility.codes_condition(codes)
                ),
            )
        own_cases.append(entry)

    held = custody.HELD
    file_conds = [held.holder_user_id == user.id, visibility.visible_case_condition(session, user)]
    total, with_action, overdue = session.execute(
        select(
            func.count(),
            func.count().filter(held.pending_action != PendingAction.NONE),
            func.count().filter(held.due_date < today),
        )
        .select_from(held)
        .join(Case, Case.id == held.case_id)
        .where(*file_conds)
    ).one()
    file_rows = session.execute(
        select(held, Case)
        .join(Case, Case.id == held.case_id)
        .where(*file_conds)
        .order_by(held.due_date.asc().nulls_last(), held.since, held.case_id)
        .limit(cfg.list_size)
    ).all()
    codes = _office_codes(session, {h.holder_office_id for h, _ in file_rows})

    alert_counts = alerts.counts_for_user(session, user)
    alert_items = [
        {
            k: item[k]
            for k in (
                "id",
                "ref_no",
                "kind",
                "kind_label",
                "severity",
                "status",
                "title",
                "due_at",
                "case",
                "case_visible",
            )
        }
        | {"created_at": item["created_at"]}
        for item in alerts.list_for_user(session, user, limit=cfg.list_size).items
    ]

    cal = calendar.calendar_for_user(
        session, user, now=now, critical_hours=cfg.critical_hours, sitting_time=cfg.sitting_time
    )
    cal_sorted = sorted(cal, key=lambda i: (not i["critical"], i["date"], str(i["case"]["id"])))
    drafts = int(
        session.scalar(
            select(func.count()).select_from(CaseNoteDraft).where(CaseNoteDraft.author_user_id == user.id)
        )
        or 0
    )
    personal = personal_headline(session, user, now=now, cfg=cfg)
    return {
        "generated_at": now,
        "cases": own_cases,
        "files": {
            "held": int(total),
            "with_pending_action": int(with_action),
            "overdue": int(overdue),
            "items": [file_item(h, c, codes, today) for h, c in file_rows],
        },
        "alerts": {"unread": alert_counts["unread"], "open": alert_counts["open"], "items": alert_items},
        "hearings": {
            "total": len(cal),
            "critical": sum(1 for i in cal if i["critical"]),
            "items": [
                {k: i[k] for k in ("date", "case", "court_no", "item_no", "critical")}
                for i in cal_sorted[: cfg.list_size]
            ],
        },
        "drafts": drafts,
        **personal,
    }


# ------------------------------------------------------------------------------------------------ headline
# design `portal-ui-redesign`, decision 23 and API A7: the personal headline, upcoming hearings and the items
# that need the caller's attention. Every list is ANDed with the caller's case visibility; nothing is written.

ATTENTION_KINDS = ("overdue_action", "confirm_next_date", "due_soon", "file_received")
RECEIVED_DAYS = 7
CONFIRM_TITLE = "Next date to confirm"
RECEIVED_TITLE = "File received"


def _due_words(days: int) -> str:
    if days <= 0:
        return "Due today"
    if days == 1:
        return "Due tomorrow"
    return f"Due in {days} days"


def _sender_text(name: str | None, designation: str | None, office_code: str | None) -> str | None:
    who = ", ".join(p for p in (name, designation) if p) or office_code
    return f"From {who}" if who else None


def _claim_counts(session: Session, user: User) -> dict[str, int] | None:
    """`to_claim`: Strong and Possible recommendations summed over the departments where one of the caller's
    memberships holds `cases.claim` (each department once); None when none does."""
    depts: dict[uuid.UUID, Office] = {}
    for m in access.members(session, user):
        if m.department is not None and m.holds(Permission.CASES_CLAIM):
            depts.setdefault(m.department.id, m.department)
    if not depts:
        return None
    high = sum(_count(session, inbox.recommended_stmt(d, band=ScoreBand.HIGH)) for d in depts.values())
    medium = sum(_count(session, inbox.recommended_stmt(d, band=ScoreBand.MEDIUM)) for d in depts.values())
    return {"high": high, "medium": medium}


def personal_headline(session: Session, user: User, *, now: datetime, cfg: ReportConfig) -> dict[str, Any]:
    """A7: `headline` (five figures, a null one when its gate fails), `upcoming` (my hearings in the next 7 days)
    and `attention` (overdue files, next dates to confirm, files due soon, files received lately), each list at
    most `list_size` long. A case shows once as `file_received`: that row leaves out any case already listed as
    overdue, as a next date to confirm or as due soon (design portal-ui-polish, decision 13); the other kinds
    may share a case, being different things to do."""
    today = today_ist(now)
    visible = visibility.visible_case_condition(session, user)
    live = Case.merged_into_case_id.is_(None)

    # my hearings, today .. today + 7 (A6)
    week = [
        i
        for i in calendar.my_calendar(
            session,
            user,
            from_=today,
            to=today + timedelta(days=HEARING_DAYS),
            now=now,
            critical_hours=cfg.critical_hours,
            sitting_time=cfg.sitting_time,
        )
        if i["kind"] == "hearing"
    ]
    upcoming = [
        {k: i[k] for k in ("date", "case", "court_no", "item_no", "critical", "this_week")}
        for i in week[: cfg.list_size]
    ]

    # files with me (the Case inbox's Files with me: held by me, visible, not merged)
    held = custody.HELD
    action = held.pending_action != PendingAction.NONE
    file_conds = [held.holder_user_id == user.id, live, visible]
    total, due_today, overdue_n, oldest = session.execute(
        select(
            func.count(),
            func.count().filter(action, held.due_date == today),
            func.count().filter(action, held.due_date < today),
            func.min(held.due_date).filter(action, held.due_date < today),
        )
        .select_from(held)
        .join(Case, Case.id == held.case_id)
        .where(*file_conds)
    ).one()

    can_review = access.has(session, user, Permission.NEXT_DATES_REVIEW)
    review_cfg = next_dates.NextDateConfig.from_settings()
    headline = {
        "to_claim": _claim_counts(session, user),
        "hearings_week": {"total": len(week), "within_48h": sum(1 for i in week if i["critical"])},
        "files_with_me": {"total": int(total), "due_today": int(due_today)},
        "overdue_actions": {
            "total": int(overdue_n),
            "oldest_days": (today - oldest).days if oldest is not None else None,
        },
        "next_dates_to_confirm": (
            next_dates.queue_count(session, user, today=today, cfg=review_cfg) if can_review else None
        ),
    }

    # needs your attention, in the order of A7
    attention: list[dict[str, Any]] = []
    room = cfg.list_size
    leg = aliased(CustodyHistory, name="attention_leg")

    def file_rows(*conds, order, limit):
        if limit <= 0:
            return []
        return session.execute(
            select(
                held, Case, leg.actor_user_id, leg.actor_name, leg.actor_designation, leg.actor_office_code
            )
            .join(Case, Case.id == held.case_id)
            .outerjoin(leg, leg.id == held.current_leg_id)
            .where(*file_conds, *conds)
            .order_by(*order)
            .limit(limit)
        ).all()

    def file_entry(kind: str, h: Custody, c: Case, detail: str | None, day: date | None) -> dict[str, Any]:
        act = PendingAction(h.pending_action)
        return {
            "kind": kind,
            "case": calendar.case_ref(c),
            "title": PENDING_ACTION_LABELS[act] if act != PendingAction.NONE else RECEIVED_TITLE,
            "date": day,
            "detail": detail,
            "pending_action": act.value,
            "overdue_days": (today - h.due_date).days if h.due_date is not None and h.due_date < today else 0,
            "next_date_id": None,
        }

    listed: set[uuid.UUID] = set()
    for h, c, *_ in file_rows(
        action, held.due_date < today, order=(held.due_date, held.since, held.case_id), limit=room
    ):
        days = (today - h.due_date).days
        attention.append(
            file_entry("overdue_action", h, c, f"Overdue {days} day{'s' if days != 1 else ''}", h.due_date)
        )
        listed.add(c.id)
    room = cfg.list_size - len(attention)

    if can_review and room > 0:
        q = next_dates.queue_subquery(
            session,
            and_(next_dates.review_condition(session, user), visible),
            today=today,
            cfg=review_cfg,
            kind="confirm",
        )
        for nd_id, d, c in session.execute(
            select(q.c.id, q.c.next_date, Case)
            .join(Case, Case.id == q.c.case_id)
            .order_by(q.c.next_date, Case.case_no_text, Case.ref_no, q.c.id)
            .limit(room)
        ).all():
            attention.append(
                {
                    "kind": "confirm_next_date",
                    "case": calendar.case_ref(c),
                    "title": CONFIRM_TITLE,
                    "date": d,
                    "detail": "Suggested from an order",
                    "pending_action": None,
                    "overdue_days": 0,
                    "next_date_id": nd_id,
                }
            )
            listed.add(c.id)
        room = cfg.list_size - len(attention)

    for h, c, *_ in file_rows(
        action,
        held.due_date >= today,
        held.due_date <= today + timedelta(days=cfg.due_soon_days),
        order=(held.due_date, held.since, held.case_id),
        limit=room,
    ):
        attention.append(file_entry("due_soon", h, c, _due_words((h.due_date - today).days), h.due_date))
        listed.add(c.id)
    room = cfg.list_size - len(attention)

    received = file_rows(
        held.since >= now - timedelta(days=RECEIVED_DAYS),
        func.coalesce(leg.actor_user_id != user.id, True),
        held.case_id.not_in(listed) if listed else true(),
        order=(held.since.desc(), held.case_id),
        limit=room,
    )
    for h, c, _actor_id, name, designation, office_code in received:
        attention.append(
            file_entry("file_received", h, c, _sender_text(name, designation, office_code), ist_date(h.since))
        )

    return {"headline": headline, "upcoming": upcoming, "attention": attention}


# ------------------------------------------------------------------------------------------------ department


def _overdue_files(
    session: Session, user: User | Member, department: Office, today: date, limit: int
) -> list[dict[str, Any]]:
    """The first overdue files of the department's primary-owned cases wherever held (custody.held
    `scope=owned`, overdue), filtered by the caller's case visibility."""
    held = custody.HELD
    rows = session.execute(
        select(held, Case)
        .join(Case, Case.id == held.case_id)
        .where(
            visibility.visible_case_condition(session, user),
            primary_owned_condition(department, held.case_id),
            held.due_date < today,
            held.pending_action != PendingAction.NONE,
        )
        .order_by(held.due_date, held.since, held.case_id)
        .limit(limit)
    ).all()
    codes = _office_codes(session, {h.holder_office_id for h, _ in rows})
    return [file_item(h, c, codes, today) for h, c in rows]


def department_block(
    session: Session,
    user: User | Member,
    department: Office,
    *,
    now: datetime | None = None,
    config: ReportConfig | None = None,
) -> dict[str, Any]:
    """Decision 9: the department's recommendations, cases, hearings, pending actions, custody by office and
    items needing attention; each section `None` when its gate fails."""
    cfg = _cfg(config)
    _require_reader(session, user)
    state = access.has(session, user, Permission.DASHBOARD_STATE)
    member = _eligible_member(session, user, department)
    if member is None and not state:
        raise Forbidden(f"the dashboard of {department.code} is not open to you")
    with_timeout(session, cfg.statement_timeout_seconds)
    now = now or now_utc()
    today = today_ist(now)

    def holds(p: Permission) -> bool:
        return member is not None and member.holds(p)

    recommendations = None
    if holds(Permission.CASES_CLAIM) or state:
        recommendations = {
            "high": _count(session, inbox.recommended_stmt(department, band=ScoreBand.HIGH)),
            "medium": _count(session, inbox.recommended_stmt(department, band=ScoreBand.MEDIUM)),
            "transfers_in_open": _count(
                session, inbox.transfers_stmt(department, direction="in", status=TransferStatus.REQUESTED)
            ),
        }

    def claimed(state_: str, role: OwnershipRole):
        return inbox.claimed_stmt(session, user, department, case_state=state_, whole=True, role=role)

    cases = {
        "claimed_active": _count(session, claimed("active", OwnershipRole.PRIMARY)),
        "claimed_disposed": _count(session, claimed("disposed", OwnershipRole.PRIMARY)),
        "watching_active": _count(session, claimed("active", OwnershipRole.WATCHER)),
        "not_allotted_active": _count(
            session,
            claimed("active", OwnershipRole.PRIMARY).where(
                CaseOwnership.officer_user_id.is_(None), CaseOwnership.unit_office_id.is_(None)
            ),
        ),
    }

    rows = calendar.hearing_rows(
        session,
        from_=today,
        to=today + timedelta(days=HEARING_DAYS),
        case_condition=calendar.department_owned_condition(department),
    )
    hearings = hearing_summary(session, user, rows, now=now, cfg=cfg)

    pending_actions = None
    custody_by_office = None
    if holds(Permission.CUSTODY_TRACK) or holds(Permission.REPORTS_DEPARTMENT) or state:
        s = custody.summary_for(session, [department], soon_days=cfg.due_soon_days, today=today)[0]
        pending_actions = {
            "held": s["with_pending_action"],
            "due_soon": s["due_soon"],
            "overdue": s["overdue"],
            "no_due_date": s["pending_no_due_date"],
            "items": None,
        }
        if holds(Permission.CUSTODY_TRACK) or state:
            pending_actions["items"] = _overdue_files(session, user, department, today, cfg.list_size)
        custody_by_office = [
            {
                "holder_department_code": o["holder_department_code"],
                "office_code": o["office_code"],
                "office_name": o["office_name"],
                "held": o["held"],
                "with_pending_action": o["with_pending_action"],
                "overdue": o["overdue"],
            }
            for o in s["by_holder_office"]
        ]

    review = (
        holds(Permission.NEXT_DATES_REVIEW)
        if member is not None
        else access.has(session, user, Permission.NEXT_DATES_REVIEW)
    )
    to_review = None
    if review:
        # design next-date-extraction, decision 18: both kinds of queue item of the department's claimed cases
        to_review = next_dates.queue_count(
            session, department, today=today, cfg=next_dates.NextDateConfig.from_settings()
        )
    recent = session.execute(
        select(NextDate, Case)
        .join(Case, Case.id == NextDate.case_id)
        .where(
            NextDate.source.in_(ORDER_SOURCES),
            NextDate.review_status.not_in(list(next_dates.CLOSED_REVIEW)),
            NextDate.created_at >= now - timedelta(days=RECENT_ORDER_DAYS),
            primary_owned_condition(department, NextDate.case_id),
            visibility.visible_case_condition(session, user),
        )
        .order_by(NextDate.created_at.desc(), NextDate.id.desc())
        .limit(cfg.list_size)
    ).all()
    soon, late = compliance_flags(today, cfg.due_soon_days)
    due_soon, overdue = session.execute(
        select(func.count().filter(soon), func.count().filter(late))
        .select_from(Alert)
        .where(*open_compliance_conditions(), primary_owned_condition(department, Alert.case_id))
    ).one()
    return {
        "generated_at": now,
        "department": office_ref(department),
        "recommendations": recommendations,
        "cases": cases,
        "hearings": hearings,
        "pending_actions": pending_actions,
        "custody_by_office": custody_by_office,
        "attention": {
            "next_dates_to_review": to_review,
            "recent_order_next_dates": [
                {
                    "case": calendar.case_ref(c),
                    "next_date": nd.next_date,
                    "source": NextDateSource(nd.source).value,
                    "review_status": ReviewStatus(nd.review_status).value,
                }
                for nd, c in recent
            ],
            "compliance_due_soon": int(due_soon),
            "compliance_overdue": int(overdue),
        },
    }


# ------------------------------------------------------------------------------------------------ State


def state_block(
    session: Session, user: User | Member, *, now: datetime | None = None, config: ReportConfig | None = None
) -> dict[str, Any]:
    """Decision 11: per Department-tier office the claimed, recommended, hearing, file and compliance counts; the
    not-claimed row; hearings across the State; overdue files by owner and by holder; compliance totals."""
    cfg = _cfg(config)
    access.require(session, user, Permission.DASHBOARD_STATE)
    with_timeout(session, cfg.statement_timeout_seconds)
    now = now or now_utc()
    today = today_ist(now)
    depts = department_rows(session)
    blank = {
        "claimed_active": 0,
        "claimed_disposed": 0,
        "recommended_high": 0,
        "recommended_medium": 0,
        "hearings_7d": 0,
        "pending_actions": 0,
        "overdue_actions": 0,
        "compliance_due_soon": 0,
        "compliance_overdue": 0,
    }
    counts: dict[uuid.UUID, dict[str, int]] = {d.id: dict(blank) for d in depts}

    def bump(office_id: uuid.UUID, key: str, n: int) -> None:
        if office_id in counts:
            counts[office_id][key] += int(n)

    primary = and_(
        CaseOwnership.status == OwnershipStatus.ACTIVE, CaseOwnership.role == OwnershipRole.PRIMARY
    )
    # the Claimed tab's split (visibility.case_state_condition): active = pending or unknown, disposed = disposed
    disposed = visibility.case_state_condition("disposed")
    for office_id, n_active, n_disposed in session.execute(
        select(CaseOwnership.office_id, func.count().filter(ACTIVE_STATES), func.count().filter(disposed))
        .join(Case, Case.id == CaseOwnership.case_id)
        .where(primary)
        .group_by(CaseOwnership.office_id)
    ).all():
        bump(office_id, "claimed_active", n_active)
        bump(office_id, "claimed_disposed", n_disposed)
    for office_id, band, n in session.execute(
        select(Recommendation.office_id, Recommendation.band, func.count())
        .join(Case, Case.id == Recommendation.case_id)
        .where(Recommendation.status == RecommendationStatus.RECOMMENDED, Case.merged_into_case_id.is_(None))
        .group_by(Recommendation.office_id, Recommendation.band)
    ).all():
        if ScoreBand(band) == ScoreBand.HIGH:
            bump(office_id, "recommended_high", n)
        elif ScoreBand(band) == ScoreBand.MEDIUM:
            bump(office_id, "recommended_medium", n)

    to = today + timedelta(days=HEARING_DAYS)
    owned_rows = calendar.hearing_rows(
        session, from_=today, to=to, case_condition=calendar.owned_case_condition()
    )
    owners: dict[uuid.UUID, set[uuid.UUID]] = {}
    ids = {r.case_id for r in owned_rows}
    if ids:
        for case_id, office_id in session.execute(
            select(CaseOwnership.case_id, CaseOwnership.office_id).where(
                CaseOwnership.case_id.in_(ids), CaseOwnership.status == OwnershipStatus.ACTIVE
            )
        ).all():
            owners.setdefault(case_id, set()).add(office_id)
    for r in owned_rows:
        for office_id in owners.get(r.case_id, ()):
            bump(office_id, "hearings_7d", 1)

    held = custody.HELD
    action = held.pending_action != PendingAction.NONE
    late_file = and_(action, held.due_date < today)
    owner_join = and_(CaseOwnership.case_id == held.case_id, primary)
    for office_id, n_action, n_late in session.execute(
        select(CaseOwnership.office_id, func.count().filter(action), func.count().filter(late_file))
        .select_from(held)
        .join(CaseOwnership, owner_join)
        .group_by(CaseOwnership.office_id)
    ).all():
        bump(office_id, "pending_actions", n_action)
        bump(office_id, "overdue_actions", n_late)
    holder_office = Office
    holder_code = func.coalesce(
        func.nullif(func.split_part(holder_office.path, "/", 2), ""), holder_office.code
    )
    by_holder = [
        {"code": code, "overdue": int(n)}
        for code, n in session.execute(
            select(holder_code, func.count())
            .select_from(held)
            .join(CaseOwnership, owner_join)
            .join(holder_office, holder_office.id == held.holder_office_id)
            .where(late_file)
            .group_by(holder_code)
            .order_by(holder_code)
        ).all()
    ]

    soon, late = compliance_flags(today, cfg.due_soon_days)
    for office_id, n_soon, n_late in session.execute(
        select(CaseOwnership.office_id, func.count().filter(soon), func.count().filter(late))
        .select_from(Alert)
        .join(CaseOwnership, and_(CaseOwnership.case_id == Alert.case_id, primary))
        .where(*open_compliance_conditions())
        .group_by(CaseOwnership.office_id)
    ).all():
        bump(office_id, "compliance_due_soon", n_soon)
        bump(office_id, "compliance_overdue", n_late)
    c_soon, c_late = session.execute(
        select(func.count().filter(soon), func.count().filter(late))
        .select_from(Alert)
        .where(*open_compliance_conditions(), primary_owned_condition(None, Alert.case_id))
    ).one()

    never = and_(Case.merged_into_case_id.is_(None), ACTIVE_STATES, visibility.never_owned())
    rec = exists().where(
        Recommendation.case_id == Case.id, Recommendation.status == RecommendationStatus.RECOMMENDED
    )
    nc_active, nc_rec = session.execute(
        select(func.count(), func.count().filter(rec)).select_from(Case).where(never)
    ).one()
    nc_rows = calendar.hearing_rows(session, from_=today, to=to, case_condition=never)

    code_of = {d.id: d.code for d in depts}
    return {
        "generated_at": now,
        "by_department": [
            {"code": d.code, "name": d.name, "is_active": bool(d.is_active), **counts[d.id]} for d in depts
        ],
        "not_claimed": {
            "active": int(nc_active),
            "recommended": int(nc_rec),
            "hearing_7d": len({r.case_id for r in nc_rows}),
        },
        "hearings": hearing_summary(session, user, owned_rows, now=now, cfg=cfg),
        "overdue_actions": {
            "total": sum(c["overdue_actions"] for c in counts.values()),
            "by_owner": [
                {"code": code_of[i], "overdue": c["overdue_actions"]}
                for i, c in counts.items()
                if c["overdue_actions"]
            ],
            "by_holder": by_holder,
        },
        "compliance": {"due_soon": int(c_soon), "overdue": int(c_late)},
    }
