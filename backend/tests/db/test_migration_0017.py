"""Migration 0017 (design `department-discovery`, "Data"): the upgrade ticks `discover` on existing rules whose text is
discoverable (never a regex), adds the CHECK, the two tables and the enum values with `discovery` between `daily` and
`load` (so a dossier asked by discovery and then the daily cycle ends `daily`, and one asked by the load and then
discovery ends `discovery`); the downgrade refuses while a `party_search` row is pending and otherwise drops the
tables and columns; the database matches the models at head."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.orm import sessionmaker

from aslms.db.base import Base
from aslms.domain.ops import FetchKind, FetchLane
from aslms.services import queue
from aslms.services.seed import seed_all
from tests.db.conftest import alembic_config, head_revision, wipe, wipe_if_migrated

pytestmark = pytest.mark.migration_cycle


def _tables(engine) -> set[str]:
    return set(sa.inspect(engine).get_table_names())


def _cols(engine, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(engine).get_columns(table)}


def test_0017_upgrade_and_downgrade(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    with sessionmaker(bind=engine)() as s:
        seed_all(s)
        s.commit()
    command.downgrade(cfg, "0016")
    try:
        assert "discover" not in _cols(engine, "office_keywords")
        assert not {"discovery_terms", "discovery_hits"} & _tables(engine)
        with engine.begin() as conn:
            goa = conn.execute(sa.text("select id from offices where code = 'GOA'")).scalar()
            for kw in ("PRITAM SAIKIA", "100% PASS", "AB"):
                conn.execute(
                    sa.text("insert into office_keywords (office_id, keyword) values (:o, :k)"),
                    {"o": goa, "k": kw},
                )
            for pattern, kind in (("PRITAM SAIKIA", "prefix"), ("DR R DAS", "exact"), ("^PRITAM", "regex")):
                conn.execute(
                    sa.text(
                        "insert into office_name_patterns (office_id, pattern, kind) "
                        "values (:o, :p, CAST(:k AS pattern_kind))"
                    ),
                    {"o": goa, "p": pattern, "k": kind},
                )
    finally:
        command.upgrade(cfg, "head")
    try:
        with engine.connect() as conn:
            kws = dict(conn.execute(sa.text("select keyword, discover from office_keywords")).all())
            pats = dict(conn.execute(sa.text("select pattern, discover from office_name_patterns")).all())
            lanes = conn.execute(sa.text("select enum_range(NULL::fetch_lane)::text")).scalar()
            kinds = conn.execute(sa.text("select enum_range(NULL::fetch_kind)::text")).scalar()
            origins = conn.execute(sa.text("select enum_range(NULL::recommendation_origin)::text")).scalar()
        assert kws == {"PRITAM SAIKIA": True, "100% PASS": False, "AB": False}
        assert pats == {"PRITAM SAIKIA": True, "DR R DAS": True, "^PRITAM": False}
        assert lanes == "{request,daily,discovery,load}"
        assert "party_search" in kinds and "discovery" in origins
        assert {"discovery_terms", "discovery_hits"} <= _tables(engine)
        # the CHECK on a regex pattern
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
            conn.execute(sa.text("update office_name_patterns set discover = true where kind = 'regex'"))
        # lane precedence with the new value
        with sessionmaker(bind=engine)() as s:
            queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000012026", 41, lane=FetchLane.DISCOVERY)
            queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000012026", 40, lane=FetchLane.DAILY)
            assert queue.get_state(s, FetchKind.DOSSIER, "GAHC010000012026").lane == FetchLane.DAILY
            queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000022026", 44, lane=FetchLane.LOAD)
            queue.enqueue(s, FetchKind.DOSSIER, "GAHC010000022026", 41, lane=FetchLane.DISCOVERY)
            row = queue.get_state(s, FetchKind.DOSSIER, "GAHC010000022026")
            assert (row.lane, row.priority) == (FetchLane.DISCOVERY, 41)
            # a pending party_search row blocks the downgrade
            queue.enqueue(
                s, FetchKind.PARTY_SEARCH, "GAHC01|P|2026|PRITAM SAIKIA", 43, lane=FetchLane.DISCOVERY
            )
            s.commit()
        with pytest.raises(RuntimeError, match="party_search"):
            command.downgrade(cfg, "0016")
        with engine.connect() as conn:
            assert (
                conn.execute(sa.text("select version_num from alembic_version")).scalar() == head_revision()
            )
        with engine.begin() as conn:
            conn.execute(sa.text("update fetch_queue set status = 'done' where kind = 'party_search'"))
        command.downgrade(cfg, "0016")
        assert not {"discovery_terms", "discovery_hits"} & _tables(engine)
        assert "discover" not in _cols(engine, "office_name_patterns")
        with engine.connect() as conn:  # the enum values stay (PostgreSQL cannot drop them)
            assert conn.execute(sa.text("select enum_range(NULL::fetch_lane)::text")).scalar() == lanes
    finally:
        command.upgrade(cfg, "head")
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(
                conn, opts={"compare_type": True, "compare_server_default": True}
            )
            diff = compare_metadata(ctx, Base.metadata)
        real = [d for d in diff if not (d[0] == "modify_type" and isinstance(d[-1], sa.Enum))]
        assert real == [], real
    finally:
        with engine.begin() as conn:
            wipe(conn)
