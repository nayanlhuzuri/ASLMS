"""Design deployment-checklist, Part C (row 78, decision 29): PgBouncer in transaction mode for api, worker and
scheduler. A source scan refuses session-level Postgres features in `backend/aslms` (transaction pooling hands each
transaction to any server connection, so a session `SET`, a session advisory lock, `LISTEN` or a temporary table
would leak to, or be lost by, the next client). The Compose wiring, the image and the entrypoint are parsed."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "backend" / "aslms"
PGB = ROOT / "infra" / "pgbouncer"
APP_SERVICES = ("api", "worker", "scheduler")
DIRECT_SERVICES = ("init", "migrate", "backup", "ops-exporter")

# A statement start: the beginning of a line or a string, or after `;` or `(`.
_START = r"""(?:^|["'`;(]\s*)"""
SESSION_FEATURES: dict[str, re.Pattern[str]] = {
    # `SET x = …`, `SET x TO …`, `SET SESSION …`, `SET ROLE …`; `SET LOCAL …` is transaction-scoped and allowed
    "session SET": re.compile(
        _START
        + r"SET\s+(?!LOCAL\b)(?:SESSION\s+)?(?:ROLE\b|AUTHORIZATION\b|[A-Za-z_{][\w.{}]*\s*(?:=|\bTO\b))",
        re.I | re.M,
    ),
    # session advisory locks; pg_advisory_xact_lock / pg_try_advisory_xact_lock are allowed
    "session advisory lock": re.compile(r"pg_(?:try_)?advisory_(?:lock|unlock)(?:_shared|_all)?\s*\(", re.I),
    "LISTEN": re.compile(_START + r"(?:UN)?LISTEN\s+[\w\"*]", re.I | re.M),
    "temporary table": re.compile(r"CREATE\s+(?:(?:GLOBAL|LOCAL)\s+)?TEMP(?:ORARY)?\s+TABLE", re.I),
    "set_config(…, false)": re.compile(r"set_config\s*\([^)]*,\s*false\s*\)", re.I),
    "cursor WITH HOLD": re.compile(r"\bWITH\s+HOLD\b", re.I),
}


def _findings(text: str) -> list[str]:
    return [name for name, pattern in SESSION_FEATURES.items() if pattern.search(text)]


def _services(name: str = "compose.yml") -> dict:
    return yaml.safe_load((ROOT / name).read_text("utf-8"))["services"]


def _env(service: dict) -> dict:
    return service.get("environment") or {}


def test_session_feature_scanner_flags_what_it_should():
    flagged = [
        'text("SET statement_timeout = 5000")',
        "cur.execute('SET search_path TO aslms')",
        '"SET ROLE aslms_app"',
        '"SET SESSION statement_timeout = 1"',
        '"SET SESSION AUTHORIZATION aslms"',
        'f"SET {name} = {value}"',
        'text("SELECT pg_advisory_lock(42)")',
        'text("SELECT pg_try_advisory_lock(:k)")',
        'text("SELECT pg_advisory_unlock_all()")',
        '"LISTEN case_events"',
        'conn.execute("UNLISTEN *")',
        '"CREATE TEMP TABLE x (id int)"',
        '"CREATE TEMPORARY TABLE x (id int)"',
        "\"SELECT set_config('statement_timeout', '5s', false)\"",
        '"DECLARE c CURSOR WITH HOLD FOR SELECT 1"',
    ]
    for sample in flagged:
        assert _findings(sample), sample
    allowed = [
        'text(f"SET LOCAL statement_timeout = {ms}")',
        "cur.execute(\"SET LOCAL log_statement = 'none'\")",
        'text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))")',
        'text("SELECT pg_try_advisory_xact_lock(:k)")',
        'text("UPDATE job_runs SET status = :s WHERE id = :id")',
        'ForeignKey("users.id", ondelete="SET NULL")',
        'event.listen(Session, "after_commit", _clear_cache)',
        'help="the address to listen on"',
        "\"SELECT set_config('statement_timeout', '5s', true)\"",
    ]
    for sample in allowed:
        assert not _findings(sample), sample


def test_no_session_level_postgres_features():
    """Decision 29: transaction pooling is safe only while the application uses transaction-scoped features."""
    paths = sorted(PACKAGE.rglob("*.py"))
    assert len(paths) > 50, "the scan reads the application package"
    problems = [
        f"{path.relative_to(ROOT)}:{number}: {name}"
        for path in paths
        for number, row in enumerate(path.read_text("utf-8").splitlines(), start=1)
        for name in _findings(row)
    ]
    assert not problems, "session-level Postgres features break PgBouncer transaction pooling:\n" + "\n".join(
        problems
    )


def test_compose_pgbouncer_urls():
    services = _services()
    for name in APP_SERVICES:
        svc = services[name]
        url = _env(svc)["DATABASE_URL_SYNC"]
        assert url == (
            "postgresql+psycopg://aslms_app:${ASLMS_APP_PASSWORD:?set ASLMS_APP_PASSWORD in .env}"
            "@pgbouncer:6432/${POSTGRES_DB:-aslms}"
        ), name
        assert svc["depends_on"]["pgbouncer"] == {"condition": "service_healthy"}, name
    # init, migrate, backup and the exporters need session features, DDL or a view independent of the pool
    for name in DIRECT_SERVICES:
        env = _env(services[name])
        for var in ("DATABASE_URL_SYNC", "ASLMS_MIGRATE_URL"):
            if var in env:
                assert "@postgres:5432/" in env[var], (name, var)
        assert not any("pgbouncer" in str(v) for v in env.values()), name
    assert _env(services["postgres-exporter"])["DATA_SOURCE_URI"].startswith("postgres:5432/")
    # the pgbouncer exporter reads the `pgbouncer` console as aslms_readonly (a stats user there)
    conn = _env(services["pgbouncer-exporter"])["PGBOUNCER_EXPORTER_CONNECTION_STRING"]
    assert conn.startswith("postgres://aslms_readonly:${ASLMS_READONLY_PASSWORD:?")
    assert conn.endswith("@pgbouncer:6432/pgbouncer?sslmode=disable")
    # nobody else goes through PgBouncer
    users = {
        name for name, svc in services.items() if any("pgbouncer:6432" in str(v) for v in _env(svc).values())
    }
    assert users == {*APP_SERVICES, "pgbouncer-exporter"}


def test_compose_pgbouncer_service():
    services = _services()
    pgb = services["pgbouncer"]
    assert pgb["build"] == "./infra/pgbouncer"
    assert "ports" not in pgb and "networks" not in pgb, "6432 stays on the internal network"
    assert "env_file" not in pgb, "only the two role passwords enter the container"
    env = _env(pgb)
    assert env["ASLMS_APP_PASSWORD"] == "${ASLMS_APP_PASSWORD:?set ASLMS_APP_PASSWORD in .env}"
    assert env["ASLMS_READONLY_PASSWORD"] == "${ASLMS_READONLY_PASSWORD:?set ASLMS_READONLY_PASSWORD in .env}"
    assert "POSTGRES_PASSWORD" not in env and "ASLMS_MIGRATE_URL" not in env
    assert env["PGBOUNCER_MAX_CLIENT_CONN"] == "${PGBOUNCER_MAX_CLIENT_CONN:-200}"
    assert env["PGBOUNCER_DEFAULT_POOL_SIZE"] == "${PGBOUNCER_DEFAULT_POOL_SIZE:-20}"
    assert env["PGBOUNCER_MAX_PREPARED_STATEMENTS"] == "${PGBOUNCER_MAX_PREPARED_STATEMENTS:-200}"
    assert pgb["tmpfs"] == ["/tmp"], "the user list is written to a tmpfs, never to a disk"
    # after init, so a changed aslms_app password is in the database before PgBouncer logs in with it
    assert pgb["depends_on"]["init"] == {"condition": "service_completed_successfully"}
    assert "6432" in " ".join(pgb["healthcheck"]["test"])
    assert pgb["cap_drop"] == ["ALL"]
    assert "pgbouncer" not in _services("compose.dev.yml"), "not published in development either"


def test_pgbouncer_image():
    text = (PGB / "Dockerfile").read_text("utf-8")
    assert re.search(r"^FROM alpine:\d+\.\d+\.\d+$", text, re.M), "pinned Alpine"
    assert "'pgbouncer>=1.21'" in text, "1.21+ tracks protocol-level prepared statements"
    assert re.search(r"^USER 10001$", text, re.M)


def test_pgbouncer_entrypoint_settings_and_secrets():
    script = (PGB / "entrypoint.sh").read_text("utf-8")
    assert "\r" not in script, "the entrypoint runs in a Linux container: LF line endings"
    for line in (
        "pool_mode = transaction",
        "max_client_conn = $MAX_CLIENT_CONN",
        "default_pool_size = $DEFAULT_POOL_SIZE",
        "max_prepared_statements = $MAX_PREPARED_STATEMENTS",
        "listen_port = 6432",
        "auth_type = hba",
        "admin_users =",
        "stats_users = aslms_readonly",
        "ignore_startup_parameters = extra_float_digits",
    ):
        assert re.search(rf"^{re.escape(line)}$", script, re.M), line
    assert re.search(r"^server_reset_query =$", script, re.M), "server_reset_query is empty"
    assert 'MAX_CLIENT_CONN="${PGBOUNCER_MAX_CLIENT_CONN:-200}"' in script
    assert 'DEFAULT_POOL_SIZE="${PGBOUNCER_DEFAULT_POOL_SIZE:-20}"' in script
    assert 'MAX_PREPARED_STATEMENTS="${PGBOUNCER_MAX_PREPARED_STATEMENTS:-200}"' in script
    # every HBA line is SCRAM: aslms_app to the database, aslms_readonly to the console only
    hba = re.findall(r"^host\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$", script, re.M)
    assert hba == [
        ("$DB", "aslms_app", "0.0.0.0/0", "scram-sha-256"),
        ("pgbouncer", "aslms_readonly", "0.0.0.0/0", "scram-sha-256"),
    ]
    assert "trust" not in script.split('cat > "$DIR/pgbouncer_hba.conf"')[1].split("EOF")[0]
    # no user= on the database line: each client logs in to Postgres as itself
    db_line = re.search(r"^\$DB = (.*)$", script, re.M)
    assert db_line and "user=" not in db_line.group(1)
    # the user list: mode 600, written once per password, never echoed
    assert "umask 077" in script
    assert 'chmod 600 "$DIR/userlist.txt"' in script
    for var in ("ASLMS_APP_PASSWORD", "ASLMS_READONLY_PASSWORD"):
        uses = [row for row in script.splitlines() if f"${var}" in row or f"${{{var}" in row]
        assert len(uses) == 2, (var, uses)  # the required-variable check and the user-list line
        assert not any(row.lstrip().startswith("echo") for row in uses), var


def test_runbook_stops_pgbouncer_before_migrate_and_restore():
    runbook = (ROOT / "docs" / "operations.md").read_text("utf-8")
    assert "docker compose stop api worker scheduler web pgbouncer`" in runbook
    assert "docker compose stop api worker scheduler web pgbouncer backup`" in runbook
    assert "## 18. PgBouncer" in runbook
    assert "**PgBouncerClientsWaiting**" in runbook
