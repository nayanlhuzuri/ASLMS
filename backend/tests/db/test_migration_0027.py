"""Migration 0027 (design partial-code-match, "Data"; the note's "0026" by build order): the partial counsel-code
weight column and its two CHECKs; on a database with a settings version, the upgrade closes it and inserts the next
one with partial 0.600 (or the thresholds' midpoint when 0.600 falls outside the band) and the other values copied,
with one audit row and one `config_changed` event; an empty table gets nothing; the downgrade drops the column and the
constraints, keeps the inserted version and writes its own audit row."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.orm import sessionmaker

from aslms.services.seed import seed_all
from tests.db.conftest import alembic_config, wipe, wipe_if_migrated

pytestmark = pytest.mark.migration_cycle

PATH = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0027_partial_code_match.py"
CONSTRAINTS = ("ck_scoring_settings_partial", "ck_scoring_settings_partial_current")


def _module():
    spec = importlib.util.spec_from_file_location("m0027", PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def at_0026(db_url, engine) -> Iterator:
    """A seeded database at 0026 with an empty `scoring_settings`, `audit_log` and `events`; afterwards back at
    head and wiped."""
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    try:
        with sessionmaker(bind=engine)() as s:
            seed_all(s)
            s.commit()
        command.downgrade(cfg, "0026")
        with engine.begin() as conn:
            conn.execute(sa.text("SET session_replication_role = replica"))  # audit_log is append-only
            for table in ("scoring_settings", "audit_log", "events"):
                conn.execute(sa.text(f"DELETE FROM {table}"))
            conn.execute(sa.text("SET session_replication_role = DEFAULT"))
        yield cfg
    finally:
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            wipe(conn)


def _insert_v1(engine, *, cc=0.95, strong=0.85, possible=0.5) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO scoring_settings (version, weight_counsel_code, weight_name_pattern, weight_watchlist, "
                "weight_linked_case, weight_keyword, threshold_strong, threshold_possible, reason, is_current) "
                "VALUES (1, :cc, 0.8, 0.75, 0.7, 0.4, :s, :p, 'Plan §4.2 defaults', true)"
            ),
            {"cc": cc, "s": strong, "p": possible},
        )


def _versions(engine) -> list:
    with engine.connect() as conn:
        return conn.execute(
            sa.text(
                "SELECT version, weight_counsel_code, weight_name_pattern, weight_watchlist, weight_linked_case, "
                "weight_keyword, weight_counsel_code_partial, threshold_strong, threshold_possible, is_current, "
                "valid_to, reason, created_by, id FROM scoring_settings ORDER BY version"
            )
        ).all()


def _audits(engine) -> list:
    with engine.connect() as conn:
        return conn.execute(
            sa.text(
                "SELECT entity_id, actor_name, before, after FROM audit_log "
                "WHERE action = 'scoring_settings.update' ORDER BY created_at"
            )
        ).all()


def _constraints(engine) -> set[str]:
    with engine.connect() as conn:
        return set(
            conn.execute(
                sa.text(
                    "SELECT conname FROM pg_constraint WHERE conrelid = 'scoring_settings'::regclass "
                    "AND conname LIKE 'ck_scoring_settings_partial%'"
                )
            ).scalars()
        )


def _has_column(engine) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                sa.text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'scoring_settings' "
                    "AND column_name = 'weight_counsel_code_partial')"
                )
            ).scalar()
        )


def test_upgrade_inserts_next_version_and_downgrade_keeps_it(at_0026, engine):
    _insert_v1(engine)
    command.upgrade(at_0026, "0027")
    assert _has_column(engine) and _constraints(engine) == set(CONSTRAINTS)
    v1, v2 = _versions(engine)
    assert v1.weight_counsel_code_partial is None and not v1.is_current and v1.valid_to is not None
    assert v2.version == 2 and v2.is_current and v2.valid_to is None and v2.created_by is None
    assert v2.weight_counsel_code_partial == Decimal("0.600")
    assert v2[1:6] == v1[1:6] and (v2.threshold_strong, v2.threshold_possible) == (
        v1.threshold_strong,
        v1.threshold_possible,
    )
    assert v2.reason == "Partial counsel-code match added (design partial-code-match), partial weight 0.600"
    (audit,) = _audits(engine)
    assert audit.entity_id == v2.id and audit.actor_name == "migration 0027"
    assert audit.before["version"] == 1 and "counsel_code_partial" not in audit.before["weights"]
    assert audit.after["version"] == 2 and audit.after["weights"]["counsel_code_partial"] == 0.6
    assert len(audit.after["weights"]) == 6 and audit.after["migration"] == "0027"
    assert audit.after["reason"] == v2.reason
    with engine.connect() as conn:
        (event,) = conn.execute(
            sa.text("SELECT payload, dedupe_key FROM events WHERE type = 'config_changed'")
        ).all()
    assert event.payload == {"entity": "scoring_settings", "id": str(v2.id), "action": "update", "version": 2}
    assert event.dedupe_key == f"scoring_settings:{v2.id}"

    command.downgrade(at_0026, "0026")
    assert not _has_column(engine) and _constraints(engine) == set()
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT version, is_current FROM scoring_settings ORDER BY version")
        ).all()
    assert [tuple(r) for r in rows] == [(1, False), (2, True)]
    first, down = _audits(engine)
    assert down.entity_id == v2.id and down.after["migration"] == "0027-downgrade"
    assert down.before["weights"]["counsel_code_partial"] == 0.6
    assert "counsel_code_partial" not in down.after["weights"]


def test_upgrade_writes_the_midpoint_outside_the_band(at_0026, engine):
    _insert_v1(engine, strong=0.9, possible=0.65)
    command.upgrade(at_0026, "0027")
    v2 = _versions(engine)[-1]
    assert v2.weight_counsel_code_partial == Decimal("0.775")
    assert v2.reason.endswith("partial weight 0.775")


def test_partial_weight_rule():
    f = _module().partial_weight
    assert f(Decimal("0.95"), Decimal("0.85"), Decimal("0.5")) == Decimal("0.600")
    assert f(Decimal("0.95"), Decimal("0.9"), Decimal("0.65")) == Decimal("0.775")
    assert f(Decimal("0.95"), Decimal("0.6"), Decimal("0.4")) == Decimal("0.500")  # 0.600 not below strong
    assert f(Decimal("0.7"), Decimal("0.9"), Decimal("0.7")) == Decimal("0.699")  # lowered below counsel_code
    assert f(Decimal("0.6"), Decimal("0.85"), Decimal("0.5")) == Decimal("0.599")


def test_empty_table_gets_no_row(at_0026, engine):
    command.upgrade(at_0026, "0027")
    assert _versions(engine) == [] and _audits(engine) == []
    assert _constraints(engine) == set(CONSTRAINTS)


def test_partial_current_check_refuses_a_current_row_without_the_weight(session):
    session.execute(sa.text("DELETE FROM scoring_settings"))
    with pytest.raises(sa.exc.IntegrityError, match="ck_scoring_settings_partial_current"):
        with session.begin_nested():
            session.execute(
                sa.text(
                    "INSERT INTO scoring_settings (version, weight_counsel_code, weight_name_pattern, "
                    "weight_watchlist, weight_linked_case, weight_keyword, threshold_strong, threshold_possible, "
                    "reason, is_current) VALUES (5, 0.95, 0.8, 0.75, 0.7, 0.4, 0.85, 0.5, 'x', true)"
                )
            )
