"""Migration 0025 (design case-workspace-admin, "Data"): the upgrade relabels `file_noting` ("Office note") and
`custody_moved` ("Case moved") while they hold the seeded text; it leaves an administrator-changed label alone; the
downgrade restores; the seed on a fresh database gives the same labels; the database matches the models at head."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.orm import sessionmaker

from aslms.services.seed import seed_all
from tests.db.conftest import alembic_config, wipe_if_migrated

pytestmark = pytest.mark.migration_cycle


def _labels(engine) -> tuple[str, str]:
    with engine.connect() as conn:
        note = conn.execute(sa.text("select label from ref_note_kind where code = 'file_noting'")).scalar()
        event = conn.execute(
            sa.text("select timeline_label from ref_event_type where code = 'custody_moved'")
        ).scalar()
    return note, event


def _seed(engine) -> None:
    with sessionmaker(bind=engine)() as s:
        seed_all(s)
        s.commit()


def _set(engine, note: str, event: str) -> None:
    with engine.begin() as conn:
        conn.execute(sa.text("update ref_note_kind set label = :l where code = 'file_noting'"), {"l": note})
        conn.execute(
            sa.text("update ref_event_type set timeline_label = :l where code = 'custody_moved'"),
            {"l": event},
        )


def test_upgrade_relabels_the_seeded_text_and_downgrade_restores(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    _seed(engine)
    command.downgrade(cfg, "0024")
    try:
        _set(engine, "File noting", "Custody moved")  # a database seeded before this item
        command.upgrade(cfg, "0025")
        assert _labels(engine) == ("Office note", "Case moved")
        command.downgrade(cfg, "0024")
        assert _labels(engine) == ("File noting", "Custody moved")
    finally:
        command.upgrade(cfg, "head")
        wipe_if_migrated(db_url)


def test_upgrade_leaves_an_administrator_label_alone(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    _seed(engine)
    command.downgrade(cfg, "0024")
    try:
        _set(engine, "Noting sheet", "Custody moved")
        command.upgrade(cfg, "0025")
        assert _labels(engine) == ("Noting sheet", "Case moved")
        command.downgrade(cfg, "0024")  # the mirror condition leaves it alone too
        assert _labels(engine) == ("Noting sheet", "Custody moved")
    finally:
        command.upgrade(cfg, "head")
        wipe_if_migrated(db_url)


def test_seed_on_a_fresh_database_gives_the_same_labels(db_url, engine):
    wipe_if_migrated(db_url)
    _seed(engine)
    assert _labels(engine) == ("Office note", "Case moved")
    _set(engine, "File noting", "Custody moved")
    _seed(engine)  # a later seed relabels the note kind still holding its generated label
    assert _labels(engine)[0] == "Office note"
    wipe_if_migrated(db_url)
