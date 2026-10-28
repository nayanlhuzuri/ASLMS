"""A case list's Words never widen what a caller sees (design list-search, decisions 18 and 26): with `q` set to
another department's case CNR, its number or a party word, that case is not returned, and every answer with `q` is a
subset of the answer without it."""

from __future__ import annotations

from typing import Any

import pytest

from aslms.services import ownership as own
from aslms.services.cases import refresh_search_vector
from tests.db import docs_support as ds
from tests.db import workflow_support as w
from tests.db.alerts_support import recommend
from tests.db.world import make_case

ENDPOINTS = [
    ("edu_off1", "/inbox/mine?view=working"),
    ("edu_off1", "/inbox/mine?view=claimed"),
    ("edu_off1", "/inbox/mine?view=disposed"),
    ("edu_admin", "/inbox/claimed"),
    ("edu_admin", "/inbox/recommended"),
    ("edu_admin", "/inbox/pool"),
    ("edu_admin", "/inbox/transfers"),
    ("edu_off2", "/custody/held?scope=me"),
    ("edu_admin", "/custody/held?scope=owned"),
    ("edu_off1", "/custody/sent"),
    ("edu_off1", "/alerts"),
    ("edu_admin", "/next-dates/review"),
    ("edu_admin", "/cases"),
]


# lists where EDU's own ZEBRA case shows, so the search is seen to find something
FINDS_OWN = {"/inbox/claimed", "/inbox/pool", "/custody/held?scope=me", "/custody/sent", "/cases"}


@pytest.fixture()
def api(world, tmp_path):
    w.widen(world)
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture()
def cases(world) -> dict[str, Any]:
    """EDU's case (ZEBRA EDUCATION, claimed, sent from edu_off1 to edu_off2), an EDU pool case (ZEBRA POOL) and
    HEALTH's claimed and recommended case (ZEBRA HEALTH, WP(C) 4321/2025)."""
    with world.Session() as s:
        edu = w.claimed_case(s, world, case_no="WP(C)/1234/2025")
        edu.petitioner_summary = "ZEBRA EDUCATION"
        w.send(s, world, "edu_off1", edu, "edu_off2")
        pool = make_case(s, pet="ZEBRA POOL")
        recommend(s, world, pool, "EDU", score=0.9)
        health = make_case(s, pet="ZEBRA HEALTH", case_no="WP(C)/4321/2025")
        health.case_type_text, health.reg_no, health.reg_year = "WP(C)", 4321, 2025
        recommend(s, world, health, "HEALTH", score=0.9)
        actor, admin = world.actor(s, "health_admin")
        own.claim(s, actor, admin, health)
        refresh_search_vector(s, [edu.id, pool.id, health.id])
        s.commit()
        return {"health_ref": health.ref_no, "health_cnr": health.cnr}


def _refs(node: Any) -> set[str]:
    """Every `ref_no` anywhere in an answer's items."""
    out: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "ref_no" and isinstance(v, str):
                out.add(v)
            else:
                out |= _refs(v)
    elif isinstance(node, list):
        for v in node:
            out |= _refs(v)
    return out


@pytest.mark.parametrize(("key", "path"), ENDPOINTS)
def test_q_never_reveals_another_departments_case(api, world, cases, key, path):
    headers = w.login(api, key)
    r = api.get(path, headers=headers)
    assert r.status_code == 200, (path, r.text)
    without = _refs(r.json().get("items", r.json()))
    assert cases["health_ref"] not in without
    join = "&" if "?" in path else "?"
    for q in (cases["health_cnr"], "WP(C) 4321/2025", "zebra", "health"):
        r = api.get(f"{path}{join}q={q}", headers=headers)
        assert r.status_code == 200, (path, q, r.text)
        found = _refs(r.json().get("items", r.json()))
        assert cases["health_ref"] not in found, (path, q)
        assert found <= without, (path, q)
        if q == "zebra" and path in FINDS_OWN:
            assert found, path
