"""Migration 0034 (design `next-date-direct`, "Data"): the enum `next_hearing_basis`, six derived columns on `cases`
with their CHECKs, foreign keys and indexes, the `next_date_differs` event type and the `next_date_reported` alert
kind; up, down, up; the downgrade refuses while a `next_date_reported` alert exists."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command

from tests.db.conftest import alembic_config, head_revision, wipe_if_migrated

pytestmark = pytest.mark.migration_cycle

COLUMNS = {
    "next_hearing_on",
    "next_hearing_basis",
    "next_hearing_next_date_id",
    "next_hearing_differs_on",
    "next_hearing_differs_id",
    "next_hearing_set_at",
}


def _state(conn) -> dict:
    q = lambda sql: conn.execute(sa.text(sql)).scalar()  # noqa: E731
    return {
        "columns": set(
            conn.execute(
                sa.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'cases' AND column_name LIKE 'next_hearing_%' AND column_name <> "
                    "'next_hearing_date'"
                )
            ).scalars()
        ),
        "enum": q("SELECT count(*) FROM pg_type WHERE typname = 'next_hearing_basis'"),
        "event": q("SELECT count(*) FROM ref_event_type WHERE code = 'next_date_differs'"),
        "kind": q("SELECT count(*) FROM ref_alert_kind WHERE code = 'next_date_reported'"),
    }


def test_migration_0034_cycles(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    try:
        command.downgrade(cfg, "0033")
        with engine.connect() as conn:
            assert _state(conn) == {"columns": set(), "enum": 0, "event": 0, "kind": 0}
        command.upgrade(cfg, "0034")
        with engine.connect() as conn:
            assert _state(conn) == {"columns": COLUMNS, "enum": 1, "event": 1, "kind": 1}
            labels = conn.execute(
                sa.text(
                    "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = 'next_hearing_basis' ORDER BY e.enumsortorder"
                )
            ).scalars()
            assert list(labels) == ["court", "order", "around", "confirmed", "manual"]
            names = set(
                conn.execute(
                    sa.text("SELECT conname FROM pg_constraint WHERE conrelid = 'cases'::regclass")
                ).scalars()
            )
            assert {
                "ck_cases_next_hearing_basis",
                "ck_cases_next_hearing_row",
                "ck_cases_next_hearing_differs",
                "fk_cases_next_hearing_next_date_id_next_dates",
                "fk_cases_next_hearing_differs_id_next_dates",
            } <= names
            indexes = set(
                conn.execute(sa.text("SELECT indexname FROM pg_indexes WHERE tablename = 'cases'")).scalars()
            )
            assert {
                "ix_cases_next_hearing_on",
                "ix_cases_next_hearing_differs",
                "ix_cases_next_hearing_unset",
            } <= indexes
            assert conn.execute(
                sa.text("SELECT has_table_privilege('aslms_app', 'cases', 'UPDATE')")
            ).scalar()
            row = conn.execute(
                sa.text(
                    "SELECT label, is_tracking_card, sort_order FROM ref_event_type WHERE code = 'next_date_differs'"
                )
            ).one()
            assert tuple(row) == ("Next date differs from the court", False, 390)
            row = conn.execute(
                sa.text(
                    "SELECT label, default_severity FROM ref_alert_kind WHERE code = 'next_date_reported'"
                )
            ).one()
            assert tuple(row) == ("Next date reported as wrong", "normal")
        # a report of a wrong date is legal-record history: the downgrade refuses while one exists
        with engine.begin() as conn:
            conn.execute(sa.text("SET session_replication_role = replica"))  # no case or office rows here
            conn.execute(
                sa.text(
                    "INSERT INTO alerts (id, case_id, kind, office_id, severity, status, title, body, data, "
                    "dedupe_key, ref_no) VALUES (gen_random_uuid(), gen_random_uuid(), 'next_date_reported', "
                    "gen_random_uuid(), 'normal', 'open', 't', 'b', '{}'::jsonb, 'next_date_reported:x', "
                    "'ASLMS/GOA/ALR/2026/000001')"
                )
            )
        with pytest.raises(RuntimeError, match="next_date_reported"):
            command.downgrade(cfg, "0033")
        with engine.begin() as conn:
            conn.execute(sa.text("SET session_replication_role = replica"))
            conn.execute(sa.text("DELETE FROM alerts WHERE kind = 'next_date_reported'"))
        command.downgrade(cfg, "0033")
        with engine.connect() as conn:
            assert _state(conn) == {"columns": set(), "enum": 0, "event": 0, "kind": 0}
    finally:
        command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == head_revision()
        assert _state(conn) == {"columns": COLUMNS, "enum": 1, "event": 1, "kind": 1}
