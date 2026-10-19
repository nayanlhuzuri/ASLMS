"""Design deployment-checklist, Part B, decisions 23 and 27: the operations exporter reads every database gauge as
`aslms_readonly` (no privilege error, no scrape error), the figures follow the rows, and no label value carries a
CNR or a case number."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from prometheus_client.parser import text_string_to_metric_families

from aslms.core.config import Settings
from aslms.domain.ops import (
    FetchKind,
    FetchLane,
    FetchQueueItem,
    FetchStatus,
    JobRun,
    JobStatus,
    NapixCallLog,
    SourceFailure,
)
from aslms.services import ops_metrics
from aslms.services.seed import seed_all
from tests.db.world import make_case

SETTINGS = Settings(_env_file=None, app_env="test", redis_url=None)
DB_GAUGES = {
    "aslms_queue_rows",
    "aslms_queue_oldest_pending_seconds",
    "aslms_job_last_success_timestamp",
    "aslms_job_running",
    "aslms_job_running_oldest_seconds",
    "aslms_worker_last_pass_timestamp",
    "aslms_napix_calls_last_hour",
    "aslms_napix_window_remaining",
    "aslms_napix_switch_on",
    "aslms_source_failures_open",
    "aslms_notifications",
    "aslms_mail_oldest_queued_seconds",
    "aslms_sourcetrace_documents",
}


def _samples(text: str) -> list:
    return [s for fam in text_string_to_metric_families(text) for s in fam.samples]


def _value(samples, name: str, **labels) -> float:
    for s in samples:
        if s.name == name and all(s.labels.get(k) == v for k, v in labels.items()):
            return s.value
    raise AssertionError(f"{name} {labels} not exposed")


def test_ops_metrics_exposes_gauges(session):
    now = datetime.now(UTC)
    seed_all(session)  # the court
    case = make_case(session)
    session.add_all(
        [
            FetchQueueItem(
                kind=FetchKind.DOSSIER,
                ref=case.cnr,
                status=FetchStatus.PENDING,
                lane=FetchLane.DISCOVERY,
                priority=50,
                created_at=now - timedelta(days=400),
            ),
            FetchQueueItem(
                kind=FetchKind.ORDER_PDF,
                ref=f"{case.cnr}:1",
                status=FetchStatus.FAILED,
                lane=FetchLane.DISCOVERY,
                priority=50,
                last_error=f"no order for {case.case_no_text}",
            ),
            JobRun(job="queue-run", started_at=now + timedelta(days=1), status=JobStatus.SUCCEEDED),
            JobRun(job="ops-metrics-test", started_at=now - timedelta(hours=7), status=JobStatus.RUNNING),
            NapixCallLog(
                api="hc-cnr-api/CNR", params_sha256="0" * 64, ok=False, called_at=now, http_status=503
            ),
            SourceFailure(
                kind="ops_metrics_test", ref=case.cnr, error=case.case_no_text, first_seen=now, last_seen=now
            ),
        ]
    )
    session.flush()
    # everything below runs as the read-only role, as the Compose ops-exporter does
    session.execute(sa.text("SET LOCAL ROLE aslms_readonly"))
    collector = ops_metrics.OpsCollector(SETTINGS, lambda: nullcontext(session), sections=[])
    samples = _samples(ops_metrics.render(collector))

    names = {s.name for s in samples}
    assert DB_GAUGES <= names, DB_GAUGES - names
    assert _value(samples, "aslms_scrape_errors") == 0, "the read-only role reads every gauge"
    assert _value(samples, "aslms_queue_rows", lane="discovery", kind="dossier", status="pending") >= 1
    assert _value(samples, "aslms_queue_rows", lane="discovery", kind="order_pdf", status="failed") >= 1
    assert _value(samples, "aslms_queue_oldest_pending_seconds", lane="discovery") >= 400 * 86400 - 60
    assert _value(samples, "aslms_worker_last_pass_timestamp") >= (now + timedelta(days=1)).timestamp() - 1
    assert _value(samples, "aslms_job_last_success_timestamp", job="queue-run") >= now.timestamp()
    assert _value(samples, "aslms_job_running", job="ops-metrics-test") == 1
    assert _value(samples, "aslms_job_running_oldest_seconds", job="ops-metrics-test") >= 7 * 3600 - 60
    assert _value(samples, "aslms_job_running", job="backup") >= 0  # every known job has a series
    assert _value(samples, "aslms_napix_calls_last_hour", outcome="failed") >= 1
    assert _value(samples, "aslms_napix_switch_on") == 0
    assert _value(samples, "aslms_source_failures_open", kind="ops_metrics_test") == 1
    for status in ("queued", "sent", "failed", "read"):
        _value(samples, "aslms_notifications", status=status)
    for status in ("pending", "ingested", "failed", "not_applicable"):
        _value(samples, "aslms_sourcetrace_documents", status=status)

    # no label carries case data
    for s in samples:
        for value in s.labels.values():
            assert case.cnr not in value and case.case_no_text not in value, (s.name, s.labels)
