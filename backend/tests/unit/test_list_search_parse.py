"""The shared list `q` (design list-search, decisions 3 and 6): length, words, literal wildcards and the five date
forms."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import Column, Date, DateTime, MetaData, String, Table, select
from sqlalchemy.dialects import postgresql

from aslms.services import list_search
from aslms.services.list_search import ListSearchError

T = Table(
    "t",
    MetaData(),
    Column("name", String),
    Column("code", String),
    Column("day", Date),
    Column("at", DateTime(timezone=True)),
)


def _sql(cond) -> str:
    return str(
        select(T.c.name)
        .where(cond)
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def test_empty_is_none():
    assert list_search.parse(None) is None
    assert list_search.parse("") is None
    assert list_search.parse("   ") is None


@pytest.mark.parametrize("q", ["a", " b ", "x" * 101])
def test_length_is_bad_q(q):
    with pytest.raises(ListSearchError) as e:
        list_search.parse(q)
    assert e.value.code == "bad_q"


def test_two_and_hundred_characters_are_fine():
    assert list_search.parse("SC").words == ("SC",)
    assert list_search.parse("x" * 100).raw == "x" * 100


def test_words_split_on_white_space_at_most_eight_punctuation_kept():
    lq = list_search.parse("  WP(C)  ga, assam one two three four five six seven ")
    assert lq.words == ("WP(C)", "ga,", "assam", "one", "two", "three", "four", "five")
    assert lq.day is None


def test_wildcards_match_literally():
    lq = list_search.parse("50%_off")
    sql = _sql(list_search.condition(lq, text=[T.c.name]))
    # literal binds double the percent signs; the escaped wildcards stay escaped
    assert "50\\%%\\_off" in sql and "ESCAPE" in sql


def test_every_word_must_match_one_column():
    sql = _sql(list_search.condition(list_search.parse("ram kumar"), text=[T.c.name, T.c.code]))
    assert sql.count("ILIKE") == 4 and " AND " in sql


@pytest.mark.parametrize(
    "q", ["12 Oct 2025", "12 october 2025", "12-10-2025", "12/10/2025", "12.10.2025", "2025-10-12"]
)
def test_five_date_forms_give_the_day(q):
    assert list_search.parse(q).day == date(2025, 10, 12)


@pytest.mark.parametrize("q", ["2025", "31-02-2025", "12 Foo 2025", "12-10/2025"])
def test_not_a_date(q):
    assert list_search.parse(q).day is None


def test_a_date_also_matches_date_and_timestamp_columns():
    sql = _sql(
        list_search.condition(
            list_search.parse("12 Oct 2025"), text=[T.c.name], dates=[T.c.day], timestamps=[T.c.at]
        )
    )
    assert "t.day = '2025-10-12'" in sql
    # IST day: 18:30 UTC of the day before to 18:30 UTC of the day
    assert "2025-10-11 18:30:00+00:00" in sql and "2025-10-12 18:30:00+00:00" in sql


def test_no_query_is_true():
    assert _sql(list_search.condition(None, text=[T.c.name])).endswith("WHERE true")


def test_matches_in_python():
    lq = list_search.parse("ram edu")
    assert list_search.matches(lq, ["Ram Kumar", "EDU"])
    assert not list_search.matches(lq, ["Ram Kumar", "HEALTH"])
    assert list_search.matches(list_search.parse("12-10-2025"), ["x"], [date(2025, 10, 12)])
    assert list_search.matches(None, [])
