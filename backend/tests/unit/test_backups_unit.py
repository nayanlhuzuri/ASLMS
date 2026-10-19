"""Design deployment-checklist, decisions 13 and 14: retention, the add-only store mirror, the password kept off the
command line, the restore refusals and the schedule."""

from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aslms.services import backups
from aslms.services.alert_rules import IST
from aslms.services.backups import BackupSet, RetentionPolicy, select_keep

URL = "postgresql+psycopg://aslms:S3cret-Pass-Word-1@db.internal:5432/aslms"
SECRET = "S3cret-Pass-Word-1"


# ------------------------------------------------------------------------------------------------ retention


def _series(now: datetime) -> list[BackupSet]:
    """Every 6 hours (00:30, 06:30, 12:30, 18:30) for 15 months up to `now`, plus pre-migrate sets."""
    sets = []
    t = (now - timedelta(days=460)).replace(hour=0, minute=30, second=0, microsecond=0)
    while t <= now:
        stamp = t.strftime("%Y%m%d-%H%M")
        sets.append(BackupSet(stamp, t, None))
        t += timedelta(hours=6)
    for days in (400, 200, 100, 50, 20, 10, 3):
        t = (now - timedelta(days=days)).replace(hour=11, minute=5, second=0, microsecond=0)
        stamp = t.strftime("%Y%m%d-%H%M")
        sets.append(BackupSet(f"{stamp}-pre-migrate", t, "pre-migrate"))
    return sets


def test_backup_select_keep():
    now = datetime(2026, 10, 19, 13, 0)  # a Monday, IST
    sets = _series(now)
    policy = RetentionPolicy()
    keep = select_keep(sets, now, policy)
    by_name = {s.name: s for s in sets}
    kept = [by_name[n] for n in keep]

    # everything of the last 48 hours
    recent = [s for s in sets if s.stamp >= now - timedelta(hours=48)]
    assert {s.name for s in recent} <= keep
    # the first scheduled set of each of the last 14 days
    for age in range(14):
        day = (now - timedelta(days=age)).date()
        first = min((s for s in sets if s.tag is None and s.stamp.date() == day), key=lambda s: s.stamp)
        assert first.name in keep
    # Sundays for 8 weeks, the 1st of the month for 12 months
    sundays = {s.stamp.date() for s in kept if s.tag is None and s.stamp.weekday() == 6}
    assert len([d for d in sundays if (now.date() - d).days < 56]) == 8
    firsts = {s.stamp.date() for s in kept if s.tag is None and s.stamp.day == 1}
    assert len(firsts) == 12
    assert min(firsts) == datetime(2025, 11, 1).date()
    # the last 5 pre-migrate sets only
    pre = sorted((s for s in kept if s.tag == "pre-migrate"), key=lambda s: s.stamp)
    assert len(pre) == 5 and pre[0].stamp.date() == (now - timedelta(days=100)).date()
    # nothing older than a year survives except nothing at all
    assert all(s.stamp >= now - timedelta(days=366) for s in kept)
    # a midday set of 20 days ago is pruned
    old_noon = (now - timedelta(days=20)).replace(hour=12, minute=30)
    assert old_noon.strftime("%Y%m%d-%H%M") not in keep


def test_backup_prune_never_touches_the_store(tmp_path):
    db = tmp_path / "db"
    db.mkdir()
    store = tmp_path / "store" / "ab"
    store.mkdir(parents=True)
    (store / ("ab" + "0" * 62 + ".pdf")).write_bytes(b"x")
    old = "20240101-0030"
    new = datetime.now(UTC).astimezone(IST).strftime("%Y%m%d-%H%M")
    for name in (old, new):
        for prefix, suffix in (("aslms-", ".dump"), ("roles-", ".sql"), ("manifest-", ".json")):
            (db / f"{prefix}{name}{suffix}").write_text("x")
    removed = backups.prune(tmp_path, None, RetentionPolicy())
    assert removed == [old]
    assert not (db / f"aslms-{old}.dump").exists() and not (db / f"roles-{old}.sql").exists()
    assert (db / f"aslms-{new}.dump").exists()
    assert len(list((tmp_path / "store").rglob("*.pdf"))) == 1


# ------------------------------------------------------------------------------------------------ store mirror


def _put(root: Path, data: bytes, ext: str = "pdf") -> Path:
    sha = hashlib.sha256(data).hexdigest()
    p = root / sha[:2] / f"{sha}.{ext}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_backup_mirror_is_add_only_and_verified(tmp_path):
    store, mirror = tmp_path / "store", tmp_path / "mirror"
    a = _put(store, b"order one")
    b = _put(store, b"order two")
    first = backups.mirror_store(store, mirror)
    assert (first.copied, first.bytes, first.bad) == (2, len(b"order one") + len(b"order two"), [])
    # a second run copies nothing, and an existing mirror file is never overwritten
    target = mirror / a.relative_to(store)
    target.write_bytes(b"kept as it is")
    second = backups.mirror_store(store, mirror)
    assert second.copied == 0 and second.present == 2
    assert target.read_bytes() == b"kept as it is"
    # a store file whose content does not match its name is reported and not copied
    bad = store / "cd" / ("cd" + "1" * 62 + ".pdf")
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"tampered")
    (store / "ef").mkdir()
    (store / "ef" / "not-a-hash.pdf").write_bytes(b"?")
    (store / "ef" / "partial.pdf.part").write_bytes(b"?")
    third = backups.mirror_store(store, mirror)
    assert third.copied == 0
    assert sorted(Path(p).name for p in third.bad) == sorted([bad.name, "not-a-hash.pdf"])
    assert not (mirror / bad.relative_to(store)).exists()
    assert not list(mirror.rglob("*.part"))
    assert (mirror / b.relative_to(store)).read_bytes() == b"order two"


# ------------------------------------------------------------------------------------------------ the password


class _Recorder:
    def __init__(self):
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, args, env=None, **kw):
        self.calls.append((list(args), dict(env or {})))
        if args[0] == "pg_dump" and "-f" in args:
            Path(args[args.index("-f") + 1]).write_bytes(b"PGDMP")
        if args[0] == "pg_dumpall":
            Path(args[args.index("-f") + 1]).write_text("CREATE ROLE x;")
        out = "pg_dump (PostgreSQL) 16.15" if "--version" in args else ""
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")


class _Conn:
    def __init__(self):
        self.statements = []

    def execution_options(self, **kw):
        return self

    def begin(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, stmt, params=None):
        self.statements.append(str(stmt))
        return self

    def scalar(self):
        last = self.statements[-1]
        if "pg_export_snapshot" in last:
            return "00000003-0000001B-1"
        if "to_regclass" in last:
            return True
        if "version_num" in last:
            return "0019"
        if "server_version" in last:
            return "16.15"
        return 7


class _Engine:
    def connect(self):
        return _Conn()

    def dispose(self):
        pass


def test_backup_never_passes_password_on_command_line(tmp_path, monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(backups, "_run", rec)
    monkeypatch.setattr(backups, "_engine", lambda url, database=None: _Engine())
    manifest = backups.dump(URL, tmp_path, "pre-migrate", now=datetime(2026, 10, 19, 1, 0, tzinfo=UTC))
    assert manifest.name == "20261019-0630-pre-migrate"
    assert manifest.revision == "0019" and manifest.row_counts["cases"] == 7
    tools = [args[0] for args, _ in rec.calls]
    assert tools == ["pg_dump", "pg_dumpall", "pg_dump", "pg_restore"]
    for args, env in rec.calls:
        assert all(SECRET not in a for a in args), args
        assert env["PGPASSWORD"] == SECRET and env["PGHOST"] == "db.internal" and env["PGUSER"] == "aslms"
    dump_args = rec.calls[0][0]
    assert "-Fc" in dump_args and "-Z" in dump_args and "--snapshot=00000003-0000001B-1" in dump_args
    assert "--roles-only" in rec.calls[1][0]
    assert (tmp_path / "db" / "manifest-20261019-0630-pre-migrate.json").exists()
    assert (tmp_path / "db" / "aslms-20261019-0630-pre-migrate.dump").exists()


def test_backup_tool_failure_never_leaks_the_password(monkeypatch):
    def failing(args, env=None, **kw):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr=f"FATAL: password {SECRET} rejected")

    monkeypatch.setattr(backups, "_run", failing)
    with pytest.raises(backups.BackupError) as exc:
        backups._tool(["pg_dump"], backups.PgTarget.from_url(URL), what="pg_dump")
    assert SECRET not in str(exc.value) and "exit 1" in str(exc.value)


def test_backup_refuses_bad_tag(tmp_path):
    with pytest.raises(backups.BackupError):
        backups.dump(URL, tmp_path, "Bad Tag!")


# ------------------------------------------------------------------------------------------------ restore refusals


def test_restore_check_refuses_other_names(tmp_path):
    for name in ("aslms", "postgres", "aslms_restore_check2", ""):
        with pytest.raises(backups.RestoreRefused):
            backups.restore_check(URL, tmp_path, tmp_path / "x.dump", scratch=name)
    backups.check_scratch_name("aslms_restore_check")


def test_restore_refuses_with_app_sessions(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(backups, "_run", lambda *a, **k: called.append(a))
    dump, roles = tmp_path / "aslms-x.dump", tmp_path / "roles-x.sql"
    dump.write_bytes(b"PGDMP")
    roles.write_text("")
    with pytest.raises(backups.RestoreRefused, match="aslms_app session"):
        backups.restore(URL, dump, roles, confirm_overwrite="aslms", sessions=lambda: 2)
    with pytest.raises(backups.RestoreRefused, match="confirm-overwrite"):
        backups.restore(URL, dump, roles, confirm_overwrite="other", sessions=lambda: 0)
    assert called == []


# ------------------------------------------------------------------------------------------------ the schedule


def test_backup_schedule_times():
    def ist(*a):
        return datetime(*a, tzinfo=IST)

    assert backups.next_backup_at(ist(2026, 10, 19, 0, 10), 6) == ist(2026, 10, 19, 0, 30)
    assert backups.next_backup_at(ist(2026, 10, 19, 0, 30), 6) == ist(2026, 10, 19, 6, 30)
    assert backups.next_backup_at(ist(2026, 10, 19, 19, 0), 6) == ist(2026, 10, 20, 0, 30)
    assert backups.next_backup_at(ist(2026, 10, 19, 1, 0), 1) == ist(2026, 10, 19, 1, 30)
    # Sunday 04:30 IST
    assert backups.next_restore_check_at(ist(2026, 10, 19, 9, 0)) == ist(2026, 10, 25, 4, 30)
    assert backups.next_restore_check_at(ist(2026, 10, 25, 4, 30)) == ist(2026, 11, 1, 4, 30)
    assert backups.next_restore_check_at(ist(2026, 10, 25, 4, 0)) == ist(2026, 10, 25, 4, 30)


def test_backup_status_files_and_failed_run(tmp_path, monkeypatch):
    monkeypatch.setattr(
        backups, "dump", lambda *a, **k: (_ for _ in ()).throw(backups.BackupError("pg_dump failed"))
    )
    recorded = []
    monkeypatch.setattr(backups, "_record_job", lambda *a: recorded.append(a))
    with pytest.raises(backups.BackupError):
        backups.run_backup(URL, tmp_path, tmp_path / "store", RetentionPolicy())
    last = backups.read_status(tmp_path, "last")
    assert last["status"] == "failed" and "pg_dump failed" in last["error"]
    assert backups.read_status(tmp_path, "last-success") is None
    assert recorded[0][1] == "backup" and recorded[0][3] == "failed"
    assert SECRET not in (tmp_path / "status" / "last.json").read_text()
