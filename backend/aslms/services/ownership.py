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
  checked in that membership, so an admin of one department who is an officer of another cannot allot there.
- Design `ownership-refinements` (owner decisions of 21 Oct 2026): a primary claim closes every other department's
  open recommendation as `claimed_elsewhere` (event `recommendation_closed`, listed in the claim's audit row), and
  a stale Claim, Dismiss or Suggest of such a department answers 409 `claimed_elsewhere`. A claim (primary or
  watcher) and an accepted transfer queue a court refresh (`dossier`, lane `request`, priority 30, the person as
  `requested_by`) when the case has no full court record or one older than `CLAIM_REFRESH_AFTER`; the queue and
  the worker do the fetch, and the outcome (`court_refresh`) is in the claim's or transfer's audit row. The claim
  never waits for or fails on the refresh."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import ColumnElement, and_, exists, false, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from aslms.domain.cases import Case
from aslms.domain.ops import FetchKind, FetchLane
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
from aslms.services import access, matching, napix_window, queue
from aslms.services import scoring_settings as ss
from aslms.services.access import DEPARTMENT_TIER_KINDS, Member
from aslms.services.audit import Actor, snapshot, write_audit
from aslms.services.cases import emit_event
from aslms.services.custody import move_custody
from aslms.services.offices import find_office
from aslms.services.refno import allocate_ref_no
from aslms.services.visibility import in_subtree, is_department, never_owned, whole_department


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
# design ownership-refinements, decision 1: a claim or an accepted transfer queues a court refresh when the case's
# full court record is missing or older than this (fixed by the owner; not a setting)
CLAIM_REFRESH_AFTER = timedelta(hours=24)
CLAIMED_ELSEWHERE_MESSAGE = "{code} claimed this case; your department's recommendation is closed"

log = structlog.get_logger(__name__)


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
        raise OwnershipError("you do not belong to a department; the Super Administrator names office_code")
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


def _queue_court_refresh(session: Session, case: Case, requester: User | Member | None) -> str:
    """Design `ownership-refinements`, decisions 1 to 3: one `dossier` row through the queue (lane `request`, priority
    30, `requeue`, the person as `requested_by`) when the case has no full court record or one older than
    `CLAIM_REFRESH_AFTER`. No NAPIX call and no integration client here: the worker fetches the row. Returns `fresh`,
    `queued` (pending after the call), `in_progress` (being fetched now), `no_reference` (neither a CNR nor a case
    number) or `failed` (logged with the case `ref_no` and the exception class). Never raises."""
    from aslms.services import napix_admin  # local: napix_admin reaches services that import this module

    fetched = case.last_full_refresh_at
    if fetched is not None and fetched >= _now() - CLAIM_REFRESH_AFTER:
        return "fresh"
    try:
        with session.begin_nested():
            ref = napix_admin.dossier_ref(session, case)
            pending = queue.enqueue(
                session,
                FetchKind.DOSSIER,
                ref,
                queue.PRIORITY["request"],
                requeue=True,
                lane=FetchLane.REQUEST,
                requested_by=napix_window.user_id_of(requester),
            )
    except napix_admin.NoReference:
        return "no_reference"
    except Exception as exc:  # noqa: BLE001 - the claim never fails on the refresh (decision 3)
        log.warning("ownership.court_refresh_failed", case_ref=case.ref_no, error=exc.__class__.__name__)
        return "failed"
    return "queued" if pending else "in_progress"


def _primary_code(session: Session, case: Case) -> str | None:
    row = next((r for r in _active_rows(session, case) if r.role == OwnershipRole.PRIMARY), None)
    return _code(session, row.office_id) if row is not None else None


def closed_by_claim(session: Session, case: Case, dept: Office | None) -> bool:
    """True when the department has no open recommendation for the case and its latest one is `claimed_elsewhere`
    (design `ownership-refinements`, decision 11)."""
    if dept is None or _active_rec(session, case, dept) is not None:
        return False
    latest = session.scalar(
        select(Recommendation.status)
        .where(Recommendation.case_id == case.id, Recommendation.office_id == dept.id)
        .order_by(Recommendation.created_at.desc(), Recommendation.id.desc())
        .limit(1)
    )
    return latest is not None and RecommendationStatus(latest) == RecommendationStatus.CLAIMED_ELSEWHERE


def _refuse_if_closed(session: Session, case: Case, dept: Office | None) -> None:
    """409 `claimed_elsewhere` naming the claiming department (decision 11); nothing when not closed."""
    if closed_by_claim(session, case, dept):
        raise OwnershipConflict(
            "claimed_elsewhere",
            CLAIMED_ELSEWHERE_MESSAGE.format(code=_primary_code(session, case) or "Another department"),
        )


def _close_other_recommendations(session: Session, case: Case, dept: Office) -> list[Recommendation]:
    """Decision 9: every other department's open recommendation becomes `claimed_elsewhere` (the caller holds the
    case row lock); returns the closed rows."""
    rows = list(
        session.scalars(
            select(Recommendation)
            .where(
                Recommendation.case_id == case.id,
                Recommendation.office_id != dept.id,
                Recommendation.status == RecommendationStatus.RECOMMENDED,
            )
            .order_by(Recommendation.created_at, Recommendation.id)
        ).all()
    )
    now = _now()
    for rec in rows:
        rec.status, rec.acted_at = RecommendationStatus.CLAIMED_ELSEWHERE, now
        rec.reason = f"claimed by {dept.code}"
    session.flush()
    return rows


def _closed_event(
    session: Session,
    case: Case,
    rec: Recommendation,
    *,
    claimed_by: str | None,
    ownership_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    backfill: bool = False,
) -> None:
    """One `recommendation_closed` event per closed row (decision 10), scoped, deduplicated per recommendation."""
    payload: dict[str, Any] = {
        "recommendation_id": str(rec.id),
        "office_code": _code(session, rec.office_id),
        "claimed_by_office_code": claimed_by,
        "ownership_id": str(ownership_id) if ownership_id else None,
        "origin": RecommendationOrigin(rec.origin).value,
        "band": ScoreBand(rec.band).value,
    }
    if backfill:
        payload["backfill"] = True
    emit_event(
        session,
        EventType.RECOMMENDATION_CLOSED,
        case,
        payload,
        dedupe=f"recommendation_closed:{rec.id}",
        scoped=True,
        actor_user_id=actor_user_id,
    )


# ------------------------------------------------------------------------------------------------ claim


def _claim_state(
    session: Session, case: Case, dept: Office
) -> tuple[Recommendation | None, list[CaseOwnership]]:
    """The case-state half of the claim check: not merged, not already held by `dept`, and in the pool or
    recommended to `dept`."""
    if case.merged_into_case_id is not None:
        raise OwnershipError("the case was merged into another case")
    rec = _active_rec(session, case, dept)
    rows = _active_rows(session, case)
    if any(r.office_id == dept.id for r in rows):
        raise OwnershipConflict("already_claimed", f"{dept.code} already holds this case")
    if ever_owned(session, case) and rec is None:
        _refuse_if_closed(session, case, dept)
        raise NotVisible("no such case")
    return rec, rows


def _check_claim(
    session: Session,
    actor_user: User,
    case: Case,
    *,
    office_code: str | None = None,
    allot_too: bool = False,
) -> tuple[Member, Office, Recommendation | None, list[CaseOwnership]]:
    """Everything `claim` checks before it writes (no lock, no write); raises what `claim` raises."""
    access.require(session, actor_user, Permission.CASES_CLAIM)
    if allot_too:
        access.require(session, actor_user, Permission.CASES_ALLOT)
    member, dept = acting_member(session, actor_user, office_code, Permission.CASES_CLAIM)
    if allot_too and not member.holds(Permission.CASES_ALLOT):
        raise access.Forbidden(f"cases.allot is not enabled for you in {dept.code}")
    rec, rows = _claim_state(session, case, dept)
    return member, dept, rec, rows


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
    _lock(session, case)
    session.refresh(case)
    member, dept, rec, rows = _check_claim(
        session, actor_user, case, office_code=office_code, allot_too=allot_too
    )
    actor = access.actor_as(actor, member)
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
    # design ownership-refinements, decisions 9 and 1-3: a primary claim closes the others; a court refresh may queue
    closed = _close_other_recommendations(session, case, dept) if row.role == OwnershipRole.PRIMARY else []
    court_refresh = _queue_court_refresh(session, case, actor_user)
    write_audit(
        session,
        actor,
        "ownership.claim",
        "case_ownership",
        row.id,
        after={
            **ownership_summary(session, row),
            "note": note,
            "closed_recommendations": [
                {"recommendation_id": str(r.id), "office_code": _code(session, r.office_id)} for r in closed
            ],
            "court_refresh": court_refresh,
        },
        case_id=case.id,
    )
    _event(
        session,
        EventType.CLAIMED,
        case,
        actor,
        {"ownership_id": str(row.id), "office_code": dept.code, "role": OwnershipRole(row.role).value},
    )
    for r in closed:
        _closed_event(
            session, case, r, claimed_by=dept.code, ownership_id=row.id, actor_user_id=actor.user_id
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


def _own_department(session: Session, actor_user: User, office_code: str | None) -> str | None:
    """Design `portal-cases`, deviation 10 and `portal-cases-followups`, decision 2: `office_code` on dismiss,
    allot, take over and stop watching (and `from_office_code` on suggest) names one of the caller's own
    departments (the screen sends the department chosen); unlike claim, the super admin gains nothing here."""
    if not office_code:
        return None
    target = _department_office(session, office_code)
    if access.member_in_department(session, actor_user, target) is None:
        raise OwnershipError(
            f"you have no membership in {target.code}; office_code names your own department"
        )
    return target.code


def _check_dismiss(
    session: Session, actor_user: User, case: Case, *, office_code: str | None = None
) -> tuple[Member, Office, Recommendation]:
    access.require(session, actor_user, Permission.CASES_DISMISS)
    member, dept = acting_member(
        session,
        actor_user,
        _own_department(session, actor_user, office_code),
        Permission.CASES_DISMISS,
        relation=lambda d: _active_rec(session, case, d) is not None or closed_by_claim(session, case, d),
    )
    rec = _active_rec(session, case, dept)
    if rec is None:
        _refuse_if_closed(session, case, dept)
        raise NotVisible("no recommendation of your department for this case")
    return member, dept, rec


def dismiss(
    session: Session,
    actor: Actor,
    actor_user: User,
    case: Case,
    *,
    reason: str | None = None,
    office_code: str | None = None,
) -> Recommendation:
    access.require(session, actor_user, Permission.CASES_DISMISS)
    reason = _reason(reason)
    _lock(session, case)
    member, dept, rec = _check_dismiss(session, actor_user, case, office_code=office_code)
    actor = access.actor_as(actor, member)
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


def _check_suggest_from(
    session: Session, actor_user: User, case: Case, target: Office | None, from_office_code: str
) -> tuple[Member, Office, Recommendation | None]:
    """Design `portal-cases-followups`, decision 2: the suggestion comes from the named department, one of the
    caller's own (400), whose membership holds the function (403) and which has an active recommendation or
    row for the case (404)."""
    code = _own_department(session, actor_user, from_office_code)
    dept = _department_office(session, code)
    member = access.member_in_department(session, actor_user, dept)
    assert member is not None
    if not member.holds(Permission.CASES_SUGGEST_ELSEWHERE):
        raise access.Forbidden(f"cases.suggest_elsewhere is not enabled for you in {dept.code}")
    own = _active_rec(session, case, dept)
    if own is None and _active_row(session, case, dept) is None:
        _refuse_if_closed(session, case, dept)
        raise NotVisible(f"no recommendation or ownership of {dept.code} for this case")
    if target is not None and target.id == dept.id:
        raise OwnershipError("suggest a department other than your own")
    if target is not None and _active_row(session, case, target) is not None:
        raise OwnershipConflict("target_owns", f"{target.code} already holds this case")
    return member, dept, own


def _check_suggest(
    session: Session,
    actor_user: User,
    case: Case,
    target: Office | None,
    *,
    from_office_code: str | None = None,
) -> tuple[Member | None, Office | None, Recommendation | None]:
    """The suggest checks; without `target` only the caller's side (the screen asks for the target).
    `from_office_code` names the caller's department the suggestion comes from; without it the first
    membership holding the function that relates to the case (else the first holder)."""
    access.require(session, actor_user, Permission.CASES_SUGGEST_ELSEWHERE)
    if from_office_code:
        return _check_suggest_from(session, actor_user, case, target, from_office_code)
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
    if target is not None and own_dept is not None and own_dept.id == target.id:
        raise OwnershipError("suggest a department other than your own")
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
        for m in holders:
            _refuse_if_closed(session, case, m.department)
        raise NotVisible("no such case")
    if target is not None and _active_row(session, case, target) is not None:
        raise OwnershipConflict("target_owns", f"{target.code} already holds this case")
    return member, own_dept, own


def suggest(
    session: Session,
    actor: Actor,
    actor_user: User,
    case: Case,
    *,
    office_code: str,
    reason: str,
    from_office_code: str | None = None,
) -> SuggestResult:
    access.require(session, actor_user, Permission.CASES_SUGGEST_ELSEWHERE)
    reason = _reason(reason, required=True)
    target = _department_office(session, office_code)
    _lock(session, case)
    member, own_dept, own = _check_suggest(
        session, actor_user, case, target, from_office_code=from_office_code
    )
    if member is not None:
        actor = access.actor_as(actor, member)
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
            "target_recommendation_id": str(existing.id),  # design ownership-refinements, decision 15
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


def _check_allot(
    session: Session, actor_user: User, case: Case, *, office_code: str | None = None
) -> tuple[Member, Office, CaseOwnership]:
    access.require(session, actor_user, Permission.CASES_ALLOT)
    member, dept = acting_member(
        session,
        actor_user,
        _own_department(session, actor_user, office_code),
        Permission.CASES_ALLOT,
        relation=lambda d: _active_row(session, case, d) is not None,
    )
    row = _active_row(session, case, dept)
    if row is None:
        raise NotVisible("no such case")
    return member, dept, row


def allot(
    session: Session,
    actor: Actor,
    actor_user: User,
    case: Case,
    *,
    unit_code: Any = UNSET,
    officer_user_id: Any = UNSET,
    office_code: str | None = None,
) -> CaseOwnership:
    """Allots the actor's department's active row (primary or watcher) to a unit and/or an officer; `None`
    clears, UNSET leaves as is. `office_code` names which of the caller's departments acts."""
    access.require(session, actor_user, Permission.CASES_ALLOT)
    _lock(session, case)
    member, dept, row = _check_allot(session, actor_user, case, office_code=office_code)
    actor = access.actor_as(actor, member)
    return _apply_allot(session, actor, case, row, dept, unit_code=unit_code, officer_user_id=officer_user_id)


def _check_take_over(
    session: Session,
    actor_user: User,
    case: Case,
    *,
    expected_officer_user_id: uuid.UUID | None = None,
    office_code: str | None = None,
) -> tuple[Member, Office, CaseOwnership]:
    """`office_code` (design `portal-cases-followups`, decision 2) names the caller's department whose row is
    taken over; without it the first membership holding the function with an active row of its department."""
    access.require(session, actor_user, Permission.CASES_TAKE_OVER)
    taker: Member | None = None
    if office_code:
        named = _department_office(session, _own_department(session, actor_user, office_code))
        m = access.member_in_department(session, actor_user, named)
        assert m is not None
        if not m.holds(Permission.CASES_TAKE_OVER):
            raise access.Forbidden(f"cases.take_over is not enabled for you in {named.code}")
        if eligible_member(session, named, m) is not None and _active_row(session, case, named) is not None:
            taker = m
    else:
        for m in access.holders_in(session, actor_user, Permission.CASES_TAKE_OVER):
            if m.department is None or eligible_member(session, m.department, m) is None:
                continue
            if _active_row(session, case, m.department) is not None:
                taker = m
                break
    if taker is None or taker.department is None:
        raise NotVisible("no such case")
    dept = taker.department
    row = _active_row(session, case, dept)
    if row is None:
        raise NotVisible("no such case")
    if row.officer_user_id is None:
        raise OwnershipConflict("not_allotted", "the case is not allotted to an officer; allot it instead")
    if row.officer_user_id == taker.id:
        raise OwnershipConflict("already_holder", "you already hold this case")
    if expected_officer_user_id is not None and expected_officer_user_id != row.officer_user_id:
        raise OwnershipConflict("stale", "the case was allotted to someone else meanwhile")
    return taker, dept, row


def take_over(
    session: Session,
    actor: Actor,
    actor_user: User,
    case: Case,
    *,
    expected_officer_user_id: uuid.UUID | None = None,
    reason: str | None = None,
    office_code: str | None = None,
) -> TakeOverResult:
    """A user of the owning department takes over a case allotted to a colleague (decision 22). No approval;
    the unit follows the taker."""
    access.require(session, actor_user, Permission.CASES_TAKE_OVER)
    reason = _reason(reason)
    _lock(session, case)
    taker, dept, row = _check_take_over(
        session,
        actor_user,
        case,
        expected_officer_user_id=expected_officer_user_id,
        office_code=office_code,
    )
    actor = access.actor_as(actor, taker)
    actor_office = taker.office
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


def _check_stop_watching(
    session: Session, actor_user: User, case: Case, *, office_code: str | None = None
) -> tuple[Member, Office, CaseOwnership]:
    access.require(session, actor_user, Permission.CASES_RELEASE)
    member, dept = acting_member(
        session,
        actor_user,
        _own_department(session, actor_user, office_code),
        Permission.CASES_RELEASE,
        relation=lambda d: _active_row(session, case, d) is not None,
    )
    row = _active_row(session, case, dept)
    if row is None:
        raise NotVisible("no such case")
    if OwnershipRole(row.role) == OwnershipRole.PRIMARY:
        raise OwnershipConflict(
            "primary_cannot_release", "the primary owner cannot let go; transfer the case instead"
        )
    return member, dept, row


def stop_watching(
    session: Session,
    actor: Actor,
    actor_user: User,
    case: Case,
    *,
    reason: str,
    office_code: str | None = None,
) -> CaseOwnership:
    """Ends the department's watcher row. A primary row is never released (decision 10). `office_code` names
    which of the caller's departments stops watching."""
    access.require(session, actor_user, Permission.CASES_RELEASE)
    reason = _reason(reason, required=True)
    _lock(session, case)
    member, dept, row = _check_stop_watching(session, actor_user, case, office_code=office_code)
    actor = access.actor_as(actor, member)
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


def _check_request_transfer(
    session: Session, actor_user: User, case: Case, to_office_code: str | None
) -> tuple[Member, Office, Office | None]:
    """The transfer-request checks; without `to_office_code` only the caller's side. Design
    `portal-cases-followups`, decision 3: a caller with a membership in the primary owner's department acts for
    it; otherwise the department is resolved as for any case action (a watcher then gets `not_primary`)."""
    access.require(session, actor_user, Permission.CASES_TRANSFER_REQUEST)
    primary = next((r for r in _active_rows(session, case) if r.role == OwnershipRole.PRIMARY), None)
    primary_dept = _office(session, primary.office_id) if primary is not None else None
    mine = access.member_in_department(session, actor_user, primary_dept)
    if mine is not None and primary_dept is not None:
        if not mine.holds(Permission.CASES_TRANSFER_REQUEST):
            raise access.Forbidden(f"cases.transfer_request is not enabled for you in {primary_dept.code}")
        member, dept = mine, primary_dept
    else:
        member, dept = acting_member(
            session,
            actor_user,
            None,
            Permission.CASES_TRANSFER_REQUEST,
            relation=lambda d: _active_row(session, case, d) is not None,
        )
    target = None
    if to_office_code is not None:
        target = _department_office(session, to_office_code)
        if target.id == dept.id:
            raise OwnershipError("a transfer goes to another department")
    row = _active_row(session, case, dept)
    if row is None:
        raise NotVisible("no such case")
    if OwnershipRole(row.role) != OwnershipRole.PRIMARY:
        raise OwnershipConflict("not_primary", "only the primary owner may request a transfer")
    if _open_transfer(session, case) is not None:
        raise OwnershipConflict("transfer_open", "a transfer request is already open for this case")
    return member, dept, target


def _open_transfer(session: Session, case: Case) -> OwnershipTransfer | None:
    return session.scalar(
        select(OwnershipTransfer).where(
            OwnershipTransfer.case_id == case.id, OwnershipTransfer.status == TransferStatus.REQUESTED
        )
    )


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
    _lock(session, case)
    member, dept, target = _check_request_transfer(session, actor_user, case, to_office_code)
    assert target is not None
    actor = access.actor_as(actor, member)
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


def _check_decide_transfer(
    session: Session, actor_user: User, transfer: OwnershipTransfer
) -> tuple[Member, Office]:
    access.require(session, actor_user, Permission.CASES_TRANSFER_DECIDE)
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
    if transfer.to_office_id != dept.id:
        raise NotVisible("no such transfer")
    if TransferStatus(transfer.status) != TransferStatus.REQUESTED:
        raise OwnershipConflict("not_open", "the transfer is no longer open")
    return member, dept


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
    case = session.get(Case, transfer.case_id)
    _lock(session, case)
    session.refresh(transfer)
    member, dept = _check_decide_transfer(session, actor_user, transfer)
    actor = access.actor_as(actor, member)
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
    after = transfer_summary(session, transfer)
    if (
        accept
    ):  # design ownership-refinements, decision 1: the accepter's court refresh (closes no recommendation)
        after["court_refresh"] = _queue_court_refresh(session, case, actor_user)
    write_audit(
        session,
        actor,
        "transfer.accept" if accept else "transfer.decline",
        "ownership_transfer",
        transfer.id,
        before=before,
        after=after,
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


def _check_withdraw_transfer(
    session: Session, actor_user: User, transfer: OwnershipTransfer
) -> tuple[Member, Office]:
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
    if transfer.from_office_id != dept.id:
        raise NotVisible("no such transfer")
    if TransferStatus(transfer.status) != TransferStatus.REQUESTED:
        raise OwnershipConflict("not_open", "the transfer is no longer open")
    return member, dept


def withdraw_transfer(
    session: Session, actor: Actor, actor_user: User, transfer: OwnershipTransfer
) -> OwnershipTransfer:
    access.require(session, actor_user, Permission.CASES_TRANSFER_REQUEST)
    case = session.get(Case, transfer.case_id)
    _lock(session, case)
    session.refresh(transfer)
    member, _dept = _check_withdraw_transfer(session, actor_user, transfer)
    actor = access.actor_as(actor, member)
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
    holds `cases.claim`, or the caller holds `cases.view_all`, or a transfer to the caller's department is
    requested (the A5 `transfer_in` basis of `portal-ui-redesign`: one and the same active membership is in
    the receiving department, reads the whole department and holds `cases.view_scope`, exactly as
    `visibility.member_bases`). Other departments' recommendations only with `cases.view_all`. Otherwise
    NotVisible."""
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
    open_transfer = session.scalar(
        select(OwnershipTransfer).where(
            OwnershipTransfer.case_id == case.id, OwnershipTransfer.status == TransferStatus.REQUESTED
        )
    )
    # design portal-ui-redesign, A5: the receiving department's whole-department memberships read the case
    # while a transfer to it is requested (sight only, like a recommendation); design portal-ui-polish,
    # decision 8: the same membership must also hold `cases.view_scope`, as in `visibility.member_bases`
    transfer_in = open_transfer is not None and any(
        m.department is not None
        and m.department.id == open_transfer.to_office_id
        and whole_department(session, m)
        and m.holds(Permission.CASES_VIEW_SCOPE)
        for m in access.members(session, actor_user)
    )
    if not (view_all or mine or pool or transfer_in):
        raise NotVisible("no such case")
    if not view_all:
        recs = [r for r in recs if r.office_id in dept_ids]
    return {
        "primary": next((r for r in rows if r.role == OwnershipRole.PRIMARY), None),
        "watchers": [r for r in rows if r.role == OwnershipRole.WATCHER],
        "recommendations": recs,
        "open_transfer": open_transfer,
    }


def _passes(check: Callable[[], object]) -> bool:
    """True when the check passes or only asks which department acts (the action is possible once the
    department is named); False on any refusal."""
    try:
        check()
    except OfficeRequired:
        return True
    except (access.Forbidden, OwnershipError):
        return False
    return True


def _ok(check: Callable[[], object]) -> bool:
    """True only when the check passes outright (a department is named, so `office_required` cannot occur)."""
    try:
        check()
    except (access.Forbidden, OwnershipError):
        return False
    return True


def _super_admin_claim_departments(session: Session, case: Case) -> list[str] | None:
    """Design `portal-cases-followups`, decision 7: the departments the super admin may claim for. None ("any
    active department") while the case is in the pool; once it has had a primary owner, the active departments
    with an active recommendation that do not hold the case (possibly none)."""
    if not ever_owned(session, case):
        return None
    held = {r.office_id for r in _active_rows(session, case)}
    conds = [
        Recommendation.case_id == case.id,
        Recommendation.status == RecommendationStatus.RECOMMENDED,
        Office.is_active.is_(True),
    ]
    if held:
        conds.append(Recommendation.office_id.not_in(held))
    offices = session.scalars(
        select(Office).join(Recommendation, Recommendation.office_id == Office.id).where(*conds)
    ).all()
    return sorted({o.code for o in offices if is_department(o)})


def _transfer_from(session: Session, actor_user: User, case: Case) -> str | None:
    """The department a transfer request would come from, or None when the caller may not request one."""
    try:
        _member, dept, _target = _check_request_transfer(session, actor_user, case, None)
    except (access.Forbidden, OwnershipError):
        return None
    return dept.code


def available_actions(session: Session, actor_user: User, case: Case) -> dict[str, Any]:
    """Design `portal-cases`, decision 14c, and `portal-cases-followups`, decisions 1 and 7: which ownership
    actions the caller may take on the case now, by running each action's own checks without locking or
    writing. The `*_departments` lists name, in membership order, each of the caller's departments for which
    the action passes with that department named; `dismiss`, `allot`, `take_over` and `stop_watching` are true
    exactly when their list is not empty, `request_transfer` exactly when `transfer_from` is set. `suggest`
    may also pass without a department (the central operator). `claim_departments` lists the caller's
    departments that may claim (for the super admin: None while the case is in the pool, else the recommended
    departments that do not hold it). The API still decides on every call."""
    codes: list[str] = []
    for m in access.members(session, actor_user):
        code = m.department.code if m.department is not None else None
        if code is not None and code not in codes:
            codes.append(code)

    def listed(check: Callable[[str], object]) -> list[str]:
        return [c for c in codes if _ok(lambda c=c: check(c))]

    claim_departments: list[str] | None
    if access.super_admin_member(session, actor_user) is not None:
        claim_departments = _super_admin_claim_departments(session, case)
        can_claim = (
            access.has(session, actor_user, Permission.CASES_CLAIM)
            and case.merged_into_case_id is None
            and (claim_departments is None or bool(claim_departments))
        )
    else:
        claim_departments = listed(lambda c: _check_claim(session, actor_user, case, office_code=c))
        can_claim = bool(claim_departments)
    dismiss_d = listed(lambda c: _check_dismiss(session, actor_user, case, office_code=c))
    suggest_d = listed(lambda c: _check_suggest(session, actor_user, case, None, from_office_code=c))
    allot_d = listed(lambda c: _check_allot(session, actor_user, case, office_code=c))
    take_over_d = listed(lambda c: _check_take_over(session, actor_user, case, office_code=c))
    stop_d = listed(lambda c: _check_stop_watching(session, actor_user, case, office_code=c))
    transfer_from = _transfer_from(session, actor_user, case)
    open_t = _open_transfer(session, case)
    return {
        "claim": can_claim,
        "claim_departments": claim_departments,
        "dismiss": bool(dismiss_d),
        "dismiss_departments": dismiss_d,
        "suggest": _passes(lambda: _check_suggest(session, actor_user, case, None)),
        "suggest_departments": suggest_d,
        "allot": bool(allot_d),
        "allot_departments": allot_d,
        "take_over": bool(take_over_d),
        "take_over_departments": take_over_d,
        "stop_watching": bool(stop_d),
        "stop_watching_departments": stop_d,
        "request_transfer": transfer_from is not None,
        "transfer_from": transfer_from,
        "withdraw_transfer": open_t is not None
        and _passes(lambda: _check_withdraw_transfer(session, actor_user, open_t)),
        "decide_transfer": open_t is not None
        and _passes(lambda: _check_decide_transfer(session, actor_user, open_t)),
    }


def _active_row_of(office_id: Any, case_id: Any = None) -> ColumnElement[bool]:
    """An active ownership row (primary or watcher) of the office for the case (`case_id`, default `Case.id`;
    a nested subquery passes its own column so that it correlates to the right row)."""
    return exists().where(
        CaseOwnership.case_id == (Case.id if case_id is None else case_id),
        CaseOwnership.office_id == office_id,
        CaseOwnership.status == OwnershipStatus.ACTIVE,
    )


def _department_office_sql() -> ColumnElement[bool]:
    """Over `Office`: the SQL twin of `is_department` (a direct child of the State root of a department-tier
    kind) and active, as `_department_office` requires."""
    return and_(
        Office.is_active.is_(True),
        Office.path.op("~")("^[^/]+/[^/]+$"),
        Office.kind.in_(list(DEPARTMENT_TIER_KINDS)),
    )


def claimable_condition(session: Session, user: User | Member) -> ColumnElement[bool]:
    """Design `portal-causelist`, decision 7: over `Case`, the SQL twin of `available_actions(...)["claim"]`
    (which is unchanged and stays the per-case decision; `claim` itself decides on every call). Not merged and,
    for some department D where the caller's membership holds `cases.claim` (D an active department), D holds no
    active ownership row and either the case has never had a primary owner or D has an active recommendation.
    For the super admin: never owned, or an active recommendation to an active department that does not hold
    the case."""
    not_merged = Case.merged_into_case_id.is_(None)
    if access.super_admin_member(session, user) is not None:
        if not access.has(session, user, Permission.CASES_CLAIM):
            return false()
        recommended_free = exists(
            select(Recommendation.id)
            .join(Office, Office.id == Recommendation.office_id)
            .where(
                Recommendation.case_id == Case.id,
                Recommendation.status == RecommendationStatus.RECOMMENDED,
                _department_office_sql(),
                ~_active_row_of(Recommendation.office_id, Recommendation.case_id),
            )
        )
        return and_(not_merged, or_(never_owned(), recommended_free))
    depts: list[Office] = []
    for m in access.members(session, user):
        d = m.department
        if d is None or not d.is_active or not is_department(d) or any(x.id == d.id for x in depts):
            continue
        mine = access.member_in_department(session, user, d)
        if mine is not None and mine.holds(Permission.CASES_CLAIM):
            depts.append(d)
    if not depts:
        return false()
    per_department = [
        and_(
            ~_active_row_of(d.id),
            or_(
                never_owned(),
                exists().where(
                    Recommendation.case_id == Case.id,
                    Recommendation.office_id == d.id,
                    Recommendation.status == RecommendationStatus.RECOMMENDED,
                ),
            ),
        )
        for d in depts
    ]
    return and_(not_merged, or_(*per_department))


def shown_recommendations_condition(session: Session, user: User | Member) -> ColumnElement[bool]:
    """Over `Recommendation`: the active recommendations the caller is shown — to one of their departments (any
    membership), or to every department with `cases.view_all` (the rule of `case_ownership_view`)."""
    active = Recommendation.status == RecommendationStatus.RECOMMENDED
    if access.has(session, user, Permission.CASES_VIEW_ALL):
        return active
    ids = [d.id for d in access.departments(session, user)]
    if not ids:
        return false()
    return and_(active, Recommendation.office_id.in_(ids))


# ------------------------------------------------------------------------------------------------ backfill

BACKFILL_ACTOR = Actor.system("ownership-backfill")


def close_claimed_backfill(session: Session, *, apply: bool, now: datetime | None = None) -> dict[str, Any]:
    """Design `ownership-refinements`, decision 14 (`aslms close-claimed-recommendations`): the open recommendations
    of other departments on cases that already have an active primary owner. With `apply` each becomes
    `claimed_elsewhere` (`reason "claimed by <DEPT> (closed on <date>)"`) with a `recommendation_closed` event marked
    `backfill: true` (the alert scan raises nothing for those), and one summary audit row
    `recommendation.close_claimed_backfill` is written when anything was closed. A dry run writes nothing and
    returns the same counts `{closed, cases, by_department}`. Idempotent: a second run closes 0."""
    from aslms.services.reporting_common import today_ist

    now = now or _now()
    primary = aliased(CaseOwnership)
    rows = session.execute(
        select(Recommendation, primary)
        .join(
            primary,
            and_(
                primary.case_id == Recommendation.case_id,
                primary.status == OwnershipStatus.ACTIVE,
                primary.role == OwnershipRole.PRIMARY,
            ),
        )
        .where(
            Recommendation.status == RecommendationStatus.RECOMMENDED,
            Recommendation.office_id != primary.office_id,
            # a suggestion made after the claim stays open for the target to claim as a watcher (ownership-refinements
            # 12(a)); engine rows created after a claim before row 120 are still closed (design followups-oct, 15)
            ~and_(
                Recommendation.origin == RecommendationOrigin.SUGGESTION,
                Recommendation.created_at >= primary.claimed_at,
            ),
        )
        .order_by(Recommendation.case_id, Recommendation.created_at, Recommendation.id)
        .with_for_update(of=Recommendation)
    ).all()
    by_department: dict[str, int] = {}
    cases: set[uuid.UUID] = set()
    for rec, _row in rows:
        code = _code(session, rec.office_id) or "?"
        by_department[code] = by_department.get(code, 0) + 1
        cases.add(rec.case_id)
    counts = {"closed": len(rows), "cases": len(cases), "by_department": dict(sorted(by_department.items()))}
    if not apply or not rows:
        return counts
    day = today_ist(now).isoformat()
    for rec, row in rows:
        owner = _code(session, row.office_id)
        rec.status, rec.acted_at = RecommendationStatus.CLAIMED_ELSEWHERE, now
        rec.reason = f"claimed by {owner} (closed on {day})"
    session.flush()
    for rec, row in rows:
        case = session.get(Case, rec.case_id)
        _closed_event(
            session,
            case,
            rec,
            claimed_by=_code(session, row.office_id),
            ownership_id=row.id,
            actor_user_id=None,
            backfill=True,
        )
    write_audit(
        session, BACKFILL_ACTOR, "recommendation.close_claimed_backfill", "recommendation", None, after=counts
    )
    session.flush()
    return counts


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
