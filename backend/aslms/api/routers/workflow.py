"""Phase 2 — custody and workflow (plan §5.7) and the case notes trail (§5.8)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import func, select

from aslms.api import schemas as S
from aslms.api.deps import Ctx, current_ctx
from aslms.api.present import office_ref
from aslms.core.config import get_settings
from aslms.core.errors import NotFoundError, ValidationError
from aslms.core.time import today_ist
from aslms.domain.cases import Case
from aslms.domain.documents import DocType
from aslms.domain.org import Office, User
from aslms.domain.workflow import (
    CaseStage,
    CustodyHistory,
    NoteKind,
    NoteVisibility,
    Request,
    RequestKind,
    RequestMessage,
    RequestStatus,
    Stage,
)
from aslms.services import cases as case_svc
from aslms.services import documents as doc_svc
from aslms.services import notes as notes_svc
from aslms.services import workflow as wf
from aslms.services.scope import require_case_scope, require_write

router = APIRouter(tags=["workflow & notes"])


def _case(ctx: Ctx, case_ref: str) -> Case:
    """`{case_ref}` is an id, a reference number (`ASLMS-GOA-CASE-2026-000001` in a URL) or a CNR."""
    case = case_svc.resolve_case_ref(ctx.db, case_ref)
    if case is None:
        raise NotFoundError("case not found")
    return case


def _leg(h: CustodyHistory) -> S.CustodyLegOut:
    return S.CustodyLegOut(
        seq_no=h.seq_no,
        holder_office=h.holder_office_code,
        holder_user=h.holder_user_name,
        reason=h.reason.value,
        pending_action=h.pending_action,
        due_date=h.due_date,
        started_at=h.started_at,
        moved_by=h.actor_name,
        moved_by_office=h.actor_office_code,
    )


@router.get("/cases/{case_ref}/custody/history", response_model=list[S.CustodyLegOut])
def custody_history(case_ref: str, ctx: Ctx = Depends(current_ctx)) -> list[S.CustodyLegOut]:
    """The movement trail is part of the tracking card: visible to every signed-in user."""
    return [_leg(h) for h in wf.history(ctx.db, _case(ctx, case_ref).id)]


def _request_out(ctx: Ctx, r: Request, case: Case | None = None, with_messages: bool = False) -> S.RequestOut:
    case = case or ctx.db.get(Case, r.case_id)
    to_user = ctx.db.get(User, r.to_user_id) if r.to_user_id else None
    msgs = []
    if with_messages:
        msgs = [
            S.RequestMessageOut(
                id=m.id,
                body=m.body,
                is_answer=m.is_answer,
                author=m.actor_name,
                author_office=m.actor_office_code,
                created_at=m.created_at,
            )
            for m in ctx.db.scalars(
                select(RequestMessage)
                .where(RequestMessage.request_id == r.id)
                .order_by(RequestMessage.created_at)
            )
        ]
    return S.RequestOut(
        id=r.id,
        ref_no=r.ref_no,
        case_id=r.case_id,
        case_no=case.case_no_text if case else None,
        kind=r.kind.value,
        from_office=office_ref(ctx.db.get(Office, r.from_office_id)),
        to_office=office_ref(ctx.db.get(Office, r.to_office_id)),
        to_user=to_user.full_name if to_user else None,
        subject=r.subject,
        body=r.body,
        due_date=r.due_date,
        status=r.status.value,
        overdue=bool(r.status == RequestStatus.OPEN and r.due_date and r.due_date < today_ist()),
        requested_by=r.actor_name,
        created_at=r.created_at,
        answered_at=r.answered_at,
        messages=msgs,
    )


@router.get("/cases/{case_ref}/requests", response_model=list[S.RequestOut])
def case_requests(case_ref: str, ctx: Ctx = Depends(current_ctx)) -> list[S.RequestOut]:
    case = _case(ctx, case_ref)
    require_case_scope(ctx.db, ctx.principal, case.id)
    rows = ctx.db.scalars(
        select(Request).where(Request.case_id == case.id).order_by(Request.created_at.desc())
    )
    return [_request_out(ctx, r, case, with_messages=True) for r in rows]


@router.post("/cases/{case_ref}/requests", response_model=S.RequestOut, status_code=201)
def send_request(case_ref: str, body: S.RequestIn, ctx: Ctx = Depends(current_ctx)) -> S.RequestOut:
    case = _case(ctx, case_ref)
    require_case_scope(ctx.db, ctx.principal, case.id)
    try:
        kind = RequestKind(body.kind)
    except ValueError as e:
        raise ValidationError(str(e)) from e
    r = wf.send_request(
        ctx.db,
        ctx.actor,
        ctx.principal,
        case,
        wf.RequestIn(
            kind=kind,
            to_office_id=body.to_office_id,
            subject=body.subject,
            body=body.body,
            due_date=body.due_date,
            to_user_id=body.to_user_id,
        ),
    )
    return _request_out(ctx, r, case)


@router.get("/requests", response_model=S.Page[S.RequestOut])
def my_requests(
    direction: str = Query("incoming", pattern="^(incoming|outgoing)$"),
    status: str | None = Query("open", pattern="^(open|answered|withdrawn|all)$"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    ctx: Ctx = Depends(current_ctx),
):
    """Requests addressed to (or sent by) your office and the offices below it."""
    st = None if status == "all" else RequestStatus(status)
    q = wf.requests_for_office(ctx.db, ctx.principal.office_path, incoming=direction == "incoming", status=st)
    total = ctx.db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
    rows = ctx.db.execute(q.offset((page - 1) * size).limit(size)).all()
    return S.Page(total=total, page=page, size=size, items=[_request_out(ctx, r, c) for r, c in rows])


@router.post("/requests/{request_id}/answer", response_model=S.RequestOut)
def answer(request_id: uuid.UUID, body: S.AnswerIn, ctx: Ctx = Depends(current_ctx)) -> S.RequestOut:
    return _request_out(
        ctx, wf.answer_request(ctx.db, ctx.actor, ctx.principal, request_id, body.body), with_messages=True
    )


@router.post("/requests/{request_id}/withdraw", response_model=S.RequestOut)
def withdraw(request_id: uuid.UUID, body: S.WithdrawIn, ctx: Ctx = Depends(current_ctx)) -> S.RequestOut:
    return _request_out(
        ctx,
        wf.withdraw_request(ctx.db, ctx.actor, ctx.principal, request_id, body.reason),
        with_messages=True,
    )


@router.post("/requests/{request_id}/messages", response_model=S.RequestOut)
def message(request_id: uuid.UUID, body: S.MessageIn, ctx: Ctx = Depends(current_ctx)) -> S.RequestOut:
    if not body.body.strip():
        raise ValidationError("the message cannot be empty")
    m = wf.add_message(ctx.db, ctx.actor, ctx.principal, request_id, body.body)
    return _request_out(ctx, ctx.db.get(Request, m.request_id), with_messages=True)


# ------------------------------------------------------------------ stages and hand-over
def _stage_out(st: CaseStage) -> S.StageOut:
    return S.StageOut(
        id=st.id,
        stage=st.stage.value,
        response_mode=st.response_mode,
        note=st.note,
        set_by=st.actor_name,
        set_by_office=st.actor_office_code,
        created_at=st.created_at,
    )


@router.get("/stages", response_model=list[str])
def stages() -> list[str]:
    """The guided department lifecycle, in order (not enforced)."""
    return [s.value for s in Stage]


@router.get("/cases/{case_ref}/stages", response_model=list[S.StageOut])
def case_stages(case_ref: str, ctx: Ctx = Depends(current_ctx)) -> list[S.StageOut]:
    case = _case(ctx, case_ref)
    require_case_scope(ctx.db, ctx.principal, case.id)
    return [
        _stage_out(s)
        for s in ctx.db.scalars(
            select(CaseStage).where(CaseStage.case_id == case.id).order_by(CaseStage.created_at)
        )
    ]


@router.post("/cases/{case_ref}/stages", response_model=S.StageSetOut, status_code=201)
def set_stage(case_ref: str, body: S.StageIn, ctx: Ctx = Depends(current_ctx)) -> S.StageSetOut:
    case = _case(ctx, case_ref)
    require_case_scope(ctx.db, ctx.principal, case.id)
    try:
        stage = Stage(body.stage)
    except ValueError as e:
        raise ValidationError(str(e)) from e
    res = wf.set_stage(
        ctx.db, ctx.actor, ctx.principal, case, stage, note=body.note, response_mode=body.response_mode
    )
    return S.StageSetOut(**_stage_out(res.stage).model_dump(), skipped=res.skipped)


@router.post("/cases/{case_ref}/handover", response_model=S.NoteOut, status_code=201)
def handover(case_ref: str, body: S.HandoverIn, ctx: Ctx = Depends(current_ctx)) -> S.NoteOut:
    case = _case(ctx, case_ref)
    require_case_scope(ctx.db, ctx.principal, case.id)
    note, _ = wf.hand_over(
        ctx.db,
        ctx.actor,
        ctx.principal,
        case,
        to_office_id=body.to_office_id,
        to_user_id=body.to_user_id,
        note=body.note,
        pending_action=body.pending_action,
        due_date=body.due_date,
    )
    return _note_out(ctx, note, [], [])


# ------------------------------------------------------------------ notes trail
def _note_out(ctx: Ctx, n, attachments, superseded_by) -> S.NoteOut:
    leg = ctx.db.get(CustodyHistory, n.custody_leg_id) if n.custody_leg_id else None
    sup = ctx.db.get(notes_svc.CaseNote, n.supersedes_id) if n.supersedes_id else None
    return S.NoteOut(
        id=n.id,
        ref_no=n.ref_no,
        seq_no=n.seq_no,
        kind=n.kind.value,
        body=n.body,
        visibility=n.visibility.value,
        author=n.actor_name,
        author_designation=n.actor_designation,
        author_office=n.actor_office_code,
        author_role=n.author_role,
        custody_leg_seq=leg.seq_no if leg else None,
        supersedes_seq=sup.seq_no if sup else None,
        superseded_by=superseded_by,
        source=n.source,
        created_at=n.created_at,
        attachments=[
            S.NoteAttachmentOut(
                document_id=d.id,
                filename=d.original_filename,
                mime=d.mime,
                size_bytes=d.size_bytes,
                virus_scan_status=d.virus_scan_status.value,
            )
            for d in attachments
        ],
    )


@router.get("/cases/{case_ref}/notes", response_model=list[S.NoteOut])
def list_notes(case_ref: str, ctx: Ctx = Depends(current_ctx)) -> list[S.NoteOut]:
    case = _case(ctx, case_ref)
    require_case_scope(ctx.db, ctx.principal, case.id)
    return [
        _note_out(ctx, n, atts, sup) for n, atts, sup in notes_svc.list_notes(ctx.db, ctx.principal, case.id)
    ]


@router.post("/cases/{case_ref}/notes", response_model=S.NoteOut, status_code=201)
def add_note(
    case_ref: str,
    body: str = Form(...),
    kind: str = Form("general"),
    visibility: str = Form("case_scope"),
    supersedes_id: uuid.UUID | None = Form(None),
    files: list[UploadFile] = File(default=[]),
    ctx: Ctx = Depends(current_ctx),
) -> S.NoteOut:
    case = _case(ctx, case_ref)
    require_write(ctx.principal)
    require_case_scope(ctx.db, ctx.principal, case.id)
    try:
        nk, nv = NoteKind(kind), NoteVisibility(visibility)
    except ValueError as e:
        raise ValidationError(str(e)) from e
    limit = get_settings().upload_max_mb * 1024 * 1024 + 1
    uploads = [
        doc_svc.UploadRequest(
            f.filename or "attachment",
            f.file.read(limit),
            DocType.OTHER,
            None,
            None,
            doc_svc.Visibility(nv.value),
            internal=True,
        )
        for f in files
        if f.filename
    ]
    n = notes_svc.add_note(
        ctx.db,
        ctx.actor,
        ctx.principal,
        case,
        notes_svc.NoteIn(kind=nk, body=body, visibility=nv, supersedes_id=supersedes_id, attachments=uploads),
    )
    listed = {x[0].id: x for x in notes_svc.list_notes(ctx.db, ctx.principal, case.id)}
    _, atts, sup = listed.get(n.id, (n, [], []))
    return _note_out(ctx, n, atts, sup)
