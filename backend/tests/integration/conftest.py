"""Integration tests need a reachable Postgres. They use a separate database (`<db>_test`), created on demand
and migrated to head, and are skipped, not failed, when the server cannot be reached.
(SQLAlchemy 2 masks passwords in str(URL); always render with hide_password=False.)"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from alembic import command
from aslms.core.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _test_url() -> str:
    override = os.environ.get("TEST_DATABASE_URL_SYNC")
    if override:
        return override
    url = make_url(get_settings().database_url_sync)
    name = url.database if url.database.endswith("_test") else f"{url.database}_test"
    return url.set(database=name).render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def test_db_url() -> str:
    url = make_url(_test_url())
    admin = sa.create_engine(
        url.set(database="postgres").render_as_string(hide_password=False), isolation_level="AUTOCOMMIT"
    )
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
            ).scalar()
            if not exists:
                conn.execute(sa.text(f'CREATE DATABASE "{url.database}"'))
    except sa.exc.OperationalError as e:  # server unreachable
        pytest.skip(f"Postgres not reachable: {e}")
    finally:
        admin.dispose()
    return url.render_as_string(hide_password=False)


def _reset_caches() -> None:
    from aslms.db import session as db_session

    get_settings.cache_clear()
    db_session.sync_engine.cache_clear()
    db_session.sync_session_factory.cache_clear()


@pytest.fixture(scope="session")
def app_env(test_db_url: str, tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Points the whole application (settings, engine, storage) at the test database and a temp storage root,
    with NAPIX disabled, and migrates to head."""
    mp = pytest.MonkeyPatch()
    mp.setenv("DATABASE_URL_SYNC", test_db_url)
    mp.setenv("STORAGE_ROOT", str(tmp_path_factory.mktemp("storage")))
    mp.setenv("NAPIX_ENABLED", "false")
    mp.setenv("SMTP_HOST", "")
    mp.setenv("CLAMAV_HOST", "")
    mp.setenv("APP_ENV", "test")
    _reset_caches()
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")
    yield test_db_url
    mp.undo()
    _reset_caches()


@pytest.fixture()
def db(app_env: str) -> Iterator[Session]:
    """A clean database for each test: every table truncated (TRUNCATE does not fire the append-only triggers)."""
    from aslms.db.session import sync_engine

    engine = sync_engine()
    with engine.begin() as conn:
        tables = [
            r[0]
            for r in conn.execute(
                sa.text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'"
                )
            )
        ]
        conn.execute(sa.text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE"))
    with Session(engine, expire_on_commit=False) as s:
        yield s


# ------------------------------------------------------------------ shared API fixtures
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from aslms.core.security import hash_password  # noqa: E402
from aslms.domain.causelists import CauseListSource  # noqa: E402
from aslms.domain.org import Office, OfficeKind, Role, User  # noqa: E402
from aslms.domain.ownership import CounselCode  # noqa: E402
from tests.integration.helpers import PW  # noqa: E402

FIX = BACKEND_DIR / "tests" / "fixtures"


def _office(db: Session, code: str, kind: OfficeKind, parent: Office | None = None) -> Office:
    o = Office(
        code=code,
        name=f"{code} office",
        kind=kind,
        parent_id=parent.id if parent else None,
        path=f"{parent.path}/{code}" if parent else code,
    )
    db.add(o)
    db.flush()
    return o


def _user(db: Session, email: str, office: Office, role: Role) -> User:
    u = User(
        email=email,
        full_name=email.split("@")[0],
        designation="Officer",
        office_id=office.id,
        role=role,
        password_hash=hash_password(PW),
        must_confirm_profile=False,
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture()
def world(db: Session):
    from aslms.db.seed import run_seed
    from aslms.services import causelists

    run_seed(db)
    edu = _office(db, "EDU", OfficeKind.DEPARTMENT)
    dse = _office(db, "DSE", OfficeKind.DIRECTORATE, edu)
    health = _office(db, "HEALTH", OfficeKind.DEPARTMENT)
    edu_sc = _office(db, "EDU-SC", OfficeKind.COUNSEL_OFFICE, edu)
    state = db.scalar(select(Office).where(Office.code == "STATE"))
    # test mapping: the Lawazima fixture's rows carry "GA, ASSAM"; map it (non-generic) to EDU for this test
    db.add(CounselCode(code="GA, ASSAM", office_id=edu.id, weight=0.95))
    users = {
        "edu_admin": _user(db, "edu.admin@t.in", edu, Role.DEPT_ADMIN),
        "edu_officer": _user(db, "edu.officer@t.in", edu, Role.DEPT_OFFICER),
        "dse": _user(db, "dse@t.in", dse, Role.DIRECTORATE_USER),
        "health_admin": _user(db, "health.admin@t.in", health, Role.DEPT_ADMIN),
        "counsel": _user(db, "counsel@t.in", edu_sc, Role.STANDING_COUNSEL),
        "cs": _user(db, "cs@t.in", state, Role.STATE_OVERSIGHT),
    }
    db.commit()
    stats, parsed = causelists.ingest_pdf(
        db,
        (FIX / "ghc_lawazima_01-09-2025.pdf").read_bytes(),
        source=CauseListSource.LOCAL_DIR,
        filename="Lawazima_01-09-2025.pdf",
    )
    db.commit()
    n_rec = sum(1 for r in parsed.rows if "GA, ASSAM" in r.counsel_codes)
    return {
        "edu": edu,
        "dse": dse,
        "health": health,
        "users": users,
        "stats": stats,
        "parsed": parsed,
        "n_rec": n_rec,
    }


@pytest.fixture()
def client(world):
    from aslms.api.main import create_app

    with TestClient(create_app()) as c:
        yield c
