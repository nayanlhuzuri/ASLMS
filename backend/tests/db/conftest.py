"""Database tests run against a real PostgreSQL (the Compose `postgres` service, database `aslms_test`).
They are skipped when it is not reachable. The schema is built by the real migration, never by create_all."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session, sessionmaker

from aslms.integration.napix.client import NapixClient
from aslms.integration.napix.crypto import NapixCrypto
from aslms.integration.napix.hc import NapixHighCourt
from aslms.services.seed import seed_all
from tests.unit.conftest import KEY, Gateway

BACKEND = Path(__file__).resolve().parents[2]
TEST_URL = os.environ.get(
    "ASLMS_TEST_DATABASE_URL", "postgresql+psycopg://aslms:aslms@localhost:5433/aslms_test"
)


def head_revision() -> str:
    """The head of the migration chain (a refused downgrade leaves the database here)."""
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(alembic_config(TEST_URL)).get_current_head()


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session", autouse=True)
def no_bootstrap_super_admin() -> Iterator[None]:
    """The suite is green whatever a local `.env` holds: ASLMS_SUPERADMIN_EMAIL / ASLMS_SUPERADMIN_PASSWORD
    there would make `seed_all` create a second super admin next to the test world's one. Process environment
    variables win over the `.env` file, so both are blanked for the session and the settings cache is cleared.
    Tests that need a bootstrap super admin patch `access_seed.get_settings` themselves."""
    from aslms.core.config import get_settings

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("ASLMS_SUPERADMIN_EMAIL", "")
        mp.setenv("ASLMS_SUPERADMIN_PASSWORD", "")
        get_settings.cache_clear()
        yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def db_url() -> str:
    try:
        engine = sa.create_engine(TEST_URL, poolclass=sa.pool.NullPool)
        with engine.connect() as conn:
            conn.execute(sa.text("select 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(
            f"test database not reachable ({exc.__class__.__name__}); start `docker compose up -d postgres`"
        )
    return TEST_URL


@pytest.fixture(scope="session")
def migrated(db_url: str) -> Iterator[str]:
    """Head of the migration chain on a clean test database. Rows left by an earlier run are wiped first: the
    downgrades refuse to strip populated tables (e.g. 0010 with `user_devices` rows)."""
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield db_url


@pytest.fixture(scope="session")
def engine(migrated: str) -> Iterator[sa.Engine]:
    eng = sa.create_engine(migrated, poolclass=sa.pool.NullPool)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine: sa.Engine) -> Iterator[Session]:
    """A session whose work is rolled back at the end of the test."""
    conn = engine.connect()
    trans = conn.begin()
    sess = sessionmaker(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")()
    try:
        yield sess
    finally:
        sess.close()
        trans.rollback()
        conn.close()


def wipe(conn_or_session) -> None:
    """Empty every application table (not alembic_version). Transactional: inside a rolled-back test
    transaction nothing persists; the pipeline tests call it on a connection they commit."""
    rows = (
        conn_or_session.execute(
            sa.text(
                "select tablename from pg_tables where schemaname = 'public' and tablename <> 'alembic_version'"
            )
        )
        .scalars()
        .all()
    )
    conn_or_session.execute(sa.text("SET session_replication_role = replica"))
    for t in rows:
        conn_or_session.execute(sa.text(f"DELETE FROM {t}"))
    conn_or_session.execute(sa.text("SET session_replication_role = DEFAULT"))


def wipe_if_migrated(url: str) -> None:
    """`wipe` on a database that has tables (no-op on an empty one)."""
    eng = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with eng.begin() as conn:
            if conn.execute(sa.text("select to_regclass('alembic_version')")).scalar() is not None:
                wipe(conn)
    finally:
        eng.dispose()


# ---------------------------------------------------------------- the scripted NAPIX gateway and a seeded DB
ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ROOT / "docs" / "specs" / "samples"
FIXTURES = ROOT / "backend" / "tests" / "fixtures" / "causelists"


def sample(name: str):
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


BENCHES_2025_01_06 = {
    "case1": {"bench_id": 2048, "judge_name": "JOINT REGISTRAR (JUDL.) MR. CHINMOY BARUAH"},
    "case2": {"bench_id": 2110, "judge_name": "JOINT REGISTRAR (VIGILANCE) - SMTI. JAYASHREE BORA"},
}
DETAILS = {
    "2048": {
        "case1": {
            "bench": "JOINT REGISTRAR (JUDL.) MR. CHINMOY BARUAH",
            "bench_id": 2048,
            "causelist_id": 1007,
            "cause_list_type": "LAWAZIMA      ",
        }
    },
    "2110": {
        "case1": {
            "bench": "JOINT REGISTRAR (VIGILANCE) - SMTI. JAYASHREE BORA",
            "bench_id": 2110,
            "causelist_id": 1008,
            "cause_list_type": "LAWAZIMA      ",
        }
    },
}


def router(gw: Gateway):
    """Answers every API from the samples (Search by Case Number and by Party Name included, and Overview for the
    window probe); the dossier is the pending sample re-labelled with the asked CNR."""
    import base64

    pdf_b64 = base64.b64encode((FIXTURES / "napix_lawazima_bench2048_2025-01-06.pdf").read_bytes()).decode()

    def handle(path: str, q: dict, request: httpx.Request) -> httpx.Response:
        plain = gw.crypto.decrypt(q["request_str"])
        params = dict(kv.split("=", 1) for kv in plain.split("|") if "=" in kv)
        if path == "hc-state-api/state":
            return gw.envelope(sample("state_master_2026-09-03.json"))
        if path == "hc-district-api/district":
            return gw.envelope(sample("district_master_2026-09-03.json"))
        if path == "hc-bench-master-api/bench":
            return gw.envelope(sample("bench_master_2026-09-03.json"))
        if path == "hc-case-type-master-api/casetypemaster":
            return gw.envelope(sample("case_type_master_2026-09-03.json"))
        if path == "hc-act-master-api/actMaster":
            return gw.envelope(sample("act_master_2026-09-03.json"))
        if path == "hc-causelist-bench-api/causelistbench":
            if params.get("causelist_date") == "2025-01-06":
                return gw.envelope(BENCHES_2025_01_06)
            return gw.encrypted_status(628)
        if path == "hc-causelist-details-api/causelistdetails":
            return gw.envelope(DETAILS[params["bench_id"]])
        if path == "hc-show-causelist-api/showcauselist":
            return gw.envelope_text(json.dumps(pdf_b64))
        if path == "hc-cnr-api/CNR":
            data = sample("cnr_pending.json")
            data["cino"] = params["cino"]
            return gw.envelope(data)
        if path == "hc-case-search-api/casesearch":
            return gw.envelope(sample("case_search_2026-09-03.json"))
        if path == "hc-party-name-api/partyname":
            return gw.envelope(sample("party_name_2026-09-03.json"))
        if path == "overview/overview":  # the connectivity check and the runner's window probe
            return gw.envelope(sample("overview_2026-09-03.json"))
        if path == "hc-current-status-api/currentStatus":
            block = sample("current_status_pending.json")["cases1"]
            out = {}
            for i, cino in enumerate(params["cino"].split(","), start=1):
                out[f"cases{i}"] = {
                    **block,
                    "cino": cino,
                    "date_next_list": "2026-10-20",
                    "purpose_name": "HEARING",
                }
            return gw.envelope(out)
        return gw.encrypted_status(628)

    return handle


@pytest.fixture()
def napix():
    gw = Gateway(NapixCrypto(KEY))
    gw.responses = [router(gw)] * 10_000
    client = NapixClient(
        base_url="https://gw.test/nic/ecourts",
        client_id="key-test",
        client_secret="secret-test",
        dept_id="dept-test",
        crypto=NapixCrypto(KEY),
        transport=httpx.MockTransport(gw.handle),
        backoff_base=0.0,
    )
    hc = NapixHighCourt(client, "GAHC01", "18")
    return gw, client, hc


@pytest.fixture()
def clean_db(engine):
    """Empty every table, then seed. Pipeline tests commit real transactions (the runner opens its own)."""
    with engine.begin() as conn:
        wipe(conn)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        seed_all(s)
        s.commit()
    return Session


@pytest.fixture()
def world(engine):
    """The committed recommend-and-claim world (tests/db/world.py), wiped again after the test so later
    modules start from an empty database."""
    from tests.db.world import build_world

    w = build_world(engine)
    yield w
    with engine.begin() as conn:
        wipe(conn)
