"""Local case search and the visible work list (design `cases-api`, decisions 4–6).

One box `q` with auto-detection: a UUID → id; `ASLMS/…` or `ASLMS-…` → `ref_no`; `^[A-Z]{4}\\d{12}$` → CNR;
`<type> <no>/<year>` or `<type>/<no>/<year>` → case number (the type compared with `case_types.short_name` and
`aliases` and with `cases.case_type_text`, upper-cased without white space; the same compact string against
`filing_no_text`); anything else → words over `cases.search_vector` (weight A parties, B advocates, AB text).
The tsquery is built in Python from `[0-9A-Za-z]+` words (at most 8, one-letter words dropped) and passed as
one bound parameter — never interpolated. `search` returns every non-merged match as a summary with `visible`
selected from `visibility.visible_case_condition`; `list_visible` filters by it. Reading writes no audit row."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from aslms.domain.cases import Case
from aslms.domain.org import User
from aslms.services import case_filters, inbox
from aslms.services.case_filters import CaseFilterError, CaseFilters
from aslms.services.visibility import (
    CaseState,
    case_state_condition,
    claim_departments,
    never_owned,
    visible_case_condition,
)

MAX_LIMIT = inbox.MAX_LIMIT
DEFAULT_LIMIT = inbox.DEFAULT_LIMIT
MIN_QUERY = case_filters.MIN_QUERY
MAX_WORDS = case_filters.MAX_WORDS
COUNT_CAP = 10_000
FIELDS = case_filters.FIELDS
Field = case_filters.Field
Kind = case_filters.Kind

CNR_RE = case_filters.CNR_RE
NUMBER_RE = case_filters.NUMBER_RE
WORD_RE = case_filters.WORD_RE
WEIGHTS = case_filters.WEIGHTS

# moved to `case_filters` (design `portal-filters`, decision 6); re-exported for existing imports
SearchError = CaseFilterError
ParsedQuery = case_filters.ParsedQuery
compact = case_filters.compact
words_of = case_filters.words_of
tsquery_text = case_filters.tsquery_text
parse_query = case_filters.parse_query
matching_case_types = case_filters.matching_case_types
case_type_ids = case_filters.case_type_ids

LEGACY = {"status": "case_status", "office": "owner"}


@dataclass
class Page:
    items: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    total_capped: bool = False


def filters_of(filters: CaseFilters | None, values: dict[str, Any]) -> CaseFilters:
    """`filters` as given, or built from keyword values (the shared names, plus the old `status` / `office`)."""
    status = values.pop("status", None)
    office = values.pop("office", None)
    unknown = set(values) - set(case_filters.NAMES)
    if unknown:
        raise TypeError("unknown filter " + ", ".join(sorted(unknown)))
    if filters is None:
        filters = case_filters.parse(**values)
    elif values:
        raise TypeError("give filters or filter values, not both")
    return case_filters.with_legacy(filters, status=status, office=office)


def _apply(
    stmt: Select, session: Session, f: CaseFilters, field_: str | None
) -> tuple[Select, Any, str | None]:
    """The shared filters; `q` parsed with the chosen field. Returns the statement, the rank expression for
    word queries (None otherwise) and the `match` the items report."""
    p = None
    if f.q is not None:
        auto = (field_ or "auto").lower() == "auto"
        p = f.parsed if auto and f.parsed is not None else parse_query(f.q, field_)
        stmt = stmt.where(case_filters.query_condition(session, p))
    elif (field_ or "auto").lower() not in FIELDS:
        raise SearchError("field is one of " + ", ".join(FIELDS))
    for cond in case_filters.conditions(session, f.without_q()):
        stmt = stmt.where(cond)
    return stmt, case_filters.text_rank(p), p.match if p is not None else None


def _count_capped(session: Session, stmt: Select) -> tuple[int, bool]:
    sub = stmt.order_by(None).limit(COUNT_CAP + 1).subquery()
    n = int(session.scalar(select(func.count()).select_from(sub)) or 0)
    return (COUNT_CAP, True) if n > COUNT_CAP else (n, False)


def _order(stmt: Select, rank) -> Select:
    cols = []
    if rank is not None:
        cols.append(rank.desc())
    cols.extend([Case.next_hearing_date.asc().nulls_last(), Case.reg_year.desc().nulls_last(), Case.id])
    return stmt.order_by(*cols)


def _items(
    session: Session, user: User, rows: list[tuple[Case, bool, bool]], match: str | None
) -> list[dict[str, Any]]:
    cases = [c for c, _, _ in rows]
    summ = inbox.summaries(session, cases)
    owners = inbox.primary_codes(session, [c.id for c in cases])
    may_claim = bool(claim_departments(session, user))
    return [
        {
            "case": summ[c.id],
            "visible": bool(visible),
            "owner_office_code": owners.get(c.id),
            "in_pool": bool(in_pool),
            "claimable": bool(in_pool) and may_claim,
            "match": match,
            "dossier_status": "fetched" if c.last_full_refresh_at is not None else "not_fetched",
        }
        for c, visible, in_pool in rows
    ]


def item_for(session: Session, user: User, case: Case, *, match: str | None = None) -> dict[str, Any]:
    """One `CaseSearchItemOut` for a case already in hand (court-search results)."""
    visible, in_pool = session.execute(
        select(visible_case_condition(session, user).label("v"), never_owned().label("p"))
        .select_from(Case)
        .where(Case.id == case.id)
    ).one()
    return _items(session, user, [(case, visible, in_pool)], match)[0]


# ------------------------------------------------------------------------------------------------ search / list


def search(
    session: Session,
    user: User,
    *,
    q: str,
    field_: str | None = "auto",
    filters: CaseFilters | None = None,
    visible_only: bool = False,
    limit: int | None = None,
    offset: int | None = None,
    **values: Any,
) -> Page:
    """Decision 5: every matching non-merged case as a summary; `visible` per row. `filters` (or the same as
    keyword values) narrow the matches (design `portal-filters`)."""
    p = parse_query(q, field_)
    auto = (field_ or "auto").lower() == "auto"
    f = replace(filters_of(filters, values), q=p.raw, parsed=p if auto else None)
    limit, offset = inbox.clamp(limit, offset)
    visible = visible_case_condition(session, user)
    stmt = select(Case, visible.label("visible"), never_owned().label("in_pool")).where(
        Case.merged_into_case_id.is_(None)
    )
    stmt, rank, match = _apply(stmt, session, f, field_)
    if visible_only:
        stmt = stmt.where(visible)
    total, capped = _count_capped(session, stmt)
    rows = session.execute(_order(stmt, rank).limit(limit).offset(offset)).all()
    return Page(_items(session, user, [(c, v, i) for c, v, i in rows], match), total, capped)


def list_visible(
    session: Session,
    user: User,
    *,
    field_: str | None = "auto",
    case_state: str | None = "all",
    filters: CaseFilters | None = None,
    limit: int | None = None,
    offset: int | None = None,
    **values: Any,
) -> Page:
    """`GET /cases`: the caller's visible, non-merged cases; `q` optional (filters alone are fine)."""
    f = filters_of(filters, values)
    state: CaseState = (case_state or "all").lower()  # type: ignore[assignment]
    if state not in ("active", "disposed", "all"):
        raise SearchError("case_state is one of active, disposed, all")
    limit, offset = inbox.clamp(limit, offset)
    visible = visible_case_condition(session, user)
    stmt = (
        select(Case, visible.label("visible"), never_owned().label("in_pool"))
        .where(Case.merged_into_case_id.is_(None))
        .where(visible)
    )
    stmt, rank, match = _apply(stmt, session, f, field_)
    sc = case_state_condition(state)
    if sc is not None:
        stmt = stmt.where(sc)
    total, capped = _count_capped(session, stmt)
    rows = session.execute(_order(stmt, rank).limit(limit).offset(offset)).all()
    return Page(_items(session, user, [(c, v, i) for c, v, i in rows], match), total, capped)
