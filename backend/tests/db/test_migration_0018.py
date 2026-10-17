"""Migration 0018 (design `next-date-extraction`, "Data"): the upgrade from 0017 on a database with orders and
`current_status` rows leaves every order `pending` and every row valid under the new CHECKs, adds the two review
statuses, the reading columns and the three reference rows; the downgrade refuses while a row read from an order
exists, otherwise drops what was added (the enum values stay); the database matches the models at head."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.orm import sessionmaker

from aslms.db.base import Base
from aslms.services.seed import seed_all
from tests.db.conftest import alembic_config, head_revision, wipe, wipe_if_migrated
from tests.db.world import make_case


def _cols(engine, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(engine).get_columns(table)}


def _scalar(engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(sa.text(sql), params).scalar()


def test_0018_upgrade_and_downgrade(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    with sessionmaker(bind=engine)() as s:
        seed_all(s)
        s.commit()
    command.downgrade(cfg, "0017")
    try:
        assert "next_date_status" not in _cols(engine, "orders")
        with sessionmaker(bind=engine)() as s:
            case = make_case(s)
            s.commit()
            case_id = case.id
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "insert into orders (case_id, order_no, order_date, kind) "
                    "values (:c, '1', current_date - 3, 'interim')"
                ),
                {"c": case_id},
            )
            conn.execute(
                sa.text(
                    "insert into next_dates (case_id, next_date, source, review_status) "
                    "values (:c, current_date + 5, 'current_status', 'not_needed')"
                ),
                {"c": case_id},
            )
    finally:
        command.upgrade(cfg, "head")
    try:
        assert {"next_date_status", "next_date_found", "next_date_read_at"} <= _cols(engine, "orders")
        assert _scalar(engine, "select next_date_status::text from orders") == "pending"
        statuses = _scalar(engine, "select enum_range(NULL::review_status)::text")
        assert statuses == "{not_needed,pending,confirmed,rejected,superseded,expired}"
        assert _scalar(
            engine, "select default_severity from ref_alert_kind where code = 'next_date_review'"
        ) == ("normal")
        assert (
            _scalar(
                engine,
                "select count(*) from ref_event_type where code in ('next_date_reviewed', 'next_date_entered') and is_tracking_card",
            )
            == 2
        )
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:  # a manual row needs its NXT ref
            conn.execute(
                sa.text(
                    "insert into next_dates (case_id, next_date, source) values (:c, current_date, 'manual')"
                ),
                {"c": case_id},
            )
        with engine.begin() as conn:
            order_id = conn.execute(sa.text("select id from orders")).scalar()
            conn.execute(
                sa.text(
                    "insert into next_dates (case_id, next_date, source, order_id, review_status, needs_review) "
                    "values (:c, current_date + 9, 'order_specific', :o, 'not_needed', false)"
                ),
                {"c": case_id, "o": order_id},
            )
        with pytest.raises(RuntimeError, match="0018"):
            command.downgrade(cfg, "0017")
        assert _scalar(engine, "select version_num from alembic_version") == head_revision()
        with engine.begin() as conn:
            conn.execute(sa.text("delete from next_dates where source = 'order_specific'"))
        command.downgrade(cfg, "0017")
        assert "next_date_status" not in _cols(engine, "orders")
        assert _scalar(engine, "select count(*) from ref_alert_kind where code = 'next_date_review'") == 0
        assert _scalar(engine, "select to_regtype('order_next_date_status')") is None
        assert _scalar(engine, "select enum_range(NULL::review_status)::text") == statuses  # values stay
        assert _scalar(engine, "select count(*) from next_dates") == 1
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
