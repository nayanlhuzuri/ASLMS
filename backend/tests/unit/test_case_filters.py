"""`case_filters.parse` validation and normalisation (design portal-filters, decisions 1, 2, 4 and 7)."""

from __future__ import annotations

from datetime import date

import pytest

from aslms.services import case_filters
from aslms.services.case_filters import (
    CaseFilterError,
    CaseFilters,
    conditions,
    like_escape,
    parse,
    with_legacy,
)


def test_parse_rejects_reversed_listed_range():
    with pytest.raises(CaseFilterError, match="listed_from is after listed_to"):
        parse(listed_from=date(2026, 10, 2), listed_to=date(2026, 10, 1))
    f = parse(listed_from="2026-10-01", listed_to="2026-10-01")
    assert f.listed_from == f.listed_to == date(2026, 10, 1)
    with pytest.raises(CaseFilterError, match="listed_from is a date"):
        parse(listed_from="1 Oct")


def test_parse_rejects_reversed_next_range():
    with pytest.raises(CaseFilterError, match="next_from is after next_to"):
        parse(next_from=date(2026, 11, 1), next_to=date(2026, 10, 1))
    assert parse(next_from=date(2026, 10, 1)).next_to is None


def test_parse_rejects_year_out_of_range():
    for bad in (1899, 2101, 202):
        with pytest.raises(CaseFilterError, match="year is between 1900 and 2100"):
            parse(year=bad)
    assert parse(year=1900).year == 1900 and parse(year="2025").year == 2025


def test_parse_rejects_unknown_case_status():
    with pytest.raises(CaseFilterError, match="case_status is one of pending, disposed, unknown"):
        parse(case_status="open")
    assert parse(case_status=" Disposed ").case_status == "disposed"


def test_parse_short_q_and_bench():
    with pytest.raises(CaseFilterError, match="q is at least 3 characters"):
        parse(q="ab")
    with pytest.raises(CaseFilterError, match="no searchable word"):
        parse(q="!!! ???")
    with pytest.raises(CaseFilterError, match="bench is 3 to 200 characters"):
        parse(bench="  ab ")
    with pytest.raises(CaseFilterError, match="bench is 3 to 200 characters"):
        parse(bench="x" * 201)
    with pytest.raises(CaseFilterError, match="court_no is at most 20 characters"):
        parse(court_no="1" * 21)
    with pytest.raises(CaseFilterError, match="case_type is empty"):
        parse(case_type="   ")
    f = parse(q="  WP(C) 4326/2025 ", court_no=" 3 ", owner=" fin ")
    assert f.q == "WP(C) 4326/2025" and f.parsed.kind == "number"
    assert f.court_no == "3" and f.owner == "FIN"


def test_bench_normalised_and_wildcards_escaped():
    f = parse(bench="  honourable   mr. justice\tsoumitra saikia ")
    assert f.bench == "HONOURABLE MR. JUSTICE SOUMITRA SAIKIA"
    assert like_escape("50%_a\\b") == "50\\%\\_a\\\\b"
    sql = str(case_filters.listing_condition(None, None, None, "100%_X").compile())
    assert "LIKE" in sql and "ESCAPE" in sql


def test_empty_filters_add_no_condition():
    f = parse(q="", listed_from=None, court_no="", bench=" ", case_type="", year="", case_status="", owner="")
    assert f == CaseFilters() and f.is_empty
    assert conditions(None, f) == [] and conditions(None, None) == []  # type: ignore[arg-type]
    assert not parse(year=2025).is_empty


def test_legacy_names_map_and_conflict():
    assert with_legacy(parse(), status="disposed", office="edu") == parse(case_status="disposed", owner="EDU")
    assert with_legacy(parse(case_status="pending"), status="PENDING").case_status == "pending"
    with pytest.raises(CaseFilterError, match="status and case_status differ"):
        with_legacy(parse(case_status="pending"), status="disposed")
    with pytest.raises(CaseFilterError, match="office and owner differ"):
        with_legacy(parse(owner="EDU"), office="HEALTH")
    with pytest.raises(CaseFilterError):
        with_legacy(parse(), status="open")
