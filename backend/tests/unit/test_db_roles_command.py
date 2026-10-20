"""`aslms db-roles` (safety-fixes decision 2): refuses a weak password before touching the database, never echoes
a password, sets both roles when valid, and reports a database failure as exit 1."""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from aslms.cli import db as dbmod
from aslms.cli.main import app

GOOD = "a1b2c3d4e5f6a7b8c9d0e1f2"


class FakeSettings:
    migrate_url = "postgresql+psycopg://owner@localhost/x"

    def __init__(self, app_pw, ro_pw=None):
        self.aslms_app_password = SecretStr(app_pw) if app_pw is not None else None
        self.aslms_readonly_password = SecretStr(ro_pw) if ro_pw else None


@pytest.fixture
def calls(monkeypatch):
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(dbmod, "_set_password", lambda url, role, pw: seen.append((role, pw)))
    return seen


def run(monkeypatch, settings):
    monkeypatch.setattr("aslms.core.config.get_settings", lambda: settings)
    return CliRunner().invoke(app, ["db-roles"])


@pytest.mark.parametrize("pw", [None, "", "qzxwvk", "aslms_app", "has space and more chars!!", "x" * 15])
def test_db_roles_refuses_bad_app_password_without_touching_db(monkeypatch, calls, pw):
    res = run(monkeypatch, FakeSettings(pw))
    assert res.exit_code == 1
    assert calls == []
    if pw:
        assert pw not in res.output


def test_db_roles_sets_app_and_readonly(monkeypatch, calls):
    res = run(monkeypatch, FakeSettings(GOOD, GOOD + "ro"))
    assert res.exit_code == 0
    assert [r for r, _ in calls] == ["aslms_app", "aslms_readonly"]
    assert GOOD not in res.output
    assert "aslms_app password set" in res.output


def test_db_roles_blank_readonly_is_left_alone(monkeypatch, calls):
    res = run(monkeypatch, FakeSettings(GOOD))
    assert res.exit_code == 0
    assert [r for r, _ in calls] == ["aslms_app"]


def test_db_roles_refuses_bad_readonly_before_setting_anything(monkeypatch, calls):
    res = run(monkeypatch, FakeSettings(GOOD, "weak"))
    assert res.exit_code == 1
    assert calls == []


def test_db_roles_database_failure_exits_1_without_leaking(monkeypatch):
    def boom(url, role, pw):
        raise RuntimeError(f"fail {pw}")

    monkeypatch.setattr(dbmod, "_set_password", boom)
    res = run(monkeypatch, FakeSettings(GOOD))
    assert res.exit_code == 1
    assert GOOD not in res.output


def test_set_password_sends_a_verifier_not_the_text(monkeypatch):
    """Design pre-pilot-hardening, decision 5: the role password is sent as a client-side SCRAM-SHA-256 verifier, with
    the algorithm named, after SET LOCAL log_statement = 'none'."""
    import sqlalchemy

    executed: list[object] = []
    asked: list[tuple[bytes, bytes, bytes]] = []
    events: list[str] = []

    class FakePgConn:
        def encrypt_password(self, password, user, algorithm=None):
            asked.append((password, user, algorithm))
            return b"SCRAM-SHA-256$4096:fake"

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, statement):
            executed.append(statement)

    class FakeRaw:
        driver_connection = type("Driver", (), {"pgconn": FakePgConn()})()

        def cursor(self):
            return FakeCursor()

        def commit(self):
            events.append("commit")

        def close(self):
            events.append("close")

    class FakeEngine:
        def raw_connection(self):
            return FakeRaw()

        def dispose(self):
            events.append("dispose")

    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *a, **k: FakeEngine())
    dbmod._set_password("postgresql+psycopg://owner@localhost/x", "aslms_app", GOOD)
    assert asked == [(GOOD.encode(), b"aslms_app", b"scram-sha-256")]
    assert executed[0] == "SET LOCAL log_statement = 'none'"
    statement = executed[1].as_string(None)
    assert statement == "ALTER ROLE \"aslms_app\" LOGIN PASSWORD 'SCRAM-SHA-256$4096:fake'"
    assert GOOD not in statement
    assert events == ["commit", "close", "dispose"]


def test_role_password_statement_quotes_the_verifier():
    class PgConn:
        def encrypt_password(self, password, user, algorithm=None):
            return b"SCRAM-SHA-256$4096:it's"

    statement = dbmod.role_password_statement(PgConn(), "aslms_readonly", GOOD).as_string(None)
    assert statement == "ALTER ROLE \"aslms_readonly\" LOGIN PASSWORD 'SCRAM-SHA-256$4096:it''s'"
