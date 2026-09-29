"""Custody and workflow (plan §5.7; decisions log). Custody is derived, never keyed in:
  claim / allot / transfer (ownership service)  → the owning office, unit or officer holds the case
  request sent                                  → the office asked to act holds it, with the due date
  request answered / withdrawn                  → back to the requesting office
  hand-over                                     → an explicit move, always with a hand-over note
Every move appends a custody_history leg (append-only) and a `custody_moved` event (tracking-card visible:
every signed-in user can see where a case is and since when)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from aslms.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from aslms.core.time import now_utc
from aslms.domain.cases import Case
from aslms.domain.events import EventType
from aslms.domain.org import Office, User
from aslms.domain.workflow import (
    STAGE_ORDER,
    CaseStage,
    Custody,
    CustodyHistory,
    CustodyReason,
    Request,
    RequestKind,
    RequestMessage,
    RequestStatus,
    Stage,
)
from aslms.services import audit, events
from aslms.services.audit import Actor
from aslms.services.refno import RecordType, allocate_ref_no
from aslms.services.scope import Principal

MAIN_TRACK = STAGE_ORDER[: STAGE_ORDER.index(Stage.COMPLIED) + 1]


# ------------------------------------------------------------------------------------------ custody
def current(session: Session, case_id: uuid.UUID) -> Custody | None:
    return session.get(Custody, case_id)


def move(
    session: Session,
    actor: Actor,
    case: Case,
    *,
    office_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    reason: CustodyReason,
    pending_action: str | None = None,
    due_date: date | None = None,
    request_id: uuid.UUID | None = None,
) -> CustodyHistory:
    office = session.get(Office, office_id)
    if office is None:
        raise NotFoundError("office not found")
    user = session.get(User, user_id) if user_id else None
    now = now_utc()
    # serialise moves of one case so seq_no stays unique
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(str(case.id)))))
    seq = (
        session.scalar(select(func.max(CustodyHistory.seq_no)).where(CustodyHistory.case_id == case.id)) or 0
    ) + 1
    leg = CustodyHistory(
        case_id=case.id,
        seq_no=seq,
        holder_office_id=office.id,
        holder_office_code=office.code,
        holder_user_id=user.id if user else None,
        holder_user_name=user.full_name if user else None,
        reason=reason,
        pending_action=pending_action,
        due_date=due_date,
        request_id=request_id,
        started_at=now,
        **actor.snapshot(),
    )
    session.add(leg)
    session.flush()
    cur = session.get(Custody, case.id)
    if cur is None:
        cur = Custody(case_id=case.id, holder_office_id=office.id, since=now)
        session.add(cur)
    cur.holder_office_id, cur.holder_user_id = office.id, user.id if user else None
    cur.pending_action, cur.due_date, cur.request_id, cur.since, cur.current_leg_id = (
        pending_action,
        due_date,
        request_id,
        now,
        leg.id,
    )
    events.emit(
        session,
        EventType.CUSTODY_MOVED,
        f"custody:{case.id}:{seq}",
        case_id=case.id,
        actor_user_id=actor.user_id,
        payload={
            "to_office": office.code,
            "to_user": user.full_name if user else None,
            "reason": reason.value,
            "pending_action": pending_action,
            "due_date": due_date.isoformat() if due_date else None,
        },
    )
    return leg


def history(session: Session, case_id: uuid.UUID) -> list[CustodyHistory]:
    return list(
        session.scalars(
            select(CustodyHistory).where(CustodyHistory.case_id == case_id).order_by(CustodyHistory.seq_no)
        )
    )


def _office_under(session: Session, office_id: uuid.UUID, root_path: str) -> bool:
    o = session.get(Office, office_id)
    return bool(o and (o.path == root_path or o.path.startswith(root_path + "/")))


def holds_or_owns(session: Session, p: Principal, case: Case) -> bool:
    """May this principal move the case (send a request, hand over)? The current holder, or the owning
    department's admin/head/officer; the State tier never writes."""
    if p.read_only:
        return False
    cur = current(session, case.id)
    if cur and (
        cur.holder_user_id == p.user_id or _office_under(session, cur.holder_office_id, p.office_path)
    ):
        return True
    from aslms.services.ownership import active_ownership

    for own in active_ownership(session, case.id):
        dept = session.get(Office, own.office_id)
        if (
            dept
            and (p.department_path == dept.path)
            and p.role.value in ("dept_admin", "dept_head", "dept_officer")
        ):
            return True
    return p.role.value == "central_operator"


# ------------------------------------------------------------------------------------------ requests
@dataclass(frozen=True)
class RequestIn:
    kind: RequestKind
    to_office_id: uuid.UUID
    subject: str
    body: str | None = None
    due_date: date | None = None
    to_user_id: uuid.UUID | None = None


def send_request(session: Session, actor: Actor, p: Principal, case: Case, req: RequestIn) -> Request:
    if not holds_or_owns(session, p, case):
        raise ForbiddenError("only the office holding the case (or its owner) can send a request")
    if not req.subject.strip():
        raise ValidationError("a subject is required")
    to = session.get(Office, req.to_office_id)
    if to is None or not to.is_active:
        raise NotFoundError("the receiving office was not found")
    if to.id == p.office_id:
        raise ValidationError("a request must go to another office")
    if req.due_date and req.due_date < now_utc().date():
        raise ValidationError("the due date is in the past")
    if req.to_user_id:
        u = session.get(User, req.to_user_id)
        if u is None or not _office_under(session, u.office_id, to.path):
            raise ValidationError("the addressee must belong to the receiving office")
    r = Request(
        ref_no=allocate_ref_no(session, p.office_code, RecordType.REQ),
        case_id=case.id,
        kind=req.kind,
        from_office_id=p.office_id,
        to_office_id=to.id,
        to_user_id=req.to_user_id,
        subject=req.subject.strip()[:300],
        body=req.body,
        due_date=req.due_date,
        **actor.snapshot(),
    )
    session.add(r)
    session.flush()
    move(
        session,
        actor,
        case,
        office_id=to.id,
        user_id=req.to_user_id,
        reason=CustodyReason.REQUEST_SENT,
        pending_action=f"{req.kind.value}: {r.subject}"[:300],
        due_date=req.due_date,
        request_id=r.id,
    )
    events.emit(
        session,
        EventType.REQUEST_SENT,
        f"request:{r.id}",
        case_id=case.id,
        actor_user_id=actor.user_id,
        payload={
            "request_id": str(r.id),
            "kind": req.kind.value,
            "to": to.code,
            "subject": r.subject,
            "due_date": req.due_date.isoformat() if req.due_date else None,
        },
    )
    audit.record(
        session,
        actor,
        "request.send",
        "request",
        r.id,
        case_id=case.id,
        after={"kind": req.kind.value, "to": to.code, "due": str(req.due_date or "")},
    )
    return r


def _get_request(session: Session, request_id: uuid.UUID) -> Request:
    r = session.get(Request, request_id)
    if r is None:
        raise NotFoundError("request not found")
    return r


def answer_request(session: Session, actor: Actor, p: Principal, request_id: uuid.UUID, body: str) -> Request:
    r = _get_request(session, request_id)
    if r.status != RequestStatus.OPEN:
        raise ConflictError("the request is no longer open", status=r.status.value)
    to = session.get(Office, r.to_office_id)
    if p.read_only or not _office_under(session, p.office_id, to.path):
        raise ForbiddenError("only the office the request was sent to can answer it")
    if not body.strip():
        raise ValidationError("the answer cannot be empty")
    r.status, r.answered_at, r.answered_by_user_id = RequestStatus.ANSWERED, now_utc(), actor.user_id
    session.add(RequestMessage(request_id=r.id, body=body.strip(), is_answer=True, **actor.snapshot()))
    case = session.get(Case, r.case_id)
    move(
        session,
        actor,
        case,
        office_id=r.from_office_id,
        user_id=r.actor_user_id,
        reason=CustodyReason.REQUEST_ANSWERED,
        pending_action=f"examine the {r.kind.value} received from {to.code}"[:300],
    )
    events.emit(
        session,
        EventType.REQUEST_ANSWERED,
        f"request_answered:{r.id}",
        case_id=case.id,
        actor_user_id=actor.user_id,
        payload={"request_id": str(r.id), "from": to.code, "subject": r.subject},
    )
    audit.record(session, actor, "request.answer", "request", r.id, case_id=case.id)
    return r


def withdraw_request(
    session: Session, actor: Actor, p: Principal, request_id: uuid.UUID, reason: str | None = None
) -> Request:
    r = _get_request(session, request_id)
    if r.status != RequestStatus.OPEN:
        raise ConflictError("the request is no longer open")
    frm = session.get(Office, r.from_office_id)
    if p.read_only or not _office_under(session, p.office_id, frm.path):
        raise ForbiddenError("only the requesting office can withdraw a request")
    r.status, r.withdrawn_at = RequestStatus.WITHDRAWN, now_utc()
    if reason:
        session.add(RequestMessage(request_id=r.id, body=f"Withdrawn: {reason}", **actor.snapshot()))
    case = session.get(Case, r.case_id)
    cur = current(session, case.id)
    if cur and cur.request_id == r.id:
        move(
            session,
            actor,
            case,
            office_id=r.from_office_id,
            user_id=r.actor_user_id,
            reason=CustodyReason.REQUEST_WITHDRAWN,
            pending_action="request withdrawn",
        )
    events.emit(
        session,
        EventType.REQUEST_WITHDRAWN,
        f"request_withdrawn:{r.id}",
        case_id=case.id,
        actor_user_id=actor.user_id,
        payload={"request_id": str(r.id)},
    )
    audit.record(
        session, actor, "request.withdraw", "request", r.id, case_id=case.id, after={"reason": reason}
    )
    return r


def add_message(
    session: Session, actor: Actor, p: Principal, request_id: uuid.UUID, body: str
) -> RequestMessage:
    r = _get_request(session, request_id)
    frm, to = session.get(Office, r.from_office_id), session.get(Office, r.to_office_id)
    if p.read_only or not (
        _office_under(session, p.office_id, frm.path) or _office_under(session, p.office_id, to.path)
    ):
        raise ForbiddenError("only the two offices of a request can write in it")
    m = RequestMessage(request_id=r.id, body=body.strip(), **actor.snapshot())
    session.add(m)
    session.flush()
    return m


def requests_for_office(
    session: Session,
    office_path: str,
    *,
    incoming: bool = True,
    status: RequestStatus | None = RequestStatus.OPEN,
):
    col = Request.to_office_id if incoming else Request.from_office_id
    q = (
        select(Request, Case)
        .join(Case, Case.id == Request.case_id)
        .where(
            col.in_(
                select(Office.id).where(or_(Office.path == office_path, Office.path.like(office_path + "/%")))
            )
        )
    )
    if status:
        q = q.where(Request.status == status)
    return q.order_by(Request.due_date.asc().nulls_last(), Request.created_at.desc())


# ------------------------------------------------------------------------------------------ stages
@dataclass(frozen=True)
class StageResult:
    stage: CaseStage
    skipped: list[str]


def current_stage(session: Session, case_id: uuid.UUID) -> CaseStage | None:
    return session.scalar(
        select(CaseStage).where(CaseStage.case_id == case_id).order_by(CaseStage.created_at.desc()).limit(1)
    )


def set_stage(
    session: Session,
    actor: Actor,
    p: Principal,
    case: Case,
    stage: Stage,
    *,
    note: str | None = None,
    response_mode: str | None = None,
) -> StageResult:
    """Guided, not enforced: any stage may be set. Stages skipped on the main track are returned so the UI can
    flag the gap."""
    if not holds_or_owns(session, p, case):
        raise ForbiddenError("only the owning department or the office holding the case can set its stage")
    if response_mode and response_mode not in ("dept_led", "directorate_led"):
        raise ValidationError("response mode is dept_led or directorate_led")
    prev = current_stage(session, case.id)
    row = CaseStage(
        case_id=case.id,
        office_id=p.department_id or p.office_id,
        stage=stage,
        response_mode=response_mode,
        note=note,
        **actor.snapshot(),
    )
    session.add(row)
    session.flush()
    skipped: list[str] = []
    if prev and prev.stage in MAIN_TRACK and stage in MAIN_TRACK:
        a, b = MAIN_TRACK.index(prev.stage), MAIN_TRACK.index(stage)
        skipped = [s.value for s in MAIN_TRACK[a + 1 : b]] if b > a + 1 else []
    events.emit(
        session,
        EventType.STAGE_CHANGED,
        f"stage:{row.id}",
        case_id=case.id,
        actor_user_id=actor.user_id,
        payload={"from": prev.stage.value if prev else None, "to": stage.value, "skipped": skipped},
    )
    audit.record(
        session,
        actor,
        "stage.set",
        "case_stage",
        row.id,
        case_id=case.id,
        after={"stage": stage.value, "skipped": skipped},
    )
    return StageResult(row, skipped)


# ------------------------------------------------------------------------------------------ hand-over
def hand_over(
    session: Session,
    actor: Actor,
    p: Principal,
    case: Case,
    *,
    to_office_id: uuid.UUID,
    to_user_id: uuid.UUID | None,
    note: str,
    pending_action: str | None = None,
    due_date: date | None = None,
):
    """A hand-over note and the custody move, in one step (decisions log)."""
    from aslms.domain.workflow import NoteKind
    from aslms.services import notes

    if not holds_or_owns(session, p, case):
        raise ForbiddenError("only the office holding the case can hand it over")
    if not note.strip():
        raise ValidationError("a hand-over needs a note")
    to = session.get(Office, to_office_id)
    if to is None:
        raise NotFoundError("office not found")
    n = notes.add_note(
        session,
        actor,
        p,
        case,
        notes.NoteIn(kind=NoteKind.HANDOVER, body=f"Handed over to {to.name}. {note.strip()}"),
    )
    leg = move(
        session,
        actor,
        case,
        office_id=to.id,
        user_id=to_user_id,
        reason=CustodyReason.HANDOVER,
        pending_action=pending_action,
        due_date=due_date,
    )
    audit.record(
        session,
        actor,
        "custody.handover",
        "custody_history",
        leg.id,
        case_id=case.id,
        after={"to": to.code, "note_id": str(n.id)},
    )
    return n, leg
