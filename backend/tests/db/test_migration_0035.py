"""Migration 0035 (design `close-case`, "Data"): the table `case_closures` with its CHECKs, indexes, triggers, grants and
class comment, the custody reason CHECK with `closed` and `reopened`, the four reference rows and the retired stage;
up, down, up; the downgrade refuses while a closure exists and restores the stage and the seven-reason CHECK."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command

from tests.db.conftest import alembic_config, head_revision, wipe_if_migrated

pytestmark = pytest.mark.migration_cycle


def _state(conn) -> dict:
    q = lambda sql: conn.execute(sa.text(sql)).scalar()  # noqa: E731
    return {
        "table": q("SELECT to_regclass('public.case_closures') IS NOT NULL"),
        "events": q("SELECT count(*) FROM ref_event_type WHERE code IN ('case_closed', 'case_reopened')"),
        "kinds": q("SELECT count(*) FROM ref_note_kind WHERE code IN ('closing', 'reopening')"),
        "stage_active": q("SELECT is_active FROM ref_case_stage WHERE code = 'closed'"),
        "function": q("SELECT count(*) FROM pg_proc WHERE proname = 'aslms_case_closure_reopen_once'"),
        "reason_check": q(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_custody_history_reason'"
        ),
    }


def _seed_stage(conn) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO ref_case_stage (code, label, phase, sort_order, is_active) "
            "VALUES ('closed', 'Closed', 'main', 170, true) ON CONFLICT (code) DO NOTHING"
        )
    )


def test_migration_0035_cycles(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    try:
        command.downgrade(cfg, "0034")
        with engine.begin() as conn:
            _seed_stage(conn)
        with engine.connect() as conn:
            before = _state(conn)
            assert before["table"] is False and before["events"] == 0 and before["kinds"] == 0
            assert before["stage_active"] is True and before["function"] == 0
            assert "'closed'" not in before["reason_check"]
        command.upgrade(cfg, "0035")
        with engine.connect() as conn:
            after = _state(conn)
            assert after["table"] is True and after["events"] == 2 and after["kinds"] == 2
            assert after["stage_active"] is False and after["function"] == 1
            assert "'closed'" in after["reason_check"] and "'reopened'" in after["reason_check"]
            names = set(
                conn.execute(
                    sa.text("SELECT conname FROM pg_constraint WHERE conrelid = 'case_closures'::regclass")
                ).scalars()
            )
            assert {
                "ck_case_closures_closed_as",
                "ck_case_closures_reopen_kind",
                "ck_case_closures_reopened",
                "ck_case_closures_reopen_manual",
                "uq_case_closures_note_id",
                "uq_case_closures_close_leg_id",
                "fk_case_closures_case_id_cases",
                "fk_case_closures_reopened_by_user_id_users",
            } <= names
            indexes = set(
                conn.execute(
                    sa.text("SELECT indexname FROM pg_indexes WHERE tablename = 'case_closures'")
                ).scalars()
            )
            assert {"ix_case_closures_open", "ix_case_closures_case_closed"} <= indexes
            triggers = set(
                conn.execute(
                    sa.text(
                        "SELECT tgname FROM pg_trigger WHERE tgrelid = 'case_closures'::regclass AND NOT tgisinternal"
                    )
                ).scalars()
            )
            assert triggers == {"case_closures_reopen_once", "case_closures_updated_at"}
            assert conn.execute(sa.text("SELECT obj_description('case_closures'::regclass)")).scalar() == (
                "class=transaction"
            )
            privilege = lambda role, p: conn.execute(  # noqa: E731
                sa.text("SELECT has_table_privilege(:r, 'case_closures', :p)"), {"r": role, "p": p}
            ).scalar()
            assert privilege("aslms_app", "INSERT") and privilege("aslms_app", "UPDATE")
            assert not privilege("aslms_app", "DELETE")
            assert privilege("aslms_readonly", "SELECT") and not privilege("aslms_readonly", "INSERT")
            row = conn.execute(
                sa.text(
                    "SELECT label, is_tracking_card, sort_order FROM ref_event_type WHERE code = 'case_closed'"
                )
            ).one()
            assert tuple(row) == ("Case closed", True, 400)
            row = conn.execute(
                sa.text("SELECT label, sort_order FROM ref_note_kind WHERE code = 'reopening'")
            ).one()
            assert tuple(row) == ("Reopening remark", 120)
        # a closure is a legal record: the downgrade refuses while one exists
        with engine.begin() as conn:
            conn.execute(sa.text("SET session_replication_role = replica"))  # no case or office rows here
            conn.execute(
                sa.text(
                    "INSERT INTO case_closures (case_id, office_id, ownership_id, closed_as, note_id, close_leg_id) "
                    "VALUES (gen_random_uuid(), gen_random_uuid(), gen_random_uuid(), 'head', gen_random_uuid(), "
                    "gen_random_uuid())"
                )
            )
        with pytest.raises(RuntimeError, match="case_closures"):
            command.downgrade(cfg, "0034")
        with engine.begin() as conn:
            conn.execute(sa.text("SET session_replication_role = replica"))
            conn.execute(sa.text("DELETE FROM case_closures"))
        command.downgrade(cfg, "0034")
        with engine.connect() as conn:
            down = _state(conn)
            assert down["table"] is False and down["events"] == 0 and down["kinds"] == 0
            assert down["stage_active"] is True and down["function"] == 0
            assert "'closed'" not in down["reason_check"] and "'reassigned_on_exit'" in down["reason_check"]
    finally:
        command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == head_revision()
        assert _state(conn)["table"] is True
