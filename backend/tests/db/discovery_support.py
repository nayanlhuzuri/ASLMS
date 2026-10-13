"""Helpers of the department-discovery tests: the expected sweep years and refs, the queue rows of a term, a term's
rules made directly."""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa

from aslms.core.config import get_settings
from aslms.domain.ops import FetchKind, FetchQueueItem
from aslms.services import discovery


def years() -> list[int]:
    return discovery.sweep_years(date.today(), get_settings().discovery_from_year)


def ref(year: int, term: str) -> str:
    return discovery.make_ref(get_settings().napix_est_code, year, term)


def party_rows(s, term: str | None = None) -> list[FetchQueueItem]:
    stmt = sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.PARTY_SEARCH)
    if term is not None:
        stmt = stmt.where(sa.func.split_part(FetchQueueItem.ref, "|", 4) == term)
    return list(
        s.scalars(
            stmt.order_by(FetchQueueItem.created_at, FetchQueueItem.id).execution_options(
                populate_existing=True
            )
        )
    )
