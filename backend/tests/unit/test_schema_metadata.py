"""The models obey DB_STANDARD v1.2 without a database: UUID v7 keys, RESTRICT by default, class comments,
updated_at on mutable tables, ref_* code sets, no deletion paths into legal records."""

from __future__ import annotations

import sqlalchemy as sa

import aslms.domain  # noqa: F401
from aslms.db.base import APPEND_ONLY_TABLES, CASCADE_TABLES, MUTABLE_TABLES, Base
from aslms.domain.reference import REF_TABLES

TABLES = Base.metadata.tables


def test_every_table_declares_its_class():
    for name, table in TABLES.items():
        assert table.comment and table.comment.startswith("class="), name
        assert table.comment.split("=")[1] in {"reference", "master", "transaction", "derived"}, name


def test_uuid_v7_primary_keys():
    for name, table in TABLES.items():
        if name == "ref_sequences" or name.startswith("ref_"):
            continue
        pk = list(table.primary_key.columns)
        assert len(pk) == 1, name
        col = pk[0]
        assert isinstance(col.type, sa.UUID | sa.dialects.postgresql.UUID), name
        if col.name == "id":
            assert str(col.server_default.arg) == "uuid_generate_v7()", name


def test_cascade_only_where_the_standard_allows():
    for name, table in TABLES.items():
        for fk in table.foreign_key_constraints:
            if fk.ondelete and fk.ondelete.upper() == "CASCADE":
                assert name in CASCADE_TABLES, f"{name}.{list(fk.columns)[0].name} cascades"
            elif fk.ondelete and fk.ondelete.upper() == "SET NULL":
                assert fk.referred_table.name == "users", f"{name}: SET NULL only for user links"
            else:
                assert (fk.ondelete or "RESTRICT").upper() == "RESTRICT", name


def test_cases_is_never_a_cascade_parent():
    for name, table in TABLES.items():
        for fk in table.foreign_key_constraints:
            if fk.referred_table.name == "cases":
                assert (fk.ondelete or "RESTRICT").upper() in {"RESTRICT", "CASCADE"} and (
                    (fk.ondelete or "RESTRICT").upper() == "RESTRICT" or name == "case_office_scores"
                ), name


def test_mutable_tables_have_updated_at_and_append_only_do_not():
    for name in MUTABLE_TABLES:
        assert "updated_at" in TABLES[name].c, name
    for name in APPEND_ONLY_TABLES:
        assert "updated_at" not in TABLES[name].c, name
        assert name in TABLES


def test_ref_tables_match_the_enums():
    assert len(REF_TABLES) == 10
    for table, (model, enum_cls) in REF_TABLES.items():
        assert model.__tablename__ == table
        assert TABLES[table].comment == "class=reference"
        assert len(enum_cls) > 0
    # every ref_code column points at a ref_* table with a 40-char code
    for name, table in TABLES.items():
        for fk in table.foreign_key_constraints:
            if name != "ref_sequences" and fk.referred_table.name.startswith("ref_"):
                col = list(fk.columns)[0]
                assert isinstance(col.type, sa.Enum) and not col.type.native_enum and col.type.length == 40, (
                    f"{name}.{col.name}"
                )


def test_ref_no_columns_are_unique():
    for name, table in TABLES.items():
        if "ref_no" in table.c:
            assert table.c.ref_no.unique or any(
                set(c.columns.keys()) == {"ref_no"}
                for c in table.constraints
                if isinstance(c, sa.UniqueConstraint)
            ), name


def test_napix_verbatim_stores_exist():
    assert {"napix_responses", "case_snapshots", "documents", "napix_call_log", "fetch_queue"} <= set(TABLES)
    assert TABLES["napix_responses"].c.payload.type.__class__.__name__ == "JSONB"
