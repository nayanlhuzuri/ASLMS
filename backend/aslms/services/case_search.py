"""Local case search and the visible work list (design `cases-api`, decisions 4–6).

One box `q` with auto-detection: a UUID → id; `ASLMS/…` or `ASLMS-…` → `ref_no`; `^[A-Z]{4}\\d{12}$` → CNR;
`<type> <no>/<year>` or `<type>/<no>/<year>` → case number (the type compared with `case_types.short_name` and
`aliases` and with `cases.case_type_text`, upper-cased without white space; the same compact string against
`filing_no_text`); anything else → words over `cases.search_vector` (weight A parties, B advocates, AB text).
The tsquery is built in Python from `[0-9A-Za-z]+` words (at most 8, one-letter words dropped) and passed as
one bound parameter — never interpolated. `search` returns every non-merged match as a summary with `visible`
selected from `visibility.visible_case_condition`; `list_visible` filters by it. Reading writes no audit row."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from sqlalchemy import Select, and_, exists, func, literal_column, or_, select
from sqlalchemy.orm import Session

from aslms.domain.cases import Case, CaseStatus
from aslms.domain.causelists import Causelist, CauselistEntry
from aslms.domain.courts import CaseType
from aslms.domain.org import User
from aslms.domain.ownership import CaseOwnership, OwnershipRole, OwnershipStatus
from aslms.domain.reference import Permission
from aslms.services import access, inbox
from aslms.services.cases import ref_no_from_url
from aslms.services.offices import find_office
from aslms.services.visibility import (
    CaseState,
    case_state_condition,
    is_department,
    never_owned,
    user_department,
    visible_case_condition,
)

MAX_LIMIT = inbox.MAX_LIMIT
DEFAULT_LIMIT = inbox.DEFAULT_LIMIT
MIN_QUERY = 3
MAX_WORDS = 8
COUNT_CAP = 10_000
FIELDS = ("auto", "cnr", "number", "party", "advocate", "text")
Field = Literal["auto", "cnr", "number", "party", "advocate", "text"]
Kind = Literal["id", "ref_no", "cnr", "number", "text"]

CNR_RE = re.compile(r"^[A-Z]{4}\d{12}$")
NUMBER_RE = re.compile(r"^(?P<type>[A-Z][A-Z().\-\s]*?)\s*[/\s]\s*(?P<no>\d{1,7})\s*/\s*(?P<year>\d{4})$")
WORD_RE = re.compile(r"[0-9A-Za-z]+")
WEIGHTS = {"party": "A", "advocate": "B", "text": "AB"}


class SearchError(ValueError):
    """Bad input (HTTP 400)."""


@dataclass
class ParsedQuery:
    kind: Kind
    raw: str
    match: str  # what the item reports: id / ref_no / cnr / number / party / advocate / text
    id: uuid.UUID | None = None
    ref_no: str | None = None
    cnr: str | None = None
    type_compact: str | None = None
    reg_no: int | None = None
    reg_year: int | None = None
    words: list[str] = field(default_factory=list)
    weights: str = "AB"

    @property
    def tsquery(self) -> str:
        return tsquery_text(self.words, self.weights)


@dataclass
class Page:
    items: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    total_capped: bool = False


# ------------------------------------------------------------------------------------------------ pure helpers


def compact(text: str | None) -> str:
    return re.sub(r"\s+", "", (text or "").upper())


def words_of(q: str) -> list[str]:
    out = [w for w in WORD_RE.findall(q or "") if len(w) > 1]
    return out[:MAX_WORDS]


def tsquery_text(words: list[str], weights: str) -> str:
    """`ram:*A & kumar:*A` — every term a prefix match restricted to the weights; only word characters and the
    operators written here can appear, whatever the user typed."""
    w = "".join(c for c in weights.upper() if c in "ABCD") or "AB"
    terms = [f"{word.lower()}:*{w}" for word in words if WORD_RE.fullmatch(word)]
    return " & ".join(terms)


def parse_query(q: str | None, field_: str | None = "auto") -> ParsedQuery:
    raw = (q or "").strip()
    if len(raw) < MIN_QUERY:
        raise SearchError(f"q is at least {MIN_QUERY} characters")
    f = (field_ or "auto").lower()
    if f not in FIELDS:
        raise SearchError("field is one of " + ", ".join(FIELDS))
    upper = raw.upper()
    if f == "cnr":
        if not CNR_RE.match(upper):
            raise SearchError("not a CNR: four letters and twelve digits")
        return ParsedQuery("cnr", raw, "cnr", cnr=upper)
    if f == "number":
        parsed = _number(raw, upper)
        if parsed is None:
            raise SearchError("not a case number: <type> <no>/<year> or <type>/<no>/<year>")
        return parsed
    if f in WEIGHTS:
        words = words_of(raw)
        if not words:
            raise SearchError("q has no searchable word")
        return ParsedQuery("text", raw, f, words=words, weights=WEIGHTS[f])
    # auto
    try:
        return ParsedQuery("id", raw, "id", id=uuid.UUID(raw))
    except ValueError:
        pass
    ref_no = ref_no_from_url(raw)
    if ref_no is not None:
        return ParsedQuery("ref_no", raw, "ref_no", ref_no=ref_no)
    if CNR_RE.match(upper):
        return ParsedQuery("cnr", raw, "cnr", cnr=upper)
    parsed = _number(raw, upper)
    if parsed is not None:
        return parsed
    words = words_of(raw)
    if not words:
        raise SearchError("q has no searchable word")
    return ParsedQuery("text", raw, "text", words=words, weights="AB")


def _number(raw: str, upper: str) -> ParsedQuery | None:
    m = NUMBER_RE.match(upper)
    if m is None:
        return None
    return ParsedQuery(
        "number",
        raw,
        "number",
        type_compact=compact(m.group("type")),
        reg_no=int(m.group("no")),
        reg_year=int(m.group("year")),
    )


# ------------------------------------------------------------------------------------------------ SQL pieces


def _compact_sql(col):
    """upper(regexp_replace(col, '\\s', '', 'g')) — the expression of `ix_cases_case_no_compact`."""
    return func.upper(
        func.regexp_replace(col, literal_column(r"'\s'"), literal_column("''"), literal_column("'g'"))
    )


def matching_case_types(session: Session, type_compact: str) -> list[CaseType]:
    """Case types whose short name or an alias equals the compact type."""
    return [
        ct
        for ct in session.scalars(select(CaseType)).all()
        if compact(ct.short_name) == type_compact or any(compact(a) == type_compact for a in ct.aliases or [])
    ]


def case_type_ids(session: Session, type_compact: str) -> list[uuid.UUID]:
    return [ct.id for ct in matching_case_types(session, type_compact)]


def _number_condition(session: Session, p: ParsedQuery):
    printed = f"{p.type_compact}/{p.reg_no}/{p.reg_year}"
    conds = [
        _compact_sql(Case.case_no_text) == printed,
        _compact_sql(Case.filing_no_text) == printed,
        and_(
            _compact_sql(Case.case_type_text) == p.type_compact,
            Case.reg_no == p.reg_no,
            Case.reg_year == p.reg_year,
        ),
    ]
    types = matching_case_types(session, p.type_compact)
    if types:
        conds.append(
            and_(
                Case.case_type_id.in_([ct.id for ct in types]),
                Case.reg_no == p.reg_no,
                Case.reg_year == p.reg_year,
            )
        )
        # an alias also finds the printed number under the master's short name (provisional cases)
        by_short = sorted(
            {f"{compact(ct.short_name)}/{p.reg_no}/{p.reg_year}" for ct in types if ct.short_name}
        )
        if by_short:
            conds.append(_compact_sql(Case.case_no_text).in_(by_short))
    return or_(*conds)


def _case_type_filter(session: Session, case_type: str):
    t = compact(case_type)
    if not t:
        raise SearchError("case_type is empty")
    cond = _compact_sql(Case.case_type_text) == t
    ids = case_type_ids(session, t)
    if ids:
        cond = cond | Case.case_type_id.in_(ids)
    return cond


def _office_filter(session: Session, office: str):
    dept = find_office(session, office)
    if dept is None or not is_department(dept):
        raise SearchError(f"{office!r} is not a department")
    return exists().where(
        CaseOwnership.case_id == Case.id,
        CaseOwnership.office_id == dept.id,
        CaseOwnership.role == OwnershipRole.PRIMARY,
        CaseOwnership.status == OwnershipStatus.ACTIVE,
    )


def _listed_filter(listed_from: date | None, listed_to: date | None):
    conds = [CauselistEntry.case_id == Case.id]
    if listed_from is not None:
        conds.append(Causelist.list_date >= listed_from)
    if listed_to is not None:
        conds.append(Causelist.list_date <= listed_to)
    return exists(
        select(1)
        .select_from(CauselistEntry)
        .join(Causelist, Causelist.id == CauselistEntry.causelist_id)
        .where(and_(*conds))
    )


def _status(value: str | None) -> CaseStatus | None:
    if not value:
        return None
    try:
        return CaseStatus(value.lower())
    except ValueError as exc:
        raise SearchError("status is one of pending, disposed, unknown") from exc


def _apply_query(stmt: Select, session: Session, p: ParsedQuery | None) -> tuple[Select, Any]:
    """Adds the `q` condition; returns the rank expression for text queries (None otherwise)."""
    if p is None:
        return stmt, None
    if p.kind == "id":
        return stmt.where(Case.id == p.id), None
    if p.kind == "ref_no":
        return stmt.where(Case.ref_no == p.ref_no), None
    if p.kind == "cnr":
        return stmt.where(Case.cnr == p.cnr), None
    if p.kind == "number":
        return stmt.where(_number_condition(session, p)), None
    tsq = func.to_tsquery("simple", p.tsquery)
    rank = func.ts_rank(Case.search_vector, tsq)
    return stmt.where(Case.search_vector.op("@@")(tsq)), rank


def _apply_filters(
    stmt: Select,
    session: Session,
    *,
    status: str | None,
    year: int | None,
    case_type: str | None,
    office: str | None,
    listed_from: date | None,
    listed_to: date | None,
) -> Select:
    st = _status(status)
    if st is not None:
        stmt = stmt.where(Case.status == st)
    if year is not None:
        stmt = stmt.where(Case.reg_year == int(year))
    if case_type:
        stmt = stmt.where(_case_type_filter(session, case_type))
    if office:
        stmt = stmt.where(_office_filter(session, office))
    if listed_from is not None or listed_to is not None:
        stmt = stmt.where(_listed_filter(listed_from, listed_to))
    return stmt


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
    may_claim = (
        access.has(session, user, Permission.CASES_CLAIM) and user_department(session, user) is not None
    )
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
    status: str | None = None,
    year: int | None = None,
    case_type: str | None = None,
    office: str | None = None,
    listed_from: date | None = None,
    listed_to: date | None = None,
    visible_only: bool = False,
    limit: int | None = None,
    offset: int | None = None,
) -> Page:
    """Decision 5: every matching non-merged case as a summary; `visible` per row."""
    p = parse_query(q, field_)
    limit, offset = inbox.clamp(limit, offset)
    visible = visible_case_condition(session, user)
    stmt = select(Case, visible.label("visible"), never_owned().label("in_pool")).where(
        Case.merged_into_case_id.is_(None)
    )
    stmt, rank = _apply_query(stmt, session, p)
    stmt = _apply_filters(
        stmt,
        session,
        status=status,
        year=year,
        case_type=case_type,
        office=office,
        listed_from=listed_from,
        listed_to=listed_to,
    )
    if visible_only:
        stmt = stmt.where(visible)
    total, capped = _count_capped(session, stmt)
    rows = session.execute(_order(stmt, rank).limit(limit).offset(offset)).all()
    return Page(_items(session, user, [(c, v, i) for c, v, i in rows], p.match), total, capped)


def list_visible(
    session: Session,
    user: User,
    *,
    q: str | None = None,
    field_: str | None = "auto",
    status: str | None = None,
    case_state: str | None = "all",
    year: int | None = None,
    case_type: str | None = None,
    office: str | None = None,
    listed_from: date | None = None,
    listed_to: date | None = None,
    next_from: date | None = None,
    next_to: date | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> Page:
    """`GET /cases`: the caller's visible, non-merged cases; `q` optional (filters alone are fine)."""
    p = parse_query(q, field_) if (q or "").strip() else None
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
    stmt, rank = _apply_query(stmt, session, p)
    stmt = _apply_filters(
        stmt,
        session,
        status=status,
        year=year,
        case_type=case_type,
        office=office,
        listed_from=listed_from,
        listed_to=listed_to,
    )
    sc = case_state_condition(state)
    if sc is not None:
        stmt = stmt.where(sc)
    if next_from is not None:
        stmt = stmt.where(Case.next_hearing_date >= next_from)
    if next_to is not None:
        stmt = stmt.where(Case.next_hearing_date <= next_to)
    total, capped = _count_capped(session, stmt)
    rows = session.execute(_order(stmt, rank).limit(limit).offset(offset)).all()
    return Page(_items(session, user, [(c, v, i) for c, v, i in rows], p.match if p else None), total, capped)
