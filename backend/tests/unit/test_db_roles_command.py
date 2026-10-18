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
