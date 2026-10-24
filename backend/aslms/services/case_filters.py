"""The shared case filters of every case list (design `portal-filters`, decisions 1-7).

One set of names in every list API and portal URL: words `q` (the Search box's parsing), the cause-list date
`listed_from` / `listed_to` with the court `court_no` and the bench `bench` read from the same cause-list entry,
the next hearing `next_from` / `next_to`, `case_type` (the master's short name or aliases, or the case's type
text), `year` (`cases.reg_year`), `case_status` and `owner` (the department holding the active primary
ownership). `parse` validates and normalises; `conditions` turns a `CaseFilters` into SQL conditions over a
`Case` entity or alias, which every list ANDs with its own rules, so a filter only ever narrows. Pure SQL
building: no write, no audit. This module imports neither `case_search` nor `inbox` (both import it).

`q` is read by `parse_query` (moved here from `case_search`): a UUID -> id; `ASLMS/...` or `ASLMS-...` ->
`ref_no`; `^[A-Z]{4}\\d{12}$` -> CNR; `<type> <no>/<year>` or `<type>/<no>/<year>` -> case number (the type
compared with `case_types.short_name` and `aliases` and with `cases.case_type_text`, upper-cased without white
space; the same compact string against `filing_no_text`); anything else -> words over `cases.search_vector`
(weight A parties, B advocates, AB text). The tsquery is built in Python from `[0-9A-Za-z]+` words (at most 8,
one-letter words dropped) and passed as one bound parameter, never interpolated."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, fields, replace
from datetime import date
from typing import Any, Literal

from sqlalchemy import ColumnElement, and_, exists, func, literal, literal_column, or_, select
from sqlalchemy.orm import Session

from aslms.domain.cases import Case, CaseStatus
from aslms.domain.causelists import CURRENT_LIST, Causelist, CauselistEntry
from aslms.domain.courts import CaseType
from aslms.domain.ownership import CaseOwnership, OwnershipRole, OwnershipStatus
from aslms.services.cases import ref_no_from_url
from aslms.services.offices import find_office
from aslms.services.visibility import is_department

MIN_QUERY = 3
MAX_WORDS = 8
MIN_BENCH = 3
MAX_BENCH = 200
MAX_COURT_NO = 20
MIN_YEAR = 1900
MAX_YEAR = 2100
CASE_STATUSES = tuple(s.value for s in CaseStatus)
FIELDS = ("auto", "cnr", "number", "party", "advocate", "text")
Field = Literal["auto", "cnr", "number", "party", "advocate", "text"]
Kind = Literal["id", "ref_no", "cnr", "number", "text"]

CNR_RE = re.compile(r"^[A-Z]{4}\d{12}$")
NUMBER_RE = re.compile(r"^(?P<type>[A-Z][A-Z().\-\s]*?)\s*[/\s]\s*(?P<no>\d{1,7})\s*/\s*(?P<year>\d{4})$")
WORD_RE = re.compile(r"[0-9A-Za-z]+")
WEIGHTS = {"party": "A", "advocate": "B", "text": "AB"}
LIKE_ESCAPE = "\\"


class CaseFilterError(ValueError):
    """A bad filter value (HTTP 400 with the message)."""


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


@dataclass(frozen=True)
class CaseFilters:
    """Decision 1: the shared filters, already validated and normalised by `parse`."""

    q: str | None = None
    listed_from: date | None = None
    listed_to: date | None = None
    court_no: str | None = None
    bench: str | None = None
    next_from: date | None = None
    next_to: date | None = None
    case_type: str | None = None
    year: int | None = None
    case_status: str | None = None
    owner: str | None = None
    parsed: ParsedQuery | None = field(default=None, compare=False, repr=False)

    @property
    def is_empty(self) -> bool:
        return all(getattr(self, f.name) is None for f in fields(self) if f.name != "parsed")

    def without_q(self) -> CaseFilters:
        return replace(self, q=None, parsed=None)


NAMES = tuple(f.name for f in fields(CaseFilters) if f.name != "parsed")
EMPTY = CaseFilters()


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


def normalise_bench(text: str | None) -> str:
    """Upper-cased with white space collapsed (the same as the SQL side of the bench condition)."""
    return re.sub(r"\s+", " ", (text or "").upper()).strip()


def like_escape(text: str) -> str:
    """LIKE wildcards in user input matched literally (escape character `\\`)."""
    return (
        text.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )


def parse_query(q: str | None, field_: str | None = "auto") -> ParsedQuery:
    raw = (q or "").strip()
    if len(raw) < MIN_QUERY:
        raise CaseFilterError(f"q is at least {MIN_QUERY} characters")
    f = (field_ or "auto").lower()
    if f not in FIELDS:
        raise CaseFilterError("field is one of " + ", ".join(FIELDS))
    upper = raw.upper()
    if f == "cnr":
        if not CNR_RE.match(upper):
            raise CaseFilterError("not a CNR: four letters and twelve digits")
        return ParsedQuery("cnr", raw, "cnr", cnr=upper)
    if f == "number":
        parsed = _number(raw, upper)
        if parsed is None:
            raise CaseFilterError("not a case number: <type> <no>/<year> or <type>/<no>/<year>")
        return parsed
    if f in WEIGHTS:
        words = words_of(raw)
        if not words:
            raise CaseFilterError("q has no searchable word")
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
        raise CaseFilterError("q has no searchable word")
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


def _text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _date(name: str, value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise CaseFilterError(f"{name} is a date (YYYY-MM-DD)") from exc


def parse_case_status(value: Any) -> str | None:
    text = _text(value)
    if text is None or not text.strip():
        return None
    v = text.strip().lower()
    if v not in CASE_STATUSES:
        raise CaseFilterError("case_status is one of " + ", ".join(CASE_STATUSES))
    return v


def parse_office_code(value: Any) -> str | None:
    text = _text(value)
    if text is None or not text.strip():
        return None
    return text.strip().upper()


def parse(
    *,
    q: Any = None,
    listed_from: Any = None,
    listed_to: Any = None,
    court_no: Any = None,
    bench: Any = None,
    next_from: Any = None,
    next_to: Any = None,
    case_type: Any = None,
    year: Any = None,
    case_status: Any = None,
    owner: Any = None,
) -> CaseFilters:
    """Decision 7: trims, upper-cases codes, normalises the bench text, validates, parses `q` once. A blank
    value is no filter, except a case type of white space only (an empty type)."""
    lf, lt = _date("listed_from", listed_from), _date("listed_to", listed_to)
    if lf is not None and lt is not None and lf > lt:
        raise CaseFilterError("listed_from is after listed_to")
    nf, nt = _date("next_from", next_from), _date("next_to", next_to)
    if nf is not None and nt is not None and nf > nt:
        raise CaseFilterError("next_from is after next_to")
    yr: int | None = None
    if year is not None and year != "":
        try:
            yr = int(year)
        except (TypeError, ValueError) as exc:
            raise CaseFilterError("year is a number") from exc
        if not (MIN_YEAR <= yr <= MAX_YEAR):
            raise CaseFilterError(f"year is between {MIN_YEAR} and {MAX_YEAR}")
    q_text = (_text(q) or "").strip() or None
    parsed = parse_query(q_text) if q_text is not None else None
    bench_text: str | None = None
    if _text(bench) is not None and _text(bench).strip():
        bench_text = normalise_bench(_text(bench))
        if not (MIN_BENCH <= len(bench_text) <= MAX_BENCH):
            raise CaseFilterError(f"bench is {MIN_BENCH} to {MAX_BENCH} characters")
    court: str | None = None
    if _text(court_no) is not None and _text(court_no).strip():
        court = _text(court_no).strip()
        if len(court) > MAX_COURT_NO:
            raise CaseFilterError(f"court_no is at most {MAX_COURT_NO} characters")
    ctype: str | None = None
    if _text(case_type) is not None and _text(case_type) != "":
        ctype = _text(case_type).strip()
        if not compact(ctype):
            raise CaseFilterError("case_type is empty")
    return CaseFilters(
        q=q_text,
        listed_from=lf,
        listed_to=lt,
        court_no=court,
        bench=bench_text,
        next_from=nf,
        next_to=nt,
        case_type=ctype,
        year=yr,
        case_status=parse_case_status(case_status),
        owner=parse_office_code(owner),
        parsed=parsed,
    )


def with_legacy(f: CaseFilters, *, status: str | None = None, office: str | None = None) -> CaseFilters:
    """Decision 2: the old names `status` (= `case_status`) and `office` (= `owner`) where they meant the same
    thing; both names with different values is an error."""
    st = parse_case_status(status)
    if st is not None:
        if f.case_status is not None and f.case_status != st:
            raise CaseFilterError("status and case_status differ")
        f = replace(f, case_status=st)
    off = parse_office_code(office)
    if off is not None:
        if f.owner is not None and f.owner != off:
            raise CaseFilterError("office and owner differ")
        f = replace(f, owner=off)
    return f


def department_code(session: Session, name: str, code: str | None):
    """The department named by a filter code, or `CaseFilterError` "... is not a department"."""
    if code is None:
        return None
    office = find_office(session, code)
    if office is None or not is_department(office):
        raise CaseFilterError(f"{name} {code!r} is not a department")
    return office


# ------------------------------------------------------------------------------------------------ SQL pieces


def compact_sql(col):
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


def number_condition(session: Session, p: ParsedQuery, case=Case):
    printed = f"{p.type_compact}/{p.reg_no}/{p.reg_year}"
    conds = [
        compact_sql(case.case_no_text) == printed,
        compact_sql(case.filing_no_text) == printed,
        and_(
            compact_sql(case.case_type_text) == p.type_compact,
            case.reg_no == p.reg_no,
            case.reg_year == p.reg_year,
        ),
    ]
    types = matching_case_types(session, p.type_compact)
    if types:
        conds.append(
            and_(
                case.case_type_id.in_([ct.id for ct in types]),
                case.reg_no == p.reg_no,
                case.reg_year == p.reg_year,
            )
        )
        # an alias also finds the printed number under the master's short name (provisional cases)
        by_short = sorted(
            {f"{compact(ct.short_name)}/{p.reg_no}/{p.reg_year}" for ct in types if ct.short_name}
        )
        if by_short:
            conds.append(compact_sql(case.case_no_text).in_(by_short))
    return or_(*conds)


def query_condition(session: Session, p: ParsedQuery, case=Case) -> ColumnElement[bool]:
    """The `q` condition of a parsed query."""
    if p.kind == "id":
        return case.id == p.id
    if p.kind == "ref_no":
        return case.ref_no == p.ref_no
    if p.kind == "cnr":
        return case.cnr == p.cnr
    if p.kind == "number":
        return number_condition(session, p, case)
    return case.search_vector.op("@@")(func.to_tsquery("simple", p.tsquery))


def text_rank(p: ParsedQuery | None, case=Case):
    """Search's relevance for word queries (None for the other kinds)."""
    if p is None or p.kind != "text":
        return None
    return func.ts_rank(case.search_vector, func.to_tsquery("simple", p.tsquery))


def case_type_condition(session: Session, case_type: str, case=Case):
    t = compact(case_type)
    if not t:
        raise CaseFilterError("case_type is empty")
    cond = compact_sql(case.case_type_text) == t
    ids = case_type_ids(session, t)
    if ids:
        cond = cond | case.case_type_id.in_(ids)
    return cond


def owner_condition(session: Session, owner: str, case=Case):
    dept = department_code(session, "owner", owner)
    return exists().where(
        CaseOwnership.case_id == case.id,
        CaseOwnership.office_id == dept.id,
        CaseOwnership.role == OwnershipRole.PRIMARY,
        CaseOwnership.status == OwnershipStatus.ACTIVE,
    )


def bench_sql(col):
    """upper(regexp_replace(col, '\\s+', ' ', 'g')) — the entry's bench text normalised as `normalise_bench`
    (leading and trailing white space does not matter for "contains")."""
    return func.upper(
        func.regexp_replace(col, literal_column(r"'\s+'"), literal_column("' '"), literal_column("'g'"))
    )


def listing_condition(
    listed_from: date | None,
    listed_to: date | None,
    court_no: str | None = None,
    bench: str | None = None,
    case=Case,
):
    """Decision 4: one EXISTS over the case's cause-list entries with every given part (date range, court,
    bench) on the same entry; None when no part is given."""
    if listed_from is None and listed_to is None and court_no is None and bench is None:
        return None
    conds = [CauselistEntry.case_id == case.id, CURRENT_LIST]
    if listed_from is not None:
        conds.append(Causelist.list_date >= listed_from)
    if listed_to is not None:
        conds.append(Causelist.list_date <= listed_to)
    if court_no is not None:
        conds.append(func.trim(CauselistEntry.court_no) == court_no.strip())
    if bench is not None:
        pattern = "%" + like_escape(normalise_bench(bench)) + "%"
        conds.append(bench_sql(CauselistEntry.bench_text).like(literal(pattern), escape=LIKE_ESCAPE))
    return exists(
        select(1)
        .select_from(CauselistEntry)
        .join(Causelist, Causelist.id == CauselistEntry.causelist_id)
        .where(and_(*conds))
    )


def conditions(session: Session, f: CaseFilters | None, case=Case) -> list[ColumnElement[bool]]:
    """Every condition of the filters over `case` (an entity or alias), to be ANDed with the list's own rules;
    an empty list for no filter."""
    if f is None or f.is_empty:
        return []
    out: list[ColumnElement[bool]] = []
    if f.q is not None:
        out.append(query_condition(session, f.parsed or parse_query(f.q), case))
    listed = listing_condition(f.listed_from, f.listed_to, f.court_no, f.bench, case)
    if listed is not None:
        out.append(listed)
    if f.next_from is not None:
        out.append(case.next_hearing_date >= f.next_from)
    if f.next_to is not None:
        out.append(case.next_hearing_date <= f.next_to)
    if f.case_type is not None:
        out.append(case_type_condition(session, f.case_type, case))
    if f.year is not None:
        out.append(case.reg_year == f.year)
    if f.case_status is not None:
        out.append(case.status == CaseStatus(f.case_status))
    if f.owner is not None:
        out.append(owner_condition(session, f.owner, case))
    return out
