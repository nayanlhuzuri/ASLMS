"""Design deployment-checklist, Part A: the migration guard (decision 12), the job sets (18), the API documentation
(4), the superuser refusal (5), the start-up repairs (18) and the internal CA (7)."""

from __future__ import annotations

import ast
import ipaddress
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from fastapi.testclient import TestClient

from aslms.core.config import Settings
from aslms.services import db_guard, job_repair
from aslms.services.db_guard import DbState, classify, outcome

BACKEND = Path(__file__).resolve().parents[2]
KNOWN = {"0001", "0002", "0003"}


# ------------------------------------------------------------------------------------------------ db guard


def test_db_guard_states():
    assert classify(None, 0, "0003", KNOWN) is DbState.FRESH
    assert classify("0003", 40, "0003", KNOWN) is DbState.AT_HEAD
    assert classify("0002", 40, "0003", KNOWN) is DbState.BEHIND
    assert classify("0099", 40, "0003", KNOWN) is DbState.AHEAD
    assert classify(None, 5, "0003", KNOWN) is DbState.AHEAD  # tables without a revision


def test_db_guard_exit_codes_and_messages():
    fresh = outcome(DbState.FRESH, None, "0003")
    assert fresh.exit_code == 0
    at = outcome(DbState.AT_HEAD, "0003", "0003")
    assert at.exit_code == 0
    behind = outcome(DbState.BEHIND, "0002", "0003")
    assert behind.exit_code == 3
    assert behind.message == (
        "The database is at 0002; this build needs 0003. Stop the application and run: "
        "docker compose --profile ops run --rm migrate (it backs the database up first)."
    )
    ahead = outcome(DbState.AHEAD, "0099", "0003")
    assert ahead.exit_code == 4 and ahead.message.startswith("The database is newer than this build")


def test_db_guard_reads_this_builds_chain():
    head, known = db_guard.script_facts(db_guard.alembic_config("postgresql+psycopg://x@localhost/x"))
    assert head in known and "0001" in known


def test_db_guard_cli_exit_code(monkeypatch):
    from typer.testing import CliRunner

    from aslms.cli.main import app

    monkeypatch.setattr(db_guard, "guard", lambda url: outcome(DbState.BEHIND, "0018", "0019"))
    res = CliRunner().invoke(app, ["ops", "db-guard"])
    assert res.exit_code == 3 and "run --rm migrate" in res.output


# ------------------------------------------------------------------------------------------------ job sets


def _job_names() -> set[str]:
    """Every `JobRun(job=<literal or constant>)` and `job: str = "<default>"` in backend/aslms."""
    names: set[str] = set()
    consts: dict[str, str] = {}
    trees = []
    for path in (BACKEND / "aslms").rglob("*.py"):
        tree = ast.parse(path.read_text("utf-8"))
        trees.append(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for t in node.targets:
                    if isinstance(t, ast.Name) and (t.id == "JOB" or t.id.startswith("JOB_")):
                        if isinstance(node.value.value, str):
                            consts[t.id] = node.value.value
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "JobRun":
                for kw in node.keywords:
                    if kw.arg == "job":
                        if isinstance(kw.value, ast.Constant):
                            names.add(kw.value.value)
                        elif isinstance(kw.value, ast.Name) and kw.value.id in consts:
                            names.add(consts[kw.value.id])
            if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                args = node.args.kwonlyargs
                for arg, default in zip(args, node.args.kw_defaults):
                    if arg.arg == "job" and isinstance(default, ast.Constant):
                        names.add(default.value)
            # services/backups.py records its runs through _record_job(url, "<job>", ...)
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_record_job":
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                    names.add(node.args[1].value)
    names.update(v for k, v in consts.items() if k.startswith("JOB_") or k == "JOB")
    return {n for n in names if isinstance(n, str)}


def test_job_repair_sets_cover_every_job_name():
    names = _job_names()
    assert {"queue-run", "extract_text", "rescore", "backup", "restore_check"} <= names
    sets = [job_repair.WORKER_JOBS, job_repair.SCHEDULER_JOBS, job_repair.BACKUP_JOBS]
    for name in names:
        owners = [s for s in sets if name in s]
        assert len(owners) == 1, f"{name!r} must belong to exactly one start-up repair set"
    assert not (job_repair.WORKER_JOBS & job_repair.SCHEDULER_JOBS)
    assert not (job_repair.SCHEDULER_JOBS & job_repair.BACKUP_JOBS)


# ------------------------------------------------------------------------------------------------ docs and superuser


def _app(env: str):
    from aslms.api.main import create_app

    return create_app(
        Settings(_env_file=None, app_env=env, aslms_jwt_secret="s" * 40), session_factory=lambda: None
    )


@pytest.mark.parametrize("env", ["prod", "test"])
def test_api_docs_only_in_dev(env):
    app = _app(env)
    client = TestClient(app)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path
    assert app.openapi()["info"]["title"].startswith("ASLMS")
    dev = _app("dev")
    dev_client = TestClient(dev)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert dev_client.get(path).status_code == 200, path
    assert dev.openapi()["paths"]


class _FakeConn:
    def __init__(self, answer):
        self.answer = answer

    def execute(self, *_a, **_k):
        return self

    def scalar(self):
        return self.answer

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeEngine:
    def __init__(self, answer):
        self.answer = answer

    def connect(self):
        return _FakeConn(self.answer)

    def dispose(self):
        pass


def test_superuser_refused_in_prod(monkeypatch, capsys):
    monkeypatch.setattr(db_guard, "create_engine", lambda *a, **k: _FakeEngine(True))
    with pytest.raises(SystemExit) as exc:
        db_guard.refuse_superuser("postgresql+psycopg://x@h/d", is_prod=True)
    assert exc.value.code == 1
    assert db_guard.SUPERUSER_REFUSAL in capsys.readouterr().err
    db_guard.refuse_superuser("postgresql+psycopg://x@h/d", is_prod=False)  # never checked outside prod
    monkeypatch.setattr(db_guard, "create_engine", lambda *a, **k: _FakeEngine(False))
    db_guard.refuse_superuser("postgresql+psycopg://x@h/d", is_prod=True)


def test_api_lifespan_refuses_superuser_in_prod(monkeypatch):
    seen = []
    monkeypatch.setattr("aslms.api.main.refuse_superuser", lambda url, is_prod: seen.append(is_prod))
    with TestClient(_app("prod")):
        pass
    assert seen == [True]


# ------------------------------------------------------------------------------------------------ start-up repairs


def test_queue_worker_repairs_at_start(monkeypatch):
    from aslms.cli import pipeline

    calls = {}

    def fake_repair(factory, jobs, started, who):
        calls.update(jobs=jobs, who=who, started=started)
        return 2

    refused = []
    monkeypatch.setattr("aslms.services.job_repair.repair_at_start", fake_repair)
    monkeypatch.setattr(
        "aslms.services.db_guard.refuse_superuser", lambda url, is_prod: refused.append(is_prod)
    )
    monkeypatch.setattr(pipeline, "get_sessionmaker", lambda *a, **k: object())

    def stop(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(pipeline, "run_queue", stop)
    with pytest.raises(KeyboardInterrupt):
        pipeline.queue_worker(idle_seconds=0, max_items=None)
    assert calls["jobs"] == job_repair.WORKER_JOBS and calls["who"] == "queue-worker"
    assert len(refused) == 1  # the superuser check runs once, before the first pass


def test_scheduler_worker_ready_repairs(monkeypatch):
    from aslms.jobs import celery_app

    calls = {}
    monkeypatch.setattr(
        "aslms.services.job_repair.repair_at_start",
        lambda factory, jobs, started, who: calls.update(jobs=jobs, who=who, started=started),
    )
    monkeypatch.setattr("aslms.services.db_guard.refuse_superuser", lambda url, is_prod: None)
    monkeypatch.setattr(celery_app, "get_sessionmaker", lambda *a, **k: object())
    celery_app.on_worker_ready()
    assert calls["jobs"] == job_repair.SCHEDULER_JOBS
    assert calls["started"] == celery_app.PROCESS_STARTED_AT


def test_scheduler_worker_ready_exits_on_superuser(monkeypatch):
    from aslms.jobs import celery_app

    def refuse(url, is_prod):
        raise SystemExit(1)

    exits = []
    monkeypatch.setattr("aslms.services.db_guard.refuse_superuser", refuse)
    monkeypatch.setattr(
        celery_app.os, "_exit", lambda code: exits.append(code) or (_ for _ in ()).throw(SystemExit(code))
    )
    with pytest.raises(SystemExit):
        celery_app.on_worker_ready()
    assert exits == [1]


def test_repair_at_start_never_raises():
    def broken():
        raise RuntimeError("database down")

    assert job_repair.repair_at_start(broken, job_repair.WORKER_JOBS, datetime.now(UTC), "test") == 0


# ------------------------------------------------------------------------------------------------ internal CA


def test_make_cert_has_sans_and_validity(tmp_path):
    from aslms.services.certs import SERVER_DAYS, make_cert

    now = datetime(2026, 10, 19, tzinfo=UTC)
    files = make_cert("aslms-pilot", tmp_path, ["192.168.10.5"], now=now)
    pem = files.fullchain.read_bytes()
    certs = x509.load_pem_x509_certificates(pem)
    server, ca = certs[0], certs[1]
    sans = server.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert sans.get_values_for_type(x509.DNSName) == ["aslms-pilot"]
    assert sans.get_values_for_type(x509.IPAddress) == [ipaddress.ip_address("192.168.10.5")]
    assert server.not_valid_after_utc - server.not_valid_before_utc == timedelta(days=SERVER_DAYS, minutes=5)
    assert server.issuer == ca.subject
    assert ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is True
    ca.public_key().verify(server.signature, server.tbs_certificate_bytes, _ecdsa(server))
    assert files.privkey.read_bytes().startswith(b"-----BEGIN PRIVATE KEY-----")
    assert files.ca_key.exists() and files.ca_cert.exists()
    with pytest.raises(ValueError):
        make_cert("bad host", tmp_path / "x")


def _ecdsa(cert):
    from cryptography.hazmat.primitives.asymmetric import ec

    return ec.ECDSA(cert.signature_hash_algorithm)


# ------------------------------------------------------------------------------------------------ ops migrate


def _migrate_env(monkeypatch, sessions: int):
    from contextlib import contextmanager

    from aslms.services import backups

    calls: list = []
    settings = Settings(
        _env_file=None,
        aslms_migrate_url="postgresql+psycopg://owner:pw@db/aslms",
        backup_dir="b",
        storage_dir="s",
    )
    monkeypatch.setattr("aslms.cli.ops.get_settings", lambda: settings)
    monkeypatch.setattr(db_guard, "count_app_sessions", lambda url: sessions)
    revisions = iter(["0018", "0019"])
    monkeypatch.setattr(db_guard, "current_revision", lambda url: next(revisions))
    monkeypatch.setattr(
        backups,
        "run_backup",
        lambda url, bdir, sdir, policy, tag=None: (
            calls.append(("backup", tag)) or {"set": "20261019-0630-pre-migrate"}
        ),
    )
    monkeypatch.setattr(db_guard, "upgrade_head", lambda url: calls.append(("upgrade", url)))
    monkeypatch.setattr("aslms.cli.db.seed", lambda url=None: calls.append(("seed", url)))
    monkeypatch.setattr(
        db_guard,
        "write_migrated_audit",
        lambda s, before, after, backup: calls.append(("audit", before, after, backup)),
    )

    @contextmanager
    def fake_scope(url=None):
        yield object()

    monkeypatch.setattr("aslms.db.session.session_scope", fake_scope)
    return calls


def test_ops_migrate_backs_up_then_migrates_and_audits(monkeypatch):
    from typer.testing import CliRunner

    from aslms.cli.main import app

    calls = _migrate_env(monkeypatch, sessions=0)
    res = CliRunner().invoke(app, ["ops", "migrate"])
    assert res.exit_code == 0, res.output
    assert [c[0] for c in calls] == ["backup", "upgrade", "seed", "audit"]
    assert calls[0] == ("backup", "pre-migrate")
    assert calls[-1] == ("audit", "0018", "0019", "20261019-0630-pre-migrate")
    assert "pw" not in res.output.replace("pre-migrate", "")


def test_ops_migrate_refuses_while_the_app_is_connected(monkeypatch):
    from typer.testing import CliRunner

    from aslms.cli.main import app

    calls = _migrate_env(monkeypatch, sessions=3)
    res = CliRunner().invoke(app, ["ops", "migrate"])
    assert res.exit_code == 2 and "3 aslms_app session" in res.output
    assert calls == []
