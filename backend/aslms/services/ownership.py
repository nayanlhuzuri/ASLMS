"""Recommend and claim (plan §4, §5.4). Scores and recommendations are written by the engine; ownership rows
only by an explicit department action (ground rule 2).

Lifecycle
  recommend   rescore() upserts case_office_scores for every department with a signal, and keeps one active
              `recommended` row per (case, department) at or above the possible threshold.
  claim       a department takes the case: primary owner if the case has none, otherwise watcher.
  dismiss     the department says it is not theirs; optionally suggests another department, which then
              receives a recommendation with origin `suggestion`.
  transfer    the primary owner asks another department to take over; that department accepts or declines.
  allot       the owning department allots the case to a unit (directorate/section) and/or an officer.
  release     a department stops owning or watching the case."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from aslms.core.config import get_settings
from aslms.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from aslms.core.time import now_utc
from aslms.domain.cases import Case, CaseAdvocate, CaseLink, CaseParty
from aslms.domain.causelists import CauseListEntry
from aslms.domain.events import EventType
from aslms.domain.org import Office, OfficeKind, User
from aslms.domain.ownership import (
    CaseOfficeScore,
    CaseOwnership,
    CounselCode,
    OfficeKeyword,
    OfficeNamePattern,
    OfficeWatchlist,
    OwnershipRole,
    OwnershipStatus,
    OwnershipTransfer,
    Recommendation,
    RecommendationOrigin,
    RecommendationStatus,
    ScoreBand,
    TransferStatus,
)
from aslms.domain.workflow import CustodyReason
from aslms.services import audit, events, workflow
from aslms.services.audit import Actor
from aslms.services.scoring import (
    ENGINE_VERSION,
    CaseFacts,
    CodeRule,
    KeywordRule,
    MatchConfig,
    OfficeRef,
    PatternRule,
    band_for,
    score_case,
)

DEPARTMENT_KINDS = {OfficeKind.DEPARTMENT}


# ------------------------------------------------------------------------------------------ config
def office_refs(session: Session) -> dict[uuid.UUID, OfficeRef]:
    offices = list(session.scalars(select(Office).where(Office.is_active.is_(True))))
    by_path = {o.path: o for o in offices}
    refs: dict[uuid.UUID, OfficeRef] = {}
    for o in offices:
        dept = by_path.get(o.path.split("/", 1)[0], o)
        refs[o.id] = OfficeRef(o.id, o.code, dept.id)
    return refs


def load_config(session: Session) -> MatchConfig:
    refs = office_refs(session)
    cfg = MatchConfig()
    for c in session.scalars(select(CounselCode).where(CounselCode.is_active.is_(True))):
        if c.office_id in refs:
            cfg.codes[c.code.strip().upper()] = CodeRule(
                c.code, refs[c.office_id], float(c.weight), c.is_generic_state
            )
    for p in session.scalars(select(OfficeNamePattern).where(OfficeNamePattern.is_active.is_(True))):
        if p.office_id in refs:
            cfg.patterns.append(PatternRule(p.pattern, p.kind.value, refs[p.office_id], float(p.weight)))
    for k in session.scalars(select(OfficeKeyword).where(OfficeKeyword.is_active.is_(True))):
        if k.office_id in refs:
            cfg.keywords.append(KeywordRule(k.keyword, refs[k.office_id], float(k.weight)))
    for w in session.scalars(select(OfficeWatchlist).where(OfficeWatchlist.is_active.is_(True))):
        if w.office_id in refs:
            cfg.watchlist.setdefault(w.cnr.upper(), []).append((refs[w.office_id], float(w.weight)))
    return cfg


def facts_for(session: Session, case: Case) -> CaseFacts:
    codes = set(
        session.scalars(
            select(CaseAdvocate.counsel_code).where(
                CaseAdvocate.case_id == case.id, CaseAdvocate.counsel_code.isnot(None)
            )
        )
    )
    for arr in session.scalars(select(CauseListEntry.counsel_codes).where(CauseListEntry.case_id == case.id)):
        codes.update(arr or [])
    texts = [case.petitioner_summary, case.respondent_summary]
    texts += list(session.scalars(select(CaseParty.name).where(CaseParty.case_id == case.id)))
    for pet, res in session.execute(
        select(CauseListEntry.petitioner_text, CauseListEntry.respondent_text)
        .where(CauseListEntry.case_id == case.id)
        .limit(5)
    ):
        texts += [pet, res]
    linked = (
        select(CaseLink.to_case_id)
        .where(CaseLink.from_case_id == case.id, CaseLink.to_case_id.isnot(None))
        .union(select(CaseLink.from_case_id).where(CaseLink.to_case_id == case.id))
    )
    owner_offices = session.scalars(
        select(CaseOwnership.office_id).where(
            CaseOwnership.case_id.in_(linked),
            CaseOwnership.status == OwnershipStatus.ACTIVE,
            CaseOwnership.role == OwnershipRole.PRIMARY,
        )
    ).all()
    refs = office_refs(session)
    return CaseFacts(
        cnr=case.cnr,
        counsel_codes=tuple(sorted(codes)),
        party_texts=tuple(t for t in dict.fromkeys(texts) if t),
        linked_owner_departments=tuple(refs[o].department_id for o in owner_offices if o in refs),
    )


# ------------------------------------------------------------------------------------------ recommend
def rescore(
    session: Session,
    case: Case,
    cfg: MatchConfig | None = None,
    *,
    origin: RecommendationOrigin = RecommendationOrigin.CAUSE_LIST,
) -> list[dict]:
    """Recomputes scores for a case and syncs recommendations. Idempotent."""
    s = get_settings()
    cfg = cfg or load_config(session)
    results = score_case(facts_for(session, case), cfg)
    now = now_utc()
    owners = set(
        session.scalars(
            select(CaseOwnership.office_id).where(
                CaseOwnership.case_id == case.id, CaseOwnership.status == OwnershipStatus.ACTIVE
            )
        )
    )
    out = []
    for r in results:
        signals = [sig.as_dict() for sig in r.signals]
        if r.suggested_unit_id:
            signals.append(
                {
                    "kind": "suggested_unit",
                    "value": str(r.suggested_unit_id),
                    "weight": 0,
                    "office": None,
                    "matched_text": None,
                }
            )
        session.execute(
            insert(CaseOfficeScore)
            .values(
                case_id=case.id,
                office_id=r.department_id,
                score=r.score,
                signals=signals,
                computed_at=now,
                engine_version=ENGINE_VERSION,
            )
            .on_conflict_do_update(
                index_elements=["case_id", "office_id"],
                set_={
                    "score": r.score,
                    "signals": signals,
                    "computed_at": now,
                    "engine_version": ENGINE_VERSION,
                },
            )
        )
        band = band_for(r.score, s.score_strong_threshold, s.score_possible_threshold)
        _sync_recommendation(
            session, case, r.department_id, r.score, band, origin, owned=r.department_id in owners
        )
        out.append({"office_id": r.department_id, "score": r.score, "band": band})
    return out


def _sync_recommendation(
    session: Session,
    case: Case,
    office_id: uuid.UUID,
    score: float,
    band: str | None,
    origin: RecommendationOrigin,
    *,
    owned: bool,
) -> None:
    active = session.scalar(
        select(Recommendation).where(
            Recommendation.case_id == case.id,
            Recommendation.office_id == office_id,
            Recommendation.status == RecommendationStatus.RECOMMENDED,
        )
    )
    if active:
        if band is None or owned:
            active.status = RecommendationStatus.EXPIRED if band is None else RecommendationStatus.CLAIMED
            active.acted_at = now_utc()
        else:
            active.score, active.band = score, ScoreBand(band)
        return
    if band is None or owned:
        return
    # never re-open a department's earlier decision on this case
    decided = session.scalar(
        select(func.count())
        .select_from(Recommendation)
        .where(
            Recommendation.case_id == case.id,
            Recommendation.office_id == office_id,
            Recommendation.status.in_(
                [
                    RecommendationStatus.DISMISSED,
                    RecommendationStatus.SUGGESTED_ELSEWHERE,
                    RecommendationStatus.CLAIMED,
                ]
            ),
        )
    )
    if decided:
        return
    rec = Recommendation(
        case_id=case.id, office_id=office_id, score=score, band=ScoreBand(band), origin=origin
    )
    session.add(rec)
    session.flush()
    events.emit(
        session,
        EventType.RECOMMENDATION_MADE,
        f"rec:{case.id}:{office_id}",
        case_id=case.id,
        payload={"office_id": str(office_id), "score": score, "band": band, "origin": origin.value},
    )


# ------------------------------------------------------------------------------------------ helpers
def department_of(session: Session, office_id: uuid.UUID) -> Office:
    office = session.get(Office, office_id)
    if office is None:
        raise NotFoundError("office not found")
    dept = session.scalar(select(Office).where(Office.path == office.path.split("/", 1)[0]))
    return dept or office


def _require_department(office: Office) -> None:
    if office.kind not in DEPARTMENT_KINDS:
        raise ValidationError("only a department can own or be recommended a case", office=office.code)


def active_ownership(session: Session, case_id: uuid.UUID) -> list[CaseOwnership]:
    return list(
        session.scalars(
            select(CaseOwnership)
            .where(CaseOwnership.case_id == case_id, CaseOwnership.status == OwnershipStatus.ACTIVE)
            .order_by(CaseOwnership.role, CaseOwnership.claimed_at)
        )
    )


def primary_owner(session: Session, case_id: uuid.UUID) -> CaseOwnership | None:
    return session.scalar(
        select(CaseOwnership).where(
            CaseOwnership.case_id == case_id,
            CaseOwnership.status == OwnershipStatus.ACTIVE,
            CaseOwnership.role == OwnershipRole.PRIMARY,
        )
    )


def _set_tracked(session: Session, case: Case) -> None:
    case.is_tracked = bool(active_ownership(session, case.id))


# ------------------------------------------------------------------------------------------ actions
@dataclass(frozen=True)
class ClaimResult:
    ownership: CaseOwnership
    role: OwnershipRole


def claim(
    session: Session, actor: Actor, case: Case, office_id: uuid.UUID, *, reason: str | None = None
) -> ClaimResult:
    dept = department_of(session, office_id)
    _require_department(dept)
    existing = session.scalar(
        select(CaseOwnership).where(
            CaseOwnership.case_id == case.id,
            CaseOwnership.office_id == dept.id,
            CaseOwnership.status == OwnershipStatus.ACTIVE,
        )
    )
    if existing:
        raise ConflictError("the department already owns or watches this case", role=existing.role.value)
    role = OwnershipRole.WATCHER if primary_owner(session, case.id) else OwnershipRole.PRIMARY
    own = CaseOwnership(
        case_id=case.id, office_id=dept.id, role=role, claimed_at=now_utc(), **actor.snapshot()
    )
    session.add(own)
    for rec in session.scalars(
        select(Recommendation).where(
            Recommendation.case_id == case.id,
            Recommendation.office_id == dept.id,
            Recommendation.status == RecommendationStatus.RECOMMENDED,
        )
    ):
        rec.status, rec.acted_at, rec.reason = RecommendationStatus.CLAIMED, now_utc(), reason
        for k, v in actor.snapshot().items():
            setattr(rec, k, v)
    session.flush()
    _set_tracked(session, case)
    if role == OwnershipRole.PRIMARY:
        workflow.move(
            session,
            actor,
            case,
            office_id=dept.id,
            user_id=None,
            reason=CustodyReason.CLAIM,
            pending_action="examine the case and decide the response",
        )
    etype = EventType.CASE_CLAIMED if role == OwnershipRole.PRIMARY else EventType.WATCHER_ADDED
    events.emit(
        session,
        etype,
        f"claim:{case.id}:{dept.id}:{own.id}",
        case_id=case.id,
        actor_user_id=actor.user_id,
        payload={"office_id": str(dept.id), "office": dept.code, "role": role.value},
    )
    audit.record(
        session,
        actor,
        "case.claim",
        "case_ownership",
        own.id,
        case_id=case.id,
        after={"office": dept.code, "role": role.value, "reason": reason},
    )
    return ClaimResult(own, role)


def dismiss(
    session: Session,
    actor: Actor,
    case: Case,
    office_id: uuid.UUID,
    *,
    reason: str,
    suggest_office_id: uuid.UUID | None = None,
) -> Recommendation:
    if not reason or not reason.strip():
        raise ValidationError("a reason is required to dismiss a recommendation")
    dept = department_of(session, office_id)
    rec = session.scalar(
        select(Recommendation).where(
            Recommendation.case_id == case.id,
            Recommendation.office_id == dept.id,
            Recommendation.status == RecommendationStatus.RECOMMENDED,
        )
    )
    if rec is None:
        # dismissing from the unclaimed pool: record the decision so the engine does not recommend it again
        rec = Recommendation(
            case_id=case.id,
            office_id=dept.id,
            score=0,
            band=ScoreBand.MEDIUM,
            origin=RecommendationOrigin.SEARCH,
        )
        session.add(rec)
    rec.status = (
        RecommendationStatus.SUGGESTED_ELSEWHERE if suggest_office_id else RecommendationStatus.DISMISSED
    )
    rec.reason, rec.acted_at = reason.strip(), now_utc()
    for k, v in actor.snapshot().items():
        setattr(rec, k, v)
    suggested = None
    if suggest_office_id:
        suggested = department_of(session, suggest_office_id)
        _require_department(suggested)
        if suggested.id == dept.id:
            raise ValidationError("cannot suggest the same department")
        rec.suggested_office_id = suggested.id
        already = session.scalar(
            select(Recommendation).where(
                Recommendation.case_id == case.id,
                Recommendation.office_id == suggested.id,
                Recommendation.status == RecommendationStatus.RECOMMENDED,
            )
        )
        if already is None and not any(
            o.office_id == suggested.id for o in active_ownership(session, case.id)
        ):
            score = session.scalar(
                select(CaseOfficeScore.score).where(
                    CaseOfficeScore.case_id == case.id, CaseOfficeScore.office_id == suggested.id
                )
            )
            s = max(float(score or 0), get_settings().score_possible_threshold)
            session.add(
                Recommendation(
                    case_id=case.id,
                    office_id=suggested.id,
                    score=s,
                    band=ScoreBand.HIGH if s >= get_settings().score_strong_threshold else ScoreBand.MEDIUM,
                    origin=RecommendationOrigin.SUGGESTION,
                    reason=f"suggested by {dept.code}: {reason.strip()}",
                )
            )
    session.flush()
    events.emit(
        session,
        EventType.RECOMMENDATION_DISMISSED,
        f"dismiss:{case.id}:{dept.id}:{rec.id}",
        case_id=case.id,
        actor_user_id=actor.user_id,
        payload={"office": dept.code, "reason": reason, "suggested": suggested.code if suggested else None},
    )
    audit.record(
        session,
        actor,
        "recommendation.dismiss",
        "recommendation",
        rec.id,
        case_id=case.id,
        after={"office": dept.code, "reason": reason, "suggested": suggested.code if suggested else None},
    )
    return rec


def request_transfer(
    session: Session,
    actor: Actor,
    case: Case,
    from_office_id: uuid.UUID,
    to_office_id: uuid.UUID,
    *,
    reason: str,
) -> OwnershipTransfer:
    src, dst = department_of(session, from_office_id), department_of(session, to_office_id)
    _require_department(dst)
    own = primary_owner(session, case.id)
    if own is None or own.office_id != src.id:
        raise ForbiddenError("only the primary owner can transfer a case")
    if src.id == dst.id:
        raise ValidationError("cannot transfer to the same department")
    open_ = session.scalar(
        select(OwnershipTransfer).where(
            OwnershipTransfer.case_id == case.id, OwnershipTransfer.status == TransferStatus.REQUESTED
        )
    )
    if open_:
        raise ConflictError("a transfer is already pending for this case")
    t = OwnershipTransfer(
        case_id=case.id, from_office_id=src.id, to_office_id=dst.id, reason=reason, **actor.snapshot()
    )
    session.add(t)
    session.flush()
    events.emit(
        session,
        EventType.OWNERSHIP_TRANSFER_REQUESTED,
        f"transfer_req:{t.id}",
        case_id=case.id,
        actor_user_id=actor.user_id,
        payload={"from": src.code, "to": dst.code, "reason": reason},
    )
    audit.record(
        session,
        actor,
        "transfer.request",
        "ownership_transfer",
        t.id,
        case_id=case.id,
        after={"from": src.code, "to": dst.code},
    )
    return t


def decide_transfer(
    session: Session,
    actor: Actor,
    transfer: OwnershipTransfer,
    acting_office_id: uuid.UUID,
    *,
    accept: bool,
    reason: str | None = None,
) -> OwnershipTransfer:
    if transfer.status != TransferStatus.REQUESTED:
        raise ConflictError("the transfer has already been decided", status=transfer.status.value)
    dept = department_of(session, acting_office_id)
    if dept.id != transfer.to_office_id:
        raise ForbiddenError("only the receiving department can decide a transfer")
    case = session.get(Case, transfer.case_id)
    transfer.status = TransferStatus.ACCEPTED if accept else TransferStatus.DECLINED
    transfer.decided_by_user_id, transfer.decided_at = actor.user_id, now_utc()
    if reason:
        transfer.reason = (
            f"{transfer.reason or ''}\n[{'accepted' if accept else 'declined'}] {reason}".strip()
        )
    if accept:
        old = primary_owner(session, case.id)
        if old:
            old.status, old.released_at = OwnershipStatus.TRANSFERRED, now_utc()
            session.flush()
        mine = session.scalar(
            select(CaseOwnership).where(
                CaseOwnership.case_id == case.id,
                CaseOwnership.office_id == dept.id,
                CaseOwnership.status == OwnershipStatus.ACTIVE,
            )
        )
        if mine:
            mine.role = OwnershipRole.PRIMARY
        else:
            session.add(
                CaseOwnership(
                    case_id=case.id,
                    office_id=dept.id,
                    role=OwnershipRole.PRIMARY,
                    claimed_at=now_utc(),
                    **actor.snapshot(),
                )
            )
        session.flush()
        workflow.move(
            session,
            actor,
            case,
            office_id=dept.id,
            reason=CustodyReason.TRANSFER,
            pending_action="case transferred to the department; examine it",
        )
        events.emit(
            session,
            EventType.OWNERSHIP_TRANSFERRED,
            f"transfer:{transfer.id}",
            case_id=case.id,
            actor_user_id=actor.user_id,
            payload={"to_office_id": str(dept.id), "to": dept.code},
        )
    audit.record(
        session,
        actor,
        "transfer.accept" if accept else "transfer.decline",
        "ownership_transfer",
        transfer.id,
        case_id=case.id,
        after={"reason": reason},
    )
    _set_tracked(session, case)
    return transfer


def withdraw_transfer(
    session: Session, actor: Actor, transfer: OwnershipTransfer, acting_office_id: uuid.UUID
) -> None:
    dept = department_of(session, acting_office_id)
    if dept.id != transfer.from_office_id or transfer.status != TransferStatus.REQUESTED:
        raise ForbiddenError("only the requesting department can withdraw a pending transfer")
    transfer.status, transfer.decided_at, transfer.decided_by_user_id = (
        TransferStatus.WITHDRAWN,
        now_utc(),
        actor.user_id,
    )
    audit.record(
        session, actor, "transfer.withdraw", "ownership_transfer", transfer.id, case_id=transfer.case_id
    )


def allot(
    session: Session,
    actor: Actor,
    case: Case,
    acting_office_id: uuid.UUID,
    *,
    unit_office_id: uuid.UUID | None,
    officer_user_id: uuid.UUID | None,
) -> CaseOwnership:
    dept = department_of(session, acting_office_id)
    own = session.scalar(
        select(CaseOwnership).where(
            CaseOwnership.case_id == case.id,
            CaseOwnership.office_id == dept.id,
            CaseOwnership.status == OwnershipStatus.ACTIVE,
        )
    )
    if own is None:
        raise ForbiddenError("the department does not own this case")
    if unit_office_id:
        unit = session.get(Office, unit_office_id)
        if unit is None or not (unit.path == dept.path or unit.path.startswith(dept.path + "/")):
            raise ValidationError("the unit must belong to the owning department")
    if officer_user_id:
        officer = session.get(User, officer_user_id)
        if officer is None or not officer.is_active:
            raise ValidationError("officer not found")
        off_office = session.get(Office, officer.office_id)
        if not (off_office.path == dept.path or off_office.path.startswith(dept.path + "/")):
            raise ValidationError("the officer must belong to the owning department")
    before = {"unit": str(own.unit_office_id or ""), "officer": str(own.officer_user_id or "")}
    own.unit_office_id, own.officer_user_id = unit_office_id, officer_user_id
    if own.role == OwnershipRole.PRIMARY and (unit_office_id or officer_user_id):
        holder_office = unit_office_id
        if holder_office is None:
            holder_office = session.get(User, officer_user_id).office_id
        workflow.move(
            session,
            actor,
            case,
            office_id=holder_office,
            user_id=officer_user_id,
            reason=CustodyReason.ALLOT,
            pending_action="prepare the department's response",
        )
    audit.record(
        session,
        actor,
        "case.allot",
        "case_ownership",
        own.id,
        case_id=case.id,
        before=before,
        after={"unit": str(unit_office_id or ""), "officer": str(officer_user_id or "")},
    )
    return own


def release(session: Session, actor: Actor, case: Case, acting_office_id: uuid.UUID, *, reason: str) -> None:
    dept = department_of(session, acting_office_id)
    own = session.scalar(
        select(CaseOwnership).where(
            CaseOwnership.case_id == case.id,
            CaseOwnership.office_id == dept.id,
            CaseOwnership.status == OwnershipStatus.ACTIVE,
        )
    )
    if own is None:
        raise NotFoundError("the department does not own or watch this case")
    was_primary = own.role == OwnershipRole.PRIMARY
    own.status, own.released_at = OwnershipStatus.RELEASED, now_utc()
    session.flush()
    if was_primary:
        # the longest-standing watcher becomes primary; nobody else is assigned automatically
        watcher = session.scalar(
            select(CaseOwnership)
            .where(CaseOwnership.case_id == case.id, CaseOwnership.status == OwnershipStatus.ACTIVE)
            .order_by(CaseOwnership.claimed_at)
            .limit(1)
        )
        if watcher:
            watcher.role = OwnershipRole.PRIMARY
            workflow.move(
                session,
                actor,
                case,
                office_id=watcher.office_id,
                reason=CustodyReason.RELEASE,
                pending_action="case released by the previous owner; examine it",
            )
    events.emit(
        session,
        EventType.OWNERSHIP_RELEASED,
        f"release:{own.id}",
        case_id=case.id,
        actor_user_id=actor.user_id,
        payload={"office": dept.code, "reason": reason},
    )
    audit.record(
        session, actor, "case.release", "case_ownership", own.id, case_id=case.id, after={"reason": reason}
    )
    _set_tracked(session, case)


# ------------------------------------------------------------------------------------------ inbox queries
def recommended_query(office_id: uuid.UUID):
    return (
        select(Recommendation, Case)
        .join(Case, Case.id == Recommendation.case_id)
        .where(
            Recommendation.office_id == office_id, Recommendation.status == RecommendationStatus.RECOMMENDED
        )
        .order_by(
            Recommendation.band.asc(), Recommendation.score.desc(), Case.next_hearing_date.asc().nulls_last()
        )
    )


def claimed_query(office_path: str):
    return (
        select(CaseOwnership, Case)
        .join(Case, Case.id == CaseOwnership.case_id)
        .join(Office, Office.id == CaseOwnership.office_id)
        .where(
            CaseOwnership.status == OwnershipStatus.ACTIVE,
            or_(Office.path == office_path, Office.path.like(office_path + "/%")),
        )
        .order_by(Case.next_hearing_date.asc().nulls_last())
    )


def unclaimed_query():
    """Cases nobody owns. Any department can search and claim these; the central operator follows them up."""
    owned = exists().where(
        and_(CaseOwnership.case_id == Case.id, CaseOwnership.status == OwnershipStatus.ACTIVE)
    )
    return (
        select(Case)
        .where(~owned, Case.merged_into_case_id.is_(None), Case.status != "disposed")
        .order_by(Case.next_hearing_date.asc().nulls_last(), Case.created_at.desc())
    )


def transfers_query(office_id: uuid.UUID):
    return (
        select(OwnershipTransfer, Case)
        .join(Case, Case.id == OwnershipTransfer.case_id)
        .where(
            or_(OwnershipTransfer.to_office_id == office_id, OwnershipTransfer.from_office_id == office_id)
        )
        .order_by(OwnershipTransfer.created_at.desc())
    )
