"""Design deployment-checklist, Part B (row 77, decisions 22-28): the monitoring services in Compose, the Prometheus
scrape list and alert rules, the Alertmanager template, the Grafana provisioning and the preflight inputs. The rules
themselves are tested with `promtool test rules infra/prometheus/rules.test.yml` (docs/operations.md section 17)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
INFRA = ROOT / "infra"
MONITORING = {
    "prometheus",
    "alertmanager",
    "grafana",
    "flower",
    "postgres-exporter",
    "redis-exporter",
    "ops-exporter",
}
HOST = {"node-exporter", "cadvisor"}
ALERTS = {
    "ServiceDown",
    "PortalDown",
    "WorkerStalled",
    "JobStuck",
    "JobLate",
    "BackupMissing",
    "RestoreCheckMissing",
    "DiskLow",
    "ClamAVDown",
    "ClamAVSignaturesOld",
    "NapixErrorsHigh",
    "MailFailing",
    "CertExpiring",
    "PostgresConnectionsHigh",
    "RedisDown",
}


def _services() -> dict:
    return yaml.safe_load((ROOT / "compose.yml").read_text("utf-8"))["services"]


def _env(service: dict) -> dict:
    return service.get("environment") or {}


def _yaml(path: Path):
    return yaml.safe_load(path.read_text("utf-8"))


def test_compose_monitoring_profile():
    services = _services()
    assert {n for n, s in services.items() if s.get("profiles") == ["monitoring"]} == MONITORING
    assert {n for n, s in services.items() if s.get("profiles") == ["monitoring-host"]} == HOST
    for name in MONITORING | HOST:
        svc = services[name]
        image = svc.get("image")
        if image:  # pinned (decision 21)
            assert re.search(r":v?\d+\.\d+\.\d+$", image), image
        for port in svc.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), (name, port)
        assert "env_file" not in svc, f"{name} must not read .env (no NAPIX, mail or JWT secret)"
    assert "--storage.tsdb.retention.time=${PROMETHEUS_RETENTION:-30d}" in services["prometheus"]["command"]
    assert "prometheus_v3:/prometheus" in services["prometheus"]["volumes"]


def test_compose_grafana_is_locked_down():
    env = _env(_services()["grafana"])
    assert (
        env["GF_SECURITY_ADMIN_PASSWORD"] == "${GRAFANA_ADMIN_PASSWORD:?set GRAFANA_ADMIN_PASSWORD in .env}"
    )
    assert env["GF_AUTH_ANONYMOUS_ENABLED"] == "false"
    assert env["GF_USERS_ALLOW_SIGN_UP"] == "false"
    # the only data source is Prometheus: no SQL source (aslms_readonly can read every table)
    sources = _yaml(INFRA / "grafana" / "provisioning" / "datasources" / "prometheus.yml")["datasources"]
    assert [(s["type"], s["url"]) for s in sources] == [("prometheus", "http://prometheus:9090")]
    for path in (INFRA / "grafana").rglob("*"):
        if path.is_file():
            text = path.read_text("utf-8").lower()
            assert "postgres:5432" not in text and '"type": "postgres' not in text, path


def test_grafana_dashboards_are_provisioned():
    provider = _yaml(INFRA / "grafana" / "provisioning" / "dashboards" / "aslms.yml")["providers"][0]
    assert provider["options"]["path"] == "/etc/grafana/dashboards"
    assert "./infra/grafana/dashboards:/etc/grafana/dashboards:ro" in _services()["grafana"]["volumes"]
    titles = {}
    for path in (INFRA / "grafana" / "dashboards").glob("*.json"):
        board = json.loads(path.read_text("utf-8"))
        titles[board["uid"]] = board["title"]
        for panel in board["panels"]:
            if panel["type"] != "row":
                assert panel["datasource"]["uid"] == "prometheus", (path.name, panel["title"])
                assert panel["targets"], (path.name, panel["title"])
    assert titles == {
        "aslms-overview": "ASLMS overview",
        "aslms-postgresql": "PostgreSQL",
        "aslms-redis-celery": "Redis and Celery",
    }


def test_compose_flower_and_exporters():
    services = _services()
    flower = _env(services["flower"])
    assert flower["FLOWER_BASIC_AUTH"] == "${FLOWER_BASIC_AUTH:?set FLOWER_BASIC_AUTH in .env}"
    assert flower["CELERY_BROKER_URL"].startswith("redis://:${REDIS_PASSWORD:?")
    pg = _env(services["postgres-exporter"])
    assert pg["DATA_SOURCE_USER"] == "aslms_readonly"
    assert pg["DATA_SOURCE_PASS"].startswith("${ASLMS_READONLY_PASSWORD:?")
    redis = _env(services["redis-exporter"])
    assert redis["REDIS_PASSWORD"].startswith("${REDIS_PASSWORD:?")


def test_compose_ops_exporter_is_read_only():
    ops = _services()["ops-exporter"]
    env = _env(ops)
    assert ops["command"] == "aslms ops metrics --port 9108"
    assert env["DATABASE_URL_SYNC"].startswith(
        "postgresql+psycopg://aslms_readonly:${ASLMS_READONLY_PASSWORD:?"
    )
    assert env["NAPIX_ENABLED"] == "${NAPIX_ENABLED:-false}"
    assert not any(k.startswith(("NAPIX_CLIENT", "NAPIX_AUTH", "MAILTRAP_", "SMTP_")) for k in env)
    assert "ASLMS_JWT_SECRET" not in env and "POSTGRES_PASSWORD" not in env
    assert "./data:/data:ro" in ops["volumes"]
    assert "${BACKUP_DIR:-./backups}:/backups:ro" in ops["volumes"]
    # it probes the proxy and web (edge) and reads postgres, clamav and the api (default); never the portal subnet
    assert set(ops["networks"]) == {"default", "edge"}


def test_compose_api_serves_metrics_on_the_internal_port_only():
    api = _services()["api"]
    assert _env(api)["API_METRICS_PORT"] == "9100"
    assert "ports" not in api
    assert "9100" not in (ROOT / "infra" / "proxy" / "aslms.conf.template").read_text("utf-8")


def test_compose_preflight_sees_the_monitoring_settings():
    for name in ("init", "migrate"):
        env = _env(_services()[name])
        for var in ("ASLMS_READONLY_PASSWORD", "GRAFANA_ADMIN_PASSWORD", "FLOWER_BASIC_AUTH"):
            assert env[var] == f"${{{var}:?set {var} in .env}}", (name, var)
        assert env["COMPOSE_PROFILES"] == "${COMPOSE_PROFILES:-}"


def test_prometheus_scrapes_every_exporter():
    config = _yaml(INFRA / "prometheus" / "prometheus.yml")
    assert config["rule_files"] == ["/etc/prometheus/rules.yml"]
    targets = {
        t for job in config["scrape_configs"] for sc in job.get("static_configs", []) for t in sc["targets"]
    }
    assert {
        "api:9100",
        "ops-exporter:9108",
        "postgres-exporter:9187",
        "redis-exporter:9121",
        "alertmanager:9093",
        "grafana:3000",
    } <= targets
    dns = {n for job in config["scrape_configs"] for sd in job.get("dns_sd_configs", []) for n in sd["names"]}
    assert dns == HOST
    alerting = config["alerting"]["alertmanagers"][0]["static_configs"][0]["targets"]
    assert alerting == ["alertmanager:9093"]


def test_alert_rules_cover_the_design_table_and_are_tested():
    rules = _yaml(INFRA / "prometheus" / "rules.yml")
    names = {r["alert"] for g in rules["groups"] for r in g["rules"]}
    assert names == ALERTS
    for g in rules["groups"]:
        for r in g["rules"]:
            assert r["labels"]["severity"] in {"critical", "warning"}, r["alert"]
            assert r["annotations"]["runbook"] == f"docs/operations.md section 17, {r['alert']}"
    tests = _yaml(INFRA / "prometheus" / "rules.test.yml")
    assert tests["rule_files"] == ["rules.yml"]
    tested = {
        a["alertname"]
        for case in tests["tests"]
        for a in case.get("alert_rule_test", [])
        if a.get("exp_alerts")
    }
    assert tested == ALERTS, ALERTS - tested
    runbook = (ROOT / "docs" / "operations.md").read_text("utf-8")
    for name in ALERTS:
        assert f"**{name}**" in runbook, f"docs/operations.md section 17 says what to do for {name}"


def test_alertmanager_never_writes_the_smtp_password_into_its_configuration():
    template = (INFRA / "alertmanager" / "alertmanager.yml.template").read_text("utf-8")
    assert "smtp_auth_password_file: /tmp/smtp_password" in template
    assert "SMTP_PASSWORD" not in template
    script = (INFRA / "alertmanager" / "entrypoint.sh").read_text("utf-8")
    assert "\r" not in script, "the entrypoint runs in a Linux container: LF line endings"
    assert script.count("SMTP_PASSWORD") == 1  # written to the mode-600 file only, never echoed
    assert "umask 077" in script
    am = _services()["alertmanager"]
    assert am["entrypoint"] == ["/bin/sh", "/etc/alertmanager/entrypoint.sh"]
    assert am["tmpfs"] == ["/tmp"]
    assert _env(am)["OPS_ALERT_EMAIL"] == "${OPS_ALERT_EMAIL:-}"


def test_env_example_carries_the_monitoring_variables():
    text = (ROOT / ".env.example").read_text("utf-8")
    for var in (
        "COMPOSE_PROFILES",
        "ASLMS_READONLY_PASSWORD",
        "GRAFANA_ADMIN_PASSWORD",
        "FLOWER_BASIC_AUTH",
        "OPS_ALERT_EMAIL",
        "PROMETHEUS_RETENTION",
    ):
        assert re.search(rf"^#?\s*{var}=", text, re.M), var
    # the master switch is never on in the example
    assert not re.search(r"^NAPIX_ENABLED\s*=\s*true", text, re.M | re.I)
