"""The ASLMS service checks that read the database (design `api-health-checker`, decision 10): the worker, the
scheduler and the backups at their thresholds, the pool card's wording, the whole run within the probe timeout when a
probe hangs, no address or password in the output, and the exporter's worker gauge equal to `worker_alive_at`."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import sqlalchemy as sa

from aslms.core.config import Settings
from aslms.domain.ops import FetchKind, FetchQueueItem, FetchStatus, JobRun, JobStatus
from aslms.services import ops_metrics
from aslms.services import service_checks as sc
from aslms.services.seed import seed_all
from tests.db.conftest import wipe

NOW = datetime.now(UTC)
SETTINGS = Settings(_env_file=None, app_env="test", redis_url=None)


def _probes(**over) -> sc.Probes:
    usage = SimpleNamespace(free=500 * 1024**3, total=1000 * 1024**3)
    values = {
        "redis": lambda s: {"ping_ms": 1, "version": "7.4", "used": 1, "max": 0},
        "pg_direct": lambda h, p, t: "N",
        "clamav": lambda s: f"ClamAV 1.5.4/1/{datetime.now(UTC).strftime('%a %b %d %H:%M:%S %Y')}",
        "web": lambda u, t: True,
        "store": lambda p: None,
        "disk": lambda p: usage,
        "db_head": lambda s: None,
    }
    values.update(over)
    return sc.Probes(**values)


def _run(session, job: str, started: datetime, status=JobStatus.SUCCEEDED, **kw) -> None:
    session.add(JobRun(job=job, started_at=started, status=status, **kw))
    session.flush()


def _clean(session) -> None:
    wipe(session)
    seed_all(session)


def test_worker_thresholds(session):
    _clean(session)
    assert sc.check_worker(session, NOW).status == "down"  # never ran
    _run(session, "queue-run", NOW - timedelta(minutes=30), counters={"processed": 12, "stopped": "window"})
    ok = sc.check_worker(session, NOW)
    assert ok.status == "ok"
    facts = {f["label"]: f["value"] for f in ok.facts}
    assert facts["Latest pass rows"] == "12" and facts["Why it stopped"] == "window"
    assert sc.check_worker(session, NOW + timedelta(minutes=45)).status == "warn"  # 75 min
    assert sc.check_worker(session, NOW + timedelta(minutes=95)).status == "down"  # 125 min
    # a claim keeps it alive during a long pass
    session.add(
        FetchQueueItem(
            kind=FetchKind.DOSSIER,
            ref="GAHC010000012025",
            status=FetchStatus.RUNNING,
            priority=40,
            started_at=NOW + timedelta(minutes=90),
        )
    )
    session.flush()
    assert sc.check_worker(session, NOW + timedelta(minutes=95)).status == "ok"
    _run(session, "queue-run", NOW + timedelta(minutes=96), status=JobStatus.FAILED, error="Traceback: boom")
    failed = sc.check_worker(session, NOW + timedelta(minutes=97))
    facts = {f["label"]: f["value"] for f in failed.facts}
    assert facts["Latest pass"] == "The latest pass failed" and "Traceback" not in json.dumps(
        failed.to_dict()
    )


def test_scheduler_thresholds(session):
    _clean(session)
    assert sc.check_scheduler(session, NOW).status == "down"
    _run(session, "notifications_send", NOW - timedelta(minutes=5))
    _run(session, "digests", NOW - timedelta(hours=2), status=JobStatus.FAILED)
    _run(session, "queue-run", NOW)  # not a scheduler job
    ok = sc.check_scheduler(session, NOW)
    assert ok.status == "ok" and {"label": "Failed scheduled jobs (24 h)", "value": "1"} in ok.facts
    assert sc.check_scheduler(session, NOW + timedelta(minutes=6)).status == "warn"  # 11 min
    assert sc.check_scheduler(session, NOW + timedelta(minutes=26)).status == "down"  # 31 min


def test_backup_thresholds(session):
    _clean(session)
    assert sc.check_backups(session, SETTINGS, NOW).headline == "No backup has been made"
    _run(session, "backup", NOW - timedelta(hours=2))
    _run(session, "restore_check", NOW - timedelta(days=2))
    _run(
        session, "backup", NOW - timedelta(minutes=10), status=JobStatus.FAILED
    )  # a failed run does not count
    ok = sc.check_backups(session, SETTINGS, NOW)
    assert ok.status == "ok" and ok.headline.startswith("Last backup 2 h ago · next by ")
    # the interval (6 h) plus 1 h, then BackupMissing's 13 h
    assert sc.check_backups(session, SETTINGS, NOW + timedelta(hours=5, minutes=1)).status == "warn"
    assert sc.check_backups(session, SETTINGS, NOW + timedelta(hours=11, minutes=1)).status == "down"
    # RestoreCheckMissing: older than 8 days
    assert sc.check_backups(session, SETTINGS, NOW + timedelta(days=6, minutes=1)).status == "down"


def test_pool_card_wording(session):
    _clean(session)
    direct = sc.check_db_pool(session, SETTINGS, _probes())
    assert direct.status == "ok" and "connects to the database directly" in direct.headline
    pooled = Settings(
        _env_file=None,
        app_env="test",
        redis_url=None,
        database_url_sync="postgresql+psycopg://u:p@pgbouncer:6432/aslms",
    )
    card = sc.check_db_pool(session, pooled, _probes())
    assert {"label": "Connection", "value": "Through the pool (PgBouncer)"} in card.facts
    behind = sc.check_db_pool(session, SETTINGS, _probes(db_head=lambda s: "9999"))
    assert behind.status == "warn" and behind.headline == "The database needs an upgrade"
    stored = session.scalar(sa.text("SELECT version_num FROM alembic_version"))
    assert sc.check_db_pool(session, SETTINGS, _probes(db_head=lambda s: stored)).status == "ok"


def test_whole_run_within_the_probe_timeout_when_a_probe_hangs(session, tmp_path):
    _clean(session)
    fast = Settings(
        _env_file=None,
        app_env="test",
        redis_url="redis://:pw-of-redis@redis:6379/0",
        storage_dir=str(tmp_path),
        ops_probe_timeout_seconds=1,
    )

    def hang(*_a):
        time.sleep(5)

    started = time.monotonic()
    out = sc.run_all(session, fast, NOW, _probes(clamav=hang))
    assert time.monotonic() - started < 3.5
    by = {x["key"]: x for x in out}
    assert by["clamav"]["status"] == "down" and by["redis"]["status"] == "ok"
    assert [x["key"] for x in out] == list(sc.ORDER)


def test_no_url_or_password_in_the_output(session, tmp_path):
    _clean(session)
    secret = Settings(
        _env_file=None,
        app_env="test",
        redis_url="redis://:redis-secret-pw@redis:6379/0",
        database_url_sync="postgresql+psycopg://aslms_app:db-secret-pw@pgbouncer:6432/aslms",
        storage_dir=str(tmp_path),
    )

    def refuse(*_a):
        raise ConnectionRefusedError("redis://:redis-secret-pw@redis:6379/0 refused")

    for probes in (_probes(), _probes(redis=refuse, pg_direct=refuse, clamav=refuse, web=lambda u, t: False)):
        dumped = json.dumps(sc.run_all(session, secret, NOW, probes))
        for leak in ("redis-secret-pw", "db-secret-pw", "redis://", "postgresql", "http://", "web:3000"):
            assert leak not in dumped, leak


def test_store_probe_writes_in_the_store(session, tmp_path):
    _clean(session)
    s = Settings(_env_file=None, app_env="test", redis_url=None, storage_dir=str(tmp_path))
    out = {
        x["key"]: x
        for x in sc.run_all(session, s, NOW, _probes(store=sc.store_probe, disk=sc.shutil.disk_usage))
    }
    assert out["store"]["status"] in ("ok", "warn") and list(tmp_path.iterdir()) == []

    def denied(path):
        raise PermissionError("denied")

    out = {x["key"]: x for x in sc.run_all(session, s, NOW, _probes(store=denied))}
    assert out["store"]["status"] == "down"


def test_ops_metrics_worker_alive_unchanged(session):
    _clean(session)
    assert ops_metrics.worker_alive_at(session) is None
    _run(session, "queue-run", NOW - timedelta(hours=1))
    session.add(
        FetchQueueItem(
            kind=FetchKind.DOSSIER,
            ref="GAHC010000022025",
            status=FetchStatus.DONE,
            priority=40,
            started_at=NOW - timedelta(minutes=10),
        )
    )
    session.add(
        FetchQueueItem(
            kind=FetchKind.SEARCH_ROWS,
            ref="00000000-0000-0000-0000-000000000001",
            status=FetchStatus.RUNNING,
            priority=30,
            lane="request",
            started_at=NOW,
        )
    )
    session.flush()
    alive = ops_metrics.worker_alive_at(session)
    assert abs((alive - (NOW - timedelta(minutes=10))).total_seconds()) < 1
    samples, _ = ops_metrics.collect_database(session, SETTINGS, NOW)
    gauge = next(s for s in samples if s.name == "aslms_worker_alive_timestamp")
    assert gauge.value == alive.timestamp()
