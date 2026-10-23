"""Migration 0022 (design alerts-visibility-roles, decision 18; the note's "0021" by build order): the two alert kinds,
the two changed access defaults applied once to an already seeded database (an audit row and an event per change, a
customised row kept with its own audit row), the private-records rule dated by one audit row, nothing written on a
fresh database (the seed carries the new defaults), a downgrade that restores only untouched rows and unused kinds,
and the database matching the models at head."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.orm import sessionmaker

from aslms.db.base import Base
from aslms.domain.alerts import Severity
from aslms.domain.reference import AlertKind
from aslms.services import alerts
from aslms.services.seed import ALERT_KIND_LABELS, ALERT_SEVERITY, seed_all
from tests.db.conftest import alembic_config, wipe, wipe_if_migrated
from tests.db.world import make_case

pytestmark = pytest.mark.migration_cycle

ACTIONS = ("access.matrix_default_changed", "access.matrix_default_kept", "access.rule_changed")


def _scalar(engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(sa.text(sql), params).scalar()


def _enabled(engine, role: str, permission: str) -> bool:
    return _scalar(
        engine,
        "select is_enabled from role_permissions where role = :r and permission = :p",
        r=role,
        p=permission,
    )


def _audits(engine, action: str) -> list:
    with engine.connect() as conn:
        return conn.execute(
            sa.text(
                "select entity_id, actor_name, before, after from audit_log where action = :a order by created_at"
            ),
            {"a": action},
        ).all()


@pytest.fixture()
def cycle(db_url, engine) -> Iterator:
    """A clean database at head; afterwards back at head and wiped."""
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    try:
        yield cfg
    finally:
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            wipe(conn)


def _seeded_at_0021_with_old_defaults(cfg, engine) -> None:
    with sessionmaker(bind=engine)() as s:
        seed_all(s)
        s.commit()
    command.downgrade(cfg, "0021")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "update role_permissions set is_enabled = false "
                "where role = 'dept_head' and permission = 'custody.recall'"
            )
        )
        conn.execute(
            sa.text(
                "update role_permissions set is_enabled = true where role = 'auditor' and permission = 'assistant.use'"
            )
        )


def test_fresh_database_gets_new_defaults_from_seed_and_no_audit(cycle, engine):
    command.downgrade(cycle, "0021")
    command.upgrade(cycle, "head")
    assert _scalar(engine, "select count(*) from role_permissions") == 0
    assert all(_audits(engine, a) == [] for a in ACTIONS)
    with sessionmaker(bind=engine)() as s:
        seed_all(s)
        s.commit()
    assert _enabled(engine, "dept_head", "custody.recall") is True
    assert _enabled(engine, "auditor", "assistant.use") is False
    assert _enabled(engine, "auditor", "cases.view_private_all") is True
    assert _enabled(engine, "state_oversight", "cases.view_private_all") is False
    assert _enabled(engine, "central_operator", "cases.view_private_all") is False
    assert all(_audits(engine, a) == [] for a in ACTIONS)


def test_seeded_database_flips_two_rows_with_audit_and_event(cycle, engine):
    _seeded_at_0021_with_old_defaults(cycle, engine)
    command.upgrade(cycle, "head")
    assert _enabled(engine, "dept_head", "custody.recall") is True
    assert _enabled(engine, "auditor", "assistant.use") is False
    changed = _audits(engine, "access.matrix_default_changed")
    assert len(changed) == 2 and _audits(engine, "access.matrix_default_kept") == []
    by_perm = {row.after["permission"]: row for row in changed}
    head = by_perm["custody.recall"]
    assert head.actor_name == "migration 0022" and head.before == {"is_enabled": False}
    assert head.after == {
        "role": "dept_head",
        "permission": "custody.recall",
        "is_enabled": True,
        "migration": "0022",
        "design": "alerts-visibility-roles",
    }
    assert by_perm["assistant.use"].after["is_enabled"] is False
    with engine.connect() as conn:
        keys = set(
            conn.execute(sa.text("select dedupe_key from events where type = 'access_changed'"))
            .scalars()
            .all()
        )
    assert keys == {
        "access_matrix_default:0022:dept_head:custody.recall",
        "access_matrix_default:0022:auditor:assistant.use",
    }
    with sessionmaker(bind=engine)() as s:  # the seed afterwards changes nothing it did not insert
        seed_all(s)
        s.commit()
    assert _enabled(engine, "dept_head", "custody.recall") is True


def test_customised_row_kept_with_kept_audit(cycle, engine):
    _seeded_at_0021_with_old_defaults(cycle, engine)
    with engine.begin() as conn:
        root = conn.execute(sa.text("select id from users limit 1")).scalar()
        if root is None:  # no login in a bare seed: a row of its own for `updated_by`
            root = conn.execute(
                sa.text(
                    "insert into users (email, password_hash, full_name, role, office_id) "
                    "select 'owner@example.org', 'x', 'Owner', 'super_admin', id from offices where code = 'GOA' "
                    "returning id"
                )
            ).scalar()
        conn.execute(  # the head's row was switched by hand (and back to the old value)
            sa.text(
                "update role_permissions set updated_by = :u where role = 'dept_head' and permission = 'custody.recall'"
            ),
            {"u": root},
        )
        conn.execute(  # the auditor's row has an access.matrix audit row whose value equals the old default
            sa.text(
                "insert into audit_log (action, entity_type, actor_name, after) values "
                "('access.matrix', 'role_permission', 'Owner', "
                '\'{"role": "auditor", "permission": "assistant.use", "is_enabled": true}\'::jsonb)'
            )
        )
    command.upgrade(cycle, "head")
    assert _enabled(engine, "dept_head", "custody.recall") is False
    assert _enabled(engine, "auditor", "assistant.use") is True
    assert _audits(engine, "access.matrix_default_changed") == []
    kept = _audits(engine, "access.matrix_default_kept")
    assert sorted(r.after["permission"] for r in kept) == ["assistant.use", "custody.recall"]
    assert all(r.after["reason"] == "customised" and r.actor_name == "migration 0022" for r in kept)
    assert _scalar(engine, "select count(*) from events where type = 'access_changed'") == 0


def test_rule_changed_audit_written_once_on_seeded_database(cycle, engine):
    _seeded_at_0021_with_old_defaults(cycle, engine)
    command.upgrade(cycle, "head")
    [rule] = _audits(engine, "access.rule_changed")
    assert rule.entity_id is None and rule.actor_name == "migration 0022"
    assert rule.after == {
        "rule": "private_records_state_wide",
        "function": "cases.view_private_all",
        "default_types": ["auditor"],
        "always": ["super_admin"],
        "withdrawn_from": ["state_oversight", "central_operator"],
        "migration": "0022",
    }
    assert (
        _scalar(engine, "select entity_type from audit_log where action = 'access.rule_changed'")
        == "access_rule"
    )


def test_alert_kinds_inserted_and_seed_agrees(cycle, engine):
    _seeded_at_0021_with_old_defaults(cycle, engine)
    assert (
        _scalar(engine, "select count(*) from ref_alert_kind where code in ('new_note', 'listed_tomorrow')")
        == 0
    )
    command.upgrade(cycle, "head")
    with engine.connect() as conn:
        rows = {
            r.code: r
            for r in conn.execute(
                sa.text(
                    "select code, label, default_severity, sort_order, is_active from ref_alert_kind "
                    "where code in ('new_note', 'listed_tomorrow')"
                )
            )
        }
    assert (rows["new_note"].label, rows["new_note"].default_severity, rows["new_note"].sort_order) == (
        "New note",
        "normal",
        130,
    )
    assert (rows["listed_tomorrow"].label, rows["listed_tomorrow"].default_severity) == (
        "Listed for tomorrow",
        "critical",
    )
    assert rows["listed_tomorrow"].sort_order == 140 and all(r.is_active for r in rows.values())
    # the seed carries the same labels, severities and sort orders (enum position x 10)
    for kind in (AlertKind.NEW_NOTE, AlertKind.LISTED_TOMORROW):
        assert ALERT_KIND_LABELS[kind] == rows[kind.value].label
        assert ALERT_SEVERITY.get(kind, "normal") == rows[kind.value].default_severity
        assert (list(AlertKind).index(kind) + 1) * 10 == rows[kind.value].sort_order


def test_downgrade_restores_only_untouched_rows_and_unused_kinds(cycle, engine):
    _seeded_at_0021_with_old_defaults(cycle, engine)
    command.upgrade(cycle, "head")
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:  # a listed_tomorrow alert in use
        from aslms.domain.org import Office

        case = make_case(s)
        office = s.scalar(sa.select(Office).where(Office.code == "GOA"))
        alerts.raise_alert(
            s,
            case=case,
            kind=AlertKind.LISTED_TOMORROW,
            key=f"listed_tomorrow:{case.id}:2026-10-23",
            office=office,
            severity=Severity.CRITICAL,
            data={"hearing_date": "2026-10-23", "entries": [], "entries_total": 0},
        )
        s.commit()
    with engine.begin() as conn:  # the owner switched the auditor's row after the migration
        conn.execute(
            sa.text(
                "insert into audit_log (action, entity_type, actor_name, after, created_at) values "
                "('access.matrix', 'role_permission', 'Owner', "
                '\'{"role": "auditor", "permission": "assistant.use", "is_enabled": false}\'::jsonb, '
                "now() + interval '1 second')"
            )
        )
    command.downgrade(cycle, "0021")
    assert _enabled(engine, "dept_head", "custody.recall") is False  # restored
    assert _enabled(engine, "auditor", "assistant.use") is False  # the owner's later choice stays
    restored = [
        r
        for r in _audits(engine, "access.matrix_default_changed")
        if r.after["migration"] == "0022-downgrade"
    ]
    assert [r.after["permission"] for r in restored] == ["custody.recall"]
    assert restored[0].before == {"is_enabled": True} and restored[0].after["is_enabled"] is False
    assert _scalar(engine, "select count(*) from ref_alert_kind where code = 'new_note'") == 0
    assert _scalar(engine, "select count(*) from ref_alert_kind where code = 'listed_tomorrow'") == 1
    command.upgrade(cycle, "head")  # a re-upgrade applies the untouched default again
    assert _enabled(engine, "dept_head", "custody.recall") is True


def test_database_matches_models_at_head(cycle, engine):
    command.downgrade(cycle, "0021")
    command.upgrade(cycle, "head")
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True, "compare_server_default": True})
        diff = compare_metadata(ctx, Base.metadata)
    real = [d for d in diff if not (d[0] == "modify_type" and isinstance(d[-1], sa.Enum))]
    assert real == [], real
