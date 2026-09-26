"""Prometheus metrics (plan §2.2, §8.2: system health from the pilot stage).

HTTP request counts and latency by route template, plus business gauges read from the database on scrape:
open source failures, open alerts by severity, cases pending/tracked, and the age of the last successful
daily cycle — the number an operator watches first."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from sqlalchemy import func, select
from starlette.middleware.base import BaseHTTPMiddleware

from aslms.core.time import now_utc
from aslms.db.session import sync_session_factory

REGISTRY = CollectorRegistry(auto_describe=True)
REQUESTS = Counter(
    "aslms_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=REGISTRY
)
LATENCY = Histogram(
    "aslms_http_request_seconds",
    "HTTP request latency",
    ["method", "route"],
    registry=REGISTRY,
    buckets=(0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
OPEN_FAILURES = Gauge("aslms_open_source_failures", "Unresolved data-collection failures", registry=REGISTRY)
OPEN_ALERTS = Gauge("aslms_open_alerts", "Open alerts", ["severity"], registry=REGISTRY)
CASES = Gauge("aslms_cases", "Cases in the portal", ["state"], registry=REGISTRY)
LAST_CYCLE_AGE = Gauge(
    "aslms_last_daily_cycle_age_seconds",
    "Seconds since the last successful daily cycle finished",
    registry=REGISTRY,
)

router = APIRouter(tags=["health"])


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        template = getattr(route, "path", "unmatched")
        if template != "/metrics":
            REQUESTS.labels(request.method, template, str(response.status_code)).inc()
            LATENCY.labels(request.method, template).observe(time.perf_counter() - start)
        return response


def _refresh_business_gauges() -> None:
    from aslms.domain.alerts import Alert, AlertStatus
    from aslms.domain.cases import Case, CaseStatus
    from aslms.domain.ops import JobKind, JobRun, JobStatus, SourceFailure

    with sync_session_factory()() as s:
        OPEN_FAILURES.set(
            s.scalar(
                select(func.count()).select_from(SourceFailure).where(SourceFailure.resolved_at.is_(None))
            )
            or 0
        )
        for sev in ("critical", "high", "normal"):
            OPEN_ALERTS.labels(sev).set(
                s.scalar(
                    select(func.count())
                    .select_from(Alert)
                    .where(Alert.status == AlertStatus.OPEN, Alert.severity == sev)
                )
                or 0
            )
        CASES.labels("pending").set(
            s.scalar(select(func.count()).select_from(Case).where(Case.status != CaseStatus.DISPOSED)) or 0
        )
        CASES.labels("tracked").set(
            s.scalar(select(func.count()).select_from(Case).where(Case.is_tracked.is_(True))) or 0
        )
        last = s.scalar(
            select(func.max(JobRun.finished_at)).where(
                JobRun.job == JobKind.DAILY_CYCLE, JobRun.status.in_([JobStatus.SUCCEEDED, JobStatus.PARTIAL])
            )
        )
        LAST_CYCLE_AGE.set((now_utc() - last).total_seconds() if last else -1)


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    try:
        _refresh_business_gauges()
    except Exception:  # noqa: BLE001 — metrics must answer even when the database is down
        pass
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
