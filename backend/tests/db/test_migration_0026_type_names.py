"""Migration 0026 (design portal-ui-polish-2, decision 11): the upgrade relabels only rows still holding the seeded
text, sets descriptions only where NULL and adds `uq_ref_role_label_lower`; the downgrade reverses under the mirror
conditions; the database matches the models at head."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.orm import sessionmaker

from aslms.services.seed import seed_all
from tests.db.conftest import alembic_config, wipe_if_migrated

pytestmark = pytest.mark.migration_cycle

OLD = {
    "super_admin": "Super admin",
    "state_oversight": "State oversight",
    "dept_head": "Dept head",
    "dept_admin": "Dept admin",
    "dept_officer": "Dept officer",
    "directorate_user": "Directorate user",
    "referral_reviewer": "Referral reviewer",
    "standing_counsel": "Standing counsel",
    "central_operator": "Central operator",
    "auditor": "Auditor",
}


def _seed(engine) -> None:
    with sessionmaker(bind=engine)() as s:
        seed_all(s)
        s.commit()


def _rows(engine) -> dict[str, tuple[str, str | None]]:
    with engine.connect() as conn:
        return {
            code: (label, description)
            for code, label, description in conn.execute(
                sa.text("select code, label, description from ref_role")
            )
        }


def _as_before_0026(engine, **overrides: str) -> None:
    """The ten rows as a database seeded before this item holds them: the old labels, no descriptions."""
    with engine.begin() as conn:
        for code, label in {**OLD, **overrides}.items():
            conn.execute(
                sa.text("update ref_role set label = :l, description = null where code = :c"),
                {"l": label, "c": code},
            )


def _index_exists(engine) -> bool:
    with engine.connect() as conn:
        return conn.execute(sa.text("select to_regclass('uq_ref_role_label_lower')")).scalar() is not None


def test_upgrade_relabels_seeded_rows_and_downgrade_restores(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    _seed(engine)
    command.downgrade(cfg, "0025")
    try:
        assert not _index_exists(engine)
        _as_before_0026(engine, dept_head="Head of the Department (custom)")
        with engine.begin() as conn:  # an administrator's description is kept
            conn.execute(sa.text("update ref_role set description = 'Own words.' where code = 'auditor'"))
        command.upgrade(cfg, "0026")
        rows = _rows(engine)
        assert rows["super_admin"][0] == "Super Administrator"
        assert rows["dept_officer"][0] == "Department Officer"
        assert rows["auditor"] == ("Auditor", "Own words.")
        assert rows["dept_head"][0] == "Head of the Department (custom)"  # customised: left alone
        assert rows["dept_officer"][1].startswith("Works on allotted cases")
        assert _index_exists(engine)

        command.downgrade(cfg, "0025")
        rows = _rows(engine)
        assert not _index_exists(engine)
        assert rows["super_admin"] == ("Super admin", None)
        assert rows["dept_officer"] == ("Dept officer", None)
        assert rows["dept_head"] == ("Head of the Department (custom)", None)
        assert rows["auditor"] == ("Auditor", "Own words.")
    finally:
        command.upgrade(cfg, "head")
        wipe_if_migrated(db_url)


def test_index_refuses_a_name_differing_only_in_case(db_url, engine):
    wipe_if_migrated(db_url)
    _seed(engine)
    try:
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
            conn.execute(sa.text("update ref_role set label = 'department officer' where code = 'auditor'"))
    finally:
        wipe_if_migrated(db_url)
