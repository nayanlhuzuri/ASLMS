"""The case page's `workflow` block (design portal-workflow, decisions 4 and 20a): for every world user and case
state the flags equal the outcome of the write they stand for (`notes.add_note`, `documents.upload`,
`stages.set_stage`, each run in a savepoint that is rolled back); the two-department person gets `draft` only
through the membership that holds the file; a pool case offers nothing to write; reading writes nothing; a
hidden case stays 404."""

from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa

from aslms.domain.cases import Case
from aslms.domain.events import AuditLog, Event
from aslms.domain.reference import Role
from aslms.domain.workflow import CaseNote, CaseNoteDraft
from aslms.services import documents, notes, stages, workflow_actions
from aslms.services import ownership as own
from aslms.services.documents import UploadRefused
from aslms.services.scanner import FakeScanner
from aslms.services.storage import LocalStore
from aslms.services.visibility import NotVisibleCase
from aslms.services.workflow_common import WorkflowError
from tests import samplefiles as sf
from tests.db import docs_support as ds
from tests.db import workflow_support as w
from tests.db.world import USERS, add_membership, make_case


@pytest.fixture()
def wide(world):
    return w.widen(world)


def _note_outcome(s, world, key, case) -> str | None:
    actor, user = world.actor(s, key)
    try:
        with s.begin_nested() as sp:
            _, is_draft = notes.add_note(
                s, actor, user, case, kind="general", body="probe", visibility_="case_scope"
            )
            sp.rollback()
    except (WorkflowError, NotVisibleCase):
        return None
    return "draft" if is_draft else "permanent"


def _upload_outcome(s, world, key, case, store) -> bool:
    actor, user = world.actor(s, key)
    try:
        with s.begin_nested() as sp:
            documents.upload(
                s,
                actor,
                user,
                case,
                data=sf.text_pdf([f"probe {key}"]),
                filename="probe.pdf",
                doc_type="petition",
                doc_group=None,
                doc_date=date(2025, 1, 3),
                description="probe upload",
                visibility="case_scope",
                scanner=FakeScanner(),
                store=store,
                max_bytes=10_000_000,
            )
            sp.rollback()
    except NotVisibleCase:
        return False
    except UploadRefused as exc:
        assert exc.code == "not_working_on_case", exc.code
        return False
    return True


def _stage_outcome(s, world, key, case) -> bool:
    actor, user = world.actor(s, key)
    code = stages.catalogue(s)[1].code
    try:
        with s.begin_nested() as sp:
            stages.set_stage(s, actor, user, case, stage=code)
            sp.rollback()
    except NotVisibleCase:
        return False
    except WorkflowError as exc:
        return exc.code == "unchanged"
    return True


def _states(s, world) -> dict:
    pool = make_case(s)
    office_held = w.claimed_case(s, world, officer=None)
    off1_holds = w.claimed_case(s, world)
    sent_on = w.claimed_case(s, world)
    w.send(s, world, "edu_off1", sent_on, "health_off")  # a HEALTH officer holds an EDU case
    s.flush()
    return {"pool": pool, "office_held": office_held, "off1_holds": off1_holds, "sent_on": sent_on}


def test_flags_match_outcomes(wide, tmp_path):
    store = LocalStore(tmp_path / "store")
    keys = [*USERS, *w.EXTRA]
    with wide.Session() as s:
        cases = _states(s, wide)
        seen = set()
        for state, case in cases.items():
            for key in keys:
                _, user = wide.actor(s, key)
                flags = workflow_actions.available(s, user, case)
                expected = {
                    "note_mode": _note_outcome(s, wide, key, case),
                    "upload": _upload_outcome(s, wide, key, case, store),
                    "set_stage": _stage_outcome(s, wide, key, case),
                }
                assert flags == expected, (state, key)
                seen.add(flags["note_mode"])
        # the world covers every mode
        assert seen == {None, "draft", "permanent"}
        _, off1 = wide.actor(s, "edu_off1")
        _, hoff = wide.actor(s, "health_off")
        assert workflow_actions.available(s, off1, cases["off1_holds"])["note_mode"] == "draft"
        assert workflow_actions.available(s, off1, cases["sent_on"])["note_mode"] == "permanent"
        assert workflow_actions.available(s, hoff, cases["sent_on"])["note_mode"] == "draft"
        s.rollback()


def test_note_mode_draft_for_holder_membership_only(wide):
    with wide.Session() as s:
        person = wide.user(s, "edu_admin")
        add_membership(s, person, wide.office(s, "HEALTH"), Role.DEPT_OFFICER, "Under Secretary")
        h_actor, h_admin = wide.actor(s, "health_admin")
        held = make_case(s)
        own.claim(s, h_actor, h_admin, held, officer_user_id=person.id)
        edu_case = w.claimed_case(s, wide)  # EDU-owned, held by off1: the EDU membership writes permanently
        s.flush()
        _, person = wide.actor(s, "edu_admin")
        assert workflow_actions.available(s, person, held)["note_mode"] == "draft"
        assert workflow_actions.available(s, person, edu_case)["note_mode"] == "permanent"
        # once the HEALTH membership sends the file on, its notes are permanent
        w.send(s, wide, "edu_admin", held, "health_off")
        assert workflow_actions.available(s, person, held)["note_mode"] == "permanent"
        s.rollback()


def test_flags_null_on_pool_case(wide):
    with wide.Session() as s:
        pool = make_case(s)
        for key in ("root", "edu_admin", "edu_off1", "oversight"):
            _, user = wide.actor(s, key)
            assert workflow_actions.available(s, user, pool) == {
                "note_mode": None,
                "upload": False,
                "set_stage": False,
            }, key
        s.rollback()


def _counts(s, case_id) -> tuple:
    """Rows a read must not add: the case's audit rows (sign-in rows carry no case), every event, the case's
    notes and drafts."""
    return (
        s.scalar(sa.select(sa.func.count()).select_from(AuditLog).where(AuditLog.case_id == case_id)),
        s.scalar(sa.select(sa.func.count()).select_from(Event)),
        s.scalar(sa.select(sa.func.count()).select_from(CaseNote).where(CaseNote.case_id == case_id)),
        s.scalar(
            sa.select(sa.func.count()).select_from(CaseNoteDraft).where(CaseNoteDraft.case_id == case_id)
        ),
    )


@pytest.fixture()
def api(wide, tmp_path):
    client = ds.make_api(wide, tmp_path)
    yield client
    client.__exit__(None, None, None)


def test_flags_write_nothing(api, wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        s.commit()
        case_id = case.id
    with wide.Session() as s:
        before = _counts(s, case_id)
    for key in ("edu_off1", "edu_admin", "oversight"):
        r = api.get(f"/cases/{case_id}", headers=w.login(api, key))
        assert r.status_code == 200, r.text
    off1 = api.get(f"/cases/{case_id}", headers=w.login(api, "edu_off1")).json()["workflow"]
    assert off1 == {"note_mode": "draft", "upload": True, "set_stage": True}
    admin = api.get(f"/cases/{case_id}", headers=w.login(api, "edu_admin")).json()["workflow"]
    assert admin == {"note_mode": "permanent", "upload": True, "set_stage": True}
    reader = api.get(f"/cases/{case_id}", headers=w.login(api, "oversight")).json()["workflow"]
    assert reader == {"note_mode": None, "upload": False, "set_stage": False}
    with wide.Session() as s:
        _, off1_user = wide.actor(s, "edu_off1")
        workflow_actions.available(s, off1_user, s.get(Case, case_id))
        s.commit()
    with wide.Session() as s:
        assert _counts(s, case_id) == before


def test_overview_hidden_case_404(api, wide):
    with wide.Session() as s:
        case = w.claimed_case(s, wide)
        s.commit()
        case_id = case.id
    assert api.get(f"/cases/{case_id}", headers=w.login(api, "health_off")).status_code == 404
    assert api.get(f"/cases/{case_id}", headers=w.login(api, "fin_off")).status_code == 404
