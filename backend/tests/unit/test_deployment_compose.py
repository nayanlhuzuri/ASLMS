"""Design deployment-checklist, Part A: the Compose files (decisions 2, 3, 6, 11, 12, 13, 15, 16, 21), parsed as YAML."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
REQUIRED = (
    "POSTGRES_PASSWORD",
    "ASLMS_APP_PASSWORD",
    "REDIS_PASSWORD",
    "PORTAL_BASE_URL",
    # Part B (row 77)
    "ASLMS_READONLY_PASSWORD",
    "GRAFANA_ADMIN_PASSWORD",
    "FLOWER_BASIC_AUTH",
)
OPS_SERVICES = {"init", "migrate", "backup"}
# Part B (decision 22): the monitoring screens, on the host's loopback only
MONITORING_PORTS = {
    "grafana": "127.0.0.1:3001:3000",
    "prometheus": "127.0.0.1:9090:9090",
    "alertmanager": "127.0.0.1:9093:9093",
    "flower": "127.0.0.1:5555:5555",
}


def _text(name: str = "compose.yml") -> str:
    return (ROOT / name).read_text("utf-8")


def _compose(name: str = "compose.yml") -> dict:
    return yaml.safe_load(_text(name))


def _services(name: str = "compose.yml") -> dict:
    return _compose(name)["services"]


def _env(service: dict) -> dict:
    env = service.get("environment") or {}
    if isinstance(env, list):
        return dict(e.split("=", 1) if "=" in e else (e, "") for e in env)
    return env


def test_compose_publishes_only_the_proxy():
    """Only the proxy is reachable from the network; Part B's monitoring screens bind 127.0.0.1 only."""
    services = _services()
    published = {name for name, svc in services.items() if svc.get("ports")}
    assert published == {"proxy"} | set(MONITORING_PORTS)
    ports = services["proxy"]["ports"]
    assert any(p.endswith(":443") for p in ports) and any(p.endswith(":80") for p in ports)
    for name, port in MONITORING_PORTS.items():
        assert services[name]["ports"] == [port], name
        assert all(str(p).startswith("127.0.0.1:") for p in services[name]["ports"]), name


def test_compose_dev_override_binds_loopback_only():
    services = _services("compose.dev.yml")
    ports = [p for svc in services.values() for p in svc.get("ports", [])]
    assert ports, "the dev override publishes postgres, api and web"
    assert all(str(p).startswith("127.0.0.1:") for p in ports)
    assert "redis" not in services or not services["redis"].get("ports")
    assert services["web"]["environment"]["TRUST_PROXY_HEADERS"] == "false"
    assert set(name for name, svc in services.items() if svc.get("ports")) == {"postgres", "api", "web"}


def test_compose_required_secrets_have_no_default():
    text = _text()
    for name in REQUIRED:
        refs = re.findall(r"\$\{" + name + r"([^}]*)\}", text)
        assert refs, f"{name} is used"
        assert all(r.startswith(":?") for r in refs), f"{name} must use ${{{name}:?...}} everywhere"
    # no password has a default; an empty one (the optional SMTP relay password) is no default
    assert not re.search(r"PASSWORD[A-Z_]*:-[^}]", text), "no password has a default"
    assert ":-aslms}@" not in text


def test_compose_redis_password_and_no_persistence():
    services = _services()
    redis = services["redis"]
    cmd = redis["command"]
    assert cmd[cmd.index("--requirepass") + 1] == "${REDIS_PASSWORD:?set REDIS_PASSWORD in .env}"
    assert cmd[cmd.index("--save") + 1] == ""
    assert cmd[cmd.index("--appendonly") + 1] == "no"
    assert "volumes" not in redis
    assert "redisdata_v3" not in (_compose().get("volumes") or {})
    assert "REDISCLI_AUTH" in redis["environment"]
    for name, svc in services.items():
        url = _env(svc).get("REDIS_URL")
        if url is not None:
            assert url.startswith("redis://:${REDIS_PASSWORD:?"), name


def test_compose_init_guards_instead_of_migrating():
    services = _services()
    init = services["init"]["command"]
    for part in ("ops preflight", "ops db-guard", "seed", "db-roles"):
        assert part in init
    assert "alembic upgrade" not in init
    migrate = services["migrate"]
    assert migrate["profiles"] == ["ops"]
    assert "ops migrate" in migrate["command"] and "ops preflight" in migrate["command"]


def test_compose_owner_url_only_in_ops_services():
    for name, svc in _services().items():
        env = _env(svc)
        migrate_url = env.get("ASLMS_MIGRATE_URL")
        owner_pw = env.get("POSTGRES_PASSWORD")
        if name in OPS_SERVICES:
            assert migrate_url, name
            continue
        assert not migrate_url, f"{name} must not receive the owner URL"
        if name != "postgres":
            assert not owner_pw, f"{name} must not receive the cluster superuser's password"
        url = env.get("DATABASE_URL_SYNC")
        if url:
            # the operations exporter reads as aslms_readonly (Part B, decision 23); the rest serve as aslms_app
            role = "aslms_readonly" if name == "ops-exporter" else "aslms_app"
            assert url.startswith(f"postgresql+psycopg://{role}:"), name
    # the services that read .env get the owner's values blanked
    for name in ("api", "worker", "scheduler"):
        env = _env(_services()[name])
        assert env["POSTGRES_PASSWORD"] == "" and env["ASLMS_MIGRATE_URL"] == ""


def test_compose_logging_and_hardening():
    for name, svc in _services().items():
        assert svc["logging"]["driver"] == "json-file", name
        assert svc["logging"]["options"] == {"max-size": "20m", "max-file": "5"}, name
        assert "no-new-privileges:true" in svc["security_opt"], name
        image = svc.get("image")
        if image:
            tag = image.rsplit(":", 1)[1] if ":" in image else "latest"
            assert tag not in {"latest", "stable"} and re.search(r"\d", tag), f"{name}: pin {image}"
    for name in ("api", "worker", "scheduler", "web", "backup", "migrate", "pgbouncer", *MONITORED_HARDENED):
        assert _services()[name]["cap_drop"] == ["ALL"], name


MONITORED_HARDENED = (
    "prometheus",
    "alertmanager",
    "grafana",
    "flower",
    "postgres-exporter",
    "redis-exporter",
    "pgbouncer-exporter",
    "ops-exporter",
    "node-exporter",
)


def test_dockerfiles_pin_their_base_images_and_backend_is_unprivileged():
    backend = (ROOT / "backend" / "Dockerfile").read_text("utf-8")
    frontend = (ROOT / "frontend" / "Dockerfile").read_text("utf-8")
    pgbouncer = (ROOT / "infra" / "pgbouncer" / "Dockerfile").read_text("utf-8")
    for text in (backend, frontend, pgbouncer):
        for image in re.findall(r"^FROM\s+(\S+)", text, re.M):
            assert re.search(r":\d+\.\d+\.\d+", image), image
    assert "USER 10001" in backend
    assert "postgresql-client-16" in backend


def test_compose_postgres_tuning():
    pg = _services()["postgres"]
    cmd = " ".join(pg["command"])
    for flag in (
        "shared_buffers=${PG_SHARED_BUFFERS:-1GB}",
        "effective_cache_size=${PG_EFFECTIVE_CACHE_SIZE:-4GB}",
        "work_mem=${PG_WORK_MEM:-16MB}",
        "maintenance_work_mem=${PG_MAINTENANCE_WORK_MEM:-256MB}",
        "max_connections=${PG_MAX_CONNECTIONS:-100}",
        "max_wal_size=4GB",
        "checkpoint_completion_target=0.9",
        "wal_compression=on",
        "random_page_cost=1.1",
        "track_io_timing=on",
        "log_min_duration_statement=2000",
        "idle_in_transaction_session_timeout=15min",
    ):
        assert flag in cmd, flag
    assert "archive_mode" not in cmd
    assert pg["shm_size"] == "1gb"


def test_compose_single_web_process():
    web = _services()["web"]
    assert "deploy" not in web or "replicas" not in web["deploy"]
    assert "scale" not in web


def test_compose_backup_service():
    backup = _services()["backup"]
    assert backup["command"] == "aslms ops backup-scheduler"
    assert _env(backup)["BACKUP_DIR"] == "/backups"
    assert "./data:/data:ro" in backup["volumes"]
    assert "${BACKUP_DIR:-./backups}:/backups" in backup["volumes"]


def test_clamav_overrides():
    offline = _services("compose.clamav-offline.yml")["clamav"]
    assert offline["environment"]["CLAMAV_NO_FRESHCLAMD"] == "true"
    mirror = _services("compose.clamav-mirror.yml")["clamav"]
    assert any("freshclam.conf" in v for v in mirror["volumes"])
    assert "PrivateMirror" in (ROOT / "infra" / "clamav" / "freshclam.conf.example").read_text("utf-8")


def test_scheduler_beat_schedule_file_is_writable_by_the_unprivileged_user():
    # /app is root-owned and the image runs as uid 10001: beat's default ./celerybeat-schedule cannot be created.
    command = _services()["scheduler"]["command"]
    assert " -B " in f" {command} "
    match = re.search(r"(?:-s|--schedule)[ =](\S+)", command)
    assert match and match.group(1).startswith("/tmp/"), command
