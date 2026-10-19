"""Design `portal-shell`, decisions 7 and 20: the Compose `web` service gets no env file (no secret enters it),
reaches the api by its service name, waits for a healthy api, and is the only address whose `X-Forwarded-For`
the api trusts."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def _compose() -> dict:
    return yaml.safe_load((ROOT / "compose.yml").read_text("utf-8"))


def _default(value: str) -> str:
    """`${NAME:-default}` -> `default`."""
    m = re.fullmatch(r"\$\{[A-Z_]+:-([^}]*)\}", value)
    return m.group(1) if m else value


def test_web_service_has_no_env_file():
    web = _compose()["services"]["web"]
    assert "env_file" not in web
    names = set(web["environment"])
    assert names == {
        "API_BASE_URL",
        "PORTAL_BASE_URL",
        "COOKIE_SECURE",
        "ASLMS_REFRESH_TOKEN_DAYS",
        "RELAY_TIMEOUT_SECONDS",
        "TRUST_PROXY_HEADERS",
    }
    assert not any(n.startswith(("NAPIX_", "MAILTRAP_", "SMTP_")) or "SECRET" in n for n in names)


def test_web_api_base_url_is_the_api_service():
    assert _compose()["services"]["web"]["environment"]["API_BASE_URL"] == "http://api:8000"


def test_api_trusts_forwarded_headers_only_from_web_ip():
    compose = _compose()
    web_ip = _default(compose["services"]["web"]["networks"]["portal"]["ipv4_address"])
    command = compose["services"]["api"]["command"]
    assert "--proxy-headers" in command
    m = re.search(r"--forwarded-allow-ips\s+(\S+)", command)
    assert m and _default(m.group(1)) == web_ip == "172.28.0.10"
    subnet = _default(compose["networks"]["portal"]["ipam"]["config"][0]["subnet"])
    assert subnet == "172.28.0.0/24"
    assert "portal" in compose["services"]["api"]["networks"]


def test_web_depends_on_healthy_api():
    compose = _compose()
    assert compose["services"]["web"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert "healthcheck" in compose["services"]["api"]
    assert "healthcheck" in compose["services"]["web"]


def test_web_is_on_portal_and_edge_and_proxy_only_on_edge():
    """Design deployment-checklist, decisions 7 and 8: the proxy reaches web only; web trusts its X-Forwarded-For."""
    compose = _compose()
    web = compose["services"]["web"]
    assert set(web["networks"]) == {"portal", "edge"}
    assert web["environment"]["TRUST_PROXY_HEADERS"] == "true"
    assert compose["services"]["proxy"]["networks"] == ["edge"]
