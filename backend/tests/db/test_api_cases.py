"""The shared case filters on Search (design portal-filters, decisions 1, 2 and 4): `GET /cases` with court and
bench, `GET /cases/search` with the next-hearing range, court and bench, the old names `status` / `office`
accepted as aliases of `case_status` / `owner` (both with different values → 400), and visibility unchanged."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.cases import CaseStatus
from aslms.services import ownership as own
from aslms.services.cases import refresh_search_vector
from tests.db.auth_support import bearer
from tests.db.world import DIVISION_BENCH, OTHER_BENCH, PW, SINGLE_BENCH, USERS, add_listing, make_case

OCT1, OCT2 = date(2026, 10, 1), date(2026, 10, 2)


@pytest.fixture()
def api(world):
    settings = Settings(
        _env_file=None,
        aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters",
        aslms_access_token_minutes=5,
    )
    with TestClient(create_app(settings, world.Session)) as client:
        yield client


def login(api: TestClient, key: str) -> dict:
    return bearer(api, USERS[key][0], PW)


def ids(body) -> list[str]:
    return sorted(str(i["case"]["id"]) for i in body["items"])


@pytest.fixture()
def cases(world):
    """Three EDU-claimed cases with the words FILTER PARTY: `a` listed 1 Oct in court 3 (single bench), next
    hearing 20 Oct; `b` listed 2 Oct in court 5 (division bench with the same judge), disposed; `c` listed 2 Oct in
    court 15 before another bench, next hearing 5 Nov. And `d`, FILTER PARTY too, never claimed (in the pool,
    which the department admin also sees)."""
    with world.Session() as s:
        a = make_case(s, pet="FILTER PARTY ONE", next_hearing=date(2026, 10, 20))
        b = make_case(s, pet="FILTER PARTY TWO", status=CaseStatus.DISPOSED)
        c = make_case(s, pet="FILTER PARTY THREE", next_hearing=date(2026, 11, 5))
        d = make_case(s, pet="FILTER PARTY FOUR")
        add_listing(s, a, OCT1, court_no="3", bench=SINGLE_BENCH)
        add_listing(s, b, OCT2, court_no="5", bench=DIVISION_BENCH)
        add_listing(s, c, OCT2, court_no="15", bench=OTHER_BENCH)
        actor, admin = world.actor(s, "edu_admin")
        for case in (a, b, c):
            own.claim(s, actor, admin, case)
        refresh_search_vector(s, [a.id, b.id, c.id, d.id])
        # the next-hearing filters read the case's one next hearing (design next-date-direct, decision 11)
        from aslms.services import next_hearing

        next_hearing.refresh(s, [a.id, b.id, c.id, d.id])
        s.commit()
        return {k: str(v.id) for k, v in dict(a=a, b=b, c=c, d=d).items()}


def test_list_court_and_bench(api, cases):
    admin = login(api, "edu_admin")

    def got(query):
        r = api.get(f"/cases?{query}", headers=admin)
        assert r.status_code == 200, r.text
        return ids(r.json())

    assert got("") == sorted(cases.values())
    assert got("court_no=5") == [cases["b"]]
    assert got("court_no=15") == [cases["c"]]
    assert got("bench=SAIKIA") == sorted([cases["a"], cases["b"]])  # the division bench too
    assert got("listed_from=2026-10-02&listed_to=2026-10-02&court_no=3") == []
    assert got("listed_from=2026-10-01&listed_to=2026-10-01&court_no=3") == [cases["a"]]
    assert got("bench=saikia&case_status=pending") == [cases["a"]]
    r = api.get("/cases?bench=ab", headers=admin)
    assert r.status_code == 400 and r.json()["detail"] == "bench is 3 to 200 characters"
    # a filter never shows a case the caller does not see
    assert got("q=filter party&owner=EDU") == sorted([cases["a"], cases["b"], cases["c"]])
    assert api.get("/cases?bench=SAIKIA", headers=login(api, "health_admin")).json()["total"] == 0
    assert api.get("/cases?bench=SAIKIA", headers=login(api, "edu_off1")).json()["total"] == 0


def test_search_next_range_court_bench(api, cases):
    admin = login(api, "edu_admin")

    def got(query):
        r = api.get(f"/cases/search?q=filter%20party&{query}", headers=admin)
        assert r.status_code == 200, r.text
        return ids(r.json())

    everyone = sorted(cases.values())
    assert got("") == everyone
    # the one next hearing (design next-date-direct, decision 4): the court's last date stays once passed, so the
    # disposed `b` keeps its cause-list date of 2 Oct
    assert got("next_from=2026-10-01&next_to=2026-10-31") == sorted([cases["a"], cases["b"]])
    assert got("next_from=2026-11-01") == [cases["c"]]
    assert got("court_no=5") == [cases["b"]]
    assert got("bench=PHUKAN") == [cases["c"]]
    assert got("listed_from=2026-10-02&bench=saikia") == [cases["b"]]
    # search summarises every case; a HEALTH reader gets the same matches with visible false
    body = api.get("/cases/search?q=filter%20party&court_no=3", headers=login(api, "health_admin")).json()
    assert ids(body) == [cases["a"]] and body["items"][0]["visible"] is False
    r = api.get("/cases/search?q=filter%20party&next_from=2026-11-02&next_to=2026-11-01", headers=admin)
    assert r.status_code == 400 and r.json()["detail"] == "next_from is after next_to"


def test_owner_and_office_alias_and_conflict_400(api, cases):
    root = login(api, "root")
    edu_owned = sorted([cases["a"], cases["b"], cases["c"]])
    for path in ("/cases?", "/cases/search?q=filter%20party&"):
        assert ids(api.get(f"{path}owner=EDU", headers=root).json()) == edu_owned, path
        assert ids(api.get(f"{path}office=edu", headers=root).json()) == edu_owned, path
        assert ids(api.get(f"{path}office=EDU&owner=EDU", headers=root).json()) == edu_owned, path
        assert api.get(f"{path}owner=HEALTH", headers=root).json()["total"] == 0, path
        r = api.get(f"{path}office=EDU&owner=HEALTH", headers=root)
        assert r.status_code == 400 and r.json()["detail"] == "office and owner differ", path
        r = api.get(f"{path}owner=EDU-DSE", headers=root)
        assert r.status_code == 400 and "is not a department" in r.json()["detail"], path


def test_case_status_alias(api, cases):
    root = login(api, "root")
    for path in ("/cases?", "/cases/search?q=filter%20party&"):
        assert ids(api.get(f"{path}case_status=disposed", headers=root).json()) == [cases["b"]], path
        assert ids(api.get(f"{path}status=disposed", headers=root).json()) == [cases["b"]], path
        r = api.get(f"{path}status=disposed&case_status=pending", headers=root)
        assert r.status_code == 400 and r.json()["detail"] == "status and case_status differ", path
        assert api.get(f"{path}case_status=open", headers=root).status_code == 400, path
