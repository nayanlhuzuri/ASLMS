"""The research index's vectors (design `research-index`, decisions 6, 7, 12, 22, 30, 32 and 34).

- `live_key` reads `/api/tags` once (never embeds, never loads) and names the live model key
  `<full name>@<first 12 hex digits of the digest>`; None when the model is not held locally (`model_unready`).
- `pending` lists current chunks with no current vector of the key, newest first (the job) or in the backfill's
  phase order; `embed_batch` sends their exact inputs (the profile's document prefix, the context line, a newline, the
  text; `truncate: false`) to the local model through `integration/ollama/` and inserts one vector per distinct input
  with `ON CONFLICT DO NOTHING` on the current unique index. A refused or wrong-dimension input goes to
  `source_failures` (kind `research_embed`, ref the chunk id), retried by the reconcile.
- `retire_unused` retires vectors no current chunk uses (`chunk_retired`).
- `wait_for_people` pauses a batch while a question holds an assistant slot (the Redis key `aslms:assistant:asking`).
- `run_job` is the 5-minute job; `backfill` the CLI's resumable pass.

No NAPIX call and no `fetch_queue` row; indexing writes no audit row (decision 33). Log lines carry counts,
characters, milliseconds and the model key, never chunk text."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from aslms.core import clock
from aslms.domain.ops import JobRun, JobStatus
from aslms.domain.research import ResearchEmbedding
from aslms.integration.ollama import OllamaClient, too_long
from aslms.integration.ollama.client import full_name
from aslms.integration.sourcetrace.connector import (
    SourceTraceProtocolError,
    SourceTraceRejected,
    SourceTraceUnavailable,
)
from aslms.services import research_chunks as rc
from aslms.services import research_index as ri
from aslms.services import source_failures

log = logging.getLogger(__name__)

ASKING_KEY = "aslms:assistant:asking"
ASKING_SECONDS = 30
WAIT_STEP_SECONDS = 2.0
WAIT_MAX_SECONDS = 120.0
EMBED_TIMEOUT_SECONDS = 180.0
SETS_PER_STEP = 500
FIRST_WATERMARK = timedelta(days=1)


# ------------------------------------------------------------------------------------------------ the live key


@dataclass(frozen=True)
class LiveKey:
    """Decision 7: the model's full name, its digest as `/api/tags` gives it, the key and the profile."""

    model: str
    digest: str
    key: str
    profile: rc.EmbedProfile


def model_key(model: str, digest: str) -> str:
    hexes = (digest or "").split(":", 1)[-1].strip().lower()
    return f"{full_name(model)}@{hexes[:12]}"


def live_key(client: OllamaClient, model: str) -> LiveKey | None:
    """The live key from `/api/tags` (and `/api/ps`, `/api/version` through `state_sync`), or None when the model is
    unreachable, missing, not held locally, has no digest or no profile."""
    profile = rc.profile_for(model)
    if profile is None:
        return None
    state = client.state_sync(model)
    if not (state.reachable and state.held and state.local and state.digest):
        return None
    return LiveKey(full_name(model), state.digest, model_key(model, state.digest), profile)


def readiness(cfg: Any, *, client: OllamaClient | None = None) -> tuple[str | None, str]:
    """The live key and the readiness for the status block (decision 32): `off` (switched off), `ready` (held and
    loaded), `held` (held, not loaded) or `unavailable`. Reads `/api/tags` and `/api/ps` only. Never raises."""
    if not bool(getattr(cfg, "research_index_enabled", False)):
        return None, "off"
    try:
        client = client or OllamaClient(cfg.assistant_ollama_url)
        state = client.state_sync(cfg.research_embed_model)
    except Exception:  # noqa: BLE001 — the block still answers with the counts
        return None, "unavailable"
    if not (state.reachable and state.held and state.local and state.digest):
        return None, "unavailable"
    return model_key(cfg.research_embed_model, state.digest), "ready" if state.loaded else "held"


def options(profile: rc.EmbedProfile, cfg: Any) -> dict[str, Any]:
    """Decision 6: `num_ctx` and `num_batch` both at the profile's input limit (the same on every call, so the model is
    never reloaded for another setting); `num_gpu: 0` with `RESEARCH_EMBED_ON_CPU`."""
    out: dict[str, Any] = {"num_ctx": profile.input_tokens, "num_batch": profile.input_tokens}
    if bool(getattr(cfg, "research_embed_on_cpu", False)):
        out["num_gpu"] = 0
    return out


def keep_alive(cfg: Any) -> str | int:
    raw = str(getattr(cfg, "research_embed_keep_alive", "-1")).strip()
    return int(raw) if raw.lstrip("-").isdigit() else raw


def batch_size(cfg: Any) -> int:
    """`RESEARCH_EMBED_BATCH`, halved on CPU (decision 22)."""
    n = int(getattr(cfg, "research_embed_batch", 16))
    return max(1, n // 2) if bool(getattr(cfg, "research_embed_on_cpu", False)) else n


# ------------------------------------------------------------------------------------------------ people first


def redis_client(cfg: Any) -> Any | None:
    """A Redis client for the asking flag, or None (no `REDIS_URL`, or the package missing). Never raises."""
    url = getattr(cfg, "redis_url", None)
    if not url:
        return None
    try:
        import redis

        return redis.Redis.from_url(url, socket_timeout=2)
    except Exception:  # noqa: BLE001 - the flag is a courtesy, never a refusal
        return None


def set_asking(r: Any | None) -> None:
    """Decision 22: a question holds an assistant slot (30 s expiry; renewed by setting it again)."""
    if r is None:
        return
    try:
        r.set(ASKING_KEY, "1", ex=ASKING_SECONDS)
    except Exception:  # noqa: BLE001
        log.debug("the asking flag could not be set")


def clear_asking(r: Any | None) -> None:
    if r is None:
        return
    try:
        r.delete(ASKING_KEY)
    except Exception:  # noqa: BLE001
        log.debug("the asking flag could not be cleared")


def wait_for_people(
    r: Any | None,
    *,
    step: float = WAIT_STEP_SECONDS,
    limit: float = WAIT_MAX_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Decision 22: while the asking flag is set, wait in `step` seconds, at most `limit` per batch. Returns the
    milliseconds waited."""
    if r is None:
        return 0
    waited = 0.0
    while waited < limit:
        try:
            busy = r.get(ASKING_KEY) is not None
        except Exception:  # noqa: BLE001 - Redis down: do not wait
            return int(waited * 1000)
        if not busy:
            break
        sleep(step)
        waited += step
    return int(waited * 1000)


# ------------------------------------------------------------------------------------------------ waiting chunks


@dataclass(frozen=True)
class Waiting:
    id: uuid.UUID
    embed_sha256: str
    context_line: str
    text: str


_PHASE_WHERE = {
    "judgment": "c.form = 'judgment'",
    "final": "c.form = 'final'",
    "interim_substantive": "c.form = 'interim' AND NOT coalesce(s.procedural, false)",
    "sheets": "c.kind = 'case_sheet'",
    "procedural": "c.form = 'interim' AND coalesce(s.procedural, false)",
}


def pending(
    session: Session,
    key: str,
    *,
    limit: int,
    phase: str | None = None,
    retry: bool = False,
) -> list[Waiting]:
    """Current chunks with no current vector of `key`, newest first, one per distinct input; with `phase`, only that
    backfill phase's chunks. Chunks with an open `research_embed` failure only with `retry` (the reconcile)."""
    where_phase = _PHASE_WHERE.get(phase or "", "")
    failure = "EXISTS" if retry else "NOT EXISTS"
    sql = f"""
        SELECT c.id, c.embed_sha256, c.context_line, c.text
        FROM research_chunks c
        LEFT JOIN order_sections s ON s.id = c.first_reading_id
        WHERE c.retired_at IS NULL {f"AND {where_phase}" if where_phase else ""}
          AND NOT EXISTS (
              SELECT 1 FROM research_embeddings e
              WHERE e.input_sha256 = c.embed_sha256 AND e.model_key = :key AND e.retired_at IS NULL)
          AND {failure} (
              SELECT 1 FROM source_failures f
              WHERE f.kind = :kind AND f.ref = c.id::text AND f.resolved_at IS NULL)
        ORDER BY c.created_at DESC, c.id
        LIMIT :limit
    """
    rows = session.execute(text(sql), {"key": key, "kind": ri.FAILURE_KIND, "limit": int(limit) * 2}).all()
    out: list[Waiting] = []
    seen: set[str] = set()
    for row in rows:
        if row.embed_sha256 in seen:
            continue
        seen.add(row.embed_sha256)
        out.append(Waiting(row.id, row.embed_sha256, row.context_line, row.text))
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------------------------------------ embedding


@dataclass
class BatchResult:
    embedded: int = 0
    reused: int = 0
    failed: int = 0
    mismatch: int = 0
    chars: int = 0
    ms: int = 0


def _fail(session: Session, chunk_id: uuid.UUID, error: str, family: str) -> None:
    source_failures.record(session, ri.FAILURE_KIND, str(chunk_id), error, family)


def _insert(session: Session, key: LiveKey, chunk: Waiting, vector: list[float]) -> bool:
    stmt = (
        pg_insert(ResearchEmbedding)
        .values(
            input_sha256=chunk.embed_sha256,
            first_chunk_id=chunk.id,
            model=key.model,
            model_digest=key.digest[:80],
            model_key=key.key,
            profile=key.profile.name,
            dims=len(vector),
            embedding=vector,
        )
        .on_conflict_do_nothing(
            index_elements=["input_sha256", "model_key"], index_where=text("retired_at IS NULL")
        )
    )
    return bool(session.execute(stmt).rowcount)


def embed_batch(
    session: Session, client: OllamaClient, key: LiveKey, chunks: list[Waiting], cfg: Any
) -> BatchResult:
    """One embedding call for `chunks` (decisions 6, 12 and 34). An input refused as too long is retried alone; still
    refused, or a vector of the wrong dimension, it is recorded in `source_failures`. A chunk whose stored hash is not
    the hash of the input the live profile would send (a profile change without `rebuild --chunks`) is skipped and
    counted `mismatch`. `SourceTraceUnavailable` (the model went away) is raised to the caller."""
    out = BatchResult()
    good: list[tuple[Waiting, str]] = []
    for c in chunks:
        inp = rc.embed_input(key.profile, c.context_line, c.text)
        if rc.sha256(inp) != c.embed_sha256:
            out.mismatch += 1
            continue
        good.append((c, inp))
    if not good:
        return out
    started = time.monotonic()
    opts = options(key.profile, cfg)
    alive = keep_alive(cfg)

    def call(items: list[tuple[Waiting, str]]) -> list[list[float]]:
        reply = client.embed_sync(
            key.model, [i for _c, i in items], options=opts, keep_alive=alive, timeout=EMBED_TIMEOUT_SECONDS
        )
        return reply.embeddings

    try:
        pairs = list(zip(good, call(good), strict=True))
    except SourceTraceRejected as exc:
        if not too_long(exc) and len(good) == 1:
            raise
        pairs = []
        for item in good:  # one at a time: only the refused input fails
            try:
                pairs.append((item, call([item])[0]))
            except SourceTraceRejected as one:
                kind = "too_long" if too_long(one) else "rejected"
                _fail(session, item[0].id, f"{type(one).__name__}: {one}", kind)
                out.failed += 1
            except SourceTraceProtocolError as one:
                _fail(session, item[0].id, f"{type(one).__name__}: {one}", "protocol")
                out.failed += 1
    except SourceTraceProtocolError as exc:
        for c, _i in good:
            _fail(session, c.id, f"{type(exc).__name__}: {exc}", "protocol")
        out.failed += len(good)
        return out
    for (c, inp), vector in pairs:
        if len(vector) != key.profile.dims:
            _fail(session, c.id, f"wrong dimension: {len(vector)} instead of {key.profile.dims}", "dimension")
            out.failed += 1
            continue
        if _insert(session, key, c, vector):
            out.embedded += 1
        else:
            out.reused += 1  # another batch wrote the same input first
        out.chars += len(inp)
        source_failures.resolve(session, ri.FAILURE_KIND, str(c.id))
    session.flush()
    out.ms = int((time.monotonic() - started) * 1000)
    log.info(
        "research index: %d embedded, %d reused, %d failed, %d characters, %d ms, model %s",
        out.embedded,
        out.reused,
        out.failed,
        out.chars,
        out.ms,
        key.key,
    )
    return out


def retire_unused(
    session: Session, *, now: datetime | None = None, hashes: Iterable[str] | None = None
) -> int:
    """Vectors no current chunk uses (`chunk_retired`, decision 13). With `hashes`, only the vectors of those
    embedding inputs (the 5-minute job passes the hashes of the chunks it has just retired). The number retired."""
    params: dict[str, Any] = {"now": now or datetime.now(UTC)}
    only = ""
    if hashes is not None:
        params["hashes"] = sorted(set(hashes))
        if not params["hashes"]:
            return 0
        only = "AND e.input_sha256 = ANY(:hashes)"
    n = session.execute(
        text(
            f"""
            UPDATE research_embeddings e SET retired_at = :now, retire_reason = 'chunk_retired'
            WHERE e.retired_at IS NULL {only} AND NOT EXISTS (
                SELECT 1 FROM research_chunks c WHERE c.retired_at IS NULL AND c.embed_sha256 = e.input_sha256)
            """
        ),
        params,
    ).rowcount
    return int(n or 0)


def resolve_retired_failures(session: Session) -> int:
    """Decision 34: an open failure whose chunk was retired is closed."""
    n = session.execute(
        text(
            """
            UPDATE source_failures f SET resolved_at = now()
            WHERE f.kind = :kind AND f.resolved_at IS NULL AND NOT EXISTS (
                SELECT 1 FROM research_chunks c WHERE c.id::text = f.ref AND c.retired_at IS NULL)
            """
        ),
        {"kind": ri.FAILURE_KIND},
    ).rowcount
    return int(n or 0)


# ------------------------------------------------------------------------------------------------ the job


COUNTERS = ("cut", "chunks", "retired", "sheets", "embedded", "reused", "failed", "skipped", "waited_ms")


def _previous_counters(session: Session) -> dict[str, Any] | None:
    """The counters of the latest finished job run that carries a watermark: a backfill phase row or a failed run
    (no watermark) never sends the job back to its first look-back."""
    return session.scalar(
        select(JobRun.counters)
        .where(JobRun.job == ri.JOB, JobRun.status != JobStatus.RUNNING, JobRun.counters.has_key("watermark"))
        .order_by(JobRun.started_at.desc())
        .limit(1)
    )


def _as_uuid(raw: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(raw)) if raw else None
    except ValueError:
        return None


def _next_sheet_cursor(
    got: dict[str, Any], since: datetime, after: uuid.UUID | None, floor: datetime
) -> tuple[datetime, uuid.UUID | None]:
    """Where the next run's sheet page starts. A short page: everything up to `floor` (now minus the slack) was read.
    A full page: just after its last case, kept before `floor` so a change still being committed is not missed;
    never moved back."""
    cursor = got.get("sheet_cursor")
    if got["sheet_candidates"] >= ri.SHEET_BATCH and cursor is not None:
        changed, last_id = cursor
        if changed is not None and changed < floor:
            return changed, last_id
    return (floor, None) if floor > since else (since, after)


def run_job(
    session_factory: Callable[[], Session],
    client: OllamaClient,
    cfg: Any,
    *,
    redis: Any | None = None,
    now: datetime | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """The 5-minute job (decision 30), within `RESEARCH_JOB_SECONDS` of wall time: sets for readings created since the
    watermark, orphan sets retired (only once their orders' new sets are cut, so shared vectors stay), sheets of
    changed cases, then embedding newest first. Disabled: returns at once, writes nothing and calls nothing. The model
    not held locally: the chunk steps run and embedding is skipped (`model_unready`). One `job_runs` row
    `research_index`, with two cursors in its counters: `watermark` (sets and orphans) moves once every set since it
    is cut (each run cuts new keys only, so a backlog shrinks); `sheet_watermark` with `sheet_after` moves past every
    page of changed cases read, so a page of unchanged sheets is never read again."""
    if not bool(getattr(cfg, "research_index_enabled", False)):
        return {"disabled": 1}
    profile = ri.profile_of(cfg.research_embed_model)
    now = now or datetime.now(UTC)
    t0 = monotonic()
    budget = float(cfg.research_job_seconds)
    counters: dict[str, Any] = dict.fromkeys(COUNTERS, 0)
    counters["model_unready"] = 0
    with session_factory() as s:
        prev = _previous_counters(s)
        since = ri.watermark_from(prev) or (now - FIRST_WATERMARK)
        sheet_mark = ri.watermark_from(prev, "sheet_watermark")
        sheet_since = sheet_mark or since
        sheet_after = _as_uuid((prev or {}).get("sheet_after")) if sheet_mark else None
        run = JobRun(job=ri.JOB, run_date=clock.today_ist(now), started_at=now)
        s.add(run)
        s.commit()
        run_id = run.id
    floor = now - ri.WATERMARK_SLACK
    sheet_next: tuple[datetime, uuid.UUID | None] = (sheet_since, sheet_after)
    sets_done = False
    try:
        with session_factory() as s:
            got = ri.sync_sets(s, profile=profile, since=since, limit=SETS_PER_STEP)
            s.commit()
        counters["cut"], counters["chunks"], counters["skipped"] = got["cut"], got["chunks"], got["skipped"]
        sets_done = got["candidates"] < SETS_PER_STEP
        with session_factory() as s:
            hashes: set[str] = set()
            counters["retired"] = ri.retire_orphans(
                s, since=since, now=now, wait_for_new_sets=True, hashes=hashes
            )
            if hashes:
                counters["vectors_retired"] = retire_unused(s, now=now, hashes=hashes)
            s.commit()
        with session_factory() as s:
            got = ri.sync_sheets(
                s, profile=profile, since=sheet_since, after_id=sheet_after, limit=ri.SHEET_BATCH, now=now
            )
            s.commit()
        counters["sheets"] = got["sheets"]
        sheet_next = _next_sheet_cursor(got, sheet_since, sheet_after, floor)
        key = live_key(client, cfg.research_embed_model)
        if key is None:
            counters["model_unready"] = 1
        else:
            counters["model_key"] = key.key
            size = batch_size(cfg)
            while monotonic() - t0 < budget:
                counters["waited_ms"] += wait_for_people(redis)
                with session_factory() as s:
                    todo = pending(s, key.key, limit=size)
                    if not todo:
                        break
                    try:
                        res = embed_batch(s, client, key, todo, cfg)
                    except SourceTraceUnavailable:
                        s.rollback()
                        counters["model_unready"] = 1
                        break
                    s.commit()
                counters["embedded"] += res.embedded
                counters["reused"] += res.reused
                counters["failed"] += res.failed
                if res.embedded + res.reused + res.failed == 0:
                    break  # nothing could be done with this batch (a profile mismatch): stop, the status shows it
    except Exception as exc:
        with session_factory() as s:
            run = s.get(JobRun, run_id)
            run.status, run.error = JobStatus.FAILED, f"{exc.__class__.__name__}: {exc}"[:2000]
            run.finished_at = datetime.now(UTC)
            run.counters = counters
            s.commit()
        raise
    counters["watermark"] = ri.next_watermark(now) if sets_done else since.isoformat()
    counters["sheet_watermark"] = sheet_next[0].isoformat()
    counters["sheet_after"] = str(sheet_next[1]) if sheet_next[1] is not None else None
    with session_factory() as s:
        run = s.get(JobRun, run_id)
        run.counters = counters
        run.status = JobStatus.PARTIAL if counters["failed"] else JobStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        s.commit()
    return counters


def reconcile_job(
    session_factory: Callable[[], Session],
    client: OllamaClient,
    cfg: Any,
    *,
    redis: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The 01:45 IST reconcile (decisions 30 and 34): `research_index.reconcile` (keys and sheets), then the open
    `research_embed` failures retried once, and the failures of retired chunks closed. One `job_runs` row
    `research_index_reconcile`. Disabled: chunks are still compared (no model call)."""
    profile = ri.profile_of(cfg.research_embed_model)
    now = now or datetime.now(UTC)
    with session_factory() as s:
        run = JobRun(job=ri.RECONCILE_JOB, run_date=clock.today_ist(now), started_at=now)
        s.add(run)
        s.commit()
        run_id = run.id
    try:
        counters: dict[str, Any] = dict(ri.reconcile(session_factory, profile=profile))
        with session_factory() as s:
            counters["failures_closed"] = resolve_retired_failures(s)
            s.commit()
        counters["retried"] = counters["retry_failed"] = 0
        if bool(getattr(cfg, "research_index_enabled", False)):
            key = live_key(client, cfg.research_embed_model)
            if key is None:
                counters["model_unready"] = 1
            else:
                seen: set[uuid.UUID] = set()
                while True:
                    wait_for_people(redis)
                    with session_factory() as s:
                        todo = [c for c in pending(s, key.key, limit=50, retry=True) if c.id not in seen][:1]
                        if not todo:
                            break
                        seen.add(todo[0].id)
                        try:
                            res = embed_batch(s, client, key, todo, cfg)
                        except SourceTraceUnavailable:
                            s.rollback()
                            counters["model_unready"] = 1
                            break
                        s.commit()
                    counters["retried"] += res.embedded + res.reused
                    counters["retry_failed"] += res.failed
    except Exception as exc:
        with session_factory() as s:
            run = s.get(JobRun, run_id)
            run.status, run.error = JobStatus.FAILED, f"{exc.__class__.__name__}: {exc}"[:2000]
            run.finished_at = datetime.now(UTC)
            s.commit()
        raise
    with session_factory() as s:
        run = s.get(JobRun, run_id)
        run.counters = counters
        run.status = JobStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        s.commit()
    return run.counters


# ------------------------------------------------------------------------------------------------ the backfill


def backfill(
    session_factory: Callable[[], Session],
    client: OllamaClient | None,
    cfg: Any,
    *,
    chunks_only: bool = False,
    limit: int | None = None,
    pause_ms: int = 200,
    redis: Any | None = None,
    echo: Callable[[str], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """`aslms research-index run --backfill` (decision 30): phase by phase (judgments, final orders, substantive
    interim, case sheets, procedural bodies), every chunk set and sheet of the phase cut, then, unless `chunks_only`
    or the switch is off, every waiting chunk of the phase embedded. One commit per batch, a pause between batches and
    for the asking flag; stopped and started again, it carries on where it was. `limit` caps the vectors written. One
    `job_runs` row `research_index` per phase with its counters (`backfill` set)."""
    profile = ri.profile_of(cfg.research_embed_model)
    embed = not chunks_only and bool(getattr(cfg, "research_index_enabled", False)) and client is not None
    key = live_key(client, cfg.research_embed_model) if embed else None
    total: dict[str, Any] = dict.fromkeys(COUNTERS, 0)
    total["model_unready"] = 1 if embed and key is None else 0
    written = 0
    for phase, _where in ri.PHASES:
        started = datetime.now(UTC)
        counters: dict[str, Any] = dict.fromkeys(COUNTERS, 0)
        counters.update({"backfill": 1, "phase": phase})
        while True:
            with session_factory() as s:
                if phase == "sheets":
                    got = ri.sync_sheets(s, profile=profile, since=None)
                    s.commit()
                    counters["sheets"] += got["sheets"]
                    done = got["sheet_candidates"] == 0 or got["sheets"] == 0
                else:
                    got = ri.sync_sets(s, profile=profile, limit=SETS_PER_STEP, phase=phase)
                    s.commit()
                    counters["cut"] += got["cut"]
                    counters["chunks"] += got["chunks"]
                    counters["skipped"] += got["skipped"]
                    done = got["candidates"] == 0 or got["cut"] == 0
            if done:
                break
        if echo is not None:
            echo(
                f"{phase}: {counters['cut']} sets ({counters['chunks']} chunks), {counters['sheets']} sheets cut"
            )
        if key is not None:
            size = batch_size(cfg)
            while limit is None or written < limit:
                counters["waited_ms"] += wait_for_people(redis, sleep=sleep)
                with session_factory() as s:
                    want = size if limit is None else min(size, limit - written)
                    todo = pending(s, key.key, limit=want, phase=phase)
                    if not todo:
                        break
                    try:
                        res = embed_batch(s, client, key, todo, cfg)
                    except SourceTraceUnavailable:
                        s.rollback()
                        total["model_unready"] = 1
                        key = None
                        break
                    s.commit()
                counters["embedded"] += res.embedded
                counters["reused"] += res.reused
                counters["failed"] += res.failed
                written += res.embedded
                if res.embedded + res.reused + res.failed == 0:
                    break
                if pause_ms:
                    sleep(pause_ms / 1000)
            if echo is not None:
                echo(f"{phase}: {counters['embedded']} embedded, {counters['failed']} failed")
        with session_factory() as s:
            s.add(
                JobRun(
                    job=ri.JOB,
                    run_date=clock.today_ist(started),
                    started_at=started,
                    finished_at=datetime.now(UTC),
                    status=JobStatus.PARTIAL if counters["failed"] else JobStatus.SUCCEEDED,
                    counters=counters,
                )
            )
            s.commit()
        for k in COUNTERS:
            total[k] += counters[k]
        if limit is not None and written >= limit:
            break
    return total


__all__ = [
    "ASKING_KEY",
    "LiveKey",
    "backfill",
    "batch_size",
    "clear_asking",
    "embed_batch",
    "keep_alive",
    "live_key",
    "model_key",
    "options",
    "pending",
    "reconcile_job",
    "redis_client",
    "retire_unused",
    "run_job",
    "set_asking",
    "wait_for_people",
]


def scheduled_run(cfg: Any, session_factory: Callable[[], Session]) -> dict[str, Any]:
    """The scheduler's `aslms.research_index` task (decision 30): the job with a client of `ASSISTANT_OLLAMA_URL`."""
    return run_job(session_factory, OllamaClient(cfg.assistant_ollama_url), cfg, redis=redis_client(cfg))


def scheduled_reconcile(cfg: Any, session_factory: Callable[[], Session]) -> dict[str, Any]:
    """The scheduler's `aslms.research_index_reconcile` task at 01:45 IST (decision 30)."""
    return reconcile_job(
        session_factory, OllamaClient(cfg.assistant_ollama_url), cfg, redis=redis_client(cfg)
    )
