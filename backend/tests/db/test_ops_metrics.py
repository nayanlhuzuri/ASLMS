"""Design deployment-checklist, Part B, decisions 23 and 27: the operations exporter reads every database gauge as
`aslms_readonly` (no privilege error, no scrape error), the figures follow the rows, and no label value carries a
CNR or a case number."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest
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
from tests.db.conftest import wipe
from tests.db.world import make_case

SETTINGS = Settings(_env_file=None, app_env="test", redis_url=None)
DB_GAUGES = {
    "aslms_queue_rows",
    "aslms_queue_oldest_pending_seconds",
    "aslms_job_last_success_timestamp",
    "aslms_job_running",
    "aslms_job_running_oldest_seconds",
    "aslms_worker_last_pass_timestamp",
    "aslms_worker_alive_timestamp",
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


# ------------------------------------------------------------------------------------------------ pre-pilot-hardening


def _worker_gauges(session, rows, now):
    wipe(session)
    session.add_all(rows)
    session.flush()
    session.execute(sa.text("SET LOCAL ROLE aslms_readonly"))
    samples, _ = ops_metrics.collect_database(session, SETTINGS, now)
    by_name = {s.name: s.value for s in samples if not s.labels}
    return by_name["aslms_worker_last_pass_timestamp"], by_name["aslms_worker_alive_timestamp"]


def _claimed(kind: FetchKind, ref: str, at: datetime) -> FetchQueueItem:
    return FetchQueueItem(
        kind=kind,
        ref=ref,
        status=FetchStatus.RUNNING,
        lane=FetchLane.LOAD,
        priority=50,
        attempts=1,
        started_at=at,
    )


def test_worker_alive_is_the_later_of_pass_start_and_claim(session):
    """Decision 4: a long load pass started hours ago, but the worker claimed a row a minute ago: it is alive."""
    now = datetime.now(UTC)
    pass_at = now - timedelta(hours=3)
    claim_at = now - timedelta(minutes=1)
    last_pass, alive = _worker_gauges(
        session,
        [
            JobRun(job="queue-run", started_at=pass_at),
            _claimed(FetchKind.CAUSELIST_DAY, "2026-10-19", claim_at),
        ],
        now,
    )
    assert last_pass == pytest.approx(pass_at.timestamp(), abs=1)
    assert alive == pytest.approx(claim_at.timestamp(), abs=1)


def test_search_rows_claims_do_not_count_as_worker_activity(session):
    """The scheduler claims search_rows (queue.LOCAL_KINDS): a live scheduler must not hide a dead worker."""
    now = datetime.now(UTC)
    pass_at = now - timedelta(hours=3)
    last_pass, alive = _worker_gauges(
        session,
        [
            JobRun(job="queue-run", started_at=pass_at),
            _claimed(FetchKind.SEARCH_ROWS, "search-1", now - timedelta(minutes=1)),
        ],
        now,
    )
    assert alive == pytest.approx(pass_at.timestamp(), abs=1) == last_pass


def test_worker_alive_without_a_pass_reads_the_claim_or_zero(session):
    now = datetime.now(UTC)
    claim_at = now - timedelta(minutes=5)
    assert _worker_gauges(session, [_claimed(FetchKind.CAUSELIST_DAY, "2026-10-19", claim_at)], now) == (
        0.0,
        pytest.approx(claim_at.timestamp(), abs=1),
    )
