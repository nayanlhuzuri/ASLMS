"""Custody remarks for State-wide readers (design alerts-visibility-roles, decision 16): the card (overview, Files
lists, Custody tab) and the history show the remark to a working basis and to a State-wide reader holding
`cases.view_private_all` (the Auditor and the super admin), never to State oversight or the central operator, who still
see who holds the file, the pending action, the due date and the legs. `sent` keeps the caller's own remarks. And the
department head recalls by default (decision 17)."""

from __future__ import annotations

import pytest

from aslms.domain.cases import Case
from aslms.services import custody
from tests.db import docs_support as ds
from tests.db import workflow_support as w

REMARK = "please act (edu_off1 to edu_counsel)"


@pytest.fixture()
def held(world):
    """An EDU case allotted to off1 and sent by off1 to the EDU standing counsel with a remark."""
    w.widen(world)
    with world.Session() as s:
        case = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", case, "edu_counsel", pending_action_="opinion")
        s.commit()
        return case.id


def _card_and_legs(s, world, key, case_id):
    _, user = world.actor(s, key)
    out = custody.history(s, user, s.get(Case, case_id))
    return out["card"], out["legs"]


def test_card_and_history_hide_remark_from_oversight_and_operator(world, held):
    with world.Session() as s:
        for key in ("oversight", "central_op"):
            card, legs = _card_and_legs(s, world, key, held)
            assert card["remark"] is None, key
            assert card["holder_user"]["full_name"] == "Edu Counsel", key
            assert card["pending_action"] == "opinion", key
            assert len(legs) >= 2 and all(leg["remark"] is None for leg in legs), key
            _, user = world.actor(s, key)
            assert custody.card(s, user, s.get(Case, held))["remark"] is None, key


def test_auditor_and_super_admin_see_remark(world, held):
    with world.Session() as s:
        for key in ("edu_auditor", "root"):
            card, legs = _card_and_legs(s, world, key, held)
            assert card["remark"] == REMARK, key
            assert REMARK in {leg["remark"] for leg in legs}, key


def test_working_basis_still_sees_remark(world, held):
    with world.Session() as s:
        for key in ("edu_admin", "edu_off1", "edu_counsel"):
            card, legs = _card_and_legs(s, world, key, held)
            assert card["remark"] == REMARK, key
            assert REMARK in {leg["remark"] for leg in legs}, key


def test_sent_list_shows_own_remark(world, held):
    with world.Session() as s:
        _, off1 = world.actor(s, "edu_off1")
        rows = custody.sent(s, off1).items
        assert [r["leg"]["remark"] for r in rows] == [REMARK]


def test_custody_api_returns_null_remark_to_oversight(world, held, tmp_path):
    api = ds.make_api(world, tmp_path)
    try:
        r = api.get(f"/cases/{held}/custody", headers=w.login(api, "oversight"))
        assert r.status_code == 200, r.text
        assert r.json()["card"]["remark"] is None
        r = api.get(f"/cases/{held}/custody", headers=w.login(api, "edu_auditor"))
        assert r.json()["card"]["remark"] == REMARK
    finally:
        api.__exit__(None, None, None)


def test_department_head_recalls_by_default(world, held):
    with world.Session() as s:
        _, head = world.actor(s, "edu_head")
        case = s.get(Case, held)
        assert custody.card(s, head, case)["can_recall"] is True
        w.recall(s, world, "edu_head", case)
        assert w.holder(s, case).holder_user_id == world.users["edu_head"].id
        s.rollback()
