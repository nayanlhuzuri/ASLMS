"""`admin.service_health` through `aslms seed` (design `api-health-checker`, decision 1) and the read-only CLI
`aslms system-health` (decision 18): it prints the cards and the services, never calls NAPIX and exits 2 with a
service down."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import sqlalchemy as sa
from typer.testing import CliRunner

from aslms.core.config import Settings
from aslms.domain.ops import NapixCallLog
from aslms.domain.org import RolePermission
from aslms.domain.reference import Permission, Role
from aslms.services import access, service_checks
from aslms.services.access_seed import DEFAULT_MATRIX, PERMISSION_LABELS


def test_seed_adds_admin_service_health_disabled_for_every_type(world):
    with world.Session() as s:
        label = s.execute(
            sa.text("SELECT label, description FROM ref_permission WHERE code = 'admin.service_health'")
        ).one()
        assert label == PERMISSION_LABELS[Permission.ADMIN_SERVICE_HEALTH]
        assert label[0] == "System health"
        rows = s.scalars(
            sa.select(RolePermission).where(RolePermission.permission == Permission.ADMIN_SERVICE_HEALTH)
        ).all()
        assert len(rows) == len(DEFAULT_MATRIX) and not any(r.is_enabled for r in rows)
        assert all(Permission.ADMIN_SERVICE_HEALTH not in perms for perms in DEFAULT_MATRIX.values())


def test_super_admin_holds_admin_service_health(world):
    with world.Session() as s:
        assert access.has(s, world.user(s, "root"), Permission.ADMIN_SERVICE_HEALTH)
        for key in ("central_op", "oversight", "edu_admin", "edu_auditor"):
            assert not access.has(s, world.user(s, key), Permission.ADMIN_SERVICE_HEALTH), key
        assert Permission.ADMIN_SERVICE_HEALTH in access.role_functions(s, Role.SUPER_ADMIN)


def _probes(clamav_down: bool) -> service_checks.Probes:
    usage = SimpleNamespace(free=500 * 1024**3, total=1000 * 1024**3)

    def clamav(_s):
        if clamav_down:
            raise ConnectionRefusedError("refused")
        return f"ClamAV 1.5.4/1/{datetime.now(UTC).strftime('%a %b %d %H:%M:%S %Y')}"

    return service_checks.Probes(
        redis=lambda s: {"ping_ms": 1, "version": "7.4", "used": 1, "max": 0},
        pg_direct=lambda h, p, t: "N",
        clamav=clamav,
        web=lambda u, t: True,
        store=lambda p: None,
        disk=lambda p: usage,
        db_head=lambda s: None,
    )


def test_system_health_cli_prints_and_never_calls_napix(world, monkeypatch, tmp_path):
    from aslms.cli import system_health as cli

    @contextmanager
    def scope():
        s = world.Session()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    with world.Session() as s:
        s.add(
            NapixCallLog(
                api="hc-state-api/state",
                params_sha256="0" * 64,
                ok=True,
                duration_ms=420,
                called_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        s.commit()
        calls = s.scalar(sa.select(sa.func.count()).select_from(NapixCallLog))
    cfg = Settings(_env_file=None, app_env="test", redis_url=None, storage_dir=str(tmp_path))
    monkeypatch.setattr(cli, "session_scope", scope)
    monkeypatch.setattr(cli, "get_settings", lambda: cfg)
    import typer

    app = typer.Typer()
    app.command("system-health")(cli.system_health_cmd)
    app.command("other")(lambda: None)
    runner = CliRunner()

    monkeypatch.setattr(service_checks, "default_probes", lambda: _probes(clamav_down=True))
    r = runner.invoke(app, ["system-health"])
    assert r.exit_code == 2, r.output
    assert "High Courts list" in r.output and "Working" in r.output and "median 420 ms" in r.output
    assert "Virus scanner" in r.output and "Not working" in r.output
    assert "Court calls switched off" in r.output

    monkeypatch.setattr(service_checks, "default_probes", lambda: _probes(clamav_down=False))
    r = runner.invoke(app, ["system-health", "--json"])
    body = json.loads(r.output)
    assert {x["key"] for x in body["services"]} == set(service_checks.ORDER)
    assert len([c for g in body["court"]["groups"] for c in g["cards"]]) == 17
    assert r.exit_code == (2 if any(x["status"] == "down" for x in body["services"]) else 0)
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(NapixCallLog)) == calls


def test_system_health_token_prints_no_secret_and_never_calls(world, monkeypatch, tmp_path):
    """`aslms system-health --token` (design `system-health-inspector`): the token's state from the shared store, its
    metadata and the call log; no call, no token request, never the token value."""
    from aslms.cli import system_health as cli
    from aslms.integration.napix.client import TokenCache, TokenRenewal
    from tests.redis_stub import RedisStub

    @contextmanager
    def scope():
        s = world.Session()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    redis = RedisStub()
    cache = TokenCache(redis_client=redis)
    cache.set("token-value-zq99", 1800)
    cache.note_request(
        TokenRenewal(ok=True, http_status=200, error_family=None, duration_ms=90, expires_in=3600)
    )
    with world.Session() as s:
        s.add(
            NapixCallLog(
                api="hc-cnr-api/CNR",
                params_sha256="0" * 64,
                ok=True,
                http_status=200,
                duration_ms=420,
                called_at=datetime.now(UTC) + timedelta(seconds=1),
            )
        )
        s.commit()
        calls = s.scalar(sa.select(sa.func.count()).select_from(NapixCallLog))
    cfg = Settings(
        _env_file=None,
        app_env="test",
        redis_url=None,
        storage_dir=str(tmp_path),
        napix_client_secret="client-secret-zq98",
        napix_dept_id="dept-id-zq97",
    )
    monkeypatch.setattr(cli, "session_scope", scope)
    monkeypatch.setattr(cli, "get_settings", lambda: cfg)
    monkeypatch.setattr(cli, "_token_cache", lambda settings: TokenCache(redis_client=redis))

    def refuse(*a, **k):
        raise AssertionError("the CLI made a court call")

    monkeypatch.setattr("aslms.integration.napix.client.NapixClient.token", refuse)
    import typer

    app = typer.Typer()
    app.command("system-health")(cli.system_health_cmd)
    app.command("other")(lambda: None)
    runner = CliRunner()
    r = runner.invoke(app, ["system-health", "--token"])
    assert r.exit_code == 0, r.output
    assert "Access token: Working (ok)" in r.output  # held, though the switch is off on this server
    assert "Held: valid for 30 more minutes" in r.output
    assert "Case details by CNR, HTTP 200" in r.output and "Token requests today: 1" in r.output
    r2 = runner.invoke(app, ["system-health", "--token", "--json"])
    assert r2.exit_code == 0 and json.loads(r2.output)["held"] is True
    for out in (r.output, r2.output):
        for secret in ("token-value-zq99", "client-secret-zq98", "dept-id-zq97"):
            assert secret not in out
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(NapixCallLog)) == calls
