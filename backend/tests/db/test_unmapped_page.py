"""Recommended From Cause Lists lists every unmapped code (design list-search, decisions 9-12 and 39):
`GET /admin/counsel-codes/unmapped/page` pages every code once in each sort, by a cursor that carries the sort,
searches the compact code, keeps partial matches scoped and leaves the old endpoint unchanged."""

from __future__ import annotations

from datetime import date

import pytest

from aslms.domain.cases import AdvocateSide, CaseAdvocate
from aslms.domain.ownership import CounselCode
from aslms.services import matching
from aslms.services.list_search import ListSearchError
from tests.db.test_api_inbox import api, login  # noqa: F401  (the `api` fixture)
from tests.db.test_case_visibility import entry_with_codes
from tests.db.world import make_case

N_LISTED = 250
ONLY_DETAILS = ["AD, ONLY ONE", "AD, ONLY TWO", "AD, ONLY THREE"]
PAGE = "/admin/counsel-codes/unmapped/page"


def _code(i: int) -> str:
    return f"SC, X{i:03d}"


def _build(world) -> None:
    """250 printed codes: code i on (i % 7) + 1 entries, its latest list on day (i % 7) + 1 of January 2025; three
    codes only among case advocates (no list date); one code mapped (not listed)."""
    with world.Session() as s:
        case = make_case(s)
        for j in range(7):
            codes = [_code(i) for i in range(N_LISTED) if (i % 7) + 1 > j]
            entry_with_codes(s, case, codes, list_date=date(2025, 1, 1 + j))
        entry_with_codes(s, case, ["SC, MAPPED"], list_date=date(2025, 1, 1))
        s.add(CounselCode(code="SC, MAPPED", office_id=world.offices["EDU"].id))
        for code in ONLY_DETAILS:
            s.add(
                CaseAdvocate(
                    case_id=case.id, side=AdvocateSide.RESPONDENT, name_as_listed=code, counsel_code=code
                )
            )
        s.commit()


def _walk(api, headers, **params) -> tuple[list[dict], dict]:  # noqa: F811
    items, cursor, first = [], None, None
    for _ in range(500):
        query = {**params, **({"cursor": cursor} if cursor else {})}
        r = api.get(PAGE, params=query, headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        first = first or body
        items.extend(body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            return items, first
    raise AssertionError("the cursor never ended")


def _expected(sort: str, direction: str) -> list[str]:
    rows = [(_code(i), (i % 7) + 1, date(2025, 1, (i % 7) + 1)) for i in range(N_LISTED)]
    rows += [(c, 1, None) for c in ONLY_DETAILS]
    if sort == "entries":
        ordered = sorted(rows, key=lambda r: (-r[1], r[0]))
        return [r[0] for r in (ordered if direction == "desc" else list(reversed(ordered)))]
    if sort == "code":
        return sorted((r[0] for r in rows), reverse=direction == "desc")
    dated = sorted((r for r in rows if r[2]), key=lambda r: (r[2], r[0]), reverse=direction == "desc")
    blank = sorted((r for r in rows if r[2] is None), key=lambda r: r[0], reverse=direction == "desc")
    return [r[0] for r in dated + blank]


def test_every_unmapped_code_is_listed(api, world):  # noqa: F811
    _build(world)
    root = login(api, "root")
    items, first = _walk(api, root)
    codes = [i["code"] for i in items]
    assert len(codes) == len(set(codes)) == first["total"] == N_LISTED + len(ONLY_DETAILS)
    assert first["matched"] == first["total"]
    assert "SC, MAPPED" not in codes
    assert codes == _expected("entries", "desc")
    with world.Session() as s:
        old = matching.unmapped_codes(s, limit=10_000)
    assert [u.code for u in old] == codes


@pytest.mark.parametrize("direction", ["asc", "desc"])
@pytest.mark.parametrize("sort", ["entries", "code", "last_seen"])
def test_every_sort_pages_stably(world, sort, direction):
    _build(world)
    with world.Session() as s:
        seen, cursor = [], None
        while True:
            page = matching.unmapped_page(s, sort=sort, dir=direction, limit=7, cursor=cursor)
            seen.extend(u.code for u in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break
    assert seen == _expected(sort, direction)
    if sort == "last_seen":
        assert seen[-len(ONLY_DETAILS) :] == sorted(ONLY_DETAILS, reverse=direction == "desc")


def test_q_matches_the_compact_code(api, world):  # noqa: F811
    _build(world)
    with world.Session() as s:
        s.add(
            CaseAdvocate(
                case_id=make_case(s).id,
                side=AdvocateSide.RESPONDENT,
                name_as_listed="x",
                counsel_code="GA, ASSAM",
            )
        )
        s.add(
            CaseAdvocate(
                case_id=make_case(s).id,
                side=AdvocateSide.RESPONDENT,
                name_as_listed="y",
                counsel_code="DY.S.G.I.",
            )
        )
        s.commit()
    root = login(api, "root")
    r = api.get(PAGE, params={"q": "ga assam"}, headers=root)
    body = r.json()
    assert [i["code"] for i in body["items"]] == ["GA, ASSAM"]
    assert body["matched"] == 1 and body["total"] == N_LISTED + len(ONLY_DETAILS) + 2
    assert [i["code"] for i in api.get(PAGE, params={"q": "DY SGI"}, headers=root).json()["items"]] == [
        "DY.S.G.I."
    ]
    body = api.get(PAGE, params={"q": "x00"}, headers=root).json()
    assert body["matched"] == 10 and len(body["items"]) == 10


def test_cursor_survives_a_mapping_between_pages(api, world):  # noqa: F811
    _build(world)
    root = login(api, "root")
    first = api.get(PAGE, params={"limit": 20}, headers=root).json()
    mapped = first["items"][3]["code"]
    r = api.post("/admin/counsel-codes", json={"code": mapped, "office_code": "EDU"}, headers=root)
    assert r.status_code == 201, r.text
    second = api.get(PAGE, params={"limit": 20, "cursor": first["next_cursor"]}, headers=root).json()
    expected = [c for c in _expected("entries", "desc") if c != mapped]
    got = [i["code"] for i in first["items"]] + [i["code"] for i in second["items"]]
    assert got == [*expected[:3], mapped, *expected[3:39]]
    assert second["total"] == first["total"] - 1


def test_cursor_from_another_sort_is_400(api, world):  # noqa: F811
    _build(world)
    root = login(api, "root")
    cursor = api.get(PAGE, params={"limit": 5}, headers=root).json()["next_cursor"]
    for params in ({"sort": "code"}, {"sort": "entries", "dir": "asc"}):
        r = api.get(PAGE, params={**params, "cursor": cursor}, headers=root)
        assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_cursor", r.text


@pytest.mark.parametrize("sort", ["entries", "code", "last_seen"])
def test_partial_matches_stay_scoped(api, world, sort):  # noqa: F811
    with world.Session() as s:
        s.add(CounselCode(code="SC, EDU", office_id=world.offices["EDU"].id))
        s.add(CounselCode(code="SC, HEALTH", office_id=world.offices["HEALTH"].id))
        case = make_case(s)
        entry_with_codes(s, case, ["SC, EDU, DSE", "SC, HEALTH, DHS"], list_date=date(2026, 10, 23))
        s.commit()
    by_key = {}
    for key in ("root", "edu_admin", "health_admin"):
        r = api.get(PAGE, params={"sort": sort}, headers=login(api, key))
        assert r.status_code == 200, r.text
        by_key[key] = {i["code"]: [p["office_code"] for p in i["partial_matches"]] for i in r.json()["items"]}
    assert by_key["root"] == {"SC, EDU, DSE": ["EDU"], "SC, HEALTH, DHS": ["HEALTH"]}
    assert by_key["edu_admin"] == {"SC, EDU, DSE": ["EDU"], "SC, HEALTH, DHS": []}
    assert by_key["health_admin"] == {"SC, EDU, DSE": [], "SC, HEALTH, DHS": ["HEALTH"]}


def test_requires_admin_counsel_codes(api, world):  # noqa: F811
    assert api.get(PAGE, headers=login(api, "edu_off1")).status_code == 403


def test_bad_cursor_is_400(api, world):  # noqa: F811
    for cursor in ("not-a-cursor", "W10", "WyJlbnRyaWVzIiwiZGVzYyIsIng5IiwiQSJd"):
        r = api.get(PAGE, params={"cursor": cursor}, headers=login(api, "root"))
        assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_cursor", (cursor, r.text)
    with pytest.raises(ListSearchError):
        matching.decode_cursor("e30", "entries", "desc")


def test_bad_q_is_400(api, world):  # noqa: F811
    root = login(api, "root")
    for q in ("a", "x" * 101):
        r = api.get(PAGE, params={"q": q}, headers=root)
        assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_q", r.text


def test_bad_sort_is_400(api, world):  # noqa: F811
    root = login(api, "root")
    for params in (
        {"sort": "raw_sql"},
        {"sort": "entries; drop table cases"},
        {"dir": "asc"},
        {"sort": "code", "dir": "up"},
    ):
        r = api.get(PAGE, params=params, headers=root)
        assert r.status_code == 400, r.text
        assert r.json()["detail"]["code"] == "bad_sort"
        assert r.json()["detail"]["allowed"] == ["entries", "code", "last_seen"]


def test_old_endpoint_unchanged(api, world):  # noqa: F811
    _build(world)
    root = login(api, "root")
    r = api.get("/admin/counsel-codes/unmapped", params={"limit": 100}, headers=root)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list) and len(body) == 100
    assert [i["code"] for i in body] == _expected("entries", "desc")[:100]
    assert set(body[0]) == {"code", "entries", "last_listed", "example_case_ref", "partial_matches"}
    assert body[0]["entries"] == 7 and body[0]["last_listed"] == "2025-01-07"
    page = api.get(PAGE, params={"limit": 100}, headers=root).json()
    assert page["items"] == body
