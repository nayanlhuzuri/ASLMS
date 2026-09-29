"""DEVELOPMENT / DEMONSTRATION DATA ONLY — refused when APP_ENV=prod.

A few departments, the counsel codes seen most often in the Gauhati High Court cause lists, some name patterns,
and one account per role, so the portal can be exercised end to end before the departments supply the real
code-to-department mapping (decisions log, Next item 3). Nothing here is a court identifier: CNRs only ever
come from cause lists and NAPIX. Idempotent."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.core.config import get_settings
from aslms.core.security import hash_password
from aslms.db.seed import OfficeSeed, run_seed, upsert_office
from aslms.domain.org import Designation, Office, OfficeKind, Role, User
from aslms.domain.ownership import CounselCode, OfficeKeyword, OfficeNamePattern, PatternKind

DEMO_PASSWORD = "Demo@2026pass"

DEPARTMENTS: tuple[OfficeSeed, ...] = (
    OfficeSeed("SEC-EDU", "Secondary Education Department", OfficeKind.DEPARTMENT),
    OfficeSeed("DSE", "Directorate of Secondary Education", OfficeKind.DIRECTORATE, "SEC-EDU"),
    OfficeSeed("ELEM-EDU", "Elementary Education Department", OfficeKind.DEPARTMENT),
    OfficeSeed("HIGHER-EDU", "Higher Education Department", OfficeKind.DEPARTMENT),
    OfficeSeed("FIN", "Finance Department", OfficeKind.DEPARTMENT),
    OfficeSeed("REV", "Revenue and Disaster Management Department", OfficeKind.DEPARTMENT),
    OfficeSeed("HEALTH", "Health and Family Welfare Department", OfficeKind.DEPARTMENT),
    OfficeSeed("DHS", "Directorate of Health Services", OfficeKind.DIRECTORATE, "HEALTH"),
    OfficeSeed("HOME", "Home and Political Department", OfficeKind.DEPARTMENT),
    OfficeSeed("FOREST", "Environment and Forest Department", OfficeKind.DEPARTMENT),
    OfficeSeed("PWD", "Public Works (Roads) Department", OfficeKind.DEPARTMENT),
    OfficeSeed("TRANSPORT", "Transport Department", OfficeKind.DEPARTMENT),
    OfficeSeed("PNRD", "Panchayat and Rural Development Department", OfficeKind.DEPARTMENT),
    OfficeSeed("PHE", "Public Health Engineering Department", OfficeKind.DEPARTMENT),
    OfficeSeed("SEC-EDU-SC", "Standing Counsel, Secondary Education", OfficeKind.COUNSEL_OFFICE, "SEC-EDU"),
)

# (code as printed, office code, weight, generic State code)
CODES: tuple[tuple[str, str, float, bool], ...] = (
    ("SC, SEC. EDU.", "SEC-EDU", 0.95, False),
    ("SC, EDU", "SEC-EDU", 0.90, False),
    ("SC, SSA", "ELEM-EDU", 0.90, False),
    ("SC, ELEM. EDU", "ELEM-EDU", 0.95, False),
    ("SC, HIGHER EDU", "HIGHER-EDU", 0.95, False),
    ("SC, HIGHER EDUCATION", "HIGHER-EDU", 0.95, False),
    ("SC, FINANCE", "FIN", 0.95, False),
    ("SC, FINANCE DEPTT.", "FIN", 0.95, False),
    ("SC, FINANCE AND TAXATION", "FIN", 0.95, False),
    ("SC, REVENUE", "REV", 0.95, False),
    ("SC, HEALTH", "HEALTH", 0.95, False),
    ("SC, HEALTH AND F W", "HEALTH", 0.95, False),
    ("SC, NHM", "DHS", 0.85, False),
    ("SC, FOREST", "FOREST", 0.95, False),
    ("SC, PWD", "PWD", 0.95, False),
    ("SC, PWD ROAD", "PWD", 0.95, False),
    ("SC, TRANSPORT", "TRANSPORT", 0.95, False),
    ("SC, A S T C", "TRANSPORT", 0.85, False),
    ("SC, P AND R.D.", "PNRD", 0.95, False),
    ("SC, P H E", "PHE", 0.95, False),
    ("PP, ASSAM", "HOME", 0.95, True),
    ("GA, ASSAM", "HOME", 0.95, True),
)

PATTERNS: tuple[tuple[str, str, float], ...] = (
    ("DIRECTOR OF SECONDARY EDUCATION", "DSE", 0.80),
    ("SECONDARY EDUCATION DEPARTMENT", "SEC-EDU", 0.80),
    ("DIRECTOR OF ELEMENTARY EDUCATION", "ELEM-EDU", 0.80),
    ("DIRECTOR OF HIGHER EDUCATION", "HIGHER-EDU", 0.80),
    ("DIRECTOR OF HEALTH SERVICES", "DHS", 0.80),
    ("PRINCIPAL CHIEF CONSERVATOR OF FORESTS", "FOREST", 0.80),
    ("COMMISSIONER OF TRANSPORT", "TRANSPORT", 0.80),
)

KEYWORDS: tuple[tuple[str, str, float], ...] = (
    ("SECONDARY EDUCATION", "SEC-EDU", 0.40),
    ("INSPECTOR OF SCHOOLS", "SEC-EDU", 0.40),
    ("HEALTH SERVICES", "HEALTH", 0.40),
    ("DIVISIONAL FOREST OFFICER", "FOREST", 0.40),
)

# (email, name, designation, office code, role)
USERS: tuple[tuple[str, str, str, str, Role], ...] = (
    (
        "cs.office@aslms.local",
        "State Oversight User",
        "Joint Secretary, CS Office",
        "STATE",
        Role.STATE_OVERSIGHT,
    ),
    ("auditor@aslms.local", "Audit User", "Deputy Accountant General", "CENTRAL", Role.AUDITOR),
    ("edu.admin@aslms.local", "Education Nodal Officer", "Under Secretary", "SEC-EDU", Role.DEPT_ADMIN),
    ("edu.head@aslms.local", "Education Secretary", "Commissioner and Secretary", "SEC-EDU", Role.DEPT_HEAD),
    ("edu.officer@aslms.local", "Education Case Officer", "Section Officer", "SEC-EDU", Role.DEPT_OFFICER),
    ("dse.user@aslms.local", "DSE Legal Cell", "Deputy Director", "DSE", Role.DIRECTORATE_USER),
    (
        "edu.counsel@aslms.local",
        "Standing Counsel Education",
        "Standing Counsel",
        "SEC-EDU-SC",
        Role.STANDING_COUNSEL,
    ),
    ("health.admin@aslms.local", "Health Nodal Officer", "Under Secretary", "HEALTH", Role.DEPT_ADMIN),
    ("fin.admin@aslms.local", "Finance Nodal Officer", "Under Secretary", "FIN", Role.DEPT_ADMIN),
)


def run_demo_seed(session: Session) -> dict[str, int]:
    if get_settings().is_prod:
        raise RuntimeError("demo data is not allowed in production")
    run_seed(session)
    offices: dict[str, Office] = {}
    for seed in DEPARTMENTS:
        offices[seed.code] = upsert_office(session, seed)
    for o in session.scalars(select(Office)):
        offices.setdefault(o.code, o)
    for code, office, weight, generic in CODES:
        row = session.scalar(select(CounselCode).where(CounselCode.code == code))
        if row is None:
            session.add(
                CounselCode(
                    code=code,
                    office_id=offices[office].id,
                    weight=weight,
                    is_generic_state=generic,
                    notes="demo mapping",
                )
            )
    for pattern, office, weight in PATTERNS:
        if not session.scalar(select(OfficeNamePattern).where(OfficeNamePattern.pattern == pattern)):
            session.add(
                OfficeNamePattern(
                    office_id=offices[office].id, pattern=pattern, kind=PatternKind.EXACT, weight=weight
                )
            )
    for kw, office, weight in KEYWORDS:
        if not session.scalar(select(OfficeKeyword).where(OfficeKeyword.keyword == kw)):
            session.add(OfficeKeyword(office_id=offices[office].id, keyword=kw, weight=weight))
    by_name = {d.name: d.id for d in session.scalars(select(Designation))}
    for email, name, designation, office, role in USERS:
        if not session.scalar(select(User).where(User.email == email)):
            session.add(
                User(
                    email=email,
                    full_name=name,
                    designation=designation,
                    designation_id=by_name.get(designation.split(",")[0].strip()),
                    office_id=offices[office].id,
                    role=role,
                    password_hash=hash_password(DEMO_PASSWORD),
                    must_confirm_profile=False,
                )
            )
    session.flush()
    return {
        "departments": len(DEPARTMENTS),
        "codes": len(CODES),
        "patterns": len(PATTERNS),
        "users": len(USERS),
    }
