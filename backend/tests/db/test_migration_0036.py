"""Migration 0036 (design `offices-import`, "Data"): the upgrade inserts the six office kinds and relabels an unedited
`directorate`; an administrator's label is kept; the downgrade refuses while an office uses a new kind and otherwise
removes the six and restores the label; up, down, up on an empty table; the seed and the migration agree on labels,
descriptions and sort orders whichever runs first."""

from __future__ import annotations

import importlib.util

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.orm import sessionmaker

from aslms.domain.reference import OfficeKind
from aslms.services.seed import OFFICE_KIND_COLUMNS, seed_all
from tests.db.conftest import BACKEND, alembic_config, head_revision, wipe_if_migrated

pytestmark = pytest.mark.migration_cycle

NEW = [
    "board_corporation",
    "statutory_authority",
    "society_mission",
    "institution",
    "local_body",
    "autonomous_council",
]


def _migration():
    path = BACKEND / "migrations" / "versions" / "0036_office_kinds.py"
    spec = importlib.util.spec_from_file_location("m0036_db", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows(engine) -> dict[str, tuple]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("select code, label, description, sort_order, is_active from ref_office_kind")
        ).all()
    return {r[0]: tuple(r[1:]) for r in rows}


def _seed(engine) -> None:
    with sessionmaker(bind=engine)() as s:
        seed_all(s)
        s.commit()


def _version(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(sa.text("select version_num from alembic_version")).scalar()


def test_upgrade_inserts_six_kinds_and_relabels_unedited_directorate(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    _seed(engine)
    command.downgrade(cfg, "0035")
    try:
        rows = _rows(engine)
        assert not set(NEW) & set(rows)
        assert rows["directorate"][:2] == ("Directorate", None)
        command.upgrade(cfg, "0036")
        rows = _rows(engine)
        m = _migration()
        for code, label, description, sort_order in m.NEW_KINDS:
            assert rows[code] == (label, description, sort_order, True)
        assert [rows[c][2] for c in NEW] == [41, 42, 43, 44, 45, 46]
        assert rows["directorate"][0] == "Directorate / Commissionerate"
        assert rows["directorate"][1].startswith("Heads of department under a department")
    finally:
        command.upgrade(cfg, "head")
        wipe_if_migrated(db_url)


def test_edited_directorate_label_is_kept(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    _seed(engine)
    command.downgrade(cfg, "0035")
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text("update ref_office_kind set label = 'Directorate (HoD)' where code = 'directorate'")
            )
        command.upgrade(cfg, "0036")
        assert _rows(engine)["directorate"][:2] == ("Directorate (HoD)", None)
        command.downgrade(cfg, "0035")
        assert _rows(engine)["directorate"][:2] == ("Directorate (HoD)", None)
    finally:
        command.upgrade(cfg, "head")
        wipe_if_migrated(db_url)


def test_downgrade_refuses_while_an_office_uses_a_new_kind(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    _seed(engine)
    with engine.begin() as conn:
        goa = conn.execute(sa.text("select id from offices where code = 'GOA'")).scalar()
        conn.execute(
            sa.text(
                "insert into offices (id, code, name, kind, parent_id, path) values "
                "(gen_random_uuid(), 'EDU', 'Education', 'department', :goa, 'GOA/EDU')"
            ),
            {"goa": goa},
        )
        edu = conn.execute(sa.text("select id from offices where code = 'EDU'")).scalar()
        conn.execute(
            sa.text(
                "insert into offices (id, code, name, kind, parent_id, path) values "
                "(gen_random_uuid(), 'EDU-BRD', 'Board', 'board_corporation', :edu, 'GOA/EDU/EDU-BRD')"
            ),
            {"edu": edu},
        )
    try:
        with pytest.raises(RuntimeError, match="cannot downgrade 0036"):
            command.downgrade(cfg, "0035")
        assert _version(engine) == head_revision()
        assert "board_corporation" in _rows(engine)
    finally:
        command.upgrade(cfg, "head")
        wipe_if_migrated(db_url)


def test_up_down_up_on_an_empty_table(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    command.downgrade(cfg, "0035")
    try:
        assert _rows(engine) == {}
        command.upgrade(cfg, "0036")
        assert sorted(_rows(engine)) == sorted(NEW)  # `directorate` is not there to relabel
        command.downgrade(cfg, "0035")
        assert _rows(engine) == {}
        command.upgrade(cfg, "0036")
        assert sorted(_rows(engine)) == sorted(NEW)
    finally:
        command.upgrade(cfg, "head")
        wipe_if_migrated(db_url)


def test_seed_and_migration_agree(db_url, engine):
    """The migration first (fresh database), then the seed; and the seed alone on a wiped database: the same rows."""
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    command.downgrade(cfg, "0035")
    try:
        command.upgrade(cfg, "head")
        _seed(engine)
        after_migration = _rows(engine)
    finally:
        wipe_if_migrated(db_url)
    _seed(engine)
    seeded = _rows(engine)
    assert seeded == after_migration
    for kind, (label, description, sort_order) in OFFICE_KIND_COLUMNS.items():
        assert seeded[kind.value] == (label, description, sort_order, True)
    assert seeded["state"][0] == "State" and len(seeded) == len(OfficeKind) == 12
    m = _migration()
    for code, label, description, sort_order in m.NEW_KINDS:
        assert seeded[code] == (label, description, sort_order, True)
    assert seeded["directorate"][:2] == (m.DIRECTORATE_NEW, m.DIRECTORATE_DESCRIPTION)
    # a database seeded before this item: the seed relabels `directorate` while it still reads "Directorate"
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "update ref_office_kind set label = 'Directorate', description = null where code = 'directorate'"
            )
        )
    _seed(engine)
    assert _rows(engine)["directorate"][:2] == (m.DIRECTORATE_NEW, m.DIRECTORATE_DESCRIPTION)
    wipe_if_migrated(db_url)
