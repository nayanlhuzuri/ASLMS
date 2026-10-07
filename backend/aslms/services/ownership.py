"""The human ownership decisions (design `recommend-and-claim`, decisions 6-11 and 22): claim, dismiss, suggest
another department, allot, take over, stop watching, and transfers.

- A case belongs to a department only after it claims it. The pool is "cases that have never had a primary
  owner"; once claimed, a case never returns to it: it stays with the last primary owner (also after
  disposal) and leaves that department only by a transfer the target accepts. A watcher may stop watching.
- Every action takes the case row lock, checks the state, writes an `audit_log` row (with `case_id`) and an
  event, moves custody when the primary row changes holder, and rescores linked cases after a claim, a
  transfer accept and a stop-watching. Refusals write nothing.
- A case another department owns is invisible to the actor (NotVisible, HTTP 404), not forbidden.
- Memberships (design `user-memberships`, decision 6): the department that acts is the caller's membership in
  it, resolved by the server (`acting_member`): the department named by `office_code`, else the primary
  membership's department when it qualifies (holds the function and, for a case action, relates to the case),
  else the single qualifying membership, else 400 `office_required` with the candidate codes. The function is
  checked in that membership, so an admin of one department who is an officer of another cannot allot there."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aslms.domain.cases import Case
from aslms.domain.org import Office, User
from aslms.domain.ownership import (
    CaseOfficeScore,
    CaseOwnership,
    OwnershipRole,
    OwnershipStatus,
    OwnershipTransfer,
    Recommendation,
    RecommendationOrigin,
    RecommendationStatus,
    ScoreBand,
    TransferStatus,
)
from aslms.domain.reference import EventType, Permission, RecordType
from aslms.services import access, matching
from aslms.services import scoring_settings as ss
from aslms.services.access import Member
from aslms.services.audit import Actor, snapshot, write_audit
from aslms.services.cases import emit_event
from aslms.services.custody import move_custody
from aslms.services.offices import find_office
from aslms.services.refno import allocate_ref_no
from aslms.services.visibility import in_subtree, is_department


class OwnershipError(ValueError):
    """Bad input (HTTP 400)."""


class OwnershipConflict(OwnershipError):
    """The state does not allow the action (HTTP 409). `code` is a machine-readable reason."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


class NotVisible(OwnershipError):
    """The case, recommendation or transfer is not visible to the actor (HTTP 404)."""


class OfficeRequired(OwnershipError):
    """The caller works in several departments and the action does not say which (HTTP 400
    `office_required`, with the candidate department codes)."""

    code = "office_required"

    def __init__(self, candidates: list[str]) -> None:
        self.candidates = candidates
        super().__init__("office_code is required: you work in " + ", ".join(candidates))


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET: Any = _Unset()
NOT_OFFICERS = access.NOT_OFFICERS
MAX_REASON = 500


@dataclass
class SuggestResult:
    own: Recommendation | None
    target: Recommendation
    target_already_recommended: bool


@dataclass
class TakeOverResult:
    ownership: CaseOwnership
    previous: User | None


# ------------------------------------------------------------------------------------------------ helpers


def _now() -> datetime:
    return datetime.now(UTC)


def _lock(session: Session, case: Case) -> None:
    session.execute(select(Case.id).where(Case.id == case.id).with_for_update())


def _office(session: Session, office_id) -> Office | None:
    return session.get(Office, office_id) if office_id else None


def _code(session: Session, office_id) -> str | None:
    o = _office(session, office_id)
    return o.code if o else None


def _reason(value: str | None, *, required: bool = False) -> str | None:
    text = (value or "").strip() or None
    if required and text is None:
        raise OwnershipError("a reason is required")
    if text and len(text) > MAX_REASON:
        raise OwnershipError(f"the reason is at most {MAX_REASON} characters")
    return text


def _event(
    session: Session, kind: EventType, case: Case, actor: Actor, payload: dict, *, scoped: bool = False
) -> None:
    emit_event(
        session,
        kind,
        case,
        payload,
        dedupe=f"{kind.value}:{case.id}:{uuid.uuid4()}",
        scoped=scoped,
        actor_user_id=actor.user_id,
    )


def _active_rows(session: Session, case: Case) -> list[CaseOwnership]:
    return list(
        session.scalars(
            select(CaseOwnership).where(
                CaseOwnership.case_id == case.id, CaseOwnership.status == OwnershipStatus.ACTIVE
            )
        ).all()
    )


def _active_row(session: Session, case: Case, office: Office) -> CaseOwnership | None:
    return next((r for r in _active_rows(session, case) if r.office_id == office.id), None)


def _active_rec(session: Session, case: Case, office: Office) -> Recommendation | None:
    return session.scalar(
        select(Recommendation).where(
            Recommendation.case_id == case.id,
            Recommendation.office_id == office.id,
            Recommendation.status == RecommendationStatus.RECOMMENDED,
        )
    )


def ever_owned(session: Session, case: Case) -> bool:
    """True once any department has held the primary role (the case is out of the pool for good)."""
    return bool(
        session.scalar(
            select(
                exists().where(CaseOwnership.case_id == case.id, CaseOwnership.role == OwnershipRole.PRIMARY)
            )
        )
    )


def _department_office(session: Session, code: str) -> Office:
    office = find_office(session, code)
    if office is None or not office.is_active or not is_department(office):
        raise OwnershipError(f"{code!r} is not an active department")
    return office


def acting_member(
    session: Session,
    actor_user: User | Member,
    office_code: str | None = None,
    permission: Permission | None = None,
    *,
    relation: Callable[[Office], bool] | None = None,
) -> tuple[Member, Office]:
    """Decision 6 of `user-memberships`: the membership that acts for a department, and that department.

    `office_code` names the department (honoured for any caller with a membership there; the super admin acts
    for any department). Without it: the primary membership's department when it qualifies (holds `permission`
    and satisfies `relation`), else the single qualifying membership, else 400 `office_required`. A membership
    that relates to the case but lacks the function → Forbidden; nothing related → NotVisible (or a 400 when
    the caller belongs to no department)."""
    members = access.members(session, actor_user)
    if office_code:
        target = _department_office(session, office_code)
        mine = access.member_in_department(session, actor_user, target)
        if mine is not None:
            if permission is not None and not mine.holds(permission):
                raise access.Forbidden(f"{permission.value} is not enabled for you in {target.code}")
            return mine, target
        sa_member = access.super_admin_member(session, actor_user)
        if sa_member is not None:
            return sa_member, target
        raise OwnershipError(
            f"you have no membership in {target.code}; office_code names your own department"
        )
    with_dept = [m for m in members if m.department is not None]
    if not with_dept:
        raise OwnershipError("you do not belong to a department; the super admin names office_code")
    related = [m for m in with_dept if relation is None or relation(m.department)]
    qualifying = [m for m in related if permission is None or m.holds(permission)]
    if qualifying:
        primary = members[0] if members else None
        if primary is not None and any(m is primary for m in qualifying):
            return primary, primary.department
        if len(qualifying) == 1:
            return qualifying[0], qualifying[0].department
        raise OfficeRequired([m.department.code for m in qualifying])
    if related and permission is not None:
        raise access.Forbidden(f"{permission.value} is not enabled for you in {related[0].department.code}")
    raise NotVisible("no such case")


def acting_department(session: Session, actor_user: User | Member, office_code: str | None = None) -> Office:
    """The department the caller acts for (compatibility helper over `acting_member`)."""
    return acting_member(session, actor_user, office_code)[1]


def eligible_officer(session: Session, department: Office, user: User | None) -> bool:
    """An active login with an active membership in the department's subtree, of any type except the
    State-wide ones (decision 9; per membership since `user-memberships`)."""
    return eligible_member(session, department, user) is not None


def eligible_member(session: Session, department: Office, user: User | Member | None) -> Member | None:
    if user is None:
        return None
    if isinstance(user, Member):
        candidates = [user] if user.is_active else []
    else:
        candidates = access.members(session, user)
    for m in candidates:
        if m.role not in NOT_OFFICERS and in_subtree(m.office, department):
            return m
    return None


def ownership_summary(session: Session, row: CaseOwnership) -> dict:
    return {
        "office_code": _code(session, row.office_id),
        "role": OwnershipRole(row.role).value,
        "status": OwnershipStatus(row.status).value,
        "unit_code": _code(session, row.unit_office_id),
        "officer_user_id": str(row.officer_user_id) if row.officer_user_id else None,
    }


def _rescore_linked(session: Session, case: Case) -> None:
    ids = matching.linked_case_ids(session, case)
    if ids:
        matching.score_cases(session, ids, origin=RecommendationOrigin.RESCORE)


def _flush_unique(session: Session, row, code: str) -> None:
    """Adds and flushes `row` in a savepoint; a unique-index race becomes OwnershipConflict."""
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError as exc:
        raise OwnershipConflict(code, "another change to this case happened at the same time") from exc


def _custody_for(session: Session, actor: Actor, case: Case, row: CaseOwnership, reason: str) -> None:
    if OwnershipRole(row.role) != OwnershipRole.PRIMARY:
        return
    office = _office(session, row.unit_office_id) or _office(session, row.office_id)
    user = session.get(User, row.officer_user_id) if row.officer_user_id else None
    # design custody-workflow, decision 2: the officer's membership in the department holds the file
    dept = _office(session, row.office_id)
    member = eligible_member(session, dept, user) if user is not None and dept is not None else None
    move_custody(
        session,
        actor,
        case,
        office=office,
        user=user,
        membership=member.membership if member is not None else None,
        reason=reason,
    )


# ------------------------------------------------------------------------------------------------ claim


def claim(
    session: Session,
    actor: Actor,
    actor_user: User,
    case: Case,
    *,
    office_code: str | None = None,
    unit_code: str | None = None,
    officer_user_id: uuid.UUID | None = None,
    note: str | None = None,
) -> CaseOwnership:
    access.require(session, actor_user, Permission.CASES_CLAIM)
    allot_too = unit_code is not None or officer_user_id is not None
    if allot_too:
        access.require(session, actor_user, Permission.CASES_ALLOT)
    note = _reason(note)
    member, dept = acting_member(session, actor_user, office_code, Permission.CASES_CLAIM)
    if allot_too and not member.holds(Permission.CASES_ALLOT):
        raise access.Forbidden(f"cases.allot is not enabled for you in {dept.code}")
    actor = access.actor_as(actor, member)
    _lock(session, case)
    session.refresh(case)
    if case.merged_into_case_id is not None:
        raise OwnershipError("the case was merged into another case")
    rec = _active_rec(session, case, dept)
    rows = _active_rows(session, case)
    if any(r.office_id == dept.id for r in rows):
        raise OwnershipConflict("already_claimed", f"{dept.code} already holds this case")
    if ever_owned(session, case) and rec is None:
        raise NotVisible("no such case")
    has_primary = any(OwnershipRole(r.role) == OwnershipRole.PRIMARY for r in rows)
    row = CaseOwnership(
        case_id=case.id,
        office_id=dept.id,
        role=OwnershipRole.WATCHER if has_primary else OwnershipRole.PRIMARY,
        claimed_at=_now(),
        status=OwnershipStatus.ACTIVE,
        **snapshot(actor),
    )
    _flush_unique(session, row, "already_claimed")
    if rec is not None:
        rec.status, rec.acted_at = RecommendationStatus.CLAIMED, _now()
    session.flush()
    write_audit(
        session,
        actor,
        "ownership.claim",
        "case_ownership",
        row.id,
        after={**ownership_summary(session, row), "note": note},
        case_id=case.id,
    )
    _event(
        session,
        EventType.CLAIMED,
        case,
        actor,
        {"ownership_id": str(row.id), "office_code": dept.code, "role": OwnershipRole(row.role).value},
    )
    _custody_for(session, actor, case, row, "claimed")
    if allot_too:
        _apply_allot(
            session,
            actor,
            case,
            row,
            dept,
            unit_code=unit_code or UNSET,
            officer_user_id=officer_user_id or UNSET,
        )
    _rescore_linked(session, case)
    return row


# ------------------------------------------------------------------------------------------------ dismiss / suggest


def dismiss(
    session: Session, actor: Actor, actor_user: User, case: Case, *, reason: str | None = None
) -> Recommendation:
    access.require(session, actor_user, Permission.CASES_DISMISS)
    reason = _reason(reason)
    member, dept = acting_member(
        session,
        actor_user,
        None,
        Permission.CASES_DISMISS,
        relation=lambda d: _active_rec(session, case, d) is not None,
    )
    actor = access.actor_as(actor, member)
    _lock(session, case)
    rec = _active_rec(session, case, dept)
    if rec is None:
        raise NotVisible("no recommendation of your department for this case")
    rec.status, rec.acted_at, rec.reason = RecommendationStatus.DISMISSED, _now(), reason
    session.flush()
    write_audit(
        session,
        actor,
        "recommendation.dismiss",
        "recommendation",
        rec.id,
        before={"status": "recommended"},
        after={"status": "dismissed", "office_code": dept.code, "reason": reason},
        case_id=case.id,
    )
    _event(
        session,
        EventType.DISMISSED,
        case,
        actor,
        {"recommendation_id": str(rec.id), "office_code": dept.code, "reason": reason},
        scoped=True,
    )
    return rec


def suggest(
    session: Session, actor: Actor, actor_user: User, case: Case, *, office_code: str, reason: str
) -> SuggestResult:
    access.require(session, actor_user, Permission.CASES_SUGGEST_ELSEWHERE)
    reason = _reason(reason, required=True)
    target = _department_office(session, office_code)
    holders = access.holders_in(session, actor_user, Permission.CASES_SUGGEST_ELSEWHERE)
    related = [
        m
        for m in holders
        if m.department is not None
        and (
            _active_rec(session, case, m.department) is not None
            or _active_row(session, case, m.department) is not None
        )
    ]
    member = (related or holders or [None])[0]
    own_dept = member.department if member is not None else None
    if member is not None:
        actor = access.actor_as(actor, member)
    if own_dept is not None and own_dept.id == target.id:
        raise OwnershipError("suggest a department other than your own")
    _lock(session, case)
    own = _active_rec(session, case, own_dept) if own_dept is not None else None
    visible = (
        own is not None
        or (own_dept is not None and _active_row(session, case, own_dept) is not None)
        or access.has(session, actor_user, Permission.CASES_VIEW_ALL)
        or (
            not ever_owned(session, case)
            and any(m.holds(Permission.CASES_CLAIM) for m in access.members(session, actor_user))
        )
    )
    if not visible:
        raise NotVisible("no such case")
    if _active_row(session, case, target) is not None:
        raise OwnershipConflict("target_owns", f"{target.code} already holds this case")
    existing = _active_rec(session, case, target)
    already = existing is not None
    if existing is None:
        settings = ss.current(session)
        score = session.scalar(
            select(CaseOfficeScore.score).where(
                CaseOfficeScore.case_id == case.id, CaseOfficeScore.office_id == target.id
            )
        )
        score_f = float(score) if score is not None else 0.0
        existing = Recommendation(
            case_id=case.id,
            office_id=target.id,
            score=Decimal(str(round(score_f, 3))),
            band=ScoreBand.HIGH if score_f >= settings.threshold_strong else ScoreBand.MEDIUM,
            status=RecommendationStatus.RECOMMENDED,
            origin=RecommendationOrigin.SUGGESTION,
            reason=reason,
            **snapshot(actor),
        )
        _flush_unique(session, existing, "target_already_recommended")
        emit_event(
            session,
            EventType.RECOMMENDATION_MADE,
            case,
            {
                "recommendation_id": str(existing.id),
                "office_code": target.code,
                "score": score_f,
                "band": ScoreBand(existing.band).value,
                "origin": "suggestion",
            },
            dedupe=f"recommendation_made:{existing.id}:suggestion",
            scoped=True,
            actor_user_id=actor.user_id,
        )
    if own is not None:
        own.status, own.acted_at = RecommendationStatus.SUGGESTED_ELSEWHERE, _now()
        own.suggested_office_id, own.reason = target.id, reason
    session.flush()
    write_audit(
        session,
        actor,
        "recommendation.suggest",
        "recommendation",
        (own or existing).id,
        after={
            "from_office_code": own_dept.code if own_dept else None,
            "to_office_code": target.code,
            "target_recommendation_id": str(existing.id),
            "target_already_recommended": already,
            "reason": reason,
        },
        case_id=case.id,
    )
    _event(
        session,
        EventType.SUGGESTED_ELSEWHERE,
        case,
        actor,
        {
            "from_office_code": own_dept.code if own_dept else None,
            "to_office_code": target.code,
            "reason": reason,
        },
        scoped=True,
    )
    return SuggestResult(own, existing, already)


# ------------------------------------------------------------------------------------------------ allot / take over


def _apply_allot(
    session: Session,
    actor: Actor,
    case: Case,
    row: CaseOwnership,
    dept: Office,
    *,
    unit_code: Any = UNSET,
    officer_user_id: Any = UNSET,
) -> CaseOwnership:
    before = ownership_summary(session, row)
    if unit_code is not UNSET:
        if unit_code is None:
            row.unit_office_id = None
        else:
            unit = find_office(session, unit_code)
            if unit is None or not unit.is_active or unit.id == dept.id or not in_subtree(unit, dept):
                raise OwnershipError(f"{unit_code!r} is not an active office inside {dept.code}")
            row.unit_office_id = unit.id
    if officer_user_id is not UNSET:
        if officer_user_id is None:
            row.officer_user_id = None
        else:
            officer = session.get(User, officer_user_id)
            if not eligible_officer(session, dept, officer):
                raise OwnershipError(f"the officer is not an eligible user of {dept.code}")
            row.officer_user_id = officer.id
    after = ownership_summary(session, row)
    if after == before:
        return row
    row.allotted_at, row.allotted_by_user_id = _now(), actor.user_id
    session.flush()
    write_audit(
        session,
        actor,
        "ownership.allot",
        "case_ownership",
        row.id,
        before=before,
        after=after,
        case_id=case.id,
    )
    _event(
        session,
        EventType.ALLOTTED,
        case,
        actor,
        {
            "ownership_id": str(row.id),
            "office_code": dept.code,
            "unit_code": after["unit_code"],
            "officer_user_id": after["officer_user_id"],
        },
    )
    _custody_for(session, actor, case, row, "allotted")
    return row


def allot(
    session: Session,
    actor: Actor,
    actor_user: User,
    case: Case,
    *,
    unit_code: Any = UNSET,
    officer_user_id: Any = UNSET,
) -> CaseOwnership:
    """Allots the actor's department's active row (primary or watcher) to a unit and/or an officer; `None`
    clears, UNSET leaves as is."""
    access.require(session, actor_user, Permission.CASES_ALLOT)
    member, dept = acting_member(
        session,
        actor_user,
        None,
        Permission.CASES_ALLOT,
        relation=lambda d: _active_row(session, case, d) is not None,
    )
    actor = access.actor_as(actor, member)
    _lock(session, case)
    row = _active_row(session, case, dept)
    if row is None:
        raise NotVisible("no such case")
    return _apply_allot(session, actor, case, row, dept, unit_code=unit_code, officer_user_id=officer_user_id)


def take_over(
    session: Session,
    actor: Actor,
    actor_user: User,
    case: Case,
    *,
    expected_officer_user_id: uuid.UUID | None = None,
    reason: str | None = None,
) -> TakeOverResult:
    """A user of the owning department takes over a case allotted to a colleague (decision 22). No approval;
    the unit follows the taker."""
    access.require(session, actor_user, Permission.CASES_TAKE_OVER)
    reason = _reason(reason)
    taker: Member | None = None
    for m in access.holders_in(session, actor_user, Permission.CASES_TAKE_OVER):
        if m.department is None or eligible_member(session, m.department, m) is None:
            continue
        if _active_row(session, case, m.department) is not None:
            taker = m
            break
    if taker is None:
        raise NotVisible("no such case")
    actor = access.actor_as(actor, taker)
    actor_office, dept = taker.office, taker.department
    _lock(session, case)
    row = _active_row(session, case, dept)
    if row is None:
        raise NotVisible("no such case")
    if row.officer_user_id is None:
        raise OwnershipConflict("not_allotted", "the case is not allotted to an officer; allot it instead")
    if row.officer_user_id == taker.id:
        raise OwnershipConflict("already_holder", "you already hold this case")
    if expected_officer_user_id is not None and expected_officer_user_id != row.officer_user_id:
        raise OwnershipConflict("stale", "the case was allotted to someone else meanwhile")
    before = ownership_summary(session, row)
    previous = session.get(User, row.officer_user_id)
    unit = _office(session, row.unit_office_id)
    if unit is None or not in_subtree(actor_office, unit):
        row.unit_office_id = None if actor_office.id == dept.id else actor_office.id
    row.officer_user_id = taker.id
    row.allotted_at, row.allotted_by_user_id = _now(), taker.id
    session.flush()
    after = ownership_summary(session, row)
    write_audit(
        session,
        actor,
        "ownership.take_over",
        "case_ownership",
        row.id,
        before=before,
        after={**after, "reason": reason},
        case_id=case.id,
    )
    _event(
        session,
        EventType.CASE_TAKEN_OVER,
        case,
        actor,
        {
            "ownership_id": str(row.id),
            "office_code": dept.code,
            "role": OwnershipRole(row.role).value,
            "from_user_id": str(previous.id) if previous else None,
            "from_user_name": previous.full_name if previous else None,
            "to_user_id": str(taker.id),
            "to_user_name": taker.full_name,
            "from_unit_code": before["unit_code"],
            "to_unit_code": after["unit_code"],
            "reason": reason,
            "taken_at": row.allotted_at.isoformat(),
        },
    )
    _custody_for(session, actor, case, row, "taken_over")
    return TakeOverResult(row, previous)


# ------------------------------------------------------------------------------------------------ stop watching


def stop_watching(
    session: Session, actor: Actor, actor_user: User, case: Case, *, reason: str
) -> CaseOwnership:
    """Ends the department's watcher row. A primary row is never released (decision 10)."""
    access.require(session, actor_user, Permission.CASES_RELEASE)
    reason = _reason(reason, required=True)
    member, dept = acting_member(
        session,
        actor_user,
        None,
        Permission.CASES_RELEASE,
        relation=lambda d: _active_row(session, case, d) is not None,
    )
    actor = access.actor_as(actor, member)
    _lock(session, case)
    row = _active_row(session, case, dept)
    if row is None:
        raise NotVisible("no such case")
    if OwnershipRole(row.role) == OwnershipRole.PRIMARY:
        raise OwnershipConflict(
            "primary_cannot_release", "the primary owner cannot let go; transfer the case instead"
        )
    before = ownership_summary(session, row)
    row.status, row.released_at, row.release_reason = OwnershipStatus.RELEASED, _now(), reason
    session.flush()
    write_audit(
        session,
        actor,
        "ownership.unwatch",
        "case_ownership",
        row.id,
        before=before,
        after={**ownership_summary(session, row), "reason": reason},
        case_id=case.id,
    )
    _event(
        session,
        EventType.OWNERSHIP_RELEASED,
        case,
        actor,
        {"ownership_id": str(row.id), "office_code": dept.code, "role": "watcher", "reason": reason},
        scoped=True,
    )
    _rescore_linked(session, case)
    return row


# ------------------------------------------------------------------------------------------------ transfers


def transfer_summary(session: Session, t: OwnershipTransfer) -> dict:
    return {
        "ref_no": t.ref_no,
        "from_office_code": _code(session, t.from_office_id),
        "to_office_code": _code(session, t.to_office_id),
        "status": TransferStatus(t.status).value,
        "stay_as_watcher": t.stay_as_watcher,
        "reason": t.reason,
        "decision_note": t.decision_note,
    }


def request_transfer(
    session: Session,
    actor: Actor,
    actor_user: User,
    case: Case,
    *,
    to_office_code: str,
    reason: str,
    stay_as_watcher: bool = False,
) -> OwnershipTransfer:
    access.require(session, actor_user, Permission.CASES_TRANSFER_REQUEST)
    reason = _reason(reason, required=True)
    member, dept = acting_member(
        session,
        actor_user,
        None,
        Permission.CASES_TRANSFER_REQUEST,
        relation=lambda d: _active_row(session, case, d) is not None,
    )
    actor = access.actor_as(actor, member)
    target = _department_office(session, to_office_code)
    if target.id == dept.id:
        raise OwnershipError("a transfer goes to another department")
    _lock(session, case)
    row = _active_row(session, case, dept)
    if row is None:
        raise NotVisible("no such case")
    if OwnershipRole(row.role) != OwnershipRole.PRIMARY:
        raise OwnershipConflict("not_primary", "only the primary owner may request a transfer")
    open_ = session.scalar(
        select(OwnershipTransfer.id).where(
            OwnershipTransfer.case_id == case.id, OwnershipTransfer.status == TransferStatus.REQUESTED
        )
    )
    if open_ is not None:
        raise OwnershipConflict("transfer_open", "a transfer request is already open for this case")
    t = OwnershipTransfer(
        case_id=case.id,
        from_office_id=dept.id,
        to_office_id=target.id,
        status=TransferStatus.REQUESTED,
        reason=reason,
        stay_as_watcher=bool(stay_as_watcher),
        ref_no=allocate_ref_no(session, dept.code, RecordType.TRF.value),
        **snapshot(actor),
    )
    _flush_unique(session, t, "transfer_open")
    write_audit(
        session,
        actor,
        "transfer.request",
        "ownership_transfer",
        t.id,
        after=transfer_summary(session, t),
        case_id=case.id,
    )
    _event(
        session,
        EventType.TRANSFER_REQUESTED,
        case,
        actor,
        {
            "transfer_id": str(t.id),
            "ref_no": t.ref_no,
            "from_office_code": dept.code,
            "to_office_code": target.code,
        },
        scoped=True,
    )
    return t


def decide_transfer(
    session: Session,
    actor: Actor,
    actor_user: User,
    transfer: OwnershipTransfer,
    *,
    accept: bool,
    note: str | None = None,
) -> OwnershipTransfer:
    access.require(session, actor_user, Permission.CASES_TRANSFER_DECIDE)
    note = _reason(note)
    try:
        member, dept = acting_member(
            session,
            actor_user,
            None,
            Permission.CASES_TRANSFER_DECIDE,
            relation=lambda d: transfer.to_office_id == d.id,
        )
    except NotVisible as exc:
        raise NotVisible("no such transfer") from exc
    actor = access.actor_as(actor, member)
    if transfer.to_office_id != dept.id:
        raise NotVisible("no such transfer")
    case = session.get(Case, transfer.case_id)
    _lock(session, case)
    session.refresh(transfer)
    if TransferStatus(transfer.status) != TransferStatus.REQUESTED:
        raise OwnershipConflict("not_open", "the transfer is no longer open")
    before = transfer_summary(session, transfer)
    now = _now()
    if accept:
        rows = _active_rows(session, case)
        old = next(
            (r for r in rows if r.office_id == transfer.from_office_id and r.role == OwnershipRole.PRIMARY),
            None,
        )
        if old is None:
            raise OwnershipConflict("not_open", "the requesting department no longer holds the case")
        old.status, old.released_at = OwnershipStatus.TRANSFERRED, now
        session.flush()
        watcher = next((r for r in rows if r.office_id == dept.id), None)
        if watcher is not None:
            watcher.role = OwnershipRole.PRIMARY
            new = watcher
            session.flush()
        else:
            new = CaseOwnership(
                case_id=case.id,
                office_id=dept.id,
                role=OwnershipRole.PRIMARY,
                claimed_at=now,
                status=OwnershipStatus.ACTIVE,
                **snapshot(actor),
            )
            _flush_unique(session, new, "already_claimed")
        if transfer.stay_as_watcher:
            _flush_unique(
                session,
                CaseOwnership(
                    case_id=case.id,
                    office_id=transfer.from_office_id,
                    role=OwnershipRole.WATCHER,
                    claimed_at=now,
                    status=OwnershipStatus.ACTIVE,
                    **snapshot(actor),
                ),
                "already_claimed",
            )
        rec = _active_rec(session, case, dept)
        if rec is not None:
            rec.status, rec.acted_at = RecommendationStatus.CLAIMED, now
        transfer.status = TransferStatus.ACCEPTED
    else:
        transfer.status = TransferStatus.DECLINED
    transfer.decision_note = note
    transfer.decided_by_user_id, transfer.decided_at = actor.user_id, now
    session.flush()
    write_audit(
        session,
        actor,
        "transfer.accept" if accept else "transfer.decline",
        "ownership_transfer",
        transfer.id,
        before=before,
        after=transfer_summary(session, transfer),
        case_id=case.id,
    )
    _event(
        session,
        EventType.TRANSFER_DECIDED,
        case,
        actor,
        {
            "transfer_id": str(transfer.id),
            "ref_no": transfer.ref_no,
            "decision": "accepted" if accept else "declined",
            "to_office_code": dept.code,
        },
        scoped=True,
    )
    if accept:
        move_custody(session, actor, case, office=dept, reason="transferred")
        _rescore_linked(session, case)
    return transfer


def withdraw_transfer(
    session: Session, actor: Actor, actor_user: User, transfer: OwnershipTransfer
) -> OwnershipTransfer:
    access.require(session, actor_user, Permission.CASES_TRANSFER_REQUEST)
    try:
        member, dept = acting_member(
            session,
            actor_user,
            None,
            Permission.CASES_TRANSFER_REQUEST,
            relation=lambda d: transfer.from_office_id == d.id,
        )
    except NotVisible as exc:
        raise NotVisible("no such transfer") from exc
    actor = access.actor_as(actor, member)
    if transfer.from_office_id != dept.id:
        raise NotVisible("no such transfer")
    case = session.get(Case, transfer.case_id)
    _lock(session, case)
    session.refresh(transfer)
    if TransferStatus(transfer.status) != TransferStatus.REQUESTED:
        raise OwnershipConflict("not_open", "the transfer is no longer open")
    before = transfer_summary(session, transfer)
    transfer.status, transfer.withdrawn_at = TransferStatus.WITHDRAWN, _now()
    session.flush()
    write_audit(
        session,
        actor,
        "transfer.withdraw",
        "ownership_transfer",
        transfer.id,
        before=before,
        after=transfer_summary(session, transfer),
        case_id=case.id,
    )
    _event(
        session,
        EventType.TRANSFER_DECIDED,
        case,
        actor,
        {"transfer_id": str(transfer.id), "ref_no": transfer.ref_no, "decision": "withdrawn"},
        scoped=True,
    )
    return transfer


def resolve_transfer(session: Session, ref: str) -> OwnershipTransfer:
    """A transfer by id or `ref_no` (slash or dash form)."""
    from aslms.services.cases import ref_no_from_url

    s = (ref or "").strip()
    t = None
    try:
        t = session.get(OwnershipTransfer, uuid.UUID(s))
    except ValueError:
        ref_no = ref_no_from_url(s)
        if ref_no is not None:
            t = session.scalar(select(OwnershipTransfer).where(OwnershipTransfer.ref_no == ref_no))
    if t is None:
        raise NotVisible("no such transfer")
    return t


# ------------------------------------------------------------------------------------------------ reading


def case_ownership_view(session: Session, actor_user: User, case: Case) -> dict:
    """Primary, watchers, recommendations and the open transfer, for a caller who may see them: the caller's
    department owns, watches or has a recommendation for the case, or the case is in the pool and the caller
    holds `cases.claim`, or the caller holds `cases.view_all`. Other departments' recommendations only with
    `cases.view_all`. Otherwise NotVisible."""
    view_all = access.has(session, actor_user, Permission.CASES_VIEW_ALL)
    dept_ids = {d.id for d in access.departments(session, actor_user)}
    rows = _active_rows(session, case)
    recs = list(session.scalars(select(Recommendation).where(Recommendation.case_id == case.id)).all())
    mine = any(r.office_id in dept_ids for r in rows) or any(
        r.office_id in dept_ids and r.status == RecommendationStatus.RECOMMENDED for r in recs
    )
    pool = not ever_owned(session, case) and any(
        m.holds(Permission.CASES_CLAIM) and m.department is not None
        for m in access.members(session, actor_user)
    )
    if not (view_all or mine or pool):
        raise NotVisible("no such case")
    if not view_all:
        recs = [r for r in recs if r.office_id in dept_ids]
    open_transfer = session.scalar(
        select(OwnershipTransfer).where(
            OwnershipTransfer.case_id == case.id, OwnershipTransfer.status == TransferStatus.REQUESTED
        )
    )
    return {
        "primary": next((r for r in rows if r.role == OwnershipRole.PRIMARY), None),
        "watchers": [r for r in rows if r.role == OwnershipRole.WATCHER],
        "recommendations": recs,
        "open_transfer": open_transfer,
    }


# ------------------------------------------------------------------------------------------------ the exit step


def reallot_on_exit(
    session: Session, actor: Actor, case: Case, *, row: CaseOwnership, from_user: User, to_member: Member
) -> CaseOwnership:
    """Design `user-memberships`, decision 21: an allotment of a leaving officer goes to the officer the admin
    chose (the officer field only; no custody leg — the file is its own exit item). The caller holds the case
    row lock. Event `allotted` with `on_exit: true`; audit `ownership.reallotted_on_exit`."""
    if row.officer_user_id != from_user.id or OwnershipStatus(row.status) != OwnershipStatus.ACTIVE:
        raise OwnershipConflict("stale", "the case is no longer allotted to the leaving officer")
    dept = session.get(Office, row.office_id)
    before = ownership_summary(session, row)
    row.officer_user_id = to_member.id
    row.allotted_at, row.allotted_by_user_id = _now(), actor.user_id
    session.flush()
    after = ownership_summary(session, row)
    write_audit(
        session,
        actor,
        "ownership.reallotted_on_exit",
        "case_ownership",
        row.id,
        before=before,
        after={**after, "from_user_id": str(from_user.id), "to_membership_id": str(to_member.membership_id)},
        case_id=case.id,
    )
    _event(
        session,
        EventType.ALLOTTED,
        case,
        actor,
        {
            "ownership_id": str(row.id),
            "office_code": dept.code if dept else None,
            "unit_code": after["unit_code"],
            "officer_user_id": after["officer_user_id"],
            "on_exit": True,
        },
    )
    return row
