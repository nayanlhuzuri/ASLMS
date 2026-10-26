"""`aslms users create --no-office` and `aslms offices create --head-email` (design `office-head-picker`, decision 21):
a login with no office is created by the CLI acting as the super admin; exactly one form (`--type` and `--office`, or
`--no-office`); a department names an existing login, including one with no office, with no password prompt; an unknown
`--head-email` exits non-zero with the `--no-office` hint and writes nothing."""

from __future__ import annotations

from contextlib import contextmanager

import sqlalchemy as sa
from typer.testing import CliRunner

from aslms.cli.main import app
from aslms.domain.events import AuditLog
from aslms.domain.org import Office, User, UserMembership
from aslms.domain.reference import Role
from aslms.services import memberships

PW = "given-by-cli-12"


def _scope(world):
    @contextmanager
    def scope():
        s = world.Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    return scope


def _patch(world, monkeypatch) -> None:
    from aslms.cli import offices as cli_offices
    from aslms.cli import users as cli_users

    monkeypatch.setattr(cli_users, "session_scope", _scope(world))
    monkeypatch.setattr(cli_offices, "session_scope", _scope(world))


def _users_create(*args: str):
    return CliRunner().invoke(
        app,
        ["users", "create", "--email", "cli.head@example.org", "--name", "Cli Head", *args, "--password", PW],
    )


def test_cli_users_create_no_office(world, monkeypatch):
    _patch(world, monkeypatch)
    for bad in (
        [],
        ["--type", "dept_officer"],
        ["--office", "EDU"],
        ["--no-office", "--type", "dept_officer"],
    ):
        r = _users_create(*bad)
        assert r.exit_code != 0 and "--no-office" in r.output, (bad, r.output)
    r = _users_create("--no-office", "--designation", "Secretary")
    assert r.exit_code != 0
    r = _users_create("--no-office")
    assert r.exit_code == 0, r.output
    assert "no office yet" in r.output
    with world.Session() as s:
        user = s.scalar(sa.select(User).where(User.email == "cli.head@example.org"))
        assert user.office_id is None and user.role is None
        assert s.scalar(sa.select(sa.func.count()).where(UserMembership.user_id == user.id)) == 0
        row = s.scalars(
            sa.select(AuditLog).where(AuditLog.action == "user.create", AuditLog.entity_id == user.id)
        ).one()
        assert row.after["no_office"] is True and row.actor_user_id == world.users["root"].id


def test_cli_offices_create_existing_head_only(world, monkeypatch):
    _patch(world, monkeypatch)
    base = [
        "offices",
        "create",
        "--code",
        "TESTD",
        "--kind",
        "department",
        "--parent",
        "GOA",
        "--name",
        "Test D",
    ]
    r = CliRunner().invoke(app, [*base, "--head-email", "unknown@example.org"], input="")
    assert r.exit_code != 0 and "aslms users create --no-office" in r.output, r.output
    assert "Password" not in r.output
    with world.Session() as s:
        assert s.scalar(sa.select(Office.id).where(Office.code == "TESTD")) is None
    r = CliRunner().invoke(app, base)
    assert r.exit_code != 0 and "head_required" in r.output
    r = CliRunner().invoke(app, [*base, "--head-email", "x@example.org", "--head-name", "X"])
    assert r.exit_code != 0  # the option is gone
    assert _users_create("--no-office").exit_code == 0
    r = CliRunner().invoke(
        app, [*base, "--head-email", "cli.head@example.org", "--head-designation", "Secretary"], input=""
    )
    assert r.exit_code == 0, r.output
    assert "Password" not in r.output
    with world.Session() as s:
        head = memberships.head_of(s, s.scalar(sa.select(Office).where(Office.code == "TESTD")))
        user = s.get(User, head.user_id)
        assert user.email == "cli.head@example.org" and head.is_primary and head.designation == "Secretary"
        assert user.role == Role.DEPT_HEAD
