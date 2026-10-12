"""The two verbatim layers (CLAUDE.md: every call is logged, every response is kept).

`NapixRecorder` is the integration layer's `on_call` hook: it collects each attempt and `flush()` writes one
`napix_call_log` row per attempt and one `napix_responses` row per decrypted JSON response (deduplicated by
API, parameters and payload hash; a repeat only bumps `last_seen_at`). PDFs are not stored here: they go to
`documents` through the storage service."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from aslms.integration.napix.client import NapixResult


def payload_sha256(data: Any) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class NapixRecorder:
    """`user_id` is the person whose action caused the calls (design `napix-window`, decision 9): set for a court
    search, a fetch or the connectivity check; the runner sets and clears it per item, like `lane`, from the row's
    `requested_by`. Both are recorded per attempt; `called_at` is the attempt's own time (decision 7)."""

    def __init__(self, job_run_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None):
        self.job_run_id = job_run_id
        self.pending: list[NapixResult] = []
        self.calls = 0
        self.last_remaining: int | None = None
        # the lane of the queue item being processed (design data-load-console, decision 7); None for API calls
        self.lane: str | None = None
        self.user_id = user_id
        self._tags: list[tuple[str | None, uuid.UUID | None]] = []

    def on_call(self, result: NapixResult) -> None:
        self.pending.append(result)
        self._tags.append((self.lane, self.user_id))
        self.calls += 1
        if result.rate_limit[1] is not None:
            self.last_remaining = result.rate_limit[1]

    def flush(self, session: Session) -> int:
        n = 0
        tags = self._tags + [(None, None)] * (len(self.pending) - len(self._tags))
        for r, (lane, user_id) in zip(self.pending, tags, strict=False):
            session.execute(
                text(
                    """
                    INSERT INTO napix_call_log (api, params_sha256, http_status, napix_status, duration_ms, ok,
                        error_family, error, token_verified, rate_limit_remaining, job_run_id, lane, user_id,
                        called_at)
                    VALUES (:api, :ps, :http, :ns, :dur, :ok, :ef, :err, :tv, :rem, :job,
                        CAST(:lane AS fetch_lane), :user_id, COALESCE(CAST(:called_at AS timestamptz), now()))
                    """
                ),
                {
                    "api": r.api,
                    "ps": r.params_sha256,
                    "http": r.http_status,
                    "ns": r.napix_status,
                    "dur": r.duration_ms,
                    "ok": r.ok,
                    "ef": r.error_family,
                    "err": (r.error or None) and r.error[:2000],
                    "tv": r.token_verified,
                    "rem": r.rate_limit[1],
                    "job": self.job_run_id,
                    "lane": getattr(lane, "value", lane),
                    "user_id": user_id,
                    "called_at": r.called_at,
                },
            )
            if r.ok and r.data is not None and r.pdf is None:
                store_response(session, r, self.job_run_id)
            n += 1
        self.pending.clear()
        self._tags.clear()
        return n


def store_response(session: Session, r: NapixResult, job_run_id: uuid.UUID | None = None) -> str:
    sha = payload_sha256(r.data)
    session.execute(
        text(
            """
            INSERT INTO napix_responses (api, params_sha256, params, payload_sha256, payload, token_verified, job_run_id)
            VALUES (:api, :ps, CAST(:params AS jsonb), :sha, CAST(:payload AS jsonb), :tv, :job)
            ON CONFLICT (api, params_sha256, payload_sha256) DO UPDATE SET last_seen_at = now()
            """
        ),
        {
            "api": r.api,
            "ps": r.params_sha256,
            "params": json.dumps(r.params, default=str),
            "sha": sha,
            "payload": json.dumps(r.data, default=str),
            "tv": r.token_verified,
            "job": job_run_id,
        },
    )
    return sha
