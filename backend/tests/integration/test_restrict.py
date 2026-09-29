"""DB_STANDARD §6 / §0: rows of legal significance are never deleted (the database refuses it), and masters are
deactivated, never deleted, so what depended on them stays."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from aslms.domain.cases import Case
from aslms.domain.org import Role
from aslms.domain.ownership import CaseOfficeScore, CounselCode
from aslms.domain.workflow import CaseNote, NoteKind, NoteVisibility
from aslms.services import notes as notes_svc
from aslms.services.audit import Actor
from aslms.services.scope import principal_for
from tests.integration.helpers import auth, login


def test_deleting_a_case_with_a_note_is_refused(world, db: Session) -> None:
    case = db.scalar(sa.select(Case).limit(1))
    user = world["users"]["edu_admin"]
    notes_svc.add_note(
        db,
        Actor.of(user, None, None),
        principal_for(db, user),
        case,
        notes_svc.NoteIn(kind=NoteKind.GENERAL, body="keep me", visibility=NoteVisibility.CASE_SCOPE),
    )
    db.commit()
    assert db.scalar(sa.select(sa.func.count()).select_from(CaseNote).where(CaseNote.case_id == case.id)) == 1
    with pytest.raises(sa.exc.IntegrityError):
        db.execute(sa.text("DELETE FROM cases WHERE id = :id"), {"id": case.id})
    db.rollback()
    assert db.get(Case, case.id) is not None


def test_deleting_a_case_listed_in_a_cause_list_is_refused(world, db: Session) -> None:
    case = db.scalar(sa.select(Case).limit(1))
    with pytest.raises(sa.exc.IntegrityError):
        db.execute(sa.text("DELETE FROM cases WHERE id = :id"), {"id": case.id})
    db.rollback()


def test_deactivating_a_counsel_code_keeps_its_scores(client: TestClient, world, db: Session) -> None:
    code = db.scalar(sa.select(CounselCode).where(CounselCode.code == "GA, ASSAM"))
    scores_before = db.scalar(sa.select(sa.func.count()).select_from(CaseOfficeScore))
    assert scores_before > 0, "the fixture list carries the code, so cases were scored"
    tokens = login(client, "edu.admin@t.in")
    r = client.delete(f"/api/v1/mapping/codes/{code.id}", headers=auth(tokens))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == str(code.id) and r.json()["is_active"] is False
    db.expire_all()
    row = db.get(CounselCode, code.id)
    assert row is not None and row.is_active is False and row.deactivated_at is not None
    assert db.scalar(sa.select(sa.func.count()).select_from(CaseOfficeScore)) == scores_before
    assert world["users"]["edu_admin"].role == Role.DEPT_ADMIN
