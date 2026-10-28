"""Court Search's search and sort (design list-search, decision 15): Names Searched matches the name and the
department codes and never shows another department's term; a name's Cases Found takes the case search, which only
narrows; every sort pages stably; `bad_sort` and `bad_q`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from aslms.domain.ownership import DiscoveryHit, DiscoveryTerm
from aslms.services.cases import refresh_search_vector
from tests.db.test_api_discovery import _setup, api, login  # noqa: F401  (the `api` fixture)
from tests.db.world import make_case

TERMS = "/admin/discovery/terms"


def _more_terms(api, world) -> None:  # noqa: F811
    """Four more EDU names with last searches and found counts that tie, so the tie-breaker matters."""
    edu = login(api, "edu_admin")
    for name in ("Bhaskar Das", "Dipen Nath", "Bijoy Roy", "Hemanta Deka"):
        r = api.post("/admin/keywords", json={"keyword": name, "office_code": "EDU"}, headers=edu)
        assert r.status_code == 201, r.text
    base = datetime(2026, 10, 1, tzinfo=UTC)
    with world.Session() as s:
        for i, t in enumerate(s.scalars(sa.select(DiscoveryTerm).order_by(DiscoveryTerm.term))):
            t.last_searched_at = None if i % 3 == 0 else base + timedelta(days=i % 2)
            t.cases_found = i % 2
        s.commit()


def test_terms_q_matches_the_name_and_stays_in_scope(api, world):  # noqa: F811
    edu, health, terms, refs = _setup(api, world)
    _more_terms(api, world)
    r = api.get(TERMS, params={"q": "saikia"}, headers=edu)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [i["term"] for i in body["items"]] == ["PRITAM SAIKIA"]
    assert body["total"] == 1 and body["total_all"] == 5
    assert api.get(TERMS, headers=edu).json()["total_all"] is None
    # a department code matches too
    assert api.get(TERMS, params={"q": "edu"}, headers=edu).json()["total"] == 5
    # another department's term never appears, under any sort
    for sort in (None, "name", "last_searched", "cases_found"):
        for dir_ in (None, "asc", "desc"):
            if sort is None and dir_:
                continue
            params = {"q": "anil", **({"sort": sort} if sort else {}), **({"dir": dir_} if dir_ else {})}
            r = api.get(TERMS, params=params, headers=edu)
            assert r.status_code == 200 and r.json()["items"] == [] and r.json()["total_all"] == 5, params
            r = api.get(TERMS, params={k: v for k, v in params.items() if k != "q"}, headers=edu)
            assert "ANIL BORA" not in [i["term"] for i in r.json()["items"]]
    assert [
        i["term"] for i in api.get(TERMS, params={"q": "anil"}, headers=login(api, "root")).json()["items"]
    ] == ["ANIL BORA"]


@pytest.mark.parametrize("dir_", ["asc", "desc"])
@pytest.mark.parametrize("sort", ["name", "last_searched", "cases_found"])
def test_terms_sort_pages_stably(api, world, sort, dir_):  # noqa: F811
    edu, *_ = _setup(api, world)
    _more_terms(api, world)
    full = api.get(TERMS, params={"sort": sort, "dir": dir_}, headers=edu).json()
    walked = []
    for offset in range(0, 6, 3):
        r = api.get(TERMS, params={"sort": sort, "dir": dir_, "limit": 3, "offset": offset}, headers=edu)
        walked.extend(i["id"] for i in r.json()["items"])
    assert walked == [i["id"] for i in full["items"]] and len(set(walked)) == 5
    key = {"name": "term", "last_searched": "last_searched_at", "cases_found": "cases_found"}[sort]
    values = [i[key] for i in full["items"] if i[key] is not None]
    assert values == sorted(values, reverse=dir_ == "desc")
    blanks = [i[key] is None for i in full["items"]]
    assert blanks == sorted(blanks)  # blanks last in both directions


def _found(world, terms) -> dict[str, str]:
    """Four more cases found by EDU's name, with words, numbers and years to search and sort by."""
    with world.Session() as s:
        made = {
            "nine": make_case(s, pet="GOLAP BORUAH", case_no="WP(C)/9/2025"),
            "ten": make_case(s, pet="MRINAL HAZARIKA", case_no="WP(C)/10/2025"),
            "wa": make_case(s, pet="GOLAP KALITA", case_no="WA/1/2024"),
            "none": make_case(s, pet="NO NUMBER", case_no="WP(C)/77/2023"),
        }
        made["nine"].case_type_text, made["nine"].reg_no, made["nine"].reg_year = "WP(C)", 9, 2025
        made["ten"].case_type_text, made["ten"].reg_no, made["ten"].reg_year = "WP(C)", 10, 2025
        made["wa"].case_type_text, made["wa"].reg_no, made["wa"].reg_year = "WA", 1, 2024
        base = datetime(2026, 10, 1, tzinfo=UTC)
        for i, case in enumerate(made.values()):
            s.add(
                DiscoveryHit(
                    term_id=terms["PRITAM SAIKIA"],
                    case_id=case.id,
                    reg_year=2023 + i % 2,
                    last_found_at=base + timedelta(hours=i % 2),
                )
            )
        refresh_search_vector(s, [c.id for c in made.values()])
        s.commit()
        return {k: v.ref_no for k, v in made.items()}


def test_term_cases_q_only_narrows(api, world):  # noqa: F811
    edu, health, terms, refs = _setup(api, world)
    found = _found(world, terms)
    path = f"{TERMS}/{terms['PRITAM SAIKIA']}/cases"
    everything = {i["case"]["ref_no"] for i in api.get(path, headers=edu).json()["items"]}
    assert len(everything) == 7
    for q, expected in (
        ("golap", {found["nine"], found["wa"]}),
        ("WP(C) 10/2025", {found["ten"]}),
        (found["wa"], {found["wa"]}),
    ):
        r = api.get(path, params={"q": q}, headers=edu)
        assert r.status_code == 200, r.text
        got = {i["case"]["ref_no"] for i in r.json()["items"]}
        assert got == expected and got <= everything and r.json()["total_all"] == 7, q
    # the CNR of a case this name did not find answers nothing
    with world.Session() as s:
        stranger = make_case(s, pet="GOLAP STRANGER")
        refresh_search_vector(s, [stranger.id])
        s.commit()
        cnr = stranger.cnr
    r = api.get(path, params={"q": cnr}, headers=edu)
    assert r.status_code == 200 and r.json()["items"] == [] and r.json()["total"] == 0
    # another department's term stays 404, with or without a search
    other = f"{TERMS}/{terms['ANIL BORA']}/cases"
    assert api.get(other, params={"q": "golap"}, headers=edu).status_code == 404
    r = api.get(path, params={"q": "go"}, headers=edu)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_q"


@pytest.mark.parametrize("dir_", ["asc", "desc"])
@pytest.mark.parametrize("sort", ["last_found", "case_no", "year"])
def test_term_cases_sort_pages_stably(api, world, sort, dir_):  # noqa: F811
    edu, health, terms, refs = _setup(api, world)
    found = _found(world, terms)
    path = f"{TERMS}/{terms['PRITAM SAIKIA']}/cases"
    full = [
        i["case"]["ref_no"]
        for i in api.get(path, params={"sort": sort, "dir": dir_}, headers=edu).json()["items"]
    ]
    walked = []
    for offset in range(0, 9, 3):
        r = api.get(path, params={"sort": sort, "dir": dir_, "limit": 3, "offset": offset}, headers=edu)
        walked.extend(i["case"]["ref_no"] for i in r.json()["items"])
    assert walked == full and len(set(walked)) == 7
    if sort == "case_no":
        numbered = [r for r in full if r in (found["nine"], found["ten"], found["wa"])]
        expected = [found["wa"], found["nine"], found["ten"]]
        assert numbered == (expected if dir_ == "asc" else list(reversed(expected)))
        # the cases with no registration number come after the numbered ones in both directions
        assert full[:3] == numbered


def test_bad_sort(api, world):  # noqa: F811
    edu, health, terms, refs = _setup(api, world)
    for path, allowed in (
        (TERMS, ["name", "last_searched", "cases_found"]),
        (f"{TERMS}/{terms['PRITAM SAIKIA']}/cases", ["last_found", "case_no", "year"]),
    ):
        for params in ({"sort": "term"}, {"dir": "asc"}, {"sort": allowed[0], "dir": "sideways"}):
            r = api.get(path, params=params, headers=edu)
            assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_sort", (path, params, r.text)
            assert r.json()["detail"]["allowed"] == allowed
    r = api.get(TERMS, params={"q": "x"}, headers=edu)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_q"
