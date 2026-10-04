"""The department case inbox (design `recommend-and-claim`, decisions 15 and 23): Recommended, Claimed (Active /
Disposed), the Unclaimed pool, Transfers, and the dashboard counts. Summary data only; the full case detail
stays behind `cases-api` visibility.

Every list checks the caller's function on the server: Recommended needs `cases.claim` for the own department
(`cases.view_all` for any office, read-only); Claimed needs `cases.view_scope` and shows the rows of
`visibility.claimed_conditions`; the pool needs `cases.claim` or `cases.view_all`; Transfers need
`cases.transfer_request` or `cases.transfer_decide` for the own department, `cases.view_all` for any.
Lists return `(items, total)` with `limit` <= 200 (default 50) and `offset`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from sqlalchemy import Select, and_, exists, func, literal, or_, select, text
from sqlalchemy.orm import Session

from aslms.domain.cases import Case, CaseStatus
from aslms.domain.causelists import Causelist, CauselistEntry
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
from aslms.services import access
from aslms.services.offices import find_office
from aslms.services.visibility import CaseState, claimed_conditions, is_department, user_department

MAX_LIMIT = 200
DEFAULT_LIMIT = 50
MIN_QUERY = 3
Direction = Literal["in", "out"]


class InboxError(ValueError):
    """Bad input (HTTP 400)."""


class OfficeRequired(InboxError):
    """The caller sits outside every department and named no `office`."""


CaseSummary = dict[str, Any]  # the CaseSummaryOut shape of the API


@dataclass
class Page:
    items: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0


# ------------------------------------------------------------------------------------------------ helpers


def clamp(limit: int | None, offset: int | None) -> tuple[int, int]:
    lim = DEFAULT_LIMIT if limit is None else max(1, min(int(limit), MAX_LIMIT))
    off = max(0, int(offset or 0))
    return lim, off


def target_department(
    session: Session, user: User, office_code: str | None, *, own_permission: Permission | None
) -> tuple[Office, bool]:
    """The department a tab is read for and whether the caller reads it as a State-wide reader. The own
    department needs `own_permission` (when given); another department, or no own department, needs
    `cases.view_all`. A `cases.view_all` holder without `own_permission` reads the own department too."""
    view_all = access.has(session, user, Permission.CASES_VIEW_ALL)
    own = user_department(session, user)
    if office_code:
        office = find_office(session, office_code)
        if office is None or not is_department(office):
            raise InboxError(f"{office_code!r} is not a department")
        if own is None or own.id != office.id:
            if not view_all:
                raise access.Forbidden("cases.view_all is needed to read another department's inbox")
            return office, True
    if own is None:
        if view_all:
            raise OfficeRequired("office is required: you do not belong to a department")
        raise access.Forbidden("you do not belong to a department")
    if own_permission is None or access.has(session, user, own_permission):
        return own, view_all
    if view_all:
        return own, True
    raise access.Forbidden(f"{own_permission.value} is not enabled for you")


def _last_listed(session: Session, case_ids: list[uuid.UUID]) -> dict[uuid.UUID, date]:
    if not case_ids:
        return {}
    rows = session.execute(
        select(CauselistEntry.case_id, func.max(Causelist.list_date))
        .join(Causelist, Causelist.id == CauselistEntry.causelist_id)
        .where(CauselistEntry.case_id.in_(case_ids))
        .group_by(CauselistEntry.case_id)
    ).all()
    return {cid: d for cid, d in rows}


def summaries(session: Session, cases: list[Case]) -> dict[uuid.UUID, CaseSummary]:
    listed = _last_listed(session, [c.id for c in cases])
    return {
        c.id: {
            "id": c.id,
            "ref_no": c.ref_no,
            "cnr": c.cnr,
            "case_no_text": c.case_no_text,
            "is_provisional": c.is_provisional,
            "petitioner_summary": c.petitioner_summary,
            "respondent_summary": c.respondent_summary,
            "status": CaseStatus(c.status).value,
            "next_hearing_date": c.next_hearing_date,
            "last_listed_on": listed.get(c.id),
        }
        for c in cases
    }


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
    """The pool predicate on `Case`: no primary ownership row ever (decision 10)."""
    return ~exists().where(CaseOwnership.case_id == Case.id, CaseOwnership.role == OwnershipRole.PRIMARY)


def _q_condition(q: str | None):
    term = (q or "").strip()
    if not term:
        return None
    if len(term) < MIN_QUERY:
        raise InboxError(f"q is at least {MIN_QUERY} characters")
    like = f"%{term}%"
    return or_(
        Case.cnr.ilike(like),
        Case.case_no_text.ilike(like),
        Case.petitioner_summary.ilike(like),
        Case.respondent_summary.ilike(like),
        exists().where(
            CauselistEntry.case_id == Case.id,
            or_(CauselistEntry.petitioner_text.ilike(like), CauselistEntry.respondent_text.ilike(like)),
        ),
    )


def _count(session: Session, stmt: Select) -> int:
    return int(session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)


# ------------------------------------------------------------------------------------------------ recommended


def recommended_stmt(department: Office, *, band: ScoreBand | None = None, q: str | None = None) -> Select:
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
    cond = _q_condition(q)
    if cond is not None:
        stmt = stmt.where(cond)
    return stmt


def recommended(
    session: Session,
    user: User,
    *,
    office: str | None = None,
    band: ScoreBand | str | None = None,
    q: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> Page:
    dept, _ = target_department(session, user, office, own_permission=Permission.CASES_CLAIM)
    band_v = ScoreBand(band) if band else None
    limit, offset = clamp(limit, offset)
    stmt = recommended_stmt(dept, band=band_v, q=q)
    total = _count(session, stmt)
    rows = session.execute(
        stmt.order_by(
            (Recommendation.band == ScoreBand.HIGH).desc(),
            Recommendation.score.desc(),
            Case.next_hearing_date.asc().nulls_last(),
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
    q: str | None = None,
) -> Select:
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
    cond = _q_condition(q)
    if cond is not None:
        stmt = stmt.where(cond)
    return stmt


def _case_state(value: str | None) -> CaseState:
    v = (value or "active").lower()
    if v not in ("active", "disposed", "all"):
        raise InboxError("case_state is one of active, disposed, all")
    return v  # type: ignore[return-value]


def claimed(
    session: Session,
    user: User,
    *,
    office: str | None = None,
    case_state: str | None = "active",
    role: OwnershipRole | str | None = None,
    unit: str | None = None,
    officer_user_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> Page:
    access.require(session, user, Permission.CASES_VIEW_SCOPE)
    dept, view_all = target_department(session, user, office, own_permission=None)
    state = _case_state(case_state)
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
        q=q,
    )
    total = _count(session, stmt)
    rows = session.execute(
        stmt.order_by(Case.next_hearing_date.asc().nulls_last(), CaseOwnership.claimed_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    cases = [c for _, c in rows]
    summ = summaries(session, cases)
    items = [ownership_item(session, r, summ[c.id]) for r, c in rows]
    return Page(items, total)


def ownership_item(session: Session, row: CaseOwnership, case: CaseSummary | None = None) -> dict[str, Any]:
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
    }


# ------------------------------------------------------------------------------------------------ pool

# the SQL twin of matching.normalise_counsel_code: upper case, whitespace collapsed, ", " after commas,
# trailing commas and spaces stripped
_NORMALISED_CODE = "rtrim(regexp_replace(regexp_replace(upper(btrim({col})), '\\s+', ' ', 'g'), '\\s*,\\s*', ', ', 'g'), ', ')"


def _state_party_condition(session: Session):
    """A generic or mapped counsel code appears in a cause-list entry or a current advocate row."""
    codes = list(session.scalars(select(CounselCode.code).where(CounselCode.is_active.is_(True))).all())
    if not codes:
        return literal(False)
    entry_sql = text(
        "EXISTS (SELECT 1 FROM causelist_entries e CROSS JOIN LATERAL unnest(e.counsel_codes) AS c(code) "
        f"WHERE e.case_id = cases.id AND {_NORMALISED_CODE.format(col='c.code')} = ANY(:codes))"
    ).bindparams(codes=codes)
    adv_sql = text(
        "EXISTS (SELECT 1 FROM case_advocates a WHERE a.case_id = cases.id AND a.is_current "
        f"AND a.counsel_code IS NOT NULL AND {_NORMALISED_CODE.format(col='a.counsel_code')} = ANY(:codes2))"
    ).bindparams(codes2=codes)
    return or_(entry_sql, adv_sql)


def pool_stmt(
    session: Session,
    *,
    q: str | None = None,
    listed_from: date | None = None,
    listed_to: date | None = None,
    status: CaseStatus | None = None,
    case_type: str | None = None,
    year: int | None = None,
    min_score: float | None = None,
    state_party: bool | None = None,
) -> Select:
    stmt = select(Case).where(Case.merged_into_case_id.is_(None), never_owned())
    cond = _q_condition(q)
    if cond is not None:
        stmt = stmt.where(cond)
    if listed_from is not None or listed_to is not None:
        conds = [CauselistEntry.case_id == Case.id]
        if listed_from is not None:
            conds.append(Causelist.list_date >= listed_from)
        if listed_to is not None:
            conds.append(Causelist.list_date <= listed_to)
        stmt = stmt.where(
            exists(
                select(1)
                .select_from(CauselistEntry)
                .join(Causelist, Causelist.id == CauselistEntry.causelist_id)
                .where(and_(*conds))
            )
        )
    if status is not None:
        stmt = stmt.where(Case.status == status)
    if case_type:
        stmt = stmt.where(func.upper(Case.case_type_text) == case_type.strip().upper())
    if year is not None:
        stmt = stmt.where(Case.reg_year == year)
    if min_score is not None:
        if not (0 <= float(min_score) <= 1):
            raise InboxError("min_score is between 0 and 1")
        stmt = stmt.where(
            exists().where(CaseOfficeScore.case_id == Case.id, CaseOfficeScore.score >= float(min_score))
        )
    if state_party is True:
        stmt = stmt.where(_state_party_condition(session))
    elif state_party is False:
        stmt = stmt.where(~_state_party_condition(session))
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
    q: str | None = None,
    listed_from: date | None = None,
    listed_to: date | None = None,
    status: CaseStatus | str | None = None,
    case_type: str | None = None,
    year: int | None = None,
    min_score: float | None = None,
    state_party: bool | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> Page:
    _pool_allowed(session, user)
    status_v = CaseStatus(status) if status else None
    limit, offset = clamp(limit, offset)
    stmt = pool_stmt(
        session,
        q=q,
        listed_from=listed_from,
        listed_to=listed_to,
        status=status_v,
        case_type=case_type,
        year=year,
        min_score=min_score,
        state_party=state_party,
    )
    total = _count(session, stmt)
    cases = list(
        session.scalars(
            stmt.order_by(Case.next_hearing_date.asc().nulls_last(), Case.created_at, Case.id)
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
    department: Office, *, direction: Direction | None = None, status: TransferStatus | None = None
) -> Select:
    stmt = select(OwnershipTransfer, Case).join(Case, Case.id == OwnershipTransfer.case_id)
    if direction == "in":
        stmt = stmt.where(OwnershipTransfer.to_office_id == department.id)
    elif direction == "out":
        stmt = stmt.where(OwnershipTransfer.from_office_id == department.id)
    else:
        stmt = stmt.where(
            or_(
                OwnershipTransfer.to_office_id == department.id,
                OwnershipTransfer.from_office_id == department.id,
            )
        )
    if status is not None:
        stmt = stmt.where(OwnershipTransfer.status == status)
    return stmt


def transfers(
    session: Session,
    user: User,
    *,
    office: str | None = None,
    direction: str | None = None,
    status: TransferStatus | str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> Page:
    view_all = access.has(session, user, Permission.CASES_VIEW_ALL)
    own = user_department(session, user)
    if office:
        dept = find_office(session, office)
        if dept is None or not is_department(dept):
            raise InboxError(f"{office!r} is not a department")
        if not (view_all or (own is not None and own.id == dept.id and _transfers_allowed(session, user))):
            raise access.Forbidden("cases.view_all is needed to read another department's transfers")
    else:
        if own is None:
            if view_all:
                raise OfficeRequired("office is required: you do not belong to a department")
            raise access.Forbidden("you do not belong to a department")
        if not (_transfers_allowed(session, user) or view_all):
            raise access.Forbidden("cases.transfer_request or cases.transfer_decide is needed")
        dept = own
    if direction is not None and direction not in ("in", "out"):
        raise InboxError("direction is in or out")
    status_v = TransferStatus(status) if status else None
    limit, offset = clamp(limit, offset)
    stmt = transfers_stmt(dept, direction=direction, status=status_v)  # type: ignore[arg-type]
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


def counts(session: Session, user: User, *, office: str | None = None, today: date | None = None) -> dict:
    """The dashboard counters, each under the rule of its tab; a count is None when the caller lacks that
    tab's function (or has no department and named no office)."""
    access.require(session, user, Permission.CASES_VIEW_SCOPE)
    today = today or date.today()
    out: dict[str, int | None] = {
        "recommended_high": None,
        "recommended_medium": None,
        "claimed_active": None,
        "claimed_disposed": None,
        "transfers_in_open": None,
        "pool_with_hearing_7d": None,
    }
    view_all = access.has(session, user, Permission.CASES_VIEW_ALL)
    own = user_department(session, user)
    dept: Office | None = None
    if office:
        o = find_office(session, office)
        if o is None or not is_department(o):
            raise InboxError(f"{office!r} is not a department")
        if not (view_all or (own is not None and own.id == o.id)):
            raise access.Forbidden("cases.view_all is needed to read another department's counts")
        dept = o
    else:
        dept = own
    reading_own = dept is not None and own is not None and dept.id == own.id
    if dept is not None:
        if view_all or (reading_own and access.has(session, user, Permission.CASES_CLAIM)):
            out["recommended_high"] = _count(session, recommended_stmt(dept, band=ScoreBand.HIGH))
            out["recommended_medium"] = _count(session, recommended_stmt(dept, band=ScoreBand.MEDIUM))
        whole = True if view_all else None
        out["claimed_active"] = _count(
            session, claimed_stmt(session, user, dept, case_state="active", whole=whole)
        )
        out["claimed_disposed"] = _count(
            session, claimed_stmt(session, user, dept, case_state="disposed", whole=whole)
        )
        if view_all or (reading_own and _transfers_allowed(session, user)):
            out["transfers_in_open"] = _count(
                session, transfers_stmt(dept, direction="in", status=TransferStatus.REQUESTED)
            )
    if view_all or access.has(session, user, Permission.CASES_CLAIM):
        out["pool_with_hearing_7d"] = _count(
            session,
            pool_stmt(session).where(
                Case.next_hearing_date >= today, Case.next_hearing_date <= today + timedelta(days=7)
            ),
        )
    return out
