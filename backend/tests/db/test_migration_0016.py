"""Migration 0016 (design `case-stages-extension`, "Data"): the seven stage rows on an empty table; the seed and the
migration give identical rows whichever runs first; the migration after a seed is a no-op (labels kept); the
downgrade refuses while a `case_stages` row uses a new code and otherwise deletes the seven, and the re-upgrade
restores them active; the database matches the models at head."""

from __future__ import annotations

import importlib.util
import uuid
from contextlib import ExitStack
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.orm import sessionmaker

from aslms.db.base import Base
from aslms.services import seed as seed_module
from aslms.services.seed import seed_all
from tests.db.conftest import BACKEND, alembic_config, head_revision, wipe_if_migrated

pytestmark = pytest.mark.migration_cycle

EXPECTED = [
    ("review_petition_filed", "Review petition filed", "appeal", 180, True),
    ("appeal_dismissed", "Appeal or review dismissed", "appeal", 190, True),
    ("appeal_allowed", "Appeal or review allowed", "appeal", 200, True),
    ("further_appeal_filed", "Further appeal filed (higher court)", "appeal", 210, True),
    ("complied_after_dismissal", "Complied after dismissal of appeal or review", "appeal", 220, True),
    ("vakalatnama_submitted", "Vakalatnama submitted", "contempt", 230, True),
    ("contempt_disposed", "Contempt disposed", "contempt", 240, True),
]
NEW = [code for code, *_ in EXPECTED]


def _migration():
    path = BACKEND / "migrations" / "versions" / "0016_case_stages.py"
    spec = importlib.util.spec_from_file_location("m0016_db", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows(engine, *, only_new: bool = False) -> list[tuple]:
    sql = "select code, label, phase, sort_order, is_active from ref_case_stage"
    if only_new:
        sql += " where code = any(:c)"
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(sa.text(sql + " order by sort_order, code"), {"c": NEW}).all()]


def _seed(engine) -> None:
    """Today's seed. On a database below 0027 (no `weight_counsel_code_partial`, design partial-code-match) its
    scoring-settings step is left out, and below 0028 (no `courts.ref_code`, design case-ref-court-prefix) its courts
    step: neither is what these tests are about."""
    with engine.connect() as conn:
        has_partial, has_ref_code = conn.execute(
            sa.text(
                "select exists (select 1 from information_schema.columns where table_name = 'scoring_settings' "
                "and column_name = 'weight_counsel_code_partial'), "
                "exists (select 1 from information_schema.columns where table_name = 'courts' "
                "and column_name = 'ref_code')"
            )
        ).one()
    with ExitStack() as stack:
        if not has_partial:
            stack.enter_context(
                patch.object(seed_module.scoring_settings, "seed_default", lambda s, report: None)
            )
        if not has_ref_code:
            stack.enter_context(patch.object(seed_module, "seed_courts", lambda s, report: None))
        with sessionmaker(bind=engine)() as s:
            seed_all(s)
            s.commit()


def _version(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(sa.text("select version_num from alembic_version")).scalar()


def test_0016_inserts_the_seven_rows_on_an_empty_table(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    command.downgrade(cfg, "0015")
    try:
        assert _rows(engine) == []
        command.upgrade(cfg, "0016")
        assert _rows(engine) == EXPECTED
        with engine.connect() as conn:
            assert (
                conn.execute(
                    sa.text("select count(*) from ref_case_stage where description is not null")
                ).scalar()
                == 0
            )
    finally:
        command.upgrade(cfg, "head")
        wipe_if_migrated(db_url)


def test_seed_and_migration_produce_the_same_rows(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    command.downgrade(cfg, "0015")
    try:
        command.upgrade(cfg, "head")  # the migration first, on an empty table
        _seed(engine)  # then the seed: the 17 others, the seven untouched
        after_migration = _rows(engine)
        assert len(after_migration) == 24
        assert _rows(engine, only_new=True) == EXPECTED
        assert all(active for *_, active in after_migration)
    finally:
        wipe_if_migrated(db_url)
    _seed(engine)  # a wiped database seeded without the migration
    assert _rows(engine) == after_migration
    assert [(*row, True) for row in _migration().NEW_STAGES] == _rows(engine, only_new=True)
    wipe_if_migrated(db_url)


def test_0016_after_seed_is_a_no_op(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    command.downgrade(cfg, "0015")
    try:
        _seed(engine)  # the seed with the new `Stage` members: 24 rows
        assert len(_rows(engine)) == 24
        with engine.begin() as conn:  # an administrator's label edit survives the migration
            conn.execute(
                sa.text(
                    "update ref_case_stage set label = 'Contempt case disposed' where code = 'contempt_disposed'"
                )
            )
        command.upgrade(cfg, "0016")
        rows = _rows(engine)
        assert len(rows) == 24
        assert ("contempt_disposed", "Contempt case disposed", "contempt", 240, True) in rows
    finally:
        command.upgrade(cfg, "head")
        wipe_if_migrated(db_url)


def test_0016_downgrade_refuses_while_a_case_stage_uses_a_new_code(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    _seed(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("SET session_replication_role = replica"))  # no case or office row needed
        conn.execute(
            sa.text(
                "insert into case_stages (id, case_id, office_id, stage) values (:i, :c, :o, 'vakalatnama_submitted')"
            ),
            {"i": uuid.uuid4(), "c": uuid.uuid4(), "o": uuid.uuid4()},
        )
        conn.execute(sa.text("SET session_replication_role = DEFAULT"))
    try:
        with pytest.raises(RuntimeError, match="cannot downgrade 0016: 1 case_stages row"):
            command.downgrade(cfg, "0015")
        assert _version(engine) == head_revision()
        assert len(_rows(engine)) == 24
    finally:
        with engine.begin() as conn:  # append-only: the trigger is bypassed for the clean-up only
            conn.execute(sa.text("SET session_replication_role = replica"))
            conn.execute(sa.text("delete from case_stages"))
            conn.execute(sa.text("SET session_replication_role = DEFAULT"))
    command.downgrade(cfg, "0015")
    try:
        rows = _rows(engine)
        assert len(rows) == 17 and not ({r[0] for r in rows} & set(NEW))
    finally:
        command.upgrade(cfg, "head")
    assert _rows(engine, only_new=True) == EXPECTED
    assert len(_rows(engine)) == 24
    wipe_if_migrated(db_url)


def test_models_match_head(db_url, engine):
    wipe_if_migrated(db_url)
    assert _version(engine) == head_revision()  # 0016 or a later head
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True, "compare_server_default": True})
        diff = compare_metadata(ctx, Base.metadata)
    real = [d for d in diff if not (d[0] == "modify_type" and isinstance(d[-1], sa.Enum))]
    assert real == [], real
