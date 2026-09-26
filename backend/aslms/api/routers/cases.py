"""Case detail page (plan §5.3): tracking card for everyone; contents, timeline, orders and documents within
scope; ownership actions (claim, dismiss, transfer, allot, release) for the department."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_, select

from aslms.api import schemas as S
from aslms.api.deps import Ctx, current_ctx
from aslms.api.present import card, detail, office_ref, ownership_rows
from aslms.core.errors import NotFoundError, ValidationError
from aslms.core.text import is_cnr
from aslms.domain.cases import Case, CaseHearing, CaseLink
from aslms.domain.causelists import CauseList, CauseListEntry
from aslms.domain.documents import DocType, Document, Order, Visibility
from aslms.domain.org import Office
from aslms.domain.ownership import CaseOfficeScore, OwnershipTransfer
from aslms.services import documents as doc_svc
from aslms.services import events as event_svc
from aslms.services import ownership, storage
from aslms.services.scope import acting_department, case_in_scope, require_case_scope, require_write

router = APIRouter(tags=["cases"])


def _case(ctx: Ctx, case_id: uuid.UUID) -> Case:
    case = ctx.db.get(Case, case_id)
    if case is None:
        raise NotFoundError("case not found")
    if case.merged_into_case_id:
        case = ctx.db.get(Case, case.merged_into_case_id)
    return case


@router.get("/cases/by-cnr/{cnr}", response_model=S.CaseCard)
def by_cnr(cnr: str, ctx: Ctx = Depends(current_ctx)) -> S.CaseCard:
    if not is_cnr(cnr):
        raise ValidationError("not a CNR")
    case = ctx.db.scalar(select(Case).where(Case.cnr == cnr.upper()))
    if case is None:
        raise NotFoundError("no case with this CNR in the portal; use search to fetch it")
    return card(ctx.db, ctx.principal, case)


@router.get("/cases/{case_id}", response_model=S.CaseDetail | S.CaseCard)
def get_case(case_id: uuid.UUID, ctx: Ctx = Depends(current_ctx)) -> S.CaseDetail | S.CaseCard:
    """Full detail when the case is in scope, otherwise the tracking card only."""
    case = _case(ctx, case_id)
    if case_in_scope(ctx.db, ctx.principal, case.id):
        return detail(ctx.db, ctx.principal, case)
    return card(ctx.db, ctx.principal, case)


@router.get("/cases/{case_id}/timeline", response_model=list[S.EventOut])
def timeline(case_id: uuid.UUID, ctx: Ctx = Depends(current_ctx)) -> list[S.EventOut]:
    case = _case(ctx, case_id)
    in_scope = case_in_scope(ctx.db, ctx.principal, case.id)
    return [
        S.EventOut(
            id=e.id,
            type=e.type.value,
            occurred_at=e.occurred_at,
            payload=e.payload,
            visibility=e.visibility.value,
        )
        for e in event_svc.timeline(ctx.db, case.id, tracking_only=not in_scope)
    ]


@router.get("/cases/{case_id}/hearings", response_model=list[S.HearingOut])
def hearings(case_id: uuid.UUID, ctx: Ctx = Depends(current_ctx)) -> list[S.HearingOut]:
    case = _case(ctx, case_id)
    require_case_scope(ctx.db, ctx.principal, case.id)
    rows = ctx.db.scalars(
        select(CaseHearing).where(CaseHearing.case_id == case.id).order_by(CaseHearing.business_date.desc())
    )
    return [
        S.HearingOut(
            business_date=h.business_date,
            purpose=h.purpose,
            bench_text=h.bench_text,
            next_date=h.next_date,
            business_text=h.business_text,
            source=h.source.value,
        )
        for h in rows
    ]


@router.get("/cases/{case_id}/listings", response_model=list[S.ListingOut])
def listings(case_id: uuid.UUID, ctx: Ctx = Depends(current_ctx)) -> list[S.ListingOut]:
    """Cause-list appearances (public court information: visible with the tracking card)."""
    case = _case(ctx, case_id)
    rows = ctx.db.execute(
        select(CauseListEntry, CauseList)
        .join(CauseList, CauseList.id == CauseListEntry.causelist_id)
        .where(CauseListEntry.case_id == case.id)
        .order_by(CauseList.list_date.desc(), CauseListEntry.sr_no)
        .limit(200)
    )
    return [
        S.ListingOut(
            list_date=cl.list_date,
            list_type=cl.list_type.value,
            source=e.source.value,
            court_no=e.court_no,
            sr_no=e.sr_no,
            case_no=e.case_no_text,
            section=(e.raw or {}).get("section"),
            bench=(e.raw or {}).get("bench"),
            counsel_codes=e.counsel_codes or [],
            causelist_id=cl.id,
        )
        for e, cl in rows
    ]


@router.get("/cases/{case_id}/links", response_model=list[S.LinkOut])
def links(case_id: uuid.UUID, ctx: Ctx = Depends(current_ctx)) -> list[S.LinkOut]:
    """Linked cases for the relationship graph (appeals, IAs, connected matters)."""
    case = _case(ctx, case_id)
    out: list[S.LinkOut] = []
    for ln in ctx.db.scalars(
        select(CaseLink).where(or_(CaseLink.from_case_id == case.id, CaseLink.to_case_id == case.id))
    ):
        outgoing = ln.from_case_id == case.id
        other_id = ln.to_case_id if outgoing else ln.from_case_id
        other = ctx.db.get(Case, other_id) if other_id else None
        out.append(
            S.LinkOut(
                kind=ln.kind.value,
                direction="out" if outgoing else "in",
                case_no=other.case_no_text if other else ln.to_case_no_text,
                cnr=other.cnr if other else ln.to_cnr,
                case_id=other.id if other else None,
                status=other.status.value if other else None,
            )
        )
    return out


@router.get("/cases/{case_id}/orders", response_model=list[S.OrderOut])
def orders(case_id: uuid.UUID, ctx: Ctx = Depends(current_ctx)) -> list[S.OrderOut]:
    case = _case(ctx, case_id)
    require_case_scope(ctx.db, ctx.principal, case.id)
    return [
        S.OrderOut.model_validate(o)
        for o in ctx.db.scalars(
            select(Order)
            .where(Order.case_id == case.id)
            .order_by(Order.order_date.desc(), Order.order_no.desc())
        )
    ]


@router.get("/cases/{case_id}/scores", response_model=list[S.ScoreOut])
def scores(case_id: uuid.UUID, ctx: Ctx = Depends(current_ctx)) -> list[S.ScoreOut]:
    """Signals behind each department's score (shown in the inbox)."""
    case = _case(ctx, case_id)
    q = (
        select(CaseOfficeScore, Office)
        .join(Office, Office.id == CaseOfficeScore.office_id)
        .where(CaseOfficeScore.case_id == case.id)
    )
    if not ctx.principal.is_state_tier:
        q = q.where(CaseOfficeScore.office_id == ctx.principal.department_id)
    return [
        S.ScoreOut(office=office_ref(o), score=float(s.score), signals=s.signals, computed_at=s.computed_at)
        for s, o in ctx.db.execute(q.order_by(CaseOfficeScore.score.desc()))
    ]


@router.get("/cases/{case_id}/ownership", response_model=list[S.OwnershipOut])
def ownership_history(case_id: uuid.UUID, ctx: Ctx = Depends(current_ctx)) -> list[S.OwnershipOut]:
    case = _case(ctx, case_id)
    return ownership_rows(ctx.db, case.id, include_history=case_in_scope(ctx.db, ctx.principal, case.id))


# ------------------------------------------------------------------ documents
@router.get("/cases/{case_id}/documents", response_model=list[S.DocumentOut])
def list_documents(case_id: uuid.UUID, ctx: Ctx = Depends(current_ctx)) -> list[S.DocumentOut]:
    case = _case(ctx, case_id)
    require_case_scope(ctx.db, ctx.principal, case.id)
    rows = ctx.db.scalars(
        select(Document)
        .where(Document.case_id == case.id, doc_svc.document_visibility_clause(ctx.principal))
        .order_by(Document.doc_date.desc().nulls_last(), Document.created_at.desc())
    )
    return [S.DocumentOut.model_validate(d) for d in rows]


@router.post("/cases/{case_id}/documents", response_model=S.DocumentOut, status_code=201)
def upload_document(
    case_id: uuid.UUID,
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    visibility: str = Form("case_scope"),
    doc_date: date | None = Form(None),
    description: str | None = Form(None),
    internal: bool | None = Form(None),
    ctx: Ctx = Depends(current_ctx),
) -> S.DocumentOut:
    case = _case(ctx, case_id)
    require_write(ctx.principal)
    require_case_scope(ctx.db, ctx.principal, case.id)
    try:
        dt, vis = DocType(doc_type), Visibility(visibility)
    except ValueError as e:
        raise ValidationError(str(e)) from e
    from aslms.core.config import get_settings

    content = file.file.read(get_settings().upload_max_mb * 1024 * 1024 + 1)
    doc = doc_svc.upload(
        ctx.db,
        ctx.actor,
        ctx.principal,
        case,
        doc_svc.UploadRequest(
            filename=file.filename or "upload",
            content=content,
            doc_type=dt,
            doc_date=doc_date,
            description=description,
            visibility=vis,
            internal=internal,
        ),
    )
    return S.DocumentOut.model_validate(doc)


@router.get("/documents/{document_id}/download")
def download_document(document_id: uuid.UUID, ctx: Ctx = Depends(current_ctx)) -> FileResponse:
    doc = doc_svc.get_visible(ctx.db, ctx.principal, document_id)
    if doc is None:
        raise NotFoundError("document not found or not visible to you")
    from aslms.services import audit

    audit.record(ctx.db, ctx.actor, "document.download", "document", doc.id, case_id=doc.case_id)
    return FileResponse(
        storage.blob_path(doc.storage_key),
        media_type=doc.mime,
        filename=doc.original_filename or f"{doc.id}",
        content_disposition_type="inline",
    )


# ------------------------------------------------------------------ ownership actions
@router.post("/cases/{case_id}/claim", response_model=list[S.OwnershipOut])
def claim(case_id: uuid.UUID, body: S.ClaimIn, ctx: Ctx = Depends(current_ctx)) -> list[S.OwnershipOut]:
    case = _case(ctx, case_id)
    dept = acting_department(ctx.principal, body.office_id)
    ownership.claim(ctx.db, ctx.actor, case, dept, reason=body.reason)
    return ownership_rows(ctx.db, case.id)


@router.post("/cases/{case_id}/dismiss", response_model=S.Ok)
def dismiss(case_id: uuid.UUID, body: S.DismissIn, ctx: Ctx = Depends(current_ctx)) -> S.Ok:
    case = _case(ctx, case_id)
    dept = acting_department(ctx.principal, body.office_id)
    ownership.dismiss(
        ctx.db, ctx.actor, case, dept, reason=body.reason, suggest_office_id=body.suggest_office_id
    )
    return S.Ok(detail="dismissed")


@router.post("/cases/{case_id}/transfer", response_model=S.Ok)
def transfer(case_id: uuid.UUID, body: S.TransferIn, ctx: Ctx = Depends(current_ctx)) -> S.Ok:
    case = _case(ctx, case_id)
    dept = acting_department(ctx.principal, body.office_id)
    t = ownership.request_transfer(ctx.db, ctx.actor, case, dept, body.to_office_id, reason=body.reason)
    return S.Ok(detail=str(t.id))


@router.post("/cases/{case_id}/allot", response_model=list[S.OwnershipOut])
def allot(case_id: uuid.UUID, body: S.AllotIn, ctx: Ctx = Depends(current_ctx)) -> list[S.OwnershipOut]:
    case = _case(ctx, case_id)
    dept = acting_department(ctx.principal, body.office_id)
    ownership.allot(
        ctx.db,
        ctx.actor,
        case,
        dept,
        unit_office_id=body.unit_office_id,
        officer_user_id=body.officer_user_id,
    )
    return ownership_rows(ctx.db, case.id)


@router.post("/cases/{case_id}/release", response_model=S.Ok)
def release(case_id: uuid.UUID, body: S.ReleaseIn, ctx: Ctx = Depends(current_ctx)) -> S.Ok:
    case = _case(ctx, case_id)
    dept = acting_department(ctx.principal, body.office_id)
    ownership.release(ctx.db, ctx.actor, case, dept, reason=body.reason)
    return S.Ok(detail="released")


def _transfer(ctx: Ctx, transfer_id: uuid.UUID) -> OwnershipTransfer:
    t = ctx.db.get(OwnershipTransfer, transfer_id)
    if t is None:
        raise NotFoundError("transfer not found")
    return t


@router.post("/transfers/{transfer_id}/accept", response_model=S.Ok)
def accept_transfer(transfer_id: uuid.UUID, body: S.DecideIn, ctx: Ctx = Depends(current_ctx)) -> S.Ok:
    t = _transfer(ctx, transfer_id)
    ownership.decide_transfer(
        ctx.db,
        ctx.actor,
        t,
        acting_department(ctx.principal, body.office_id),
        accept=True,
        reason=body.reason,
    )
    return S.Ok(detail="accepted")


@router.post("/transfers/{transfer_id}/decline", response_model=S.Ok)
def decline_transfer(transfer_id: uuid.UUID, body: S.DecideIn, ctx: Ctx = Depends(current_ctx)) -> S.Ok:
    t = _transfer(ctx, transfer_id)
    ownership.decide_transfer(
        ctx.db,
        ctx.actor,
        t,
        acting_department(ctx.principal, body.office_id),
        accept=False,
        reason=body.reason,
    )
    return S.Ok(detail="declined")


@router.post("/transfers/{transfer_id}/withdraw", response_model=S.Ok)
def withdraw_transfer(transfer_id: uuid.UUID, body: S.DecideIn, ctx: Ctx = Depends(current_ctx)) -> S.Ok:
    t = _transfer(ctx, transfer_id)
    ownership.withdraw_transfer(ctx.db, ctx.actor, t, acting_department(ctx.principal, body.office_id))
    return S.Ok(detail="withdrawn")
