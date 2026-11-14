"""The six new office kinds (design `offices-import`, decisions 1-6): placed under a department only, a Unit inside
each, at the directorate tier inside the department's visibility, delegable to the department administrator, never
Department-tier; and office codes at most 17 characters on the portal and the command line."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from aslms.cli.main import app as cli_app
from aslms.domain.org import Office, PermissionEffect
from aslms.domain.reference import OfficeKind, Permission, Role
from aslms.services import access, matching, offices
from aslms.services import ownership as own
from aslms.services.offices import NEW_KINDS, OfficeError
from aslms.services.visibility import access_basis
from tests.db.world import add_membership, make_case

pytestmark = pytest.mark.usefixtures("world")


def _create(s, world, code, kind, parent, by="root"):
    actor, user = world.actor(s, by)
    return offices.create_office(
        s, actor, user, code=code, name=f"Office {code}", kind=kind, parent=world.office(s, parent)
    )


def test_new_kinds_placed_under_department_only(world):
    with world.Session() as s:
        for i, kind in enumerate(NEW_KINDS):
            o = _create(s, world, f"EDU-N{i}", kind, "EDU")
            assert o.kind == kind and o.path == f"GOA/EDU/EDU-N{i}"
            for parent in ("GOA", "EDU-DSE", "CENTRAL"):
                with pytest.raises(OfficeError, match="cannot be placed"):
                    _create(s, world, f"X{i}{parent[:3]}", kind, parent)
        s.rollback()


def test_unit_under_each_new_kind(world):
    with world.Session() as s:
        for i, kind in enumerate(NEW_KINDS):
            _create(s, world, f"EDU-N{i}", kind, "EDU")
            unit = _create(s, world, f"EDU-N{i}-U", OfficeKind.UNIT, f"EDU-N{i}")
            assert unit.path == f"GOA/EDU/EDU-N{i}/EDU-N{i}-U"
            # nothing but a Unit sits inside one of the new kinds
            with pytest.raises(OfficeError, match="cannot be placed"):
                _create(s, world, f"EDU-N{i}-D", OfficeKind.DIRECTORATE, f"EDU-N{i}")
        s.rollback()


def test_new_kinds_are_directorate_tier_and_inside_department_visibility(world):
    with world.Session() as s:
        board = _create(s, world, "EDU-BRD", OfficeKind.BOARD_CORPORATION, "EDU")
        assert offices.tier_of(board) == "directorate"
        assert access.department_of(s, board).code == "EDU"
        board_user = world.user(s, "health_off")
        # a second membership of a HEALTH officer, as a directorate user at the Board under EDU
        add_membership(s, board_user, board, Role.DIRECTORATE_USER)
        case = make_case(s)
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, case, unit_code="EDU-BRD")
        s.flush()
        assert access_basis(s, world.user(s, "edu_head"), case)  # the whole department
        assert access_basis(s, board_user, case)  # the case is with a unit inside the Board's subtree
        assert not access_basis(s, world.user(s, "health_admin"), case)
        assert access.in_scope(s, world.user(s, "edu_head"), board)
        assert not access.in_scope(s, world.user(s, "health_admin"), board)
        s.rollback()


def test_department_admin_may_create_new_kinds_in_own_subtree(world):
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        access.set_override(
            s, actor, root, world.user(s, "edu_admin"), Permission.OFFICES_MANAGE, PermissionEffect.GRANT
        )
        for i, kind in enumerate(NEW_KINDS):
            o = _create(s, world, f"EDU-A{i}", kind, "EDU", by="edu_admin")
            assert o.parent_id == world.office(s, "EDU").id
        with pytest.raises(access.Forbidden):
            _create(s, world, "HEALTH-B", OfficeKind.BOARD_CORPORATION, "HEALTH", by="edu_admin")
        s.rollback()


def test_new_kinds_never_department_tier(world):
    with world.Session() as s:
        made = [_create(s, world, f"EDU-T{i}", kind, "EDU") for i, kind in enumerate(NEW_KINDS)]
        for o in made:
            assert not access.is_department(o)
            assert access.department_of(s, o).code == "EDU"
            assert OfficeKind(o.kind) not in access.DEPARTMENT_TIER_KINDS
            assert OfficeKind(o.kind) not in matching.DEPARTMENT_TIER_KINDS
            assert OfficeKind(o.kind) not in offices.DEPARTMENT_TIER_KINDS
        node = offices.office_tree(s, [world.office(s, "EDU")])[0]
        assert all(c.tier == "directorate" and not c.no_head for c in node.children)
        s.rollback()


def test_office_code_over_17_refused_portal_and_cli(world, monkeypatch):
    from contextlib import contextmanager

    from aslms.api.main import create_app
    from aslms.cli import offices as cli_offices
    from aslms.core.config import Settings
    from tests.db.auth_support import bearer, ready_all

    with world.Session() as s:
        with pytest.raises(OfficeError, match="2 to 17 characters"):
            _create(s, world, "EDU-ABCDEFGHIJKLMN", OfficeKind.DIRECTORATE, "EDU")  # 18
        assert _create(s, world, "EDU-ABCDEFGHIJKLM", OfficeKind.DIRECTORATE, "EDU").code  # 17
        s.rollback()
    with world.Session() as s:
        ready_all(s)
        s.commit()
    settings = Settings(_env_file=None, aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters")
    with TestClient(create_app(settings, world.Session)) as api:
        root = bearer(api, "root@example.org", "correct-horse-battery-7")
        r = api.post(
            "/admin/offices",
            json={
                "code": "EDU-ABCDEFGHIJKLMN",
                "name": "Too Long",
                "kind": "directorate",
                "parent_code": "EDU",
            },
            headers=root,
        )
        assert r.status_code == 422, r.text
        r = api.post(
            "/admin/offices",
            json={"code": "EDU-INST", "name": "An Institute", "kind": "institution", "parent_code": "EDU"},
            headers=root,
        )
        assert r.status_code == 201, r.text
        assert r.json()["kind"] == "institution" and r.json()["tier"] == "directorate"

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

    monkeypatch.setattr(cli_offices, "session_scope", scope)
    r = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"}).invoke(
        cli_app,
        [
            "offices",
            "create",
            "--code",
            "EDU-ABCDEFGHIJKLMN",
            "--name",
            "Too Long",
            "--kind",
            "unit",
            "--parent",
            "EDU",
        ],
    )
    assert r.exit_code != 0 and "17" in r.output
    with world.Session() as s:
        assert s.scalar(sa.select(Office.id).where(Office.code == "EDU-ABCDEFGHIJKLMN")) is None
