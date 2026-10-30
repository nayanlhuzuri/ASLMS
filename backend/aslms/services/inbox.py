"""The department case inbox (design `recommend-and-claim`, decisions 15 and 23): Recommended, Claimed (Active /
Disposed), the Unclaimed pool, Transfers, and the dashboard counts. Summary data only; the full case detail
stays behind `cases-api` visibility.

Every list checks the caller's function on the server: Recommended needs `cases.claim` for the own department
(`cases.view_all` for any office, read-only); Claimed needs `cases.view_scope` and shows the rows of
`visibility.claimed_conditions`; the pool needs `cases.claim` or `cases.view_all`; Transfers need
`cases.transfer_request` or `cases.transfer_decide` for the own department, `cases.view_all` for any.
Lists return `(items, total)` with `limit` <= 200 (default 50) and `offset`.

Memberships (design `user-memberships`, decision 6): the department a tab is read for is the caller's
membership in it — the one named by `office`, else the primary membership's department when it holds the
tab's function, else the single membership that does, else 400 `office_required`. `counts` returns one block
per department the caller works in."""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, aliased

from aslms.core.clock import today_ist
from aslms.domain.cases import Case, CaseStatus
from aslms.domain.causelists import CURRENT_LIST, Causelist, CauselistEntry
from aslms.domain.org import Office, User
from aslms.domain.ownership import (
    CaseOfficeScore,
    CaseOwnership,
    CounselCode,
    OwnershipRole,
    OwnershipStatus,
    OwnershipTransfer,
    Recommendation,
    RecommendationStatus,
    ScoreBand,
    TransferStatus,
)
from aslms.domain.reference import Permission
from aslms.domain.workflow import Custody
from aslms.services import access, case_filters
from aslms.services.case_filters import CaseFilters
from aslms.services.offices import find_office
from aslms.services.visibility import (
    CaseState,
    claim_departments,
    claimed_conditions,
    codes_condition,
    is_department,
    whole_department,
)
from aslms.services.visibility import never_owned as visibility_never_owned

MAX_LIMIT = 200
DEFAULT_LIMIT = 50
MIN_QUERY = 3

# the file's due date in the Claimed order, under an alias: the visibility rule correlates on `custody` itself
_CLAIMED_DUE = aliased(Custody, name="claimed_due")

Direction = Literal["in", "out"]


class InboxError(ValueError):
    """Bad input (HTTP 400)."""


class OfficeRequired(InboxError):
    """The caller sits outside every department (or works in several) and named no `office`. `candidates`
    lists the department codes when there are several."""

    code = "office_required"

    def __init__(self, message: str, candidates: list[str] | None = None) -> None:
        super().__init__(message)
        self.candidates = candidates or []


CaseSummary = dict[str, Any]  # the CaseSummaryOut shape of the API


@dataclass
class Page:
    items: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    extra: dict[str, Any] = field(default_factory=dict)  # list-specific blocks (e.g. recipients' `units`)


# ------------------------------------------------------------------------------------------------ helpers


def clamp(limit: int | None, offset: int | None) -> tuple[int, int]:
    lim = DEFAULT_LIMIT if limit is None else max(1, min(int(limit), MAX_LIMIT))
    off = max(0, int(offset or 0))
    return lim, off


def target_department(
    session: Session, user: User, office_code: str | None, *, own_permission: Permission | None
) -> tuple[Office, bool]:
    """The department a tab is read for and whether the caller reads it as a State-wide reader. A department
    the caller works in needs `own_permission` (when given) in that membership; another department, or none
    of one's own, needs `cases.view_all`. A `cases.view_all` holder without `own_permission` reads their own
    department too."""
    view_all = access.has(session, user, Permission.CASES_VIEW_ALL)
    members = [m for m in access.members(session, user) if m.department is not None]
    if office_code:
        office = find_office(session, office_code)
        if office is None or not is_department(office):
            raise InboxError(f"{office_code!r} is not a department")
        mine = next((m for m in members if m.department.id == office.id), None)
        if mine is None:
            if not view_all:
                raise access.Forbidden("cases.view_all is needed to read another department's inbox")
            return office, True
        if own_permission is None or mine.holds(own_permission):
            return office, view_all
        if view_all:
            return office, True
        raise access.Forbidden(f"{own_permission.value} is not enabled for you in {office.code}")
    if not members:
        if view_all:
            raise OfficeRequired("office is required: you do not belong to a department")
        raise access.Forbidden("you do not belong to a department")
    qualifying = [m for m in members if own_permission is None or m.holds(own_permission)]
    if qualifying:
        if qualifying[0] is members[0] or len(qualifying) == 1:
            return qualifying[0].department, view_all
        codes = [m.department.code for m in qualifying]
        raise OfficeRequired("office is required: you work in " + ", ".join(codes), codes)
    if view_all:
        return members[0].department, True
    raise access.Forbidden(f"{own_permission.value} is not enabled for you")


def _last_listings(session: Session, case_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    """The latest cause-list entry of each case (latest list date, then the lowest item number): court-public
    data, the same as the listings tab (design `portal-cases`, decision 14b)."""
    if not case_ids:
        return {}
    rows = session.execute(
        select(
            CauselistEntry.case_id,
            Causelist.list_date,
            Causelist.list_type,
            CauselistEntry.court_no,
            CauselistEntry.sr_no,
        )
        .join(Causelist, Causelist.id == CauselistEntry.causelist_id)
        .where(CauselistEntry.case_id.in_(case_ids), CURRENT_LIST)
        .ext(distinct_on(CauselistEntry.case_id))
        .order_by(CauselistEntry.case_id, Causelist.list_date.desc(), CauselistEntry.sr_no, CauselistEntry.id)
    ).all()
    return {
        cid: {
            "list_date": d,
            "list_type": lt.value if hasattr(lt, "value") else str(lt),
            "court_no": court_no,
            "sr_no": sr_no,
        }
        for cid, d, lt, court_no, sr_no in rows
    }


def summaries(
    session: Session, cases: list[Case], *, hidden: Collection[uuid.UUID] = ()
) -> dict[uuid.UUID, CaseSummary]:
    """The one builder of `CaseSummaryOut`. `next_hearing` is the case's one next hearing (design next-date-direct,
    decision 11), never the court's raw `next_hearing_date`. `hidden` names the cases the caller cannot open: their
    `next_hearing` keeps only the court-public tiers (`next_hearing.court_public`), never a department's own date."""
    from aslms.services import next_hearing

    listings = _last_listings(session, [c.id for c in cases])
    hearings = next_hearing.outs(session, cases)
    for cid in set(hidden) & hearings.keys():
        hearings[cid] = next_hearing.court_public(hearings[cid])
    out: dict[uuid.UUID, CaseSummary] = {}
    for c in cases:
        last = listings.get(c.id)
        out[c.id] = {
            "id": c.id,
            "ref_no": c.ref_no,
            "cnr": c.cnr,
            "case_no_text": c.case_no_text,
            "is_provisional": c.is_provisional,
            "petitioner_summary": c.petitioner_summary,
            "respondent_summary": c.respondent_summary,
            "status": CaseStatus(c.status).value,
            "next_hearing": hearings.get(c.id),
            "last_listed_on": last["list_date"] if last else None,
            "last_listing": last,
        }
    return out


def _office_codes(session: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, Office]:
    if not ids:
        return {}
    return {o.id: o for o in session.scalars(select(Office).where(Office.id.in_(ids))).all()}


def primary_codes(session: Session, case_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not case_ids:
        return {}
    rows = session.execute(
        select(CaseOwnership.case_id, Office.code)
        .join(Office, Office.id == CaseOwnership.office_id)
        .where(
            CaseOwnership.case_id.in_(case_ids),
            CaseOwnership.status == OwnershipStatus.ACTIVE,
            CaseOwnership.role == OwnershipRole.PRIMARY,
        )
    ).all()
    return {cid: code for cid, code in rows}


def never_owned() -> Any:
    """The pool predicate on `Case`: no primary ownership row ever (decision 10; shared with visibility)."""
    return visibility_never_owned()


def _filtered(stmt: Select, session: Session | None, filters: CaseFilters | None) -> Select:
    """The shared case filters (design `portal-filters`) ANDed on the statement's `Case`."""
    if filters is None or filters.is_empty:
        return stmt
    if session is None:
        raise TypeError("a session is needed to apply case filters")
    return stmt.where(*case_filters.conditions(session, filters))


def _no_owner(filters: CaseFilters | None) -> CaseFilters | None:
    """Recommended, Claimed, the pool and Transfers have no owner filter (design `portal-filters`, decision 5)."""
    if filters is not None and filters.owner is not None:
        raise InboxError("owner is not a filter of this list")
    return filters


def _count(session: Session, stmt: Select) -> int:
    return int(session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)


# ------------------------------------------------------------------------------------------------ recommended


def recommended_stmt(
    department: Office,
    *,
    band: ScoreBand | None = None,
    filters: CaseFilters | None = None,
    session: Session | None = None,
) -> Select:
    stmt = (
        select(Recommendation, Case)
        .join(Case, Case.id == Recommendation.case_id)
        .where(
            Recommendation.office_id == department.id,
            Recommendation.status == RecommendationStatus.RECOMMENDED,
            Case.merged_into_case_id.is_(None),
        )
    )
    if band is not None:
        stmt = stmt.where(Recommendation.band == band)
    return _filtered(stmt, session, filters)


def recommended(
    session: Session,
    user: User,
    *,
    office: str | None = None,
    band: ScoreBand | str | None = None,
    filters: CaseFilters | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> Page:
    dept, _ = target_department(session, user, office, own_permission=Permission.CASES_CLAIM)
    band_v = ScoreBand(band) if band else None
    limit, offset = clamp(limit, offset)
    stmt = recommended_stmt(dept, band=band_v, filters=_no_owner(filters), session=session)
    total = _count(session, stmt)
    rows = session.execute(
        stmt.order_by(
            (Recommendation.band == ScoreBand.HIGH).desc(),
            Recommendation.score.desc(),
            Case.next_hearing_on.asc().nulls_last(),
            Recommendation.created_at,
        )
        .limit(limit)
        .offset(offset)
    ).all()
    cases = [c for _, c in rows]
    ids = [c.id for c in cases]
    summ = summaries(session, cases)
    owners = primary_codes(session, ids)
    scores = (
        {
            s.case_id: s
            for s in session.scalars(
                select(CaseOfficeScore).where(
                    CaseOfficeScore.case_id.in_(ids), CaseOfficeScore.office_id == dept.id
                )
            ).all()
        }
        if ids
        else {}
    )
    suggesters = _office_codes(session, {r.suggested_office_id for r, _ in rows if r.suggested_office_id})
    items = [
        recommendation_item(session, r, summ[c.id], owners.get(c.id), scores.get(c.id), suggesters)
        for r, c in rows
    ]
    return Page(items, total)


def recommendation_item(
    session: Session,
    rec: Recommendation,
    case: CaseSummary,
    owner_code: str | None,
    score: CaseOfficeScore | None,
    suggesters: dict[uuid.UUID, Office] | None = None,
) -> dict[str, Any]:
    suggested_by = None
    if rec.suggested_office_id is not None:
        o = (suggesters or {}).get(rec.suggested_office_id) or session.get(Office, rec.suggested_office_id)
        suggested_by = o.code if o else None
    return {
        "id": rec.id,
        "case": case,
        "office_code": _code(session, rec.office_id),
        "score": float(rec.score),
        "band": ScoreBand(rec.band).value,
        "status": RecommendationStatus(rec.status).value,
        "origin": rec.origin.value if hasattr(rec.origin, "value") else str(rec.origin),
        "signals": list(score.signals) if score is not None else [],
        "suggested_by_office_code": suggested_by,
        "reason": rec.reason,
        "created_at": rec.created_at,
        "acted_at": rec.acted_at,
        "current_owner_code": owner_code,
    }


def _code(session: Session, office_id) -> str | None:
    o = session.get(Office, office_id) if office_id else None
    return o.code if o else None


# ------------------------------------------------------------------------------------------------ claimed


def claimed_stmt(
    session: Session,
    user: User,
    department: Office,
    *,
    case_state: CaseState = "active",
    whole: bool | None = None,
    role: OwnershipRole | None = None,
    unit: Office | None = None,
    officer_user_id: uuid.UUID | None = None,
    filters: CaseFilters | None = None,
    unallotted: bool = False,
    stage: str | None = None,
    holder: str | None = None,
    action: str | None = None,
) -> Select:
    """The Claimed rows; `unallotted` keeps rows with no officer, `stage` the case's latest stage (or `none`),
    `holder` where the file is (`department` / `elsewhere`), `action` the file's due date (`overdue` /
    `due_week`) (design `portal-ui-redesign`, A3)."""
    from aslms.services import my_cases

    stmt = (
        select(CaseOwnership, Case)
        .join(Case, Case.id == CaseOwnership.case_id)
        .where(*claimed_conditions(session, user, department, case_state=case_state, whole=whole))
    )
    if role is not None:
        stmt = stmt.where(CaseOwnership.role == role)
    if unit is not None:
        units = select(Office.id).where(or_(Office.id == unit.id, Office.path.like(unit.path + "/%")))
        stmt = stmt.where(CaseOwnership.unit_office_id.in_(units))
    if officer_user_id is not None:
        stmt = stmt.where(CaseOwnership.officer_user_id == officer_user_id)
    if unallotted:
        stmt = stmt.where(CaseOwnership.officer_user_id.is_(None))
    for extra in (
        my_cases.stage_condition(stage),
        my_cases.holder_condition(holder, department),
        my_cases.action_condition(action),
    ):
        if extra is not None:
            stmt = stmt.where(extra)
    return _filtered(stmt, session, filters)


def _case_state(value: str | None) -> CaseState:
    v = (value or "active").lower()
    if v not in ("active", "disposed", "all"):
        raise InboxError("case_state is one of active, disposed, all")
    return v  # type: ignore[return-value]


def claimed_order(state: CaseState, action: str | None) -> list[Any]:
    """Design `case-inbox-simplify`, decision 13: with `case_state=all` active cases first; with `action` the
    file's due date next (nulls last); then the next hearing (nulls last) and the newest claim. `active` and
    `disposed` without `action` keep the earlier order exactly."""
    order: list[Any] = []
    if state == "all":
        order.append((Case.status == CaseStatus.DISPOSED).asc())
    if action is not None and str(action).strip() != "":
        due = select(_CLAIMED_DUE.due_date).where(_CLAIMED_DUE.case_id == Case.id).scalar_subquery()
        order.append(due.asc().nulls_last())
    order += [Case.next_hearing_on.asc().nulls_last(), CaseOwnership.claimed_at.desc()]
    return order


def claimed(
    session: Session,
    user: User,
    *,
    office: str | None = None,
    case_state: str | None = "active",
    role: OwnershipRole | str | None = None,
    unit: str | None = None,
    officer_user_id: uuid.UUID | None = None,
    filters: CaseFilters | None = None,
    unallotted: bool | None = None,
    stage: str | None = None,
    holder: str | None = None,
    action: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> Page:
    from aslms.services import my_cases

    access.require(session, user, Permission.CASES_VIEW_SCOPE)
    dept, view_all = target_department(session, user, office, own_permission=None)
    state = _case_state(case_state)
    if unallotted and officer_user_id is not None:
        raise InboxError("unallotted and officer_user_id cannot be combined")
    role_v = OwnershipRole(role) if role else None
    unit_office = None
    if unit:
        unit_office = find_office(session, unit)
        if unit_office is None or not unit_office.path.startswith(dept.path + "/"):
            raise InboxError(f"{unit!r} is not an office of {dept.code}")
    limit, offset = clamp(limit, offset)
    stmt = claimed_stmt(
        session,
        user,
        dept,
        case_state=state,
        whole=True if view_all else None,
        role=role_v,
        unit=unit_office,
        officer_user_id=officer_user_id,
        filters=_no_owner(filters),
        unallotted=bool(unallotted),
        stage=stage,
        holder=holder,
        action=action,
    )
    total = _count(session, stmt)
    rows = session.execute(stmt.order_by(*claimed_order(state, action)).limit(limit).offset(offset)).all()
    cases = [c for _, c in rows]
    summ = summaries(session, cases)
    briefs = my_cases.case_briefs(session, user, [c.id for c in cases])
    items = [ownership_item(session, r, summ[c.id], briefs.get(c.id)) for r, c in rows]
    return Page(items, total)


def ownership_item(
    session: Session,
    row: CaseOwnership,
    case: CaseSummary | None = None,
    brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One ownership row; `brief` (from `my_cases.case_briefs`) adds the case's stage and file holder."""
    if case is None:
        case = summaries(session, [session.get(Case, row.case_id)])[row.case_id]
    unit = session.get(Office, row.unit_office_id) if row.unit_office_id else None
    officer = session.get(User, row.officer_user_id) if row.officer_user_id else None
    return {
        "id": row.id,
        "case": case,
        "office_code": _code(session, row.office_id),
        "role": OwnershipRole(row.role).value,
        "status": OwnershipStatus(row.status).value,
        "unit": {"code": unit.code, "name": unit.name} if unit else None,
        "officer": {"id": officer.id, "full_name": officer.full_name} if officer else None,
        "claimed_at": row.claimed_at,
        "allotted_at": row.allotted_at,
        "released_at": row.released_at,
        "release_reason": row.release_reason,
        "stage": (brief or {}).get("stage"),
        "custody": (brief or {}).get("custody"),
    }


# ------------------------------------------------------------------------------------------------ pool


def _state_party_condition(session: Session):
    """A generic or mapped counsel code appears in a cause-list entry or a current advocate row (the SQL
    normalisation `visibility.NORMALISED_CODE_SQL`, shared with the counsel visibility basis)."""
    codes = list(session.scalars(select(CounselCode.code).where(CounselCode.is_active.is_(True))).all())
    return codes_condition(codes)


def pool_stmt(
    session: Session,
    *,
    filters: CaseFilters | None = None,
    min_score: float | None = None,
    scored_for: Office | None = None,
    state_party: bool | None = None,
    found_for: Office | None = None,
) -> Select:
    """Never-owned non-merged cases, then the shared filters. `scored_for` keeps cases with a score row for
    that department, and with `min_score` the same row must reach it (design `portal-filters`, decision 5);
    `min_score` alone: any department's row. `found_for` keeps cases found by that department's court search
    (design `department-discovery`, decision 10)."""
    stmt = _filtered(select(Case).where(Case.merged_into_case_id.is_(None), never_owned()), session, filters)
    if min_score is not None and not (0 <= float(min_score) <= 1):
        raise InboxError("min_score is between 0 and 1")
    if scored_for is not None or min_score is not None:
        conds = [CaseOfficeScore.case_id == Case.id]
        if scored_for is not None:
            conds.append(CaseOfficeScore.office_id == scored_for.id)
        if min_score is not None:
            conds.append(CaseOfficeScore.score >= float(min_score))
        stmt = stmt.where(exists().where(*conds))
    if state_party is True:
        stmt = stmt.where(_state_party_condition(session))
    elif state_party is False:
        stmt = stmt.where(~_state_party_condition(session))
    if found_for is not None:
        from aslms.services.discovery import found_for_condition

        stmt = stmt.where(found_for_condition(session, found_for))
    return stmt


def _pool_allowed(session: Session, user: User) -> None:
    if not (
        access.has(session, user, Permission.CASES_CLAIM)
        or access.has(session, user, Permission.CASES_VIEW_ALL)
    ):
        raise access.Forbidden("cases.claim or cases.view_all is needed to search the unclaimed pool")


def pool(
    session: Session,
    user: User,
    *,
    filters: CaseFilters | None = None,
    min_score: float | None = None,
    scored_for: str | None = None,
    state_party: bool | None = None,
    found_for: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> Page:
    _pool_allowed(session, user)
    scored = case_filters.department_code(session, "scored_for", case_filters.parse_office_code(scored_for))
    found = case_filters.department_code(session, "found_for", case_filters.parse_office_code(found_for))
    if found is not None and not access.has(session, user, Permission.CASES_VIEW_ALL):
        if not any(d.id == found.id for d in claim_departments(session, user)):
            raise access.Forbidden("cases.view_all is needed to see another department's court-search finds")
    limit, offset = clamp(limit, offset)
    stmt = pool_stmt(
        session,
        filters=_no_owner(filters),
        min_score=min_score,
        scored_for=scored,
        state_party=state_party,
        found_for=found,
    )
    total = _count(session, stmt)
    cases = list(
        session.scalars(
            stmt.order_by(Case.next_hearing_on.asc().nulls_last(), Case.created_at, Case.id)
            .limit(limit)
            .offset(offset)
        ).all()
    )
    ids = [c.id for c in cases]
    summ = summaries(session, cases)
    best: dict[uuid.UUID, tuple[float, str]] = {}
    dismissed: dict[uuid.UUID, list[str]] = {}
    if ids:
        for cid, score, code in session.execute(
            select(CaseOfficeScore.case_id, CaseOfficeScore.score, Office.code)
            .join(Office, Office.id == CaseOfficeScore.office_id)
            .where(CaseOfficeScore.case_id.in_(ids))
            .order_by(CaseOfficeScore.score.desc())
        ).all():
            best.setdefault(cid, (float(score), code))
        for cid, code in session.execute(
            select(Recommendation.case_id, Office.code)
            .join(Office, Office.id == Recommendation.office_id)
            .where(
                Recommendation.case_id.in_(ids),
                Recommendation.status.in_(
                    [RecommendationStatus.DISMISSED, RecommendationStatus.SUGGESTED_ELSEWHERE]
                ),
            )
            .order_by(Office.code)
        ).all():
            lst = dismissed.setdefault(cid, [])
            if code not in lst:
                lst.append(code)
    items = [
        {
            "case": summ[c.id],
            "best_score": best[c.id][0] if c.id in best else None,
            "best_office_code": best[c.id][1] if c.id in best else None,
            "dismissed_by": dismissed.get(c.id, []),
        }
        for c in cases
    ]
    return Page(items, total)


# ------------------------------------------------------------------------------------------------ transfers


def _transfers_allowed(session: Session, user: User) -> bool:
    return access.has(session, user, Permission.CASES_TRANSFER_REQUEST) or access.has(
        session, user, Permission.CASES_TRANSFER_DECIDE
    )


def transfers_stmt(
    department: Office,
    *,
    direction: Direction | None = None,
    status: TransferStatus | None = None,
    other: Office | None = None,
    filters: CaseFilters | None = None,
    session: Session | None = None,
) -> Select:
    """The department's transfers; `other` keeps those whose other side is that department (`from` for In,
    `to` for Out, either side without a direction; design `portal-filters`, decision 5)."""
    stmt = select(OwnershipTransfer, Case).join(Case, Case.id == OwnershipTransfer.case_id)
    incoming = OwnershipTransfer.to_office_id == department.id
    outgoing = OwnershipTransfer.from_office_id == department.id
    if other is not None:
        incoming = and_(incoming, OwnershipTransfer.from_office_id == other.id)
        outgoing = and_(outgoing, OwnershipTransfer.to_office_id == other.id)
    if direction == "in":
        stmt = stmt.where(incoming)
    elif direction == "out":
        stmt = stmt.where(outgoing)
    else:
        stmt = stmt.where(or_(incoming, outgoing))
    if status is not None:
        stmt = stmt.where(OwnershipTransfer.status == status)
    return _filtered(stmt, session, filters)


def transfers(
    session: Session,
    user: User,
    *,
    office: str | None = None,
    direction: str | None = None,
    status: TransferStatus | str | None = None,
    other_office: str | None = None,
    filters: CaseFilters | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> Page:
    view_all = access.has(session, user, Permission.CASES_VIEW_ALL)
    if office:
        dept = find_office(session, office)
        if dept is None or not is_department(dept):
            raise InboxError(f"{office!r} is not a department")
        mine = access.member_in_department(session, user, dept)
        if not (view_all or (mine is not None and _transfers_allowed(session, mine))):
            raise access.Forbidden("cases.view_all is needed to read another department's transfers")
    else:
        members = [m for m in access.members(session, user) if m.department is not None]
        if not members:
            if view_all:
                raise OfficeRequired("office is required: you do not belong to a department")
            raise access.Forbidden("you do not belong to a department")
        qualifying = [m for m in members if _transfers_allowed(session, m)]
        if not qualifying and not view_all:
            raise access.Forbidden("cases.transfer_request or cases.transfer_decide is needed")
        if qualifying and qualifying[0] is not members[0] and len(qualifying) > 1:
            codes = [m.department.code for m in qualifying]
            raise OfficeRequired("office is required: you work in " + ", ".join(codes), codes)
        dept = (qualifying or members)[0].department
    if direction is not None and direction not in ("in", "out"):
        raise InboxError("direction is in or out")
    status_v = TransferStatus(status) if status else None
    other = case_filters.department_code(
        session, "other_office", case_filters.parse_office_code(other_office)
    )
    limit, offset = clamp(limit, offset)
    stmt = transfers_stmt(
        dept,
        direction=direction,  # type: ignore[arg-type]
        status=status_v,
        other=other,
        filters=_no_owner(filters),
        session=session,
    )
    total = _count(session, stmt)
    rows = session.execute(
        stmt.order_by(OwnershipTransfer.created_at.desc()).limit(limit).offset(offset)
    ).all()
    cases = [c for _, c in rows]
    summ = summaries(session, cases)
    items = [transfer_item(session, t, summ[c.id]) for t, c in rows]
    return Page(items, total)


def transfer_item(session: Session, t: OwnershipTransfer, case: CaseSummary | None = None) -> dict[str, Any]:
    if case is None:
        case = summaries(session, [session.get(Case, t.case_id)])[t.case_id]
    decided_by = session.get(User, t.decided_by_user_id) if t.decided_by_user_id else None
    return {
        "id": t.id,
        "ref_no": t.ref_no,
        "case": case,
        "from_office_code": _code(session, t.from_office_id),
        "to_office_code": _code(session, t.to_office_id),
        "status": TransferStatus(t.status).value,
        "reason": t.reason,
        "stay_as_watcher": t.stay_as_watcher,
        "decision_note": t.decision_note,
        "requested_by": {"id": t.actor_user_id, "full_name": t.actor_name},
        "requested_at": t.created_at,
        "decided_by": {"id": decided_by.id, "full_name": decided_by.full_name} if decided_by else None,
        "decided_at": t.decided_at,
        "withdrawn_at": t.withdrawn_at,
    }


# ------------------------------------------------------------------------------------------------ counts


def _counts_for(session: Session, user: User, dept: Office | None, *, today: date) -> dict:
    out: dict[str, Any] = {
        "office_code": dept.code if dept is not None else None,
        "recommended_high": None,
        "recommended_medium": None,
        "claimed_active": None,
        "claimed_disposed": None,
        "transfers_in_open": None,
        "pool_with_hearing_7d": None,
        "whole_department": False,
    }
    view_all = access.has(session, user, Permission.CASES_VIEW_ALL)
    mine = access.member_in_department(session, user, dept) if dept is not None else None
    if dept is not None:
        out["whole_department"] = bool(view_all or (mine is not None and whole_department(session, mine)))
    if dept is not None:
        if view_all or (mine is not None and mine.holds(Permission.CASES_CLAIM)):
            out["recommended_high"] = _count(session, recommended_stmt(dept, band=ScoreBand.HIGH))
            out["recommended_medium"] = _count(session, recommended_stmt(dept, band=ScoreBand.MEDIUM))
        whole = True if view_all else None
        out["claimed_active"] = _count(
            session, claimed_stmt(session, user, dept, case_state="active", whole=whole)
        )
        out["claimed_disposed"] = _count(
            session, claimed_stmt(session, user, dept, case_state="disposed", whole=whole)
        )
        if view_all or (mine is not None and _transfers_allowed(session, mine)):
            out["transfers_in_open"] = _count(
                session, transfers_stmt(dept, direction="in", status=TransferStatus.REQUESTED)
            )
    if view_all or access.has(session, user, Permission.CASES_CLAIM):
        out["pool_with_hearing_7d"] = _count(
            session,
            pool_stmt(session).where(
                Case.next_hearing_on >= today, Case.next_hearing_on <= today + timedelta(days=7)
            ),
        )
    return out


def counts(session: Session, user: User, *, office: str | None = None, today: date | None = None) -> dict:
    """The dashboard counters, one block per department the caller works in (or the department named by
    `office`), each under the rule of its tab; a count is None when the caller lacks that tab's function in
    that department. A caller with no department gets one block with `office_code` None (the pool count).
    Shape: `{"departments": [{office_code, ...counts}]}` (design `user-memberships`, flagged shape change)."""
    access.require(session, user, Permission.CASES_VIEW_SCOPE)
    today = today or today_ist()
    view_all = access.has(session, user, Permission.CASES_VIEW_ALL)
    if office:
        o = find_office(session, office)
        if o is None or not is_department(o):
            raise InboxError(f"{office!r} is not a department")
        if not (view_all or access.member_in_department(session, user, o) is not None):
            raise access.Forbidden("cases.view_all is needed to read another department's counts")
        depts: list[Office | None] = [o]
    else:
        depts = list(access.departments(session, user)) or [None]
    return {"departments": [_counts_for(session, user, d, today=today) for d in depts]}
