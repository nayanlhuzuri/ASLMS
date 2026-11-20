"""Migration 0038 (design `order-sections`, "Data"): the four enum types, `order_sections` with its CHECKs, indexes,
class comment, triggers and grants (`aslms_app` SELECT / INSERT / UPDATE, never DELETE), `order_kind` reused and kept;
up, down, up on an empty table and on a filled one (the table is derived: the downgrade needs no refusal)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command

from tests.db.conftest import alembic_config, head_revision, wipe_if_migrated

pytestmark = pytest.mark.migration_cycle

TYPES = ("order_layout", "order_outcome", "order_section_flag", "order_section_replace_reason")


def _state(conn) -> dict:
    q = lambda sql: conn.execute(sa.text(sql)).scalar()  # noqa: E731
    return {
        "table": q("SELECT to_regclass('order_sections') IS NOT NULL"),
        "types": q(f"SELECT count(*) FROM pg_type WHERE typname IN {TYPES}"),
        "order_kind": q("SELECT count(*) FROM pg_type WHERE typname = 'order_kind'"),
        "function": q("SELECT count(*) FROM pg_proc WHERE proname = 'aslms_order_section_replace_once'"),
    }


def _fill(engine) -> None:
    """The seed, one order with a stored PDF and one reading of it (through the reader). At 0038 the seed's
    scoring-settings step is left out (no `weight_named_in_title` before 0040, design state-insights): it is not what
    this test is about."""
    from unittest.mock import patch

    from sqlalchemy.orm import Session

    from aslms.services import order_sections, scoring_settings
    from aslms.services.seed import seed_all
    from tests.db import next_dates_support as h
    from tests.db import order_sections_support as o
    from tests.db.world import make_case

    with Session(engine) as s, patch.object(scoring_settings, "seed_default", lambda s, report: None):
        seed_all(s)
        case = make_case(s)
        h.order_with_text(s, case, o.order_text(cnr=case.cnr, case_no=case.case_no_text))
        assert order_sections.read_batch(s, batch=10)["parsed"] == 1
        s.commit()


def test_migration_0038_cycles(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    try:
        command.downgrade(cfg, "0037")
        with engine.connect() as conn:
            assert _state(conn) == {"table": False, "types": 0, "order_kind": 1, "function": 0}
        command.upgrade(cfg, "0038")
        with engine.connect() as conn:
            assert _state(conn) == {"table": True, "types": 4, "order_kind": 1, "function": 1}
            priv = lambda role, p: conn.execute(  # noqa: E731
                sa.text("SELECT has_table_privilege(:r, 'order_sections', :p)"), {"r": role, "p": p}
            ).scalar()
            assert priv("aslms_app", "SELECT") and priv("aslms_app", "INSERT") and priv("aslms_app", "UPDATE")
            assert not priv("aslms_app", "DELETE")
            assert priv("aslms_readonly", "SELECT") and not priv("aslms_readonly", "UPDATE")
            assert (
                conn.execute(sa.text("SELECT obj_description('order_sections'::regclass)")).scalar()
                == "class=derived"
            )
            names = set(
                conn.execute(
                    sa.text("SELECT conname FROM pg_constraint WHERE conrelid = 'order_sections'::regclass")
                ).scalars()
            )
            assert {
                "ck_order_sections_replaced",
                "ck_order_sections_successor",
                "ck_order_sections_whole",
                "ck_order_sections_registrar",
                "ck_order_sections_outcome",
                "fk_order_sections_replaced_by_id_order_sections",
                "pk_order_sections",
            } <= names
            deferred = conn.execute(
                sa.text(
                    "SELECT condeferrable AND condeferred FROM pg_constraint "
                    "WHERE conname = 'fk_order_sections_replaced_by_id_order_sections'"
                )
            ).scalar()
            assert deferred
            indexes = set(
                conn.execute(
                    sa.text("SELECT indexname FROM pg_indexes WHERE tablename = 'order_sections'")
                ).scalars()
            )
            assert {
                "ix_order_sections_current",
                "ix_order_sections_order_created",
                "ix_order_sections_document_id",
                "ix_order_sections_replaced_by_id",
                "ix_order_sections_body_sha256",
            } <= indexes
            triggers = set(
                conn.execute(
                    sa.text(
                        "SELECT tgname FROM pg_trigger WHERE tgrelid = 'order_sections'::regclass AND NOT tgisinternal"
                    )
                ).scalars()
            )
            assert triggers == {"order_sections_replace_once", "order_sections_updated_at"}
            labels = conn.execute(
                sa.text(
                    "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = 'order_outcome' ORDER BY e.enumsortorder"
                )
            ).scalars()
            assert list(labels) == [
                "allowed",
                "partly_allowed",
                "dismissed",
                "disposed_of",
                "withdrawn",
                "closed",
            ]
        # a filled table goes down and up too
        _fill(engine)
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT count(*) FROM order_sections")).scalar() == 1
        command.downgrade(cfg, "0037")
        with engine.connect() as conn:
            assert _state(conn) == {"table": False, "types": 0, "order_kind": 1, "function": 0}
        command.upgrade(cfg, "0038")
    finally:
        wipe_if_migrated(db_url)
        command.upgrade(cfg, head_revision())
