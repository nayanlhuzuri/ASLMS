"""Migration 0030 (design claim-assign-wording, decision 8): the upgrade relabels the `allotted` event type (label and
timeline label) and the `dept_officer` description while they hold the seeded text; it leaves an edited description
alone; the downgrade restores under the mirror condition; the seed on a fresh database gives the same texts, and a
later seed refreshes the `cases.allot` function label to "Assign Cases"."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.orm import sessionmaker

from aslms.services.seed import seed_all
from tests.db.conftest import alembic_config, wipe_if_migrated

pytestmark = pytest.mark.migration_cycle

OLD_DESC = "Works on allotted cases: moves the case, adds notes and documents, and receives alerts."
NEW_DESC = "Works on cases assigned to them: moves the case, adds notes and documents, and receives alerts."


def _seed(engine) -> None:
    with sessionmaker(bind=engine)() as s:
        seed_all(s)
        s.commit()


def _texts(engine) -> tuple[str, str, str]:
    with engine.connect() as conn:
        label, timeline = conn.execute(
            sa.text("select label, timeline_label from ref_event_type where code = 'allotted'")
        ).one()
        desc = conn.execute(sa.text("select description from ref_role where code = 'dept_officer'")).scalar()
    return label, timeline, desc


def _set(engine, label: str, timeline: str, desc: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text("update ref_event_type set label = :l, timeline_label = :t where code = 'allotted'"),
            {"l": label, "t": timeline},
        )
        conn.execute(sa.text("update ref_role set description = :d where code = 'dept_officer'"), {"d": desc})


def test_migration_assign_labels_upgrade_and_downgrade(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    _seed(engine)
    command.downgrade(cfg, "0029")
    try:
        _set(engine, "Allotted", "Allotted", OLD_DESC)  # a database seeded before this item
        command.upgrade(cfg, "0030")
        assert _texts(engine) == ("Assigned", "Assigned", NEW_DESC)
        command.downgrade(cfg, "0029")
        assert _texts(engine) == ("Allotted", "Allotted", OLD_DESC)
    finally:
        command.upgrade(cfg, "head")
        wipe_if_migrated(db_url)


def test_migration_assign_labels_leaves_an_edited_description_alone(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    _seed(engine)
    command.downgrade(cfg, "0029")
    try:
        _set(engine, "Allotted", "Allotted", "Officers of the department.")
        command.upgrade(cfg, "0030")
        assert _texts(engine) == ("Assigned", "Assigned", "Officers of the department.")
        command.downgrade(cfg, "0029")  # the mirror condition leaves it alone too
        assert _texts(engine) == ("Allotted", "Allotted", "Officers of the department.")
    finally:
        command.upgrade(cfg, "head")
        wipe_if_migrated(db_url)


def test_seed_on_a_fresh_database_gives_the_assign_texts(db_url, engine):
    wipe_if_migrated(db_url)
    _seed(engine)
    assert _texts(engine) == ("Assigned", "Assigned", NEW_DESC)
    wipe_if_migrated(db_url)


def test_seed_relabels_assign_permission(db_url, engine):
    wipe_if_migrated(db_url)
    _seed(engine)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "update ref_permission set label = 'Allot Cases', description = 'old' where code = 'cases.allot'"
            )
        )
    _seed(engine)  # `aslms seed` refreshes permission labels
    with engine.connect() as conn:
        label, desc = conn.execute(
            sa.text("select label, description from ref_permission where code = 'cases.allot'")
        ).one()
    assert label == "Assign Cases"
    assert desc == "Choose the responsible unit and the dealing officer for a case of the department."
    wipe_if_migrated(db_url)
