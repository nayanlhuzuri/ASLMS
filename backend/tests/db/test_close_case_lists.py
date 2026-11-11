"""Closed cases in the lists, counts, dashboards and the case page flags (design close-case, decisions 15-17 and 20-22):
`held` and the tracking summary leave closed cases out in every scope, the With Me count, a send overtaken by a
closure, the Open / Closed switch of My Cases and Department with the newest closure first and the split counts,
`closed` on every case summary (null when hidden), the Ready to Close attention item, the department block's figures,
the five workflow flags, and the retired stage."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aslms.domain.cases import CaseStatus
from aslms.domain.org import PermissionEffect
from aslms.domain.reference import Permission, Role
from aslms.domain.workflow import CaseStage
from aslms.services import custody, dashboard, inbox, my_cases, stages, workflow_actions
from aslms.services import ownership as own
from aslms.services.reporting_common import ReportConfig
from aslms.services.workflow_common import WorkflowError
from tests.db import closure_support as c
from tests.db import workflow_support as w


@pytest.fixture()
def wide(world):
    return w.widen(world)


def _ids(page) -> list:
    return [i["case"]["id"] for i in page.items]


# ------------------------------------------------------------------------------------------------ custody


def test_closed_leaves_held_every_scope(wide):
    with wide.Session() as s:
        open_case = c.disposed_case(s, wide)
        closed = c.disposed_case(s, wide)
        _, off1 = wide.actor(s, "edu_off1")
        _, head = wide.actor(s, "edu_head")
        edu = wide.office(s, "EDU")
        before = custody.summary_for(s, [edu])[0]["held"]
        c.close(s, wide, "edu_off1", closed)
        assert _ids(custody.held(s, off1, scope="me")) == [open_case.id]
        for scope in ("office", "owned"):
            assert closed.id not in _ids(custody.held(s, head, scope=scope)), scope
        assert custody.summary_for(s, [edu])[0]["held"] == before - 1
        s.rollback()


def test_files_count_excludes_closed(wide):
    with wide.Session() as s:
        c.disposed_case(s, wide)
        closed = c.disposed_case(s, wide)
        _, off1 = wide.actor(s, "edu_off1")
        assert my_cases.mine_counts(s, off1)["files"] == 2
        c.close(s, wide, "edu_off1", closed)
        counts = my_cases.mine_counts(s, off1)
        assert counts["files"] == 1
        assert counts["all_open"] + counts["all_closed"] == counts["all"] and counts["all_closed"] == 1
        s.rollback()


def test_send_overtaken_by_closure_not_still_out(wide):
    with wide.Session() as s:
        case = c.disposed_case(s, wide)
        w.send(s, wide, "edu_off1", case, "edu_off2", pending_action_="examine")
        _, off1 = wide.actor(s, "edu_off1")
        assert _ids(custody.sent(s, off1, still_out=True)) == [case.id]
        c.close(s, wide, "edu_head", case)
        assert _ids(custody.sent(s, off1, still_out=True)) == []
        earlier = custody.sent(s, off1).items
        assert [i["case"]["id"] for i in earlier] == [case.id] and earlier[0]["current"] is False
        s.rollback()


# ------------------------------------------------------------------------------------------------ the inbox


def test_closure_filter_open_closed_all(wide):
    with wide.Session() as s:
        open_case = c.disposed_case(s, wide)
        closed = c.disposed_case(s, wide)
        c.close(s, wide, "edu_off1", closed)
        _, off1 = wide.actor(s, "edu_off1")
        assert set(_ids(my_cases.mine(s, off1, view="all"))) == {open_case.id, closed.id}
        assert _ids(my_cases.mine(s, off1, view="all", closure="open")) == [open_case.id]
        assert _ids(my_cases.mine(s, off1, view="all", closure="closed")) == [closed.id]
        _, head = wide.actor(s, "edu_head")
        claimed = lambda closure: _ids(inbox.claimed(s, head, case_state="all", closure=closure))  # noqa: E731
        assert set(claimed("all")) == {open_case.id, closed.id}
        assert claimed("open") == [open_case.id] and claimed("closed") == [closed.id]
        with pytest.raises(inbox.InboxError):
            my_cases.mine(s, off1, view="all", closure="shut")
        s.rollback()


def test_closed_order_newest_first(wide):
    with wide.Session() as s:
        first = c.disposed_case(s, wide)
        second = c.disposed_case(s, wide)
        c.close(s, wide, "edu_off1", second)  # closed first: the older closure
        s.commit()  # a closure's time is its transaction's
        c.close(s, wide, "edu_off1", first)
        s.commit()
        _, off1 = wide.actor(s, "edu_off1")
        assert _ids(my_cases.mine(s, off1, view="all", closure="closed")) == [first.id, second.id]
        _, head = wide.actor(s, "edu_head")
        assert _ids(inbox.claimed(s, head, case_state="all", closure="closed")) == [first.id, second.id]


def test_counts_split(wide):
    with wide.Session() as s:
        c.disposed_case(s, wide)
        w.claimed_case(s, wide)
        closed = c.disposed_case(s, wide)
        c.close(s, wide, "edu_off1", closed)
        _, head = wide.actor(s, "edu_head")
        [block] = inbox.counts(s, head)["departments"]
        assert (
            block["claimed_open"] + block["claimed_closed"]
            == block["claimed_active"] + block["claimed_disposed"]
        )
        assert block["claimed_closed"] == 1 and block["claimed_open"] == 2
        s.rollback()


def test_summary_closed_null_when_hidden(wide):
    with wide.Session() as s:
        closed = c.disposed_case(s, wide)
        open_case = c.disposed_case(s, wide)
        c.close(s, wide, "edu_off1", closed)
        out = inbox.summaries(s, [closed, open_case], hidden={open_case.id})
        assert out[closed.id]["closed"] is True and out[open_case.id]["closed"] is None
        assert inbox.summaries(s, [open_case])[open_case.id]["closed"] is False
        s.rollback()


# ------------------------------------------------------------------------------------------------ dashboards


def test_ready_to_close_attention(wide):
    with wide.Session() as s:
        ready = c.disposed_case(s, wide)
        w.claimed_case(s, wide)  # pending: no item
        cfg = ReportConfig()
        now = datetime.now(UTC)
        items = dashboard.personal_headline(s, wide.user(s, "edu_off1"), now=now, cfg=cfg)["attention"]
        mine = [i for i in items if i["kind"] == "ready_to_close"]
        assert [i["case"]["id"] for i in mine] == [ready.id]
        assert (
            mine[0]["title"] == "Close this case"
            and mine[0]["detail"] == "Disposed by the court on 20 Oct 2026"
        )
        assert not [i for i in items if i["kind"] == "file_received" and i["case"]["id"] == ready.id]
        # a holder without the function, or from another department, gets no item
        c.set_function(s, wide, "edu_off1", Permission.CASES_CLOSE, PermissionEffect.DENY)
        items = dashboard.personal_headline(s, wide.user(s, "edu_off1"), now=now, cfg=cfg)["attention"]
        assert not [i for i in items if i["kind"] == "ready_to_close"]
        elsewhere = c.disposed_case(s, wide)
        w.send(s, wide, "edu_off1", elsewhere, "health_off", pending_action_="opinion")
        items = dashboard.personal_headline(s, wide.user(s, "health_off"), now=now, cfg=cfg)["attention"]
        assert not [i for i in items if i["kind"] == "ready_to_close"]
        # a closed case is not listed
        c.set_function(s, wide, "edu_off1", Permission.CASES_CLOSE, PermissionEffect.GRANT)
        c.close(s, wide, "edu_off1", ready)
        items = dashboard.personal_headline(s, wide.user(s, "edu_off1"), now=now, cfg=cfg)["attention"]
        assert not [i for i in items if i["kind"] == "ready_to_close"]
        s.rollback()


def test_department_block_to_close_and_closed(wide):
    with wide.Session() as s:
        c.disposed_case(s, wide)
        c.disposed_case(s, wide)
        w.claimed_case(s, wide)
        closed = c.disposed_case(s, wide)
        c.close(s, wide, "edu_off1", closed)
        block = dashboard.department_block(s, wide.user(s, "edu_head"), wide.office(s, "EDU"))
        assert block["cases"]["to_close"] == 2 and block["cases"]["closed"] == 1
        assert block["attention"]["to_close"] == 2
        assert block["cases"]["claimed_disposed"] == 3  # unchanged: the court's figure
        s.rollback()


# ------------------------------------------------------------------------------------------------ the case page


def test_workflow_flags_agree_with_the_writes(wide):
    with wide.Session() as s:
        flags = lambda key, case: workflow_actions.available(s, wide.user(s, key), case)  # noqa: E731
        case = c.disposed_case(s, wide)
        f = flags("edu_off1", case)
        assert (f["close"], f["close_as"], f["close_blocked"]) == (True, "holder", None)
        assert flags("edu_head", case)["close_as"] == "head"
        assert flags("root", case)["close_as"] == "super_admin"
        assert flags("edu_off2", case)["close"] is False and flags("edu_off2", case)["close_blocked"] is None
        # a holder from another department
        away = c.disposed_case(s, wide)
        w.send(s, wide, "edu_off1", away, "health_off", pending_action_="opinion")
        f = flags("health_off", away)
        assert f["close"] is False and f["close_blocked"] is None
        # a pending case
        pending = w.claimed_case(s, wide)
        f = flags("edu_off1", pending)
        assert f["close"] is False and f["close_blocked"] == "not_disposed"
        # an open transfer
        moving = c.disposed_case(s, wide)
        actor, admin = wide.actor(s, "edu_admin")
        own.request_transfer(s, actor, admin, moving, to_office_code="HEALTH", reason="theirs")
        assert flags("edu_off1", moving)["close_blocked"] == "transfer_open"
        # a closed case: its head may reopen; another department's head holding the function may not
        c.close(s, wide, "edu_off1", case)
        assert flags("edu_off1", case)["close"] is False
        f = flags("edu_head", case)
        assert f["reopen"] is True and f["reopen_blocked"] is None
        assert (
            flags("edu_off1", case)["reopen"] is False and flags("edu_off1", case)["reopen_blocked"] is None
        )
        c.add_login(s, wide, "health_head", Role.DEPT_HEAD, "HEALTH")
        f = flags("health_head", case)
        assert f["reopen"] is False and f["reopen_blocked"] == "not_own_department"
        assert flags("edu_head", pending)["reopen"] is False
        s.rollback()


def test_closed_stage_cannot_be_set(wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        a, u = wide.actor(s, "edu_off1")
        with pytest.raises(WorkflowError) as e:
            stages.set_stage(s, a, u, case, stage="closed")
        assert e.value.code == "bad_field"
        assert "closed" not in {x.code for x in stages.catalogue(s)}
        # a past row keeps its label
        s.add(CaseStage(case_id=case.id, office_id=wide.office(s, "EDU").id, stage="closed"))
        s.flush()
        block = stages.current_block(s, case)
        assert block["stage"] == "closed" and block["label"] == "Closed"
        assert my_cases.case_briefs(s, u, [case.id])[case.id]["stage"]["label"] == "Closed"
        assert CaseStatus(case.status) == CaseStatus.PENDING
        s.rollback()
