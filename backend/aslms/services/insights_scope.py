"""Who sees which Insights (design `state-insights`, decisions 17 to 21): State-wide or one department, by function,
always ANDed with the viewer's case visibility in SQL.

- **State scope** (decision 18): a membership that holds `insights.state` **and** is State-wide (the super admin, or
  `cases.view_all`); otherwise 403 `state_scope_not_state_wide`. The case set is every live case ANDed with that
  membership's visibility (`true` for a State-wide membership, kept as defence in depth). A State-wide holder may also
  open the department view of any department.
- **Department scope** (decision 19): a membership in that department holding `insights.department` (or the
  State-wide case above). The case set is the department's three bands (decision 21: claimed, likely or named) ANDed
  with `member_bases` of that one membership, so the plain unclaimed pool is never counted. Several departments give
  a switch (`available`); the primary membership's department is the default.
- `band_conditions(department)`: the three bands as SQL over `cases` joined to `insight_case_facts` (alias `facts`),
  disjoint for one department and never added together."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, and_, exists, false, func, or_
from sqlalchemy.orm import Session, aliased

from aslms.domain.cases import Case
from aslms.domain.insights import InsightCaseFact
from aslms.domain.org import Office, User
from aslms.domain.ownership import (
    CaseOwnership,
    OwnershipRole,
    OwnershipStatus,
    Recommendation,
    RecommendationStatus,
)
from aslms.domain.reference import Permission
from aslms.services import access, visibility
from aslms.services.access import Forbidden, Member
from aslms.services.offices import find_office

# the fact row of the case under consideration; every Insights query joins it by this alias (LEFT JOIN)
FACTS = aliased(InsightCaseFact, name="facts")


@dataclass(frozen=True)
class Scope:
    kind: str  # "state" or "department"
    department: Office | None
    member: Member
    condition: ColumnElement[bool]

    @property
    def is_state(self) -> bool:
        return self.kind == "state"

    def ref(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "department": (
                {"code": self.department.code, "name": self.department.name} if self.department else None
            ),
        }


def _state_wide(member: Member) -> bool:
    return member.is_super_admin or member.holds(Permission.CASES_VIEW_ALL)


def state_members(session: Session, user: User | Member) -> list[Member]:
    """Memberships holding `insights.state` that are State-wide (decision 18)."""
    return [m for m in access.members(session, user) if m.holds(Permission.INSIGHTS_STATE) and _state_wide(m)]


def department_members(session: Session, user: User | Member) -> list[Member]:
    """Memberships in a department holding `insights.department` (decision 19)."""
    return [
        m
        for m in access.members(session, user)
        if m.department is not None and m.holds(Permission.INSIGHTS_DEPARTMENT)
    ]


def require_any_insights(session: Session, user: User | Member) -> None:
    if not (
        access.has(session, user, Permission.INSIGHTS_STATE)
        or access.has(session, user, Permission.INSIGHTS_DEPARTMENT)
    ):
        raise Forbidden(
            "insights.state or insights.department is not enabled for you", "no_insights_function"
        )


def available(session: Session, user: User | Member) -> dict[str, Any]:
    """`GET /insights/scopes`: whether the State view is open, the departments of the switch (each once, primary
    first) and the default view."""
    require_any_insights(session, user)
    state = bool(state_members(session, user))
    depts: list[Office] = []
    for m in department_members(session, user):
        if all(d.id != m.department.id for d in depts):
            depts.append(m.department)
    if state:
        default = {"scope": "state", "department": None}
    elif depts:
        default = {"scope": "department", "department": depts[0].code}
    else:
        default = {"scope": None, "department": None}
    return {
        "state": state,
        "departments": [{"code": d.code, "name": d.name} for d in depts],
        "default": default,
    }


def primary_claimed(department: Office | uuid.UUID | None = None, case_id: Any = None) -> ColumnElement[bool]:
    """An active primary ownership of the case (by `department` when given)."""
    conds = [
        CaseOwnership.case_id == (case_id if case_id is not None else Case.id),
        CaseOwnership.status == OwnershipStatus.ACTIVE,
        CaseOwnership.role == OwnershipRole.PRIMARY,
    ]
    if department is not None:
        conds.append(
            CaseOwnership.office_id == (department.id if isinstance(department, Office) else department)
        )
    return exists().where(and_(*conds))


def recommended_to(department: Office | uuid.UUID) -> ColumnElement[bool]:
    dept_id = department.id if isinstance(department, Office) else department
    return exists().where(
        Recommendation.case_id == Case.id,
        Recommendation.office_id == dept_id,
        Recommendation.status == RecommendationStatus.RECOMMENDED,
    )


def named_condition(department: Office | uuid.UUID) -> ColumnElement[bool]:
    """The department is named in the cause title (or respondent names) or by an exactly mapped counsel code."""
    dept_id = department.id if isinstance(department, Office) else department
    return or_(
        FACTS.named_title_department_ids.any(dept_id),
        FACTS.named_counsel_department_ids.any(dept_id),
    )


def band_conditions(department: Office | uuid.UUID) -> dict[str, ColumnElement[bool]]:
    """Decision 21: for a case and a department D, `claimed` (an active primary ownership of D), `likely` (an open
    recommendation of D, not claimed by D) and `named` (D named, neither claimed by D nor likely for D). Disjoint."""
    claimed = primary_claimed(department)
    likely = and_(recommended_to(department), ~claimed)
    named = and_(func.coalesce(named_condition(department), false()), ~claimed, ~recommended_to(department))
    return {"claimed": claimed, "likely": likely, "named": named}


def any_band(department: Office | uuid.UUID) -> ColumnElement[bool]:
    b = band_conditions(department)
    return or_(b["claimed"], b["likely"], b["named"])


def _member_visibility(session: Session, member: Member) -> ColumnElement[bool]:
    bases = visibility.member_bases(session, member)
    if not bases:
        return false()
    return bases[0][1] if len(bases) == 1 else or_(*[c for _, c in bases])


def resolve(session: Session, user: User | Member, scope: str | None, department: str | None) -> Scope:
    """Decisions 18 and 19: the scope asked for, or the default one; `Forbidden` with `no_insights_function`,
    `state_scope_not_state_wide` or `department_not_yours`. A bad department code is `department_not_yours` too
    (nothing about other offices is told)."""
    require_any_insights(session, user)
    kind = scope or available(session, user)["default"]["scope"]
    if kind == "state":
        holders = state_members(session, user)
        if not holders:
            if access.has(session, user, Permission.INSIGHTS_STATE):
                raise Forbidden(
                    "the State view needs a State-wide membership holding View State Insights",
                    "state_scope_not_state_wide",
                )
            raise Forbidden("View State Insights is not enabled for you", "no_insights_function")
        member = holders[0]
        return Scope("state", None, member, _member_visibility(session, member))
    if kind != "department":
        raise Forbidden("no Insights view is open to you", "no_insights_function")
    code = department or available(session, user)["default"]["department"]
    office = find_office(session, code) if code else None
    if office is None or not access.is_department(office):
        holders = state_members(session, user)
        if not code and holders:
            raise Forbidden("name a department", "department_not_yours")
        raise Forbidden("that department's Insights are not open to you", "department_not_yours")
    member = next((m for m in department_members(session, user) if m.department.id == office.id), None)
    if member is None:
        holders = state_members(session, user)
        if not holders:
            raise Forbidden("that department's Insights are not open to you", "department_not_yours")
        member = holders[0]
    condition = and_(any_band(office), _member_visibility(session, member))
    return Scope("department", office, member, condition)
