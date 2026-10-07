"""Migration 0009 (design custody-workflow, decision 27 and "Data"): the request tables are gone at head; the
guard stops the upgrade while a request row exists (no legal record is dropped); the downgrade guard stops while
a file was sent; DELETE is granted on the two draft tables only; 0009 goes down and up again."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from alembic import command

from tests.db.conftest import alembic_config


def _scalar(conn, sql: str, **params):
    return conn.execute(sa.text(sql), params).scalar()


def test_request_tables_gone_and_draft_grants(engine: sa.Engine):
    with engine.connect() as conn:
        for t in ("requests", "request_messages", "ref_request_kind"):
            assert _scalar(conn, "select to_regclass(:t)", t=t) is None
        assert _scalar(conn, "select count(*) from pg_type where typname = 'request_status'") == 0
        for t in ("custody", "custody_history"):
            assert (
                _scalar(
                    conn,
                    "select count(*) from information_schema.columns where table_name = :t and column_name = 'request_id'",
                    t=t,
                )
                == 0
            )
        for t in ("case_note_drafts", "case_note_draft_documents"):
            assert _scalar(conn, f"select has_table_privilege('aslms_app', '{t}', 'DELETE')") is True
            assert _scalar(conn, f"select has_table_privilege('aslms_readonly', '{t}', 'SELECT')") is True
            assert _scalar(conn, f"select has_table_privilege('aslms_readonly', '{t}', 'DELETE')") is False
        for t in ("case_notes", "case_note_attachments", "custody_history"):
            assert _scalar(conn, f"select has_table_privilege('aslms_app', '{t}', 'DELETE')") is False
        values = (
            conn.execute(sa.text("select unnest(enum_range(null::pending_action))::text")).scalars().all()
        )
        assert {"parawise_comments", "other", "none", "examine"} <= set(values)
        assert (
            _scalar(conn, "select count(*) from pg_trigger where tgname = 'case_note_drafts_updated_at'") == 1
        )


def test_guard_stops_on_a_request_row_and_downgrade_guard(db_url: str, engine: sa.Engine):
    cfg = alembic_config(db_url)
    command.downgrade(cfg, "0008")
    try:
        with engine.begin() as conn:
            assert _scalar(conn, "select to_regclass('requests')") is not None
            conn.execute(sa.text("SET session_replication_role = replica"))  # no FK targets needed
            conn.execute(
                sa.text(
                    "insert into requests (id, case_id, kind, from_office_id, to_office_id, subject, ref_no) "
                    "values (:id, :c, 'report', :o, :o, 'subject', 'ASLMS/EDU/REQ/2026/000001')"
                ),
                {"id": uuid.uuid4(), "c": uuid.uuid4(), "o": uuid.uuid4()},
            )
            conn.execute(sa.text("SET session_replication_role = DEFAULT"))
        with pytest.raises(Exception, match="requests or request messages exist"):
            command.upgrade(cfg, "0009")
        with engine.begin() as conn:
            assert _scalar(conn, "select count(*) from requests") == 1  # nothing dropped
            conn.execute(sa.text("delete from requests"))
        command.upgrade(cfg, "0009")
        # a leg of a sent file blocks the downgrade
        with engine.begin() as conn:
            conn.execute(sa.text("SET session_replication_role = replica"))
            conn.execute(
                sa.text(
                    "insert into custody_history (id, case_id, seq_no, holder_office_id, holder_office_code, "
                    "reason, remark) values (:id, :c, 1, :o, 'EDU', 'sent', 'r')"
                ),
                {"id": uuid.uuid4(), "c": uuid.uuid4(), "o": uuid.uuid4()},
            )
            conn.execute(sa.text("SET session_replication_role = DEFAULT"))
        with pytest.raises(Exception, match="files were sent or recalled"):
            command.downgrade(cfg, "0008")
        with engine.begin() as conn:
            conn.execute(sa.text("SET session_replication_role = replica"))
            conn.execute(sa.text("delete from custody_history"))
            conn.execute(sa.text("SET session_replication_role = DEFAULT"))
        command.downgrade(cfg, "0008")
    finally:
        with engine.begin() as conn:
            if _scalar(conn, "select to_regclass('requests')") is not None:
                conn.execute(sa.text("delete from requests"))
        command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert _scalar(conn, "select version_num from alembic_version") == "0009"
