"""The research index's chunk sets and case sheets (design `research-index`, decisions 2, 9, 11, 13, 30, 32 and 33).

Reads only court information: current `order_sections` readings, and the court-public fields of `cases`,
`case_parties`, `case_acts`, `case_hearings` and `courts` (a unit test scans this module's SQL). Never notes, custody,
internal documents or drafts. No NAPIX call, no `fetch_queue` row, no model call (embedding is `research_embed`).

- `sync_sets` cuts the chunk set of every current reading whose key (body_sha256, form, parser_version,
  `CHUNKER_VERSION`) has none, one set per key (identical bodies are cut once); a lost race on the partial unique
  index counts `skipped`.
- `retire_orphans` retires the sets whose key lost its last current reading (`reading_gone`) and, in the reconcile,
  the sets of an older chunker version (`chunker_version`).
- `sync_sheets` writes a new case sheet when its text changes (`sheet_changed`) and retires a merged case's
  (`case_merged`).
- `reconcile` is the 01:45 IST full pass; `status` the data-health block; `rebuild` the audited
  `aslms research-index rebuild`.

Indexing is system work on derived data: no event, alert or audit row (decision 33), except the rebuild."""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aslms.domain.ops import JobRun, SourceFailure
from aslms.domain.research import ResearchChunk, ResearchChunkKind, ResearchEmbedding, ResearchRetireReason
from aslms.services import research_chunks as rc
from aslms.services.audit import Actor, write_audit

log = logging.getLogger(__name__)

JOB = "research_index"
RECONCILE_JOB = "research_index_reconcile"
FAILURE_KIND = "research_embed"
UNIQUE_SET = "ix_research_chunks_set_current"
UNIQUE_SHEET = "ix_research_chunks_sheet_current"
SHEET_BATCH = 500
WATERMARK_SLACK = timedelta(seconds=60)

# the backfill's order (decision 30): research is useful early
PHASES: tuple[tuple[str, str], ...] = (
    ("judgment", "s.form = 'judgment'"),
    ("final", "s.form = 'final'"),
    ("interim_substantive", "s.form = 'interim' AND NOT s.procedural"),
    ("sheets", ""),
    ("procedural", "s.form = 'interim' AND s.procedural"),
)


class NoProfile(LookupError):
    """`RESEARCH_EMBED_MODEL` names a model family with no profile (decision 6): nothing can be cut or embedded."""


def profile_of(model: str) -> rc.EmbedProfile:
    profile = rc.profile_for(model)
    if profile is None:
        raise NoProfile(f"the embedding model {model!r} has no profile in EMBED_PROFILES")
    return profile


def _now() -> datetime:
    return datetime.now(UTC)


def _unique(exc: IntegrityError, name: str) -> bool:
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    return getattr(diag, "constraint_name", None) == name or name in str(exc)


# ------------------------------------------------------------------------------------------------ chunk sets


_SET_CANDIDATES = """
    SELECT id, body_sha256, form, parser_version, body_text, paragraphs, parts FROM (
        SELECT DISTINCT ON (s.body_sha256, s.form, s.parser_version)
               s.id, s.body_sha256, s.form::text AS form, s.parser_version, s.body_text, s.paragraphs, s.parts,
               s.created_at
        FROM order_sections s
        WHERE s.replaced_at IS NULL AND length(btrim(s.body_text)) > 0 {since} {phase}
          AND NOT EXISTS (
              SELECT 1 FROM research_chunks c
              WHERE c.kind = 'order_body' AND c.retired_at IS NULL AND c.body_sha256 = s.body_sha256
                AND c.form = s.form AND c.parser_version = s.parser_version AND c.chunker_version = :cv)
        ORDER BY s.body_sha256, s.form, s.parser_version, s.created_at DESC
    ) k
    ORDER BY created_at DESC
    LIMIT :limit
"""


def sync_sets(
    session: Session,
    *,
    profile: rc.EmbedProfile,
    since: datetime | None = None,
    limit: int = 500,
    phase: str | None = None,
) -> dict[str, int]:
    """Decision 9: the sets of current readings without one, newest first, each in a savepoint. Returns `cut` (sets),
    `chunks` and `skipped` (a lost race, or a body that gave no chunk)."""
    where_phase = dict(PHASES).get(phase or "", "")
    sql = _SET_CANDIDATES.format(
        since="AND s.created_at >= :since" if since is not None else "",
        phase=f"AND {where_phase}" if where_phase else "",
    )
    params: dict[str, Any] = {"cv": rc.CHUNKER_VERSION, "limit": int(limit)}
    if since is not None:
        params["since"] = since
    rows = session.execute(text(sql), params).all()
    cap = rc.cap_chars(profile)
    out = {"cut": 0, "chunks": 0, "skipped": 0, "candidates": len(rows)}
    for row in rows:
        specs = rc.chunk_reading(row.form, row.body_text, row.paragraphs or [], row.parts or [], cap=cap)
        if not specs:
            out["skipped"] += 1
            continue
        try:
            with session.begin_nested():
                for sp in specs:
                    session.add(
                        ResearchChunk(
                            kind=ResearchChunkKind.ORDER_BODY,
                            body_sha256=row.body_sha256,
                            form=row.form,
                            parser_version=row.parser_version,
                            chunker_version=rc.CHUNKER_VERSION,
                            seq=sp.seq,
                            first_reading_id=row.id,
                            part=sp.part[:30],
                            para_first=sp.para_first,
                            para_last=sp.para_last,
                            txt_start=sp.txt_start,
                            txt_end=sp.txt_end,
                            split=sp.split,
                            context_line=sp.context_line,
                            text=sp.text,
                            embed_sha256=rc.input_sha256(profile, sp.context_line, sp.text),
                            chars=len(sp.text),
                        )
                    )
                session.flush()
        except IntegrityError as exc:
            if not _unique(exc, UNIQUE_SET):
                raise
            out["skipped"] += 1
            continue
        out["cut"] += 1
        out["chunks"] += len(specs)
    return out


def retire_orphans(
    session: Session,
    *,
    since: datetime | None = None,
    now: datetime | None = None,
    wait_for_new_sets: bool = False,
    hashes: set[str] | None = None,
) -> int:
    """Decision 13: the order chunk sets no current reading holds any more (`reading_gone`); with `since`, only the
    keys of readings replaced since then. The number of chunks retired.

    `wait_for_new_sets` (the 5-minute job): a set is retired only once every order that held it has the set of its
    current reading cut (or a current reading with no body), so its vectors stay while a replacing set with the same
    embedding inputs waits to be cut (decision 12: a parser-version bump needs no model call). The reconcile cuts
    before it retires vectors and does not need it. `hashes`, when given, receives the retired chunks' `embed_sha256`."""
    now = now or _now()
    params: dict[str, Any] = {"now": now}
    scope = ""
    if since is not None:
        scope = (
            "AND (c.body_sha256, c.form, c.parser_version) IN (SELECT r.body_sha256, r.form, r.parser_version "
            "FROM order_sections r WHERE r.replaced_at >= :since)"
        )
        params["since"] = since
    wait = ""
    if wait_for_new_sets:
        wait = f"""
              AND NOT EXISTS (
                  SELECT 1 FROM order_sections r
                  JOIN order_sections n ON n.order_id = r.order_id AND n.replaced_at IS NULL
                  WHERE r.body_sha256 = c.body_sha256 AND r.form = c.form AND r.parser_version = c.parser_version
                    {"AND r.replaced_at >= :since" if since is not None else ""}
                    AND length(btrim(n.body_text)) > 0
                    AND NOT EXISTS (
                        SELECT 1 FROM research_chunks x
                        WHERE x.kind = 'order_body' AND x.retired_at IS NULL AND x.body_sha256 = n.body_sha256
                          AND x.form = n.form AND x.parser_version = n.parser_version AND x.chunker_version = :cv))"""
        params["cv"] = rc.CHUNKER_VERSION
    rows = session.execute(
        text(
            f"""
            UPDATE research_chunks c SET retired_at = :now, retire_reason = 'reading_gone'
            WHERE c.kind = 'order_body' AND c.retired_at IS NULL {scope}
              AND NOT EXISTS (
                  SELECT 1 FROM order_sections s
                  WHERE s.replaced_at IS NULL AND s.body_sha256 = c.body_sha256 AND s.form = c.form
                    AND s.parser_version = c.parser_version){wait}
            RETURNING c.embed_sha256
            """
        ),
        params,
    ).all()
    if hashes is not None:
        hashes.update(r[0] for r in rows)
    return len(rows)


def retire_old_chunker(session: Session, *, now: datetime | None = None) -> int:
    """Sets cut by another chunker version (`chunker_version`); the reconcile cuts them again."""
    n = session.execute(
        update(ResearchChunk)
        .where(
            ResearchChunk.kind == ResearchChunkKind.ORDER_BODY,
            ResearchChunk.retired_at.is_(None),
            ResearchChunk.chunker_version != rc.CHUNKER_VERSION,
        )
        .values(retired_at=now or _now(), retire_reason=ResearchRetireReason.CHUNKER_VERSION)
        .execution_options(synchronize_session=False)
    ).rowcount
    return int(n or 0)


# ------------------------------------------------------------------------------------------------ case sheets


def sheet_inputs(session: Session, case_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Decision 11: each live case's sheet text, from court-public fields only (`cases`, `courts`, `case_parties`,
    `case_acts`, `case_hearings`)."""
    ids = list(dict.fromkeys(case_ids))
    if not ids:
        return {}
    cases = session.execute(
        text(
            """
            SELECT c.id, c.case_type_text, coalesce(c.reg_year, c.filing_year) AS year,
                   coalesce(c.court_est_name, ct.name) AS court, c.category, c.sub_category, c.status::text AS status,
                   c.disposal_nature, c.short_order, c.petitioner_summary, c.respondent_summary
            FROM cases c JOIN courts ct ON ct.id = c.court_id
            WHERE c.id = ANY(:ids) AND c.merged_into_case_id IS NULL
            """
        ),
        {"ids": ids},
    ).all()
    parties: dict[uuid.UUID, dict[str, list[str]]] = defaultdict(lambda: {"petitioner": [], "respondent": []})
    for cid, role, name in session.execute(
        text(
            "SELECT case_id, role::text, name FROM case_parties WHERE case_id = ANY(:ids) AND is_current "
            "ORDER BY case_id, role, party_no"
        ),
        {"ids": ids},
    ).all():
        parties[cid]["petitioner" if role == "petitioner" else "respondent"].append(name)
    acts: dict[uuid.UUID, list[str]] = defaultdict(list)
    for cid, name, section in session.execute(
        text(
            "SELECT case_id, act_name_as_listed, section FROM case_acts WHERE case_id = ANY(:ids) "
            "ORDER BY case_id, created_at, id"
        ),
        {"ids": ids},
    ).all():
        acts[cid].append(f"{name} {section}".strip())
    orders: dict[uuid.UUID, list[str]] = defaultdict(list)
    for cid, so in session.execute(
        text(
            """
            SELECT case_id, short_order_text FROM (
                SELECT h.case_id, h.short_order_text,
                       row_number() OVER (PARTITION BY h.case_id ORDER BY h.business_date DESC NULLS LAST, h.id) AS n
                FROM case_hearings h WHERE h.case_id = ANY(:ids)
            ) x WHERE n <= :n ORDER BY case_id, n
            """
        ),
        {"ids": ids, "n": rc.SHEET_HEARINGS},
    ).all():
        if so:
            orders[cid].append(so)
    out: dict[uuid.UUID, str] = {}
    for row in cases:
        case = {
            "case_type": row.case_type_text,
            "year": row.year,
            "court": row.court,
            "category": row.category,
            "sub_category": row.sub_category,
            "status": row.status,
            "disposal_nature": row.disposal_nature,
            "short_order": row.short_order,
            "petitioner_summary": row.petitioner_summary,
            "respondent_summary": row.respondent_summary,
        }
        out[row.id] = rc.case_sheet_text(case, parties[row.id], acts[row.id], orders[row.id])
    return out


def _changed_cases(
    session: Session, since: datetime | None, limit: int, after_id: uuid.UUID | None = None
) -> list[tuple[uuid.UUID, datetime | None]]:
    """The cases to compare, with the time of their latest change. With `since`: the cases with a change at or after
    `since`, oldest change first, as a keyset page after (`since`, `after_id`) when `after_id` is given, so the caller
    can move its cursor past a full page (a page of cases whose sheets did not change is never read twice). With None:
    the live cases without a sheet, newest first."""
    if since is None:
        sql = """
            SELECT c.id, c.updated_at FROM cases c
            WHERE c.merged_into_case_id IS NULL AND NOT EXISTS (
                SELECT 1 FROM research_chunks r
                WHERE r.kind = 'case_sheet' AND r.retired_at IS NULL AND r.case_id = c.id)
            ORDER BY c.updated_at DESC, c.id LIMIT :limit
        """
        return [(r[0], r[1]) for r in session.execute(text(sql), {"limit": int(limit)}).all()]
    params: dict[str, Any] = {"since": since, "limit": int(limit)}
    having = ""
    if after_id is not None:
        having = "HAVING (max(updated_at), id) > (CAST(:since AS timestamptz), CAST(:after AS uuid))"
        params["after"] = after_id
    sql = f"""
        SELECT id, max(updated_at) AS changed FROM (
            SELECT c.id, c.updated_at FROM cases c WHERE c.updated_at >= :since
            UNION SELECT p.case_id, p.updated_at FROM case_parties p WHERE p.updated_at >= :since
            UNION SELECT a.case_id, a.updated_at FROM case_acts a WHERE a.updated_at >= :since
            UNION SELECT h.case_id, h.updated_at FROM case_hearings h WHERE h.updated_at >= :since
        ) x GROUP BY id {having} ORDER BY changed, id LIMIT :limit
    """
    return [(r[0], r[1]) for r in session.execute(text(sql), params).all()]


def write_sheets(
    session: Session, case_ids: list[uuid.UUID], *, profile: rc.EmbedProfile, now: datetime | None = None
) -> dict[str, int]:
    """Decision 11 for the given cases: a new sheet when the text's hash differs from the current sheet's (the old one
    `sheet_changed`), a merged case's sheet retired (`case_merged`). Returns `sheets` (new), `sheets_retired`."""
    now = now or _now()
    out = {"sheets": 0, "sheets_retired": 0, "skipped": 0}
    if not case_ids:
        return out
    texts = sheet_inputs(session, case_ids)
    current = {
        c.case_id: c
        for c in session.scalars(
            select(ResearchChunk).where(
                ResearchChunk.kind == ResearchChunkKind.CASE_SHEET,
                ResearchChunk.retired_at.is_(None),
                ResearchChunk.case_id.in_(case_ids),
            )
        ).all()
    }
    for cid in dict.fromkeys(case_ids):
        sheet = texts.get(cid)
        old = current.get(cid)
        if sheet is None:  # merged (or gone): its sheet is retired
            if old is not None:
                old.retired_at, old.retire_reason = now, ResearchRetireReason.CASE_MERGED
                out["sheets_retired"] += 1
            continue
        digest = rc.sha256(sheet)
        if old is not None and old.sheet_sha256 == digest:
            continue
        try:
            with session.begin_nested():
                if old is not None:
                    old.retired_at, old.retire_reason = now, ResearchRetireReason.SHEET_CHANGED
                    session.flush()
                    out["sheets_retired"] += 1
                session.add(
                    ResearchChunk(
                        kind=ResearchChunkKind.CASE_SHEET,
                        chunker_version=rc.CHUNKER_VERSION,
                        seq=0,
                        case_id=cid,
                        context_line=rc.SHEET_CONTEXT,
                        text=sheet,
                        sheet_sha256=digest,
                        embed_sha256=rc.input_sha256(profile, rc.SHEET_CONTEXT, sheet),
                        chars=len(sheet),
                    )
                )
                session.flush()
        except IntegrityError as exc:
            if not _unique(exc, UNIQUE_SHEET):
                raise
            out["skipped"] += 1
            continue
        out["sheets"] += 1
    session.flush()
    return out


def sync_sheets(
    session: Session,
    *,
    profile: rc.EmbedProfile,
    since: datetime | None = None,
    after_id: uuid.UUID | None = None,
    limit: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Decision 11: the cases changed since `since` (after `after_id` among those changed at `since`; with None: the
    live cases without a sheet), at most `limit` (`SHEET_BATCH`). `sheet_candidates` is the page's size and, with
    `since`, `sheet_cursor` the (time, case id) of its last case, from which the next page starts."""
    page = _changed_cases(session, since, int(limit or SHEET_BATCH), after_id)
    ids = [cid for cid, _ in page]
    out: dict[str, Any] = write_sheets(session, ids, profile=profile, now=now)
    out["sheet_candidates"] = len(ids)
    out["sheet_cursor"] = (page[-1][1], page[-1][0]) if since is not None and page else None
    return out


def _merged_with_sheet(session: Session, limit: int) -> list[uuid.UUID]:
    return list(
        session.scalars(
            text(
                "SELECT r.case_id FROM research_chunks r JOIN cases c ON c.id = r.case_id "
                "WHERE r.kind = 'case_sheet' AND r.retired_at IS NULL AND c.merged_into_case_id IS NOT NULL "
                "LIMIT :limit"
            ),
            {"limit": int(limit)},
        ).all()
    )


# ------------------------------------------------------------------------------------------------ the reconcile


def reconcile(
    session_factory: Callable[[], Session],
    *,
    profile: rc.EmbedProfile,
    batch: int = 500,
    echo: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Decision 30, the daily full pass at 01:45 IST: sets of an older chunker version retired, orphan sets retired,
    every current key without a set cut, every live case's sheet compared by hash, merged cases' sheets retired, and
    vectors no current chunk uses retired. One commit per batch."""
    from aslms.services import research_embed

    total = defaultdict(int)
    with session_factory() as s:
        total["retired_chunker"] += retire_old_chunker(s)
        total["retired"] += retire_orphans(s)
        s.commit()
    while True:
        with session_factory() as s:
            got = sync_sets(s, profile=profile, limit=batch)
            s.commit()
        for k in ("cut", "chunks", "skipped"):
            total[k] += got[k]
        if got["candidates"] == 0 or got["cut"] == 0:
            break
    last: uuid.UUID | None = None
    while True:
        with session_factory() as s:
            ids = list(
                s.scalars(
                    text(
                        "SELECT c.id FROM cases c WHERE c.merged_into_case_id IS NULL "
                        "AND (CAST(:last AS uuid) IS NULL OR c.id > CAST(:last AS uuid)) ORDER BY c.id LIMIT :n"
                    ),
                    {"last": last, "n": SHEET_BATCH},
                ).all()
            )
            if not ids:
                break
            got = write_sheets(s, ids, profile=profile)
            s.commit()
        last = ids[-1]
        total["sheets"] += got["sheets"]
        total["sheets_retired"] += got["sheets_retired"]
    with session_factory() as s:
        merged = _merged_with_sheet(s, 10_000)
        got = write_sheets(s, merged, profile=profile)
        total["sheets_retired"] += got["sheets_retired"]
        total["vectors_retired"] += research_embed.retire_unused(s)
        s.commit()
    if echo is not None:
        echo(", ".join(f"{k} {v}" for k, v in sorted(total.items())))
    return dict(total)


# ------------------------------------------------------------------------------------------------ status


def counts(session: Session, live_key: str | None) -> dict[str, Any]:
    """Chunks current by kind, vectors of the live key and of other keys, waiting and coverage (counts only)."""
    by_kind = {
        str(getattr(k, "value", k)): int(n)
        for k, n in session.execute(
            select(ResearchChunk.kind, func.count())
            .where(ResearchChunk.retired_at.is_(None))
            .group_by(ResearchChunk.kind)
        ).all()
    }
    total = sum(by_kind.values())
    embedded = 0
    if live_key:
        embedded = int(
            session.scalar(
                text(
                    "SELECT count(*) FROM research_chunks c WHERE c.retired_at IS NULL AND EXISTS ("
                    "SELECT 1 FROM research_embeddings e WHERE e.input_sha256 = c.embed_sha256 "
                    "AND e.model_key = :key AND e.retired_at IS NULL)"
                ),
                {"key": live_key},
            )
            or 0
        )
    keys = {
        k: int(n)
        for k, n in session.execute(
            select(ResearchEmbedding.model_key, func.count())
            .where(ResearchEmbedding.retired_at.is_(None))
            .group_by(ResearchEmbedding.model_key)
        ).all()
    }
    return {
        "chunks": {
            "order_body": by_kind.get("order_body", 0),
            "case_sheet": by_kind.get("case_sheet", 0),
            "total": total,
        },
        "vectors_live": embedded,
        "waiting": max(0, total - embedded) if live_key else total,
        "coverage": round(embedded / total, 4) if total and live_key else 0.0,
        "other_keys": {k: n for k, n in keys.items() if k != live_key},
        "vectors_by_key": keys,
    }


def table_sizes(session: Session) -> dict[str, int]:
    return {
        t: int(session.scalar(text(f"SELECT pg_total_relation_size('{t}')")) or 0)
        for t in ("research_chunks", "research_embeddings")
    }


def failures_open(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(SourceFailure)
            .where(SourceFailure.kind == FAILURE_KIND, SourceFailure.resolved_at.is_(None))
        )
        or 0
    )


def last_run(session: Session, job: str = JOB) -> dict[str, Any] | None:
    run = session.scalar(select(JobRun).where(JobRun.job == job).order_by(JobRun.started_at.desc()).limit(1))
    if run is None:
        return None
    return {
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "status": getattr(run.status, "value", run.status),
        "counters": dict(run.counters or {}),
    }


def status(
    session: Session,
    *,
    enabled: bool,
    live_key: str | None,
    readiness: str,
    timeout_s: int,
    restore_s: int,
) -> dict[str, Any]:
    """Decision 32, the data-health block: `enabled`, `live_model_key`, `readiness`, counts in isolated parts under
    `timeout_s` (a slow part is left out and named in `timed_out`), open failures, the last run, the table sizes."""
    from aslms.services.reporting_common import isolated

    timed_out: list[str] = []
    got, late = isolated(
        session, timeout_s, restore_s, lambda: counts(session, live_key), part="research counts"
    )
    if late:
        timed_out.append("counts")
    sizes, late = isolated(session, timeout_s, restore_s, lambda: table_sizes(session), part="research sizes")
    if late:
        timed_out.append("sizes")
    got = got or {}
    return {
        "enabled": bool(enabled),
        "live_model_key": live_key,
        "readiness": readiness,
        "chunks": got.get("chunks"),
        "vectors_live": got.get("vectors_live"),
        "waiting": got.get("waiting"),
        "coverage": got.get("coverage"),
        "other_keys": got.get("other_keys"),
        "failures_open": failures_open(session),
        "last_run": last_run(session),
        "last_reconcile": last_run(session, RECONCILE_JOB),
        "table_sizes": sizes,
        "timed_out": timed_out,
    }


# ------------------------------------------------------------------------------------------------ rebuild


def rebuild(
    session: Session,
    *,
    chunks: bool,
    embeddings: bool,
    live_key: str | None,
    actor: Actor,
    now: datetime | None = None,
) -> dict[str, Any]:
    """`aslms research-index rebuild` (decisions 7 and 33): `chunks` retires every current chunk (`rebuilt`; the job
    cuts them again under the live profile, and the vectors no chunk uses are retired with them); `embeddings` retires
    every vector of a key other than the live one (`model_changed`). One audit row `research_index.rebuilt` with what
    was retired and the counts."""
    if not chunks and not embeddings:
        raise ValueError("choose --chunks or --embeddings")
    now = now or _now()
    after: dict[str, Any] = {
        "chunks": bool(chunks),
        "embeddings": bool(embeddings),
        "live_model_key": live_key,
    }
    if chunks:
        n = session.execute(
            update(ResearchChunk)
            .where(ResearchChunk.retired_at.is_(None))
            .values(retired_at=now, retire_reason=ResearchRetireReason.REBUILT)
            .execution_options(synchronize_session=False)
        ).rowcount
        after["chunks_retired"] = int(n or 0)
        from aslms.services import research_embed

        after["vectors_retired_unused"] = research_embed.retire_unused(session, now=now)
    if embeddings:
        if not live_key:
            raise ValueError(
                "the live model key cannot be read; the model server must answer before a rebuild"
            )
        by_key = dict(
            session.execute(
                select(ResearchEmbedding.model_key, func.count())
                .where(ResearchEmbedding.retired_at.is_(None), ResearchEmbedding.model_key != live_key)
                .group_by(ResearchEmbedding.model_key)
            ).all()
        )
        session.execute(
            update(ResearchEmbedding)
            .where(ResearchEmbedding.retired_at.is_(None), ResearchEmbedding.model_key != live_key)
            .values(retired_at=now, retire_reason=ResearchRetireReason.MODEL_CHANGED)
            .execution_options(synchronize_session=False)
        )
        after["vectors_retired_by_key"] = {k: int(v) for k, v in by_key.items()}
    session.flush()
    write_audit(session, actor, "research_index.rebuilt", "research_index", None, after=after)
    return after


def iter_batches(values: Iterable[Any], size: int) -> Iterable[list[Any]]:
    chunk: list[Any] = []
    for v in values:
        chunk.append(v)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def watermark_from(counters: dict[str, Any] | None, key: str = "watermark") -> datetime | None:
    raw = (counters or {}).get(key)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def next_watermark(started: datetime) -> str:
    return (started - WATERMARK_SLACK).isoformat()


def elapsed(started: float) -> float:
    return time.monotonic() - started


__all__ = [
    "FAILURE_KIND",
    "JOB",
    "PHASES",
    "RECONCILE_JOB",
    "NoProfile",
    "counts",
    "profile_of",
    "rebuild",
    "reconcile",
    "retire_old_chunker",
    "retire_orphans",
    "sheet_inputs",
    "status",
    "sync_sets",
    "sync_sheets",
    "write_sheets",
]
