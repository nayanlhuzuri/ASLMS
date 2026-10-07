"""Permanent notes (design custody-workflow, decisions 14, 16, 26): notes by anyone but the personal holder are
permanent at once; `seq_no` under concurrency; the author snapshot is frozen and taken from the acting
membership; UPDATE and DELETE on `case_notes` and `case_note_attachments` are refused; the correction rules."""

from __future__ import annotations

import threading

import pytest
import sqlalchemy as sa

from aslms.db.base import APPEND_ONLY_TABLES
from aslms.domain.cases import Case
from aslms.domain.reference import EventType, Role
from aslms.domain.workflow import CaseNote, CaseNoteAttachment
from aslms.services import ownership as own
from aslms.services.workflow_common import WorkflowError
from tests.db import workflow_support as w
from tests.db.world import add_membership, make_case


@pytest.fixture()
def wide(world):
    return w.widen(world)


def test_non_holder_notes_are_permanent(wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        w.send(s, wide, "edu_off1", case, "health_off")
        n, is_draft = w.note(s, wide, "edu_admin", case, body="instruction to HEALTH", kind="instruction")
        assert not is_draft and n.ref_no.startswith("ASLMS/EDU/NOTE/") and n.seq_no == 1
        assert n.custody_leg_id == w.holder(s, case).current_leg_id and n.drafted_at is None
        n2, is_draft = w.note(s, wide, "edu_off1", case, body="allotted officer's note")
        assert not is_draft and n2.seq_no == 2
        ev = w.events(s, case.id, EventType.NOTE_ADDED)
        assert len(ev) == 2 and "instruction to HEALTH" not in str(ev[0].payload)
        audit = w.audits(s, "note.added", case.id)
        assert len(audit) == 2 and "instruction to HEALTH" not in str(audit[0].after)
        assert audit[0].after["body"]["length"] == len("instruction to HEALTH")
        s.rollback()


def test_notes_need_a_claimed_case_and_a_working_basis(wide):
    with wide.Session() as s:
        pool = make_case(s)
        with pytest.raises(WorkflowError) as e:
            w.note(s, wide, "root", pool)
        assert e.value.code == "not_owned"
        case = w.claimed_case(s, wide)
        with pytest.raises(Exception) as e:
            w.note(s, wide, "health_off", case)  # HEALTH has no basis on an EDU case
        assert (
            getattr(e.value, "code", None) == "not_working_on_case"
            or type(e.value).__name__ == "NotVisibleCase"
        )
        with pytest.raises(WorkflowError) as e:
            w.note(s, wide, "edu_off1", case, body="   ")
        assert e.value.code == "bad_field"
        with pytest.raises(WorkflowError):
            w.note(s, wide, "edu_admin", case, kind="correction")  # retired kind
        with pytest.raises(WorkflowError):
            w.note(s, wide, "edu_admin", case, visibility_="public")
        s.rollback()


def test_seq_no_under_concurrency(wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        s.commit()
        case_id = case.id
    errors: list[Exception] = []

    def write(key: str, i: int):
        try:
            with wide.Session() as s:
                w.note(s, wide, key, s.get(Case, case_id), body=f"{key} {i}")
                s.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=write, args=(k, i)) for i in range(3) for k in ("edu_admin", "edu_head")
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    with wide.Session() as s:
        assert [n.seq_no for n in w.case_notes(s, case_id)] == [1, 2, 3, 4, 5, 6]


def test_author_snapshot_frozen_and_from_the_acting_membership(wide):
    with wide.Session() as s:
        add_membership(
            s, wide.user(s, "edu_admin"), wide.office(s, "HEALTH"), Role.DEPT_OFFICER, "Under Secretary"
        )
        h_actor, h_admin = wide.actor(s, "health_admin")
        case = make_case(s)
        own.claim(s, h_actor, h_admin, case, officer_user_id=wide.user(s, "edu_admin").id)
        # the person holds the HEALTH file through the HEALTH membership: a draft; the HEALTH admin writes a note
        draft, is_draft = w.note(s, wide, "edu_admin", case, body="as HEALTH officer")
        assert is_draft and draft.membership_id == wide.membership(s, "edu_admin", "HEALTH").id
        assert draft.actor_office_code == "HEALTH" and draft.actor_designation == "Under Secretary"
        w.send(s, wide, "edu_admin", case, "health_off", to_office=None)
        n = [x for x in w.case_notes(s, case.id) if x.body == "as HEALTH officer"][0]
        assert n.actor_office_code == "HEALTH" and n.actor_designation == "Under Secretary"
        assert n.ref_no.startswith("ASLMS/HEALTH/NOTE/") and n.author_role == "dept_officer"
        m = wide.membership(s, "edu_admin", "HEALTH")
        m.designation = "Deputy Secretary"
        s.flush()
        s.refresh(n)
        assert n.actor_designation == "Under Secretary"
        s.rollback()


def test_update_and_delete_refused_on_notes_and_attachments(wide, engine):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        n, _ = w.note(s, wide, "edu_admin", case)
        s.commit()
        note_id = n.id
    for stmt in (
        sa.text("UPDATE case_notes SET body = 'x' WHERE id = :id"),
        sa.text("DELETE FROM case_notes WHERE id = :id"),
    ):
        with engine.connect() as conn, pytest.raises(sa.exc.DBAPIError):
            conn.execute(stmt, {"id": note_id})
    with engine.connect() as conn:
        trig = conn.execute(
            sa.text(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'case_note_attachments'::regclass "
                "AND tgname = 'case_note_attachments_append_only'"
            )
        ).scalar()
        assert trig == 1
        assert not conn.execute(
            sa.text("SELECT has_table_privilege('aslms_app', 'case_note_attachments', 'UPDATE')")
        ).scalar()
        assert not conn.execute(
            sa.text("SELECT has_table_privilege('aslms_app', 'case_notes', 'DELETE')")
        ).scalar()
    assert CaseNoteAttachment.__tablename__ in APPEND_ONLY_TABLES


def test_correction_rules(wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        w.send(s, wide, "edu_off1", case, "fin_off")  # off1 keeps the allotment, no longer the holder
        original, _ = w.note(s, wide, "edu_off1", case, body="first", kind="opinion")
        # the holder from FIN sees the note but may not correct it; the department's nodal officer may
        with pytest.raises(WorkflowError) as e:
            w.note(s, wide, "fin_off", case, body="fix", supersedes=original.ref_no, kind=None)
        assert e.value.code == "not_author" and e.value.http_status == 403
        with pytest.raises(WorkflowError) as e:
            w.note(
                s,
                wide,
                "edu_off1",
                case,
                body="fix",
                supersedes=original.ref_no,
                kind=None,
                visibility_="private_to_office",
            )
        assert e.value.code == "bad_field"
        with pytest.raises(WorkflowError):
            w.note(s, wide, "edu_off1", case, body="fix", supersedes=original.ref_no, kind="general")
        corr, _ = w.note(s, wide, "edu_off1", case, body="corrected", supersedes=original.ref_no, kind=None)
        assert corr.supersedes_id == original.id and corr.kind.value == "opinion"
        with pytest.raises(WorkflowError) as e:
            w.note(s, wide, "edu_admin", case, body="again", supersedes=original.ref_no, kind=None)
        assert e.value.code == "already_superseded" and e.value.http_status == 409
        corr2, _ = w.note(s, wide, "edu_admin", case, body="nodal fix", supersedes=str(corr.id), kind=None)
        assert corr2.supersedes_id == corr.id
        _, off1 = wide.actor(s, "edu_off1")
        from aslms.services import notes

        page = notes.list_for_case(s, off1, case)
        by_ref = {n["ref_no"]: n for n in page.items}
        assert by_ref[original.ref_no]["superseded_by"]["ref_no"] == corr.ref_no
        assert notes.list_for_case(s, off1, case, include_superseded=False).total == 1
        assert (
            s.scalar(sa.select(sa.func.count()).select_from(CaseNote).where(CaseNote.case_id == case.id)) == 3
        )
        s.rollback()
