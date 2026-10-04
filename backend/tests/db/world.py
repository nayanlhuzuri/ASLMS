"""A committed test world for the recommend-and-claim tests: the seeded database plus

    GOA ─┬─ EDU ─┬─ EDU-DSE
         │       ├─ EDU-DHE
         │       └─ EDU-SC (unit: the department's standing counsel)
         ├─ HEALTH
         └─ CENTRAL (central)

and one user per role that the tests act as. Users are inserted with one shared password hash (hashing once
keeps the fixture fast); `PW` signs in through the API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from aslms.domain.cases import Case, CaseStatus, FirstSeenSource
from aslms.domain.courts import Court
from aslms.domain.org import Office, User
from aslms.domain.reference import OfficeKind, Role
from aslms.services import access
from aslms.services.audit import Actor
from aslms.services.refno import allocate_ref_no
from aslms.services.seed import seed_all
from aslms.services.users import hash_password
from tests.db.conftest import wipe

PW = "correct-horse-battery"

USERS = {
    # key: (email, role, office code)
    "root": ("root@example.org", Role.SUPER_ADMIN, "GOA"),
    "edu_admin": ("admin.edu@example.org", Role.DEPT_ADMIN, "EDU"),
    "edu_head": ("head.edu@example.org", Role.DEPT_HEAD, "EDU"),
    "edu_off1": ("off1.edu@example.org", Role.DEPT_OFFICER, "EDU"),
    "edu_off2": ("off2.edu@example.org", Role.DEPT_OFFICER, "EDU"),
    "dse_user": ("user.dse@example.org", Role.DIRECTORATE_USER, "EDU-DSE"),
    "dhe_user": ("user.dhe@example.org", Role.DIRECTORATE_USER, "EDU-DHE"),
    "edu_reviewer": ("reviewer.edu@example.org", Role.REFERRAL_REVIEWER, "EDU"),
    "edu_counsel": ("counsel.edu@example.org", Role.STANDING_COUNSEL, "EDU-SC"),
    "edu_auditor": ("auditor@example.org", Role.AUDITOR, "GOA"),
    "health_admin": ("admin.health@example.org", Role.DEPT_ADMIN, "HEALTH"),
    "health_off": ("off.health@example.org", Role.DEPT_OFFICER, "HEALTH"),
    "central_op": ("operator@example.org", Role.CENTRAL_OPERATOR, "CENTRAL"),
    "oversight": ("oversight@example.org", Role.STATE_OVERSIGHT, "GOA"),
}


@dataclass
class World:
    Session: sessionmaker
    offices: dict[str, Office] = field(default_factory=dict)
    users: dict[str, User] = field(default_factory=dict)

    def office(self, s: Session, code: str) -> Office:
        return s.scalar(sa.select(Office).where(Office.code == code))

    def user(self, s: Session, key: str) -> User:
        return s.get(User, self.users[key].id)

    def actor(self, s: Session, key: str) -> tuple[Actor, User]:
        u = self.user(s, key)
        return access.actor_for(u, s.get(Office, u.office_id)), u


def build_world(engine) -> World:
    with engine.begin() as conn:
        wipe(conn)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    w = World(Session)
    with Session() as s:
        seed_all(s)
        goa = s.scalar(sa.select(Office).where(Office.code == "GOA"))

        def office(code, name, kind, parent):
            o = Office(code=code, name=name, kind=kind, parent_id=parent.id, path=f"{parent.path}/{code}")
            s.add(o)
            s.flush()
            w.offices[code] = o
            return o

        w.offices["GOA"] = goa
        edu = office("EDU", "Education", OfficeKind.DEPARTMENT, goa)
        office("EDU-DSE", "Secondary Education", OfficeKind.DIRECTORATE, edu)
        office("EDU-DHE", "Higher Education", OfficeKind.DIRECTORATE, edu)
        office("EDU-SC", "Standing Counsel, Education", OfficeKind.UNIT, edu)
        office("HEALTH", "Health", OfficeKind.DEPARTMENT, goa)
        office("CENTRAL", "Central Cell", OfficeKind.CENTRAL, goa)
        pw_hash = hash_password(PW)
        for key, (email, role, code) in USERS.items():
            u = User(
                email=email,
                password_hash=pw_hash,
                full_name=key.replace("_", " ").title(),
                role=role,
                office_id=w.offices[code].id,
            )
            s.add(u)
            s.flush()
            w.users[key] = u
        s.commit()
    return w


_seq = {"n": 0}


def make_case(
    s: Session,
    *,
    cnr: str | None = None,
    case_no: str | None = None,
    status: CaseStatus = CaseStatus.PENDING,
    pet: str | None = None,
    res: str | None = None,
    next_hearing: date | None = None,
    source: FirstSeenSource = FirstSeenSource.CAUSELIST,
) -> Case:
    _seq["n"] += 1
    n = _seq["n"]
    court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
    case = Case(
        cnr=cnr if cnr is not None else f"ASHC01{n:06d}2025",
        court_id=court.id,
        case_no_text=case_no or f"WP(C)/{n}/2025",
        ref_no=allocate_ref_no(s, "GOA", "CASE"),
        status=status,
        petitioner_summary=pet,
        respondent_summary=res,
        next_hearing_date=next_hearing,
        first_seen_source=source,
        is_provisional=False,
    )
    s.add(case)
    s.flush()
    return case
