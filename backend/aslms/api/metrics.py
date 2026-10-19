"""API request metrics (design deployment-checklist, Part B, decision 24).

A pure ASGI middleware counts every HTTP request and measures its duration by method, **route template** (the
matched route's path, such as `/cases/{ref}`; never the raw path, which carries case references) and status class
(`2xx` … `5xx`). A request no route served (a 404, the upload guard's 413) is `unmatched`. The metrics live in their own registry and are served
by the API lifespan on `API_METRICS_PORT` (9100 in Compose) inside the Compose network only: the relay calls only
`api:8000` and the proxy reaches only `web`, so the port needs no `Permission`."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Histogram, ProcessCollector

log = logging.getLogger(__name__)

REGISTRY = CollectorRegistry(auto_describe=True)
ProcessCollector(registry=REGISTRY)
REQUESTS = Counter(
    "aslms_api_requests",
    "HTTP requests answered by the API, by method, route template and status class",
    ["method", "route", "status"],
    registry=REGISTRY,
)
DURATION = Histogram(
    "aslms_api_request_duration_seconds",
    "time to answer an HTTP request, by method and route template",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
    registry=REGISTRY,
)
METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
UNMATCHED = "unmatched"

_server_lock = threading.Lock()
_server_port: int | None = None


def route_template(scope: dict[str, Any]) -> str:
    """The template of the route that served the request (routing puts it in `scope["route"]`); `unmatched` for a
    request no route served: a 404, or an answer given before routing (the upload size guard's 413)."""
    path = getattr(scope.get("route"), "path", None)
    return path if path else UNMATCHED


def status_class(code: int | None) -> str:
    return f"{code // 100}xx" if code and 100 <= code < 600 else "5xx"


class RequestMetricsMiddleware:
    """Outermost middleware (added last), so every answer, error pages included, is counted once."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status: dict[str, int] = {}

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            status.setdefault("code", 500)
            raise
        finally:
            method = scope.get("method", "")
            method = method if method in METHODS else "other"
            route = route_template(scope)
            REQUESTS.labels(method, route, status_class(status.get("code"))).inc()
            DURATION.labels(method, route).observe(time.perf_counter() - start)


def install(app: Any) -> None:
    """Adds the middleware; call after every other middleware so it is the outermost."""
    app.add_middleware(RequestMetricsMiddleware)


def start_server(port: int, addr: str = "0.0.0.0") -> bool:
    """Serves `REGISTRY` on `addr:port` once per process; a port already in use is logged, never fatal."""
    global _server_port
    if not port:
        return False
    from prometheus_client import start_http_server

    with _server_lock:
        if _server_port is not None:
            return _server_port == port
        try:
            start_http_server(port, addr=addr, registry=REGISTRY)
        except OSError as exc:
            log.warning("API metrics not served on port %s: %s", port, exc.__class__.__name__)
            return False
        _server_port = port
        log.info("API metrics on %s:%s", addr, port)
        return True
