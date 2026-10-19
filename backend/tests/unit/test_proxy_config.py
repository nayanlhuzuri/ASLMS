"""Design deployment-checklist, decisions 8-10: the proxy's template and its start-up script."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from aslms.api.routers.documents import MULTIPART_OVERHEAD
from aslms.core.config import Settings

ROOT = Path(__file__).resolve().parents[3]
PROXY = ROOT / "infra" / "proxy"
TEMPLATE = (PROXY / "aslms.conf.template").read_text("utf-8")


def _location(pattern: str) -> str:
    m = re.search(r"location\s+" + re.escape(pattern) + r"\s*\{(.*?)\n    \}", TEMPLATE, re.S)
    assert m, pattern
    return m.group(1)


def _api_limits(settings: Settings) -> dict[str, int]:
    """The same formula as api/routers/documents.py `_body_limit` plus the multipart overhead."""
    return {
        "upload": settings.upload_max_bytes + MULTIPART_OVERHEAD,
        "notes": settings.attachments_max_files * settings.upload_max_bytes + MULTIPART_OVERHEAD,
    }


def _run_script(tmp_path: Path, **env: str) -> dict[str, str]:
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("no POSIX sh on this machine")
    certs = tmp_path / "certs"
    certs.mkdir()
    (certs / "fullchain.pem").write_text("cert")
    (certs / "privkey.pem").write_text("key")
    out, confd = tmp_path / "out", tmp_path / "confd"
    confd.mkdir()
    (confd / "default.conf").write_text("server {}")
    full = {
        **os.environ,
        "ASLMS_NGINX_DIR": str(out),
        "ASLMS_CERT_DIR": str(certs),
        "NGINX_CONF_D": str(confd),
        "PORTAL_BASE_URL": "https://aslms.example.internal:443/x",
        **env,
    }
    proc = subprocess.run([sh, str(PROXY / "15-aslms-limits.sh")], env=full, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert not (confd / "default.conf").exists()
    return {p.name: p.read_text() for p in out.iterdir()}


def test_proxy_body_limits_match_the_api(tmp_path):
    settings = Settings(_env_file=None, upload_max_bytes=7_000_000, attachments_max_files=3)
    files = _run_script(
        tmp_path, UPLOAD_MAX_BYTES="7000000", ATTACHMENTS_MAX_FILES="3", RELAY_TIMEOUT_SECONDS="90"
    )
    limits = _api_limits(settings)
    assert files["limit-upload.conf"].strip() == f"client_max_body_size {limits['upload']};"
    assert files["limit-notes.conf"].strip() == f"client_max_body_size {limits['notes']};"
    assert "proxy_read_timeout 120s;" in files["timeouts.conf"]
    assert files["server_name.conf"].strip() == "server_name aslms.example.internal;"
    assert files["real_ip.conf"].lstrip().startswith("#")


def test_proxy_defaults_match_the_api_defaults(tmp_path):
    files = _run_script(tmp_path)
    limits = _api_limits(Settings(_env_file=None))
    assert files["limit-upload.conf"].strip() == f"client_max_body_size {limits['upload']};"
    assert files["limit-notes.conf"].strip() == f"client_max_body_size {limits['notes']};"


def test_proxy_trusted_upstream_turns_on_real_ip(tmp_path):
    files = _run_script(tmp_path, PROXY_TRUSTED_UPSTREAM="10.20.0.0/16")
    assert "set_real_ip_from 10.20.0.0/16;" in files["real_ip.conf"]
    assert "real_ip_recursive on;" in files["real_ip.conf"]


def test_proxy_script_refuses_missing_certificate(tmp_path):
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("no POSIX sh on this machine")
    env = {
        **os.environ,
        "ASLMS_NGINX_DIR": str(tmp_path / "o"),
        "ASLMS_CERT_DIR": str(tmp_path / "none"),
        "NGINX_CONF_D": str(tmp_path),
        "PORTAL_BASE_URL": "https://a.example",
    }
    proc = subprocess.run([sh, str(PROXY / "15-aslms-limits.sh")], env=env, capture_output=True, text=True)
    assert proc.returncode != 0 and "make-cert" in proc.stderr


def test_proxy_upload_locations_use_the_snippets_and_stream():
    assert "limit-upload.conf" in _location(r"~ ^/api/backend/.+/documents$")
    assert "limit-notes.conf" in _location(r"~ ^/api/backend/cases/[^/]+/notes$")
    assert "limit-notes.conf" in _location("= /api/backend/admin/tickets/head-change")
    for loc in (
        r"~ ^/api/backend/.+/documents$",
        r"~ ^/api/backend/cases/[^/]+/notes$",
        "= /api/backend/admin/tickets/head-change",
    ):
        assert "proxy_request_buffering off;" in _location(loc)
    assert re.search(r"^client_max_body_size 1m;", TEMPLATE, re.M)
    assert '"code":"too_large"' in TEMPLATE


def test_proxy_overwrites_forwarded_for():
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in TEMPLATE
    assert "$proxy_add_x_forwarded_for" not in TEMPLATE
    assert "proxy_set_header X-Forwarded-Proto https;" in TEMPLATE


def test_proxy_throttles_session_and_answers_json():
    assert "limit_req zone=session" in _location("/api/session/")
    assert "limit_req zone=api" in _location("/api/backend/")
    assert "limit_req_status 429;" in TEMPLATE
    assert "error_page 429 = @throttled;" in TEMPLATE
    throttled = _location("@throttled")
    assert '"code":"throttled"' in throttled and '"retry_after":60' in throttled
    assert "Retry-After 60" in throttled
    assert "rate=${PROXY_SESSION_RATE}" in TEMPLATE and "limit_conn perip ${PROXY_CONN_PER_IP}" in TEMPLATE


def test_proxy_tls_and_host_rules():
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in TEMPLATE
    assert "ssl_session_tickets off;" in TEMPLATE
    assert 'Strict-Transport-Security "max-age=31536000" always' in TEMPLATE
    assert "includeSubDomains" not in TEMPLATE and "preload" not in TEMPLATE
    assert "server_tokens off;" in TEMPLATE
    assert "return 301 https://$host$request_uri;" in TEMPLATE
    assert TEMPLATE.count("return 444;") >= 2
