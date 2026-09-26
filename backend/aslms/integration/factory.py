"""Builds the configured court source. NAPIX is used only when all credentials are present; otherwise the
system runs on local / website cause-list PDFs and the NAPIX-dependent steps are skipped (and reported)."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from aslms.core.config import get_settings
from aslms.core.time import now_utc
from aslms.domain.ops import NapixCallLog
from aslms.integration.napix.client import NapixClient, NapixResult
from aslms.integration.napix.hc import NapixHighCourt


def napix_configured() -> bool:
    return get_settings().napix_configured


class CallRecorder:
    """Collects NAPIX call results in memory (the client is async and database-free) and writes them to
    `napix_call_log` when flushed (ground rule 7)."""

    def __init__(self, job_run_id: uuid.UUID | None = None):
        self.job_run_id = job_run_id
        self.pending: list[NapixResult] = []

    def __call__(self, result: NapixResult) -> None:
        self.pending.append(result)

    def flush(self, session: Session) -> int:
        n = len(self.pending)
        for r in self.pending:
            session.add(
                NapixCallLog(
                    api=r.api,
                    params_sha256=r.params_sha256,
                    http_status=r.http_status,
                    napix_status=r.napix_status,
                    duration_ms=r.duration_ms,
                    ok=r.ok,
                    error=r.error,
                    called_at=now_utc(),
                    job_run_id=self.job_run_id,
                )
            )
        self.pending.clear()
        return n


def napix_source(job_run_id: uuid.UUID | None = None) -> tuple[NapixHighCourt, CallRecorder] | None:
    if not napix_configured():
        return None
    s = get_settings()
    recorder = CallRecorder(job_run_id)
    client = NapixClient.from_settings(on_call=recorder)
    return NapixHighCourt(client, s.napix_hc_est_code, s.napix_state_code), recorder


SourceFactory = Callable[[uuid.UUID | None], tuple[NapixHighCourt, CallRecorder] | None]
