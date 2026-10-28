"""Server sorting of the lists through an allow-list (design `list-search`, decisions 31, 32, 36 and 37).

Each list declares its keys once, as a `SortSpec`: key name -> SQL expressions, type and first direction, plus the
list's default order and a unique tie-breaker. The request only picks a key name from that dict: a column name, an
expression or SQL in `sort` is never read as one, and any value outside the dict is 400 `bad_sort` with the allowed
keys. `dir` without `sort` is `bad_sort`; `sort` without `dir` takes the key's first direction. Blanks go last in
both directions; text keys compare `lower(expr)` then `expr`; the tie-breaker follows the chosen direction, so
paging never repeats or skips a row. A sort only reorders the rows the list's own conditions allow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, func, select

from aslms.domain.cases import Case
from aslms.domain.courts import CaseType
from aslms.services.case_filters import compact_sql

DIRECTIONS = ("asc", "desc")
TYPES = ("text", "number", "date", "case_no")


class ListSortError(ValueError):
    """A sort outside the list's allow-list: HTTP 400 `bad_sort` with `allowed`."""

    code = "bad_sort"

    def __init__(self, message: str, allowed: list[str]) -> None:
        super().__init__(message)
        self.allowed = allowed


@dataclass(frozen=True)
class SortKey:
    name: str
    exprs: tuple[Any, ...]
    type: str = "text"
    first_dir: str = "asc"
    # ordered ascending in both directions, before `exprs` (a case with no number after the numbered ones)
    lead: tuple[Any, ...] = ()


@dataclass(frozen=True)
class SortSpec:
    keys: dict[str, SortKey]
    default: tuple[Any, ...]
    tiebreak: Any

    @property
    def allowed(self) -> list[str]:
        return list(self.keys)


@dataclass(frozen=True)
class Sort:
    key: SortKey
    dir: str

    @property
    def name(self) -> str:
        return self.key.name


def parse_keys(keys: dict[str, str], sort: str | None, dir: str | None) -> tuple[str, str] | None:  # noqa: A002
    """The allow-list rule over key names and their first directions: `(name, direction)`, or None for the list's
    default order. Shared by SQL lists (`parse`) and lists ordered in Python."""
    allowed = list(keys)
    if sort is None:
        if dir:
            raise ListSortError("dir needs a sort", allowed)
        return None
    if sort not in keys:
        raise ListSortError("sort is one of " + ", ".join(allowed), allowed)
    if dir is None or dir == "":
        return sort, keys[sort]
    if dir not in DIRECTIONS:
        raise ListSortError("dir is asc or desc", allowed)
    return sort, dir


def parse(spec: SortSpec, sort: str | None, dir: str | None) -> Sort | None:  # noqa: A002
    """The chosen key from `spec.keys` only; None for the list's default order."""
    picked = parse_keys({k: v.first_dir for k, v in spec.keys.items()}, sort, dir)
    if picked is None:
        return None
    return Sort(spec.keys[picked[0]], picked[1])


def sort_python(
    items: list[Any], value: Any, direction: str, *, tiebreak: Any, text: bool = False
) -> list[Any]:
    """A list held in Python ordered as `order_by` orders SQL: `value(item)` in the direction with blanks last in
    both directions (text by its lower case, then itself), then `tiebreak(item)` in the same direction."""

    def k(item: Any) -> tuple:
        v = value(item)
        if text and v is not None:
            v = (str(v).lower(), str(v))
        return (v is None, v, tiebreak(item))

    present = [i for i in items if value(i) is not None]
    blanks = [i for i in items if value(i) is None]
    present.sort(key=lambda i: k(i)[1:], reverse=direction == "desc")
    blanks.sort(key=lambda i: str(tiebreak(i)), reverse=direction == "desc")
    return present + blanks


def _ordered(expr: Any, direction: str) -> Any:
    return expr.asc().nulls_last() if direction == "asc" else expr.desc().nulls_last()


def order_by(spec: SortSpec, sort: Sort | None) -> list[Any]:
    """The ORDER BY of the list: its default order plus the tie-breaker, or the chosen key (each expression in the
    direction, blanks last; text by lower then value) then the tie-breaker in the same direction."""
    if sort is None:
        return [*spec.default, spec.tiebreak.asc()]
    out: list[Any] = [expr.asc() for expr in sort.key.lead]
    for expr in sort.key.exprs:
        if sort.key.type == "text":
            out.append(_ordered(func.lower(expr), sort.dir))
        out.append(_ordered(expr, sort.dir))
    out.append(spec.tiebreak.asc() if sort.dir == "asc" else spec.tiebreak.desc())
    return out


def case_no_exprs(case: Any = Case) -> tuple[ColumnElement, ...]:
    """Decision 37: the compact case type (the master's short name, else the case's type text), then `reg_no`, then
    `reg_year`, then the id. The master is read through a correlated subquery, so no list needs its own join."""
    short = select(CaseType.short_name).where(CaseType.id == case.case_type_id).scalar_subquery()
    return (
        compact_sql(func.coalesce(short, case.case_type_text)),
        case.reg_no,
        case.reg_year,
        case.id,
    )


def case_no_key(case: Any = Case, name: str = "case_no") -> SortKey:
    """The `case_no` key: blanks (no registration number) after the numbered cases in both directions."""
    exprs = case_no_exprs(case)
    # the type compares as plain upper-case text (already folded), so it is a "case_no" key, not "text"
    return SortKey(name, exprs[:3], type="case_no", first_dir="asc", lead=(case.reg_no.is_(None),))
