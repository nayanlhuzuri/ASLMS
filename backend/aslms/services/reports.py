"""Reports (design `reports-dashboards`, decisions 4-8 and 14): management information for departments and State
oversight, plan §5.10.

Four reports (`CATALOGUE`): `pending-cases` (group x court x age band, as of now), `hearings-disposals` (dated
facts of a period), `pending-actions` (files with a pending action by holder office and officer, overdue
compliance by addressed office, optionally one row per file) and `data-health` (the daily data cycle, NAPIX calls,
source failures and SourceTrace, State scope only). A case counts for its **current** active primary owner.

Scope (decision 7): `department=CODE` needs `reports.department` in a membership of that department, or
`reports.state`; no department means the State for a `reports.state` holder, else the caller's single
`reports.department` department. Aggregates cover the scope the function grants; every row that names a case is
ANDed with the caller's case visibility (decision 8). Builders set the statement timeout first and only SELECT;
they never read a custody remark, a note, a draft or a document description. The export audit row is written
by the caller (router or CLI) after the file is built (`report_export.audit_export`)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

from sqlalchemy import Date, and_, case, cast, exists, false, func, literal_column, select
from sqlalchemy.orm import Session, aliased

from aslms.core.config import Settings, get_settings
from aslms.domain.alerts import Alert
from aslms.domain.cases import Case, CaseHearing, CaseStatus
from aslms.domain.causelists import Causelist, CauselistEntry
from aslms.domain.courts import Court
from aslms.domain.ops import FetchKind, FetchQueueItem, FetchStatus, NapixCallLog, SourceFailure
from aslms.domain.org import Office, User
from aslms.domain.ownership import (
    CaseOwnership,
    OwnershipRole,
    OwnershipStatus,
    Recommendation,
    RecommendationStatus,
)
from aslms.domain.reference import Permission
from aslms.domain.workflow import PENDING_ACTION_LABELS, CustodyHistory, PendingAction, SourcetraceIngestion
from aslms.services import access, custody, sourcetrace_ingest, visibility
from aslms.services.access import Forbidden, Member
from aslms.services.dashboard import compliance_flags, open_compliance_conditions
from aslms.services.offices import find_office
from aslms.services.refno import now_ist
from aslms.services.reporting_common import (
    AGE_BANDS,
    AGE_UNKNOWN,
    IST_ZONE,
    BadDepartment,
    DepartmentRequired,
    ReportConfig,
    ReportError,
    age_band_expr,
    causelist_counts,
    causelist_day_rows,
    department_rows,
    ist_date,
    primary_owned_condition,
    primary_owner_subquery,
    today_ist,
    with_timeout,
)

ColumnKind = Literal["text", "int", "date", "days"]
ACTIVE_STATUSES = (CaseStatus.PENDING, CaseStatus.UNKNOWN)
NOT_CLAIMED_RECOMMENDED = ("NC-REC", "Not claimed — recommended")
NOT_CLAIMED_NONE = ("NC-NONE", "Not claimed — no recommendation")
NOT_ALLOTTED = ("DEPT", "Department office / not allotted")
CALL_LOG_NOTE = (
    "NAPIX call-log rows exist only from the first live call and until the retention pruning, when one is "
    "introduced."
)

CATALOGUE: dict[str, dict[str, Any]] = {
    "pending-cases": {
        "title": "Pending cases by department, court and age",
        "params": ["department"],
        "scopes": ("state", "department"),
    },
    "hearings-disposals": {
        "title": "Hearings and disposals over a period",
        "params": ["from", "to", "department"],
        "scopes": ("state", "department"),
    },
    "pending-actions": {
        "title": "Pending actions and overdue compliance by office",
        "params": ["department", "holder_department", "include_cases"],
        "scopes": ("state", "department"),
    },
    "data-health": {
        "title": "Data collection health",
        "params": ["from", "to"],
        "scopes": ("state",),
    },
}


# ------------------------------------------------------------------------------------------------ value types


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: ColumnKind = "text"

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "label": self.label, "kind": self.kind}


@dataclass
class Section:
    key: str
    title: str
    columns: list[Column]
    rows: list[dict[str, Any]]
    totals: dict[str, Any] | None = None
    note: str | None = None
    total_rows: int | None = None
    truncated: bool = False

    def __post_init__(self) -> None:
        if self.total_rows is None:
            self.total_rows = len(self.rows)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "columns": [c.to_dict() for c in self.columns],
            "rows": self.rows,
            "totals": self.totals,
            "note": self.note,
            "total_rows": self.total_rows,
            "truncated": self.truncated,
        }


@dataclass
class Report:
    key: str
    title: str
    scope: str
    department_code: str | None
    params: dict[str, Any]
    generated_at: datetime
    generated_by: dict[str, Any]
    as_of_note: str
    sections: list[Section] = field(default_factory=list)

    @property
    def rows(self) -> int:
        return sum(len(s.rows) for s in self.sections)

    @property
    def truncated(self) -> bool:
        return any(s.truncated for s in self.sections)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "scope": self.scope,
            "department_code": self.department_code,
            "params": self.params,
            "generated_at": self.generated_at,
            "generated_by": self.generated_by,
            "as_of_note": self.as_of_note,
            "sections": [s.to_dict() for s in self.sections],
        }


@dataclass(frozen=True)
class Scope:
    """What a report covers and the membership it is run through (the "generated by" of the header)."""

    kind: Literal["state", "department"]
    department: Office | None
    member: Member | None

    @property
    def department_code(self) -> str | None:
        return self.department.code if self.department is not None else None

    def label(self) -> str:
        return "State" if self.department is None else f"{self.department.name} ({self.department.code})"


# ------------------------------------------------------------------------------------------------ scope


def _state_members(session: Session, user: User | Member) -> list[Member]:
    return access.holders_in(session, user, Permission.REPORTS_STATE)


def _department_members(session: Session, user: User | Member) -> list[Member]:
    return [
        m for m in access.holders_in(session, user, Permission.REPORTS_DEPARTMENT) if m.department is not None
    ]


def check_report(key: str) -> dict[str, Any]:
    entry = CATALOGUE.get(key)
    if entry is None:
        raise ReportError("unknown_report", f"no report {key!r}", 404)
    return entry


def resolve_scope(
    session: Session, user: User | Member, report_key: str, department_code: str | None
) -> Scope:
    """Decision 7. 403 without the function; 400 `bad_department`, `department_required` (with candidates) or
    `department_not_allowed` (data-health)."""
    entry = check_report(report_key)
    state_members = _state_members(session, user)
    dept_members = _department_members(session, user)
    if "department" not in entry["scopes"]:
        if department_code:
            raise ReportError(
                "department_not_allowed", f"{report_key} describes the whole system; it takes no department"
            )
        if not state_members:
            raise Forbidden("reports.state is not enabled for you")
        return Scope("state", None, state_members[0])
    if department_code:
        office = find_office(session, department_code)
        if office is None or not access.is_department(office):
            raise BadDepartment(department_code)
        mine = next((m for m in dept_members if m.department.id == office.id), None)
        if mine is not None:
            return Scope("department", office, mine)
        if state_members:
            return Scope("department", office, state_members[0])
        raise Forbidden(f"reports.department is not enabled for you in {office.code}")
    if state_members:
        return Scope("state", None, state_members[0])
    depts: list[tuple[Office, Member]] = []
    for m in dept_members:
        if all(d.id != m.department.id for d, _ in depts):
            depts.append((m.department, m))
    if len(depts) == 1:
        return Scope("department", depts[0][0], depts[0][1])
    if len(depts) > 1:
        raise DepartmentRequired([d.code for d, _ in depts])
    raise Forbidden("reports.department or reports.state is not enabled for you")


def catalogue_for(session: Session, user: User | Member) -> list[dict[str, Any]]:
    """The reports the caller may run, their parameters, scopes and the departments they may name."""
    state = bool(_state_members(session, user))
    own = []
    for m in _department_members(session, user):
        if m.department.code not in own:
            own.append(m.department.code)
    if not state and not own:
        raise Forbidden("reports.department or reports.state is not enabled for you")
    all_depts = [d.code for d in department_rows(session)] if state else own
    out = []
    for key, entry in CATALOGUE.items():
        scopes = []
        if state:
            scopes.append("state")
        if "department" in entry["scopes"] and (state or own):
            scopes.append("department")
        if not scopes:
            continue
        out.append(
            {
                "key": key,
                "title": entry["title"],
                "params": list(entry["params"]),
                "scopes": scopes,
                "departments": all_depts if "department" in scopes else [],
            }
        )
    return out


def check_period(from_: date | None, to: date | None, max_days: int, *, today: date | None = None) -> None:
    """`from` and `to` given, `to` not before `from`, at most `max_days` days counted inclusively, `from` not in
    the future (422 `bad_period`)."""
    today = today or today_ist()
    if from_ is None or to is None:
        raise ReportError("bad_period", "from and to are required", 422)
    if to < from_:
        raise ReportError("bad_period", "`to` is before `from`", 422)
    if (to - from_).days + 1 > max_days:
        raise ReportError("bad_period", f"the period is at most {max_days} days", 422)
    if from_ > today:
        raise ReportError("bad_period", "`from` is in the future", 422)


def _generated_by(session: Session, user: User | Member, scope: Scope) -> dict[str, Any]:
    member = scope.member or access.primary_member(session, user)
    if member is None:
        return {"name": user.full_name, "designation": None, "office_code": None}
    return {"name": member.full_name, "designation": member.designation, "office_code": member.office.code}


def _report(
    session: Session,
    user: User | Member,
    scope: Scope,
    key: str,
    params: dict[str, Any],
    as_of_note: str,
    sections: list[Section],
) -> Report:
    return Report(
        key=key,
        title=CATALOGUE[key]["title"],
        scope=scope.kind,
        department_code=scope.department_code,
        params={"department": scope.department_code, **params},
        generated_at=now_ist(),
        generated_by=_generated_by(session, user, scope),
        as_of_note=as_of_note,
        sections=sections,
    )


# ------------------------------------------------------------------------------------------------ grouping


def _ordinals(n: int) -> list:
    return [literal_column(str(i)) for i in range(1, n + 1)]


def _rec_exists(case_id) -> Any:
    return exists().where(
        Recommendation.case_id == case_id, Recommendation.status == RecommendationStatus.RECOMMENDED
    )


def _group_keys(scope: Scope, po, case_id):
    """(key1, key2, join condition, outer?) of decision 5's grouping over a fact keyed by `case_id`: the owning
    department and whether an unowned case is recommended (State), or the unit (department)."""
    if scope.department is not None:
        return (
            po.c.unit_office_id,
            false(),
            and_(po.c.case_id == case_id, po.c.office_id == scope.department.id),
            False,
        )
    rec_flag = case((po.c.office_id.is_(None), _rec_exists(case_id)), else_=false())
    return po.c.office_id, rec_flag, po.c.case_id == case_id, True


class _Groups:
    """The group rows of a report in decision 5's order: State — every department row, then the two not-claimed
    rows; department — "Department office / not allotted", then the units by path."""

    def __init__(self, session: Session, scope: Scope) -> None:
        self.session = session
        self.scope = scope
        self.offices: dict[uuid.UUID, Office] = {}
        if scope.department is None:
            self.order: list[Any] = []
            for d in department_rows(session):
                self.offices[d.id] = d
                self.order.append(d.id)
            self.order += [NOT_CLAIMED_RECOMMENDED[0], NOT_CLAIMED_NONE[0]]
        else:
            self.order = [NOT_ALLOTTED[0]]

    def key(self, k1: uuid.UUID | None, k2: bool) -> Any:
        if self.scope.department is not None:
            return k1 if k1 is not None else NOT_ALLOTTED[0]
        if k1 is not None:
            return k1
        return NOT_CLAIMED_RECOMMENDED[0] if k2 else NOT_CLAIMED_NONE[0]

    def finish(self, used: set[Any]) -> list[Any]:
        """The ordered keys: the fixed rows, then any further office seen (units in path order)."""
        extra = [k for k in used if isinstance(k, uuid.UUID) and k not in self.order]
        if extra:
            for o in self.session.scalars(select(Office).where(Office.id.in_(extra))).all():
                self.offices[o.id] = o
            extra.sort(key=lambda i: (self.offices[i].path, self.offices[i].code))
        return self.order + extra

    def label(self, key: Any) -> tuple[str, str]:
        if isinstance(key, uuid.UUID):
            o = self.offices.get(key) or self.session.get(Office, key)
            return (o.code, o.name) if o is not None else (str(key), str(key))
        for code, label in (NOT_CLAIMED_RECOMMENDED, NOT_CLAIMED_NONE, NOT_ALLOTTED):
            if key == code:
                return code, label
        return str(key), str(key)  # pragma: no cover


def _group_columns(scope: Scope) -> list[Column]:
    if scope.department is None:
        return [Column("group_code", "Department code"), Column("group", "Department")]
    return [Column("group_code", "Unit code"), Column("group", "Unit")]


def _totals(columns: list[Column], rows: list[dict[str, Any]], label_key: str, label: str = "Total") -> dict:
    out: dict[str, Any] = {c.key: None for c in columns}
    for c in columns:
        if c.kind == "int":
            out[c.key] = sum(int(r.get(c.key) or 0) for r in rows)
    out[label_key] = label
    return out


# ------------------------------------------------------------------------------------------------ pending cases


PENDING_MEASURES = (
    [
        Column("total", "Active cases", "int"),
        Column("pending", "Status pending", "int"),
        Column("unknown", "Status unknown", "int"),
        Column("provisional", "Provisional", "int"),
        Column("watching", "Watching (not owned)", "int"),
    ]
    + [Column(k, label, "int") for k, label, _l, _h in AGE_BANDS]
    + [Column(AGE_UNKNOWN[0], AGE_UNKNOWN[1], "int")]
)


def pending_cases(
    session: Session,
    user: User | Member,
    scope: Scope,
    *,
    today: date | None = None,
    config: ReportConfig | None = None,
) -> Report:
    """Decision 5, `pending-cases`: non-merged cases with status `pending` or `unknown`, as they stand now, by
    group x court x age band; watched cases in their own column, never counted as owned."""
    cfg = config or ReportConfig.from_settings()
    with_timeout(session, cfg.statement_timeout_seconds)
    today = today or today_ist()
    po = primary_owner_subquery()
    k1, k2, on, outer = _group_keys(scope, po, Case.id)
    band = age_band_expr(today)
    stmt = select(k1, k2, Case.court_id, Case.status, Case.is_provisional, band, func.count()).select_from(
        Case
    )
    stmt = stmt.join(po, on, isouter=outer)
    stmt = stmt.where(Case.merged_into_case_id.is_(None), Case.status.in_(ACTIVE_STATUSES)).group_by(
        *_ordinals(6)
    )
    groups = _Groups(session, scope)
    blank = {c.key: 0 for c in PENDING_MEASURES}
    by_group: dict[Any, dict[str, int]] = defaultdict(lambda: dict(blank))
    by_court: dict[tuple[Any, uuid.UUID], dict[str, int]] = defaultdict(lambda: dict(blank))
    for g1, g2, court_id, status, provisional, band_key, n in session.execute(stmt).all():
        key = groups.key(g1, bool(g2))
        for bucket in (by_group[key], by_court[(key, court_id)]):
            bucket["total"] += n
            bucket["pending" if CaseStatus(status) == CaseStatus.PENDING else "unknown"] += n
            if provisional:
                bucket["provisional"] += n
            bucket[band_key] += n
    watch = select(
        CaseOwnership.unit_office_id if scope.department is not None else CaseOwnership.office_id,
        Case.court_id,
        func.count(func.distinct(Case.id)),
    ).join(Case, Case.id == CaseOwnership.case_id)
    watch = watch.where(
        CaseOwnership.role == OwnershipRole.WATCHER,
        CaseOwnership.status == OwnershipStatus.ACTIVE,
        Case.merged_into_case_id.is_(None),
        Case.status.in_(ACTIVE_STATUSES),
    )
    if scope.department is not None:
        watch = watch.where(CaseOwnership.office_id == scope.department.id)
    for g1, court_id, n in session.execute(watch.group_by(*_ordinals(2))).all():
        key = groups.key(g1, False)
        by_group[key]["watching"] += n
        by_court[(key, court_id)]["watching"] += n
    courts = {
        cid: (code, name)
        for cid, code, name in session.execute(select(Court.id, Court.est_code, Court.name)).all()
    }
    order = groups.finish(set(by_group) | {k for k, _ in by_court})
    gcols = _group_columns(scope)
    group_rows = []
    for key in order:
        code, label = groups.label(key)
        group_rows.append({"group_code": code, "group": label, **(by_group.get(key) or blank)})
    court_rows = []
    for key in order:
        code, label = groups.label(key)
        for (_gk, court_id), counts in sorted(
            ((k, v) for k, v in by_court.items() if k[0] == key),
            key=lambda kv: courts.get(kv[0][1], ("", ""))[0],
        ):
            ccode, cname = courts.get(court_id, ("", ""))
            court_rows.append(
                {"group_code": code, "group": label, "court_code": ccode, "court_name": cname, **counts}
            )
    court_cols = (
        gcols + [Column("court_code", "Court code"), Column("court_name", "Court")] + PENDING_MEASURES
    )
    note = (
        "Active cases: status pending or unknown, merged duplicates excluded. 'Active cases' = pending + unknown; "
        "the age bands (NJDG) count from the registration date, else the filing date, else the first listing. "
        "'Watching' counts cases the group follows without owning them; they are not in 'Active cases'."
    )
    sections = [
        Section(
            "by_group",
            "By " + ("department" if scope.department is None else "unit"),
            gcols + PENDING_MEASURES,
            group_rows,
            totals=_totals(gcols + PENDING_MEASURES, group_rows, "group"),
            note=note,
        ),
        Section(
            "by_group_court",
            "By " + ("department" if scope.department is None else "unit") + " and court",
            court_cols,
            court_rows,
            totals=_totals(court_cols, court_rows, "group"),
        ),
    ]
    return _report(
        session,
        user,
        scope,
        "pending-cases",
        {"as_of": today},
        f"Counts as they stand on {today.isoformat()} (IST); each case is counted for the department that owns it "
        "now (its current primary owner).",
        sections,
    )


# ------------------------------------------------------------------------------------------------ hearings


HEARING_MEASURES = [
    Column("listings", "Listings", "int"),
    Column("cases_heard", "Cases listed", "int"),
    Column("proceedings", "Proceedings (dossiers)", "int"),
    Column("disposed", "Disposed", "int"),
]


def _month_starts(from_: date, to: date) -> list[date]:
    out = []
    d = from_.replace(day=1)
    while d <= to:
        out.append(d)
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def hearings_disposals(
    session: Session,
    user: User | Member,
    scope: Scope,
    *,
    from_: date,
    to: date,
    today: date | None = None,
    config: ReportConfig | None = None,
) -> Report:
    """Decision 5, `hearings-disposals`: cause-list listings (distinct case and date), dossier proceedings
    (distinct case and business date), cases listed and disposals (`disposal_date` in the period, status
    `disposed`), per group and per calendar month. Merged duplicates are left out."""
    cfg = config or ReportConfig.from_settings()
    check_period(from_, to, cfg.max_range_days, today=today)
    with_timeout(session, cfg.statement_timeout_seconds)
    listed = (
        select(CauselistEntry.case_id.label("case_id"), Causelist.list_date.label("d"))
        .join(Causelist, Causelist.id == CauselistEntry.causelist_id)
        .where(CauselistEntry.case_id.is_not(None), Causelist.list_date.between(from_, to))
        .distinct()
        .subquery("listed")
    )
    procs = (
        select(CaseHearing.case_id.label("case_id"), CaseHearing.business_date.label("d"))
        .where(CaseHearing.business_date.between(from_, to))
        .distinct()
        .subquery("procs")
    )
    disposed = (
        select(Case.id.label("case_id"), Case.disposal_date.label("d"))
        .where(Case.disposal_date.between(from_, to), Case.status == CaseStatus.DISPOSED)
        .subquery("disposed")
    )
    groups = _Groups(session, scope)
    blank = {c.key: 0 for c in HEARING_MEASURES}
    by_group: dict[Any, dict[str, int]] = defaultdict(lambda: dict(blank))
    by_month: dict[date, dict[str, int]] = defaultdict(lambda: dict(blank))

    def run(fact, measure: str, cases_measure: str | None) -> None:
        po = primary_owner_subquery()
        k1, k2, on, outer = _group_keys(scope, po, fact.c.case_id)
        month = cast(func.date_trunc("month", fact.c.d), Date)
        measures = (func.count(), func.count(func.distinct(fact.c.case_id)))

        def base(*cols):
            return (
                select(*cols, *measures)
                .select_from(fact)
                .join(Case, Case.id == fact.c.case_id)
                .join(po, on, isouter=outer)
                .where(Case.merged_into_case_id.is_(None))
            )

        for g1, g2, n, n_cases in session.execute(base(k1, k2).group_by(*_ordinals(2))).all():
            bucket = by_group[groups.key(g1, bool(g2))]
            bucket[measure] += n
            if cases_measure:
                bucket[cases_measure] += n_cases
        for m, n, n_cases in session.execute(base(month).group_by(*_ordinals(1))).all():
            by_month[m][measure] += n
            if cases_measure:
                by_month[m][cases_measure] += n_cases

    run(listed, "listings", "cases_heard")
    run(procs, "proceedings", None)
    run(disposed, "disposed", None)
    gcols = _group_columns(scope)
    order = groups.finish(set(by_group))
    group_rows = []
    for key in order:
        code, label = groups.label(key)
        group_rows.append({"group_code": code, "group": label, **(by_group.get(key) or blank)})
    month_cols = [Column("month", "Month")] + HEARING_MEASURES
    month_rows = [
        {"month": m.strftime("%Y-%m"), **(by_month.get(m) or blank)} for m in _month_starts(from_, to)
    ]
    group_totals = _totals(gcols + HEARING_MEASURES, group_rows, "group")
    month_totals = _totals(month_cols, month_rows, "month")
    # a case listed in two months is one case of the period: the period figure comes from the group totals
    month_totals["cases_heard"] = group_totals["cases_heard"]
    sections = [
        Section(
            "by_group",
            "By " + ("department" if scope.department is None else "unit"),
            gcols + HEARING_MEASURES,
            group_rows,
            totals=group_totals,
            note=(
                "Listings: distinct case and date in a cause list of the period (the court's published listing). "
                "Proceedings: distinct case and business date from the case dossiers (a dossier may lag the "
                "list). Disposed: disposal date in the period and status disposed."
            ),
        ),
        Section(
            "by_month",
            "By calendar month",
            month_cols,
            month_rows,
            totals=month_totals,
            note="'Cases listed' in the totals row counts each case once over the whole period.",
        ),
    ]
    return _report(
        session,
        user,
        scope,
        "hearings-disposals",
        {"from": from_, "to": to},
        f"Dated facts from {from_.isoformat()} to {to.isoformat()}; each case is counted for the department that "
        "owns it now (its current primary owner).",
        sections,
    )


# ------------------------------------------------------------------------------------------------ pending actions


ACTION_COLUMNS = [
    Column("holder_department_code", "Holder department code"),
    Column("holder_department", "Holder department"),
    Column("office_code", "Holder office code"),
    Column("office_name", "Holder office"),
    Column("officer", "Officer"),
    Column("designation", "Designation"),
    Column("held", "Files with a pending action", "int"),
    Column("due_soon", "Due soon", "int"),
    Column("overdue", "Overdue", "int"),
    Column("no_due_date", "No due date", "int"),
    Column("oldest_since", "Oldest since", "date"),
    Column("max_overdue_days", "Most days overdue", "days"),
]
COMPLIANCE_COLUMNS = [
    Column("department_code", "Department code"),
    Column("office_code", "Addressed office code"),
    Column("office_name", "Addressed office"),
    Column("open", "Open", "int"),
    Column("due_soon", "Due soon", "int"),
    Column("overdue", "Overdue", "int"),
]
CASE_COLUMNS = [
    Column("case_no", "Case number"),
    Column("cnr", "CNR"),
    Column("ref_no", "Reference"),
    Column("holder_office_code", "Holder office"),
    Column("officer", "Officer"),
    Column("designation", "Designation"),
    Column("pending_action", "Pending action"),
    Column("since", "Since", "date"),
    Column("due_date", "Due date", "date"),
    Column("overdue_days", "Days overdue", "days"),
]


def _holder_department(session: Session, code: str | None) -> Office | None:
    if not code:
        return None
    office = find_office(session, code)
    if office is None or not access.is_department(office):
        raise BadDepartment(code)
    return office


def _dept_code_expr(office):
    return func.coalesce(func.nullif(func.split_part(office.path, "/", 2), ""), office.code)


def _names(session: Session, codes: set[str]) -> dict[str, str]:
    if not codes:
        return {}
    return dict(session.execute(select(Office.code, Office.name).where(Office.code.in_(codes))).all())


def pending_actions(
    session: Session,
    user: User | Member,
    scope: Scope,
    *,
    holder_department: str | None = None,
    include_cases: bool = False,
    row_cap: int | None = None,
    today: date | None = None,
    config: ReportConfig | None = None,
) -> Report:
    """Decision 5, `pending-actions`: files of the scope's primary-owned cases with a pending action, by holder
    department, office and officer (the current leg's snapshot); overdue compliance by addressed office; with
    `include_cases`, one row per file the caller may see (never the remark)."""
    cfg = config or ReportConfig.from_settings()
    with_timeout(session, cfg.statement_timeout_seconds)
    today = today or today_ist()
    hdept = _holder_department(session, holder_department)
    soon_end = today + timedelta(days=cfg.due_soon_days)
    held = custody.HELD
    leg = aliased(CustodyHistory, name="current_leg")
    holder = aliased(Office, name="holder_office")
    conds = [
        held.pending_action != PendingAction.NONE,
        primary_owned_condition(scope.department, held.case_id),
    ]
    if hdept is not None:
        conds.append(held.holder_office_id.in_(visibility.subtree_ids(hdept)))
    overdue = held.due_date < today
    dcode = _dept_code_expr(holder)
    agg = (
        select(
            dcode,
            holder.code,
            holder.name,
            leg.holder_user_name,
            leg.holder_designation,
            func.count(),
            func.count().filter(and_(held.due_date >= today, held.due_date <= soon_end)),
            func.count().filter(overdue),
            func.count().filter(held.due_date.is_(None)),
            func.min(held.since),
            func.min(case((overdue, held.due_date))),
        )
        .select_from(held)
        .join(holder, holder.id == held.holder_office_id)
        .outerjoin(leg, leg.id == held.current_leg_id)
        .where(*conds)
        .group_by(*_ordinals(5))
        .order_by(*_ordinals(2), literal_column("4"))
    )
    rows = session.execute(agg).all()
    names = _names(session, {r[0] for r in rows})
    action_rows = [
        {
            "holder_department_code": d,
            "holder_department": names.get(d, d),
            "office_code": code,
            "office_name": name,
            "officer": officer,
            "designation": designation,
            "held": n,
            "due_soon": n_soon,
            "overdue": n_late,
            "no_due_date": n_none,
            "oldest_since": ist_date(since),
            "max_overdue_days": (today - earliest).days if earliest is not None else None,
        }
        for d, code, name, officer, designation, n, n_soon, n_late, n_none, since, earliest in rows
    ]
    action_totals = _totals(ACTION_COLUMNS, action_rows, "holder_department_code")
    if action_rows:
        action_totals["oldest_since"] = min(r["oldest_since"] for r in action_rows if r["oldest_since"])
        days = [r["max_overdue_days"] for r in action_rows if r["max_overdue_days"] is not None]
        action_totals["max_overdue_days"] = max(days) if days else None
    soon, late = compliance_flags(today, cfg.due_soon_days)
    addressed = aliased(Office, name="addressed_office")
    comp = session.execute(
        select(
            _dept_code_expr(addressed),
            addressed.code,
            addressed.name,
            func.count(),
            func.count().filter(soon),
            func.count().filter(late),
        )
        .select_from(Alert)
        .join(addressed, addressed.id == Alert.office_id)
        .where(*open_compliance_conditions(), primary_owned_condition(scope.department, Alert.case_id))
        .group_by(*_ordinals(3))
        .order_by(*_ordinals(2))
    ).all()
    comp_rows = [
        {"department_code": d, "office_code": c, "office_name": n, "open": a, "due_soon": s, "overdue": o}
        for d, c, n, a, s, o in comp
    ]
    sections = [
        Section(
            "by_holder",
            "Files with a pending action by holder",
            ACTION_COLUMNS,
            action_rows,
            totals=action_totals,
            note=(
                f"Due soon: due within {cfg.due_soon_days} days (IST); overdue: due before today. Files of the "
                "scope's cases wherever they are held"
                + (f"; held in {hdept.code} only." if hdept is not None else ".")
            ),
        ),
        Section(
            "compliance",
            "Overdue compliance by office",
            COMPLIANCE_COLUMNS,
            comp_rows,
            totals=_totals(COMPLIANCE_COLUMNS, comp_rows, "department_code"),
            note="Open or acknowledged compliance alerts (registry objections) on the scope's cases, by the office "
            "each alert is addressed to; a done alert has been complied with.",
        ),
    ]
    if include_cases:
        cap = row_cap if row_cap is not None else cfg.xlsx_max_rows
        case_stmt = (
            select(held, Case, holder.code, leg.holder_user_name, leg.holder_designation)
            .select_from(held)
            .join(Case, Case.id == held.case_id)
            .join(holder, holder.id == held.holder_office_id)
            .outerjoin(leg, leg.id == held.current_leg_id)
            .where(*conds, visibility.visible_case_condition(session, user))
        )
        total = int(session.scalar(select(func.count()).select_from(case_stmt.subquery())) or 0)
        file_rows = session.execute(
            case_stmt.order_by(held.due_date.asc().nulls_last(), held.since, held.case_id).limit(cap)
        ).all()
        rows_out = []
        for h, c, hcode, officer, designation in file_rows:
            late_days = (today - h.due_date).days if h.due_date is not None and h.due_date < today else 0
            rows_out.append(
                {
                    "case_no": c.case_no_text,
                    "cnr": c.cnr,
                    "ref_no": c.ref_no,
                    "holder_office_code": hcode,
                    "officer": officer,
                    "designation": designation,
                    "pending_action": PENDING_ACTION_LABELS[PendingAction(h.pending_action)],
                    "since": ist_date(h.since),
                    "due_date": h.due_date,
                    "overdue_days": late_days,
                }
            )
        truncated = total > len(rows_out)
        sections.append(
            Section(
                "files",
                "Files with a pending action",
                CASE_COLUMNS,
                rows_out,
                note=(f"First {len(rows_out)} of {total} rows. " if truncated else "")
                + "Only cases you may open are listed.",
                total_rows=total,
                truncated=truncated,
            )
        )
    return _report(
        session,
        user,
        scope,
        "pending-actions",
        {
            "holder_department": hdept.code if hdept else None,
            "include_cases": bool(include_cases),
            "as_of": today,
        },
        f"Files and alerts as they stand on {today.isoformat()} (IST); each case is counted for the department "
        "that owns it now (its current primary owner).",
        sections,
    )


# ------------------------------------------------------------------------------------------------ data health


HEALTH_COLUMNS = [
    Column("date", "Date", "date"),
    Column("causelist_day_status", "Cause-list day"),
    Column("causelist_day_attempts", "Attempts", "int"),
    Column("lists_stored", "Lists stored", "int"),
    Column("entries_parsed", "Entries parsed", "int"),
    Column("lists_parse_failed", "Lists failed to parse", "int"),
    Column("status_batches_done", "Status batches done", "int"),
    Column("status_batches_failed", "Status batches failed", "int"),
    Column("napix_calls", "NAPIX calls", "int"),
    Column("napix_failed", "NAPIX calls failed", "int"),
    Column("napix_error_families", "Failures by family"),
    Column("dossiers_done", "Dossiers done", "int"),
    Column("dossiers_failed", "Dossiers failed", "int"),
    Column("order_pdfs_done", "Order PDFs done", "int"),
    Column("order_pdfs_failed", "Order PDFs failed", "int"),
    Column("sourcetrace_ok", "SourceTrace sent", "int"),
    Column("sourcetrace_failed", "SourceTrace failed", "int"),
]


def _ist_day(col):
    return cast(func.timezone("Asia/Kolkata", col), Date)


def _value(v: Any) -> Any:
    return v.value if hasattr(v, "value") else v


def data_health(
    session: Session,
    user: User | Member,
    scope: Scope | None = None,
    *,
    from_: date,
    to: date,
    today: date | None = None,
    settings: Settings | None = None,
    config: ReportConfig | None = None,
) -> Report:
    """Decision 5, `data-health` (State scope only): one row per date of the daily cycle's queue rows, cause
    lists, status batches, NAPIX calls (IST day), dossier and order-PDF rows finished and SourceTrace attempts;
    NAPIX calls by API; open source failures by kind; SourceTrace status now. Counts only."""
    cfg = config or ReportConfig.from_settings(settings)
    if scope is None:
        scope = resolve_scope(session, user, "data-health", None)
    if scope.department is not None:
        raise ReportError(
            "department_not_allowed", "data-health describes the whole system; it takes no department"
        )
    check_period(from_, to, cfg.health_max_days, today=today)
    with_timeout(session, cfg.statement_timeout_seconds)
    days = [from_ + timedelta(days=i) for i in range((to - from_).days + 1)]
    start = datetime.combine(from_, time.min, IST_ZONE).astimezone(UTC)
    end = datetime.combine(to + timedelta(days=1), time.min, IST_ZONE).astimezone(UTC)
    rows: dict[date, dict[str, Any]] = {
        d: {c.key: (0 if c.kind == "int" else None) for c in HEALTH_COLUMNS} | {"date": d} for d in days
    }
    for row in rows.values():
        row["causelist_day_attempts"] = None
        row["napix_error_families"] = ""
    refs = {d.isoformat(): d for d in days}
    for d, day in causelist_day_rows(session, days).items():
        rows[d]["causelist_day_status"] = day["status"]
        rows[d]["causelist_day_attempts"] = day["attempts"]
    for d, counts in causelist_counts(session, from_, to).items():
        rows[d].update(counts)
    batch_day = func.split_part(FetchQueueItem.ref, ":", 1)
    for ref, done, failed in session.execute(
        select(
            batch_day,
            func.count().filter(FetchQueueItem.status == FetchStatus.DONE),
            func.count().filter(FetchQueueItem.status == FetchStatus.FAILED),
        )
        .where(FetchQueueItem.kind == FetchKind.STATUS_BATCH, batch_day.in_(list(refs)))
        .group_by(batch_day)
    ).all():
        rows[refs[ref]].update(status_batches_done=done, status_batches_failed=failed)
    call_day = _ist_day(NapixCallLog.called_at)
    in_range = and_(NapixCallLog.called_at >= start, NapixCallLog.called_at < end)
    for d, n, failed in session.execute(
        select(call_day, func.count(), func.count().filter(NapixCallLog.ok.is_(False)))
        .where(in_range)
        .group_by(*_ordinals(1))
    ).all():
        if d in rows:
            rows[d].update(napix_calls=n, napix_failed=failed)
    families: dict[date, list[str]] = defaultdict(list)
    for d, family, n in session.execute(
        select(call_day, func.coalesce(NapixCallLog.error_family, "unknown"), func.count())
        .where(in_range, NapixCallLog.ok.is_(False))
        .group_by(*_ordinals(2))
        .order_by(*_ordinals(1), func.count().desc(), literal_column("2"))
    ).all():
        families[d].append(f"{family} {n}")
    for d, items in families.items():
        if d in rows:
            rows[d]["napix_error_families"] = ", ".join(items)
    finished_day = _ist_day(FetchQueueItem.finished_at)
    for d, kind, done, failed in session.execute(
        select(
            finished_day,
            FetchQueueItem.kind,
            func.count().filter(FetchQueueItem.status == FetchStatus.DONE),
            func.count().filter(FetchQueueItem.status == FetchStatus.FAILED),
        )
        .where(
            FetchQueueItem.kind.in_([FetchKind.DOSSIER, FetchKind.ORDER_PDF]),
            FetchQueueItem.finished_at >= start,
            FetchQueueItem.finished_at < end,
        )
        .group_by(*_ordinals(2))
    ).all():
        if d in rows:
            prefix = "dossiers" if FetchKind(kind) == FetchKind.DOSSIER else "order_pdfs"
            rows[d][f"{prefix}_done"] += done
            rows[d][f"{prefix}_failed"] += failed
    st_day = _ist_day(SourcetraceIngestion.created_at)
    for d, ok, failed in session.execute(
        select(
            st_day,
            func.count().filter(SourcetraceIngestion.ok.is_(True)),
            func.count().filter(SourcetraceIngestion.ok.is_(False)),
        )
        .where(SourcetraceIngestion.created_at >= start, SourcetraceIngestion.created_at < end)
        .group_by(*_ordinals(1))
    ).all():
        if d in rows:
            rows[d].update(sourcetrace_ok=ok, sourcetrace_failed=failed)
    day_rows = [rows[d] for d in days]
    totals = _totals(HEALTH_COLUMNS, day_rows, "causelist_day_status")
    totals["date"] = None
    totals["causelist_day_attempts"] = None

    api_cols = [
        Column("api", "API"),
        Column("calls", "Calls", "int"),
        Column("failed", "Failed", "int"),
        Column("median_ms", "Median duration (ms)", "int"),
    ]
    api_rows = [
        {
            "api": api,
            "calls": n,
            "failed": failed,
            "median_ms": int(round(median)) if median is not None else None,
        }
        for api, n, failed, median in session.execute(
            select(
                NapixCallLog.api,
                func.count(),
                func.count().filter(NapixCallLog.ok.is_(False)),
                func.percentile_cont(0.5).within_group(NapixCallLog.duration_ms),
            )
            .where(in_range)
            .group_by(NapixCallLog.api)
            .order_by(NapixCallLog.api)
        ).all()
    ]
    api_totals = _totals(api_cols, api_rows, "api")
    api_totals["median_ms"] = None
    fail_cols = [
        Column("kind", "Kind"),
        Column("open", "Open", "int"),
        Column("oldest_first_seen", "Oldest", "date"),
    ]
    fail_rows = [
        {"kind": kind, "open": n, "oldest_first_seen": ist_date(oldest)}
        for kind, n, oldest in session.execute(
            select(SourceFailure.kind, func.count(), func.min(SourceFailure.first_seen))
            .where(SourceFailure.resolved_at.is_(None))
            .group_by(SourceFailure.kind)
            .order_by(SourceFailure.kind)
        ).all()
    ]
    st = sourcetrace_ingest.status(session, settings or get_settings())
    st_cols = [Column("measure", "Measure"), Column("count", "Count", "int")]
    st_rows = [{"measure": f"documents {k}", "count": v} for k, v in st["counts"].items()] + [
        {"measure": "filings waiting for a CNR", "count": st["waiting_cnr"]},
        {"measure": "due now", "count": st["due_now"]},
    ]
    sections = [
        Section("by_date", "By date", HEALTH_COLUMNS, day_rows, totals=totals, note=CALL_LOG_NOTE),
        Section(
            "napix_by_api", "NAPIX calls by API", api_cols, api_rows, totals=api_totals, note=CALL_LOG_NOTE
        ),
        Section(
            "source_failures",
            "Open source failures by kind",
            fail_cols,
            fail_rows,
            totals=_totals(fail_cols, fail_rows, "kind"),
            note="Failures not yet resolved, whenever they were first seen.",
        ),
        Section(
            "sourcetrace",
            "SourceTrace status now",
            st_cols,
            st_rows,
            note=f"Connector state: {st['state']}. Court orders and uploaded court filings only.",
        ),
    ]
    return _report(
        session,
        user,
        scope,
        "data-health",
        {"from": from_, "to": to},
        f"Operations rows dated from {from_.isoformat()} to {to.isoformat()} (IST days); open failures and the "
        f"SourceTrace status as they stand now. {CALL_LOG_NOTE}",
        sections,
    )


def build(
    session: Session,
    user: User | Member,
    key: str,
    *,
    department: str | None = None,
    from_: date | None = None,
    to: date | None = None,
    holder_department: str | None = None,
    include_cases: bool = False,
    row_cap: int | None = None,
    config: ReportConfig | None = None,
    settings: Settings | None = None,
) -> tuple[Report, Scope]:
    """One entry point for the router and the CLI: the scope (decision 7), then the report."""
    check_report(key)
    scope = resolve_scope(session, user, key, department)
    if key == "pending-cases":
        report = pending_cases(session, user, scope, config=config)
    elif key == "hearings-disposals":
        report = hearings_disposals(session, user, scope, from_=from_, to=to, config=config)
    elif key == "pending-actions":
        report = pending_actions(
            session,
            user,
            scope,
            holder_department=holder_department,
            include_cases=include_cases,
            row_cap=row_cap,
            config=config,
        )
    else:
        if from_ is None and to is None:
            to = today_ist()
            from_ = to - timedelta(days=6)
        report = data_health(session, user, scope, from_=from_, to=to, settings=settings, config=config)
    return report, scope
