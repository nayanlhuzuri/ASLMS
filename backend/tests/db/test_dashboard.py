"""Dashboards (design `reports-dashboards`, "Tests", database): blocks by function and membership, the department
choice, the gates of the department sections, counts equal to the inbox, calendar and alerts, visibility of the
lists, the personal and State blocks, and that nothing is written."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from aslms.domain.alerts import AlertStatus, ReviewStatus
from aslms.domain.cases import AdvocateSide, CaseAdvocate
from aslms.domain.org import Office, PermissionEffect
from aslms.domain.ownership import CounselCode, ScoreBand
from aslms.domain.reference import OfficeKind, Permission, Role
from aslms.services import alerts, calendar, dashboard, inbox
from aslms.services.access import Forbidden
from aslms.services.reporting_common import BadDepartment, DepartmentRequired
from tests.db.alerts_support import recommend
from tests.db.report_support import (
    claim,
    compliance_alert,
    dispose,
    new_case,
    next_date,
    override,
    own_directly,
    row_counts,
    set_due,
    today,
)
from tests.db.workflow_support import note, send
from tests.db.world import add_membership


def _codes(block: dict) -> list[str]:
    return [d["code"] for d in block["departments"]]


def test_blocks_follow_functions_not_types(world):
    with world.Session() as s:
        expect = {
            "oversight": ([], True),
            "root": ([], True),
            "edu_admin": (["EDU"], False),
            "edu_head": (["EDU"], False),
            "health_admin": (["HEALTH"], False),
            "edu_off1": ([], False),
            "dse_user": ([], False),
            "edu_counsel": ([], False),
            "edu_reviewer": ([], False),
            "central_op": ([], False),
        }
        for key, (depts, state) in expect.items():
            idx = dashboard.available(s, world.user(s, key))
            assert idx["me"] is True, key
            assert _codes(idx) == depts, key
            assert idx["state"] is state, key
        override(s, world, "edu_off1", Permission.REPORTS_DEPARTMENT, PermissionEffect.GRANT)
        assert _codes(dashboard.available(s, world.user(s, "edu_off1"))) == ["EDU"]


def _two_departments(s, world):
    admin = world.user(s, "edu_admin")
    add_membership(s, admin, world.office(s, "HEALTH"), Role.DEPT_OFFICER)
    s.flush()
    override(s, world, "edu_admin", Permission.CASES_ALLOT, PermissionEffect.GRANT, office="HEALTH")
    return admin


def test_person_with_two_departments_gets_two_blocks(world):
    with world.Session() as s:
        admin = _two_departments(s, world)
        assert _codes(dashboard.available(s, admin)) == ["EDU", "HEALTH"]
        for code in ("EDU", "HEALTH"):
            office, member = dashboard.resolve_department(s, admin, code)
            assert office.code == code and member.department.code == code
            assert dashboard.department_block(s, admin, office)["department"]["code"] == code


def test_department_required_lists_candidates(world):
    with world.Session() as s:
        admin = _two_departments(s, world)
        with pytest.raises(DepartmentRequired) as e:
            dashboard.resolve_department(s, admin, None)
        assert e.value.code == "department_required" and e.value.extra["candidates"] == ["EDU", "HEALTH"]
        # one eligible department: chosen without asking
        office, _ = dashboard.resolve_department(s, world.user(s, "health_admin"), None)
        assert office.code == "HEALTH"
        # a State reader with no department of their own must name one
        with pytest.raises(DepartmentRequired):
            dashboard.resolve_department(s, world.user(s, "oversight"), None)
        with pytest.raises(Forbidden):
            dashboard.resolve_department(s, world.user(s, "edu_off1"), None)


def test_department_block_of_another_department_is_403_unless_dashboard_state(world):
    with world.Session() as s:
        admin = world.user(s, "edu_admin")
        with pytest.raises(Forbidden):
            dashboard.resolve_department(s, admin, "HEALTH")
        health = world.office(s, "HEALTH")
        with pytest.raises(Forbidden):
            dashboard.department_block(s, admin, health)
        with pytest.raises(Forbidden):  # a membership in EDU that is not eligible
            dashboard.resolve_department(s, world.user(s, "edu_off1"), "EDU")
        oversight = world.user(s, "oversight")
        office, member = dashboard.resolve_department(s, oversight, "health")
        assert office.code == "HEALTH" and member is None
        block = dashboard.department_block(s, oversight, office)
        assert block["recommendations"] is not None and block["pending_actions"] is not None
        for bad in ("EDU-DSE", "NOPE"):
            with pytest.raises(BadDepartment):
                dashboard.resolve_department(s, oversight, bad)


def test_department_counts_equal_inbox_counts(world):
    with world.Session() as s:
        admin = world.user(s, "edu_admin")
        for band in (ScoreBand.HIGH, ScoreBand.HIGH, ScoreBand.MEDIUM):
            recommend(s, world, new_case(s), "EDU", band=band, score=0.9 if band == ScoreBand.HIGH else 0.6)
        recommend(s, world, new_case(s), "HEALTH")
        active = [new_case(s) for _ in range(3)]
        for c in active:
            claim(s, world, c)
        dispose(s, active[0])
        claim(s, world, new_case(s), by="health_admin")
        block = dashboard.department_block(s, admin, world.office(s, "EDU"))
        counts = inbox.counts(s, admin, office="EDU")["departments"][0]
        assert (
            block["recommendations"]
            == {
                "high": counts["recommended_high"],
                "medium": counts["recommended_medium"],
                "transfers_in_open": counts["transfers_in_open"],
            }
            == {"high": 2, "medium": 1, "transfers_in_open": 0}
        )
        assert block["cases"]["claimed_active"] == counts["claimed_active"] == 2
        assert block["cases"]["claimed_disposed"] == counts["claimed_disposed"] == 1
        assert block["cases"]["claimed_active"] == inbox.claimed(s, admin, role="primary").total
        assert block["cases"]["not_allotted_active"] == 2 and block["cases"]["watching_active"] == 0


def _overdue_file(s, world):
    """An EDU case allotted to edu_off1, sent to edu_off2 and now three days overdue."""
    case = new_case(s)
    claim(s, world, case, officer="edu_off1")
    send(s, world, "edu_off1", case, "edu_off2", due_date=today() + timedelta(days=5))
    set_due(s, case, -3)
    return case


def test_pending_action_sections_need_track_or_reports_function(world):
    with world.Session() as s:
        case = _overdue_file(s, world)
        edu = world.office(s, "EDU")
        block = dashboard.department_block(s, world.user(s, "edu_admin"), edu)
        assert block["pending_actions"]["held"] == 1 and block["pending_actions"]["overdue"] == 1
        assert [i["case"]["id"] for i in block["pending_actions"]["items"]] == [case.id]
        assert block["pending_actions"]["items"][0]["overdue_days"] == 3
        assert block["custody_by_office"] == [
            {
                "holder_department_code": "EDU",
                "office_code": "EDU",
                "office_name": "Education",
                "held": 1,
                "with_pending_action": 1,
                "overdue": 1,
            }
        ]
        override(s, world, "edu_head", Permission.CUSTODY_TRACK, PermissionEffect.DENY)
        override(s, world, "edu_head", Permission.REPORTS_DEPARTMENT, PermissionEffect.DENY)
        head = dashboard.department_block(s, world.user(s, "edu_head"), edu)
        assert head["pending_actions"] is None and head["custody_by_office"] is None
        assert head["cases"]["claimed_active"] == 1  # still eligible through cases.claim
        override(s, world, "edu_head", Permission.REPORTS_DEPARTMENT, None)
        head = dashboard.department_block(s, world.user(s, "edu_head"), edu)
        assert head["pending_actions"]["overdue"] == 1 and head["pending_actions"]["items"] is None
        assert head["custody_by_office"] is not None


def test_hearings_7d_and_critical_48h_match_calendar(world):
    with world.Session() as s:
        for days in (1, 1, 5, 9):
            c = new_case(s, next_hearing=today() + timedelta(days=days))
            claim(s, world, c)
        claim(s, world, new_case(s, next_hearing=today() + timedelta(days=1)), by="health_admin")
        now = datetime.now(UTC)
        block = dashboard.department_block(s, world.user(s, "edu_admin"), world.office(s, "EDU"), now=now)
        cal = calendar.calendar_for_user(s, world.user(s, "oversight"), office="EDU", now=now)
        assert block["hearings"]["total"] == len(cal) == 3
        assert block["hearings"]["critical"] == sum(1 for i in cal if i["critical"]) == 2
        assert [i["critical"] for i in block["hearings"]["items"]] == [True, True, False]


def test_hearing_list_hides_cases_the_caller_cannot_see(world):
    with world.Session() as s:
        mine = new_case(s, next_hearing=today() + timedelta(days=2))
        claim(s, world, mine, unit="EDU-DSE")
        other = new_case(s, next_hearing=today() + timedelta(days=3))
        claim(s, world, other, officer="edu_off1")
        override(s, world, "dse_user", Permission.REPORTS_DEPARTMENT, PermissionEffect.GRANT)
        dse = world.user(s, "dse_user")
        office, _ = dashboard.resolve_department(s, dse, None)
        block = dashboard.department_block(s, dse, office)
        assert block["hearings"]["total"] == 2  # the department's count (decision 8)
        assert [i["case"]["id"] for i in block["hearings"]["items"]] == [mine.id]
        assert block["cases"]["claimed_active"] == 2  # department totals, not the caller's slice
        assert block["recommendations"] is None  # no cases.claim


def test_attention_counts_next_dates_to_review_and_compliance(world):
    with world.Session() as s:
        case = new_case(s)
        claim(s, world, case)
        stranger = new_case(s)
        next_date(s, case, today() + timedelta(days=20))
        next_date(s, stranger, today() + timedelta(days=20))
        next_date(s, case, today() + timedelta(days=30), review=ReviewStatus.CONFIRMED, needs_review=False)
        compliance_alert(s, world, case, today() + timedelta(days=1))
        compliance_alert(s, world, case, today() - timedelta(days=2))
        compliance_alert(s, world, case, today() - timedelta(days=4), status=AlertStatus.DONE)
        edu = world.office(s, "EDU")
        att = dashboard.department_block(s, world.user(s, "edu_admin"), edu)["attention"]
        assert att["next_dates_to_review"] == 0  # next-date-direct, decision 9: a pending row asks nobody
        assert att["compliance_due_soon"] == 1 and att["compliance_overdue"] == 1
        assert len(att["recent_order_next_dates"]) == 2
        assert {i["case"]["id"] for i in att["recent_order_next_dates"]} == {case.id}
        override(s, world, "edu_head", Permission.NEXT_DATES_REVIEW, PermissionEffect.DENY)
        att = dashboard.department_block(s, world.user(s, "edu_head"), edu)["attention"]
        assert att["next_dates_to_review"] is None and att["compliance_overdue"] == 1


def test_me_block_own_cases_files_alerts_hearings_drafts(world):
    with world.Session() as s:
        # a directorate user's unit allotment
        unit_case = new_case(s, next_hearing=today() + timedelta(days=1))
        claim(s, world, unit_case, unit="EDU-DSE")
        me = dashboard.me_block(s, world.user(s, "dse_user"))
        assert me["cases"] == [
            {"department_code": "EDU", "allotted_active": 1, "allotted_disposed": 0, "counsel_active": None}
        ]
        assert me["hearings"]["total"] == 1 and me["hearings"]["critical"] == 1
        # standing counsel: the counsel basis
        s.add(CounselCode(code="SC, EDU", office_id=world.office(s, "EDU-SC").id, is_generic_state=False))
        counsel_case = new_case(s)
        s.add(
            CaseAdvocate(
                case_id=counsel_case.id,
                side=AdvocateSide.RESPONDENT,
                name_as_listed="Standing counsel",
                counsel_code="SC, EDU",
            )
        )
        s.flush()
        me = dashboard.me_block(s, world.user(s, "edu_counsel"))
        assert me["cases"][0]["counsel_active"] == 1
        # files held by edu_off2, ordered by due date; one overdue
        first, second = new_case(s), new_case(s)
        for c, days in ((first, 6), (second, 3)):
            claim(s, world, c, officer="edu_off1")
            send(s, world, "edu_off1", c, "edu_off2", due_date=today() + timedelta(days=days))
        set_due(s, first, -1)
        off2 = world.user(s, "edu_off2")
        note(s, world, "edu_off2", second, body="a draft of the holder")
        me = dashboard.me_block(s, off2)
        assert me["files"]["held"] == 2 and me["files"]["with_pending_action"] == 2
        assert me["files"]["overdue"] == 1
        assert [i["case"]["id"] for i in me["files"]["items"]] == [first.id, second.id]
        assert me["files"]["items"][0]["overdue_days"] == 1
        assert me["drafts"] == 1
        counts = alerts.counts_for_user(s, off2)
        assert me["alerts"]["unread"] == counts["unread"] and me["alerts"]["open"] == counts["open"]
        assert me["hearings"]["total"] == len(calendar.calendar_for_user(s, off2))
        # a State-wide reader without a working basis gets zeros
        me = dashboard.me_block(s, world.user(s, "oversight"))
        assert me["cases"] == [] and me["hearings"]["total"] == 0 and me["files"]["held"] == 0


def test_state_block_by_department_and_not_claimed_row(world):
    with world.Session() as s:
        goa = world.office(s, "GOA")
        fin = Office(code="FIN", name="Finance", kind=OfficeKind.DEPARTMENT, parent_id=goa.id, path="GOA/FIN")
        old = Office(
            code="OLD", name="Old Dept", kind=OfficeKind.DEPARTMENT, parent_id=goa.id, path="GOA/OLD"
        )
        s.add_all([fin, old])
        s.flush()
        fin_case = new_case(s, next_hearing=today() + timedelta(days=2))
        own_directly(s, world, fin_case, "FIN")
        fin.is_active = False
        old.is_active = False
        overdue = _overdue_file(s, world)
        compliance_alert(s, world, overdue, today() - timedelta(days=1))
        compliance_alert(s, world, overdue, today() + timedelta(days=2))
        claim(s, world, new_case(s, next_hearing=today() + timedelta(days=1)))
        unclaimed_rec = new_case(s, next_hearing=today() + timedelta(days=3))
        recommend(s, world, unclaimed_rec, "EDU")
        new_case(s)  # unclaimed, no recommendation, no hearing
        dispose(s, new_case(s))  # disposed and unclaimed: not active
        s.flush()
        block = dashboard.state_block(s, world.user(s, "oversight"))
        rows = {r["code"]: r for r in block["by_department"]}
        assert "OLD" not in rows  # inactive and owning nothing
        assert rows["FIN"]["is_active"] is False and rows["FIN"]["claimed_active"] == 1
        assert rows["FIN"]["hearings_7d"] == 1
        assert rows["HEALTH"]["claimed_active"] == 0 and rows["HEALTH"]["is_active"] is True
        edu = rows["EDU"]
        assert edu["claimed_active"] == 2 and edu["recommended_high"] == 1
        assert edu["hearings_7d"] == 1 and edu["pending_actions"] == 1 and edu["overdue_actions"] == 1
        assert edu["compliance_due_soon"] == 1 and edu["compliance_overdue"] == 1
        assert block["not_claimed"] == {"active": 2, "recommended": 1, "hearing_7d": 1}
        assert block["hearings"]["total"] == sum(r["hearings_7d"] for r in rows.values()) == 2
        assert block["overdue_actions"]["total"] == sum(r["overdue_actions"] for r in rows.values()) == 1
        assert block["overdue_actions"]["by_owner"] == [{"code": "EDU", "overdue": 1}]
        assert block["overdue_actions"]["by_holder"] == [{"code": "EDU", "overdue": 1}]
        assert block["compliance"] == {
            "due_soon": sum(r["compliance_due_soon"] for r in rows.values()),
            "overdue": sum(r["compliance_overdue"] for r in rows.values()),
        }
        with pytest.raises(Forbidden):
            dashboard.state_block(s, world.user(s, "edu_admin"))


def test_dashboard_writes_nothing(world):
    with world.Session() as s:
        _overdue_file(s, world)
        claim(s, world, new_case(s, next_hearing=today() + timedelta(days=1)))
        s.commit()
        before = row_counts(s)
        for key in ("oversight", "edu_admin", "edu_off2", "dse_user"):
            user = world.user(s, key)
            dashboard.available(s, user)
            dashboard.me_block(s, user)
            for d in dashboard.eligible_departments(s, user):
                dashboard.department_block(s, user, d)
        dashboard.department_block(s, world.user(s, "oversight"), world.office(s, "EDU"))
        dashboard.state_block(s, world.user(s, "oversight"))
        assert not s.new and not s.dirty and not s.deleted
        assert row_counts(s) == before
        assert s.execute(sa.text("select count(*) from audit_log where action like 'report%'")).scalar() == 0


def test_attention_counts_next_dates_that_differ(world):
    """Design next-date-direct, decision 5: the department's claimed cases whose latest order gives an exact date
    other than the court's record."""
    from aslms.services import next_hearing
    from tests.db import next_dates_support as h

    with world.Session() as s:
        differs = h.claimed(s, world, next_hearing=today() + timedelta(days=12))
        h.order_with_text(s, differs, f"List this matter on {h.dmy(h.days(10))}.", order_date=h.days(-1))
        agrees = h.claimed(s, world, next_hearing=today() + timedelta(days=10))
        h.order_with_text(s, agrees, f"List this matter on {h.dmy(h.days(10))}.", order_date=h.days(-1))
        other = h.claimed(s, world, key="health_admin", next_hearing=today() + timedelta(days=12))
        h.order_with_text(s, other, f"List this matter on {h.dmy(h.days(10))}.", order_date=h.days(-1))
        h.read(s)
        next_hearing.refresh(s, [differs.id, agrees.id, other.id])
        att = dashboard.department_block(s, world.user(s, "edu_admin"), world.office(s, "EDU"))["attention"]
        assert att["next_dates_differ"] == 1
        att = dashboard.department_block(s, world.user(s, "health_admin"), world.office(s, "HEALTH"))[
            "attention"
        ]
        assert att["next_dates_differ"] == 1
        s.rollback()
