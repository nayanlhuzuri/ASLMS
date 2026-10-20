"""Migration 0012 (design `reports-dashboards`, "Data"): the two reporting indexes exist after the upgrade and are
gone after the downgrade; the database matches the models at head."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from aslms.db.base import Base
from tests.db.conftest import alembic_config, wipe_if_migrated

pytestmark = pytest.mark.migration_cycle

INDEXES = ("ix_cases_disposal_date", "ix_case_hearings_business_date")


def _present(engine) -> dict[str, str | None]:
    with engine.connect() as conn:
        return {
            name: conn.execute(
                sa.text("select indexdef from pg_indexes where indexname = :n"), {"n": name}
            ).scalar()
            for name in INDEXES
        }


def test_migration_0012_up_down(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    found = _present(engine)
    assert "WHERE (disposal_date IS NOT NULL)" in found["ix_cases_disposal_date"]
    assert "(business_date)" in found["ix_case_hearings_business_date"]
    command.downgrade(cfg, "0011")
    try:
        assert _present(engine) == dict.fromkeys(INDEXES)
    finally:
        command.upgrade(cfg, "head")
    assert all(_present(engine).values())
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True, "compare_server_default": True})
        diff = compare_metadata(ctx, Base.metadata)
    real = [d for d in diff if not (d[0] == "modify_type" and isinstance(d[-1], sa.Enum))]
    assert real == [], real
