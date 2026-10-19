"""Design deployment-checklist, Part B, decision 24: the API counts requests by method, route template and status
class, never by the raw path (which carries case references), and serves them only on the internal port."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from aslms.api import metrics
from aslms.api.main import create_app
from aslms.core.config import Settings

CNR = "ASHC010012342025"


def _app():
    settings = Settings(_env_file=None, app_env="test", aslms_jwt_secret="j" * 48)
    return create_app(settings, session_factory=MagicMock)  # no database is reached before the 401


def _count(method: str, route: str, status: str) -> float:
    value = metrics.REGISTRY.get_sample_value(
        "aslms_api_requests_total", {"method": method, "route": route, "status": status}
    )
    return value or 0.0


def test_api_metrics_use_route_templates():
    client = TestClient(_app())  # no lifespan: no listener is opened
    before_case = _count("GET", "/cases/{ref}", "4xx")
    before_health = _count("GET", "/health", "2xx")
    before_unmatched = _count("GET", "unmatched", "4xx")
    before_guard = _count("POST", "unmatched", "4xx")

    assert client.get("/health").status_code == 200
    assert client.get(f"/cases/{CNR}").status_code == 401  # no token: answered by the route's dependency
    assert client.get(f"/no-such-page/{CNR}").status_code == 404
    # the upload size guard answers 413 before routing: counted, as `unmatched`, without the raw path
    too_big = client.post(
        f"/cases/{CNR}/documents", headers={"content-length": str(500 * 1024 * 1024)}, content=b""
    )
    assert too_big.status_code == 413

    assert _count("GET", "/health", "2xx") == before_health + 1
    assert _count("GET", "/cases/{ref}", "4xx") == before_case + 1
    assert _count("GET", "unmatched", "4xx") == before_unmatched + 1
    assert _count("POST", "unmatched", "4xx") == before_guard + 1
    text = generate_latest(metrics.REGISTRY).decode()
    assert CNR not in text
    assert "aslms_api_request_duration_seconds_bucket" in text


def test_status_class_and_unknown_methods():
    assert metrics.status_class(204) == "2xx"
    assert metrics.status_class(503) == "5xx"
    assert metrics.status_class(None) == "5xx"
    client = TestClient(_app())
    before = _count("other", "unmatched", "4xx") + _count("other", "/health", "4xx")
    client.request("PROPFIND", "/health")
    after = _count("other", "unmatched", "4xx") + _count("other", "/health", "4xx")
    assert after == before + 1


def test_metrics_server_is_off_without_a_port(monkeypatch):
    started = []
    monkeypatch.setattr("prometheus_client.start_http_server", lambda *a, **k: started.append(a))
    assert metrics.start_server(0) is False
    assert started == []


def test_metrics_server_starts_once_and_survives_a_busy_port(monkeypatch):
    calls = []

    def fake_start(port, addr="0.0.0.0", registry=None):
        calls.append(port)
        if port == 1:
            raise OSError("address in use")

    monkeypatch.setattr("prometheus_client.start_http_server", fake_start)
    monkeypatch.setattr(metrics, "_server_port", None)
    assert metrics.start_server(1) is False  # logged, not fatal
    assert metrics.start_server(9100) is True
    assert metrics.start_server(9100) is True  # already serving: not started again
    assert calls == [1, 9100]
