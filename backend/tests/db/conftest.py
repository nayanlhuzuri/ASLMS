"""Database tests run against a real PostgreSQL (the Compose `postgres` service locally, a service container in CI).
Each session works in its own database `<base>_<UTC stamp>_<hex>` (tests/db/rundb.py, design github-and-ci), created
at the start and dropped at the end. They are skipped when the server is not reachable, unless
`ASLMS_TEST_REQUIRE_DB=1` (CI). The schema is built by the real migration, never by create_all."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
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
from tests.db import rundb
from tests.unit.conftest import KEY, Gateway

BACKEND = Path(__file__).resolve().parents[2]
BASE_URL = rundb.base_url()
PER_RUN = rundb.flag("ASLMS_TEST_DB_PER_RUN", "1")
KEEP_DB = rundb.flag("ASLMS_TEST_KEEP_DB", "0")
REQUIRE_DB = rundb.flag("ASLMS_TEST_REQUIRE_DB", "0")
RUN_DATABASE = rundb.run_database_name(BASE_URL.database or "aslms_test") if PER_RUN else BASE_URL.database
# a module constant, as before: the modules that import it get this run's database
TEST_URL = rundb.url_string(BASE_URL.set(database=RUN_DATABASE))


@contextmanager
def cluster_lock() -> Iterator[None]:
    """Serialises cluster-wide changes (roles, `pg_monitor`) between concurrent runs on one server."""
    with rundb.cluster_lock(BASE_URL):
        yield


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


def _unreachable(exc: Exception) -> None:
    msg = (
        f"test database server not reachable ({exc.__class__.__name__}); start `docker compose up -d postgres` "
        "or set ASLMS_TEST_DATABASE_URL"
    )
    if REQUIRE_DB:
        pytest.fail(f"{msg} (ASLMS_TEST_REQUIRE_DB=1)", pytrace=False)
    pytest.skip(msg)


def _report(request: pytest.FixtureRequest, line: str) -> None:
    reporter = request.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(line)
    else:
        print(line)


@pytest.fixture(scope="session")
def db_url(request: pytest.FixtureRequest) -> Iterator[str]:
    """This run's database. Per run (the default): the stale run databases of killed runs are swept, the run's
    database is created, the cluster roles are pre-created under the cluster lock, and the database is dropped at
    the end of the session (kept with ASLMS_TEST_KEEP_DB=1). With ASLMS_TEST_DB_PER_RUN=0 the named database is
    used as it is, and only when its name contains `test`."""
    if not PER_RUN:
        try:
            rundb.check_named_database(RUN_DATABASE)
        except ValueError as exc:
            pytest.fail(str(exc), pytrace=False)
    target = rundb.maintenance_url(BASE_URL) if PER_RUN else BASE_URL.set(database=RUN_DATABASE)
    admin = rundb.autocommit_engine(target)
    try:
        try:
            with admin.connect() as conn:
                conn.execute(sa.text("select 1"))
        except Exception as exc:  # noqa: BLE001
            _unreachable(exc)
        if not PER_RUN:
            with cluster_lock(), admin.connect() as conn:
                rundb.ensure_roles(conn)
            yield TEST_URL
            return
        with admin.connect() as conn:
            rundb.sweep_stale(conn, BASE_URL.database or "aslms_test")
            try:
                rundb.create_database(conn, RUN_DATABASE)
            except sa.exc.ProgrammingError as exc:
                pytest.fail(
                    f"cannot create the run database {RUN_DATABASE} ({exc.orig.__class__.__name__}): the user of "
                    "ASLMS_TEST_DATABASE_URL needs CREATEDB, or set ASLMS_TEST_DB_PER_RUN=0 to use the named "
                    "database",
                    pytrace=False,
                )
        try:
            with cluster_lock(), admin.connect() as conn:
                rundb.ensure_roles(conn)
            yield TEST_URL
        finally:
            if KEEP_DB:
                _report(request, f"ASLMS_TEST_KEEP_DB=1: the run database {RUN_DATABASE} is kept")
            else:
                with admin.connect() as conn:
                    rundb.drop_database(conn, RUN_DATABASE)
    finally:
        admin.dispose()


@pytest.fixture(scope="session")
def migrated(db_url: str) -> Iterator[str]:
    """Head of the migration chain on this run's database, under the cluster lock (0001 and 0020 touch roles that
    every database shares). Per run the database is new and empty. With ASLMS_TEST_DB_PER_RUN=0, rows left by an
    earlier run are wiped and the chain is downgraded first: the downgrades refuse to strip populated tables
    (e.g. 0010 with `user_devices` rows)."""
    cfg = alembic_config(db_url)
    with cluster_lock():
        if not PER_RUN:
            wipe_if_migrated(db_url)
            command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    yield db_url


@pytest.fixture(autouse=True)
def _migration_cycle_lock(request: pytest.FixtureRequest) -> Iterator[None]:
    """Tests marked `migration_cycle` (they call command.upgrade / downgrade) hold the cluster lock while they run:
    0020's downgrade revokes `pg_monitor` for every database on the server."""
    if request.node.get_closest_marker("migration_cycle") is None:
        yield
        return
    with cluster_lock():
        yield


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
    """Answers every API from the samples (Search by Case Number, Party Name, Advocate Name and Filing Number
    included, and Overview for the window probe); the dossier is the pending sample re-labelled with the asked CNR."""
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
        if path == "hc-advocate-name-api/advocatename":  # the live probe's answer (P1, 18 Oct 2026)
            return gw.envelope(sample("advocate_name_2026-10-18-p1.json"))
        if path == "hc-filing-api/Filing":  # the live probe's answer (P5, 18 Oct 2026)
            return gw.envelope(sample("filing_2026-10-18-p5.json"))
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
