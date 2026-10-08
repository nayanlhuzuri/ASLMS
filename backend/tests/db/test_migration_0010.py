"""Migration 0010 (design `otp-and-profile`, "Data"): up, down with an empty `user_devices`, up again; the
grants and the `updated_at` trigger of `user_devices`; the down refuses while a device row exists; the back-fill
`must_change_password = must_confirm_profile`."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from alembic import command

from tests.db.conftest import TEST_URL, alembic_config, head_revision, wipe_if_migrated


def test_migration_0010_cycles_and_refuses_with_a_device(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    command.downgrade(cfg, "0009")
    with engine.connect() as conn:
        assert conn.execute(sa.text("select to_regclass('user_devices')")).scalar() is None
        cols = conn.execute(
            sa.text("select column_name from information_schema.columns where table_name = 'users'")
        ).scalars()
        assert "must_change_password" not in set(cols)
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert (
            conn.execute(sa.text("select has_table_privilege('aslms_app','user_devices','DELETE')")).scalar()
            is False
        )
        assert (
            conn.execute(sa.text("select has_table_privilege('aslms_app','user_devices','UPDATE')")).scalar()
            is True
        )
        assert (
            conn.execute(
                sa.text("select count(*) from pg_trigger where tgname = 'user_devices_updated_at'")
            ).scalar()
            == 1
        )
    with engine.begin() as conn:
        conn.execute(sa.text("SET session_replication_role = replica"))  # no user row needed
        conn.execute(
            sa.text("insert into user_devices (id, user_id, token_hash) values (:i, :u, :h)"),
            {"i": uuid.uuid4(), "u": uuid.uuid4(), "h": "b" * 64},
        )
        conn.execute(sa.text("SET session_replication_role = DEFAULT"))
    try:
        with pytest.raises(RuntimeError, match="cannot downgrade 0010"):
            command.downgrade(cfg, "0009")
        with engine.connect() as conn:
            assert (
                conn.execute(sa.text("select version_num from alembic_version")).scalar() == head_revision()
            )
            assert conn.execute(sa.text("select count(*) from user_devices")).scalar() == 1
    finally:
        with engine.begin() as conn:
            conn.execute(sa.text("delete from user_devices"))
        command.upgrade(cfg, "head")


def test_backfill_must_change_from_must_confirm(db_url, engine):
    """0010 sets `must_change_password` for every login that had not confirmed its profile."""
    cfg = alembic_config(TEST_URL)
    wipe_if_migrated(db_url)
    command.downgrade(cfg, "0009")
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("SET session_replication_role = replica"))
            for email, confirm in (("a@example.org", True), ("b@example.org", False)):
                conn.execute(
                    sa.text(
                        "insert into users (id, email, password_hash, full_name, office_id, role, "
                        "must_confirm_profile) values (:i, :e, 'x', 'X', :o, 'dept_officer', :c)"
                    ),
                    {"i": uuid.uuid4(), "e": email, "o": uuid.uuid4(), "c": confirm},
                )
            conn.execute(sa.text("SET session_replication_role = DEFAULT"))
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            rows = dict(conn.execute(sa.text("select email, must_change_password from users")).all())
        assert rows == {"a@example.org": True, "b@example.org": False}
    finally:
        wipe_if_migrated(db_url)
        command.upgrade(cfg, "head")
