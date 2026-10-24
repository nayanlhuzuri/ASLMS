"""The two verbatim layers (CLAUDE.md: every call is logged, every response is kept).

`NapixRecorder` is the integration layer's `on_call` hook: it collects each attempt and `flush()` writes one
`napix_call_log` row per attempt and one `napix_responses` row per decrypted JSON response (deduplicated by
API, parameters and payload hash; a repeat only bumps `last_seen_at`). PDFs are not stored here: they go to
`documents` through the storage service.

`flush_apart(session_factory)` writes the same rows in a session of its own and commits it at once, so a failure
later in an API request cannot roll them back (design `api-health-checker-followups`, decisions 1 and 11): the
pattern of the queue runner's window probe, which flushes and commits in its own session. A recorder built with
`session_factory` (the request paths) does that on every `flush`, whatever session the caller passes."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from aslms.core.logging import get_logger
from aslms.integration.napix.client import NapixResult

log = get_logger(__name__)


class CallLogUnavailable(RuntimeError):
    """The database cannot be reached, so the run's calls could not be logged: nothing is called."""


def require_call_log(command: str = "this command") -> None:
    """Before the first call of an operator's command (`napix-check`, `napix-probe-rate`; design court-data-freshness,
    decision 22): the call log must be reachable, or the run would make unlogged calls. Only the exception's class is
    shown (the URL may carry credentials)."""
    from aslms.db import session as db_session

    try:
        with db_session.session_scope() as session:
            session.execute(text("SELECT 1 FROM napix_call_log LIMIT 0"))
    except Exception as e:  # noqa: BLE001
        raise CallLogUnavailable(
            f"cannot reach the database ({type(e).__name__}); {command} logs every call in napix_call_log "
            "and does not start without it"
        ) from None


def payload_sha256(data: Any) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class NapixRecorder:
    """`user_id` is the person whose action caused the calls (design `napix-window`, decision 9): set for a court
    search, a fetch or the connectivity check; the runner sets and clears it per item, like `lane`, from the row's
    `requested_by`. Both are recorded per attempt; `called_at` is the attempt's own time (decision 7)."""

    def __init__(
        self,
        job_run_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        session_factory: sessionmaker[Session] | None = None,
    ):
        self.job_run_id = job_run_id
        # set on the request paths: every flush is committed apart (design api-health-checker-followups, 11)
        self.session_factory = session_factory
        self.pending: list[NapixResult] = []
        self.calls = 0
        self.last_remaining: int | None = None
        # the lane of the queue item being processed (design data-load-console, decision 7); None for API calls
        self.lane: str | None = None
        self.user_id = user_id
        self._tags: list[tuple[str | None, uuid.UUID | None]] = []
        # the `napix_responses.id` of each response written by the last flush, by (api, params_sha256) (design
        # safety-fixes, decision 13: a capped advocate search queues the background storing of these responses)
        self.response_ids: dict[tuple[str, str], uuid.UUID] = {}

    def on_call(self, result: NapixResult) -> None:
        self.pending.append(result)
        self._tags.append((self.lane, self.user_id))
        self.calls += 1
        if result.rate_limit[1] is not None:
            self.last_remaining = result.rate_limit[1]

    def flush(self, session: Session) -> int:
        """The pending attempts into `session` (the caller commits), or committed apart when the recorder was built
        with a session factory."""
        if self.session_factory is not None:
            return self.flush_apart(self.session_factory)
        n = self._write(session)
        self._clear()
        return n

    def flush_apart(self, session_factory: sessionmaker[Session]) -> int:
        """The pending attempts in a session of their own, committed at once. When that write fails (the database
        cannot be reached), each attempt is named in a warning by its non-secret fields (never the parameters, the
        payload or the error text) and the exception propagates; the attempts stay pending."""
        if not self.pending:
            return 0
        try:
            with session_factory() as s:
                n = self._write(s)
                s.commit()
        except Exception:
            log.warning(
                "napix call rows could not be written",
                attempts=[
                    {
                        "api": r.api,
                        "http_status": r.http_status,
                        "napix_status": r.napix_status,
                        "error_family": r.error_family,
                        "duration_ms": r.duration_ms,
                        "called_at": r.called_at.isoformat() if r.called_at else None,
                    }
                    for r in self.pending
                ],
            )
            raise
        self._clear()
        return n

    def _clear(self) -> None:
        self.pending.clear()
        self._tags.clear()

    def _write(self, session: Session) -> int:
        n = 0
        self.response_ids = {}
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
                self.response_ids[(r.api, r.params_sha256)] = store_response(session, r, self.job_run_id)
            n += 1
        return n


def store_response(session: Session, r: NapixResult, job_run_id: uuid.UUID | None = None) -> uuid.UUID:
    """Insert the response, or bump `last_seen_at` of the same payload; the row's id either way."""
    sha = payload_sha256(r.data)
    return session.execute(
        text(
            """
            INSERT INTO napix_responses (api, params_sha256, params, payload_sha256, payload, token_verified, job_run_id)
            VALUES (:api, :ps, CAST(:params AS jsonb), :sha, CAST(:payload AS jsonb), :tv, :job)
            ON CONFLICT (api, params_sha256, payload_sha256) DO UPDATE SET last_seen_at = now()
            RETURNING id
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
    ).scalar_one()
