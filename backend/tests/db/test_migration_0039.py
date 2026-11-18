"""Migration 0039 (design `state-insights`, "Data"): the five tables with their checks, keys, triggers, grants and class
comments, the reference rows on a database that has the court and its case types; up, down, up; the downgrade refuses
after a person's edit; the database matches the models at head."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from aslms.db.base import Base
from tests.db.conftest import alembic_config, head_revision, wipe_if_migrated

pytestmark = pytest.mark.migration_cycle

TABLES = (
    "insight_groups",
    "insight_subject_categories",
    "insight_case_type_groups",
    "insight_case_facts",
    "office_title_names",
)
CLASSES = {
    "insight_groups": "class=master",
    "insight_subject_categories": "class=master",
    "insight_case_type_groups": "class=master",
    "insight_case_facts": "class=derived",
    "office_title_names": "class=master",
}


def _present(conn) -> dict[str, bool]:
    return {
        t: conn.execute(sa.text(f"SELECT to_regclass('public.{t}') IS NOT NULL")).scalar() for t in TABLES
    }


def _court_and_types(conn) -> None:
    """The Gauhati High Court's principal seat and two case types, as the seed and the master sync hold them."""
    court = conn.execute(sa.text("SELECT id FROM courts WHERE est_code = 'GAHC01'")).scalar()
    if court is None:
        court = conn.execute(
            sa.text(
                "INSERT INTO courts (est_code, name, court_level, ref_code) "
                "VALUES ('GAHC01', 'Gauhati High Court, Principal Seat', 'hc', 'GHC') RETURNING id"
            )
        ).scalar()
    for code, short in ((111, "WP(C)"), (220, "I.A.(Civil)")):
        conn.execute(
            sa.text(
                "INSERT INTO case_types (court_id, case_type_code, type_name, short_name) "
                "SELECT :c, :code, :name, :short WHERE NOT EXISTS "
                "(SELECT 1 FROM case_types WHERE court_id = :c AND case_type_code = :code)"
            ),
            {"c": court, "code": code, "name": f"{short} : x", "short": short},
        )


def test_migration_0039_up_down_up(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    try:
        command.downgrade(cfg, "0038")
        with engine.connect() as conn:
            assert not any(_present(conn).values())
        with engine.begin() as conn:
            _court_and_types(conn)
        command.upgrade(cfg, "0039")
        with engine.connect() as conn:
            assert all(_present(conn).values())
            q = lambda sql: conn.execute(sa.text(sql)).scalar()  # noqa: E731
            assert q("SELECT count(*) FROM insight_groups WHERE kind = 'family'") == 20
            assert q("SELECT count(*) FROM insight_groups WHERE kind = 'subject'") == 15
            assert q("SELECT count(*) FROM insight_groups WHERE is_reserved") == 4
            assert q("SELECT count(*) FROM insight_subject_categories") == 235
            assert (
                q(
                    "SELECT g.code FROM insight_case_type_groups t JOIN insight_groups g ON g.id = t.group_id "
                    "JOIN case_types ct ON ct.id = t.case_type_id WHERE ct.case_type_code = 220"
                )
                == "ia"
            )
            assert q("SELECT count(*) FROM audit_log") == 0  # reference data writes no audit row
            for table, klass in CLASSES.items():
                assert q(f"SELECT obj_description('{table}'::regclass)") == klass
                privilege = lambda role, p, t=table: conn.execute(  # noqa: E731
                    sa.text("SELECT has_table_privilege(:r, :t, :p)"), {"r": role, "t": t, "p": p}
                ).scalar()
                assert privilege("aslms_app", "INSERT") and privilege("aslms_app", "UPDATE")
                assert not privilege("aslms_app", "DELETE") and privilege("aslms_readonly", "SELECT")
                assert privilege("aslms_owner", "DELETE")
                triggers = set(
                    conn.execute(
                        sa.text(
                            f"SELECT tgname FROM pg_trigger WHERE tgrelid = '{table}'::regclass AND NOT tgisinternal"
                        )
                    ).scalars()
                )
                assert f"{table}_updated_at" in triggers
            assert q("SELECT count(*) FROM pg_trigger WHERE tgname = 'insight_groups_fixed'") == 1
            names = set(
                conn.execute(
                    sa.text(
                        "SELECT conname FROM pg_constraint WHERE conrelid = 'insight_case_facts'::regclass"
                    )
                ).scalars()
            )
            assert {
                "ck_insight_case_facts_basis",
                "ck_insight_case_facts_writ",
                "ck_insight_case_facts_orders",
            } <= names
            # no FK on the two department-id arrays (decision 13)
            fks = q(
                "SELECT count(*) FROM pg_constraint WHERE conrelid = 'insight_case_facts'::regclass AND contype = 'f'"
            )
            assert fks == 4  # case_id, main_case_id, original_writ_case_id, title_order_id
        # a person's edit: the downgrade refuses (no login exists here: the key check is set aside for the row)
        with engine.begin() as conn:
            conn.execute(sa.text("SET session_replication_role = replica"))
            conn.execute(
                sa.text(
                    "UPDATE insight_groups SET label = 'Edited Label', updated_by = gen_random_uuid() WHERE code = 'tax'"
                )
            )
        with pytest.raises(RuntimeError, match="edited group"):
            command.downgrade(cfg, "0038")
        with engine.begin() as conn:
            conn.execute(sa.text("SET session_replication_role = replica"))
            conn.execute(sa.text("UPDATE insight_groups SET updated_by = NULL"))
        command.downgrade(cfg, "0038")
        with engine.connect() as conn:
            assert not any(_present(conn).values())
            assert (
                conn.execute(
                    sa.text("SELECT count(*) FROM pg_proc WHERE proname = 'aslms_insight_group_fixed'")
                ).scalar()
                == 0
            )
    finally:
        command.upgrade(cfg, "head")
        wipe_if_migrated(db_url)  # the court and case types inserted here are not left for later modules
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == head_revision()
        ctx = MigrationContext.configure(conn, opts={"compare_type": True, "compare_server_default": True})
        diff = compare_metadata(ctx, Base.metadata)
    real = [d for d in diff if not (d[0] == "modify_type" and isinstance(d[-1], sa.Enum))]
    assert real == [], real
