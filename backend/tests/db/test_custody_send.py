"""Sending the file (design custody-workflow, decisions 3-5, 19): the holder sends to an officer of another
department; a referral reviewer holding the file sends it on without `custody.move`; a non-holder is refused;
an office-held leg is sent by its controller; bad targets, the same holder and a past due date are refused; a
stage recorded with the send, or the send refused before anything is written."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.ownership import CaseOwnership, OwnershipStatus
from aslms.domain.reference import EventType
from aslms.domain.workflow import CaseStage, PendingAction
from aslms.services import ownership as own
from aslms.services.workflow_common import WorkflowError
from tests.db import workflow_support as w


@pytest.fixture()
def wide(world):
    return w.widen(world)


def test_holder_sends_to_an_officer_of_another_department(wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        owner_before = s.scalars(sa.select(CaseOwnership).where(CaseOwnership.case_id == case.id)).all()
        snapshot = [(o.id, o.office_id, o.officer_user_id, o.status) for o in owner_before]
        result = w.send(
            s, wide, "edu_off1", case, "health_dir", due_date=w.in_days(10), remark="parawise comments please"
        )
        leg = result.leg
        target = wide.membership(s, "health_dir")
        assert leg.reason == "sent" and leg.holder_membership_id == target.id
        assert leg.holder_designation == "Deputy Director"
        assert leg.holder_office_code == "HEALTH-DHS" and leg.holder_user_id == w.uid(wide, "health_dir")
        assert leg.remark == "parawise comments please"
        assert leg.pending_action == PendingAction.PARAWISE_COMMENTS and leg.due_date == w.in_days(10)
        assert leg.actor_user_id == w.uid(wide, "edu_off1") and leg.actor_office_code == "EDU"
        row = w.holder(s, case)
        assert row.holder_membership_id == target.id and row.current_leg_id == leg.id
        assert row.due_date == w.in_days(10)
        # ownership untouched
        after = s.scalars(sa.select(CaseOwnership).where(CaseOwnership.case_id == case.id)).all()
        assert [(o.id, o.office_id, o.officer_user_id, o.status) for o in after] == snapshot
        assert any(o.status == OwnershipStatus.ACTIVE for o in after)
        # one event, never the remark; one audit row with the remark's digest only
        ev = w.events(s, case.id, EventType.CUSTODY_MOVED)[-1]
        assert ev.payload["reason"] == "sent" and "remark" not in ev.payload
        assert "parawise comments please" not in str(ev.payload)
        audit = w.audits(s, "custody.sent", case.id)
        assert len(audit) == 1 and "parawise comments please" not in str(audit[0].after)
        assert audit[0].after["remark"]["length"] == len("parawise comments please")
        s.rollback()


def test_referral_reviewer_holding_the_file_sends_it_on(wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        w.send(s, wide, "edu_off1", case, "edu_reviewer", pending_action_="review")
        _, reviewer = wide.actor(s, "edu_reviewer")
        from aslms.domain.reference import Permission
        from aslms.services import access

        assert not access.has(s, reviewer, Permission.CUSTODY_MOVE)
        leg = w.send(s, wide, "edu_reviewer", case, "edu_off2", pending_action_="examine").leg
        assert leg.holder_user_id == w.uid(wide, "edu_off2")
        s.rollback()


def test_non_holder_is_refused(wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        for key in ("edu_off2", "edu_admin", "health_off"):
            with pytest.raises(Exception) as e:
                w.send(s, wide, key, case, "fin_off")
            code = getattr(e.value, "code", None)
            assert code in ("not_in_control",) or type(e.value).__name__ == "NotVisibleCase", (key, e.value)
        s.rollback()


def test_office_held_leg_sent_by_its_controllers(wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide, officer=None)  # claimed: the leg names EDU only
        row = w.holder(s, case)
        assert row.holder_user_id is None and row.holder_membership_id is None
        with pytest.raises(WorkflowError) as e:
            w.send(s, wide, "oversight", case, "fin_off")  # sees every case, holds no custody.move
        assert e.value.code == "not_in_control"
        leg = w.send(s, wide, "edu_admin", case, "fin_off").leg  # whole-department membership
        assert leg.holder_user_id == w.uid(wide, "fin_off")
        s.rollback()
    with wide.Session() as s:
        case = w.claimed_case(s, wide, officer=None)
        actor, admin = wide.actor(s, "edu_admin")
        own.allot(s, actor, admin, case, unit_code="EDU-DSE", officer_user_id=None)
        row = w.holder(s, case)
        assert row.holder_user_id is None and row.holder_office_id == wide.offices["EDU-DSE"].id
        leg = w.send(s, wide, "dse_user", case, "health_off").leg  # a unit user with custody.move
        assert leg.holder_user_id == w.uid(wide, "health_off")
        s.rollback()


@pytest.mark.parametrize("target", ["oversight", "central_op", "edu_auditor", "root"])
def test_state_wide_targets_refused(wide, target):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        with pytest.raises(WorkflowError) as e:
            w.send(s, wide, "edu_off1", case, target)
        assert e.value.code == "bad_target" and e.value.http_status == 400
        s.rollback()


def test_inactive_membership_same_holder_and_bad_fields(wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        n_legs = len(w.legs(s, case))  # claimed + allotted
        from aslms.domain.reference import Role
        from aslms.services import custody
        from tests.db.world import add_membership

        extra = add_membership(s, wide.user(s, "health_off"), wide.office(s, "FIN"), Role.DEPT_OFFICER)
        extra.is_active = False
        extra.deactivated_at = extra.created_at
        s.flush()
        actor, off1 = wide.actor(s, "edu_off1")
        with pytest.raises(WorkflowError) as e:
            custody.send(
                s, actor, off1, case, to_membership=extra.id, pending_action_="report", remark="report please"
            )
        assert e.value.code == "bad_target"
        fin = wide.user(s, "fin_off")
        fin.is_active = False  # a disabled login is no target either
        s.flush()
        with pytest.raises(WorkflowError) as e:
            w.send(s, wide, "edu_off1", case, "fin_off")
        assert e.value.code == "bad_target"
        fin.is_active = True
        s.flush()
        with pytest.raises(WorkflowError) as e:
            w.send(s, wide, "edu_off1", case, "edu_off1")
        assert e.value.code == "unchanged" and e.value.http_status == 409
        with pytest.raises(WorkflowError) as e:
            w.send(s, wide, "edu_off1", case, "fin_off", due_date=w.in_days(-1))
        assert e.value.code == "bad_due_date"
        with pytest.raises(WorkflowError) as e:
            w.send(s, wide, "edu_off1", case, "fin_off", pending_action_="none")
        assert e.value.code == "bad_field"
        with pytest.raises(WorkflowError) as e:
            w.send(s, wide, "edu_off1", case, "fin_off", remark="no")
        assert e.value.code == "bad_field"
        assert len(w.legs(s, case)) == n_legs  # nothing written
        s.rollback()


def test_send_needs_a_claimed_case(wide):
    from aslms.services import custody
    from tests.db.world import make_case

    with wide.Session() as s:
        case = make_case(s)
        actor, root = wide.actor(s, "root")
        with pytest.raises(WorkflowError) as e:
            custody.send(
                s,
                actor,
                root,
                case,
                to_membership=wide.membership(s, "fin_off").id,
                pending_action_="report",
                remark="please report",
            )
        assert e.value.code == "not_owned" and e.value.http_status == 409
        s.rollback()


def test_stage_with_send(wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        w.send(s, wide, "edu_off1", case, "edu_counsel", stage="parawise_comments_sought")
        stages = s.scalars(sa.select(CaseStage).where(CaseStage.case_id == case.id)).all()
        assert [st.stage.value if hasattr(st.stage, "value") else st.stage for st in stages] == [
            "parawise_comments_sought"
        ]
        # standing counsel holds the file but has no stages.set: a send with a stage is refused, nothing written
        n_legs = len(w.legs(s, case))
        with pytest.raises(WorkflowError) as e:
            w.send(s, wide, "edu_counsel", case, "edu_off2", stage="affidavit_vetted")
        assert e.value.http_status == 403
        assert len(w.legs(s, case)) == n_legs
        # without the stage the counsel sends on
        w.send(s, wide, "edu_counsel", case, "edu_off2")
        s.rollback()


def test_sent_item_visible_false_after_sending_on(wide):
    """Design portal-workflow, decision 20g: the HEALTH officer who sends an EDU file on loses sight of it
    (`visible` false); the EDU admin's own send of a case EDU owns stays visible."""
    from aslms.services import custody

    with wide.Session() as s:
        case = w.claimed_case(s, wide, officer=None)  # held by the EDU office; the admin controls it
        w.send(s, wide, "edu_admin", case, "health_off")
        w.send(s, wide, "health_off", case, "fin_off")
        _, hoff = wide.actor(s, "health_off")
        _, admin = wide.actor(s, "edu_admin")
        (mine,) = custody.sent(s, hoff).items
        assert mine["visible"] is False and mine["leg"]["remark"]
        (theirs,) = custody.sent(s, admin).items
        assert theirs["visible"] is True
        s.rollback()
