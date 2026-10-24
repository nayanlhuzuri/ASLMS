"""Migration 0023 (design court-data-freshness, "Data"; the note's "0021" by build order): a database holding cause lists
and entries upgrades with every row version 1 and current; the `listing_changed` event type exists without a seed; the
downgrade refuses while a corrected version exists or a recheck is pending, and otherwise restores the six-column key."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.orm import sessionmaker

from aslms.services.seed import seed_all
from tests.db.conftest import alembic_config, head_revision, wipe, wipe_if_migrated

pytestmark = pytest.mark.migration_cycle


def _scalar(engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(sa.text(sql), params).scalar()


@pytest.fixture()
def cycle(db_url, engine) -> Iterator:
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    try:
        yield cfg
    finally:
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            wipe(conn)


def _insert_list(conn, version: int | None = None, supersedes=None) -> str:
    court = conn.execute(sa.text("select id from courts where est_code = 'GAHC01'")).scalar()
    cols = "court_id, list_date, bench_id, napix_causelist_id, list_type, source"
    vals = ":c, DATE '2026-10-20', 2048, 1007, 'lawazima', 'napix'"
    params = {"c": court}
    if version is not None:
        cols += ", version, supersedes_id"
        vals += ", :v, :s"
        params.update(v=version, s=supersedes)
    return conn.execute(
        sa.text(f"insert into causelists ({cols}) values ({vals}) returning id"), params
    ).scalar()


def test_0023_upgrade_downgrade(cycle, engine):
    with sessionmaker(bind=engine)() as s:
        seed_all(s)
        s.commit()
    command.downgrade(cycle, "0022")
    assert _scalar(engine, "select count(*) from ref_event_type where code = 'listing_changed'") == 0
    with engine.begin() as conn:
        v1 = _insert_list(conn)
        conn.execute(
            sa.text(
                "insert into causelist_entries (causelist_id, sr_no, source, case_no_text) "
                "values (:l, 1, 'pdf_parse', 'WP(C)/1/2026')"
            ),
            {"l": v1},
        )
    command.upgrade(cycle, "head")
    with engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "select version, supersedes_id, superseded_at, entries_sha256 from causelists where id = :i"
            ),
            {"i": v1},
        ).one()
    assert tuple(row) == (1, None, None, None)
    assert _scalar(engine, "select count(*) from causelist_entries where causelist_id = :i", i=v1) == 1
    label = _scalar(engine, "select timeline_label from ref_event_type where code = 'listing_changed'")
    assert label == "Cause list corrected"
    assert (
        _scalar(engine, "select is_tracking_card from ref_event_type where code = 'listing_changed'") is True
    )
    assert _scalar(engine, "select 'causelist_recheck' = any(enum_range(null::fetch_kind)::text[])") is True

    # the checks hold: version 1 has no predecessor, a later version has one, never itself
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
        _insert_list(conn, version=2, supersedes=None)
    with engine.begin() as conn:
        conn.execute(sa.text("update causelists set superseded_at = now() where id = :i"), {"i": v1})
        v2 = _insert_list(conn, version=2, supersedes=v1)
    with pytest.raises(RuntimeError, match="corrected version"):
        command.downgrade(cycle, "0022")
    assert _scalar(engine, "select version_num from alembic_version") == head_revision()

    with (
        engine.begin() as conn
    ):  # test data only: clear the corrected version, then a pending recheck refuses
        conn.execute(sa.text("delete from causelists where id = :i"), {"i": v2})
        conn.execute(sa.text("update causelists set superseded_at = null where id = :i"), {"i": v1})
        conn.execute(
            sa.text(
                "insert into fetch_queue (kind, ref, priority, lane) "
                "values ('causelist_recheck', '2026-10-20', 21, 'daily')"
            )
        )
    with pytest.raises(RuntimeError, match="causelist_recheck"):
        command.downgrade(cycle, "0022")
    with engine.begin() as conn:
        conn.execute(sa.text("update fetch_queue set status = 'done' where kind = 'causelist_recheck'"))
    command.downgrade(cycle, "0022")
    assert _scalar(engine, "select count(*) from ref_event_type where code = 'listing_changed'") == 0
    assert (
        _scalar(
            engine,
            "select count(*) from information_schema.columns where table_name = 'causelists' and column_name = 'version'",
        )
        == 0
    )
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:  # the six-column key is back
        _insert_list(conn)
