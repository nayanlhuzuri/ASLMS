"""Close Case (design close-case, decisions 2-9): who may close (the holder of the owning department, the head
wherever the case is, the super admin), the conditions in order with nothing written on a refusal, the `closed` leg,
the `closing` note, the closure row, the event and the audit row without the remark, drafts made permanent first, the
system note kinds, the correction of a closing note, a closed case that does not move, a closer losing sight, and the
table's own guards."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.cases import CaseStatus
from aslms.domain.documents import Visibility
from aslms.domain.org import Office, PermissionEffect
from aslms.domain.reference import EventType, NoteKind, Permission, Role
from aslms.domain.workflow import CaseNote, CustodyHistory, PendingAction
from aslms.services import access, case_closure, custody, notes, stages, visibility, workflow_codes
from aslms.services import ownership as own
from aslms.services.visibility import NotVisibleCase
from aslms.services.workflow_common import WorkflowError
from tests.db import closure_support as c
from tests.db import workflow_support as w
from tests.db.world import make_case


@pytest.fixture()
def wide(world):
    return w.widen(world)


def _refused(fn, code: str) -> None:
    with pytest.raises(WorkflowError) as e:
        fn()
    assert e.value.code == code, (e.value.code, str(e.value))


def _nothing_written(s, case, legs_before: int) -> None:
    assert c.closures(s, case) == []
    assert len(w.legs(s, case)) == legs_before
    assert w.events(s, case.id, EventType.CASE_CLOSED) == []


def test_holder_of_owning_department_closes(wide):
    with wide.Session() as s:
        # a department officer holding the case
        case = c.disposed_case(s, wide)
        result = c.close(s, wide, "edu_off1", case)
        [closure] = c.closures(s, case)
        assert closure.closed_as == "holder" and closure.reopened_at is None
        assert closure.disposal_date == c.DISPOSED_ON and closure.office_id == wide.office(s, "EDU").id
        assert closure.actor_user_id == w.uid(wide, "edu_off1") and closure.actor_office_code == "EDU"
        leg = w.legs(s, case)[-1]
        assert leg.reason == "closed" and leg.holder_office_code == "EDU"
        assert leg.holder_user_id is None and leg.holder_membership_id is None
        assert leg.pending_action == PendingAction.NONE and leg.due_date is None and leg.remark is None
        assert closure.close_leg_id == leg.id
        row = w.holder(s, case)
        assert row.holder_user_id is None and row.current_leg_id == leg.id
        note = s.get(CaseNote, closure.note_id)
        assert note.kind == NoteKind.CLOSING and note.visibility == Visibility.CASE_SCOPE
        assert note.custody_leg_id == leg.id and note.body == c.REMARK and result.note.id == note.id
        [ev] = w.events(s, case.id, EventType.CASE_CLOSED)
        assert ev.payload["closed_as"] == "holder" and ev.payload["note_ref_no"] == note.ref_no
        assert ev.payload["office_code"] == "EDU" and ev.payload["seq_no"] == leg.seq_no
        assert c.REMARK not in str(ev.payload)
        [audit] = w.audits(s, "case.closed", case.id)
        assert audit.entity_type == "case_closure" and audit.entity_id == closure.id
        assert audit.after["remark"]["length"] == len(c.REMARK) and c.REMARK not in str(audit.after)
        assert audit.after["closed_as"] == "holder" and audit.before["holder_user_id"] is not None
        assert w.audits(s, "note.added", case.id)[-1].entity_id == note.id
        assert case_closure.is_closed(s, case)

        # a directorate user of the department whose type was given the function, holding the case
        other = c.disposed_case(s, wide)
        w.send(s, wide, "edu_off1", other, "dse_user", pending_action_="examine")
        _, dse = wide.actor(s, "dse_user")
        assert not access.has(s, dse, Permission.CASES_CLOSE)
        from aslms.domain.org import RolePermission

        rp = s.scalar(
            sa.select(RolePermission).where(
                RolePermission.role == Role.DIRECTORATE_USER,
                RolePermission.permission == Permission.CASES_CLOSE,
            )
        )
        rp.is_enabled = True
        s.flush()
        c.close(s, wide, "dse_user", other)
        [closure2] = c.closures(s, other)
        assert closure2.closed_as == "holder" and closure2.actor_office_code == "EDU-DSE"
        s.rollback()


def test_holder_from_other_department_refused(wide):
    with wide.Session() as s:
        case = c.disposed_case(s, wide)
        w.send(s, wide, "edu_off1", case, "health_off", pending_action_="opinion")
        _, health = wide.actor(s, "health_off")
        assert access.has(s, health, Permission.CASES_CLOSE)
        before = len(w.legs(s, case))
        _refused(lambda: c.close(s, wide, "health_off", case), "not_closer")
        _nothing_written(s, case, before)
        s.rollback()


def test_head_closes_wherever_the_case_is(wide):
    with wide.Session() as s:
        with_officer = c.disposed_case(s, wide)
        with_unit = make_case(s, status=CaseStatus.DISPOSED)
        actor, admin = wide.actor(s, "edu_admin")
        own.claim(s, actor, admin, with_unit, unit_code="EDU-DSE")
        assert w.holder(s, with_unit).holder_user_id is None
        elsewhere = c.disposed_case(s, wide)
        w.send(s, wide, "edu_off1", elsewhere, "health_off", pending_action_="opinion")
        for case in (with_officer, with_unit, elsewhere):
            c.close(s, wide, "edu_head", case)
            [closure] = c.closures(s, case)
            assert closure.closed_as == "head", case.case_no_text
            assert w.legs(s, case)[-1].holder_office_code == "EDU"
        s.rollback()


def test_super_admin_closes_any_case(wide):
    with wide.Session() as s:
        case = c.disposed_case(s, wide)
        c.close(s, wide, "root", case)
        assert c.closures(s, case)[0].closed_as == "super_admin"
        pending = w.claimed_case(s, wide)
        _refused(lambda: c.close(s, wide, "root", pending), "not_disposed")
        s.rollback()


def test_refusals_in_order(wide):
    with wide.Session() as s:
        # unclaimed
        unclaimed = make_case(s, status=CaseStatus.DISPOSED)
        _refused(lambda: c.close(s, wide, "root", unclaimed), "not_owned")
        assert c.closures(s, unclaimed) == []
        # pending or unknown
        for status in (CaseStatus.PENDING, CaseStatus.UNKNOWN):
            case = w.claimed_case(s, wide)
            case.status = status
            s.flush()
            before = len(w.legs(s, case))
            _refused(lambda case=case: c.close(s, wide, "edu_off1", case), "not_disposed")
            _nothing_written(s, case, before)
        # already closed
        case = c.disposed_case(s, wide)
        c.close(s, wide, "edu_off1", case)
        _refused(lambda: c.close(s, wide, "edu_head", case), "already_closed")
        assert len(c.closures(s, case)) == 1
        # an open transfer
        case = c.disposed_case(s, wide)
        actor, admin = wide.actor(s, "edu_admin")
        own.request_transfer(s, actor, admin, case, to_office_code="HEALTH", reason="belongs to health")
        before = len(w.legs(s, case))
        _refused(lambda: c.close(s, wide, "edu_off1", case), "transfer_open")
        _nothing_written(s, case, before)
        # a department officer not holding the case, the department admin and a State-wide reader
        case = c.disposed_case(s, wide)
        c.set_function(s, wide, "edu_admin", Permission.CASES_CLOSE, PermissionEffect.GRANT)
        c.set_function(s, wide, "oversight", Permission.CASES_CLOSE, PermissionEffect.GRANT)
        w.send(s, wide, "edu_off1", case, "edu_off2", pending_action_="examine")
        w.send(s, wide, "edu_off2", case, "edu_off1", pending_action_="examine")
        before = len(w.legs(s, case))
        for key in ("edu_off2", "edu_admin", "oversight"):
            _, u = wide.actor(s, key)
            if not visibility.access_basis(s, u, case):
                with pytest.raises(NotVisibleCase):
                    c.close(s, wide, key, case)
            else:
                _refused(lambda key=key: c.close(s, wide, key, case), "not_closer")
        _nothing_written(s, case, before)
        # no function
        c.set_function(s, wide, "edu_off1", Permission.CASES_CLOSE, PermissionEffect.DENY)
        _refused(lambda: c.close(s, wide, "edu_off1", case), "function_missing")
        # a short remark
        _refused(lambda: c.close(s, wide, "edu_head", case, remark="no"), "bad_field")
        _nothing_written(s, case, before)
        # invisible
        with pytest.raises(NotVisibleCase):
            c.close(s, wide, "fin_off", case)
        s.rollback()


def test_admin_and_oversight_see_the_case_to_be_refused(wide):
    """The department admin (whole department) and a State-wide reader can open the case, so they meet
    `not_closer`, not 404."""
    with wide.Session() as s:
        case = c.disposed_case(s, wide)
        for key in ("edu_admin", "oversight"):
            _, u = wide.actor(s, key)
            assert visibility.access_basis(s, u, case), key
        s.rollback()


def test_holder_without_function_refused(wide):
    with wide.Session() as s:
        case = c.disposed_case(s, wide)
        c.set_function(s, wide, "edu_off1", Permission.CASES_CLOSE, PermissionEffect.DENY)
        before = len(w.legs(s, case))
        _refused(lambda: c.close(s, wide, "edu_off1", case), "function_missing")
        _nothing_written(s, case, before)
        s.rollback()


def test_drafts_finalised_before_closing_note(wide):
    with wide.Session() as s:
        case = c.disposed_case(s, wide)
        draft, is_draft = w.note(s, wide, "edu_off1", case, body="my working note")
        assert is_draft
        result = c.close(s, wide, "edu_off1", case)
        trail = w.case_notes(s, case.id)
        assert [n.kind for n in trail] == [NoteKind.GENERAL, NoteKind.CLOSING]
        assert trail[0].body == "my working note" and trail[0].seq_no < trail[1].seq_no
        assert result.finalised == [trail[0].ref_no]
        assert w.drafts(s, case.id) == []
        assert w.audits(s, "case.closed", case.id)[0].after["finalised_notes"] == [trail[0].ref_no]
        s.rollback()


def test_system_kinds_not_selectable(wide):
    with wide.Session() as s:
        for kind in ("closing", "reopening"):
            with pytest.raises(WorkflowError) as e:
                notes.check_kind(s, kind)
            assert e.value.code == "bad_field"
        listed = {k["code"]: k for k in workflow_codes.codes(s)["note_kinds"]}
        assert listed["closing"]["selectable"] is False and listed["reopening"]["selectable"] is False
        assert listed["closing"]["label"] == "Closing remark"
        assert listed["general"]["selectable"] is True
        reasons = {r["code"]: r["label"] for r in workflow_codes.codes(s)["custody_reasons"]}
        assert reasons["closed"] == "Closed" and reasons["reopened"] == "Reopened"
        case = c.disposed_case(s, wide)
        with pytest.raises(WorkflowError):
            w.note(s, wide, "edu_head", case, kind="closing")
        s.rollback()


def test_closing_note_correction(wide):
    with wide.Session() as s:
        case = c.disposed_case(s, wide)
        result = c.close(s, wide, "edu_off1", case)
        original = result.note
        fixed, is_draft = w.note(
            s, wide, "edu_off1", case, body="Corrected reason.", kind=None, supersedes=original.ref_no
        )
        assert not is_draft
        assert fixed.kind == NoteKind.CLOSING and fixed.visibility == Visibility.CASE_SCOPE
        assert fixed.supersedes_id == original.id
        assert c.closures(s, case)[0].note_id == original.id
        s.rollback()


def test_closed_case_does_not_move(wide):
    with wide.Session() as s:
        case = c.disposed_case(s, wide)
        c.close(s, wide, "edu_off1", case)
        # custody
        _refused(lambda: w.send(s, wide, "edu_admin", case, "edu_off2"), "case_closed")
        _refused(lambda: w.recall(s, wide, "edu_admin", case), "case_closed")
        # ownership
        actor, admin = wide.actor(s, "edu_admin")
        for fn in (
            lambda: own.allot(s, actor, admin, case, officer_user_id=w.uid(wide, "edu_off2")),
            lambda: own.request_transfer(s, actor, admin, case, to_office_code="HEALTH", reason="theirs"),
            lambda: own.take_over(s, *wide.actor(s, "edu_off2"), case),
        ):
            with pytest.raises(own.OwnershipConflict) as e:
                fn()
            assert e.value.code == "case_closed"
        actions = own.available_actions(s, admin, case)
        assert not actions["allot"] and not actions["request_transfer"] and not actions["take_over"]
        card = custody.card(s, admin, case)
        assert card["closed"] is True and card["can_send"] is False and card["can_recall"] is False
        # still allowed: a note (permanent: nobody holds the case) and a stage
        n, is_draft = w.note(s, wide, "edu_off1", case, body="certified copy received")
        assert not is_draft and n.kind == NoteKind.GENERAL
        a, u = wide.actor(s, "edu_off1")
        row = stages.set_stage(s, a, u, case, stage="compliance_reported")
        assert row.stage.value == "compliance_reported"
        s.rollback()


def test_closer_loses_sight_visible_false(wide):
    with wide.Session() as s:
        case = c.disposed_case(s, wide)
        w.send(s, wide, "edu_off1", case, "edu_off2", pending_action_="examine")
        _, off2 = wide.actor(s, "edu_off2")
        assert visibility.access_basis(s, off2, case) == ["custody"] or "custody" in visibility.access_basis(
            s, off2, case
        )
        c.close(s, wide, "edu_off2", case)
        assert c.closures(s, case)[0].closed_as == "holder"
        assert visibility.access_basis(s, off2, case) == []
        s.rollback()


def test_one_open_closure_per_case(wide):
    with wide.Session() as s:
        case = c.disposed_case(s, wide)
        c.close(s, wide, "edu_off1", case)
        [closure] = c.closures(s, case)
        leg = w.legs(s, case)[0]
        note2 = w.note(s, wide, "edu_off1", case, body="another")[0]
        with pytest.raises(sa.exc.IntegrityError):
            with s.begin_nested():
                s.execute(
                    sa.text(
                        "INSERT INTO case_closures (case_id, office_id, ownership_id, closed_as, note_id, "
                        "close_leg_id) VALUES (:c, :o, :w, 'head', :n, :l)"
                    ),
                    {
                        "c": case.id,
                        "o": closure.office_id,
                        "w": closure.ownership_id,
                        "n": note2.id,
                        "l": leg.id,
                    },
                )
        s.rollback()


def test_closure_row_update_guard(wide, engine):
    with wide.Session() as s:
        case = c.disposed_case(s, wide)
        c.close(s, wide, "edu_off1", case)
        [closure] = c.closures(s, case)
        cid = closure.id
        for sql in (
            "UPDATE case_closures SET closed_as = 'head' WHERE id = :id",
            "UPDATE case_closures SET closed_at = now() - interval '1 day' WHERE id = :id",
            "UPDATE case_closures SET note_id = (SELECT id FROM case_notes WHERE id <> note_id LIMIT 1) "
            "WHERE id = :id",
        ):
            with pytest.raises(sa.exc.DBAPIError, match="only the reopening columns"):
                with s.begin_nested():
                    s.execute(sa.text(sql), {"id": cid})
        c.reopen(s, wide, "edu_head", case)
        for sql in (
            "UPDATE case_closures SET reopened_at = now() + interval '1 day' WHERE id = :id",
            "UPDATE case_closures SET reopen_kind = 'automatic', reopen_note_id = NULL, reopened_by_name = NULL, "
            "reopened_status = 'pending' WHERE id = :id",
        ):
            with pytest.raises(sa.exc.DBAPIError, match="reopened once"):
                with s.begin_nested():
                    s.execute(sa.text(sql), {"id": cid})
        s.rollback()
    with engine.connect() as conn:
        assert (
            conn.execute(
                sa.text("SELECT has_table_privilege('aslms_app', 'case_closures', 'DELETE')")
            ).scalar()
            is False
        )
        assert (
            conn.execute(
                sa.text("SELECT has_table_privilege('aslms_app', 'case_closures', 'UPDATE')")
            ).scalar()
            is True
        )
        assert conn.execute(
            sa.text("SELECT has_table_privilege('aslms_readonly', 'case_closures', 'SELECT')")
        ).scalar()


def test_closed_office_rest_widens_no_sight(wide):
    """Decision 6: resting the case at the department office does not let an officer without whole-department sight
    see it."""
    with wide.Session() as s:
        case = c.disposed_case(s, wide, officer=None)
        actor, admin = wide.actor(s, "edu_admin")
        own.allot(s, actor, admin, case, officer_user_id=w.uid(wide, "edu_off1"))
        c.close(s, wide, "edu_head", case)
        _, off2 = wide.actor(s, "edu_off2")
        assert visibility.access_basis(s, off2, case) == []
        assert (
            s.scalar(
                sa.select(CustodyHistory.reason)
                .where(CustodyHistory.case_id == case.id)
                .order_by(CustodyHistory.seq_no.desc())
                .limit(1)
            )
            == "closed"
        )
        assert s.get(Office, w.holder(s, case).holder_office_id).code == "EDU"
        s.rollback()
