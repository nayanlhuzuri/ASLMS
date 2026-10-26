"""A committed test world for the recommend-and-claim tests: the seeded database plus

    GOA ─┬─ EDU ─┬─ EDU-DSE
         │       ├─ EDU-DHE
         │       └─ EDU-SC (unit: the department's standing counsel)
         ├─ HEALTH
         └─ CENTRAL (central)

and one user per role that the tests act as. Users are inserted with one shared password hash (hashing once
keeps the fixture fast), each with its primary membership (design `user-memberships`); `PW` signs in through
the API. `add_membership` gives a login a further membership (the two-department person of the membership
tests is the EDU admin with a HEALTH officer membership)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from aslms.domain.cases import Case, CaseStatus, FirstSeenSource
from aslms.domain.courts import Court
from aslms.domain.org import Office, User, UserMembership
from aslms.domain.reference import OfficeKind, Role
from aslms.services import access, memberships
from aslms.services.audit import Actor
from aslms.services.refno import allocate_case_ref_no
from aslms.services.seed import seed_all
from aslms.services.users import hash_password
from tests.db.conftest import wipe

PW = "correct-horse-battery-7"

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
        return access.actor_for(u), u

    def membership(self, s: Session, key: str, office_code: str | None = None) -> UserMembership:
        """The user's active membership (at `office_code`'s department when given, else the primary)."""
        u = self.user(s, key)
        ms = access.active_memberships(s, u)
        if office_code is None:
            return next(m for m in ms if m.is_primary)
        dept = access.department_of(s, self.office(s, office_code))
        return next(m for m in ms if m.department_id == (dept.id if dept else None))


def add_membership(s: Session, user: User, office: Office, role: Role, designation: str | None = None):
    """A further membership for a login, written directly (tests only; no authority check)."""
    return memberships.insert_membership(
        s, Actor.system("test"), user, office=office, role=role, designation=designation, audit=False
    )


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
            memberships.insert_membership(
                s, Actor.system("test"), u, office=w.offices[code], role=role, audit=False
            )
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
        ref_no=allocate_case_ref_no(s, court),
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


DIVISION_BENCH = "HONOURABLE THE CHIEF JUSTICE, HONOURABLE MR. JUSTICE SOUMITRA SAIKIA"
SINGLE_BENCH = "HONOURABLE MR. JUSTICE SOUMITRA SAIKIA"
OTHER_BENCH = "HONOURABLE MRS. JUSTICE SUSMITA PHUKAN KHAUND"


def add_listing(
    s: Session, case: Case, list_date: date, *, court_no: str = "3", bench: str | None = SINGLE_BENCH
):
    """One cause-list entry of `case` on `list_date` in a court and before a bench, written directly (the
    filter tests' listings: design `portal-filters`)."""
    from aslms.domain.causelists import Causelist, CauselistEntry, EntrySource, ListSource, ListType

    court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
    cl = s.scalar(
        sa.select(Causelist).where(
            Causelist.list_date == list_date, Causelist.source == ListSource.GHC_WEBSITE
        )
    )
    if cl is None:
        cl = Causelist(
            court_id=court.id, list_date=list_date, list_type=ListType.DAILY, source=ListSource.GHC_WEBSITE
        )
        s.add(cl)
        s.flush()
    n = int(s.scalar(sa.select(sa.func.count()).select_from(CauselistEntry)) or 0) + 1
    e = CauselistEntry(
        causelist_id=cl.id,
        sr_no=n,
        cnr=case.cnr,
        case_id=case.id,
        case_no_text=case.case_no_text,
        court_no=court_no,
        bench_text=bench,
        petitioner_text=case.petitioner_summary,
        source=EntrySource.PDF_PARSE,
    )
    s.add(e)
    s.flush()
    return e
