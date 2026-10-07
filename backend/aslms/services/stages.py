"""Case stages (design `custody-workflow`, decision 19): one track of the 17 stages per case; the current stage is
the latest `case_stages` row; any stage may be set (guided, not enforced) by a `stages.set` holder with a working
basis on a claimed case — the personal holder from another department included (decision 9). The read returns
the history and the gaps (main-phase stages ordered before a main current stage that were never recorded). No
stage is set by the system. Writes take the case row lock, emit `stage_set` and audit `stage.set` (the stage
note's length and hash, never its text)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.domain.cases import Case
from aslms.domain.org import Office, User
from aslms.domain.reference import EventType, Permission, RefCaseStage, Stage
from aslms.domain.workflow import CaseStage, ResponseMode
from aslms.services import access
from aslms.services.access import Member
from aslms.services.audit import Actor, snapshot, write_audit
from aslms.services.cases import emit_event
from aslms.services.visibility import require_visible
from aslms.services.workflow_common import (
    RESPONSE_MODE_LABELS,
    STAGE_NOTE_MAX,
    acting_member,
    bad,
    clean_text,
    conflict,
    digest,
    lock_case,
    require_function,
    require_owned,
    require_visible_basis,
    value,
)

MAIN_PHASE = "main"


@dataclass(frozen=True)
class StageInfo:
    code: str
    label: str
    phase: str
    sort_order: int


def compute_gaps(catalogue_: Iterable[StageInfo], recorded: set[str], current_: str | None) -> list[str]:
    """Main-phase stages ordered (by `sort_order`) before the current stage and never recorded, when the
    current stage is a main one; nothing otherwise."""
    items = list(catalogue_)
    by_code = {s.code: s for s in items}
    cur = by_code.get(current_) if current_ else None
    if cur is None or cur.phase != MAIN_PHASE:
        return []
    return [
        s.code
        for s in sorted(items, key=lambda s: (s.sort_order, s.code))
        if s.phase == MAIN_PHASE and s.sort_order < cur.sort_order and s.code not in recorded
    ]


def catalogue(session: Session, *, active_only: bool = True) -> list[StageInfo]:
    stmt = select(RefCaseStage).order_by(RefCaseStage.sort_order, RefCaseStage.code)
    if active_only:
        stmt = stmt.where(RefCaseStage.is_active.is_(True))
    return [StageInfo(r.code, r.label, r.phase, r.sort_order) for r in session.scalars(stmt).all()]


def check_stage(session: Session, raw: str | None) -> RefCaseStage:
    try:
        member = Stage(str(raw or "").strip().lower())
    except ValueError as exc:
        raise bad(f"unknown stage {raw!r}") from exc
    row = session.get(RefCaseStage, member.value)
    if row is None or not row.is_active:
        raise bad(f"stage {member.value} cannot be set")
    return row


def check_mode(raw: str | None) -> ResponseMode | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return ResponseMode(str(raw).strip().lower())
    except ValueError as exc:
        raise bad("response_mode must be department, counsel or none") from exc


def current(session: Session, case: Case) -> CaseStage | None:
    return session.scalar(
        select(CaseStage)
        .where(CaseStage.case_id == case.id)
        .order_by(CaseStage.created_at.desc(), CaseStage.id.desc())
        .limit(1)
    )


def set_stage(
    session: Session,
    actor: Actor,
    user: User | Member,
    case: Case,
    *,
    stage: str,
    response_mode: str | None = None,
    note: str | None = None,
    member: Member | None = None,
    checked: bool = False,
) -> CaseStage:
    """`checked`: the caller (a send) has checked visibility, the claim, holds the case row lock and passes the
    acting membership, which holds `stages.set`."""
    ref = check_stage(session, stage)
    mode = check_mode(response_mode)
    text_ = clean_text(note, "note", min_len=1, max_len=STAGE_NOTE_MAX, required=False)
    if not checked:
        require_function(session, user, Permission.STAGES_SET)
        require_visible_basis(session, user, case)
        lock_case(session, case)
        require_owned(session, case)
        member = acting_member(session, user, case, Permission.STAGES_SET)
    assert member is not None
    actor = access.actor_as(actor, member)
    office = member.office
    prev = current(session, case)
    if mode is None:
        mode = ResponseMode(prev.response_mode) if prev is not None else ResponseMode.DEPARTMENT
    if prev is not None and value(prev.stage) == ref.code and ResponseMode(prev.response_mode) == mode:
        raise conflict("unchanged", f"the case is already at {ref.label}")
    row = CaseStage(
        case_id=case.id,
        office_id=office.id,
        stage=Stage(ref.code),
        response_mode=mode,
        note=text_,
        **snapshot(actor),
    )
    session.add(row)
    session.flush()
    emit_event(
        session,
        EventType.STAGE_SET,
        case,
        {
            "stage_id": str(row.id),
            "stage": ref.code,
            "label": ref.label,
            "phase": ref.phase,
            "response_mode": mode.value,
            "office_code": office.code,
        },
        dedupe=f"stage_set:{row.id}",
        actor_user_id=actor.user_id,
    )
    write_audit(
        session,
        actor,
        "stage.set",
        "case_stage",
        row.id,
        case_id=case.id,
        before=(
            {"stage": value(prev.stage), "response_mode": value(prev.response_mode)}
            if prev is not None
            else None
        ),
        after={
            "stage": ref.code,
            "response_mode": mode.value,
            "office_code": office.code,
            "note": digest(text_) if text_ else None,
        },
    )
    return row


def stage_out(session: Session, row: CaseStage, labels: dict[str, StageInfo] | None = None) -> dict[str, Any]:
    labels = labels or {s.code: s for s in catalogue(session, active_only=False)}
    info = labels.get(value(row.stage))
    office = session.get(Office, row.office_id)
    return {
        "id": row.id,
        "stage": value(row.stage),
        "label": info.label if info else value(row.stage),
        "phase": info.phase if info else None,
        "response_mode": value(row.response_mode),
        "response_mode_label": RESPONSE_MODE_LABELS.get(ResponseMode(row.response_mode)),
        "note": row.note,
        "office_code": office.code if office else None,
        "set_by": row.actor_name,
        "set_at": row.created_at,
    }


def current_block(session: Session, case: Case) -> dict[str, Any] | None:
    """The overview's `stage` block (decision 25)."""
    row = current(session, case)
    if row is None:
        return None
    out = stage_out(session, row)
    return {k: out[k] for k in ("stage", "label", "phase", "response_mode", "set_at", "office_code")}


def history_with_gaps(session: Session, user: User | Member, case: Case) -> dict[str, Any]:
    require_visible(session, user, case)
    labels = {s.code: s for s in catalogue(session, active_only=False)}
    rows = list(
        session.scalars(
            select(CaseStage)
            .where(CaseStage.case_id == case.id)
            .order_by(CaseStage.created_at.desc(), CaseStage.id.desc())
        ).all()
    )
    hist = [stage_out(session, r, labels) for r in rows]
    cur = hist[0] if hist else None
    gaps = compute_gaps(labels.values(), {h["stage"] for h in hist}, cur["stage"] if cur else None)
    return {"current": cur, "history": hist, "gaps": gaps}
