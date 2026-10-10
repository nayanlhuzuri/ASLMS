"""A small world for the portal-shell API tests: the seeded State, two departments (EDU with a directorate,
HEALTH), the super admin, a department admin and an officer in each department, and a login whose only membership
has ended."""

from __future__ import annotations

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.org import Office
from aslms.domain.reference import OfficeKind, Role
from aslms.services.audit import Actor
from aslms.services.seed import seed_all
from aslms.services.users import create_user
from tests.db.auth_support import ready_all, sign_in
from tests.db.conftest import wipe

PW = "correct-horse-battery-7"

USERS = [
    ("root@example.org", "Root", Role.SUPER_ADMIN, "GOA"),
    ("admin.edu@example.org", "Edu Admin", Role.DEPT_ADMIN, "EDU"),
    ("anita.sharma@example.org", "Anita Sharma", Role.DIRECTORATE_USER, "EDU-DSE"),
    ("admin.health@example.org", "Health Admin", Role.DEPT_ADMIN, "HEALTH"),
    ("anil.kumar@example.org", "Anil Kumar", Role.DEPT_OFFICER, "HEALTH"),
    ("gone.away@example.org", "Gone Away", Role.DEPT_OFFICER, "EDU"),
]


def build_api(engine) -> TestClient:
    with engine.begin() as conn:
        wipe(conn)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        seed_all(s)
        goa = s.scalar(sa.select(Office).where(Office.code == "GOA"))
        edu = Office(
            code="EDU", name="Education", kind=OfficeKind.DEPARTMENT, parent_id=goa.id, path="GOA/EDU"
        )
        health = Office(
            code="HEALTH", name="Health", kind=OfficeKind.DEPARTMENT, parent_id=goa.id, path="GOA/HEALTH"
        )
        s.add_all([edu, health])
        s.flush()
        dse = Office(
            code="EDU-DSE",
            name="Secondary Education",
            kind=OfficeKind.DIRECTORATE,
            parent_id=edu.id,
            path="GOA/EDU/EDU-DSE",
        )
        s.add(dse)
        s.flush()
        offices = {"GOA": goa, "EDU": edu, "HEALTH": health, "EDU-DSE": dse}
        sys = Actor.system("test")
        for email, name, role, office in USERS:
            create_user(s, sys, email=email, password=PW, full_name=name, role=role, office=offices[office])
        s.flush()
        s.execute(
            sa.text(
                "UPDATE user_memberships SET is_active = false, is_primary = false, deactivated_at = now(), "
                "end_reason = 'left' WHERE user_id = (SELECT id FROM users WHERE email = 'gone.away@example.org')"
            )
        )
        ready_all(s)
        s.commit()
    settings = Settings(
        _env_file=None,
        aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters",
        aslms_access_token_minutes=5,
    )
    return TestClient(create_app(settings, Session))


def headers(api: TestClient, email: str) -> dict:
    return {"Authorization": f"Bearer {sign_in(api, email, PW)['access_token']}"}
