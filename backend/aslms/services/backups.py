"""Backups, the restore check and the disaster restore (design deployment-checklist, decisions 13 and 14).

Every run of `backup` writes under `BACKUP_DIR`:
- `db/aslms-<YYYYMMDD-HHMM>[-<tag>].dump` (`pg_dump -Fc -Z 6`), `db/roles-<...>.sql` (`pg_dumpall --roles-only`, mode
  600: it holds password hashes) and `db/manifest-<...>.json` (times, revision, versions, size and sha256, row counts,
  the store's file count and size). The counts and the revision are read in the same snapshot `pg_dump` uses.
- `store/`: an add-only mirror of `STORAGE_DIR`, after the dump, so every file the dump refers to is mirrored. Store
  files are named by their sha256 and never change, so copying the missing ones is a complete copy; each copy is
  checked against its name and a file that does not match is reported, never copied.
- `status/last.json` and `status/last-success.json` (readable while the database is down), and a `job_runs` row.

Retention prunes dump sets only, never the store mirror. The password reaches `pg_dump`, `pg_dumpall`,
`pg_restore` and `psql` through `PGPASSWORD` in the child environment only, never on the command line."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from aslms.services.alert_rules import IST

log = logging.getLogger(__name__)

PREMIGRATE = "pre-migrate"
SCRATCH_DB = "aslms_restore_check"
DOCUMENT_SAMPLE = 50
STAMP_FORMAT = "%Y%m%d-%H%M"
DUMP_RE = re.compile(r"^aslms-(?P<stamp>\d{8}-\d{4})(?:-(?P<tag>[a-z0-9-]+))?\.dump$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
COUNTED_TABLES = (
    "cases",
    "causelist_entries",
    "orders",
    "documents",
    "case_notes",
    "custody_history",
    "case_ownership",
    "audit_log",
    "users",
    "offices",
)
CHUNK = 1024 * 1024

# replaced in tests; every external tool goes through this
Runner = Callable[..., subprocess.CompletedProcess]
_run: Runner = subprocess.run


class BackupError(RuntimeError):
    pass


class RestoreRefused(BackupError):
    pass


# ------------------------------------------------------------------------------------------------ connections


@dataclass(frozen=True)
class PgTarget:
    host: str
    port: int
    user: str
    password: str
    database: str

    @classmethod
    def from_url(cls, url: str) -> PgTarget:
        u = make_url(url)
        return cls(
            host=u.host or "localhost",
            port=int(u.port or 5432),
            user=u.username or "",
            password=u.password or "",
            database=u.database or "",
        )

    def env(self, database: str | None = None) -> dict[str, str]:
        """The child environment: libpq variables, the password among them; never the command line."""
        out = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
        out.update(
            {
                "PGHOST": self.host,
                "PGPORT": str(self.port),
                "PGUSER": self.user,
                "PGDATABASE": database or self.database,
            }
        )
        if self.password:
            out["PGPASSWORD"] = self.password
        return out


def _tool(args: list[str], target: PgTarget, *, database: str | None = None, what: str) -> str:
    """Runs one PostgreSQL client tool; a failure names the tool and its exit code, never a secret."""
    proc = _run(args, env=target.env(database), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()[-1:] or [""]
        detail_text = detail[0].replace(target.password, "***") if target.password else detail[0]
        raise BackupError(f"{what} failed (exit {proc.returncode}): {detail_text[:300]}")
    return proc.stdout or ""


def _engine(url: str, database: str | None = None):
    u = make_url(url)
    if database:
        u = u.set(database=database)
    return create_engine(u, poolclass=NullPool)


# ------------------------------------------------------------------------------------------------ files


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(data, indent=2, default=str, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def store_totals(store_dir: Path) -> tuple[int, int]:
    files = size = 0
    if store_dir.exists():
        for p in store_dir.rglob("*"):
            if p.is_file() and not p.name.endswith(".part"):
                files += 1
                size += p.stat().st_size
    return files, size


def set_name(stamp: str, tag: str | None) -> str:
    return f"{stamp}-{tag}" if tag else stamp


# ------------------------------------------------------------------------------------------------ dump


@dataclass
class Manifest:
    name: str
    started_at: str
    finished_at: str
    revision: str | None
    server_version: str
    pg_dump_version: str
    dump_file: str
    dump_bytes: int
    dump_sha256: str
    roles_file: str
    roles_bytes: int
    row_counts: dict[str, int]
    store_files: int
    store_bytes: int
    tag: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _counts(conn: Any) -> dict[str, int]:
    out = {}
    for table in COUNTED_TABLES:
        exists = conn.execute(text("SELECT to_regclass(:t) IS NOT NULL"), {"t": f"public.{table}"}).scalar()
        out[table] = int(conn.execute(text(f'SELECT count(*) FROM "{table}"')).scalar()) if exists else 0
    return out


def _revision(conn: Any) -> str | None:
    if not conn.execute(text("SELECT to_regclass('public.alembic_version') IS NOT NULL")).scalar():
        return None
    return conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()


def dump(
    url: str,
    backup_dir: str | Path,
    tag: str | None = None,
    *,
    store_dir: str | Path | None = None,
    now: datetime | None = None,
) -> Manifest:
    """One dump set: the database (in the snapshot the counts were read in), the roles and the manifest."""
    if tag is not None and not TAG_RE.match(tag):
        raise BackupError("a tag is 1-40 lower-case letters, digits or hyphens")
    target = PgTarget.from_url(url)
    started = now or datetime.now(UTC)
    stamp = started.astimezone(IST).strftime(STAMP_FORMAT)
    name = set_name(stamp, tag)
    db_dir = Path(backup_dir) / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    dump_path = db_dir / f"aslms-{name}.dump"
    roles_path = db_dir / f"roles-{name}.sql"
    part = dump_path.with_suffix(".dump.part")
    engine = _engine(url)
    try:
        # the counts, the revision and pg_dump share one snapshot (pg_dump --snapshot while this transaction is open)
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn, conn.begin():
            snapshot = conn.execute(text("SELECT pg_export_snapshot()")).scalar()
            revision = _revision(conn)
            counts = _counts(conn)
            server_version = str(conn.execute(text("SHOW server_version")).scalar())
            _tool(
                ["pg_dump", "-Fc", "-Z", "6", f"--snapshot={snapshot}", "-f", str(part)],
                target,
                what="pg_dump",
            )
    finally:
        engine.dispose()
    part.replace(dump_path)
    _tool(
        ["pg_dumpall", "--roles-only", "-f", str(roles_path)], target, database="postgres", what="pg_dumpall"
    )
    try:
        os.chmod(roles_path, 0o600)
    except OSError:  # pragma: no cover — a file system without modes
        pass
    version = _tool(["pg_dump", "--version"], target, what="pg_dump --version").strip()
    files, size = store_totals(Path(store_dir)) if store_dir else (0, 0)
    manifest = Manifest(
        name=name,
        started_at=started.isoformat(),
        finished_at=datetime.now(UTC).isoformat(),
        revision=revision,
        server_version=server_version,
        pg_dump_version=version,
        dump_file=dump_path.name,
        dump_bytes=dump_path.stat().st_size,
        dump_sha256=_sha256_file(dump_path),
        roles_file=roles_path.name,
        roles_bytes=roles_path.stat().st_size,
        row_counts=counts,
        store_files=files,
        store_bytes=size,
        tag=tag,
    )
    _write_json(db_dir / f"manifest-{name}.json", manifest.as_dict())
    _tool(["pg_restore", "--list", str(dump_path)], target, what="pg_restore --list")
    return manifest


# ------------------------------------------------------------------------------------------------ store mirror


@dataclass
class MirrorResult:
    copied: int = 0
    bytes: int = 0
    present: int = 0
    bad: list[str] = field(default_factory=list)


def mirror_store(store_dir: str | Path, mirror_dir: str | Path) -> MirrorResult:
    """Copies the store files missing from the mirror; an existing mirror file is never overwritten. A file whose
    content does not match its sha256 name is reported in `bad` and not copied."""
    src_root, dst_root = Path(store_dir), Path(mirror_dir)
    result = MirrorResult()
    if not src_root.exists():
        return result
    for src in sorted(p for p in src_root.rglob("*") if p.is_file()):
        if src.name.endswith(".part"):
            continue
        rel = src.relative_to(src_root)
        dst = dst_root / rel
        if dst.exists():
            result.present += 1
            continue
        stem = src.name.split(".", 1)[0]
        if not SHA_RE.match(stem):
            result.bad.append(str(rel))
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".part")
        h = hashlib.sha256()
        n = 0
        with src.open("rb") as fin, tmp.open("wb") as fout:
            for chunk in iter(lambda: fin.read(CHUNK), b""):
                h.update(chunk)
                fout.write(chunk)
                n += len(chunk)
        if h.hexdigest() != stem:
            tmp.unlink(missing_ok=True)
            result.bad.append(str(rel))
            continue
        tmp.replace(dst)
        result.copied += 1
        result.bytes += n
    if result.bad:
        log.warning("store mirror: %d file(s) do not match their names and were not copied", len(result.bad))
    return result


# ------------------------------------------------------------------------------------------------ retention


@dataclass(frozen=True)
class BackupSet:
    name: str
    stamp: datetime  # IST, naive local time from the file name
    tag: str | None


@dataclass(frozen=True)
class RetentionPolicy:
    recent_hours: int = 48
    daily: int = 14
    weekly: int = 8
    monthly: int = 12
    premigrate: int = 5

    @classmethod
    def from_settings(cls, s: Any) -> RetentionPolicy:
        return cls(
            recent_hours=s.backup_keep_recent_hours,
            daily=s.backup_keep_daily,
            weekly=s.backup_keep_weekly,
            monthly=s.backup_keep_monthly,
            premigrate=s.backup_keep_premigrate,
        )


def list_sets(backup_dir: str | Path) -> list[BackupSet]:
    out = []
    db_dir = Path(backup_dir) / "db"
    if not db_dir.exists():
        return out
    for p in db_dir.iterdir():
        m = DUMP_RE.match(p.name)
        if not m:
            continue
        stamp = datetime.strptime(m["stamp"], STAMP_FORMAT)
        out.append(BackupSet(set_name(m["stamp"], m["tag"]), stamp, m["tag"]))
    return sorted(out, key=lambda s: (s.stamp, s.name))


def _first_per_day(sets: Iterable[BackupSet]) -> dict[date, BackupSet]:
    firsts: dict[date, BackupSet] = {}
    for s in sorted(sets, key=lambda s: s.stamp):
        firsts.setdefault(s.stamp.date(), s)
    return firsts


def select_keep(sets: list[BackupSet], now: datetime, policy: RetentionPolicy) -> set[str]:
    """The names of the sets to keep (pure). `now` is IST local time (naive) like the stamps.
    Kept: every set of the last `recent_hours`; the first scheduled set of each of the last `daily` days, of each
    Sunday of the last `weekly` weeks and of the 1st of each of the last `monthly` months; the last `premigrate`
    pre-migrate sets."""
    keep = {s.name for s in sets if s.stamp >= now - timedelta(hours=policy.recent_hours)}
    today = now.date()
    firsts = _first_per_day(s for s in sets if s.tag is None)
    for day, s in firsts.items():
        age = (today - day).days
        if 0 <= age < policy.daily:
            keep.add(s.name)
        if day.weekday() == 6 and 0 <= age < policy.weekly * 7:
            keep.add(s.name)
        months = (today.year - day.year) * 12 + (today.month - day.month)
        if day.day == 1 and 0 <= months < policy.monthly:
            keep.add(s.name)
    pre = sorted((s for s in sets if s.tag == PREMIGRATE), key=lambda s: s.stamp)
    if policy.premigrate > 0:
        keep.update(s.name for s in pre[-policy.premigrate :])
    return keep


def prune(backup_dir: str | Path, now: datetime | None, policy: RetentionPolicy) -> list[str]:
    """Deletes the dump, roles and manifest files of the sets `select_keep` drops; never the store mirror."""
    now_ist = (now or datetime.now(UTC)).astimezone(IST).replace(tzinfo=None)
    sets = list_sets(backup_dir)
    keep = select_keep(sets, now_ist, policy)
    db_dir = Path(backup_dir) / "db"
    removed = []
    for s in sets:
        if s.name in keep:
            continue
        for prefix, suffix in (("aslms-", ".dump"), ("roles-", ".sql"), ("manifest-", ".json")):
            (db_dir / f"{prefix}{s.name}{suffix}").unlink(missing_ok=True)
        removed.append(s.name)
    return removed


# ------------------------------------------------------------------------------------------------ status and job rows


def write_status(backup_dir: str | Path, name: str, data: dict[str, Any]) -> None:
    _write_json(Path(backup_dir) / "status" / f"{name}.json", data)


def read_status(backup_dir: str | Path, name: str) -> dict[str, Any] | None:
    path = Path(backup_dir) / "status" / f"{name}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _record_job(
    url: str, job: str, started: datetime, status: str, counters: dict, error: str | None
) -> None:
    """One `job_runs` row in the database; a database that cannot be reached is logged (the status files remain)."""
    from aslms.db.session import session_scope
    from aslms.domain.ops import JobRun, JobStatus

    try:
        with session_scope(url) as s:
            s.add(
                JobRun(
                    job=job,
                    run_date=started.astimezone(IST).date(),
                    started_at=started,
                    finished_at=datetime.now(UTC),
                    status=JobStatus(status),
                    counters=counters,
                    error=error,
                )
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("job_runs row for %s not written: %s", job, exc.__class__.__name__)


def run_backup(
    url: str, backup_dir: str | Path, store_dir: str | Path, policy: RetentionPolicy, tag: str | None = None
) -> dict[str, Any]:
    """A whole backup run: dump set, store mirror, retention, status files and the `job_runs` row."""
    started = datetime.now(UTC)
    t0 = time.monotonic()
    status, error, counters = "succeeded", None, {}
    manifest = None
    try:
        manifest = dump(url, backup_dir, tag, store_dir=store_dir, now=started)
        mirror = mirror_store(store_dir, Path(backup_dir) / "store")
        pruned = prune(backup_dir, None, policy)
        counters = {
            "db_bytes": manifest.dump_bytes,
            "roles_bytes": manifest.roles_bytes,
            "store_files_copied": mirror.copied,
            "store_bytes_copied": mirror.bytes,
            "store_files_bad": len(mirror.bad),
            "pruned_sets": len(pruned),
        }
        if mirror.bad:
            status = "partial"
    except Exception as exc:  # noqa: BLE001 — recorded, never a secret (BackupError scrubs the password)
        status, error = "failed", f"{exc.__class__.__name__}: {exc}"[:2000]
    counters["seconds"] = round(time.monotonic() - t0, 1)
    record = {
        "job": "backup",
        "status": status,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "set": manifest.name if manifest else None,
        "revision": manifest.revision if manifest else None,
        "counters": counters,
        "error": error,
    }
    write_status(backup_dir, "last", record)
    if status != "failed":
        write_status(backup_dir, "last-success", record)
    _record_job(url, "backup", started, status, counters, error)
    if status == "failed":
        raise BackupError(error or "backup failed")
    return record


# ------------------------------------------------------------------------------------------------ restore check


@dataclass
class RestoreCheckResult:
    dump: str
    revision: str | None
    tables_compared: int = 0
    mismatches: list[str] = field(default_factory=list)
    files_checked: int = 0
    files_bad: int = 0
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.mismatches and self.files_bad == 0


def latest_dump(backup_dir: str | Path) -> Path:
    sets = list_sets(backup_dir)
    if not sets:
        raise BackupError("no dump in BACKUP_DIR/db")
    return Path(backup_dir) / "db" / f"aslms-{sets[-1].name}.dump"


def _manifest_for(dump_path: Path) -> dict[str, Any] | None:
    name = dump_path.name.removeprefix("aslms-").removesuffix(".dump")
    path = dump_path.with_name(f"manifest-{name}.json")
    return json.loads(path.read_text("utf-8")) if path.exists() else None


def check_scratch_name(name: str) -> None:
    if name != SCRATCH_DB:
        raise RestoreRefused(f"the restore check uses only the scratch database {SCRATCH_DB}")


def _recreate_database(url: str, name: str) -> None:
    from psycopg import sql

    engine = _engine(url, "postgres")
    try:
        raw = engine.raw_connection()
        try:
            raw.driver_connection.autocommit = True
            with raw.driver_connection.cursor() as cur:
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        finally:
            raw.close()
    finally:
        engine.dispose()


def _drop_database(url: str, name: str) -> None:
    from psycopg import sql

    engine = _engine(url, "postgres")
    try:
        raw = engine.raw_connection()
        try:
            raw.driver_connection.autocommit = True
            with raw.driver_connection.cursor() as cur:
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        finally:
            raw.close()
    finally:
        engine.dispose()


def restore_check(
    url: str,
    backup_dir: str | Path,
    dump_file: str | Path | None = None,
    *,
    scratch: str = SCRATCH_DB,
    sample: int = DOCUMENT_SAMPLE,
) -> RestoreCheckResult:
    """Restores a dump (the latest by default) into the scratch database, compares the revision and the manifest's row
    counts, checks `sample` random documents against the store mirror, drops the scratch database, and records a
    `job_runs` row `restore_check` and `status/restore-check.json`."""
    check_scratch_name(scratch)
    started = datetime.now(UTC)
    t0 = time.monotonic()
    path = Path(dump_file) if dump_file else latest_dump(backup_dir)
    result = RestoreCheckResult(dump=path.name, revision=None)
    error = None
    try:
        manifest = _manifest_for(path) or {}
        target = PgTarget.from_url(url)
        _recreate_database(url, scratch)
        try:
            _tool(
                ["pg_restore", "--exit-on-error", "--no-owner", "-d", scratch, str(path)],
                target,
                database=scratch,
                what="pg_restore",
            )
            engine = _engine(url, scratch)
            try:
                with engine.connect() as conn:
                    result.revision = _revision(conn)
                    if manifest.get("revision") != result.revision:
                        result.mismatches.append(
                            f"revision: manifest {manifest.get('revision')}, restored {result.revision}"
                        )
                    counts = _counts(conn)
                    for table, expected in (manifest.get("row_counts") or {}).items():
                        result.tables_compared += 1
                        if counts.get(table) != expected:
                            result.mismatches.append(
                                f"{table}: manifest {expected}, restored {counts.get(table)}"
                            )
                    rows = conn.execute(
                        text("SELECT sha256, storage_key FROM documents ORDER BY random() LIMIT :n"),
                        {"n": sample},
                    ).all()
            finally:
                engine.dispose()
            mirror = Path(backup_dir) / "store"
            for sha, key in rows:
                result.files_checked += 1
                f = mirror / key
                if not f.exists() or _sha256_file(f) != sha:
                    result.files_bad += 1
        finally:
            _drop_database(url, scratch)
    except Exception as exc:  # noqa: BLE001
        error = f"{exc.__class__.__name__}: {exc}"[:2000]
    result.seconds = round(time.monotonic() - t0, 1)
    status = "failed" if error or not result.ok else "succeeded"
    counters = {
        "revision": result.revision,
        "tables_compared": result.tables_compared,
        "mismatches": len(result.mismatches),
        "files_checked": result.files_checked,
        "files_bad": result.files_bad,
        "seconds": result.seconds,
    }
    write_status(
        backup_dir,
        "restore-check",
        {
            "status": status,
            "dump": result.dump,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "counters": counters,
            "mismatches": result.mismatches,
            "error": error,
        },
    )
    _record_job(
        url, "restore_check", started, status, counters, error or "; ".join(result.mismatches) or None
    )
    if error:
        raise BackupError(error)
    return result


# ------------------------------------------------------------------------------------------------ disaster restore


def restore(
    url: str,
    dump_file: str | Path,
    roles_file: str | Path,
    *,
    confirm_overwrite: str,
    store_from: str | Path | None = None,
    store_dir: str | Path | None = None,
    sessions: Callable[[], int] | None = None,
) -> dict[str, Any]:
    """Decision 14: roles, then the database recreated from the dump, then the store from the mirror (add-only), then
    the audit row `system.restored` in the restored database. Refused unless `confirm_overwrite` names the database,
    and while any `aslms_app` session is connected."""
    from aslms.services import db_guard

    target = PgTarget.from_url(url)
    if confirm_overwrite != target.database:
        raise RestoreRefused(f"--confirm-overwrite must name the database ({target.database})")
    count = sessions() if sessions else db_guard.count_app_sessions(url)
    if count:
        raise RestoreRefused(
            f"{count} aslms_app session(s) are connected; stop api, worker, scheduler and pgbouncer first"
        )
    dump_path, roles_path = Path(dump_file), Path(roles_file)
    for p in (dump_path, roles_path):
        if not p.exists():
            raise RestoreRefused(f"{p.name} does not exist")
    _tool(["psql", "-q", "-f", str(roles_path)], target, database="postgres", what="psql (roles)")
    _recreate_database(url, target.database)
    _tool(["pg_restore", "--exit-on-error", "-d", target.database, str(dump_path)], target, what="pg_restore")
    mirror = None
    if store_from and store_dir:
        mirror = mirror_store(store_from, store_dir)
    manifest = _manifest_for(dump_path) or {}
    from aslms.db.session import session_scope
    from aslms.services.audit import Actor, write_audit

    with session_scope(url) as s:
        write_audit(
            s,
            Actor.system("ops"),
            "system.restored",
            "database",
            None,
            after={"dump": dump_path.name, "revision": manifest.get("revision")},
        )
    return {
        "dump": dump_path.name,
        "revision": manifest.get("revision"),
        "store_files_copied": mirror.copied if mirror else 0,
        "store_files_bad": len(mirror.bad) if mirror else 0,
    }


# ------------------------------------------------------------------------------------------------ the scheduler


def next_backup_at(now: datetime, interval_hours: int) -> datetime:
    """The next minute 30 of an hour divisible by `interval_hours`, IST, strictly after `now`."""
    local = now.astimezone(IST)
    candidate = local.replace(minute=30, second=0, microsecond=0)
    for _ in range(0, 49):
        if candidate > local and candidate.hour % interval_hours == 0:
            return candidate
        candidate += timedelta(hours=1)
    raise AssertionError("no backup slot within two days")  # pragma: no cover


def next_restore_check_at(now: datetime) -> datetime:
    """The next Sunday 04:30 IST strictly after `now`."""
    local = now.astimezone(IST)
    candidate = local.replace(hour=4, minute=30, second=0, microsecond=0)
    while candidate <= local or candidate.weekday() != 6:
        candidate += timedelta(days=1)
    return candidate


def scheduler_loop(settings: Any, *, sleep: Callable[[float], None] = time.sleep, once: bool = False) -> None:
    """The `backup` service: repairs its own interrupted `job_runs` rows, then runs the backups and the weekly restore
    check at their times, for ever (`once` stops after the first due run, for tests)."""
    from aslms.db.session import get_sessionmaker
    from aslms.services.job_repair import BACKUP_JOBS, repair_at_start

    url = settings.migrate_url
    started = datetime.now(UTC)
    repair_at_start(get_sessionmaker(url), BACKUP_JOBS, started, "backup scheduler")
    policy = RetentionPolicy.from_settings(settings)
    log.info("backup scheduler started; backups every %d h at minute 30 IST", settings.backup_interval_hours)
    while True:
        now = datetime.now(UTC)
        nb = next_backup_at(now, settings.backup_interval_hours)
        nr = next_restore_check_at(now)
        due = min(nb, nr)
        sleep(max(0.0, (due - now).total_seconds()))
        try:
            if due == nr:
                restore_check(url, settings.backup_dir)
            else:
                run_backup(url, settings.backup_dir, settings.storage_dir, policy)
        except Exception as exc:  # noqa: BLE001 — recorded by the run itself; the loop carries on
            log.error("scheduled %s failed: %s", "restore check" if due == nr else "backup", exc)
        if once:
            return
