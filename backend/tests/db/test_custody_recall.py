"""Recall (design custody-workflow, decisions 6-8, 13, 23b): the owning department's recall from any depth of the
chain, in one step, with every holder's drafts permanent; `custody.recall` granted by the department admin and
not by another department's grant; refusals; an ownership move acting as a recall and alerting the previous
holder."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.alerts import Alert
from aslms.domain.org import PermissionEffect
from aslms.domain.reference import AlertKind, Permission
from aslms.domain.workflow import PendingAction
from aslms.services import access, alerts, custody
from aslms.services import ownership as own
from aslms.services.workflow_common import WorkflowError
from tests.db import alerts_support as h
from tests.db import workflow_support as w


@pytest.fixture()
def wide(world):
    return w.widen(world)


def test_recall_from_any_depth(wide):
    """EDU officer → HEALTH officer → HEALTH directorate officer → FIN officer; the EDU admin recalls in one
    step; the card shows the admin; every holder's drafts are permanent notes."""
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        chain = [("edu_off1", "health_off"), ("health_off", "health_dir"), ("health_dir", "fin_off")]
        for sender, target in chain:
            _, is_draft = w.note(s, wide, sender, case, body=f"draft of {sender}")
            assert is_draft
            result = w.send(s, wide, sender, case, target)
            assert len(result.finalised) == 1
        _, is_draft = w.note(s, wide, "fin_off", case, body="draft of fin_off")
        assert is_draft
        result = w.recall(s, wide, "edu_admin", case)
        assert len(result.finalised) == 1
        leg = result.leg
        admin_m = wide.membership(s, "edu_admin")
        assert leg.reason == "recalled" and leg.holder_membership_id == admin_m.id
        assert leg.pending_action == PendingAction.EXAMINE and leg.due_date is None
        assert leg.remark == "calling the file back"
        _, admin = wide.actor(s, "edu_admin")
        card = custody.card(s, admin, case)
        assert card["holder_user"]["id"] == w.uid(wide, "edu_admin")
        assert (
            card["pending_action"] == "examine" and card["can_recall"] is False and card["can_send"] is True
        )
        assert not w.drafts(s, case.id)
        bodies = [n.body for n in w.case_notes(s, case.id)]
        assert bodies == [
            "draft of edu_off1",
            "draft of health_off",
            "draft of health_dir",
            "draft of fin_off",
        ]
        assert [n.seq_no for n in w.case_notes(s, case.id)] == [1, 2, 3, 4]
        assert all(n.drafted_at is not None for n in w.case_notes(s, case.id))
        # the FIN officer lost the custody basis
        _, fin = wide.actor(s, "fin_off")
        from aslms.services import visibility

        assert not visibility.can_view_case(s, fin, case)
        audit = w.audits(s, "custody.recalled", case.id)
        assert len(audit) == 1 and "calling the file back" not in str(audit[0].after)
        s.rollback()


def test_recall_needs_the_function_granted_by_the_department_admin(wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        w.send(s, wide, "edu_off1", case, "health_off")
        actor, admin = wide.actor(s, "edu_admin")
        # edu_off1 still sees the case through the allotment, but lacks custody.recall
        with pytest.raises(WorkflowError) as e:
            w.recall(s, wide, "edu_off1", case)
        assert e.value.code == "function_missing" and e.value.http_status == 403
        access.set_override(
            s, actor, admin, wide.membership(s, "edu_off1"), Permission.CUSTODY_RECALL, PermissionEffect.GRANT
        )
        leg = w.recall(s, wide, "edu_off1", case).leg
        assert leg.holder_user_id == w.uid(wide, "edu_off1")
        s.rollback()


def test_another_departments_grant_gives_no_recall(wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        w.send(s, wide, "edu_off1", case, "health_dir")
        r_actor, root = wide.actor(s, "root")
        access.set_override(
            s,
            r_actor,
            root,
            wide.membership(s, "health_off"),
            Permission.CUSTODY_RECALL,
            PermissionEffect.GRANT,
        )
        w.send(s, wide, "health_dir", case, "health_off")  # health_off holds it and can see it
        with pytest.raises(WorkflowError) as e:
            w.recall(s, wide, "health_off", case)
        assert e.value.code == "not_owner_department"
        s.rollback()


def test_health_nodal_officer_refused_and_already_holding(wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        w.send(s, wide, "edu_off1", case, "health_admin")
        with pytest.raises(WorkflowError) as e:
            w.recall(s, wide, "health_admin", case)
        assert e.value.code == "not_owner_department"
        w.recall(s, wide, "edu_admin", case)
        with pytest.raises(WorkflowError) as e:
            w.recall(s, wide, "edu_admin", case)
        assert e.value.code == "unchanged" and e.value.http_status == 409
        s.rollback()


def test_ownership_move_acts_as_recall_and_alerts_the_previous_holder(wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        w.send(s, wide, "edu_off1", case, "health_off")
        w.note(s, wide, "health_off", case, body="health draft")
        actor, admin = wide.actor(s, "edu_admin")
        own.allot(s, actor, admin, case, officer_user_id=wide.user(s, "edu_off2").id)
        row = w.holder(s, case)
        assert row.holder_user_id == w.uid(wide, "edu_off2")
        assert row.holder_membership_id == wide.membership(s, "edu_off2").id
        assert not w.drafts(s, case.id)
        assert [n.body for n in w.case_notes(s, case.id)] == ["health draft"]
        s.commit()
        case_id = case.id
    with wide.Session() as s:
        alerts.scan_events(s, now=h.now_utc())
        s.commit()
        rows = s.scalars(
            sa.select(Alert).where(Alert.case_id == case_id, Alert.kind == AlertKind.WORKFLOW)
        ).all()
        recalled = [a for a in rows if a.data.get("event") == "file_recalled"]
        assert len(recalled) == 1
        assert h.recipient_emails(s, recalled[0]) == {w.email_of("health_off")}
