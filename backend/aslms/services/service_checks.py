"""The ten ASLMS service checks of the System health screen (design `api-health-checker`, decision 10).

Each check returns a status (`ok` / `warn` / `down` / `unknown`), a one-line headline, a few labelled facts and its
`duration_ms`. The thresholds are the Prometheus rules' numbers (`infra/prometheus/rules.yml`), so the screen and the
alerts agree. The network probes (Redis, the direct database probe, ClamAV, the web portal and the document store)
run in parallel threads, each within `OPS_PROBE_TIMEOUT_SECONDS`; the database readings run on the request's session.
A check that raises becomes `unknown` with the exception's class name only. Never calls NAPIX; never returns a URL, a
password or a host credential; writes nothing but one temporary probe file in the store. Not audited (a read).

Design `assistant-ollama`, decision 17: an eleventh check, "Case Assistant Model", only with `ASSISTANT_MODE=ollama`.
It reads `/api/version`, `/api/tags` and `/api/ps` only (never generates, never loads) and never shows the address."""

from __future__ import annotations

import shutil
import socket
import struct
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

import aslms
from aslms.core.config import Settings
from aslms.domain.ops import FetchQueueItem, FetchStatus, JobRun, JobStatus
from aslms.integration.ollama import ModelState, OllamaClient, expires_label
from aslms.services.audit_search import to_ist

PROCESS_STARTED = datetime.now(UTC)
SSL_REQUEST = struct.pack("!ii", 8, 80877103)  # what `pg_isready` establishes: the server answers S or N
GB = 1024**3
ORDER = (
    "api",
    "db_pool",
    "db_direct",
    "redis",
    "worker",
    "scheduler",
    "clamav",
    "backups",
    "store",
    "web",
)
LABELS = {
    "api": "ASLMS API",
    "db_pool": "Database through the pool",
    "db_direct": "Database server (direct)",
    "redis": "Redis",
    "worker": "Queue worker",
    "scheduler": "Scheduler",
    "clamav": "Virus scanner",
    "backups": "Backups",
    "store": "Document store",
    "web": "Web portal",
    "assistant_model": "Case Assistant Model",
}
# the Prometheus rules' numbers (decision 10)
CONNECTIONS_WARN = 0.8  # PostgresConnectionsHigh
WORKER_DOWN = timedelta(hours=2)  # WorkerStalled
WORKER_WARN = timedelta(minutes=70)  # a worker sleeping until the window's reset wakes within about 62 min
SCHEDULER_DOWN = timedelta(minutes=30)  # JobLate (notifications_send)
SCHEDULER_WARN = timedelta(minutes=10)
CLAMAV_OLD = timedelta(days=3)  # ClamAVSignaturesOld
BACKUP_DOWN = timedelta(hours=13)  # BackupMissing
RESTORE_DOWN = timedelta(days=8)  # RestoreCheckMissing
DISK_FREE_RATIO, DISK_FREE_BYTES = 0.15, 10 * GB  # DiskLow
WEB_SLOW_MS = 2000
SUCCESS = (JobStatus.SUCCEEDED, JobStatus.PARTIAL)


@dataclass
class Check:
    key: str
    status: str
    headline: str
    facts: list[dict[str, str]] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": LABELS[self.key],
            "status": self.status,
            "headline": self.headline,
            "facts": self.facts,
            "duration_ms": self.duration_ms,
        }


def _f(label: str, value: Any) -> dict[str, str]:
    return {"label": label, "value": "—" if value is None else str(value)}


def _when(value: datetime | None) -> str:
    return to_ist(value).strftime("%d %b %Y %H:%M") if value is not None else "never"


def _ago(now: datetime, value: datetime) -> str:
    s = max(0, int((now - value).total_seconds()))
    if s < 90:
        return f"{s} s ago"
    if s < 90 * 60:
        return f"{s // 60} min ago"
    if s < 48 * 3600:
        return f"{s // 3600} h ago"
    return f"{s // 86400} days ago"


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


# ------------------------------------------------------------------------------------------------ probes


@dataclass
class Probes:
    """The outside world, injectable for tests. Each raises (or returns a falsy answer) when the target is down."""

    redis: Callable[[Settings], dict[str, Any]]
    pg_direct: Callable[[str, int, float], str]
    clamav: Callable[[Settings], str]
    web: Callable[[str, float], bool]
    store: Callable[[Path], None]
    disk: Callable[[str], Any]
    db_head: Callable[[Settings], str | None]
    assistant_model: Callable[[Settings], ModelState] | None = None


def redis_probe(settings: Settings) -> dict[str, Any]:
    import redis

    client = redis.Redis.from_url(
        settings.redis_url,
        socket_timeout=settings.ops_probe_timeout_seconds,
        socket_connect_timeout=settings.ops_probe_timeout_seconds,
    )
    try:
        started = time.perf_counter()
        client.ping()
        ping_ms = _ms(started)
        server = client.info("server")
        memory = client.info("memory")
    finally:
        client.close()
    return {
        "ping_ms": ping_ms,
        "version": server.get("redis_version"),
        "used": int(memory.get("used_memory") or 0),
        "max": int(memory.get("maxmemory") or 0),
    }


def pg_direct_probe(host: str, port: int, timeout: float) -> str:
    """The 8-byte SSLRequest and the server's one-byte answer, without a login: `S` or `N` means a PostgreSQL server
    is accepting connections."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(SSL_REQUEST)
        reply = sock.recv(1)
    return reply.decode("latin-1")


def clamav_probe(settings: Settings) -> str:
    from aslms.services.scanner import ClamdScanner

    return ClamdScanner(
        settings.clamav_host, settings.clamav_port, settings.ops_probe_timeout_seconds
    ).version()


def web_probe(url: str, timeout: float) -> bool:
    from aslms.services.ops_metrics import probe_http

    return probe_http(url, timeout)


def store_probe(path: Path) -> None:
    from aslms.services.store_check import write_probe

    write_probe(path)


_HEAD: dict[str, str | None] = {}


def db_head(settings: Settings) -> str | None:
    """The code's migration head (`db_guard.script_facts`), read once per process."""
    if "head" not in _HEAD:
        from aslms.services.db_guard import alembic_config, script_facts

        _HEAD["head"] = script_facts(alembic_config(settings.database_url_sync))[0]
    return _HEAD["head"]


def assistant_model_probe(settings: Settings) -> ModelState:
    """`/api/version`, `/api/tags` and `/api/ps` of the Ollama server (decision 17 of `assistant-ollama`)."""
    client = OllamaClient(settings.assistant_ollama_url)
    return client.state_sync(settings.assistant_ollama_model, timeout=settings.ops_probe_timeout_seconds)


def default_probes() -> Probes:
    return Probes(
        redis=redis_probe,
        pg_direct=pg_direct_probe,
        clamav=clamav_probe,
        web=web_probe,
        store=store_probe,
        disk=shutil.disk_usage,
        db_head=db_head,
        assistant_model=assistant_model_probe,
    )


# ------------------------------------------------------------------------------------------------ the checks


def check_api(now: datetime) -> Check:
    up = int((now - PROCESS_STARTED).total_seconds())
    return Check(
        "api",
        "ok",
        "Answering",
        [
            _f("Version", aslms.__version__),
            _f("Process started", _when(PROCESS_STARTED)),
            _f("Uptime", f"{up // 3600} h {(up % 3600) // 60} min"),
        ],
    )


def _address(settings: Settings) -> str:
    url = make_url(settings.database_url_sync)
    return f"{url.host}:{url.port or 5432}"


def check_db_pool(session: Session, settings: Settings, probes: Probes) -> Check:
    started = time.perf_counter()
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — the card reads down with the class name only
        return Check(
            "db_pool", "down", "The database did not answer", [_f("Error", type(exc).__name__)], _ms(started)
        )
    select_ms = _ms(started)
    try:
        with session.begin_nested():  # a refused reading must not spoil the request's transaction
            version, size, used, limit = session.execute(
                text(
                    "SELECT current_setting('server_version'), pg_database_size(current_database()), "
                    "(SELECT count(*) FROM pg_stat_activity), current_setting('max_connections')::int"
                )
            ).one()
    except Exception as exc:  # noqa: BLE001
        return Check(
            "db_pool",
            "warn",
            f"Answered in {select_ms} ms; its details could not be read",
            [_f("Error", type(exc).__name__)],
            select_ms,
        )
    # `aslms_app` has no right on `alembic_version` (migration 0001 revokes it), so in the running services the
    # revision is not readable here; `init` already refuses to start the services on a database behind the code
    stored = None
    try:
        with session.begin_nested():
            stored = session.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    except Exception:  # noqa: BLE001 — a refused revision is a missing fact, not a fault
        stored = None
    try:
        head = probes.db_head(settings)
    except Exception:  # noqa: BLE001 — the head is a fact, not the check
        head = None
    ratio = int(used) / int(limit) if limit else 0.0
    status, headline = "ok", f"Answered in {select_ms} ms"
    if ratio > CONNECTIONS_WARN:
        status, headline = "warn", f"Connections are {round(ratio * 100)} % of the limit"
    if head is not None and stored is not None and stored != head:
        status, headline = "warn", "The database needs an upgrade"
    direct = _address(settings) != settings.health_pool_address
    facts = [
        _f("Server version", version),
        _f("Database size", f"{round(int(size) / (1024 * 1024))} MB"),
        _f("Connections", f"{int(used)} of {int(limit)}"),
        _f("Database revision", stored or "checked when the services start"),
        _f("Code revision", head or "not known"),
    ]
    if direct:
        facts.insert(0, _f("Connection", "The API connects to the database directly on this server"))
        if status == "ok":
            headline = f"Answered in {select_ms} ms; the API connects to the database directly on this server"
    else:
        facts.insert(0, _f("Connection", "Through the pool (PgBouncer)"))
    return Check("db_pool", status, headline, facts, select_ms)


def check_db_direct(
    answer: str | None, error: str | None, pool_up: bool, settings: Settings, ms: int
) -> Check:
    target = _f("Checked", "A sign-in-free protocol probe of the database server")
    if answer in ("S", "N"):
        headline = f"Accepting connections ({ms} ms)"
        if not pool_up:
            headline = "The database answers; the pool (PgBouncer) does not"
        return Check("db_direct", "ok", headline, [target], ms)
    facts = [target, _f("Error", error or "no answer")]
    if pool_up:
        return Check(
            "db_direct",
            "warn",
            "The pool answers but the direct probe does not (a configuration mismatch)",
            facts,
            ms,
        )
    return Check("db_direct", "down", "The database server does not answer", facts, ms)


def check_redis(info: dict[str, Any] | None, error: str | None, ms: int) -> Check:
    if info is None:
        return Check("redis", "down", "Redis does not answer", [_f("Error", error or "no answer")], ms)
    used, cap = info["used"], info["max"]
    facts = [_f("Version", info.get("version")), _f("Memory used", f"{round(used / (1024 * 1024), 1)} MB")]
    if cap:
        facts.append(_f("Memory limit", f"{round(cap / (1024 * 1024), 1)} MB"))
        if used > 0.9 * cap:
            return Check("redis", "warn", f"Memory is {round(used / cap * 100)} % of the limit", facts, ms)
    return Check("redis", "ok", f"Answered in {info.get('ping_ms', ms)} ms", facts, info.get("ping_ms", ms))


def check_worker(session: Session, now: datetime) -> Check:
    from aslms.services import queue
    from aslms.services.ops_metrics import WORKER_PASS_JOB, worker_alive_at

    started = time.perf_counter()
    alive = worker_alive_at(session)
    last = session.scalar(
        select(JobRun)
        .where(JobRun.job == WORKER_PASS_JOB)
        .order_by(JobRun.started_at.desc(), JobRun.id.desc())
        .limit(1)
    )
    waiting = session.scalar(
        select(func.count())
        .select_from(FetchQueueItem)
        .where(
            FetchQueueItem.status == FetchStatus.PENDING,
            or_(FetchQueueItem.not_before.is_(None), FetchQueueItem.not_before <= now),
            FetchQueueItem.kind.not_in(queue.LOCAL_KINDS),
        )
    )
    facts = [_f("Last sign of work", _when(alive)), _f("Rows waiting to run", int(waiting or 0))]
    if last is not None:
        status = last.status.value if hasattr(last.status, "value") else str(last.status)
        if status == JobStatus.FAILED.value:
            facts.append(_f("Latest pass", "The latest pass failed"))
        else:
            counters = last.counters or {}
            facts.append(_f("Latest pass rows", counters.get("processed", 0)))
            facts.append(
                _f("Latest pass ended", _when(last.finished_at) if last.finished_at else "still running")
            )
            stopped = counters.get("stopped")
            if stopped:
                facts.append(_f("Why it stopped", str(stopped)[:120]))
    ms = _ms(started)
    if alive is None:
        return Check("worker", "down", "The queue worker has never run", facts, ms)
    age = now - alive
    if age > WORKER_DOWN:
        return Check(
            "worker", "down", f"No sign of work for {_ago(now, alive).removesuffix(' ago')}", facts, ms
        )
    if age > WORKER_WARN:
        return Check("worker", "warn", f"Last sign of work {_ago(now, alive)}", facts, ms)
    return Check("worker", "ok", f"Working; last sign of work {_ago(now, alive)}", facts, ms)


def check_scheduler(session: Session, now: datetime) -> Check:
    from aslms.services.job_repair import SCHEDULER_JOBS

    started = time.perf_counter()
    jobs = sorted(SCHEDULER_JOBS)
    latest = session.scalar(select(func.max(JobRun.started_at)).where(JobRun.job.in_(jobs)))
    failed = session.scalar(
        select(func.count())
        .select_from(JobRun)
        .where(
            JobRun.job.in_(jobs),
            JobRun.status == JobStatus.FAILED,
            JobRun.started_at >= now - timedelta(hours=24),
        )
    )
    facts = [_f("Latest scheduled job", _when(latest)), _f("Failed scheduled jobs (24 h)", int(failed or 0))]
    ms = _ms(started)
    if latest is None:
        return Check("scheduler", "down", "No scheduled job has run", facts, ms)
    age = now - latest
    if age > SCHEDULER_DOWN:
        return Check(
            "scheduler", "down", f"No scheduled job for {_ago(now, latest).removesuffix(' ago')}", facts, ms
        )
    if age > SCHEDULER_WARN:
        return Check("scheduler", "warn", f"Latest scheduled job {_ago(now, latest)}", facts, ms)
    return Check("scheduler", "ok", f"Latest scheduled job {_ago(now, latest)}", facts, ms)


def check_clamav(reply: str | None, error: str | None, now: datetime, ms: int) -> Check:
    from aslms.services.ops_metrics import parse_clamav_version

    if reply is None:
        return Check(
            "clamav",
            "down",
            "The virus scanner does not answer; uploads are refused",
            [_f("Error", error)],
            ms,
        )
    engine = reply.split("/", 1)[0].strip()[:60]
    signed = parse_clamav_version(reply)
    facts = [_f("Engine", engine)]
    if signed is None:
        return Check("clamav", "warn", "Answering; the signatures are not loaded yet", facts, ms)
    facts.append(_f("Signatures from", signed.strftime("%d %b %Y")))
    if now - signed > CLAMAV_OLD:
        return Check("clamav", "warn", f"Signatures from {signed.strftime('%d %b')} are old", facts, ms)
    return Check("clamav", "ok", f"Signatures from {signed.strftime('%d %b')}", facts, ms)


def check_backups(session: Session, settings: Settings, now: datetime) -> Check:
    started = time.perf_counter()

    def latest(job: str) -> datetime | None:
        return session.scalar(
            select(func.max(JobRun.started_at)).where(JobRun.job == job, JobRun.status.in_(SUCCESS))
        )

    backup, restore = latest("backup"), latest("restore_check")
    interval = timedelta(hours=settings.backup_interval_hours)
    facts = [_f("Last backup", _when(backup))]
    if backup is not None:
        facts.append(_f("Expected next by", _when(backup + interval)))
    facts.append(_f("Last restore check", _when(restore)))
    ms = _ms(started)
    if backup is None:
        return Check("backups", "down", "No backup has been made", facts, ms)
    if now - backup > BACKUP_DOWN:
        return Check("backups", "down", f"The last backup was {_ago(now, backup)}", facts, ms)
    if restore is None or now - restore > RESTORE_DOWN:
        return Check("backups", "down", "No restore check in the last 8 days", facts, ms)
    head = f"Last backup {_ago(now, backup)} · next by {to_ist(backup + interval).strftime('%H:%M')}"
    if now - backup > interval + timedelta(hours=1):
        return Check("backups", "warn", head, facts, ms)
    return Check("backups", "ok", head, facts, ms)


def check_store(error: str | None, usage: Any, ms: int) -> Check:
    if error is not None:
        return Check("store", "down", "ASLMS cannot save documents", [_f("Error", error)], ms)
    facts = []
    if usage is None:
        return Check("store", "ok", "Documents can be saved", facts, ms)
    free, total = int(usage.free), int(usage.total)
    ratio = free / total if total else 1.0
    facts = [_f("Free space", f"{round(free / GB, 1)} GB"), _f("Disk size", f"{round(total / GB, 1)} GB")]
    if ratio < DISK_FREE_RATIO or free < DISK_FREE_BYTES:
        return Check("store", "warn", f"Free space is low ({round(free / GB, 1)} GB)", facts, ms)
    return Check("store", "ok", f"Documents can be saved · {round(free / GB, 1)} GB free", facts, ms)


def check_web(up: bool | None, ms: int) -> Check:
    if up is None:
        return Check("web", "unknown", "No address configured for the portal check", [], ms)
    if not up:
        return Check("web", "down", "The portal does not answer", [], ms)
    if ms > WEB_SLOW_MS:
        return Check("web", "warn", f"Answered slowly ({ms} ms)", [], ms)
    return Check("web", "ok", f"Answered in {ms} ms", [], ms)


# ------------------------------------------------------------------------------------------------ the run


GPU_WORDS = {"full": "Fully", "partial": "Partly", "none": "No"}


def check_assistant_model(settings: Settings, state: ModelState | None, error: str | None, ms: int) -> Check:
    """Decision 17: `ok` loaded; `warn` held but not loaded, a version below 0.40, or the model only partly on the GPU;
    `down` unreachable, missing, not local, or the cloud rule broken. Facts: Ollama Version, Model, Loaded, On GPU and
    Kept Loaded Until — never the address."""
    from aslms.services.assistant_ollama import cloud_problems

    model = settings.assistant_ollama_model
    if cloud_problems(settings):
        return Check(
            "assistant_model",
            "down",
            "The model setting points at a cloud model or address; the Case Assistant is off",
            [_f("Model", "refused")],
            ms,
        )
    if state is None or error is not None or not state.reachable:
        return Check("assistant_model", "down", "Cannot reach the model server", [_f("Model", model)], ms)
    expires = expires_label(state.expires_at)
    facts = [
        _f("Ollama Version", state.version or "—"),
        _f("Model", model),
        _f("Loaded", "Yes" if state.loaded else "No"),
        _f("On GPU", GPU_WORDS.get(state.on_gpu or "", "—")),
        _f(
            "Kept Loaded Until",
            (
                "while the server runs"
                if expires is not None and expires.year >= 2200
                else (_when(expires) if expires is not None else "—")
            ),
        ),
    ]
    if state.reason == "missing":
        return Check("assistant_model", "down", "The model is not on the model server", facts, ms)
    if not state.local:
        return Check("assistant_model", "down", "The model is not held on the model server itself", facts, ms)
    if not state.loaded:
        return Check("assistant_model", "warn", "The model is on the server but not loaded yet", facts, ms)
    if not state.version_ok:
        return Check("assistant_model", "warn", "Ollama is older than 0.40", facts, ms)
    if state.on_gpu in ("partial", "none"):
        return Check("assistant_model", "warn", "The model is loaded but not fully on the GPU", facts, ms)
    return Check("assistant_model", "ok", "Loaded and ready", facts, ms)


def _timed(fn: Callable[[], Any]) -> tuple[Any, str | None, int]:
    started = time.perf_counter()
    try:
        return fn(), None, _ms(started)
    except Exception as exc:  # noqa: BLE001 — the class name only, never the message (it may hold an address)
        return None, type(exc).__name__, _ms(started)


def _safe(key: str, fn: Callable[[], Check]) -> Check:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — a raising check is unknown, with the class name only
        return Check(key, "unknown", "The check could not be run", [_f("Error", type(exc).__name__)])


def run_all(
    session: Session, settings: Settings, now: datetime | None = None, probes: Probes | None = None
) -> list[dict[str, Any]]:
    """The ten checks, in decision 10's order, and the Case Assistant Model in ollama mode (`assistant-ollama`)."""
    now = now or datetime.now(UTC)
    probes = probes or default_probes()
    timeout = settings.ops_probe_timeout_seconds
    store_dir = Path(settings.storage_dir)

    def store() -> Any:
        probes.store(store_dir)
        try:
            return probes.disk(str(store_dir))
        except OSError:
            return None

    jobs: dict[str, Callable[[], Any] | None] = {
        "redis": (lambda: probes.redis(settings)) if settings.redis_url else None,
        "db_direct": lambda: probes.pg_direct(
            settings.health_postgres_direct_host, settings.health_postgres_direct_port, timeout
        ),
        "clamav": lambda: probes.clamav(settings),
        "web": (lambda: probes.web(settings.ops_probe_web_url, timeout))
        if settings.ops_probe_web_url
        else None,
        "store": store,
    }
    ollama_mode = (getattr(settings, "assistant_mode", "off") or "off") == "ollama"
    if ollama_mode and probes.assistant_model is not None:
        jobs["assistant_model"] = lambda: probes.assistant_model(settings)
    pool = ThreadPoolExecutor(max_workers=7, thread_name_prefix="service-check")
    futures = {k: pool.submit(_timed, fn) for k, fn in jobs.items() if fn is not None}
    deadline = time.monotonic() + timeout + 1
    try:
        checks: dict[str, Check] = {"api": check_api(now)}
        checks["db_pool"] = _safe("db_pool", lambda: check_db_pool(session, settings, probes))
        checks["worker"] = _safe("worker", lambda: check_worker(session, now))
        checks["scheduler"] = _safe("scheduler", lambda: check_scheduler(session, now))
        checks["backups"] = _safe("backups", lambda: check_backups(session, settings, now))
        results: dict[str, tuple[Any, str | None, int]] = {}
        for key, fut in futures.items():
            try:
                results[key] = fut.result(timeout=max(0.0, deadline - time.monotonic()))
            except FutureTimeout:
                results[key] = (None, f"no answer within {timeout:g} s", int((timeout + 1) * 1000))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    pool_up = checks["db_pool"].status != "down"

    def res(key: str) -> tuple[Any, str | None, int]:
        return results.get(key, (None, None, 0))

    if settings.redis_url:
        info, err, ms = res("redis")
        checks["redis"] = _safe("redis", lambda: check_redis(info, err, ms))
    else:
        checks["redis"] = Check("redis", "unknown", "REDIS_URL is not set on this server")
    answer, err, ms = res("db_direct")
    checks["db_direct"] = _safe("db_direct", lambda: check_db_direct(answer, err, pool_up, settings, ms))
    reply, err, ms = res("clamav")
    checks["clamav"] = _safe("clamav", lambda: check_clamav(reply, err, now, ms))
    usage, err, ms = res("store")
    checks["store"] = _safe("store", lambda: check_store(err, usage, ms))
    if "web" in futures:
        up, err, ms = res("web")
        checks["web"] = _safe("web", lambda: check_web(bool(up) if err is None else False, ms))
    else:
        checks["web"] = check_web(None, 0)
    order = list(ORDER)
    if ollama_mode:
        state, err, ms = res("assistant_model")
        checks["assistant_model"] = _safe(
            "assistant_model", lambda: check_assistant_model(settings, state, err, ms)
        )
        order.append("assistant_model")
    return [checks[k].to_dict() for k in order]
