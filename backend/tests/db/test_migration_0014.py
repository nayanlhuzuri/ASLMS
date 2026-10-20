"""Migration 0014 (design `data-load-console`, "Data"): the rows of the running historical load are classified on the
upgrade (priority-60 days and priority-45 dossiers become `load` with their list date, their order PDFs follow,
pending load rows take the `cases_first` priorities, daily order PDFs at 75 move to 40); the downgrade removes the
table, the columns and the types; the database matches the models at head."""

from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.orm import sessionmaker

from aslms.db.base import Base
from aslms.services.seed import seed_all
from tests.db.conftest import alembic_config, wipe, wipe_if_migrated

pytestmark = pytest.mark.migration_cycle

CNR = "GAHC010000012025"
OTHER = "GAHC010000022025"


def _types(engine) -> set[str]:
    with engine.connect() as conn:
        return set(
            conn.execute(
                sa.text("select typname from pg_type where typname in ('fetch_lane', 'load_order')")
            ).scalars()
        )


def test_0014_classifies_existing_rows(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    with sessionmaker(bind=engine)() as s:
        seed_all(s)
        s.commit()
    command.downgrade(cfg, "0013")
    try:
        assert _types(engine) == set()
        with engine.begin() as conn:
            court = conn.execute(sa.text("select id from courts where est_code = 'GAHC01'")).scalar()
            cl_early = conn.execute(
                sa.text(
                    "insert into causelists (court_id, list_date, list_type, source) "
                    "values (:c, '2025-01-06', 'daily', 'napix') returning id"
                ),
                {"c": court},
            ).scalar()
            cl_late = conn.execute(
                sa.text(
                    "insert into causelists (court_id, list_date, list_type, source) "
                    "values (:c, '2025-01-09', 'daily', 'napix') returning id"
                ),
                {"c": court},
            ).scalar()
            for cl, sr, cnr, no in (
                (cl_late, 1, CNR, "WP(C)/1/2025"),
                (cl_early, 1, CNR, "WP(C)/1/2025"),
                (cl_late, 2, None, "WA/7/2024"),
            ):
                conn.execute(
                    sa.text(
                        "insert into causelist_entries (causelist_id, sr_no, cnr, case_no_text, source, "
                        "resolution_status) values (:cl, :sr, :cnr, :no, 'pdf_parse', 'provisional')"
                    ),
                    {"cl": cl, "sr": sr, "cnr": cnr, "no": no},
                )
            rows = [
                ("causelist_day", "2025-01-06", 60, "pending"),
                ("causelist_day", "2025-01-09", 60, "done"),
                ("causelist_day", "2026-10-10", 20, "done"),
                ("dossier", CNR, 45, "pending"),
                ("dossier", "GAHC01|WA/7/2024", 45, "failed"),
                ("dossier", OTHER, 40, "pending"),
                ("order_pdf", f"{CNR}|1|2025-01-06", 75, "pending"),
                ("order_pdf", f"{OTHER}|1|2026-10-01", 75, "pending"),
                ("order_pdf", f"{OTHER}|2|2020-10-01", 80, "pending"),
            ]
            for kind, ref, priority, status in rows:
                conn.execute(
                    sa.text(
                        "insert into fetch_queue (kind, ref, priority, status) "
                        "values (CAST(:k AS fetch_kind), :r, :p, CAST(:s AS fetch_queue_status))"
                    ),
                    {"k": kind, "r": ref, "p": priority, "s": status},
                )
    finally:
        command.upgrade(cfg, "head")
    try:
        with engine.connect() as conn:
            got = {
                (k, r): (lane, p, d)
                for k, r, lane, p, d in conn.execute(
                    sa.text("select kind::text, ref, lane::text, priority, list_date from fetch_queue")
                ).all()
            }
        assert got[("causelist_day", "2025-01-06")] == ("load", 46, date(2025, 1, 6))
        assert got[("causelist_day", "2025-01-09")] == ("load", 60, date(2025, 1, 9))  # done: priority kept
        assert got[("causelist_day", "2026-10-10")] == ("daily", 20, None)
        assert got[("dossier", CNR)] == ("load", 44, date(2025, 1, 6))  # the earliest list carrying the CNR
        assert got[("dossier", "GAHC01|WA/7/2024")] == ("load", 45, date(2025, 1, 9))  # by the printed number
        assert got[("dossier", OTHER)] == ("daily", 40, None)
        assert got[("order_pdf", f"{CNR}|1|2025-01-06")] == ("load", 48, date(2025, 1, 6))
        assert got[("order_pdf", f"{OTHER}|1|2026-10-01")] == ("daily", 40, None)
        assert got[("order_pdf", f"{OTHER}|2|2020-10-01")] == ("daily", 80, None)
        assert _types(engine) == {"fetch_lane", "load_order"}
        with engine.connect() as conn:
            ctx = MigrationContext.configure(
                conn, opts={"compare_type": True, "compare_server_default": True}
            )
            diff = compare_metadata(ctx, Base.metadata)
        real = [d for d in diff if not (d[0] == "modify_type" and isinstance(d[-1], sa.Enum))]
        assert real == [], real
        with engine.connect() as conn:
            values = set(
                conn.execute(
                    sa.text(
                        "select e.enumlabel from pg_enum e join pg_type t on t.oid = e.enumtypid "
                        "where t.typname in ('link_kind', 'link_source')"
                    )
                ).scalars()
            )
        assert {"court_duplicate", "dedupe"} <= values
        cols = {c["name"] for c in sa.inspect(engine).get_columns("data_load_settings")}
        assert {"version", "paused", "load_order", "first_from", "first_to", "is_current"} <= cols
    finally:
        with engine.begin() as conn:
            wipe(conn)
