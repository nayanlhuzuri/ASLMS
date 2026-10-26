"""Migration 0028 (design case-ref-court-prefix, "Data" and decisions 2 and 6-16): on 0027-era rows every case number
moves from `ASLMS/GOA/CASE/` to `ASLMS/GHC/CASE/` with the same year and number (provisional, CNR-less and merged rows
included), the CNRs and `updated_at` are untouched, the vectors find the new number, the CASE counters move (each at
least the highest number held), other counters, events and audit rows stay, one summary audit row is written, the next
case continues the counter; the downgrade restores everything and drops the column, the constraints and the
extension; a second upgrade writes a second summary row; the guards stop the upgrade (and the downgrade) with nothing
changed."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.orm import sessionmaker

from aslms.domain.courts import Court
from aslms.services.refno import allocate_case_ref_no
from aslms.services.seed import seed_all
from tests.db.conftest import alembic_config, wipe, wipe_if_migrated

pytestmark = pytest.mark.migration_cycle

OLD = "ASLMS/GOA/CASE/"
NEW = "ASLMS/GHC/CASE/"


@pytest.fixture()
def at_0027(db_url, engine) -> Iterator:
    """A seeded database at 0027 with empty `audit_log` and `events`; afterwards wiped, back at head and wiped."""
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    try:
        with sessionmaker(bind=engine)() as s:
            seed_all(s)
            s.commit()
        command.downgrade(cfg, "0027")
        with engine.begin() as conn:
            conn.execute(sa.text("SET session_replication_role = replica"))  # audit_log is append-only
            for table in ("audit_log", "events"):
                conn.execute(sa.text(f"DELETE FROM {table}"))
            conn.execute(sa.text("SET session_replication_role = DEFAULT"))
        yield cfg
    finally:
        with engine.begin() as conn:
            wipe(conn)
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            wipe(conn)


def _court_id(conn, est: str = "GAHC01"):
    return conn.execute(sa.text("SELECT id FROM courts WHERE est_code = :e"), {"e": est}).scalar_one()


def _case(conn, ref_no: str, *, cnr: str | None, case_no: str | None, merged_into=None, court=None):
    return conn.execute(
        sa.text(
            "INSERT INTO cases (cnr, court_id, case_no_text, ref_no, first_seen_source, is_provisional, "
            "merged_into_case_id) VALUES (:cnr, :court, :case_no, :ref, 'causelist', :prov, :merged) RETURNING id"
        ),
        {
            "cnr": cnr,
            "court": court or _court_id(conn),
            "case_no": case_no,
            "ref": ref_no,
            "prov": cnr is None or merged_into is not None,
            "merged": merged_into,
        },
    ).scalar_one()


def _seed_0027_rows(engine) -> dict:
    """GOA cases (one pending with a CNR, one provisional without, one merged into the first, one of 2025), the
    GOA CASE counters (2026 above the highest held, 2025 below it), a GOA ALR and an EDU NOTE counter, and an event
    and an audit row carrying a GOA number."""
    with engine.begin() as conn:
        a = _case(conn, f"{OLD}2026/000001", cnr="GAHC010000012025", case_no="WP(C)/1/2025")
        b = _case(conn, f"{OLD}2026/000002", cnr=None, case_no="WP(C)/2/2025")
        c = _case(conn, f"{OLD}2026/000003", cnr=None, case_no="WP(C)/1/2025", merged_into=a)
        d = _case(conn, f"{OLD}2025/000007", cnr="GAHC010000072024", case_no="WA/7/2024")
        conn.execute(sa.text("UPDATE cases SET search_vector = aslms_case_search_vector(id)"))
        conn.execute(
            sa.text(
                "INSERT INTO ref_sequences (office_code, record_type, year, last_value) VALUES "
                "('GOA', 'CASE', 2026, 5), ('GOA', 'CASE', 2025, 3), ('GOA', 'ALR', 2026, 4), "
                "('EDU', 'NOTE', 2026, 9)"
            )
        )
        payload = {"merged_ref_no": f"{OLD}2026/000003", "into_ref_no": f"{OLD}2026/000001"}
        conn.execute(
            sa.text(
                "INSERT INTO events (type, case_id, payload, dedupe_key, visibility) "
                "VALUES ('case_merged', :case, CAST(:p AS jsonb), 'case_merged:seed', 'scoped')"
            ),
            {"case": a, "p": json.dumps(payload)},
        )
        conn.execute(
            sa.text(
                "INSERT INTO audit_log (action, entity_type, entity_id, case_id, actor_name, after) "
                "VALUES ('case.merged', 'case', :case, :case, 'system', CAST(:p AS jsonb))"
            ),
            {"case": a, "p": json.dumps(payload)},
        )
    return {"a": a, "b": b, "c": c, "d": d}


def _state(engine) -> dict:
    with engine.connect() as conn:
        return {
            "refs": dict(conn.execute(sa.text("SELECT id, ref_no FROM cases")).all()),
            "updated": dict(conn.execute(sa.text("SELECT id, updated_at FROM cases")).all()),
            "cnr_md5": conn.execute(
                sa.text("SELECT md5(string_agg(cnr, ',' ORDER BY id)) FROM cases")
            ).scalar(),
            "counters": {
                (r.office_code, r.record_type, r.year): r.last_value
                for r in conn.execute(sa.text("SELECT * FROM ref_sequences")).all()
            },
            "events": conn.execute(sa.text("SELECT id, type, payload FROM events ORDER BY id")).all(),
            "audits": conn.execute(
                sa.text("SELECT id, action, after FROM audit_log WHERE action = 'case.merged' ORDER BY id")
            ).all(),
        }


def _summaries(engine) -> list:
    with engine.connect() as conn:
        return conn.execute(
            sa.text(
                "SELECT actor_name, entity_type, after FROM audit_log WHERE action = 'case.ref_renumbered' "
                "ORDER BY created_at"
            )
        ).all()


def _schema(engine) -> dict:
    with engine.connect() as conn:
        return {
            "column": conn.execute(
                sa.text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'courts' "
                    "AND column_name = 'ref_code')"
                )
            ).scalar(),
            "constraints": set(
                conn.execute(
                    sa.text(
                        "SELECT conname FROM pg_constraint WHERE conname IN "
                        "('ck_cases_ref_no_court', 'ck_courts_ref_code_format', 'ex_courts_ref_code_one_court')"
                    )
                ).scalars()
            ),
            "extension": conn.execute(
                sa.text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'btree_gist')")
            ).scalar(),
            "revision": conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar(),
        }


def _finds(engine, ref_no: str) -> int:
    with engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT count(*) FROM cases WHERE search_vector @@ plainto_tsquery('simple', :r)"),
            {"r": ref_no},
        ).scalar()


ALL_CONSTRAINTS = {"ck_cases_ref_no_court", "ck_courts_ref_code_format", "ex_courts_ref_code_one_court"}


def test_upgrade_renumbers_and_downgrade_restores(at_0027, engine):
    ids = _seed_0027_rows(engine)
    before = _state(engine)
    assert _schema(engine) == {"column": False, "constraints": set(), "extension": False, "revision": "0027"}

    command.upgrade(at_0027, "0028")
    up = _state(engine)
    assert up["refs"] == {k: v.replace(OLD, NEW) for k, v in before["refs"].items()}
    assert up["refs"][ids["c"]] == f"{NEW}2026/000003"  # the merged row moves too
    assert up["cnr_md5"] == before["cnr_md5"] and up["updated"] == before["updated"]
    assert _finds(engine, f"{NEW}2026/000001") == 1 and _finds(engine, f"{OLD}2026/000001") == 0
    assert up["counters"] == {
        ("GHC", "CASE", 2026): 5,
        ("GHC", "CASE", 2025): 7,  # raised to the highest number held
        ("GOA", "ALR", 2026): 4,
        ("EDU", "NOTE", 2026): 9,
    }
    assert up["events"] == before["events"] and up["audits"] == before["audits"]  # history as recorded
    assert _schema(engine) == {
        "column": True,
        "constraints": ALL_CONSTRAINTS,
        "extension": True,
        "revision": "0028",
    }
    with engine.connect() as conn:
        assert set(conn.execute(sa.text("SELECT DISTINCT ref_code FROM courts")).scalars()) == {"GHC"}
    (summary,) = _summaries(engine)
    assert summary.actor_name == "migration 0028" and summary.entity_type == "system"
    after = summary.after
    assert (after["from_prefix"], after["to_prefix"]) == (OLD, NEW)
    assert (after["cases"], after["provisional"], after["merged"]) == (4, 2, 1)
    assert (after["first"], after["last"]) == (f"{NEW}2025/000007", f"{NEW}2026/000003")
    assert after["sequences"] == [{"year": 2025, "last_value": 7}, {"year": 2026, "last_value": 5}]
    assert after["rule"] == "same year and number" and after["owner_decision"] == "2026-10-25"
    assert after["migration"] == "0028"

    # the next case continues the counter on the court's code
    with sessionmaker(bind=engine)() as s:
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        assert allocate_case_ref_no(s, court, datetime(2026, 6, 1)) == f"{NEW}2026/000006"
        s.rollback()

    command.downgrade(at_0027, "0027")
    down = _state(engine)
    assert down["refs"] == before["refs"] and down["updated"] == before["updated"]
    assert down["cnr_md5"] == before["cnr_md5"]
    assert down["counters"] == {
        ("GOA", "CASE", 2026): 5,
        ("GOA", "CASE", 2025): 7,
        ("GOA", "ALR", 2026): 4,
        ("EDU", "NOTE", 2026): 9,
    }
    assert _finds(engine, f"{OLD}2026/000001") == 1 and _finds(engine, f"{NEW}2026/000001") == 0
    assert _schema(engine) == {"column": False, "constraints": set(), "extension": False, "revision": "0027"}
    assert len(_summaries(engine)) == 1  # audit rows are append-only and stay

    command.upgrade(at_0027, "0028")
    again = _state(engine)
    assert again["refs"] == up["refs"] and again["counters"] == up["counters"]
    assert again["updated"] == before["updated"]
    first, second = _summaries(engine)  # a re-application is recorded
    assert second.after["cases"] == 4 and second.after["sequences"] == first.after["sequences"]


def test_empty_database_writes_no_summary(at_0027, engine):
    command.upgrade(at_0027, "0028")
    assert _summaries(engine) == []
    assert _schema(engine)["constraints"] == ALL_CONSTRAINTS


def _refused(cfg, engine, revision: str, match: str) -> None:
    before = _state(engine)
    schema = _schema(engine)
    with pytest.raises(Exception, match=match) as info:  # the class of alembic's own load of the module
        if revision == "0027":
            command.downgrade(cfg, revision)
        else:
            command.upgrade(cfg, revision)
    assert type(info.value).__name__ == "RenumberRefused"
    assert _state(engine) == before and _schema(engine) == schema


def test_department_prefixed_case_stops_the_upgrade(at_0027, engine):
    _seed_0027_rows(engine)
    with engine.begin() as conn:
        _case(conn, "ASLMS/EDU/CASE/2026/000001", cnr="GAHC010000092025", case_no="WP(C)/9/2025")
    _refused(at_0027, engine, "0028", "not of the form")


def test_case_on_another_court_stops_the_upgrade(at_0027, engine):
    _seed_0027_rows(engine)
    with engine.begin() as conn:
        hc = conn.execute(
            sa.text("INSERT INTO high_courts (napix_state_code, name) VALUES (99, 'Another') RETURNING id")
        ).scalar_one()
        court = conn.execute(
            sa.text(
                "INSERT INTO courts (est_code, name, high_court_id) VALUES ('OTHC01', 'Other', :hc) RETURNING id"
            ),
            {"hc": hc},
        ).scalar_one()
        _case(conn, f"{OLD}2026/000004", cnr="OTHC010000012025", case_no="WP(C)/4/2025", court=court)
    _refused(at_0027, engine, "0028", "not a Gauhati High Court establishment")


def test_office_ghc_stops_the_upgrade(at_0027, engine):
    _seed_0027_rows(engine)
    with engine.begin() as conn:
        root = conn.execute(sa.text("SELECT id FROM offices WHERE code = 'GOA'")).scalar_one()
        conn.execute(
            sa.text(
                "INSERT INTO offices (code, name, kind, parent_id, path) "
                "VALUES ('GHC', 'High Court cell', 'central', :root, 'GOA/GHC')"
            ),
            {"root": root},
        )
    _refused(at_0027, engine, "0028", "an office holds the code GHC")


def test_existing_ghc_counter_stops_the_upgrade(at_0027, engine):
    _seed_0027_rows(engine)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO ref_sequences (office_code, record_type, year, last_value) VALUES ('GHC', 'CASE', 2026, 1)"
            )
        )
    _refused(at_0027, engine, "0028", "GHC CASE counter already exists")


def test_another_court_code_stops_the_downgrade(at_0027, engine):
    _seed_0027_rows(engine)
    command.upgrade(at_0027, "0028")
    with engine.begin() as conn:
        hc = conn.execute(
            sa.text("INSERT INTO high_courts (napix_state_code, name) VALUES (99, 'Another') RETURNING id")
        ).scalar_one()
        court = conn.execute(
            sa.text(
                "INSERT INTO courts (est_code, name, high_court_id, ref_code) "
                "VALUES ('OTHC01', 'Other', :hc, 'OHC') RETURNING id"
            ),
            {"hc": hc},
        ).scalar_one()
        _case(conn, "ASLMS/OHC/CASE/2026/000001", cnr="OTHC010000012025", case_no="WP(C)/1/2025", court=court)
    _refused(at_0027, engine, "0027", "only GHC maps back")
