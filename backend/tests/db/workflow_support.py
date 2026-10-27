"""Shared helpers for the custody-workflow tests over `tests/db/world.py`: a wider world (a HEALTH directorate with
an officer, a FIN department with an officer), a claimed EDU case held by an EDU officer, sending and recalling
through the service, and sign-in for the extra users."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from aslms.domain.cases import Case
from aslms.domain.events import AuditLog, Event
from aslms.domain.org import Office, User
from aslms.domain.reference import EventType, OfficeKind, Role
from aslms.domain.workflow import CaseNote, CaseNoteDraft, Custody, CustodyHistory
from aslms.services import custody, memberships, notes
from aslms.services import ownership as own
from aslms.services.audit import Actor
from aslms.services.users import hash_password
from tests.db.auth_support import bearer
from tests.db.world import PW, World, make_case

EXTRA = {
    # key: (email, role, office code, designation)
    "health_dir": ("user.healthdir@example.org", Role.DIRECTORATE_USER, "HEALTH-DHS", "Deputy Director"),
    "fin_off": ("off.fin@example.org", Role.DEPT_OFFICER, "FIN", "Under Secretary"),
}


def widen(world: World) -> World:
    """Adds HEALTH-DHS (a directorate of HEALTH), FIN (a department) and their officers to the world."""
    with world.Session() as s:
        health = world.office(s, "HEALTH")
        goa = world.office(s, "GOA")
        for code, name, kind, parent in (
            ("HEALTH-DHS", "Health Services", OfficeKind.DIRECTORATE, health),
            ("FIN", "Finance", OfficeKind.DEPARTMENT, goa),
        ):
            o = Office(code=code, name=name, kind=kind, parent_id=parent.id, path=f"{parent.path}/{code}")
            s.add(o)
            s.flush()
            world.offices[code] = o
        pw_hash = hash_password(PW)
        for key, (email, role, code, designation) in EXTRA.items():
            u = User(
                email=email,
                password_hash=pw_hash,
                full_name=key.replace("_", " ").title(),
                role=role,
                office_id=world.offices[code].id,
            )
            s.add(u)
            s.flush()
            memberships.insert_membership(
                s,
                Actor.system("test"),
                u,
                office=world.offices[code],
                role=role,
                designation=designation,
                audit=False,
            )
            world.users[key] = u
        s.commit()
    return world


def email_of(key: str) -> str:
    from tests.db.world import USERS

    return EXTRA[key][0] if key in EXTRA else USERS[key][0]


def login(api: TestClient, key: str) -> dict:
    return bearer(api, email_of(key), PW)


def claimed_case(s: Session, world: World, *, officer: str | None = "edu_off1", case_no=None) -> Case:
    """An EDU case claimed by the EDU admin, allotted to `officer` (who then holds the file personally)."""
    case = make_case(s, case_no=case_no)
    actor, admin = world.actor(s, "edu_admin")
    kw = {"officer_user_id": world.user(s, officer).id} if officer else {}
    own.claim(s, actor, admin, case, **kw)
    return case


def send(s: Session, world: World, key: str, case: Case, to: str, *, to_office: str | None = None, **kw):
    actor, user = world.actor(s, key)
    kw.setdefault("pending_action_", "parawise_comments")
    kw.setdefault("remark", f"please act ({key} to {to})")
    return custody.send(s, actor, user, case, to_membership=world.membership(s, to, to_office).id, **kw)


def recall(s: Session, world: World, key: str, case: Case, remark: str = "calling the file back"):
    actor, user = world.actor(s, key)
    return custody.recall(s, actor, user, case, remark=remark)


def note(s: Session, world: World, key: str, case: Case, body: str = "a note", **kw):
    actor, user = world.actor(s, key)
    kw.setdefault("kind", "general")
    kw.setdefault("visibility_", "case_scope")
    return notes.add_note(s, actor, user, case, body=body, **kw)


def holder(s: Session, case: Case) -> Custody:
    return s.execute(
        sa.select(Custody).where(Custody.case_id == case.id).execution_options(populate_existing=True)
    ).scalar_one()


def legs(s: Session, case: Case) -> list[CustodyHistory]:
    return list(
        s.scalars(
            sa.select(CustodyHistory).where(CustodyHistory.case_id == case.id).order_by(CustodyHistory.seq_no)
        ).all()
    )


def case_notes(s: Session, case_id) -> list[CaseNote]:
    return list(
        s.scalars(sa.select(CaseNote).where(CaseNote.case_id == case_id).order_by(CaseNote.seq_no)).all()
    )


def drafts(s: Session, case_id) -> list[CaseNoteDraft]:
    return list(
        s.scalars(
            sa.select(CaseNoteDraft)
            .where(CaseNoteDraft.case_id == case_id)
            .order_by(CaseNoteDraft.created_at, CaseNoteDraft.id)
        ).all()
    )


def events(s: Session, case_id, kind: EventType) -> list[Event]:
    """In write order. `occurred_at` is the transaction's `now()`, so every event of one transaction ties on it
    and Postgres returns ties in heap order; the UUID v7 id, issued in insertion order, breaks the tie."""
    return list(
        s.scalars(
            sa.select(Event)
            .where(Event.case_id == case_id, Event.type == kind)
            .order_by(Event.occurred_at, Event.id)
        ).all()
    )


def audits(s: Session, action: str, case_id=None) -> list[AuditLog]:
    stmt = sa.select(AuditLog).where(AuditLog.action == action)
    if case_id is not None:
        stmt = stmt.where(AuditLog.case_id == case_id)
    return list(s.scalars(stmt.order_by(AuditLog.created_at, AuditLog.id)).all())


def uid(world: World, key: str) -> uuid.UUID:
    return world.users[key].id


def in_days(n: int) -> date:
    from aslms.services.workflow_common import today_ist

    return today_ist() + timedelta(days=n)
