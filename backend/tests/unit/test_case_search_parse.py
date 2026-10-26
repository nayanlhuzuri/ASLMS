"""`parse_query` auto-detection and `tsquery_text` (design cases-api, decision 5–6): id, ref_no in both forms,
CNR in lower case, case numbers in the printed and spaced forms, text; refusals; the forced fields; the tsquery
holds only word characters and the operators written by the code, whatever the user typed."""

from __future__ import annotations

import uuid

import pytest

from aslms.services.case_search import SearchError, parse_query, tsquery_text, words_of


def test_auto_detects_identifiers():
    u = uuid.uuid4()
    p = parse_query(str(u))
    assert p.kind == "id" and p.id == u and p.match == "id"
    p = parse_query("ASLMS/GHC/CASE/2026/001842")
    assert p.kind == "ref_no" and p.ref_no == "ASLMS/GHC/CASE/2026/001842"
    p = parse_query("aslms-goa-case-2026-001842")
    assert p.kind == "ref_no" and p.ref_no == "ASLMS/GHC/CASE/2026/001842"
    p = parse_query("gahc010129772026")
    assert p.kind == "cnr" and p.cnr == "GAHC010129772026" and p.match == "cnr"


@pytest.mark.parametrize(
    "q, type_compact, no, year",
    [
        ("WP(C)/4326/2025", "WP(C)", 4326, 2025),
        ("WP(C) 4326/2025", "WP(C)", 4326, 2025),
        ("wa 435/2024", "WA", 435, 2024),
        ("I.A.(Civil) 3959 / 2024", "I.A.(CIVIL)", 3959, 2024),
        ("Crl.A./12/2019", "CRL.A.", 12, 2019),
    ],
)
def test_auto_detects_case_numbers(q, type_compact, no, year):
    p = parse_query(q)
    assert p.kind == "number" and p.match == "number"
    assert (p.type_compact, p.reg_no, p.reg_year) == (type_compact, no, year)


def test_auto_falls_back_to_text():
    p = parse_query("State of Assam")
    assert p.kind == "text" and p.words == ["State", "of", "Assam"] and p.weights == "AB"
    assert p.tsquery == "state:*AB & of:*AB & assam:*AB"
    # digits alone are words too (a year, a number without a type)
    assert parse_query("4326 2025").kind == "text"


def test_refusals():
    with pytest.raises(SearchError):
        parse_query("ab")
    with pytest.raises(SearchError):
        parse_query("   x ")
    with pytest.raises(SearchError):
        parse_query("state", "parties")
    with pytest.raises(SearchError):
        parse_query("not a cnr", "cnr")
    with pytest.raises(SearchError):
        parse_query("state of assam", "number")
    with pytest.raises(SearchError):
        parse_query("!!! ???")


def test_forced_fields():
    p = parse_query("GAHC010129772026", "party")  # looks like a CNR, searched as party words
    assert p.kind == "text" and p.weights == "A" and p.match == "party"
    p = parse_query("kathar", "advocate")
    assert p.kind == "text" and p.weights == "B" and p.match == "advocate"
    p = parse_query("WP(C)/4326/2025", "text")
    assert p.kind == "text" and p.weights == "AB" and p.words == ["WP", "4326", "2025"]
    p = parse_query("wp(c) 4326/2025", "number")
    assert p.kind == "number" and p.type_compact == "WP(C)"


def test_tsquery_text_is_built_only_from_word_characters():
    assert words_of("x' | !(y) <-> z & a:* or") == ["or"]  # one-letter words dropped
    assert tsquery_text(words_of("x' | !(y) <-> z & a:* or"), "AB") == "or:*AB"
    assert tsquery_text(["Ram", "Kumar"], "A") == "ram:*A & kumar:*A"
    assert tsquery_text(["Ram"], "xyz") == "ram:*AB"  # unknown weights fall back to AB
    assert tsquery_text(["bad word"], "A") == ""  # a non-word never reaches the query
    many = words_of(" ".join(f"w{i}" for i in range(12)))
    assert len(many) == 8
    q = "Robert'); DROP TABLE cases; --"
    assert tsquery_text(words_of(q), "AB") == "robert:*AB & drop:*AB & table:*AB & cases:*AB"
