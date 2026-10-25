"""`GET /cases/{ref}/custody?order=` and `remarks_shown` (design case-workspace-admin, decisions 14-16 and 23): newest
first with `order=desc`, paged from the newest; `asc` and no `order` unchanged; `remarks_shown` true for a working basis
and a State-wide reader holding `cases.view_private_all`, false for State oversight and the central operator (whose legs
carry no remark); a caller who cannot see the case gets 404."""

from __future__ import annotations

import pytest

from aslms.domain.cases import Case
from aslms.services import custody
from aslms.services.workflow_common import WorkflowError
from tests.db import docs_support as ds
from tests.db import workflow_support as w


@pytest.fixture()
def moved(world):
    """An EDU case claimed and allotted to off1 (legs 1-2), sent off1 -> off2 (leg 3), then off2 -> counsel (leg 4)."""
    with world.Session() as s:
        case = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", case, "edu_off2")
        w.send(s, world, "edu_off2", case, "edu_counsel")
        s.commit()
        return case.id


def _seqs(out) -> list[int]:
    return [leg["seq_no"] for leg in out["legs"]]


def test_desc_is_newest_first_and_pages_from_the_newest(world, moved):
    with world.Session() as s:
        _, user = world.actor(s, "edu_admin")
        case = s.get(Case, moved)
        first = custody.history(s, user, case, order="desc", limit=2)
        assert _seqs(first) == [4, 3]
        assert first["total"] == 4
        rest = custody.history(s, user, case, order="desc", limit=2, offset=2)
        assert _seqs(rest) == [2, 1]


def test_asc_and_default_are_unchanged(world, moved):
    with world.Session() as s:
        _, user = world.actor(s, "edu_admin")
        case = s.get(Case, moved)
        assert _seqs(custody.history(s, user, case)) == [1, 2, 3, 4]
        assert _seqs(custody.history(s, user, case, order="asc")) == [1, 2, 3, 4]


def test_unknown_order_is_refused_by_the_service(world, moved):
    with world.Session() as s:
        _, user = world.actor(s, "edu_admin")
        with pytest.raises(WorkflowError):
            custody.history(s, user, s.get(Case, moved), order="sideways")


def test_remarks_shown_by_basis(world, moved):
    with world.Session() as s:
        case = s.get(Case, moved)
        for key, shown in (
            ("edu_admin", True),
            ("edu_counsel", True),
            ("edu_auditor", True),
            ("root", True),
            ("oversight", False),
            ("central_op", False),
        ):
            _, user = world.actor(s, key)
            out = custody.history(s, user, case, order="desc")
            assert out["remarks_shown"] is shown, key
            if shown:
                assert any(leg["remark"] for leg in out["legs"]), key
            else:
                assert all(leg["remark"] is None for leg in out["legs"]), key


def test_api_order_remarks_shown_404_and_422(world, moved, tmp_path):
    api = ds.make_api(world, tmp_path)
    try:
        h = w.login(api, "edu_admin")
        r = api.get(f"/cases/{moved}/custody", params={"order": "desc", "limit": 3}, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert [leg["seq_no"] for leg in body["legs"]] == [4, 3, 2]
        assert body["remarks_shown"] is True and body["total"] == 4
        r = api.get(f"/cases/{moved}/custody", headers=h)
        assert [leg["seq_no"] for leg in r.json()["legs"]] == [1, 2, 3, 4]
        r = api.get(f"/cases/{moved}/custody", params={"order": "desc"}, headers=w.login(api, "oversight"))
        assert r.status_code == 200 and r.json()["remarks_shown"] is False
        assert all(leg["remark"] is None for leg in r.json()["legs"])
        r = api.get(f"/cases/{moved}/custody", params={"order": "up"}, headers=h)
        assert r.status_code == 422
        r = api.get(f"/cases/{moved}/custody", params={"order": "desc"}, headers=w.login(api, "health_off"))
        assert r.status_code == 404
    finally:
        api.__exit__(None, None, None)
