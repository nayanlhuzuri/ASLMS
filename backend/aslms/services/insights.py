"""State Insights: the cross-filtered counts and the case list (design `state-insights`, decisions 4, 5 and 20 to 26).

- `overview`: the headline figures, every chart (kind of case by age, next hearing, age, year filed, departments or
  units in three bands never added together, posts, subjects, counsel codes, registrations against disposals,
  outcomes) and the accountability section (action status, compliance by owning department, offices holding overdue
  files, the department scorecard), with the coverage line and the chips. Every chart counts with every filter except
  its own dimension, inside the scope, the status switch, "State Cases Only" and "Include Interlocutory Applications"
  (the trend ignores the status and the dates, the outcomes the status).
- `case_page`: 20 cases a page with the same filters, in an allow-listed sort, each with the who-has-it text built on
  the server (decision 26).

**How** (decision 25): one base scan over `cases` LEFT JOINed to its readings (`insights_filters.from_clause`), with a
boolean per filter, materialised once as a CTE; the single-valued charts come from one `GROUPING SETS` over it, each
set counting `FILTER (WHERE <every filter except its dimension>)`; the multi-valued charts, the trend, the outcomes and
the accountability are further `UNION ALL` branches over the same CTE. Everything runs in one read transaction under
`SET LOCAL statement_timeout` (`INSIGHTS_STATEMENT_TIMEOUT_SECONDS`); past it, `InsightsTimeout` (503
`insights_timeout`). No `SET` beyond `SET LOCAL`, no temporary table.

**Visibility** (decision 20): the scope's condition (the viewer's visibility, and the department's bands in a
department scope) is ANDed into the SQL of every count and list; nothing is filtered after the query. The
who-has-it text and "Recommended to" name other departments only in the State scope. Nothing here writes; opening
Insights is not audited (decision 28). It never reads a note, a draft, a custody remark, a document or a document
description."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import (
    Integer,
    String,
    and_,
    case,
    cast,
    exists,
    func,
    literal,
    literal_column,
    null,
    select,
    text,
    true,
    tuple_,
    union_all,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from aslms.core.clock import today_ist
from aslms.core.config import Settings, get_settings
from aslms.domain.alerts import Alert
from aslms.domain.cases import Case
from aslms.domain.causelists import CURRENT_LIST, Causelist
from aslms.domain.insights import InsightCaseFact, InsightGroup
from aslms.domain.org import Office, User, UserMembership
from aslms.domain.ownership import (
    CaseOwnership,
    OwnershipRole,
    OwnershipStatus,
    Recommendation,
    RecommendationStatus,
)
from aslms.domain.workflow import PENDING_ACTION_LABELS, PendingAction
from aslms.services import case_closure
from aslms.services import insights_filters as F
from aslms.services import insights_rules as R
from aslms.services.access import Member
from aslms.services.dashboard import compliance_flags, open_compliance_conditions
from aslms.services.insights_scope import FACTS, Scope
from aslms.services.reporting_common import (
    AGE_BANDS,
    AGE_UNKNOWN,
    QUERY_CANCELED,
    department_rows,
    with_timeout,
)

PAGE_SIZE = 20
SORTS = ("next", "registered", "latest_order")
TREND_MONTHS = 12
HOLDERS_SHOWN = 10
MEDIAN_MIN_CLAIMS = 3
MEDIAN_WINDOW_DAYS = 365
COURT_NAME = "Gauhati High Court"
BASIS_WORDS = {
    "party": "Parties",
    "officer": "Officer Named",
    "counsel": "Counsel Code",
    "title": "Cause Title",
    "writ": "Original Writ",
    "claimed": "Claimed",
}
BASIS_ORDER = ("party", "officer", "counsel", "title", "writ", "claimed")
NEXT_LABELS = dict(R.HEARING_BANDS)
SUBJECT_EXTRA = {"none": "No Category", "not_grouped": "Not Grouped"}


class InsightsTimeout(RuntimeError):
    """A statement ran past the Insights statement timeout (HTTP 503 `insights_timeout`)."""

    code = "insights_timeout"
    message = "This selection took too long. Narrow it and try again."


@dataclass(frozen=True)
class InsightsConfig:
    statement_timeout_seconds: int = 30
    export_timeout_seconds: int = 90
    xlsx_max_rows: int = 100_000
    pdf_max_rows: int = 2_000
    due_soon_days: int = 2
    portal_base_url: str = ""

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> InsightsConfig:
        s = settings or get_settings()
        return cls(
            statement_timeout_seconds=s.insights_statement_timeout_seconds,
            export_timeout_seconds=s.insights_export_timeout_seconds,
            xlsx_max_rows=s.insights_xlsx_max_rows,
            pdf_max_rows=s.insights_pdf_max_rows,
            due_soon_days=s.request_due_soon_days,
            portal_base_url=(s.portal_base_url or "").rstrip("/"),
        )


def _now() -> datetime:
    return datetime.now(UTC)


def guard(fn):
    """Runs `fn`; a cancelled statement (`57014`) becomes `InsightsTimeout`."""
    try:
        return fn()
    except OperationalError as exc:
        if getattr(getattr(exc, "orig", None), "sqlstate", None) == QUERY_CANCELED:
            raise InsightsTimeout(InsightsTimeout.message) from exc
        raise


# ------------------------------------------------------------------------------------------------ the base scan


def base_select(session: Session, f: F.InsightFilters, scope: Scope, e: F.Expr, soon_days: int):
    """Decision 25: one row per live case in the scope, with the derived columns and a boolean per filter (`p_<dim>`);
    no filter is applied here except the scope and `merged_into_case_id IS NULL`."""
    conds = F.conditions(session, f, scope, e, soon_days)
    soon, late = compliance_flags(e.today, soon_days)
    compliance_late = exists().where(Alert.case_id == Case.id, *open_compliance_conditions(), late)
    compliance_soon = exists().where(Alert.case_id == Case.id, *open_compliance_conditions(), soon)
    cols = [
        Case.id.label("id"),
        e.kind.label("kind"),
        e.age.label("age"),
        e.next_band.label("next"),
        e.filed.label("filed"),
        e.subject.label("subject"),
        e.action.label("action"),
        e.outcome.label("outcome"),
        e.state_case.label("state_case"),
        e.over_5.label("over_5"),
        e.within_7.label("within_7"),
        e.never_owned.label("never_owned"),
        e.disposed.label("disposed"),
        e.overdue.label("overdue"),
        compliance_late.label("compliance_late"),
        compliance_soon.label("compliance_soon"),
        Case.registration_date.label("registration_date"),
        Case.disposal_date.label("disposal_date"),
        F.CUSTODY.holder_office_id.label("holder_office_id"),
        func.coalesce(FACTS.named_title_department_ids, cast(literal([]), ARRAY(UUID(as_uuid=True)))).label(
            "named_t"
        ),
        func.coalesce(FACTS.named_counsel_department_ids, cast(literal([]), ARRAY(UUID(as_uuid=True)))).label(
            "named_c"
        ),
        func.coalesce(FACTS.posts, cast(literal([]), ARRAY(String))).label("posts"),
        func.coalesce(FACTS.government_codes, cast(literal([]), ARRAY(String))).label("gov_codes"),
        func.coalesce(func.cardinality(FACTS.title_phrases), 0).label("phrases_n"),
        *[cond.label(f"p_{dim}") for dim, cond in conds.items()],
    ]
    return (
        select(*cols).select_from(F.from_clause()).where(Case.merged_into_case_id.is_(None), scope.condition)
    )


def _pass(b, *without: str):
    parts = [b.c[f"p_{d}"] for d in F.DIMENSIONS if d not in without]
    return and_(*parts) if parts else true()


def _row(chart: str, k1: Any = None, k2: Any = None, *nums: Any):
    """One branch of the union: (chart, k1, k2, n1 .. n8)."""
    padded = list(nums) + [literal(0)] * (8 - len(nums))
    return [
        literal(chart).label("chart"),
        cast(k1 if k1 is not None else null(), String).label("k1"),
        cast(k2 if k2 is not None else null(), String).label("k2"),
        *[cast(n, Integer).label(f"n{i + 1}") for i, n in enumerate(padded)],
    ]


def _count(cond) -> Any:
    return func.count().filter(cond)


def _claimed_by(office_col, case_col):
    return exists().where(
        CaseOwnership.case_id == case_col,
        CaseOwnership.office_id == office_col,
        CaseOwnership.status == OwnershipStatus.ACTIVE,
        CaseOwnership.role == OwnershipRole.PRIMARY,
    )


def _recommended_by(office_col, case_col):
    return exists().where(
        Recommendation.case_id == case_col,
        Recommendation.office_id == office_col,
        Recommendation.status == RecommendationStatus.RECOMMENDED,
    )


def _union(b, scope: Scope, today: date):
    """Every branch of the overview over the materialised base `b` (decisions 21 to 23, 25)."""
    branches = []
    # the single-valued charts and the headline: one GROUPING SETS (decision 25)
    grouping = func.grouping(b.c.kind, b.c.age, b.c.next, b.c.filed, b.c.subject, b.c.action)
    sets = func.grouping_sets(
        tuple_(b.c.kind, b.c.age),
        tuple_(b.c.next),
        tuple_(b.c.age),
        tuple_(b.c.filed),
        tuple_(b.c.subject),
        tuple_(b.c.action),
        literal_column("()"),
    )
    all_ = _pass(b)
    gs = (
        select(
            case(
                (grouping == 15, literal("kind_age")),
                (grouping == 55, literal("next")),
                (grouping == 47, literal("age")),
                (grouping == 59, literal("filed")),
                (grouping == 61, literal("subject")),
                (grouping == 62, literal("action")),
                else_=literal("headline"),
            ).label("chart"),
            cast(
                case(
                    (grouping == 15, b.c.kind),
                    (grouping == 55, b.c.next),
                    (grouping == 47, b.c.age),
                    (grouping == 59, b.c.filed),
                    (grouping == 61, b.c.subject),
                    (grouping == 62, b.c.action),
                    else_=null(),
                ),
                String,
            ).label("k1"),
            cast(case((grouping == 15, b.c.age), else_=null()), String).label("k2"),
            cast(
                case(
                    (grouping == 15, _count(_pass(b, "kind"))),
                    (grouping == 55, _count(_pass(b, "next"))),
                    (grouping == 47, _count(_pass(b, "age"))),
                    (grouping == 59, _count(_pass(b, "filed"))),
                    (grouping == 61, _count(_pass(b, "subject"))),
                    (grouping == 62, _count(_pass(b, "action"))),
                    else_=_count(all_),
                ),
                Integer,
            ).label("n1"),
            cast(_count(and_(all_, b.c.state_case)), Integer).label("n2"),
            cast(_count(and_(all_, b.c.kind == "contempt")), Integer).label("n3"),
            cast(_count(and_(all_, b.c.over_5)), Integer).label("n4"),
            cast(_count(and_(all_, b.c.within_7)), Integer).label("n5"),
            cast(_count(and_(all_, b.c.never_owned)), Integer).label("n6"),
            cast(
                _count(and_(_pass(b, "dept"), b.c.phrases_n > 0, func.cardinality(b.c.named_t) == 0)), Integer
            ).label("n7"),
            cast(literal(0), Integer).label("n8"),
        )
        .select_from(b)
        .group_by(sets)
    )
    branches.append(gs)

    # departments in three bands (State) or the scope department's bands (decision 21)
    dept_pass = _pass(b, "dept")
    own = (
        select(
            *_row(
                "claimed",
                cast(CaseOwnership.office_id, String),
                None,
                func.count(),
                _count(b.c.kind == "contempt"),
                _count(b.c.within_7),
                _count(b.c.overdue),
                _count(b.c.compliance_late),
            )
        )
        .select_from(b)
        .join(
            CaseOwnership,
            and_(
                CaseOwnership.case_id == b.c.id,
                CaseOwnership.status == OwnershipStatus.ACTIVE,
                CaseOwnership.role == OwnershipRole.PRIMARY,
            ),
        )
        .where(dept_pass)
        .group_by(CaseOwnership.office_id)
    )
    likely = (
        select(
            *_row("likely", cast(Recommendation.office_id, String), None, func.count(func.distinct(b.c.id)))
        )
        .select_from(b)
        .join(
            Recommendation,
            and_(Recommendation.case_id == b.c.id, Recommendation.status == RecommendationStatus.RECOMMENDED),
        )
        .where(dept_pass, ~_claimed_by(Recommendation.office_id, b.c.id))
        .group_by(Recommendation.office_id)
    )
    named_ids = (
        func.unnest(func.array_cat(b.c.named_t, b.c.named_c))
        .table_valued("dept_id")
        .render_derived(name="nd", with_types=False)
    )
    named = (
        select(*_row("named", cast(named_ids.c.dept_id, String), None, func.count(func.distinct(b.c.id))))
        .select_from(b)
        .join(named_ids, true())
        .where(
            dept_pass,
            ~_claimed_by(named_ids.c.dept_id, b.c.id),
            ~_recommended_by(named_ids.c.dept_id, b.c.id),
        )
        .group_by(named_ids.c.dept_id)
    )
    branches += [own, likely, named]

    # units of the scope department: its claimed cases by the assigned unit's child office of the department
    if scope.department is not None:
        unit = Office.__table__.alias("unit_office")
        child = func.split_part(unit.c.path, "/", 3)
        unit_key = func.coalesce(func.nullif(child, ""), literal("none"))
        units = (
            select(*_row("unit", unit_key, None, func.count()))
            .select_from(b)
            .join(
                CaseOwnership,
                and_(
                    CaseOwnership.case_id == b.c.id,
                    CaseOwnership.status == OwnershipStatus.ACTIVE,
                    CaseOwnership.role == OwnershipRole.PRIMARY,
                    CaseOwnership.office_id == scope.department.id,
                ),
            )
            .outerjoin(unit, unit.c.id == CaseOwnership.unit_office_id)
            .where(_pass(b, "unit"))
            .group_by(unit_key)
        )
        branches.append(units)

    # posts and counsel codes, multi-valued (a case counts once in each)
    post_v = func.unnest(b.c.posts).table_valued("v").render_derived(name="pv", with_types=False)
    branches.append(
        select(*_row("post", post_v.c.v, None, func.count()))
        .select_from(b)
        .join(post_v, true())
        .where(_pass(b, "post"))
        .group_by(post_v.c.v)
    )
    code_v = func.unnest(b.c.gov_codes).table_valued("v").render_derived(name="cv", with_types=False)
    branches.append(
        select(*_row("counsel", code_v.c.v, None, func.count()))
        .select_from(b)
        .join(code_v, true())
        .where(_pass(b, "counsel"))
        .group_by(code_v.c.v)
    )

    # registrations against disposals per IST month, the last 12 months (ignores the status and the dates)
    first = date(today.year, today.month, 1)
    for _ in range(TREND_MONTHS - 1):
        first = (first - timedelta(days=1)).replace(day=1)
    trend_pass = _pass(b, "status", "dates")
    for chart, col in (("registered", b.c.registration_date), ("disposed", b.c.disposal_date)):
        month = func.to_char(col, "YYYY-MM")
        branches.append(
            select(*_row(chart, month, None, func.count()))
            .select_from(b)
            .where(trend_pass, col >= first, col <= today)
            .group_by(month)
        )

    # how cases end: disposed cases only, ignoring the status switch
    branches.append(
        select(*_row("outcome", b.c.outcome, None, func.count()))
        .select_from(b)
        .where(_pass(b, "status", "outcome"), b.c.disposed)
        .group_by(b.c.outcome)
    )

    # compliance with court directions by owning department (the dashboard's definitions)
    comp_pass = _pass(b, "compliance")
    branches.append(
        select(
            *_row(
                "compliance",
                cast(CaseOwnership.office_id, String),
                None,
                _count(b.c.compliance_late),
                _count(b.c.compliance_soon),
            )
        )
        .select_from(b)
        .join(
            CaseOwnership,
            and_(
                CaseOwnership.case_id == b.c.id,
                CaseOwnership.status == OwnershipStatus.ACTIVE,
                CaseOwnership.role == OwnershipRole.PRIMARY,
            ),
        )
        .where(comp_pass)
        .group_by(CaseOwnership.office_id)
    )

    # offices holding files with an overdue action (the holder's own office)
    holders = (
        select(b.c.holder_office_id.label("office_id"), func.count().label("n"))
        .select_from(b)
        .where(_pass(b, "holder"), b.c.overdue)
        .group_by(b.c.holder_office_id)
        .order_by(func.count().desc(), b.c.holder_office_id)
        .limit(HOLDERS_SHOWN)
        .subquery("top_holders")
    )
    branches.append(select(*_row("holder", cast(holders.c.office_id, String), None, holders.c.n)))
    return union_all(*branches)


def _department_names(session: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, Office]:
    if not ids:
        return {}
    return {o.id: o for o in session.scalars(select(Office).where(Office.id.in_(ids))).all()}


def _median_days(session: Session, now: datetime) -> dict[uuid.UUID, float]:
    """Decision 23: the median days from the first recommendation of the case to the department until its primary
    claim, over the department's claims in the last 365 days; only with at least 3 such claims."""
    rows = session.execute(
        text(
            """
            SELECT o.office_id, count(*), percentile_cont(0.5) WITHIN GROUP (
                       ORDER BY extract(epoch FROM o.claimed_at - r.first_at) / 86400.0)
            FROM case_ownership o
            JOIN LATERAL (SELECT min(created_at) AS first_at FROM recommendations r
                          WHERE r.case_id = o.case_id AND r.office_id = o.office_id) r ON r.first_at IS NOT NULL
            JOIN cases c ON c.id = o.case_id AND c.merged_into_case_id IS NULL
            WHERE o.role = 'primary' AND o.claimed_at >= :since AND o.claimed_at >= r.first_at
            GROUP BY o.office_id
            """
        ),
        {"since": now - timedelta(days=MEDIAN_WINDOW_DAYS)},
    ).all()
    return {
        oid: round(float(med), 1) for oid, n, med in rows if int(n) >= MEDIAN_MIN_CLAIMS and med is not None
    }


def _labels(session: Session, kind: str) -> list[tuple[str, str]]:
    return [
        (code, label)
        for code, label in session.execute(
            select(InsightGroup.code, InsightGroup.label)
            .where(InsightGroup.kind == kind, InsightGroup.is_active.is_(True))
            .order_by(InsightGroup.sort_order, InsightGroup.code)
        ).all()
    ]


def coverage(session: Session, f: F.InsightFilters) -> dict[str, Any]:
    """Decision 4: what the counts cover: the court, the earliest held cause-list date, the readings waiting and their
    freshness, and the coverage line every chart card prints."""
    listed_since = session.scalar(select(func.min(Causelist.list_date)).where(CURRENT_LIST))
    waiting = int(
        session.scalar(
            select(func.count())
            .select_from(Case)
            .outerjoin(InsightCaseFact, InsightCaseFact.case_id == Case.id)
            .where(
                Case.merged_into_case_id.is_(None),
                (InsightCaseFact.case_id.is_(None)) | (InsightCaseFact.reader_version != R.READER_VERSION),
            )
        )
        or 0
    )
    built_at = session.scalar(select(func.max(InsightCaseFact.built_at)))
    parts = []
    if listed_since is not None:
        parts.append(
            f"Cases listed since {listed_since.day} {listed_since.strftime('%b')} {listed_since.year}"
        )
    parts.append("State cases (worked out)" if f.state_only else "All cases")
    parts.append({"pending": "Pending", "disposed": "Disposed", "all": "Pending and Disposed"}[f.status])
    parts.append(
        "Interlocutory applications counted as cases"
        if f.include_ia
        else "Interlocutory applications inside their main case"
    )
    return {
        "court": COURT_NAME,
        "listed_since": listed_since,
        "facts_waiting": waiting,
        "facts_built_at": built_at,
        "line": " · ".join(parts),
    }


def _applications(session: Session, scope: Scope, e: F.Expr, base_cte, all_pass) -> tuple[int, int]:
    """Decision 5: pending IA cases whose main case is in the selection, and those whose main case is not held."""
    ia_kind = e.kind == "ia"
    inside = int(
        session.scalar(
            select(func.count())
            .select_from(F.from_clause())
            .join(base_cte, base_cte.c.id == FACTS.main_case_id)
            .where(Case.merged_into_case_id.is_(None), e.active, ia_kind, all_pass)
        )
        or 0
    )
    main = Case.__table__.alias("main_case")
    not_held = int(
        session.scalar(
            select(func.count())
            .select_from(F.from_clause().outerjoin(main, main.c.id == FACTS.main_case_id))
            .where(
                Case.merged_into_case_id.is_(None),
                e.active,
                ia_kind,
                scope.condition,
                (main.c.id.is_(None)) | (main.c.merged_into_case_id.is_not(None)),
            )
        )
        or 0
    )
    return inside, not_held


def overview(
    session: Session,
    user: User | Member,
    f: F.InsightFilters,
    scope: Scope,
    *,
    now: datetime | None = None,
    cfg: InsightsConfig | None = None,
) -> dict[str, Any]:
    """`GET /insights` (decisions 21 to 25): the whole page's counts in one read transaction."""
    cfg = cfg or InsightsConfig.from_settings()
    now = now or _now()
    today = today_ist(now)
    return guard(lambda: _overview(session, f, scope, now=now, today=today, cfg=cfg))


def _overview(
    session: Session, f: F.InsightFilters, scope: Scope, *, now: datetime, today: date, cfg: InsightsConfig
) -> dict[str, Any]:
    with_timeout(session, cfg.statement_timeout_seconds)
    e = F.expressions(today, cfg.due_soon_days)
    base = base_select(session, f, scope, e, cfg.due_soon_days)
    b = base.cte("b").prefix_with("MATERIALIZED")
    rows = session.execute(_union(b, scope, today)).all()

    headline: dict[str, int] = {}
    single: dict[str, dict[Any, int]] = {k: {} for k in ("next", "age", "filed", "subject", "action")}
    kind_age: dict[str, dict[str, int]] = {}
    bands: dict[str, dict[str, Any]] = {}
    units: dict[str, int] = {}
    multi: dict[str, dict[str, int]] = {
        "post": {},
        "counsel": {},
        "registered": {},
        "disposed": {},
        "outcome": {},
    }
    compliance: dict[str, tuple[int, int]] = {}
    holders: list[tuple[str, int]] = []
    unmapped_named = 0
    for chart, k1, k2, *n in rows:
        if chart == "headline":
            headline = {
                "cases": n[0],
                "state_cases": n[1],
                "contempt": n[2],
                "over_5_years": n[3],
                "hearing_7_days": n[4],
                "not_claimed": n[5],
            }
            unmapped_named = n[6]
        elif chart == "kind_age":
            kind_age.setdefault(k1, {})[k2] = n[0]
        elif chart in single:
            single[chart][k1] = n[0]
        elif chart in ("claimed", "likely", "named"):
            entry = bands.setdefault(k1, {"claimed": 0, "likely": 0, "named": 0, "extra": [0, 0, 0, 0]})
            entry[chart] = n[0]
            if chart == "claimed":
                entry["extra"] = n[1:5]
        elif chart == "unit":
            units[k1] = n[0]
        elif chart in multi:
            multi[chart][k1] = n[0]
        elif chart == "compliance":
            compliance[k1] = (n[0], n[1])
        elif chart == "holder":
            holders.append((k1, n[0]))

    all_pass = _pass(b)
    if not f.include_ia:
        inside, not_held = _applications(session, scope, e, b, all_pass)
    else:
        inside, not_held = 0, 0
    headline = {
        "cases": 0,
        "state_cases": 0,
        "contempt": 0,
        "over_5_years": 0,
        "hearing_7_days": 0,
        "not_claimed": 0,
        **headline,
        "applications_inside": inside,
        "applications_main_not_held": not_held,
    }

    ids = {uuid.UUID(k) for k in list(bands) + list(compliance) if k} | {
        uuid.UUID(k) for k, _ in holders if k
    }
    offices = _department_names(session, ids)

    def office_ref(key: str | None) -> dict[str, Any] | None:
        o = offices.get(uuid.UUID(key)) if key else None
        return {"code": o.code, "name": o.name} if o is not None else None

    # kind of case by age: every active kind with its bands, by total
    kinds = _labels(session, "family")
    age_keys = [b_[0] for b_ in AGE_BANDS] + [AGE_UNKNOWN[0]]
    kind_rows = []
    for code, label in kinds:
        by_age = {k: kind_age.get(code, {}).get(k, 0) for k in age_keys}
        kind_rows.append({"key": code, "label": label, "total": sum(by_age.values()), "by_age": by_age})
    kind_rows.sort(key=lambda r: (-r["total"], r["label"]))

    next_keys = [k for k in R.HEARING_BAND_KEYS if k != "disposed" or f.status == "all"]
    filed_keys = [str(today.year - i) for i in range(F.FILED_YEARS)] + ["earlier", "unknown"]
    filed_labels = {"earlier": f"Before {today.year - F.FILED_YEARS + 1}", "unknown": "Year Not Known"}
    subjects = _labels(session, "subject") + list(SUBJECT_EXTRA.items())
    action_labels = dict(F.ACTION_LABELS) | {"due_soon": f"Due Soon ({cfg.due_soon_days} Days)"}

    departments_out = None
    units_out = None
    department_bands = None
    scorecard = None
    if scope.is_state:
        depts = department_rows(session)
        departments_out = []
        for d in depts:
            entry = bands.get(str(d.id), {"claimed": 0, "likely": 0, "named": 0})
            departments_out.append(
                {
                    "code": d.code,
                    "name": d.name,
                    "claimed": entry["claimed"],
                    "likely": entry["likely"],
                    "named": entry["named"],
                }
            )
        departments_out.sort(key=lambda r: (-max(r["claimed"], r["likely"], r["named"]), r["name"]))
        medians = _median_days(session, now)
        scorecard = []
        for d in depts:
            entry = bands.get(str(d.id), {"claimed": 0, "likely": 0, "named": 0, "extra": [0, 0, 0, 0]})
            contempt_c, hearing_c, overdue_c, comp_c = entry.get("extra", [0, 0, 0, 0])
            scorecard.append(
                {
                    "code": d.code,
                    "name": d.name,
                    "claimed": entry["claimed"],
                    "likely": entry["likely"],
                    "named_only": entry["named"],
                    "contempt_claimed": contempt_c,
                    "hearing_7_days": hearing_c,
                    "overdue_actions": overdue_c,
                    "compliance_overdue": comp_c,
                    "median_days_to_claim": medians.get(d.id),
                }
            )
        scorecard.sort(key=lambda r: (-r["claimed"], -r["likely"], r["name"]))
    else:
        d = scope.department
        entry = bands.get(str(d.id), {"claimed": 0, "likely": 0, "named": 0})
        department_bands = {"claimed": entry["claimed"], "likely": entry["likely"], "named": entry["named"]}
        children = {o.code: o for o in session.scalars(select(Office).where(Office.parent_id == d.id)).all()}
        units_out = []
        for code, n in units.items():
            if code == "none":
                units_out.append({"code": "none", "name": "Not Yet Assigned to a Unit", "claimed": n})
            else:
                o = children.get(code)
                units_out.append({"code": code, "name": o.name if o else code, "claimed": n})
        units_out.sort(key=lambda r: (r["code"] == "none", -r["claimed"], r["name"]))

    months = []
    m = date(today.year, today.month, 1)
    for _ in range(TREND_MONTHS):
        months.append(m.strftime("%Y-%m"))
        m = (m - timedelta(days=1)).replace(day=1)
    months.reverse()

    compliance_out = []
    for key, (late, soon) in compliance.items():
        ref = office_ref(key)
        if ref is None or (late == 0 and soon == 0):
            continue
        compliance_out.append({**ref, "overdue": late, "due_soon": soon})
    compliance_out.sort(key=lambda r: (-r["overdue"], -r["due_soon"], r["name"]))

    holders_out = []
    if holders:
        holder_offices = _department_names(session, {uuid.UUID(k) for k, _ in holders if k})
        for key, n in holders:
            o = holder_offices.get(uuid.UUID(key)) if key else None
            if o is not None:
                holders_out.append({"code": o.code, "name": o.name, "overdue": n})

    posts_out = [
        {"key": code, "label": R.POST_LABELS[code], "count": multi["post"].get(code, 0)}
        for code in R.POST_CODES
    ]
    posts_out.sort(key=lambda r: (-r["count"], R.POST_CODES.index(r["key"])))
    counsel_out = sorted(
        ({"key": k, "label": k, "count": v} for k, v in multi["counsel"].items()),
        key=lambda r: (-r["count"], r["key"]),
    )
    outcomes_out = [
        {"key": k, "label": label, "count": multi["outcome"].get(k, 0)} for k, label in R.OUTCOMES
    ]

    return {
        "scope": scope.ref(),
        "generated_at": now,
        "coverage": coverage(session, f),
        "chips": F.chips(session, f, today),
        "headline": headline,
        "kind_by_age": {
            "bands": [{"key": k, "label": R.AGE_LABELS[k]} for k in age_keys],
            "rows": kind_rows,
        },
        "next_hearing": [
            {"key": k, "label": NEXT_LABELS[k], "count": single["next"].get(k, 0)} for k in next_keys
        ],
        "age": [{"key": k, "label": R.AGE_LABELS[k], "count": single["age"].get(k, 0)} for k in age_keys],
        "filed": [
            {"key": k, "label": filed_labels.get(k, k), "count": single["filed"].get(k, 0)}
            for k in filed_keys
        ],
        "subjects": sorted(
            ({"key": k, "label": label, "count": single["subject"].get(k, 0)} for k, label in subjects),
            key=lambda r: (-r["count"], r["label"]),
        ),
        "posts": posts_out,
        "counsel": counsel_out,
        "outcomes": outcomes_out,
        "departments": departments_out,
        "units": units_out,
        "department_bands": department_bands,
        "unmapped_named": unmapped_named,
        "trend": [
            {
                "month": mo,
                "registered": multi["registered"].get(mo, 0),
                "disposed": multi["disposed"].get(mo, 0),
            }
            for mo in months
        ],
        "accountability": {
            "action": [
                {"key": k, "label": action_labels[k], "count": single["action"].get(k, 0)}
                for k in ACTION_ORDER
            ],
            "compliance": compliance_out,
            "holders": holders_out,
            "scorecard": scorecard,
        },
    }


ACTION_ORDER = (
    "not_claimed",
    "closed",
    "overdue",
    "due_soon",
    "due_later",
    "no_due_date",
    "with_officer",
    "not_sent",
)


# ------------------------------------------------------------------------------------------------ the case list


def sort_order(sort: str, e: F.Expr, today: date) -> list[Any]:
    """Decision 26: `next` (hearings today or later soonest first, then passed dates most recent first, then no date;
    disposed cases by disposal date, newest first), `registered` (oldest first) or `latest_order` (newest first); ties
    by registration date, then id."""
    on = Case.next_hearing_on
    tail = [Case.registration_date.asc().nulls_last(), Case.id]
    if sort == "registered":
        return tail
    if sort == "latest_order":
        return [FACTS.latest_order_on.desc().nulls_last(), *tail]
    group = case(
        (e.disposed, literal(3)),
        (on.is_(None), literal(2)),
        (on >= today, literal(0)),
        else_=literal(1),
    )
    return [
        group,
        case((and_(~e.disposed, on >= today), on), else_=null()).asc().nulls_last(),
        case((and_(~e.disposed, on < today), on), else_=null()).desc().nulls_last(),
        case((e.disposed, Case.disposal_date), else_=null()).desc().nulls_last(),
        *tail,
    ]


def check_sort(sort: str | None) -> str:
    if sort in (None, ""):
        return "next"
    if sort not in SORTS:
        raise F.InsightFilterError("bad_sort", "sort", "sort is next, registered or latest_order")
    return str(sort)


def filtered_ids(session: Session, f: F.InsightFilters, scope: Scope, e: F.Expr, soon_days: int, sort: str):
    """The selection with every filter, in the list's order: a statement selecting `cases.id` (and the kind)."""
    conds = F.conditions(session, f, scope, e, soon_days)
    return (
        select(Case.id, e.kind.label("kind"))
        .select_from(F.from_clause())
        .where(Case.merged_into_case_id.is_(None), scope.condition, F.all_but(conds))
        .order_by(*sort_order(sort, e, e.today))
    )


def case_page(
    session: Session,
    user: User | Member,
    f: F.InsightFilters,
    scope: Scope,
    *,
    page: int = 1,
    sort: str | None = None,
    now: datetime | None = None,
    cfg: InsightsConfig | None = None,
) -> dict[str, Any]:
    """`GET /insights/cases`: 20 cases a page of the filtered selection (decision 26)."""
    cfg = cfg or InsightsConfig.from_settings()
    sort = check_sort(sort)
    page = max(1, int(page or 1))
    now = now or _now()
    today = today_ist(now)

    def run() -> dict[str, Any]:
        with_timeout(session, cfg.statement_timeout_seconds)
        e = F.expressions(today, cfg.due_soon_days)
        stmt = filtered_ids(session, f, scope, e, cfg.due_soon_days, sort)
        total = int(session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
        rows = session.execute(stmt.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
        items = case_items(session, [r[0] for r in rows], scope, f, today=today)
        return {"items": items, "total": total, "page": page, "page_size": PAGE_SIZE, "sort": sort}

    return guard(run)


def _kind_labels(session: Session) -> dict[str, str]:
    return dict(_labels(session, "family")) | {"other": "Other"}


def case_items(
    session: Session, ids: list[uuid.UUID], scope: Scope, f: F.InsightFilters, *, today: date
) -> list[dict[str, Any]]:
    """The list's rows for `ids`, in that order: identity, kind, status, who has it, next hearing, the departments
    named, the State bases in words and the applications pending (decisions 5, 6, 20, 26)."""
    if not ids:
        return []
    kinds = _kind_labels(session)
    e = F.expressions(today, 0)
    rows = {
        r.id: r
        for r in session.execute(
            select(
                Case.id,
                Case.ref_no,
                Case.case_no_text,
                Case.cnr,
                Case.status,
                Case.next_hearing_on,
                Case.next_hearing_basis,
                Case.disposal_date,
                e.kind.label("kind"),
                func.coalesce(FACTS.state_basis, cast(literal([]), ARRAY(String))).label("state_basis"),
                func.coalesce(
                    FACTS.named_title_department_ids, cast(literal([]), ARRAY(UUID(as_uuid=True)))
                ).label("named_t"),
                func.coalesce(FACTS.title_phrases, cast(literal([]), ARRAY(String))).label("phrases"),
            )
            .select_from(F.from_clause())
            .where(Case.id.in_(ids))
        ).all()
    }
    who = who_has_it(session, ids, scope)
    claimed = set(
        session.scalars(
            select(CaseOwnership.case_id).where(
                CaseOwnership.case_id.in_(ids),
                CaseOwnership.status == OwnershipStatus.ACTIVE,
                CaseOwnership.role == OwnershipRole.PRIMARY,
            )
        ).all()
    )
    dept_ids = {d for r in rows.values() for d in (r.named_t or [])}
    depts = _department_names(session, dept_ids)
    from aslms.services.insights_facts import load_maps

    maps = load_maps(session) if any(r.phrases for r in rows.values()) else None
    apps = applications_pending(session, ids) if not f.include_ia else {}
    out = []
    for cid in ids:
        r = rows.get(cid)
        if r is None:
            continue
        basis = basis_list(list(r.state_basis or []), bool(r.named_t), cid in claimed)
        named = [{"code": depts[d].code, "name": depts[d].name} for d in (r.named_t or []) if d in depts]
        unmapped = [p for p in (r.phrases or []) if maps is not None and maps.is_unmapped(p)]
        status = getattr(r.status, "value", r.status)
        out.append(
            {
                "case": {"id": r.id, "ref_no": r.ref_no, "case_no": r.case_no_text, "cnr": r.cnr},
                "kind": {"code": r.kind, "label": kinds.get(r.kind, r.kind)},
                "status": status,
                "who": who.get(cid, NOT_CLAIMED),
                "next_hearing": {
                    "on": r.next_hearing_on,
                    "basis": getattr(r.next_hearing_basis, "value", r.next_hearing_basis),
                },
                "disposal_date": r.disposal_date,
                "departments_named": named,
                "phrases_unmapped": unmapped,
                "applications_pending": apps.get(cid, 0) if not f.include_ia else None,
                "state_case": bool(basis),
                "state_basis": basis,
            }
        )
    return out


def basis_list(stored: list[str], named_department: bool, claimed: bool) -> list[str]:
    """The State bases in order: the stored ones, `title` also when a department is named, `claimed` live."""
    have = set(stored)
    if named_department:
        have.add("title")
    if claimed:
        have.add("claimed")
    return [b for b in BASIS_ORDER if b in have]


def basis_words(bases: list[str]) -> str:
    if not bases:
        return "No"
    return "Yes (" + ", ".join(BASIS_WORDS[b] for b in bases) + ")"


def applications_pending(session: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Decision 5: pending IA cases whose resolved main case is each of `ids` (a live count)."""
    e = F.expressions(today_ist(), 0)
    rows = session.execute(
        select(FACTS.main_case_id, func.count())
        .select_from(F.from_clause())
        .where(
            FACTS.main_case_id.in_(ids),
            Case.merged_into_case_id.is_(None),
            e.active,
            e.kind == "ia",
        )
        .group_by(FACTS.main_case_id)
    ).all()
    return {cid: int(n) for cid, n in rows}


NOT_CLAIMED = {
    "kind": "none",
    "text": "Not Claimed by Any Department",
    "officer_name": None,
    "designation": None,
    "office_code": None,
    "department_code": None,
    "recommended_to": None,
    "more": 0,
}


def who_has_it(session: Session, ids: list[uuid.UUID], scope: Scope) -> dict[uuid.UUID, dict[str, Any]]:
    """Decision 26: with an officer; closed in ASLMS; with an office; claimed; not claimed with recommendations (other
    departments named only in the State scope); not claimed by any department. Structured, so the portal names offices
    through `OfficeName`."""
    if not ids:
        return {}
    custody = {
        r.case_id: r
        for r in session.execute(
            select(
                F.CUSTODY.case_id,
                F.CUSTODY.holder_office_id,
                F.CUSTODY.holder_membership_id,
                F.CUSTODY.pending_action,
                F.CUSTODY.due_date,
                User.full_name,
                UserMembership.designation,
            )
            .outerjoin(UserMembership, UserMembership.id == F.CUSTODY.holder_membership_id)
            .outerjoin(User, User.id == UserMembership.user_id)
            .where(F.CUSTODY.case_id.in_(ids))
        ).all()
    }
    owners = dict(
        session.execute(
            select(CaseOwnership.case_id, CaseOwnership.office_id).where(
                CaseOwnership.case_id.in_(ids),
                CaseOwnership.status == OwnershipStatus.ACTIVE,
                CaseOwnership.role == OwnershipRole.PRIMARY,
            )
        ).all()
    )
    closed = set(
        session.scalars(select(Case.id).where(Case.id.in_(ids), case_closure.closed_condition(Case.id))).all()
    )
    recs: dict[uuid.UUID, list[tuple[float, uuid.UUID]]] = {}
    for cid, office_id, score in session.execute(
        select(Recommendation.case_id, Recommendation.office_id, Recommendation.score).where(
            Recommendation.case_id.in_(ids), Recommendation.status == RecommendationStatus.RECOMMENDED
        )
    ).all():
        recs.setdefault(cid, []).append((float(score), office_id))
    office_ids = {c.holder_office_id for c in custody.values()} | set(owners.values())
    office_ids |= {o for lst in recs.values() for _, o in lst}
    offices = _department_names(session, office_ids)

    def name(oid) -> str:
        o = offices.get(oid)
        return o.name if o is not None else "?"

    def code(oid) -> str | None:
        o = offices.get(oid)
        return o.code if o is not None else None

    out: dict[uuid.UUID, dict[str, Any]] = {}
    for cid in ids:
        cu = custody.get(cid)
        owner = owners.get(cid)
        base = dict(NOT_CLAIMED)
        if cu is not None and cu.holder_membership_id is not None:
            who = ", ".join(p for p in (cu.full_name, cu.designation) if p)
            out[cid] = base | {
                "kind": "officer",
                "text": f"With {who} · {name(cu.holder_office_id)}",
                "officer_name": cu.full_name,
                "designation": cu.designation,
                "office_code": code(cu.holder_office_id),
                "department_code": code(owner) if owner else None,
            }
        elif owner is not None and cid in closed:
            out[cid] = base | {
                "kind": "closed",
                "text": f"Claimed by {name(owner)} · Closed in ASLMS",
                "department_code": code(owner),
            }
        elif cu is not None:
            out[cid] = base | {
                "kind": "office",
                "text": f"With {name(cu.holder_office_id)} · Not Sent to an Officer",
                "office_code": code(cu.holder_office_id),
                "department_code": code(owner) if owner else None,
            }
        elif owner is not None:
            out[cid] = base | {
                "kind": "claimed",
                "text": f"Claimed by {name(owner)}",
                "department_code": code(owner),
            }
        elif cid in recs:
            ranked = sorted(recs[cid], key=lambda t: (-t[0], name(t[1])))
            if scope.is_state:
                top = ranked[0][1]
                more = len(ranked) - 1
                text_ = f"Not Claimed · Recommended to {name(top)}" + (f" and {more} more" if more else "")
                out[cid] = base | {
                    "kind": "recommended",
                    "text": text_,
                    "recommended_to": code(top),
                    "more": more,
                }
            else:
                mine = scope.department is not None and any(o == scope.department.id for _, o in ranked)
                if mine:
                    out[cid] = base | {
                        "kind": "recommended",
                        "text": f"Not Claimed · Recommended to {scope.department.name}",
                        "recommended_to": scope.department.code,
                    }
                else:
                    out[cid] = base | {"kind": "not_claimed", "text": "Not Claimed"}
        else:
            out[cid] = base
    return out


def pending_action_words(action: PendingAction | str | None) -> str | None:
    if action is None:
        return None
    act = PendingAction(action)
    return None if act == PendingAction.NONE else PENDING_ACTION_LABELS[act]
