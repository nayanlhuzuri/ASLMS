"""Design github-and-ci, decisions 4 and 5: the run-database name, the sweep pattern, the `test` guard of
`ASLMS_TEST_DB_PER_RUN=0`, and the rule that every test cycling migrations is marked `migration_cycle`."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import warnings
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from tests.db import rundb

BACKEND = Path(__file__).resolve().parents[2]
DB_TESTS = BACKEND / "tests" / "db"


def test_run_name_matches_the_pattern_and_fits():
    name = rundb.run_database_name("aslms_test", datetime(2026, 10, 20, 10, 15, tzinfo=UTC), "a1b2c3")
    assert name == "aslms_test_20261020101500_a1b2c3"
    assert rundb.run_name_pattern("aslms_test").match(rundb.run_database_name("aslms_test"))
    long = rundb.run_database_name("x" * 100)
    assert len(long) <= 63
    assert rundb.run_name_pattern("x" * 100).match(long)
    assert rundb.run_database_name("ASLMS_Test").startswith("aslms_test_")


def test_test_url_changes_only_the_database(monkeypatch):
    monkeypatch.setenv("ASLMS_TEST_DATABASE_URL", "postgresql+psycopg://u:p%40ss@db.example:6543/base_test")
    base = rundb.base_url()
    url = make_url(rundb.url_string(base.set(database=rundb.run_database_name(base.database))))
    assert (url.drivername, url.username, url.password, url.host, url.port) == (
        "postgresql+psycopg",
        "u",
        "p@ss",
        "db.example",
        6543,
    )
    assert url.database != "base_test"
    assert rundb.run_name_pattern("base_test").match(url.database)


def test_conftest_test_url_keeps_server_and_credentials():
    from tests.db import conftest

    got, base = make_url(conftest.TEST_URL), conftest.BASE_URL
    assert (got.username, got.password, got.host, got.port) == (
        base.username,
        base.password,
        base.host,
        base.port,
    )
    if conftest.PER_RUN:
        assert got.database != base.database
        assert rundb.run_name_pattern(base.database).match(got.database)


def test_sweep_pattern_matches_only_run_names():
    pattern = rundb.run_name_pattern("aslms_test")
    for name in (
        "aslms",
        "aslms_test",
        "aslms_test_x",
        "aslms_restore_check",
        "aslms_test_2026102010150_a1b2c3",
        "aslms_test_20261020101500_a1b2c",
        "aslms_test_20261020101500_A1B2C3",
        "aslms_test_20261020101500_a1b2c3_x",
        "xaslms_test_20261020101500_a1b2c3",
        "aslms_testX20261020101500_a1b2c3",
    ):
        assert not pattern.match(name), name
    assert pattern.match("aslms_test_20261020101500_a1b2c3")


def test_stale_names_keeps_fresh_and_foreign():
    now = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    stale = rundb.run_database_name("aslms_test", now - timedelta(hours=25), "aaaaaa")
    fresh = rundb.run_database_name("aslms_test", now - timedelta(hours=23), "bbbbbb")
    bad_date = "aslms_test_20261399000000_cccccc"
    assert rundb.stale_names([stale, fresh, bad_date, "aslms", "aslms_test"], "aslms_test", now) == [stale]


@pytest.mark.parametrize("name", ["aslms", "postgres", "", None, "prod"])
def test_named_mode_refuses_a_database_without_test(name):
    with pytest.raises(ValueError, match="ASLMS_TEST_DB_PER_RUN=0"):
        rundb.check_named_database(name)


def test_named_mode_accepts_a_test_database():
    rundb.check_named_database("aslms_test")
    rundb.check_named_database("my_TEST_db")


def test_named_mode_refusal_through_pytest(tmp_path):
    """The fixture refuses `aslms` with ASLMS_TEST_DB_PER_RUN=0 before it touches the server (an unreachable port)."""
    env = {
        **os.environ,
        "ASLMS_TEST_DB_PER_RUN": "0",
        "ASLMS_TEST_DATABASE_URL": "postgresql+psycopg://u:p@127.0.0.1:1/aslms",
        "ASLMS_TEST_REQUIRE_DB": "0",
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/db/test_run_database.py::test_cluster_roles_exist_after_db_url",
        ],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode != 0
    assert "does not contain 'test'" in proc.stdout


# ------------------------------------------------------------------ the migration_cycle marker rule (AST scan)
def _marks_cycle(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Attribute) and n.attr == "migration_cycle" for n in ast.walk(node))


def _cycles(fn: ast.AST) -> bool:
    for n in ast.walk(fn):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in {"upgrade", "downgrade"}
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "command"
        ):
            return True
    return False


def _is_fixture(fn: ast.FunctionDef) -> bool:
    return any("fixture" in ast.unparse(d) for d in fn.decorator_list)


def unmarked_cycling_tests(path: Path) -> list[str]:
    with warnings.catch_warnings():  # an odd escape in a test string is not this rule's business
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(path.read_text(encoding="utf-8"))
    module_marked = any(
        isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in n.targets)
        and _marks_cycle(n.value)
        for n in tree.body
    )
    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
    cycling_fixtures = {f.name for f in funcs if _is_fixture(f) and _cycles(f)}
    out = []
    for f in funcs:
        if not f.name.startswith("test"):
            continue
        uses = {a.arg for a in f.args.args} & cycling_fixtures
        if not (_cycles(f) or uses):
            continue
        if module_marked or any(_marks_cycle(d) for d in f.decorator_list):
            continue
        out.append(f"{path.name}::{f.name}")
    return out


def test_every_migration_cycling_test_is_marked():
    files = [p for p in sorted(DB_TESTS.glob("*.py")) if p.name != "conftest.py"]
    assert files
    missing = [m for p in files for m in unmarked_cycling_tests(p)]
    assert missing == [], f"mark these @pytest.mark.migration_cycle: {missing}"


def test_marker_scan_finds_an_unmarked_test(tmp_path):
    bad = tmp_path / "test_bad.py"
    bad.write_text(
        "import pytest\nfrom alembic import command\n\n"
        "@pytest.fixture()\ndef down(cfg):\n    command.downgrade(cfg, 'base')\n\n"
        "def test_a(cfg):\n    command.upgrade(cfg, 'head')\n\n"
        "def test_b(down):\n    pass\n\n"
        "@pytest.mark.migration_cycle\ndef test_c(cfg):\n    command.upgrade(cfg, 'head')\n",
        encoding="utf-8",
    )
    assert unmarked_cycling_tests(bad) == ["test_bad.py::test_a", "test_bad.py::test_b"]


def test_marker_is_registered():
    text = (BACKEND / "pyproject.toml").read_text(encoding="utf-8")
    assert '"migration_cycle:' in text
