"""What the dashboards and the reports share (design `reports-dashboards`): today in IST, the configuration from
the settings, the statement timeout every builder sets first (decision 2), the Department-tier rows of the State
views, the current primary owner of a case (decision 4) and the NJDG age bands (decision 6). Nothing here
writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import ColumnElement, Date, and_, case, exists, func, literal, or_, select, text
from sqlalchemy.orm import Session

from aslms.core.config import Settings, get_settings
from aslms.domain.cases import Case
from aslms.domain.org import Office
from aslms.domain.ownership import CaseOwnership, OwnershipRole, OwnershipStatus
from aslms.services import access
from aslms.services.alert_rules import IST

IST_ZONE = IST

# decision 6: the national judicial data grid bands, [low, high) in whole years; exactly N years is the next band
AGE_BANDS: tuple[tuple[str, str, int, int | None], ...] = (
    ("age_lt_1", "Up to 1 year", 0, 1),
    ("age_1_3", "1 to 3 years", 1, 3),
    ("age_3_5", "3 to 5 years", 3, 5),
    ("age_5_10", "5 to 10 years", 5, 10),
    ("age_10_20", "10 to 20 years", 10, 20),
    ("age_20_30", "20 to 30 years", 20, 30),
    ("age_gt_30", "Over 30 years", 30, None),
)
AGE_UNKNOWN = ("age_unknown", "Age not known")
AGE_KEYS: tuple[str, ...] = tuple(b[0] for b in AGE_BANDS) + (AGE_UNKNOWN[0],)


class ReportError(ValueError):
    """A refused dashboard or report request. `code` is machine-readable; `http_status` 400 or 422; `extra`
    goes into the error body (the candidates of `department_required`)."""

    def __init__(self, code: str, message: str, http_status: int = 400, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.extra = extra


class DepartmentRequired(ReportError):
    """No `department` named and the caller may read several (or, State-wide, none of their own)."""

    def __init__(self, candidates: list[str]) -> None:
        msg = "department is required"
        if candidates:
            msg += ": you may read " + ", ".join(candidates)
        super().__init__("department_required", msg, 400, candidates=candidates)


class BadDepartment(ReportError):
    def __init__(self, code: str) -> None:
        super().__init__("bad_department", f"{code!r} is not a department", 400)


@dataclass(frozen=True)
class ReportConfig:
    max_range_days: int = 366
    health_max_days: int = 92
    xlsx_max_rows: int = 5000
    pdf_max_rows: int = 1000
    statement_timeout_seconds: int = 30
    list_size: int = 10
    due_soon_days: int = 2
    critical_hours: int = 48
    sitting_time: str = "10:30"

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> ReportConfig:
        s = settings or get_settings()
        return cls(
            max_range_days=s.report_max_range_days,
            health_max_days=s.report_health_max_days,
            xlsx_max_rows=s.report_xlsx_max_rows,
            pdf_max_rows=s.report_pdf_max_rows,
            statement_timeout_seconds=s.report_statement_timeout_seconds,
            list_size=s.dashboard_list_size,
            due_soon_days=s.request_due_soon_days,
            critical_hours=s.alert_critical_hours,
            sitting_time=s.court_sitting_time,
        )


def now_utc() -> datetime:
    return datetime.now(UTC)


def today_ist(now: datetime | None = None) -> date:
    return (now or now_utc()).astimezone(IST).date()


def ist_date(value: datetime | None) -> date | None:
    return value.astimezone(IST).date() if value is not None else None


def with_timeout(session: Session, seconds: int) -> None:
    """Decision 2: `SET LOCAL statement_timeout` for the rest of the transaction."""
    session.execute(text(f"SET LOCAL statement_timeout = {max(1, int(seconds)) * 1000}"))


def department_rows(session: Session) -> list[Office]:
    """The active Department-tier offices and any inactive one that still owns a case (active primary row),
    ordered by name."""
    owns = exists().where(
        CaseOwnership.office_id == Office.id,
        CaseOwnership.status == OwnershipStatus.ACTIVE,
        CaseOwnership.role == OwnershipRole.PRIMARY,
    )
    rows = session.scalars(
        select(Office)
        .where(
            Office.parent_id.is_not(None),
            Office.kind.in_(list(access.DEPARTMENT_TIER_KINDS)),
            or_(Office.is_active.is_(True), owns),
        )
        .order_by(Office.name, Office.code)
    ).all()
    return [o for o in rows if access.is_department(o)]


def primary_owner_subquery():
    """(case_id, office_id, unit_office_id, officer_user_id) of the active primary ownership rows."""
    return (
        select(
            CaseOwnership.case_id,
            CaseOwnership.office_id,
            CaseOwnership.unit_office_id,
            CaseOwnership.officer_user_id,
        )
        .where(CaseOwnership.status == OwnershipStatus.ACTIVE, CaseOwnership.role == OwnershipRole.PRIMARY)
        .subquery("primary_owner")
    )


def primary_owned_condition(department: Office | None = None, case_id=None) -> ColumnElement[bool]:
    """Over `cases` (or the given case-id column): the case has an active primary owner (in `department`)."""
    conds = [
        CaseOwnership.case_id == (case_id if case_id is not None else Case.id),
        CaseOwnership.status == OwnershipStatus.ACTIVE,
        CaseOwnership.role == OwnershipRole.PRIMARY,
    ]
    if department is not None:
        conds.append(CaseOwnership.office_id == department.id)
    return exists().where(and_(*conds))


def years_before(today: date, years: int) -> date:
    """The same day `years` earlier (29 February becomes the 28th)."""
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        return today.replace(year=today.year - years, day=28)


def age_start(case_row: Any) -> date | None:
    return case_row.registration_date or case_row.filing_date or case_row.date_first_list


def age_band(start: date | None, today: date) -> str:
    """Decision 6 in Python (the twin of `age_band_expr`): the band key of a case first dated `start`."""
    if start is None:
        return AGE_UNKNOWN[0]
    for key, _label, _low, high in AGE_BANDS:
        if high is None or start > years_before(today, high):
            return key
    return AGE_BANDS[-1][0]  # pragma: no cover - the last band has no upper bound


def age_band_expr(today: date) -> ColumnElement[str]:
    """Decision 6 in SQL: the band key over `coalesce(registration_date, filing_date, date_first_list)`; the
    thresholds are computed once in Python so the SQL and `age_band` agree to the day."""
    start = func.coalesce(Case.registration_date, Case.filing_date, Case.date_first_list)
    whens = [(start.is_(None), literal(AGE_UNKNOWN[0]))]
    for key, _label, _low, high in AGE_BANDS:
        if high is None:
            break
        whens.append((start > literal(years_before(today, high), Date), literal(key)))
    return case(*whens, else_=literal(AGE_BANDS[-1][0]))


def age_label(key: str) -> str:
    if key == AGE_UNKNOWN[0]:
        return AGE_UNKNOWN[1]
    return next(label for k, label, _l, _h in AGE_BANDS if k == key)


def office_ref(o: Office | None) -> dict[str, Any] | None:
    return {"code": o.code, "name": o.name} if o is not None else None
