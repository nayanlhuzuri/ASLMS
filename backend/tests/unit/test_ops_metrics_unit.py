"""Design deployment-checklist, Part B, decision 23: the operations exporter's non-database readings (backup status
files, disks, ClamAV, the probes and the certificate), its cache and its error count."""

from __future__ import annotations

import json
import socket
import ssl
import threading
from datetime import UTC, datetime, timedelta

from aslms.core.config import Settings
from aslms.services import ops_metrics as om
from aslms.services.certs import make_cert
from aslms.services.scanner import ScannerUnavailable


def _settings(**over) -> Settings:
    values = dict(app_env="test", portal_base_url="https://aslms.example.internal")
    values.update(over)
    return Settings(_env_file=None, **values)


def _by_name(samples):
    out = {}
    for s in samples:
        out.setdefault(s.name, []).append(s)
    return out


def test_parse_clamav_version():
    at = om.parse_clamav_version("ClamAV 1.5.4/27795/Sun Oct 18 08:26:03 2026")
    assert at == datetime(2026, 10, 18, 8, 26, 3, tzinfo=UTC)
    assert om.parse_clamav_version("ClamAV 1.5.4/27795/Mon Oct  5 01:02:03 2026").day == 5
    assert om.parse_clamav_version("ClamAV 1.5.4") is None  # signatures not loaded yet
    assert om.parse_clamav_version("garbage/x/not a date") is None


def test_collect_clamav_up_down():
    s = _settings()
    up = _by_name(om.collect_clamav(s, version=lambda: "ClamAV 1.5.4/27795/Sun Oct 18 08:26:03 2026"))
    assert up["aslms_clamav_up"][0].value == 1
    assert (
        up["aslms_clamav_signature_timestamp"][0].value
        == datetime(2026, 10, 18, 8, 26, 3, tzinfo=UTC).timestamp()
    )

    def down():
        raise ScannerUnavailable("refused")

    gone = _by_name(om.collect_clamav(s, version=down))
    assert gone["aslms_clamav_up"][0].value == 0
    assert "aslms_clamav_signature_timestamp" not in gone


def test_collect_backups_reads_the_status_files(tmp_path):
    status = tmp_path / "status"
    status.mkdir()
    (status / "last-success.json").write_text(
        json.dumps({"finished_at": "2026-10-19T06:31:00+00:00", "counters": {"db_bytes": 12345}}), "utf-8"
    )
    (status / "restore-check.json").write_text(
        json.dumps({"status": "succeeded", "finished_at": "2026-10-18T23:10:00+00:00"}), "utf-8"
    )
    got = {s.name: s.value for s in om.collect_backups(str(tmp_path))}
    assert got["aslms_backup_last_success_timestamp"] == datetime(2026, 10, 19, 6, 31, tzinfo=UTC).timestamp()
    assert got["aslms_backup_last_size_bytes"] == 12345
    assert (
        got["aslms_restore_check_last_success_timestamp"]
        == datetime(2026, 10, 18, 23, 10, tzinfo=UTC).timestamp()
    )

    # a failed restore check overwrote the file: the job_runs success (later or not) is used instead
    (status / "restore-check.json").write_text(json.dumps({"status": "failed", "finished_at": "x"}), "utf-8")
    earlier = datetime(2026, 10, 11, 23, 0, tzinfo=UTC)
    got = {s.name: s.value for s in om.collect_backups(str(tmp_path), {"restore_check": earlier})}
    assert got["aslms_restore_check_last_success_timestamp"] == earlier.timestamp()


def test_collect_backups_without_files_reports_never(tmp_path):
    got = {s.name: s.value for s in om.collect_backups(str(tmp_path / "missing"))}
    assert got == {
        "aslms_backup_last_success_timestamp": 0.0,
        "aslms_backup_last_size_bytes": 0.0,
        "aslms_restore_check_last_success_timestamp": 0.0,
    }


def test_collect_disks_skips_missing_paths(tmp_path):
    got = om.collect_disks([str(tmp_path), str(tmp_path / "nope")])
    assert {(s.name, s.labels["path"]) for s in got} == {
        ("aslms_disk_free_bytes", str(tmp_path)),
        ("aslms_disk_total_bytes", str(tmp_path)),
    }
    free, total = (s.value for s in got)
    assert 0 < free <= total


def test_collect_probes_with_fakes():
    seen = {}
    expiry = datetime(2027, 1, 1, tzinfo=UTC)

    def tls(url, host, timeout):
        seen["tls"] = (url, host)
        return om.TlsProbe(True, expiry)

    def http(url, timeout):
        return url.endswith("/api/health")

    got = om.collect_probes(_settings(), tls=tls, http=http)
    assert seen["tls"] == ("https://proxy/api/health", "aslms.example.internal")
    values = {(s.name, s.labels.get("target")): s.value for s in got}
    assert values == {
        ("aslms_probe_up", "portal"): 1,
        ("aslms_tls_cert_expiry_timestamp", None): expiry.timestamp(),
        ("aslms_probe_up", "web"): 1,
        ("aslms_probe_up", "api"): 0,
    }
    # a blank URL is not probed
    none = om.collect_probes(
        _settings(ops_probe_portal_url="", ops_probe_web_url="", ops_probe_api_url=""), tls=tls, http=http
    )
    assert none == []


def test_probe_tls_reads_the_served_certificate_and_sends_the_portal_host(tmp_path):
    files = make_cert("aslms.example.internal", tmp_path, [])
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(files.fullchain, files.privkey)
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    got = {}

    def serve():
        conn, _ = server.accept()
        with ctx.wrap_socket(conn, server_side=True) as tls:
            got["request"] = tls.recv(4096).decode()
            tls.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        result = om.probe_tls(f"https://127.0.0.1:{port}/api/health", "aslms.example.internal", 5)
    finally:
        thread.join(5)
        server.close()
    assert result.up is True
    assert "Host: aslms.example.internal" in got["request"]
    assert got["request"].startswith("GET /api/health ")
    assert result.cert_expiry is not None
    assert result.cert_expiry > datetime.now(UTC) + timedelta(days=800)


def test_probe_tls_down_when_refused():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()  # nothing listens there now
    assert om.probe_tls(f"https://127.0.0.1:{port}/api/health", "x", 1).up is False


def test_collector_caches_and_counts_failed_sections():
    clock = [0.0]
    calls = []

    def ok(jobs):
        calls.append("ok")
        return [om.Sample("aslms_clamav_up", {}, 1)]

    def broken(jobs):
        raise RuntimeError("boom")

    collector = om.OpsCollector(_settings(), None, clock=lambda: clock[0], sections=[ok, broken])
    text = om.render(collector)
    assert "aslms_clamav_up 1.0" in text
    assert "aslms_scrape_errors 1.0" in text
    om.render(collector)
    assert calls == ["ok"]  # served from the cache
    clock[0] += 61
    om.render(collector)
    assert calls == ["ok", "ok"]


def test_collector_counts_an_unreachable_database():
    def factory():
        raise OSError("connection refused")

    collector = om.OpsCollector(_settings(), factory, sections=[])
    text = om.render(collector)
    assert "aslms_scrape_errors 1.0" in text


def test_every_gauge_has_help():
    collector = om.OpsCollector(
        _settings(), None, sections=[lambda jobs: [om.Sample("aslms_probe_up", {"target": "api"}, 1)]]
    )
    text = om.render(collector)
    assert "# HELP aslms_probe_up 1 when the target's health page answers 2xx" in text
    assert "# TYPE aslms_probe_up gauge" in text
