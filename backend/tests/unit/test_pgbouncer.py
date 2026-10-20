"""Design deployment-checklist, Part C (row 78, decision 29): PgBouncer in transaction mode for api, worker and
scheduler. A source scan refuses session-level Postgres features in `backend/aslms` (transaction pooling hands each
transaction to any server connection, so a session `SET`, a session advisory lock, `LISTEN` or a temporary table
would leak to, or be lost by, the next client). The Compose wiring, the image, the entrypoint and the healthcheck are
parsed. Design pre-pilot-hardening (rows 90 to 93): the scan reads SQL statements, the libpq floor, the exact pin and
the login healthcheck."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import psycopg
import yaml

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "backend" / "aslms"
PGB = ROOT / "infra" / "pgbouncer"
APP_SERVICES = ("api", "worker", "scheduler")
DIRECT_SERVICES = ("init", "migrate", "backup", "ops-exporter")

# Part 1, line-based (design pre-pilot-hardening, decision 9): unambiguous anywhere in a line. It also catches
# SQLAlchemy `func.pg_advisory_lock(…)`, which is not a string.
LINE_FEATURES: dict[str, re.Pattern[str]] = {
    # session advisory locks; pg_advisory_xact_lock / pg_try_advisory_xact_lock are allowed
    "session advisory lock": re.compile(r"pg_(?:try_)?advisory_(?:lock|unlock)(?:_shared|_all)?\s*\(", re.I),
    "temporary table": re.compile(r"CREATE\s+(?:(?:GLOBAL|LOCAL)\s+)?TEMP(?:ORARY)?\s+TABLE", re.I),
    "set_config(…, false)": re.compile(r"set_config\s*\([^)]*,\s*false\s*\)", re.I),
    "cursor WITH HOLD": re.compile(r"\bWITH\s+HOLD\b", re.I),
}

# Part 2, statement starts: every string constant of a module (docstrings excepted, f-strings joined with `{}` per
# placeholder) is split on `;`; leading whitespace, `(`, `--` comment lines and `/* */` comments are stripped; the
# statement is flagged when it starts with one of these. An `UPDATE … SET` is never flagged: its SET is not at a
# statement start. Keywords match in any case in a string passed directly to `text(…)`, `.execute(…)`,
# `.exec_driver_sql(…)` or `sql.SQL(…)`, and in upper case only elsewhere (the package writes SQL in upper case; the
# rule keeps English strings such as "Reset passwords" out).
_NAME = r"[A-Za-z_{][\w.{}]*"
STATEMENT_FEATURES: dict[str, str] = {
    # SET LOCAL, SET TRANSACTION and SET CONSTRAINTS are transaction-scoped and allowed
    "session SET": (
        r"SET\s+(?!(?:LOCAL|TRANSACTION|CONSTRAINTS)\b)(?:SESSION\s+)?"
        rf"(?:ROLE\b|AUTHORIZATION\b|TIME\s+ZONE\b|NAMES\b|SCHEMA\b|{_NAME}\s*(?:=|\bTO\b))"
    ),
    "RESET": rf"RESET\s+(?:ALL|ROLE|SESSION\s+AUTHORIZATION|{_NAME})\s*\Z",
    "DISCARD": r"DISCARD\s+(?:ALL|PLANS|SEQUENCES|TEMP|TEMPORARY)\b",
    "SQL PREPARE": rf"PREPARE\s+(?:TRANSACTION\b|{_NAME}\s*(?:\([^)]*\)\s*)?AS\b)",
    "SQL DEALLOCATE": rf"DEALLOCATE\s+(?:PREPARE\s+)?(?:ALL\b|{_NAME})",
    "LISTEN": r"(?:UN)?LISTEN\s+[\w\"*{]",
}
STATEMENT_ANY_CASE = {name: re.compile(p, re.I) for name, p in STATEMENT_FEATURES.items()}
STATEMENT_UPPER = {name: re.compile(p) for name, p in STATEMENT_FEATURES.items()}
SQL_CALLS = frozenset({"text", "execute", "exec_driver_sql", "SQL"})
_LEADING = re.compile(r"\A(?:\s+|\(|--[^\n]*(?:\n|\Z)|/\*.*?\*/)+", re.S)


class _Strings(ast.NodeVisitor):
    """(first line, text, passed directly to a SQL call) for every string constant except docstrings."""

    def __init__(self, tree: ast.AST) -> None:
        self.found: list[tuple[int, str, bool]] = []
        self.docstrings: set[int] = set()
        self.direct: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = node.body
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    self.docstrings.add(id(body[0].value))
        self.visit(tree)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = (
            func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        )
        if name in SQL_CALLS and node.args and isinstance(node.args[0], (ast.Constant, ast.JoinedStr)):
            self.direct.add(id(node.args[0]))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and id(node) not in self.docstrings:
            self.found.append((node.lineno, node.value, id(node) in self.direct))

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            elif isinstance(value, ast.FormattedValue):
                parts.append("{}")
                self.visit(value.value)  # strings inside a placeholder are strings of their own
        self.found.append((node.lineno, "".join(parts), id(node) in self.direct))


def _statement_findings(source: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for line, value, direct in _Strings(ast.parse(source)).found:
        patterns = STATEMENT_ANY_CASE if direct else STATEMENT_UPPER
        for statement in value.split(";"):
            statement = _LEADING.sub("", statement, count=1)
            out.extend((line, name) for name, pattern in patterns.items() if pattern.match(statement))
    return out


def _line_findings(source: str) -> list[tuple[int, str]]:
    return [
        (number, name)
        for number, row in enumerate(source.splitlines(), start=1)
        for name, pattern in LINE_FEATURES.items()
        if pattern.search(row)
    ]


def _findings(source: str) -> list[str]:
    """Both parts over one sample of Python source; `pass` first, so a bare string sample is not a module docstring."""
    source = "pass\n" + source
    return [name for _line, name in _line_findings(source) + _statement_findings(source)]


def _services(name: str = "compose.yml") -> dict:
    return yaml.safe_load((ROOT / name).read_text("utf-8"))["services"]


def _env(service: dict) -> dict:
    return service.get("environment") or {}


def test_session_feature_scanner_flags_what_it_should():
    """Each sample is Python source, parsed as the package's modules are (pre-pilot-hardening, decision 9)."""
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
        "func.pg_advisory_lock(42)",
        '"LISTEN case_events"',
        'conn.execute("UNLISTEN *")',
        '"CREATE TEMP TABLE x (id int)"',
        '"CREATE TEMPORARY TABLE x (id int)"',
        "\"SELECT set_config('statement_timeout', '5s', false)\"",
        '"DECLARE c CURSOR WITH HOLD FOR SELECT 1"',
        # row 91: what the line scan missed
        'conn.execute(text("""\n    SELECT 1;\n        SET statement_timeout = 0\n"""))',
        'text("""\n    SET statement_timeout = 0\n""")',
        "\"SET TIME ZONE 'UTC'\"",
        "\"SET SESSION TIME ZONE 'UTC'\"",
        '"RESET ALL"',
        '"RESET statement_timeout"',
        '"RESET ROLE"',
        '"DISCARD ALL"',
        '"DISCARD PLANS"',
        '"PREPARE q (int) AS SELECT $1"',
        "\"PREPARE TRANSACTION 'x'\"",
        '"DEALLOCATE ALL"',
        '"DEALLOCATE PREPARE q"',
        '"SELECT 1; SET search_path TO x"',
        r'"-- note\nSET x = 1"',
        '"/* a comment */ (SET x = 1)"',
        'text("set search_path to x")',
        'sql.SQL("reset all")',
        'conn.exec_driver_sql("listen x")',
    ]
    for sample in flagged:
        assert _findings(sample), sample
    allowed = [
        'text(f"SET LOCAL statement_timeout = {ms}")',
        "cur.execute(\"SET LOCAL log_statement = 'none'\")",
        'text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))")',
        'text("SELECT pg_try_advisory_xact_lock(:k)")',
        'text("UPDATE job_runs SET status = :s WHERE id = :id")',
        'text("""UPDATE job_runs\n   SET status = \'failed\'\n WHERE id = :id""")',
        '"SET TRANSACTION READ ONLY"',
        '"SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"',
        '"SET CONSTRAINTS ALL DEFERRED"',
        'def f():\n    """SET search_path TO x"""\n',
        'class C:\n    """RESET ALL"""\n',
        '"Reset passwords"',
        '"set names the incoming head only"',
        '"reset overdue: probing in 5 s"',
        'ForeignKey("users.id", ondelete="SET NULL")',
        'event.listen(Session, "after_commit", _clear_cache)',
        'help="the address to listen on"',
        "\"SELECT set_config('statement_timeout', '5s', true)\"",
    ]
    for sample in allowed:
        assert not _findings(sample), sample


def test_no_session_level_postgres_features():
    """Decision 29: transaction pooling is safe only while the application uses transaction-scoped features. Both
    parts of the scan (pre-pilot-hardening, decision 9) run over every module of the package."""
    paths = sorted(PACKAGE.rglob("*.py"))
    assert len(paths) > 50, "the scan reads the application package"
    problems = []
    for path in paths:
        source = path.read_text("utf-8")
        for number, name in sorted(_line_findings(source) + _statement_findings(source)):
            problems.append(f"{path.relative_to(ROOT)}:{number}: {name}")
    assert not problems, "session-level Postgres features break PgBouncer transaction pooling:\n" + "\n".join(
        problems
    )


def test_libpq_is_17_or_later():
    """Decision 6 (row 90): psycopg closes prepared statements with the protocol message Close, which PgBouncer
    tracks, only on libpq 17 or later."""
    assert psycopg.pq.version() >= 170000, psycopg.pq.version()


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
    # the healthcheck logs in through the pool (pre-pilot-hardening, decision 8)
    assert pgb["healthcheck"]["test"] == ["CMD", "/bin/sh", "/usr/local/bin/pgbouncer-healthcheck.sh"]
    assert pgb["cap_drop"] == ["ALL"]
    assert "pgbouncer" not in _services("compose.dev.yml"), "not published in development either"


def test_pgbouncer_image():
    text = (PGB / "Dockerfile").read_text("utf-8")
    assert re.search(r"^FROM alpine:\d+\.\d+\.\d+$", text, re.M), "pinned Alpine"
    # decision 7 (row 93): pinned exactly, and at least 1.22 (psycopg's minimum for prepared statements)
    pin = re.search(r"'pgbouncer=(\d+)\.(\d+)\.(\d+)-r(\d+)'", text)
    assert pin, "PgBouncer is pinned exactly (pgbouncer=X.Y.Z-rN)"
    assert tuple(int(x) for x in pin.groups()[:3]) >= (1, 22, 0)
    assert ">=" not in text and "~" not in text, "no fuzzy pins"
    assert re.search(r"'postgresql16-client=\d+\.\d+-r\d+'", text), "psql for the healthcheck, pinned"
    assert "COPY healthcheck.sh /usr/local/bin/pgbouncer-healthcheck.sh" in text
    assert re.search(r"chmod 0755 .*/usr/local/bin/pgbouncer-healthcheck\.sh", text)
    assert re.search(r"^USER 10001$", text, re.M)


def test_pgbouncer_healthcheck_logs_in_as_app():
    """Decision 8 (row 92): the healthcheck logs in through the pool as aslms_app; the password only as PGPASSWORD."""
    script = (PGB / "healthcheck.sh").read_text("utf-8")
    assert "\r" not in script, "the healthcheck runs in a Linux container: LF line endings"
    assert "set -eu" in script
    assert ': "${ASLMS_APP_PASSWORD:?}"' in script
    code = [row for row in script.splitlines() if not row.lstrip().startswith("#")]
    psql = next(row for row in code if "psql " in row)
    for part in ("-U aslms_app", "-h 127.0.0.1", "-p 6432", "'SELECT 1'", "-X", "-A", "-t"):
        assert part in psql, part
    assert "PGCONNECT_TIMEOUT=3" in script
    assert 'PGPASSWORD="$ASLMS_APP_PASSWORD"' in script
    assert not re.search(r"(?<![A-Z])password=", script), "no password in a conninfo"
    uses = [row for row in code if "ASLMS_APP_PASSWORD" in row]
    assert len(uses) == 2, uses  # the required-variable check and PGPASSWORD
    assert not any(re.search(r"\b(?:echo|printf)\b", row) for row in code), "nothing is echoed"
    assert '[ "$out" = "1" ]' in script
    healthcheck = _services()["pgbouncer"]["healthcheck"]
    assert healthcheck["test"] == ["CMD", "/bin/sh", "/usr/local/bin/pgbouncer-healthcheck.sh"]
    assert "$" not in str(healthcheck), "nothing is interpolated into the healthcheck"
    assert healthcheck["start_period"] == "10s"
    assert (healthcheck["interval"], healthcheck["timeout"], healthcheck["retries"]) == ("5s", "5s", 20)


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
