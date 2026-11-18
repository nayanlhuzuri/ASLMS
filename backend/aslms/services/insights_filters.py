"""The filters of State Insights and the per-case expressions they read (design `state-insights`, decisions 21 to 25).

- `InsightFilters` and `parse` (decision 24): one value per dimension, validated against the scope; a bad value is
  `InsightFilterError("bad_filter", param)`, a From after a To `InsightFilterError("bad_dates", "from")`.
- `Expr` (built by `expressions`): the derived columns every Insights query reads, over `cases` LEFT JOINed to its
  fact row (`insights_scope.FACTS`), its kind and subject groups, its custody row (`from_clause`): the kind of case, the
  NJDG age band, the next-hearing band, the year filed, the subject, the action status, the outcome and the State
  case test.
- `conditions` turns the filters into one SQL condition per dimension; `all_but(conds, dims)` ANDs every condition
  except the given dimensions (each chart counts with every filter except its own, decision 22).
- `chips` labels every applied filter on the server (the portal never builds labels from codes).

The action and compliance predicates are those of the dashboard (`dashboard.compliance_flags`,
`dashboard.open_compliance_conditions`, `visibility.never_owned`, `case_closure.closed_condition`); the custody row is
read by the custody service's `HELD` alias. Pure SQL building: no write, no audit; never a note, a draft, a custody
remark, a document or a document description."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, timedelta
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Integer,
    and_,
    case,
    cast,
    exists,
    extract,
    false,
    func,
    literal,
    or_,
    true,
)
from sqlalchemy.orm import Session, aliased

from aslms.domain.alerts import Alert
from aslms.domain.cases import Case, CaseStatus
from aslms.domain.insights import InsightCaseTypeGroup, InsightGroup, InsightSubjectCategory
from aslms.domain.ownership import CaseOwnership, OwnershipRole, OwnershipStatus
from aslms.domain.workflow import PendingAction
from aslms.services import access, case_closure, visibility
from aslms.services import insights_rules as R
from aslms.services.custody import HELD
from aslms.services.dashboard import compliance_flags, open_compliance_conditions
from aslms.services.insights_scope import FACTS, Scope, band_conditions, primary_claimed
from aslms.services.matching import normalise_counsel_code
from aslms.services.offices import find_office
from aslms.services.reporting_common import AGE_BANDS, AGE_KEYS, AGE_UNKNOWN

STATUSES = ("pending", "disposed", "all")
BANDS = ("claimed", "likely", "named")
BAND_LABELS = {
    "claimed": "Claimed",
    "likely": "Recommended, Not Claimed",
    "named": "Named in the Cause Title or by Counsel Code",
}
NEXT_VALUES = R.HEARING_BAND_KEYS + ("within_7",)
ACTIONS = (
    "overdue",
    "due_soon",
    "due_later",
    "no_due_date",
    "with_officer",
    "not_sent",
    "closed",
    "not_claimed",
)
COMPLIANCE = ("overdue", "due_soon")
DATE_OF = ("registration", "next_hearing", "latest_order", "disposal")
DATE_OF_WORDS = {
    "registration": "Registered",
    "next_hearing": "Next Hearing",
    "latest_order": "Latest Order",
    "disposal": "Disposed",
}
FILED_YEARS = 8
MIN_YEAR = 1950
COUNSEL_MAX = 120
ACTIVE = (CaseStatus.PENDING, CaseStatus.UNKNOWN)

KIND_LINK = aliased(InsightCaseTypeGroup, name="kind_link")
KIND_GROUP = aliased(InsightGroup, name="kind_group")
SUBJECT_CATEGORY = aliased(InsightSubjectCategory, name="subject_category")
SUBJECT_GROUP = aliased(InsightGroup, name="subject_group")
CUSTODY = HELD


class InsightFilterError(ValueError):
    """A refused filter value: HTTP 400 with `code` (`bad_filter`, `bad_dates`, `bad_sort`) naming `param`."""

    def __init__(self, code: str, param: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.param = param


@dataclass(frozen=True)
class InsightFilters:
    status: str = "pending"
    state_only: bool = True
    include_ia: bool = False
    kind: str | None = None
    age: str | None = None
    next: str | None = None
    filed: str | None = None
    dept: str | None = None
    band: str | None = None
    unit: str | None = None
    post: str | None = None
    subject: str | None = None
    counsel: str | None = None
    outcome: str | None = None
    action: str | None = None
    compliance: str | None = None
    holder: str | None = None
    date_of: str | None = None
    from_: date | None = None
    to: date | None = None

    def as_params(self) -> dict[str, Any]:
        """The filters as the query names them (`from` for `from_`), without unset values: the export's audit row."""
        out: dict[str, Any] = {}
        for f in fields(self):
            v = getattr(self, f.name)
            if v is None:
                continue
            out["from" if f.name == "from_" else f.name] = v.isoformat() if isinstance(v, date) else v
        return out


# ------------------------------------------------------------------------------------------------ parsing


def _bool(param: str, value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    v = str(value).strip().lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no"):
        return False
    raise InsightFilterError("bad_filter", param, f"{param} is true or false")


def _one_of(param: str, value: Any, allowed: tuple[str, ...] | list[str] | set[str]) -> str | None:
    if value is None or value == "":
        return None
    v = str(value).strip()
    if v not in allowed:
        raise InsightFilterError("bad_filter", param, f"{param} is not a known value")
    return v


def _date(param: str, value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise InsightFilterError("bad_filter", param, f"{param} is a date (YYYY-MM-DD)") from exc


def _group_codes(session: Session, kind: str) -> dict[str, str]:
    return dict(
        session.execute(
            InsightGroup.__table__.select()
            .with_only_columns(InsightGroup.code, InsightGroup.label)
            .where(InsightGroup.kind == kind, InsightGroup.is_active.is_(True))
        ).all()
    )


def parse(session: Session, scope: Scope, *, today: date, **params: Any) -> InsightFilters:
    """Decision 24: validates every parameter (400 `bad_filter` naming it, 400 `bad_dates` for From after To) and
    returns the normalised filters. `dept` must be a department, `band` needs `dept`, `unit` an office of the scope's
    department (department scope only), `holder` an office."""
    get = params.get
    status = _one_of("status", get("status"), STATUSES) or "pending"
    kind = _one_of("kind", get("kind"), set(_group_codes(session, "family")))
    age = _one_of("age", get("age"), AGE_KEYS + ("over_5",))
    nxt = _one_of("next", get("next"), NEXT_VALUES)
    filed = get("filed")
    if filed not in (None, ""):
        filed = str(filed).strip()
        if filed not in ("earlier", "unknown"):
            if not filed.isdigit() or not (MIN_YEAR <= int(filed) <= today.year):
                raise InsightFilterError("bad_filter", "filed", f"filed is a year from {MIN_YEAR} or earlier")
    else:
        filed = None
    dept = get("dept") or None
    band = _one_of("band", get("band"), BANDS)
    if band is not None and dept is None:
        raise InsightFilterError("bad_filter", "band", "band needs dept")
    if dept is not None:
        office = find_office(session, str(dept).strip())
        if office is None or not access.is_department(office):
            raise InsightFilterError("bad_filter", "dept", "dept is a department code")
        dept = office.code
    unit = get("unit") or None
    if unit is not None:
        if scope.is_state or scope.department is None:
            raise InsightFilterError("bad_filter", "unit", "unit is for a department's Insights")
        unit = str(unit).strip()
        if unit != "none":
            office = find_office(session, unit)
            if (
                office is None
                or office.id == scope.department.id
                or not visibility.in_subtree(office, scope.department)
            ):
                raise InsightFilterError("bad_filter", "unit", "unit is an office of the department")
            unit = office.code
    post = _one_of("post", get("post"), R.POST_CODES)
    subject = _one_of(
        "subject", get("subject"), set(_group_codes(session, "subject")) | {"none", "not_grouped"}
    )
    counsel = get("counsel")
    if counsel not in (None, ""):
        counsel = normalise_counsel_code(str(counsel))
        if not counsel or len(counsel) > COUNSEL_MAX:
            raise InsightFilterError("bad_filter", "counsel", f"counsel is 1 to {COUNSEL_MAX} characters")
    else:
        counsel = None
    outcome = _one_of("outcome", get("outcome"), R.OUTCOME_KEYS)
    action = _one_of("action", get("action"), ACTIONS)
    compliance = _one_of("compliance", get("compliance"), COMPLIANCE)
    holder = get("holder") or None
    if holder is not None:
        office = find_office(session, str(holder).strip())
        if office is None:
            raise InsightFilterError("bad_filter", "holder", "holder is an office code")
        holder = office.code
    date_of = _one_of("date_of", get("date_of"), DATE_OF)
    from_ = _date("from", get("from") if "from" in params else get("from_"))
    to = _date("to", get("to"))
    if (from_ or to) and date_of is None:
        raise InsightFilterError("bad_filter", "date_of", "date_of names the date From and To apply to")
    if from_ and to and from_ > to:
        raise InsightFilterError("bad_dates", "from", "From is after To")
    if date_of is not None and from_ is None and to is None:
        date_of = None
    return InsightFilters(
        status=status,
        state_only=_bool("state_only", get("state_only"), True),
        include_ia=_bool("include_ia", get("include_ia"), False),
        kind=kind,
        age=age,
        next=nxt,
        filed=filed,
        dept=dept,
        band=band,
        unit=unit,
        post=post,
        subject=subject,
        counsel=counsel,
        outcome=outcome,
        action=action,
        compliance=compliance,
        holder=holder,
        date_of=date_of,
        from_=from_,
        to=to,
    )


# ------------------------------------------------------------------------------------------------ expressions


def from_clause():
    """`cases` LEFT JOINed to its fact row, its kind and subject groups (active ones only) and its custody row: the
    one FROM every Insights scan uses, so the expressions below and the visibility conditions (correlated to `cases`)
    read the same rows."""
    return (
        Case.__table__.outerjoin(FACTS, FACTS.case_id == Case.id)
        .outerjoin(KIND_LINK, KIND_LINK.case_type_id == Case.case_type_id)
        .outerjoin(KIND_GROUP, and_(KIND_GROUP.id == KIND_LINK.group_id, KIND_GROUP.is_active.is_(True)))
        .outerjoin(
            SUBJECT_CATEGORY,
            and_(
                SUBJECT_CATEGORY.court_id == Case.court_id,
                SUBJECT_CATEGORY.category_code == FACTS.subject_category_code,
            ),
        )
        .outerjoin(
            SUBJECT_GROUP,
            and_(SUBJECT_GROUP.id == SUBJECT_CATEGORY.group_id, SUBJECT_GROUP.is_active.is_(True)),
        )
        .outerjoin(CUSTODY, CUSTODY.case_id == Case.id)
    )


@dataclass(frozen=True)
class Expr:
    today: date
    kind: Any
    start: Any
    age: Any
    over_5: Any
    next_band: Any
    within_7: Any
    filed: Any
    subject: Any
    action: Any
    outcome: Any
    state_case: Any
    disposed: Any
    active: Any
    never_owned: Any
    closed: Any
    overdue: Any


def expressions(today: date, soon_days: int) -> Expr:
    status = Case.status
    disposed = status == CaseStatus.DISPOSED
    active = status.in_(list(ACTIVE))
    kind = func.coalesce(KIND_GROUP.code, literal("other"))
    start = func.coalesce(Case.registration_date, Case.filing_date, Case.date_first_list)
    end = case((disposed, func.coalesce(Case.disposal_date, literal(today))), else_=literal(today))

    def years_before(n: int):
        return cast(end - func.make_interval(n), Case.registration_date.type)

    whens = [(start.is_(None), literal(AGE_UNKNOWN[0]))]
    for key, _label, _low, high in AGE_BANDS:
        if high is None:
            break
        whens.append((start > years_before(high), literal(key)))
    age = case(*whens, else_=literal(AGE_BANDS[-1][0]))
    over_5 = and_(start.is_not(None), start <= years_before(5))
    on = Case.next_hearing_on
    next_band = case(
        (disposed, literal("disposed")),
        (on.is_(None), literal("none")),
        (on < today, literal("passed")),
        (on == today, literal("today")),
        (on == today + timedelta(days=1), literal("tomorrow")),
        (on <= today + timedelta(days=R.SOON_DAYS), literal("days_2_7")),
        (on <= today + timedelta(days=R.MONTH_DAYS), literal("days_8_30")),
        else_=literal("later"),
    )
    within_7 = and_(~disposed, on.is_not(None), on >= today, on <= today + timedelta(days=R.SOON_DAYS))
    year = cast(extract("year", func.coalesce(Case.registration_date, Case.filing_date)), Integer)
    filed = case(
        (year.is_(None), literal("unknown")),
        (year > today.year - FILED_YEARS, cast(year, Case.case_no_text.type)),
        else_=literal("earlier"),
    )
    subject = case(
        (and_(kind == "contempt", FACTS.original_writ_case_id.is_(None)), literal("contempt")),
        (FACTS.subject_category_code.is_(None), literal("none")),
        (SUBJECT_GROUP.id.is_(None), literal("not_grouped")),
        else_=SUBJECT_GROUP.code,
    )
    never = visibility.never_owned()
    closed = case_closure.closed_condition(Case.id)
    pending_action = and_(CUSTODY.case_id.is_not(None), CUSTODY.pending_action != PendingAction.NONE)
    due = CUSTODY.due_date
    action = case(
        (never, literal("not_claimed")),
        (closed, literal("closed")),
        (
            pending_action,
            case(
                (due.is_(None), literal("no_due_date")),
                (due < today, literal("overdue")),
                (due <= today + timedelta(days=soon_days), literal("due_soon")),
                else_=literal("due_later"),
            ),
        ),
        (CUSTODY.holder_membership_id.is_not(None), literal("with_officer")),
        else_=literal("not_sent"),
    )
    overdue = and_(pending_action, due.is_not(None), due < today)
    outcome = literal_sql_outcome()
    state_case = or_(
        func.coalesce(func.cardinality(FACTS.state_basis), 0) > 0,
        func.coalesce(func.cardinality(FACTS.named_title_department_ids), 0) > 0,
        primary_claimed(),
    )
    return Expr(
        today=today,
        kind=kind,
        start=start,
        age=age,
        over_5=over_5,
        next_band=next_band,
        within_7=within_7,
        filed=filed,
        subject=subject,
        action=action,
        outcome=outcome,
        state_case=state_case,
        disposed=disposed,
        active=active,
        never_owned=never,
        closed=closed,
        overdue=overdue,
    )


def literal_sql_outcome():
    from sqlalchemy import literal_column

    return literal_column(R.outcome_case_sql("cases.disposal_type"))


# ------------------------------------------------------------------------------------------------ conditions

DIMENSIONS = (
    "status",
    "state_only",
    "include_ia",
    "dates",
    "kind",
    "age",
    "next",
    "filed",
    "dept",
    "unit",
    "post",
    "subject",
    "counsel",
    "outcome",
    "action",
    "compliance",
    "holder",
)


def status_condition(status: str, e: Expr) -> ColumnElement[bool]:
    if status == "pending":
        return e.active
    if status == "disposed":
        return e.disposed
    return true()


def date_column(date_of: str) -> Any:
    return {
        "registration": Case.registration_date,
        "next_hearing": Case.next_hearing_on,
        "latest_order": FACTS.latest_order_on,
        "disposal": Case.disposal_date,
    }[date_of]


def compliance_condition(value: str, today: date, soon_days: int) -> ColumnElement[bool]:
    soon, late = compliance_flags(today, soon_days)
    return exists().where(
        Alert.case_id == Case.id, *open_compliance_conditions(), late if value == "overdue" else soon
    )


def conditions(
    session: Session, f: InsightFilters, scope: Scope, e: Expr, soon_days: int
) -> dict[str, ColumnElement[bool]]:
    """Decision 22: one condition per dimension (`true()` when unset)."""
    c: dict[str, ColumnElement[bool]] = {d: true() for d in DIMENSIONS}
    c["status"] = status_condition(f.status, e)
    if f.state_only:
        c["state_only"] = e.state_case
    if not f.include_ia:
        c["include_ia"] = e.kind != "ia"
    if f.date_of and (f.from_ or f.to):
        col = date_column(f.date_of)
        parts = []
        if f.from_:
            parts.append(col >= f.from_)
        if f.to:
            parts.append(col <= f.to)
        c["dates"] = and_(*parts)
    if f.kind:
        c["kind"] = e.kind == f.kind
    if f.age:
        c["age"] = e.over_5 if f.age == "over_5" else e.age == f.age
    if f.next:
        c["next"] = e.within_7 if f.next == "within_7" else e.next_band == f.next
    if f.filed:
        c["filed"] = e.filed == f.filed
    if f.dept:
        office = find_office(session, f.dept)
        bands = band_conditions(office)
        c["dept"] = bands[f.band] if f.band else or_(bands["claimed"], bands["likely"], bands["named"])
    if f.unit and scope.department is not None:
        own = [
            CaseOwnership.case_id == Case.id,
            CaseOwnership.status == OwnershipStatus.ACTIVE,
            CaseOwnership.role == OwnershipRole.PRIMARY,
            CaseOwnership.office_id == scope.department.id,
        ]
        if f.unit == "none":
            own.append(CaseOwnership.unit_office_id.is_(None))
        else:
            unit = find_office(session, f.unit)
            own.append(CaseOwnership.unit_office_id.in_(visibility.subtree_ids(unit)))
        c["unit"] = exists().where(and_(*own))
    if f.post:
        c["post"] = func.coalesce(FACTS.posts.any(f.post), false())
    if f.subject:
        c["subject"] = e.subject == f.subject
    if f.counsel:
        c["counsel"] = func.coalesce(FACTS.counsel_codes.any(f.counsel), false())
    if f.outcome:
        c["outcome"] = and_(e.disposed, e.outcome == f.outcome)
    if f.action:
        c["action"] = e.action == f.action
    if f.compliance:
        c["compliance"] = compliance_condition(f.compliance, e.today, soon_days)
    if f.holder:
        office = find_office(session, f.holder)
        c["holder"] = CUSTODY.holder_office_id == office.id
    return c


def all_but(conds: dict[str, ColumnElement[bool]], *dims: str) -> ColumnElement[bool]:
    parts = [v for k, v in conds.items() if k not in dims]
    return and_(*parts) if parts else true()


# ------------------------------------------------------------------------------------------------ chips


def _day(d: date) -> str:
    return f"{d.day} {d.strftime('%b')} {d.year}"


def date_words(f: InsightFilters) -> str | None:
    if not f.date_of or not (f.from_ or f.to):
        return None
    what = DATE_OF_WORDS[f.date_of]
    if f.from_ and f.to:
        return f"{what}: {_day(f.from_)} to {_day(f.to)}"
    if f.from_:
        return f"{what}: From {_day(f.from_)}"
    return f"{what}: Up to {_day(f.to)}"


def _office_name(session: Session, code: str) -> str:
    office = find_office(session, code)
    return office.name if office is not None else code


def chips(session: Session, f: InsightFilters, today: date) -> list[dict[str, Any]]:
    """A chip for every applied dimension filter and the dates, each with its label in words."""
    out: list[dict[str, Any]] = []

    def chip(param: str, value: Any, label: str) -> None:
        out.append({"param": param, "value": str(value), "label": label})

    if f.kind:
        chip("kind", f.kind, f"Kind: {_group_codes(session, 'family').get(f.kind, f.kind)}")
    if f.age:
        chip("age", f.age, "Age: Over 5 Years" if f.age == "over_5" else f"Age: {R.AGE_LABELS[f.age]}")
    if f.next:
        label = "In the Next 7 Days" if f.next == "within_7" else dict(R.HEARING_BANDS)[f.next]
        chip("next", f.next, f"Next Hearing: {label}")
    if f.filed:
        word = {"earlier": f"Before {today.year - FILED_YEARS + 1}", "unknown": "Year Not Known"}.get(
            f.filed, f.filed
        )
        chip("filed", f.filed, f"Filed: {word}")
    if f.dept:
        name = _office_name(session, f.dept)
        chip("dept", f.dept, f"{name} · {BAND_LABELS[f.band]}" if f.band else name)
    if f.unit:
        chip(
            "unit",
            f.unit,
            "Unit: Not Yet Assigned to a Unit"
            if f.unit == "none"
            else f"Unit: {_office_name(session, f.unit)}",
        )
    if f.post:
        chip("post", f.post, f"Post: {R.POST_LABELS[f.post]}")
    if f.subject:
        labels = _group_codes(session, "subject") | {"none": "No Category", "not_grouped": "Not Grouped"}
        chip("subject", f.subject, f"Subject: {labels.get(f.subject, f.subject)}")
    if f.counsel:
        chip("counsel", f.counsel, f"Counsel Code: {f.counsel}")
    if f.outcome:
        chip("outcome", f.outcome, f"Outcome: {dict(R.OUTCOMES)[f.outcome]}")
    if f.action:
        chip("action", f.action, f"Action: {ACTION_LABELS[f.action]}")
    if f.compliance:
        chip("compliance", f.compliance, f"Compliance: {COMPLIANCE_LABELS[f.compliance]}")
    if f.holder:
        chip("holder", f.holder, f"Holder: {_office_name(session, f.holder)}")
    words = date_words(f)
    if words:
        chip("date_of", f.date_of, words)
    return out


ACTION_LABELS = {
    "not_claimed": "Not Claimed",
    "closed": "Closed in ASLMS",
    "overdue": "Overdue",
    "due_soon": "Due Soon",
    "due_later": "Due Later",
    "no_due_date": "Action Pending With No Due Date",
    "with_officer": "With an Officer, No Action Pending",
    "not_sent": "Claimed, Not Sent to an Officer",
}
COMPLIANCE_LABELS = {"overdue": "Overdue", "due_soon": "Due Soon"}
