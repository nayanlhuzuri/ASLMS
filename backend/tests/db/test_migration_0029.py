"""Migration 0029 (design `office-head-picker`, "Data"): `users.office_id` and `users.role` nullable with CHECK
`ck_users_placed`; the downgrade restores NOT NULL and drops the CHECK on a database with no login lacking an office,
and refuses, naming the count and changing nothing, while one exists."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from alembic import command

from tests.db.conftest import alembic_config, head_revision, wipe_if_migrated

pytestmark = pytest.mark.migration_cycle

NULLABLE = sa.text(
    "SELECT column_name, is_nullable FROM information_schema.columns "
    "WHERE table_name = 'users' AND column_name IN ('office_id', 'role') ORDER BY column_name"
)
CHECK = sa.text("SELECT count(*) FROM pg_constraint WHERE conname = 'ck_users_placed'")


def test_migration_users_placed(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    command.downgrade(cfg, "0028")
    try:
        with engine.connect() as conn:
            assert conn.execute(NULLABLE).all() == [("office_id", "NO"), ("role", "NO")]
            assert conn.execute(CHECK).scalar() == 0
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            assert conn.execute(NULLABLE).all() == [("office_id", "YES"), ("role", "YES")]
            assert conn.execute(CHECK).scalar() == 1
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO users (id, email, password_hash, full_name) VALUES (:i, 'w@example.org', 'x', 'W')"
                ),
                {"i": uuid.uuid4()},
            )
        with pytest.raises(RuntimeError, match="1 login"):
            command.downgrade(cfg, "0028")
        with engine.connect() as conn:
            assert (
                conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == head_revision()
            )
            assert conn.execute(NULLABLE).all() == [("office_id", "YES"), ("role", "YES")]
    finally:
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM users WHERE email = 'w@example.org'"))
        command.upgrade(cfg, "head")
