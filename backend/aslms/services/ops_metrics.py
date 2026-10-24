"""The ASLMS operations exporter (design deployment-checklist, Part B, decision 23): `aslms ops metrics --port 9108`.

One read-only process in the backend image, connected as `aslms_readonly`, that Prometheus scrapes. Every reading is
a gauge, computed at most once per `OPS_METRICS_CACHE_SECONDS` (60) and served from the cache in between:
- the database, in one `READ ONLY` transaction under `SET LOCAL statement_timeout` (`OPS_METRICS_STATEMENT_TIMEOUT_
  SECONDS`, 10): the queue by lane, kind and status and the oldest runnable row per lane; each job's last success,
  running rows and the oldest running row; the worker's last pass (the latest `queue-run` start) and its liveness
  (the later of that and the latest row it claimed, `search_rows` excepted: design pre-pilot-hardening, decision 4;
  Flower cannot see it); NAPIX calls of the last hour, the detected window's remaining calls
  (`services/napix_window.py`) and the master switch as this process sees it; open source failures by kind
  (`data_health.failures`), e-mail notifications by status and the oldest queued (`data_health.mail`), SourceTrace
  documents by status (`sourcetrace_ingest.status`);
- `BACKUP_DIR/status` (mounted read-only; readable while the database is down): the last backup and restore check;
- the free and total bytes of each path in `OPS_DISK_PATHS` (`/data`, `/backups`);
- clamd's `VERSION` answer: up and the signature date;
- HTTP probes of the portal through the proxy (with the portal's host name, so the proxy's host check passes; the
  certificate's expiry is read from the same handshake), `web` and `api`;
- `aslms_scrape_errors`: the sections that failed in the latest refresh.

No label carries case data: labels are queue lanes, kinds and statuses, job names, failure kinds, notification and
SourceTrace statuses, disk paths and probe targets. Never calls NAPIX; never writes; never prints a secret."""

from __future__ import annotations

import logging
import shutil
import socket
import ssl
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from aslms.core.config import Settings
from aslms.domain.alerts import Notification
from aslms.domain.ops import (
    FetchKind,
    FetchLane,
    FetchQueueItem,
    FetchStatus,
    JobRun,
    JobStatus,
    NapixCallLog,
    failed_call,
    renewal_step,
)
from aslms.domain.org import Channel

log = logging.getLogger(__name__)

WORKER_PASS_JOB = "queue-run"
SUCCESS = (JobStatus.SUCCEEDED, JobStatus.PARTIAL)
PROBE_TARGETS = ("portal", "web", "api")

HELP: dict[str, str] = {
    "aslms_queue_rows": "fetch_queue rows by lane, kind and status",
    "aslms_queue_oldest_pending_seconds": "age of the oldest runnable pending fetch_queue row per lane (0: none)",
    "aslms_job_last_success_timestamp": "start of the latest succeeded or partial job_runs row per job (unix time)",
    "aslms_job_running": "job_runs rows still running per job",
    "aslms_job_running_oldest_seconds": "age of the oldest running job_runs row per job (0: none)",
    "aslms_worker_last_pass_timestamp": "start of the latest queue-run pass (0: never)",
    "aslms_worker_alive_timestamp": (
        "the queue worker's liveness: the later of the latest queue-run pass start and the latest row it claimed "
        "(0: never)"
    ),
    "aslms_napix_calls_last_hour": "NAPIX calls in the last hour by outcome (ok, failed, renewal)",
    "aslms_napix_window_remaining": "calls left in the detected NAPIX window (NaN: not known)",
    "aslms_napix_switch_on": "1 when NAPIX_ENABLED is true in this process",
    "aslms_source_failures_open": "open source failures by kind",
    "aslms_notifications": "e-mail notifications by status",
    "aslms_mail_oldest_queued_seconds": "age of the oldest queued e-mail notification (0: none)",
    "aslms_sourcetrace_documents": "orders and uploads by SourceTrace status",
    "aslms_backup_last_success_timestamp": "end of the latest successful backup (unix time; 0: never)",
    "aslms_backup_last_size_bytes": "database dump size of the latest successful backup",
    "aslms_restore_check_last_success_timestamp": "end of the latest successful restore check (unix time; 0: never)",
    "aslms_disk_free_bytes": "free bytes on the file system of a path",
    "aslms_disk_total_bytes": "size in bytes of the file system of a path",
    "aslms_clamav_up": "1 when clamd answers VERSION",
    "aslms_clamav_signature_timestamp": "date of the loaded ClamAV signatures (unix time)",
    "aslms_probe_up": "1 when the target's health page answers 2xx",
    "aslms_tls_cert_expiry_timestamp": "expiry of the certificate the proxy serves (unix time)",
    "aslms_scrape_errors": "sections of the latest refresh that failed",
}


@dataclass(frozen=True)
class Sample:
    name: str
    labels: dict[str, str] = field(default_factory=dict)
    value: float = 0.0


def _ts(value: datetime | None) -> float:
    return value.timestamp() if value is not None else 0.0


def _age(now: datetime, value: datetime | None) -> float:
    return max(0.0, (now - value).total_seconds()) if value is not None else 0.0


def _v(x: Any) -> str:
    return str(x.value if hasattr(x, "value") else x)


# ------------------------------------------------------------------------------------------------ the database


def worker_alive_at(session: Session) -> datetime | None:
    """The queue worker's liveness (design pre-pilot-hardening, decision 4): the later of the latest `queue-run`
    start and the latest claimed `fetch_queue` row. A long pass claims rows for hours; `search_rows`
    (`queue.LOCAL_KINDS`) are claimed by the scheduler and do not count. One rule for the exporter and the System
    health screen (design `api-health-checker`, decision 16). None when the worker never ran."""
    from aslms.services import queue

    last_pass = session.scalar(select(func.max(JobRun.started_at)).where(JobRun.job == WORKER_PASS_JOB))
    last_claim = session.scalar(
        select(func.max(FetchQueueItem.started_at)).where(FetchQueueItem.kind.not_in(queue.LOCAL_KINDS))
    )
    return max((t for t in (last_pass, last_claim) if t is not None), default=None)


def collect_database(
    session: Session, settings: Settings, now: datetime | None = None
) -> tuple[list[Sample], dict[str, datetime]]:
    """Every database gauge in one read-only transaction under the statement timeout. Returns the samples and each
    job's last success (the backup gauges fall back to it)."""
    from aslms.services import data_health, napix_window, sourcetrace_ingest
    from aslms.services.job_repair import ALL_SETS
    from aslms.services.reporting_common import with_timeout

    now = now or datetime.now(UTC)
    session.execute(text("SET TRANSACTION READ ONLY"))
    with_timeout(session, settings.ops_metrics_statement_timeout_seconds)
    out: list[Sample] = []

    # the queue: every lane x kind x status (zeros included, so a series falls to 0 instead of vanishing)
    q = FetchQueueItem
    counts = {
        (_v(lane), _v(kind), _v(status)): int(n)
        for lane, kind, status, n in session.execute(
            select(q.lane, q.kind, q.status, func.count()).group_by(q.lane, q.kind, q.status)
        ).all()
    }
    for lane in FetchLane:
        for kind in FetchKind:
            for status in FetchStatus:
                n = counts.get((lane.value, kind.value, status.value), 0)
                out.append(
                    Sample(
                        "aslms_queue_rows",
                        {"lane": lane.value, "kind": kind.value, "status": status.value},
                        n,
                    )
                )
    runnable = (q.status == FetchStatus.PENDING) & or_(q.not_before.is_(None), q.not_before <= now)
    oldest = {
        _v(lane): at
        for lane, at in session.execute(
            select(q.lane, func.min(q.created_at)).where(runnable).group_by(q.lane)
        )
    }
    for lane in FetchLane:
        out.append(
            Sample(
                "aslms_queue_oldest_pending_seconds", {"lane": lane.value}, _age(now, oldest.get(lane.value))
            )
        )

    # jobs: one grouped pass over job_runs
    running = JobRun.status == JobStatus.RUNNING
    rows = session.execute(
        select(
            JobRun.job,
            func.max(JobRun.started_at).filter(JobRun.status.in_(SUCCESS)),
            func.count().filter(running),
            func.min(JobRun.started_at).filter(running),
            func.max(JobRun.started_at).filter(JobRun.job == WORKER_PASS_JOB),
        ).group_by(JobRun.job)
    ).all()
    known = set().union(*ALL_SETS.values())
    last_success: dict[str, datetime] = {}
    seen: set[str] = set()
    last_pass: datetime | None = None
    for job, ok_at, n_running, oldest_running, pass_at in rows:
        seen.add(job)
        if ok_at is not None:
            last_success[job] = ok_at
            out.append(Sample("aslms_job_last_success_timestamp", {"job": job}, _ts(ok_at)))
        out.append(Sample("aslms_job_running", {"job": job}, int(n_running)))
        out.append(Sample("aslms_job_running_oldest_seconds", {"job": job}, _age(now, oldest_running)))
        if pass_at is not None:
            last_pass = pass_at
    for job in sorted(known - seen):
        out.append(Sample("aslms_job_running", {"job": job}, 0))
        out.append(Sample("aslms_job_running_oldest_seconds", {"job": job}, 0))
    out.append(Sample("aslms_worker_last_pass_timestamp", {}, _ts(last_pass)))
    out.append(Sample("aslms_worker_alive_timestamp", {}, _ts(worker_alive_at(session))))

    # NAPIX: the last hour, the detected window, the switch
    # a token renewal's 401 step is its own series, so `failed` (and NapixErrorsHigh) leaves it out while ok + failed +
    # renewal stays every call (design followups-oct, decision 8)
    ok_n, failed_n, renewal_n = session.execute(
        select(
            func.count().filter(NapixCallLog.ok.is_(True)),
            func.count().filter(failed_call()),
            func.count().filter(NapixCallLog.ok.is_(False), renewal_step()),
        ).where(NapixCallLog.called_at >= now - timedelta(hours=1))
    ).one()
    out.append(Sample("aslms_napix_calls_last_hour", {"outcome": "ok"}, int(ok_n)))
    out.append(Sample("aslms_napix_calls_last_hour", {"outcome": "failed"}, int(failed_n)))
    out.append(Sample("aslms_napix_calls_last_hour", {"outcome": "renewal"}, int(renewal_n)))
    window = napix_window.current(session, settings, now)
    out.append(
        Sample(
            "aslms_napix_window_remaining", {}, float("nan") if window.remaining is None else window.remaining
        )
    )
    out.append(Sample("aslms_napix_switch_on", {}, 1 if settings.napix_enabled else 0))

    # source failures, mail, SourceTrace
    for row in data_health.failures(session):
        out.append(Sample("aslms_source_failures_open", {"kind": row["kind"]}, row["open"]))
    by_status = {
        _v(st): int(n)
        for st, n in session.execute(
            select(Notification.status, func.count())
            .where(Notification.channel == Channel.EMAIL)
            .group_by(Notification.status)
        ).all()
    }
    from aslms.domain.alerts import NotificationStatus

    for st in NotificationStatus:
        out.append(Sample("aslms_notifications", {"status": st.value}, by_status.get(st.value, 0)))
    mail = data_health.mail(session)
    out.append(Sample("aslms_mail_oldest_queued_seconds", {}, _age(now, mail["email_oldest_queued_at"])))
    for st, n in sourcetrace_ingest.status(session, settings)["counts"].items():
        out.append(Sample("aslms_sourcetrace_documents", {"status": st}, n))
    return out, last_success


# ------------------------------------------------------------------------------------------------ files and disks


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def collect_backups(backup_dir: str, job_success: dict[str, datetime] | None = None) -> list[Sample]:
    """The status files of the backup service; the later of the file and the `job_runs` success counts."""
    from aslms.services.backups import read_status

    job_success = job_success or {}
    last = read_status(backup_dir, "last-success") or {}
    backup_at = _parse_time(last.get("finished_at"))
    size = (last.get("counters") or {}).get("db_bytes") or 0
    check = read_status(backup_dir, "restore-check") or {}
    check_at = _parse_time(check.get("finished_at")) if check.get("status") == "succeeded" else None
    candidates_b = [t for t in (backup_at, job_success.get("backup")) if t is not None]
    candidates_r = [t for t in (check_at, job_success.get("restore_check")) if t is not None]
    return [
        Sample("aslms_backup_last_success_timestamp", {}, _ts(max(candidates_b)) if candidates_b else 0.0),
        Sample("aslms_backup_last_size_bytes", {}, float(size)),
        Sample(
            "aslms_restore_check_last_success_timestamp", {}, _ts(max(candidates_r)) if candidates_r else 0.0
        ),
    ]


def collect_disks(paths: Iterable[str]) -> list[Sample]:
    """Free and total bytes per path; a path that does not exist in this container is left out."""
    out = []
    for path in paths:
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        out.append(Sample("aslms_disk_free_bytes", {"path": path}, float(usage.free)))
        out.append(Sample("aslms_disk_total_bytes", {"path": path}, float(usage.total)))
    return out


# ------------------------------------------------------------------------------------------------ ClamAV


def parse_clamav_version(reply: str) -> datetime | None:
    """`ClamAV 1.5.4/27795/Sun Oct 18 08:26:03 2026` -> the signature date (clamd prints its local time, UTC in the
    official image). None when the reply carries no date (signatures not loaded yet)."""
    parts = reply.strip().split("/", 2)
    if len(parts) < 3:
        return None
    try:
        return datetime.strptime(" ".join(parts[2].split()), "%a %b %d %H:%M:%S %Y").replace(tzinfo=UTC)
    except ValueError:
        return None


def collect_clamav(settings: Settings, version: Callable[[], str] | None = None) -> list[Sample]:
    from aslms.services.scanner import ClamdScanner, ScannerUnavailable

    if version is None:
        version = ClamdScanner(
            settings.clamav_host, settings.clamav_port, settings.ops_probe_timeout_seconds
        ).version
    try:
        reply = version()
    except ScannerUnavailable:
        return [Sample("aslms_clamav_up", {}, 0)]
    out = [Sample("aslms_clamav_up", {}, 1)]
    signed = parse_clamav_version(reply)
    if signed is not None:
        out.append(Sample("aslms_clamav_signature_timestamp", {}, _ts(signed)))
    return out


# ------------------------------------------------------------------------------------------------ probes


@dataclass(frozen=True)
class TlsProbe:
    up: bool
    cert_expiry: datetime | None = None


def probe_tls(url: str, host_name: str, timeout: float) -> TlsProbe:
    """GET `url` over TLS with `host_name` as SNI and Host header (the proxy refuses other names). The internal CA is
    not in this container, so the chain is not verified; the probe checks that the portal answers, and the served
    certificate's expiry is read from the handshake."""
    from cryptography import x509

    parsed = urlparse(url)
    port = parsed.port or 443
    path = parsed.path or "/"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    expiry = None
    try:
        with socket.create_connection((parsed.hostname, port), timeout=timeout) as raw:
            with ctx.wrap_socket(raw, server_hostname=host_name) as tls:
                der = tls.getpeercert(binary_form=True)
                if der:
                    expiry = x509.load_der_x509_certificate(der).not_valid_after_utc
                tls.sendall(
                    f"GET {path} HTTP/1.1\r\nHost: {host_name}\r\nUser-Agent: aslms-ops-metrics\r\n"
                    "Connection: close\r\n\r\n".encode("ascii")
                )
                head = tls.recv(64).decode("latin-1", "replace")
    except (OSError, ssl.SSLError, ValueError):
        return TlsProbe(False, expiry)
    parts = head.split(" ", 2)
    up = len(parts) >= 2 and parts[1].isdigit() and 200 <= int(parts[1]) < 300
    return TlsProbe(up, expiry)


def probe_http(url: str, timeout: float) -> bool:
    try:
        return 200 <= httpx.get(url, timeout=timeout, follow_redirects=False).status_code < 300
    except httpx.HTTPError:
        return False


def collect_probes(
    settings: Settings,
    *,
    tls: Callable[[str, str, float], TlsProbe] = probe_tls,
    http: Callable[[str, float], bool] = probe_http,
) -> list[Sample]:
    out = []
    timeout = settings.ops_probe_timeout_seconds
    if settings.ops_probe_portal_url:
        host_name = urlparse(settings.portal_base_url).hostname or "localhost"
        result = tls(settings.ops_probe_portal_url, host_name, timeout)
        out.append(Sample("aslms_probe_up", {"target": "portal"}, 1 if result.up else 0))
        if result.cert_expiry is not None:
            out.append(Sample("aslms_tls_cert_expiry_timestamp", {}, _ts(result.cert_expiry)))
    for target, url in (("web", settings.ops_probe_web_url), ("api", settings.ops_probe_api_url)):
        if url:
            out.append(Sample("aslms_probe_up", {"target": target}, 1 if http(url, timeout) else 0))
    return out


# ------------------------------------------------------------------------------------------------ the collector


class OpsCollector:
    """A `prometheus_client` collector over the cached readings. `session_factory` builds sessions as
    `aslms_readonly`; `sections` replaces the non-database readings in tests."""

    def __init__(
        self,
        settings: Settings,
        session_factory: Callable[[], Session] | None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sections: list[Callable[[dict[str, datetime]], list[Sample]]] | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.clock = clock
        self.sections = sections if sections is not None else self._default_sections()
        self._lock = threading.Lock()
        self._cache: list[Sample] | None = None
        self._at = 0.0

    def _default_sections(self) -> list[Callable[[dict[str, datetime]], list[Sample]]]:
        s = self.settings
        paths = [p.strip() for p in s.ops_disk_paths.split(",") if p.strip()]
        return [
            lambda jobs: collect_backups(s.backup_dir, jobs),
            lambda jobs: collect_disks(paths),
            lambda jobs: collect_clamav(s),
            lambda jobs: collect_probes(s),
        ]

    def refresh(self) -> list[Sample]:
        out: list[Sample] = []
        errors = 0
        job_success: dict[str, datetime] = {}
        if self.session_factory is not None:
            try:
                with self.session_factory() as session:
                    try:
                        samples, job_success = collect_database(session, self.settings)
                    finally:
                        session.rollback()
                out.extend(samples)
            except Exception as exc:  # noqa: BLE001 — counted in aslms_scrape_errors, the rest still served
                errors += 1
                log.warning("ops metrics: database readings failed: %s", exc.__class__.__name__)
        for section in self.sections:
            try:
                out.extend(section(job_success))
            except Exception as exc:  # noqa: BLE001
                errors += 1
                log.warning("ops metrics: a section failed: %s", exc.__class__.__name__)
        out.append(Sample("aslms_scrape_errors", {}, errors))
        return out

    def samples(self) -> list[Sample]:
        with self._lock:
            now = self.clock()
            if self._cache is None or now - self._at >= self.settings.ops_metrics_cache_seconds:
                self._cache = self.refresh()
                self._at = now
            return self._cache

    def describe(self) -> list:
        return []  # registered without a reading; the first scrape reads

    def collect(self) -> Iterator:
        from prometheus_client.core import GaugeMetricFamily

        families: dict[str, Any] = {}
        for s in self.samples():
            keys = sorted(s.labels)
            fam = families.get(s.name)
            if fam is None:
                fam = families[s.name] = GaugeMetricFamily(s.name, HELP.get(s.name, s.name), labels=keys)
            fam.add_metric([s.labels[k] for k in keys], s.value)
        yield from families.values()


def registry_for(collector: OpsCollector):
    from prometheus_client import CollectorRegistry

    registry = CollectorRegistry(auto_describe=False)
    registry.register(collector)
    return registry


def render(collector: OpsCollector) -> str:
    """The exposition text, as Prometheus would read it."""
    from prometheus_client import generate_latest

    return generate_latest(registry_for(collector)).decode("utf-8")


def serve(settings: Settings, port: int, addr: str = "0.0.0.0") -> None:  # pragma: no cover — runs forever
    """`aslms ops metrics`: the exporter on `addr:port` until stopped."""
    from prometheus_client import start_http_server

    from aslms.db.session import get_sessionmaker

    collector = OpsCollector(settings, get_sessionmaker(settings.database_url_sync))
    start_http_server(port, addr=addr, registry=registry_for(collector))
    log.info("ops metrics on %s:%s", addr, port)
    while True:
        time.sleep(3600)
