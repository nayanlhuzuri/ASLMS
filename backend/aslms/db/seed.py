"""Bootstrap rows: the `ref_*` code sets, designations, Assam and its districts (seed_ref.py), the structural
offices, the Gauhati High Court establishment, and one operator account. Idempotent: safe to run again; the
returned counts say what a run inserted. Department offices, counsel codes, patterns and keywords are compiled
with the departments and entered through Administration (or a later seed file), not here."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.core.config import get_settings
from aslms.core.logging import get_logger
from aslms.core.security import hash_password
from aslms.db.seed_ref import seed_assam, seed_designations, seed_ref_tables
from aslms.domain.org import Office, OfficeKind, Role, User
from aslms.domain.reference import Court, CourtLevel

log = get_logger(__name__)


@dataclass(frozen=True)
class OfficeSeed:
    code: str
    name: str
    kind: OfficeKind
    parent: str | None = None


STRUCTURAL_OFFICES: tuple[OfficeSeed, ...] = (
    OfficeSeed("STATE", "Office of the Chief Minister / Chief Secretary", OfficeKind.STATE_OFFICE),
    OfficeSeed("CENTRAL", "Central Monitoring Cell (Legal Case Monitoring Portal)", OfficeKind.CENTRAL_CELL),
    OfficeSeed("AG", "Office of the Advocate General, Assam", OfficeKind.COUNSEL_OFFICE),
)

COURTS: tuple[dict[str, str], ...] = (
    {
        "est_code": "GAHC01",
        "name": "Gauhati High Court, Principal Seat",
        "state_code": "6",
        "bench_location": "Guwahati",
    },
)


def upsert_office(session: Session, seed: OfficeSeed) -> Office:
    office = session.scalar(select(Office).where(Office.code == seed.code))
    parent = session.scalar(select(Office).where(Office.code == seed.parent)) if seed.parent else None
    path = f"{parent.path}/{seed.code}" if parent else seed.code
    if office is None:
        office = Office(
            code=seed.code, name=seed.name, kind=seed.kind, parent_id=parent.id if parent else None, path=path
        )
        session.add(office)
        session.flush()
        log.info("office created", code=seed.code)
    else:
        office.name, office.kind, office.path = seed.name, seed.kind, path
        office.parent_id = parent.id if parent else None
    return office


def upsert_court(session: Session, row: dict[str, str]) -> Court:
    court = session.scalar(select(Court).where(Court.est_code == row["est_code"]))
    if court is None:
        court = Court(court_level=CourtLevel.HC, **row)
        session.add(court)
        session.flush()
        log.info("court created", est_code=row["est_code"])
    else:
        for k, v in row.items():
            setattr(court, k, v)
    return court


def upsert_operator(session: Session) -> User:
    settings = get_settings()
    central = session.scalar(select(Office).where(Office.code == "CENTRAL"))
    assert central is not None
    user = session.scalar(select(User).where(User.email == settings.seed_admin_email.lower()))
    if user is None:
        user = User(
            email=settings.seed_admin_email.lower(),
            password_hash=hash_password(settings.seed_admin_password.get_secret_value()),
            full_name="Central Operator",
            designation="Operator, Central Monitoring Cell",
            office_id=central.id,
            role=Role.CENTRAL_OPERATOR,
            must_confirm_profile=False,
        )
        session.add(user)
        session.flush()
        log.info("operator account created", email=user.email)
    return user


def run_seed(session: Session) -> dict[str, int]:
    counts = {
        "ref_rows_inserted": seed_ref_tables(session),
        "designations_inserted": seed_designations(session),
        "districts_inserted": seed_assam(session),
    }
    for seed in STRUCTURAL_OFFICES:
        upsert_office(session, seed)
    for row in COURTS:
        upsert_court(session, row)
    upsert_operator(session)
    return {**counts, "offices": len(STRUCTURAL_OFFICES), "courts": len(COURTS), "users": 1}
