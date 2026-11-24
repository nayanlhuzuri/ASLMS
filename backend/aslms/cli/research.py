"""`aslms research-index` (design `research-index`, "Services", decisions 7, 30 to 33): the meaning search for research.

- `status`: the data-health block (`enabled`, the live model key, readiness, chunks by kind, vectors of the live key,
  waiting, coverage, other keys, open failures, the last runs, table sizes; `timed_out` names a part that ran out of
  time).
- `run [--backfill] [--chunks-only] [--limit N] [--pause-ms N]`: without `--backfill`, one run of the 5-minute job;
  with it, phase by phase (judgments, final orders, substantive interim, case sheets, procedural bodies) every chunk set
  and sheet cut and, unless `--chunks-only` or the switch is off, every waiting chunk embedded; one commit per batch,
  a pause between batches and while a person is asking; stopped and started again, it carries on. Run it outside the
  app services: `docker compose run -d --rm api aslms research-index run --backfill`.
- `rebuild (--chunks | --embeddings) --yes`: `--chunks` retires every current chunk (cut again by the job under the live
  profile); `--embeddings` retires every vector of a model key other than the live one. Audited
  (`research_index.rebuilt`).
- `search "question" [--scope research|my_cases] [--login EMAIL] [--explain]`: read-only; prints the words list, the
  meaning list and the fused order with order ids, case numbers, pages and scores. Sends no text to the chat model.

No NAPIX call and no `fetch_queue` row. Indexing writes no audit row; the rebuild writes one."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid

import typer
from rich import print as rprint
from sqlalchemy import select, text

from aslms.core.config import get_settings
from aslms.db.session import get_sessionmaker
from aslms.integration.ollama import OllamaClient
from aslms.integration.sourcetrace.connector import AskRequest, AskScope, CaseContext
from aslms.services import research_embed as remb
from aslms.services import research_index as ri
from aslms.services import research_search as rsearch

research_app = typer.Typer(
    no_args_is_help=True, help="The research index (meaning search): status, run, rebuild, search"
)


def _client(cfg) -> OllamaClient:
    return OllamaClient(cfg.assistant_ollama_url)


def _readiness(cfg, client: OllamaClient) -> tuple[str | None, str]:
    return remb.readiness(cfg, client=client)


@research_app.command("status")
def status() -> None:
    """The research index's state (counts only)."""
    cfg = get_settings()
    key, readiness = _readiness(cfg, _client(cfg))
    with get_sessionmaker()() as s:
        block = ri.status(
            s,
            enabled=cfg.research_index_enabled,
            live_key=key,
            readiness=readiness,
            timeout_s=cfg.order_sections_status_timeout_seconds,
            restore_s=60,
        )
        s.rollback()
    rprint(json.dumps(block, default=str, indent=2))


@research_app.command("run")
def run(
    backfill: bool = typer.Option(False, "--backfill", help="every waiting chunk, phase by phase, resumable"),
    chunks_only: bool = typer.Option(False, "--chunks-only", help="cut chunk sets and sheets; call no model"),
    limit: int | None = typer.Option(None, "--limit", min=1, help="at most this many vectors written"),
    pause_ms: int = typer.Option(200, "--pause-ms", min=0, max=60000, help="pause between batches"),
) -> None:
    """One run of the 5-minute job, or the backfill."""
    cfg = get_settings()
    client = _client(cfg)
    redis = remb.redis_client(cfg)
    Session = get_sessionmaker()
    if backfill:
        got = remb.backfill(
            Session,
            None if chunks_only else client,
            cfg,
            chunks_only=chunks_only,
            limit=limit,
            pause_ms=pause_ms,
            redis=redis,
            echo=rprint,
        )
    elif chunks_only:
        profile = ri.profile_of(cfg.research_embed_model)
        with Session() as s:
            got = ri.sync_sets(s, profile=profile, limit=limit or 500)
            got.update(ri.sync_sheets(s, profile=profile, since=None, limit=limit or ri.SHEET_BATCH))
            s.commit()
    else:
        got = remb.run_job(Session, client, cfg, redis=redis)
    rprint(json.dumps(got, default=str, indent=2))


@research_app.command("rebuild")
def rebuild(
    chunks: bool = typer.Option(False, "--chunks", help="retire every current chunk (cut again by the job)"),
    embeddings: bool = typer.Option(
        False, "--embeddings", help="retire the vectors of keys other than the live one"
    ),
    yes: bool = typer.Option(False, "--yes", help="confirm"),
) -> None:
    """Retire chunks or old vectors (audited `research_index.rebuilt`)."""
    if chunks == embeddings:
        raise typer.BadParameter("choose exactly one of --chunks or --embeddings")
    if not yes:
        raise typer.BadParameter("add --yes to confirm")
    from aslms.cli.pipeline import _cli_actor

    cfg = get_settings()
    key = None
    if embeddings:
        live = remb.live_key(_client(cfg), cfg.research_embed_model)
        if live is None:
            raise typer.BadParameter(
                "the embedding model is not held on the model server; the live key is unknown"
            )
        key = live.key
    with get_sessionmaker()() as s:
        actor, _member = _cli_actor(s)
        after = ri.rebuild(s, chunks=chunks, embeddings=embeddings, live_key=key, actor=actor)
        s.commit()
    rprint(json.dumps(after, default=str, indent=2))


@research_app.command("search")
def search(
    question: str = typer.Argument(..., help="the question, as an officer would ask it"),
    scope: str = typer.Option("research", "--scope", help="research or my_cases"),
    login: str | None = typer.Option(
        None, "--login", help="for my_cases: the login whose cases are searched"
    ),
    explain: bool = typer.Option(False, "--explain", help="print the two lists and the fused order"),
) -> None:
    """A read-only search through the index (Verification 6). Sends nothing to the chat model."""
    if scope not in ("research", "my_cases"):
        raise typer.BadParameter("scope is research or my_cases")
    cfg = get_settings()
    client = _client(cfg)
    Session = get_sessionmaker()
    focus: tuple[CaseContext, ...] = ()
    with Session() as s:
        if scope == "my_cases":
            from aslms.domain.org import User
            from aslms.services import assistant_sources as src

            user = s.scalar(select(User).where(User.email == (login or "").strip().lower()))
            if user is None:
                raise typer.BadParameter("--login names no login")
            ids, _trunc = src.focus_cases(s, user, "my_cases", None)
            focus = tuple(CaseContext(**c) for c in src.case_contexts(s, ids or []))
        s.rollback()
    key, _readiness_ = _readiness(cfg, client)
    query = (
        asyncio.run(rsearch.embed_question(client, cfg, question, key))
        if key
        else rsearch.QueryVector(None, "model_unready")
    )
    request = AskRequest(
        request_id=uuid.uuid4(),
        question=question,
        scope=AskScope(kind=scope, focus=focus, orders="all" if scope == "research" else "focus"),  # type: ignore[arg-type]
    )
    from aslms.services.assistant_preview import Budget

    profile = rsearch.rc.profile_for(cfg.research_embed_model)
    with Session() as s:
        s.execute(text("SET TRANSACTION READ ONLY"))
        res = rsearch.passages(
            s,
            request,
            Budget(60.0, 30_000, threading.Event()),
            query=query,
            dims=profile.dims if profile else 768,
            filters=rsearch.Filters(),
            limit=cfg.assistant_ollama_sources,
            source_chars=cfg.assistant_ollama_source_chars,
            candidates=cfg.research_candidates,
            exact_max=cfg.research_exact_max,
            ef_search=cfg.research_ef_search,
        )
        rows = []
        for p in res.passages:
            if p.kind == "order" and p.holder:
                case_no = s.scalar(
                    text("SELECT case_no_text FROM cases WHERE id = :c"), {"c": p.holder.case_id}
                )
                rows.append(
                    {
                        "kind": "order",
                        "order_id": str(p.holder.order_id),
                        "case_no": case_no,
                        "page": p.page,
                        "paragraphs": [p.para_first, p.para_last],
                        "match": p.match,
                        "score": round(p.score, 5),
                        "same_words_in": p.holder.same_words_in,
                        "context": p.context_line,
                    }
                )
            elif p.kind == "sheet":
                rows.append({"kind": "case_sheet", "case_id": str(p.case_id), "score": round(p.score, 5)})
            elif p.page_passage is not None:
                rows.append(
                    {
                        "kind": "page",
                        "document_id": str(p.page_passage.document_id),
                        "page": p.page_passage.page,
                        "score": round(p.score, 5),
                    }
                )
        s.rollback()
    out = {
        "kind": res.kind,
        "reason": res.reason,
        "lists": res.counts,
        "fused": res.fused,
        "stale_dropped": res.stale_dropped,
        "passages": rows if explain else len(rows),
    }
    rprint(json.dumps(out, default=str, indent=2))
