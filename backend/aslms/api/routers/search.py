"""Search (plan §5.2): portal database first, NAPIX live search as fallback (stores what it finds)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query

from aslms.api import schemas as S
from aslms.api.deps import Ctx, current_ctx
from aslms.api.present import cards
from aslms.services import search as search_svc

router = APIRouter(tags=["search"])


class SearchOut(S.Page[S.CaseCard]):
    live: dict[str, Any] = {}


@router.get("/search", response_model=SearchOut)
def search(
    q: str | None = Query(
        None, description="CNR/CINO, case number (WP(C)/1234/2024), party or advocate name"
    ),
    status: str | None = Query(None, pattern="^(pending|disposed)$"),
    year: int | None = None,
    case_type: str | None = None,
    department_id: uuid.UUID | None = None,
    ownership: str | None = Query(None, pattern="^(claimed|unclaimed)$"),
    advocate: str | None = None,
    party: str | None = None,
    mine: bool = Query(False, description="only cases within your access"),
    live: bool = Query(True, description="query NAPIX when nothing is found locally"),
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=100),
    ctx: Ctx = Depends(current_ctx),
) -> SearchOut:
    f = search_svc.SearchFilters(
        status=status,
        year=year,
        case_type=case_type,
        department_id=department_id,
        ownership=ownership,
        advocate=advocate,
        party=party,
    )
    res = search_svc.search(ctx.db, ctx.principal, q, f, page=page, size=size, live=live, only_in_scope=mine)
    return SearchOut(
        total=res.total, page=page, size=size, items=cards(ctx.db, ctx.principal, res.items), live=res.live
    )
