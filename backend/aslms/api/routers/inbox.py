"""Department case inbox (plan §5.4): Recommended, Claimed, Unclaimed pool, Transfers."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from aslms.api import schemas as S
from aslms.api.deps import Ctx, current_ctx
from aslms.api.present import card, cards, office_ref
from aslms.domain.cases import Case
from aslms.domain.org import Office, Role
from aslms.domain.ownership import CaseOfficeScore
from aslms.services import ownership
from aslms.services.scope import acting_department, require_role

router = APIRouter(prefix="/inbox", tags=["inbox"])


def _dept(ctx: Ctx, office_id: uuid.UUID | None) -> Office:
    return ctx.db.get(Office, acting_department(ctx.principal, office_id))


def _page(ctx: Ctx, stmt, page: int, size: int):
    total = ctx.db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    return total, ctx.db.execute(stmt.offset((page - 1) * size).limit(size)).all()


@router.get("/recommended", response_model=S.Page[S.RecommendationOut])
def recommended(
    office_id: uuid.UUID | None = None,
    band: str | None = Query(None, pattern="^(high|medium)$"),
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=200),
    ctx: Ctx = Depends(current_ctx),
):
    dept = _dept(ctx, office_id)
    stmt = ownership.recommended_query(dept.id)
    if band:
        from aslms.domain.ownership import Recommendation

        stmt = stmt.where(Recommendation.band == band)
    total, rows = _page(ctx, stmt, page, size)
    case_cards = {c.id: c for c in cards(ctx.db, ctx.principal, [r[1] for r in rows])}
    signals = (
        dict(
            ctx.db.execute(
                select(CaseOfficeScore.case_id, CaseOfficeScore.signals).where(
                    CaseOfficeScore.office_id == dept.id, CaseOfficeScore.case_id.in_([r[1].id for r in rows])
                )
            ).all()
        )
        if rows
        else {}
    )
    items = [
        S.RecommendationOut(
            id=rec.id,
            case=case_cards[case.id],
            score=float(rec.score),
            band=rec.band.value,
            origin=rec.origin.value,
            signals=signals.get(case.id, []),
            reason=rec.reason,
            created_at=rec.created_at,
        )
        for rec, case in rows
    ]
    return S.Page(total=total, page=page, size=size, items=items)


@router.get("/claimed", response_model=S.Page[S.CaseCard])
def claimed(
    office_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=200),
    ctx: Ctx = Depends(current_ctx),
):
    dept = _dept(ctx, office_id)
    total, rows = _page(ctx, ownership.claimed_query(dept.path), page, size)
    seen, cases = set(), []
    for _, case in rows:
        if case.id not in seen:
            seen.add(case.id)
            cases.append(case)
    return S.Page(total=total, page=page, size=size, items=cards(ctx.db, ctx.principal, cases))


@router.get("/unclaimed", response_model=S.Page[S.CaseCard])
def unclaimed(
    q: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=200),
    ctx: Ctx = Depends(current_ctx),
):
    """The unclaimed pool: any department can search and claim; the central operator follows it up."""
    require_role(
        ctx.principal,
        Role.DEPT_ADMIN,
        Role.DEPT_HEAD,
        Role.CENTRAL_OPERATOR,
        Role.STATE_OVERSIGHT,
        Role.AUDITOR,
    )
    stmt = ownership.unclaimed_query()
    if q:
        like = f"%{q.strip().upper()}%"
        stmt = stmt.where(
            (func.upper(Case.case_no_text).like(like))
            | (func.upper(Case.petitioner_summary).like(like))
            | (func.upper(Case.respondent_summary).like(like))
            | (Case.cnr == q.strip().upper())
        )
    total = ctx.db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(ctx.db.scalars(stmt.offset((page - 1) * size).limit(size)))
    return S.Page(total=total, page=page, size=size, items=cards(ctx.db, ctx.principal, rows))


@router.get("/transfers", response_model=list[S.TransferOut])
def transfers(office_id: uuid.UUID | None = None, ctx: Ctx = Depends(current_ctx)):
    dept = _dept(ctx, office_id)
    out = []
    for t, case in ctx.db.execute(ownership.transfers_query(dept.id).limit(200)):
        out.append(
            S.TransferOut(
                id=t.id,
                case=card(ctx.db, ctx.principal, case),
                direction="incoming" if t.to_office_id == dept.id else "outgoing",
                from_office=office_ref(ctx.db.get(Office, t.from_office_id)),
                to_office=office_ref(ctx.db.get(Office, t.to_office_id)),
                status=t.status.value,
                reason=t.reason,
                requested_by=t.actor_name,
                created_at=t.created_at,
                decided_at=t.decided_at,
            )
        )
    return out
