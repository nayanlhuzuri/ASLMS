"""Cause-list archive: lists per date and their entries (public court information)."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import any_, func, literal, select

from aslms.api import schemas as S
from aslms.api.deps import Ctx, current_ctx
from aslms.core.errors import NotFoundError
from aslms.domain.causelists import CauseList, CauseListEntry
from aslms.domain.documents import Document
from aslms.services import storage

router = APIRouter(prefix="/causelists", tags=["cause lists"])


@router.get("/dates", response_model=list[S.CauseListDateOut])
def dates(limit: int = Query(60, le=400), ctx: Ctx = Depends(current_ctx)) -> list[dict]:
    rows = ctx.db.execute(
        select(CauseList.list_date, func.count(), func.sum(CauseList.entry_count))
        .group_by(CauseList.list_date)
        .order_by(CauseList.list_date.desc())
        .limit(limit)
    )
    return [{"date": d.isoformat(), "lists": n, "entries": int(e or 0)} for d, n, e in rows]


@router.get("", response_model=list[S.CauseListOut])
def lists(
    list_date: date = Query(..., alias="date"), ctx: Ctx = Depends(current_ctx)
) -> list[S.CauseListOut]:
    return [
        S.CauseListOut.model_validate(c)
        for c in ctx.db.scalars(
            select(CauseList)
            .where(CauseList.list_date == list_date)
            .order_by(CauseList.list_type, CauseList.source, CauseList.bench_id)
        )
    ]


@router.get("/{causelist_id}/entries", response_model=S.Page[S.EntryOut])
def entries(
    causelist_id: uuid.UUID,
    q: str | None = None,
    code: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=500),
    ctx: Ctx = Depends(current_ctx),
):
    stmt = select(CauseListEntry).where(CauseListEntry.causelist_id == causelist_id)
    if q:
        like = f"%{q.strip().upper()}%"
        stmt = stmt.where(
            func.upper(CauseListEntry.case_no_text).like(like)
            | func.upper(CauseListEntry.petitioner_text).like(like)
            | func.upper(CauseListEntry.respondent_text).like(like)
            | (CauseListEntry.cnr == q.strip().upper())
        )
    if code:
        stmt = stmt.where(literal(code.strip().upper()) == any_(CauseListEntry.counsel_codes))
    total = ctx.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = ctx.db.scalars(stmt.order_by(CauseListEntry.sr_no).offset((page - 1) * size).limit(size))
    return S.Page(total=total, page=page, size=size, items=[S.EntryOut.model_validate(e) for e in rows])


@router.get("/{causelist_id}/pdf")
def pdf(causelist_id: uuid.UUID, ctx: Ctx = Depends(current_ctx)) -> FileResponse:
    cl = ctx.db.get(CauseList, causelist_id)
    if cl is None or cl.document_id is None:
        raise NotFoundError("no document stored for this cause list")
    doc = ctx.db.get(Document, cl.document_id)
    return FileResponse(
        storage.blob_path(doc.storage_key),
        media_type="application/pdf",
        filename=doc.original_filename or f"causelist_{cl.list_date}.pdf",
        content_disposition_type="inline",
    )
