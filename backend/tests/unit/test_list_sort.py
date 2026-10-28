"""Server sorting through an allow-list (design list-search, decisions 31, 32 and 37)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from aslms.domain.cases import Case
from aslms.services import list_sort
from aslms.services.list_sort import ListSortError, SortKey, SortSpec

SPEC = SortSpec(
    keys={
        "next_hearing": SortKey("next_hearing", (Case.next_hearing_date,), "date", "asc"),
        "year": SortKey("year", (Case.reg_year,), "number", "desc"),
        "title": SortKey("title", (Case.case_type_text,), "text", "asc"),
        "case_no": list_sort.case_no_key(Case),
    },
    default=(Case.next_hearing_date.asc().nulls_last(),),
    tiebreak=Case.id,
)


def _sql(order) -> str:
    return str(select(Case.id).order_by(*order).compile(dialect=postgresql.dialect()))


@pytest.mark.parametrize(
    ("sort", "dir_"),
    [
        ("ref_no", None),
        ("cases.ref_no", None),
        ("id; drop table cases", None),
        ("", None),
        (None, "asc"),
        ("year", "up"),
    ],
)
def test_allow_list_only(sort, dir_):
    with pytest.raises(ListSortError) as e:
        list_sort.parse(SPEC, sort, dir_)
    assert e.value.code == "bad_sort"
    assert e.value.allowed == ["next_hearing", "year", "title", "case_no"]


def test_no_sort_is_the_default_order():
    assert list_sort.parse(SPEC, None, None) is None
    sql = _sql(list_sort.order_by(SPEC, None))
    assert sql.endswith("ORDER BY cases.next_hearing_date ASC NULLS LAST, cases.id ASC")


def test_first_direction_used_without_dir():
    assert list_sort.parse(SPEC, "year", None).dir == "desc"
    assert list_sort.parse(SPEC, "next_hearing", None).dir == "asc"
    assert list_sort.parse(SPEC, "year", "asc").dir == "asc"


def test_tiebreak_follows_the_direction():
    assert _sql(list_sort.order_by(SPEC, list_sort.parse(SPEC, "year", "desc"))).endswith(
        "cases.reg_year DESC NULLS LAST, cases.id DESC"
    )
    assert _sql(list_sort.order_by(SPEC, list_sort.parse(SPEC, "year", "asc"))).endswith(
        "cases.reg_year ASC NULLS LAST, cases.id ASC"
    )


@pytest.mark.parametrize("dir_", ["asc", "desc"])
@pytest.mark.parametrize("key", ["next_hearing", "year", "title", "case_no"])
def test_blanks_last_both_directions(key, dir_):
    order = list_sort.order_by(SPEC, list_sort.parse(SPEC, key, dir_))
    parts = [str(o.compile(dialect=postgresql.dialect())) for o in order]
    # every chosen expression carries NULLS LAST (the tie-breaker and the case-number lead do not need it)
    body = [p for p in parts if not p.startswith("cases.id") and "IS NULL" not in p]
    assert body and all(p.endswith("NULLS LAST") for p in body), parts


def test_text_keys_order_by_lower_then_value():
    sql = _sql(list_sort.order_by(SPEC, list_sort.parse(SPEC, "title", "asc")))
    assert (
        "lower(cases.case_type_text) ASC NULLS LAST, cases.case_type_text ASC NULLS LAST, cases.id ASC" in sql
    )


def test_case_no_exprs():
    exprs = list_sort.case_no_exprs(Case)
    compiled = [str(e.compile(dialect=postgresql.dialect())) for e in exprs]
    assert "upper(regexp_replace(coalesce((SELECT case_types.short_name" in compiled[0]
    assert "cases.case_type_text" in compiled[0]
    assert compiled[1:] == ["cases.reg_no", "cases.reg_year", "cases.id"]
    sql = _sql(list_sort.order_by(SPEC, list_sort.parse(SPEC, "case_no", "desc")))
    # a case with no registration number comes last in both directions
    assert "ORDER BY cases.reg_no IS NULL ASC" in sql
    assert sql.endswith("cases.reg_no DESC NULLS LAST, cases.reg_year DESC NULLS LAST, cases.id DESC")


def test_sort_python_blanks_last_and_tiebreak():
    rows = [(1, None), (2, 5), (3, 7), (4, 5), (5, None)]
    asc = list_sort.sort_python(rows, lambda r: r[1], "asc", tiebreak=lambda r: r[0])
    desc = list_sort.sort_python(rows, lambda r: r[1], "desc", tiebreak=lambda r: r[0])
    assert [r[0] for r in asc] == [2, 4, 3, 1, 5]
    assert [r[0] for r in desc] == [3, 4, 2, 5, 1]
    names = [(1, "beta"), (2, "Alpha"), (3, "alpha")]
    assert [
        r[0] for r in list_sort.sort_python(names, lambda r: r[1], "asc", tiebreak=lambda r: r[0], text=True)
    ] == [
        2,
        3,
        1,
    ]
