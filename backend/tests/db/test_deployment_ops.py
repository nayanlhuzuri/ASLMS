"""Design deployment-checklist, Part A, against the test database: the start-up repair of `job_runs` (decision 18),
the load counts and the CNR sample (decision 19), the superuser check (decision 5) and the audit row of an explicit
migration (decision 12); design pre-pilot-hardening: a dump longer than the idle timeout (decision 1) and role
passwords stored as SCRAM verifiers (decision 5)."""

from __future__ import annotations

import secrets
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from aslms.cli import db as cli_db
from aslms.domain.cases import CaseParty, CaseStatus, PartyRole
from aslms.domain.events import AuditLog
from aslms.domain.ops import (
    FetchKind,
    FetchLane,
    FetchQueueItem,
    FetchStatus,
    JobRun,
    JobStatus,
    NapixCallLog,
    SourceFailure,
)
from aslms.services import backups, db_guard, load_report
from aslms.services.job_repair import SCHEDULER_JOBS, WORKER_JOBS, repair_interrupted
from tests.db.conftest import head_revision
from tests.db.world import add_listing, make_case

START = datetime(2026, 10, 19, 6, 0, tzinfo=UTC)


def test_repair_interrupted_marks_only_own_jobs_before_start(session):
    s = session
    own_old = JobRun(job="queue-run", started_at=START - timedelta(hours=3), error="earlier note")
    own_new = JobRun(job="queue-run", started_at=START + timedelta(seconds=5))
    own_done = JobRun(job="queue-run", started_at=START - timedelta(hours=4), status=JobStatus.SUCCEEDED)
    other = JobRun(job="extract_text", started_at=START - timedelta(hours=3))
    s.add_all([own_old, own_new, own_done, other])
    s.flush()
    assert repair_interrupted(s, WORKER_JOBS, START, "queue-worker restarted", dry_run=True) >= 1
    n = repair_interrupted(s, WORKER_JOBS, START, "queue-worker restarted")
    s.expire_all()
    assert n >= 1
    assert own_old.status == JobStatus.FAILED and own_old.finished_at is not None
    assert own_old.error == "earlier note; interrupted: queue-worker restarted"
    assert own_new.status == JobStatus.RUNNING and own_new.finished_at is None
    assert own_done.status == JobStatus.SUCCEEDED
    assert other.status == JobStatus.RUNNING
    assert repair_interrupted(s, SCHEDULER_JOBS, START, "scheduler restarted") >= 1
    s.expire_all()
    assert other.status == JobStatus.FAILED and other.error == "interrupted: scheduler restarted"


def _seed_load(s) -> dict:
    pending = [make_case(s, status=CaseStatus.PENDING) for _ in range(4)]
    disposed = [make_case(s, status=CaseStatus.DISPOSED) for _ in range(3)]
    provisional = make_case(s, cnr="", status=CaseStatus.UNKNOWN)
    provisional.cnr, provisional.is_provisional = None, True
    s.flush()
    for c in pending + disposed:
        c.last_full_refresh_at = START
        s.add(
            CaseParty(
                case_id=c.id, role=PartyRole.PETITIONER, party_no=1, name=f"Pet {c.cnr}", name_normalised="p"
            )
        )
        s.add(
            CaseParty(
                case_id=c.id,
                role=PartyRole.RESPONDENT,
                party_no=1,
                name="State of Assam",
                name_normalised="s",
            )
        )
    pending[0].last_full_refresh_at = None  # never fetched
    add_listing(s, pending[1], date(2025, 1, 6))
    add_listing(s, pending[2], date(2025, 3, 7))
    for ref, status in (
        ("2025-01-06", FetchStatus.DONE),
        ("2025-01-05", FetchStatus.SKIPPED),
        ("2025-01-07", FetchStatus.FAILED),
        ("2025-01-08", FetchStatus.PENDING),
    ):
        s.add(
            FetchQueueItem(
                kind=FetchKind.CAUSELIST_DAY, ref=ref, status=status, priority=50, lane=FetchLane.LOAD
            )
        )
    s.add(
        FetchQueueItem(kind=FetchKind.DOSSIER, ref="ZZHC010000992025", status=FetchStatus.FAILED, priority=50)
    )
    s.add(
        NapixCallLog(
            api="hc-cnr-api/CNR", params_sha256="0" * 64, ok=True, called_at=START - timedelta(days=1)
        )
    )
    s.add(
        NapixCallLog(
            api="hc-cnr-api/CNR",
            params_sha256="0" * 64,
            ok=False,
            error_family="NapixUnavailable",
            called_at=START - timedelta(days=20),
        )
    )
    s.add(SourceFailure(kind="order_pdf", ref="r1"))
    s.add(SourceFailure(kind="order_pdf", ref="r2", resolved_at=START))
    s.flush()
    return {"pending": pending, "disposed": disposed}


def _count(s, sql: str) -> int:
    return int(s.execute(sa.text(sql)).scalar())


def test_load_report_counts(clean_db, tmp_path):
    store = tmp_path / "store" / "ab"
    store.mkdir(parents=True)
    (store / "ab01.pdf").write_bytes(b"12345")
    with clean_db() as s:
        _seed_load(s)
        r = load_report.report(s, store_dir=tmp_path / "store", now=START)
        assert r["period"] == {"first_list_date": date(2025, 1, 6), "last_list_date": date(2025, 3, 7)}
        assert r["causelist_days"] == {
            "loaded": 1,
            "skipped": 1,
            "failed": 1,
            "pending": 1,
            "list_pdfs_stored": _count(s, "SELECT count(*) FROM causelists WHERE document_id IS NOT NULL"),
            "entries": 2,
        }
        assert r["cases"] == {
            "total": 8,
            "with_cnr": 7,
            "provisional_with_cnr": 0,
            "provisional_without_cnr": 1,
            "pending": 4,
            "disposed": 3,
        }
        assert r["dossiers"] == {"applied": 6, "failed": 1, "never_fetched": 1}
        assert r["parties"] == _count(s, "SELECT count(*) FROM case_parties") == 14
        assert r["advocates"] == _count(s, "SELECT count(*) FROM case_advocates")
        assert r["orders"]["references"] == _count(s, "SELECT count(*) FROM orders")
        assert r["napix_calls"]["total"] == 2
        assert r["napix_calls"]["by_outcome"] == {"NapixUnavailable": 1, "ok": 1}
        assert r["napix_calls"]["per_day_last_7_days"] == round(1 / 7, 1)
        assert {"lane": "load", "status": "done", "rows": 1} in r["fetch_queue"]
        assert r["source_failures_open"] == {"order_pdf": 1}
        assert r["database_bytes"] > 0
        assert r["store"] == {"files": 1, "bytes": 5}
        md = load_report.report_markdown(r)
        assert "## Load counts" in md and "| loaded | 1 |" in md


def test_sample_cnrs_reproducible_and_stratified(clean_db):
    with clean_db() as s:
        seeded = _seed_load(s)
        first = load_report.sample(s, pending=2, disposed=2, seed=20261018)
        again = load_report.sample(s, pending=2, disposed=2, seed=20261018)
        assert [r["cnr"] for r in first] == [r["cnr"] for r in again]
        assert [r["status"] for r in first] == ["pending", "pending", "disposed", "disposed"]
        applied = {c.cnr for c in seeded["pending"][1:] + seeded["disposed"]}
        assert all(r["cnr"] in applied for r in first)  # a CNR and an applied dossier only
        everything = load_report.sample(s, pending=10, disposed=10, seed=1)
        assert len(everything) == 6  # 3 applied pending, 3 disposed
        row = first[0]
        assert row["petitioner"].startswith("Pet ") and row["respondent"] == "State of Assam"
        assert row["court_shows"] == "" and row["match"] == ""
        md = load_report.sample_markdown(first, 20261018)
        assert "seed 20261018" in md and "| Court shows | Match |" in md


def test_superuser_check_reads_current_role(engine):
    with engine.connect() as conn:
        assert db_guard.is_superuser(conn) is True
        conn.execute(sa.text("SET ROLE aslms_app"))
        assert db_guard.is_superuser(conn) is False
        conn.execute(sa.text("RESET ROLE"))
        conn.rollback()


def test_db_guard_state_of_the_test_database(engine):
    with engine.connect() as conn:
        result = db_guard.state(conn, db_guard.alembic_config(str(engine.url)))
    assert result.state is db_guard.DbState.AT_HEAD and result.exit_code == 0


def test_audit_system_migrated_row(session):
    row = db_guard.write_migrated_audit(session, "0018", "0019", "20261019-0630-pre-migrate")
    got = session.get(AuditLog, row.id)
    assert got.action == "system.migrated" and got.entity_type == "database"
    assert got.actor_user_id is None and got.actor_name == "ops"
    assert got.before == {"revision": "0018"}
    assert got.after == {"revision": "0019", "backup": "20261019-0630-pre-migrate"}


# ------------------------------------------------------------------------------------------------ pre-pilot-hardening


def _with_options(url: str, options: str) -> str:
    return make_url(url).update_query_dict({"options": options}).render_as_string(hide_password=False)


def test_dump_survives_a_pg_dump_longer_than_the_idle_timeout(migrated, tmp_path, monkeypatch):
    """Decision 1: the exporting transaction sits idle while pg_dump runs; it turns off its own idle timeout, so a
    dump longer than idle_in_transaction_session_timeout no longer has its snapshot session killed."""
    url = _with_options(migrated, "-c idle_in_transaction_session_timeout=1000")
    # the server does enforce the 1 s timeout on this URL: an idle transaction without the fix is ended
    control = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with pytest.raises(sa.exc.DBAPIError):
            with control.connect() as conn, conn.begin():
                conn.execute(sa.text("SELECT 1"))
                time.sleep(2)
                conn.execute(sa.text("SELECT 1"))
    finally:
        control.dispose()

    calls: list[str] = []

    def fake_tool(args, target, *, database=None, what):
        calls.append(what)
        if args[0] == "pg_dump" and "-f" in args:
            time.sleep(2)  # longer than the 1 s timeout
            Path(args[args.index("-f") + 1]).write_bytes(b"PGDMP fake dump")
        elif args[0] == "pg_dumpall":
            Path(args[args.index("-f") + 1]).write_text("-- roles", encoding="utf-8")
        elif args[:2] == ["pg_dump", "--version"]:
            return "pg_dump (PostgreSQL) 16.15"
        return ""

    monkeypatch.setattr(backups, "_tool", fake_tool)
    manifest = backups.dump(url, tmp_path, tag="idle-check")
    assert calls == ["pg_dump", "pg_dumpall", "pg_dump --version", "pg_restore --list"]
    assert manifest.dump_bytes == len(b"PGDMP fake dump")
    assert manifest.revision == head_revision()
    assert (tmp_path / "db" / f"aslms-{manifest.name}.dump").exists()


def test_role_password_is_stored_as_scram_and_logs_in(migrated, engine):
    """Decision 5: the password is sent as a client-side SCRAM-SHA-256 verifier; the role logs in with it."""
    role = f"aslms_pwcheck_{secrets.token_hex(4)}"
    password = f"pw-{secrets.token_hex(12)}"
    database = make_url(migrated).database
    with engine.begin() as conn:
        conn.execute(sa.text(f'CREATE ROLE "{role}" LOGIN'))
        conn.execute(sa.text(f'GRANT CONNECT ON DATABASE "{database}" TO "{role}"'))
    try:
        cli_db._set_password(migrated, role, password)
        with engine.connect() as conn:
            stored = conn.execute(
                sa.text("SELECT rolpassword FROM pg_authid WHERE rolname = :r"), {"r": role}
            ).scalar()
        assert stored.startswith("SCRAM-SHA-256$")
        as_role = make_url(migrated).set(username=role, password=password)
        ok = sa.create_engine(as_role, poolclass=sa.pool.NullPool)
        try:
            with ok.connect() as conn:
                assert conn.execute(sa.text("SELECT current_user")).scalar() == role
        finally:
            ok.dispose()
        wrong = sa.create_engine(as_role.set(password=password + "x"), poolclass=sa.pool.NullPool)
        try:
            with pytest.raises(sa.exc.OperationalError):
                with wrong.connect():
                    pass
        finally:
            wrong.dispose()
        raw = engine.raw_connection()
        try:
            pgconn = raw.driver_connection
            statement = cli_db.role_password_statement(pgconn.pgconn, role, password).as_string(pgconn)
        finally:
            raw.close()
        assert password not in statement and "SCRAM-SHA-256$" in statement
    finally:
        with engine.begin() as conn:
            conn.execute(sa.text(f'REVOKE CONNECT ON DATABASE "{database}" FROM "{role}"'))
            conn.execute(sa.text(f'DROP ROLE IF EXISTS "{role}"'))
