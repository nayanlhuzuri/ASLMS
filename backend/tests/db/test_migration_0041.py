"""Migration 0041 (design cause-title-signal-review-advisories, decisions 6 and 8): the two columns of
`insight_case_facts`, the CHECK `ck_insight_case_facts_phrase_pos` and the partial index on the rescore mark; the
downgrade drops them all. The CHECK refuses a length mismatch, a NULL element, a position past the departments and a
negative one, and accepts empty positions on a row not derived since the migration."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.exc import IntegrityError

from tests.db import insights_support as ins
from tests.db.conftest import alembic_config, wipe, wipe_if_migrated

TABLE = "insight_case_facts"
CHECK = "ck_insight_case_facts_phrase_pos"
INDEX = "ix_insight_case_facts_named_changed_at"


def _shape(engine) -> dict:
    insp = sa.inspect(engine)
    return {
        "columns": {c["name"]: c for c in insp.get_columns(TABLE)},
        "checks": {c["name"] for c in insp.get_check_constraints(TABLE)},
        "indexes": {i["name"]: i for i in insp.get_indexes(TABLE)},
    }


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


@pytest.mark.migration_cycle
def test_upgrade_and_downgrade(cycle, engine):
    shape = _shape(engine)
    pos = shape["columns"]["title_phrase_department_pos"]
    assert not pos["nullable"] and "'{}'" in str(pos["default"])
    assert isinstance(pos["type"], sa.ARRAY) and isinstance(pos["type"].item_type, sa.SmallInteger)
    assert shape["columns"]["named_changed_at"]["nullable"]
    assert CHECK in shape["checks"]
    assert shape["indexes"][INDEX]["column_names"] == ["named_changed_at"]
    assert "named_changed_at IS NOT NULL" in str(shape["indexes"][INDEX].get("dialect_options", {}))
    command.downgrade(cycle, "0040")
    down = _shape(engine)
    assert "title_phrase_department_pos" not in down["columns"] and "named_changed_at" not in down["columns"]
    assert CHECK not in down["checks"] and INDEX not in down["indexes"]
    command.upgrade(cycle, "0041")
    assert CHECK in _shape(engine)["checks"]


def _fact(s, c, **values) -> None:
    """One fact row written as raw SQL (the CHECK is the database's, not the service's)."""
    base = {
        "phrases": ["EDUCATION", "HEALTH"],
        "ids": [],
        "pos": [],
    }
    base.update(values)
    with s.begin_nested():
        s.execute(
            sa.text(
                "INSERT INTO insight_case_facts (case_id, title_phrases, named_title_department_ids, "
                "title_phrase_department_pos, reader_version, built_at) "
                "VALUES (:cid, CAST(:phrases AS varchar[]), CAST(:ids AS uuid[]), CAST(:pos AS smallint[]), '2', now())"
            ),
            {"cid": c.id, **base},
        )


@pytest.mark.parametrize(
    "pos",
    [
        [1],  # one element for two phrases
        [1, None],  # a NULL element
        [1, 3],  # past the two departments named
        [1, -1],  # negative
    ],
)
def test_check_refuses_bad_positions(world, pos):
    with world.Session() as s:
        edu, health = world.office(s, "EDU"), world.office(s, "HEALTH")
        c = ins.case(s)
        with pytest.raises(IntegrityError, match=CHECK):
            _fact(s, c, ids=[str(edu.id), str(health.id)], pos=pos)
        s.rollback()


def test_check_accepts_good_and_empty_positions(world):
    with world.Session() as s:
        edu, health = world.office(s, "EDU"), world.office(s, "HEALTH")
        old, good, none = ins.case(s), ins.case(s), ins.case(s)
        _fact(s, old, ids=[str(edu.id)], pos=[])  # a row not derived since 0041
        _fact(s, good, ids=[str(edu.id), str(health.id)], pos=[1, 2])
        _fact(s, none, ids=[], pos=[0, 0])
        assert s.scalar(sa.text("SELECT count(*) FROM insight_case_facts")) == 3
        s.rollback()
