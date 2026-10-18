"""Design `safety-fixes`, decisions 12-14: an advocate court search stores the first `NAPIX_ADVOCATE_STORE_NOW` new
cases in the request and queues the rest as `search_rows` rows (one per response that carries them), which the
background handler stores without a NAPIX call and idempotently; over `NAPIX_ADVOCATE_STORE_MAX` nothing more is
stored, the answer and the audit row say so, and every response stays verbatim."""

from __future__ import annotations

import sqlalchemy as sa

from aslms.domain.cases import Case
from aslms.domain.ops import FetchKind, FetchLane, FetchQueueItem, FetchStatus
from aslms.services import court_search
from tests.db.conftest import sample
from tests.db.test_court_search import api, audits, count, login, types  # noqa: F401 — fixtures

ADV_SAMPLE = "advocate_name_2026-10-18-p1.json"


def _first(n: int) -> dict:
    data = sample(ADV_SAMPLE)
    keys = list(data["casenos"])[:n]
    data["casenos"] = {f"case{i}": data["casenos"][k] for i, k in enumerate(keys, start=1)}
    return data


def _search_rows(world) -> list[FetchQueueItem]:
    with world.Session() as s:
        return list(
            s.scalars(sa.select(FetchQueueItem).where(FetchQueueItem.kind == FetchKind.SEARCH_ROWS)).all()
        )


def test_advocate_search_stores_first_n_and_queues_rest(api, world, types):  # noqa: F811
    api.settings.napix_advocate_store_now = 25
    data = _first(30)
    cnrs = [row["cino"] for row in data["casenos"].values()]
    assert len(set(cnrs)) == 30
    api.gw.responses = [lambda p, q, r: api.gw.envelope(data)] * 2 + api.gw.responses
    r = api.post(
        "/cases/search-court",
        json={"kind": "advocate", "name": "P J SAIKIA", "reg_year": 2025, "pend_disp": "both"},
        headers=login(api, "edu_admin"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["created"], body["court_cases"], body["queued"], body["not_stored"]) == (25, 30, 5, 0)
    assert {i["case"]["cnr"] for i in body["items"]} == set(cnrs[:25])
    assert count(world, "cases") == 25 and body["calls"] == 2
    rows = _search_rows(world)
    assert len(rows) == 2  # one per response ("both": P and D)
    edu_admin = world.users["edu_admin"].id
    assert all(
        x.lane == FetchLane.REQUEST
        and x.priority == 30
        and x.requested_by == edu_admin
        and x.status == FetchStatus.PENDING
        for x in rows
    )
    with world.Session() as s:
        ids = set(
            s.execute(sa.text("select id::text from napix_responses where api like 'hc-advocate%'")).scalars()
        )
    assert {x.ref for x in rows} == ids
    rec = audits(world, "case.search_court")[-1].after
    assert (rec["court_cases"], rec["queued"], rec["not_stored"], rec["created"]) == (30, 5, 0, 25)
    # the background handler stores the remaining 5 without a call; the second row finds them held
    seen = len(api.gw.seen)
    out = court_search.run_store_search_rows(world.Session)
    assert out == {"done": 2, "skipped": 0, "failed": 0}
    assert len(api.gw.seen) == seen  # no NAPIX call
    assert count(world, "cases") == 30
    rows = _search_rows(world)
    assert all(x.status == FetchStatus.DONE for x in rows)
    assert sorted(x.result["stored"] for x in rows) == [0, 5]
    with world.Session() as s:
        stored = s.scalars(sa.select(Case).where(Case.cnr.in_(cnrs[25:]))).all()
        assert len(stored) == 5 and all(c.last_full_refresh_at is None for c in stored)
        # a second run of the handler creates nothing (idempotent)
        again = court_search.store_response_rows(s, rows[0].ref)
        s.commit()
    assert again == {"stored": 0, "held": 30, "unmatched": 0}
    assert count(world, "cases") == 30
    assert court_search.run_store_search_rows(world.Session) == {"done": 0, "skipped": 0, "failed": 0}


def test_advocate_search_over_cap_stores_first_n_only(api, world, types):  # noqa: F811
    api.settings.napix_advocate_store_now = 25
    api.settings.napix_advocate_store_max = 25
    r = api.post(
        "/cases/search-court",
        json={"kind": "advocate", "name": "SAIKIA", "reg_year": 2025},
        headers=login(api, "edu_admin"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["created"], body["court_cases"], body["queued"], body["not_stored"]) == (25, 36, 0, 11)
    assert len(body["items"]) == 25 and count(world, "cases") == 25
    assert _search_rows(world) == []
    rec = audits(world, "case.search_court")[-1].after
    assert (rec["court_cases"], rec["queued"], rec["not_stored"], rec["created"]) == (36, 0, 11, 25)
    with world.Session() as s:  # nothing is lost: the response is kept verbatim
        payload = s.execute(
            sa.text("select payload from napix_responses where api = 'hc-advocate-name-api/advocatename'")
        ).scalar()
    assert payload == sample(ADV_SAMPLE)


def test_advocate_search_lists_held_cases_within_the_cap(api, world, types):  # noqa: F811
    """Held cases among the first STORE_MAX CNRs are listed (not counted as new); new ones beyond STORE_NOW wait."""
    api.settings.napix_advocate_store_now = 1
    headers = login(api, "edu_admin")
    data = _first(4)
    api.gw.responses = [lambda p, q, r: api.gw.envelope(data)] * 2 + api.gw.responses
    first = api.post(
        "/cases/search-court",
        json={"kind": "advocate", "name": "P J SAIKIA", "reg_year": 2025},
        headers=headers,
    ).json()
    assert (first["created"], first["queued"]) == (1, 3)
    second = api.post(
        "/cases/search-court",
        json={"kind": "advocate", "name": "P J SAIKIA", "reg_year": 2025},
        headers=headers,
    ).json()
    # one held + one new stored now; two still queued (the same response row, revived)
    assert (second["created"], second["queued"], len(second["items"])) == (1, 2, 2)
    assert len(_search_rows(world)) == 1


def test_party_search_is_not_capped(api, world, types):  # noqa: F811
    api.settings.napix_advocate_store_now = 1
    r = api.post(
        "/cases/search-court",
        json={"kind": "party", "name": "STATE OF ASSAM", "reg_year": 2024},
        headers=login(api, "edu_admin"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == len(body["items"]) > 1
    assert (body["court_cases"], body["queued"], body["not_stored"]) == (0, 0, 0)
    assert "court_cases" not in audits(world, "case.search_court")[-1].after
