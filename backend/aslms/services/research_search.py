"""Hybrid retrieval over the research index (design `research-index`, decisions 3, 13 and 15 to 21).

For the Assistant's All Court Orders (`research`), My Cases (`my_cases`) and the related orders of This Case, in
ollama mode with `RESEARCH_INDEX_ENABLED`:
- (a) words: `research_chunks.search_vector @@ websearch_to_tsquery('english', question)` ranked by `ts_rank_cd`;
- (b) meaning: the question's vector against the live key's vectors (HNSW with `hnsw.ef_search` and
  `hnsw.iterative_scan = relaxed_order` for large sets; an exact scan for My Cases and small filtered sets);
- (c) court filings of My Cases by today's page word search (`assistant_preview.search_passages`, unchanged);
- (d) court orders of the scope not yet in the index (no current reading, or no chunk set for its key), by today's
  page word search, so nothing new is missing.

The lists are merged by reciprocal rank fusion (k = 60), weighted by the order's own reading (procedural × 0.5,
judgment or final × 1.2), shared bodies kept once on the newest order in scope (`same_words_in`), at most 2 passages
per order with adjacent chunks joined, and each passage read small-to-big: the matched paragraphs and their neighbours
in the same part up to `ASSISTANT_OLLAMA_SOURCE_CHARS`. A hit is cited only through a current reading whose
`text_sha256` equals the SHA-256 of today's stored text; otherwise that order is dropped and counted
(`stale_dropped`). Everything runs in the caller's read-only transaction under its `Budget`; every setting is
`SET LOCAL`. Reads only court information: `research_chunks`, `research_embeddings`, `order_sections`, `orders`,
`documents`, `document_text`, `cases`, `case_parties` and `courts` (a unit test scans this module's SQL)."""

from __future__ import annotations

import asyncio
import re
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import and_, exists, not_, select, text
from sqlalchemy.orm import Session

from aslms.domain.documents import Document
from aslms.integration.ollama import OllamaClient
from aslms.integration.sourcetrace.connector import AskRequest, SourceTraceError
from aslms.services import research_chunks as rc
from aslms.services import research_embed as remb
from aslms.services.assistant_preview import Budget, Passage, PreviewConnector, search_passages
from aslms.services.assistant_sources import court_order_condition

RRF_K = 60
WEIGHT_PROCEDURAL = 0.5
WEIGHT_JUDGMENT = 1.2
WEIGHT_OTHER = 1.0
PASSAGES_PER_ORDER = 2
UNINDEXED_DOCS = 5
FILING_PASSAGES = 4
EXCERPT_CHARS = 1000
OUTCOMES = ("allowed", "partly_allowed", "dismissed", "disposed_of", "withdrawn", "closed")
FORMS = ("judgment", "final", "interim")
CITE_MAX = 80
ACT_MAX = 200
STATE_PARTY_SQL = r"(STATE\s+OF\s+ASSAM|GO?VE?R?N?M?E?N?T\.?\s*OF\s+ASSAM)"  # insights_rules.STATE_PARTY_RE


# ------------------------------------------------------------------------------------------------ filters


class BadFilter(ValueError):
    """400 `bad_filter`: an unknown outcome, form or act key, a citation too long, or `from` after `to`."""


@dataclass(frozen=True)
class Filters:
    """Decision 20, court-public values the asker typed."""

    forms: tuple[str, ...] = ()
    substantive_only: bool = False
    outcomes: tuple[str, ...] = ()
    against_state: bool = False
    cites: str | None = None
    act: str | None = None
    date_from: date | None = None
    date_to: date | None = None

    @property
    def any(self) -> bool:
        return bool(
            self.forms
            or self.substantive_only
            or self.outcomes
            or self.against_state
            or self.cites
            or self.act
            or self.date_from
            or self.date_to
        )

    def stored(self) -> dict[str, Any]:
        """The filters as kept in `scope_info.filters` and `assistant.asked`."""
        out: dict[str, Any] = {}
        if self.forms:
            out["forms"] = list(self.forms)
        if self.substantive_only:
            out["substantive_only"] = True
        if self.outcomes:
            out["outcomes"] = list(self.outcomes)
        if self.against_state:
            out["against_state"] = True
        if self.cites:
            out["cites"] = self.cites
        if self.act:
            out["act"] = self.act
        if self.date_from:
            out["from"] = self.date_from.isoformat()
        if self.date_to:
            out["to"] = self.date_to.isoformat()
        return out


def collapse(value: str) -> str:
    """Row 250's citation normalisation: whitespace runs collapsed, trimmed."""
    return re.sub(r"\s+", " ", value or "").strip()


def parse_filters(raw: dict[str, Any] | None, *, known_acts: set[str] | None = None) -> Filters:
    """`POST /assistant/ask`'s `filters`, checked (decision 20). `known_acts`, when given, is the set of act keys row
    250 has read; an unknown key is refused."""
    if not raw:
        return Filters()
    forms = tuple(dict.fromkeys(raw.get("forms") or ()))
    if any(f not in FORMS for f in forms):
        raise BadFilter("forms are judgment, final or interim")
    outcomes = tuple(dict.fromkeys(raw.get("outcomes") or ()))
    if any(o not in OUTCOMES for o in outcomes):
        raise BadFilter("an outcome is one of " + ", ".join(OUTCOMES))
    cites = collapse(raw.get("cites") or "") or None
    if cites and len(cites) > CITE_MAX:
        raise BadFilter(f"a citation is at most {CITE_MAX} characters")
    act = (raw.get("act") or "").strip() or None
    if act and (len(act) > ACT_MAX or (known_acts is not None and act not in known_acts)):
        raise BadFilter("no such act key")
    d_from, d_to = raw.get("from"), raw.get("to")
    if d_from and d_to and d_from > d_to:
        raise BadFilter("from is after to")
    return Filters(
        forms=forms,
        substantive_only=bool(raw.get("substantive_only")),
        outcomes=outcomes,
        against_state=bool(raw.get("against_state")),
        cites=cites,
        act=act,
        date_from=d_from,
        date_to=d_to,
    )


def act_known(session: Session, act: str) -> bool:
    """An act key row 250 has read in some current reading (uses `ix_order_sections_facts_acts`)."""
    import json

    return bool(
        session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM order_sections WHERE replaced_at IS NULL "
                "AND (facts -> 'acts') @> CAST(:j AS jsonb))"
            ),
            {"j": json.dumps([{"act_key": act}])},
        )
    )


# ------------------------------------------------------------------------------------------------ filter choices
# design research-index-portal, "Services": the lists the portal's Act and Cites a Judgment fields pick from, built
# from current court-order readings only (row 250's `facts.acts` and `facts.judgments`), the same for every user.

CHOICES_SQL_SECONDS = 15
CHOICES_CACHE_SECONDS = 21600  # 6 hours: acts and citations change slowly
CHOICES_LIMIT = 20
CHOICES_LIMIT_MAX = 50
CHOICE_KINDS = ("act", "cites")
_CHOICES_SQL = {
    "act": (
        "SELECT a.item ->> 'act_key' AS value, mode() WITHIN GROUP (ORDER BY a.item ->> 'act') AS label, "
        "NULL AS detail, count(DISTINCT s.id) AS orders FROM order_sections s "
        "CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(s.facts -> 'acts') = 'array' "
        "THEN s.facts -> 'acts' ELSE '[]'::jsonb END) AS a(item) "
        "WHERE s.replaced_at IS NULL AND coalesce(a.item ->> 'act_key', '') <> '' GROUP BY 1"
    ),
    "cites": (
        "SELECT j.item ->> 'citation' AS value, j.item ->> 'citation' AS label, "
        "mode() WITHIN GROUP (ORDER BY j.item ->> 'case_name') AS detail, count(DISTINCT s.id) AS orders "
        "FROM order_sections s "
        "CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(s.facts -> 'judgments') = 'array' "
        "THEN s.facts -> 'judgments' ELSE '[]'::jsonb END) AS j(item) "
        "WHERE s.replaced_at IS NULL AND coalesce(j.item ->> 'citation', '') <> '' GROUP BY 1"
    ),
}
_choices_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_choices_locks = {k: threading.Lock() for k in CHOICE_KINDS}


def _fold(value: str | None) -> str:
    """Lower case, every non-letter or digit a space, whitespace collapsed (the `q` match)."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).split())


def _choices_list(session: Session, kind: str, restore_seconds: int) -> list[dict[str, Any]] | None:
    """The cached full list of `kind`, or None while another request builds it or after a timeout."""
    from aslms.services.reporting_common import isolated

    hit = _choices_cache.get(kind)
    if hit is not None and time.monotonic() - hit[0] <= CHOICES_CACHE_SECONDS:
        return hit[1]
    lock = _choices_locks[kind]
    if not lock.acquire(blocking=False):
        return None  # one build at a time; this request answers not ready
    try:
        rows, late = isolated(
            session,
            CHOICES_SQL_SECONDS,
            restore_seconds,
            lambda: session.execute(text(_CHOICES_SQL[kind])).all(),
            part=f"filter choices ({kind})",
        )
        if late or rows is None:
            return None
        items = [
            {
                "value": r.value,
                "label": r.label or r.value,
                "detail": r.detail or None,
                "orders": int(r.orders),
                "_fold": " ".join((_fold(r.value), _fold(r.label), _fold(r.detail))),
            }
            for r in rows
        ]
        items.sort(key=lambda i: (-i["orders"], i["label"].lower(), i["value"]))
        _choices_cache[kind] = (time.monotonic(), items)
        return items
    finally:
        lock.release()


def filter_choices(
    session: Session,
    kind: str,
    q: str | None = None,
    limit: int = CHOICES_LIMIT,
    *,
    restore_seconds: int = 30,
) -> dict[str, Any]:
    """`GET /assistant/filter-choices`: `{kind, ready, items: [{value, label, detail, orders}]}`, matched on a folded
    substring of the value, label or detail, by `orders` descending then label; `ready` false (no items) while the
    list is being built or after its statement ran out of time, so the next request tries again."""
    if kind not in CHOICE_KINDS:
        raise ValueError(f"kind is one of {', '.join(CHOICE_KINDS)}")
    limit = max(1, min(int(limit or CHOICES_LIMIT), CHOICES_LIMIT_MAX))
    items = _choices_list(session, kind, restore_seconds)
    if items is None:
        return {"kind": kind, "ready": False, "items": []}
    needle = _fold(q)
    picked = [i for i in items if not needle or needle in i["_fold"]][:limit]
    return {
        "kind": kind,
        "ready": True,
        "items": [{k: v for k, v in i.items() if k != "_fold"} for i in picked],
    }


def reset_filter_choices() -> None:
    """Tests: forget the cached lists."""
    _choices_cache.clear()


# ------------------------------------------------------------------------------------------------ the question


@dataclass(frozen=True)
class QueryVector:
    vector: list[float] | None
    reason: str | None = None
    model_key: str | None = None
    ms: int = 0


async def embed_question(client: OllamaClient, cfg: Any, question: str, key: str | None) -> QueryVector:
    """Decision 21: the question's vector with the profile's query prefix within `RESEARCH_QUERY_EMBED_SECONDS`, or a
    reason (`no_profile`, `model_unready`, `timeout`, `unavailable`, `wrong_dimension`). Never raises."""
    profile = rc.profile_for(cfg.research_embed_model)
    if profile is None:
        return QueryVector(None, "no_profile")
    if not key:
        return QueryVector(None, "model_unready")
    started = time.monotonic()
    seconds = float(cfg.research_query_embed_seconds)
    try:
        reply = await asyncio.wait_for(
            client.embed(
                cfg.research_embed_model,
                [rc.query_input(profile, question)],
                options=remb.options(profile, cfg),
                keep_alive=remb.keep_alive(cfg),
                timeout=seconds,
            ),
            timeout=seconds,
        )
    except TimeoutError:
        return QueryVector(None, "timeout")
    except SourceTraceError:
        return QueryVector(None, "unavailable")
    except Exception:  # noqa: BLE001 - the question is answered by words; never refused for this
        return QueryVector(None, "unavailable")
    vec = reply.embeddings[0] if reply.embeddings else []
    if len(vec) != profile.dims:
        return QueryVector(None, "wrong_dimension")
    return QueryVector(vec, None, key, int((time.monotonic() - started) * 1000))


# ------------------------------------------------------------------------------------------------ scope SQL


@dataclass(frozen=True)
class Scope:
    """`kind` research / my_cases / related; `focus` the focus case ids (my_cases), or the excluded cases (related)."""

    kind: str
    focus: tuple[uuid.UUID, ...] = ()
    filters: Filters = field(default_factory=Filters)


def _holder_where(
    scope: Scope, params: dict[str, Any], alias: str = "s", order: str = "o", case: str = "k"
) -> str:
    """The SQL conditions on a current reading `s`, its order `o` and its case `k` for the scope and the filters."""
    conds = [f"{alias}.replaced_at IS NULL", f"{case}.merged_into_case_id IS NULL"]
    if scope.kind == "my_cases":
        conds.append(f"{order}.case_id = ANY(:focus)")
        params["focus"] = list(scope.focus)
    elif scope.kind == "related":
        conds.append(f"{order}.case_id <> ALL(:focus)")
        conds.append(
            f"NOT EXISTS (SELECT 1 FROM orders fo WHERE fo.document_id = {order}.document_id AND fo.case_id = ANY(:focus))"
        )
        params["focus"] = list(scope.focus)
    f = scope.filters
    if f.forms:
        conds.append(f"{alias}.form::text = ANY(:forms)")
        params["forms"] = list(f.forms)
    if f.substantive_only:
        conds.append(f"NOT {alias}.procedural")
    if f.outcomes:
        conds.append(f"{alias}.outcome::text = ANY(:outcomes)")
        params["outcomes"] = list(f.outcomes)
    if f.date_from:
        conds.append(f"{order}.order_date >= :d_from")
        params["d_from"] = f.date_from
    if f.date_to:
        conds.append(f"{order}.order_date <= :d_to")
        params["d_to"] = f.date_to
    if f.cites:
        import json

        conds.append(f"({alias}.facts -> 'judgments') @> CAST(:cites AS jsonb)")
        params["cites"] = json.dumps([{"citation": f.cites}])
    if f.act:
        import json

        conds.append(f"({alias}.facts -> 'acts') @> CAST(:act AS jsonb)")
        params["act"] = json.dumps([{"act_key": f.act}])
    return " AND ".join(conds)


def _chunk_scope(scope: Scope, params: dict[str, Any]) -> str:
    """The chunks of the scope: order chunks held by a current reading in scope, and (no order filter, not related)
    the sheets of the scope's live cases."""
    held = (
        "(c.kind = 'order_body' AND EXISTS (SELECT 1 FROM order_sections s JOIN orders o ON o.id = s.order_id "
        "JOIN cases k ON k.id = o.case_id WHERE s.body_sha256 = c.body_sha256 AND s.form = c.form "
        f"AND s.parser_version = c.parser_version AND {_holder_where(scope, params)}))"
    )
    if scope.kind == "related" or scope.filters.any:
        return held
    sheet = "(c.kind = 'case_sheet' AND EXISTS (SELECT 1 FROM cases k WHERE k.id = c.case_id AND k.merged_into_case_id IS NULL"
    if scope.kind == "my_cases":
        sheet += " AND k.id = ANY(:focus)"
        params["focus"] = list(scope.focus)
    sheet += "))"
    return f"({held} OR {sheet})"


# ------------------------------------------------------------------------------------------------ the lists


def ranked_words(s: Session, budget: Budget, question: str, scope: Scope, limit: int) -> list[uuid.UUID]:
    """Decision 17 (a): chunk ids, best `ts_rank_cd` first."""
    params: dict[str, Any] = {"q": question, "n": int(limit)}
    where = _chunk_scope(scope, params)
    budget.arm(s)
    rows = s.execute(
        text(
            f"""
            SELECT c.id FROM research_chunks c, websearch_to_tsquery('english', :q) q
            WHERE c.retired_at IS NULL AND c.search_vector @@ q AND {where}
            ORDER BY ts_rank_cd(c.search_vector, q) DESC, c.id
            LIMIT :n
            """
        ),
        params,
    ).all()
    return [r[0] for r in rows]


def scope_size(s: Session, budget: Budget, scope: Scope, cap: int) -> int:
    """The chunks of the scope, counted up to `cap + 1` (decision 15: an exact scan at or under the cap)."""
    params: dict[str, Any] = {"cap": int(cap) + 1}
    where = _chunk_scope(scope, params)
    budget.arm(s)
    return int(
        s.scalar(
            text(
                f"SELECT count(*) FROM (SELECT 1 FROM research_chunks c WHERE c.retired_at IS NULL AND {where} "
                "LIMIT :cap) x"
            ),
            params,
        )
        or 0
    )


def meaning_sql(dims: int, where: str, *, exact: bool) -> str:
    """The meaning list's query (`:v` the question's vector, `:key` the live key, `:n` the row cap). With the index
    (`exact` false) it orders by the index's own expression alone: a second sort key (`c.id`) would stop PostgreSQL
    from walking the HNSW index and make it scan and sort every live vector (decision 15). Ties at the same distance
    are rare and harmless there; the exact scan keeps `c.id` as its tie-break."""
    d = int(dims)
    if exact:
        order = "e.embedding <=> CAST(:v AS halfvec), c.id"
    else:
        order = f"(e.embedding::halfvec({d})) <=> CAST(:v AS halfvec({d}))"
    return f"""
        SELECT c.id FROM research_embeddings e
        JOIN research_chunks c ON c.embed_sha256 = e.input_sha256 AND c.retired_at IS NULL
        WHERE e.retired_at IS NULL AND e.dims = {d} AND e.model_key = :key AND {where}
        ORDER BY {order}
        LIMIT :n
    """


def ranked_meaning(
    s: Session,
    budget: Budget,
    vector: list[float],
    key: str,
    dims: int,
    scope: Scope,
    limit: int,
    *,
    exact: bool,
    ef_search: int,
) -> list[uuid.UUID]:
    """Decision 17 (b): chunk ids nearest first by cosine distance, the live key's current vectors only. `exact`: no
    index (My Cases, small filtered sets); otherwise the HNSW index of `dims` with the iterative scan."""
    from aslms.db.base import vector_literal

    params: dict[str, Any] = {"v": vector_literal(vector), "key": key, "n": int(limit) * 2}
    where = _chunk_scope(scope, params)
    budget.arm(s)
    if not exact:
        s.execute(text(f"SET LOCAL hnsw.ef_search = {int(ef_search)}"))
        s.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    rows = s.execute(text(meaning_sql(dims, where, exact=exact)), params).all()
    out: list[uuid.UUID] = []
    for (cid,) in rows:
        if cid not in out:
            out.append(cid)
        if len(out) >= limit:
            break
    return out


def unindexed_docs(
    s: Session, budget: Budget, question: str, scope: Scope, limit: int
) -> list[tuple[uuid.UUID, float]]:
    """Decision 17 (d): court orders of the scope with no current reading holding a current chunk set, best page-search
    rank first (today's statements)."""
    from sqlalchemy import func

    if scope.kind == "my_cases":
        corpus = court_order_condition(focus_case_ids=list(scope.focus))
    elif scope.kind == "related":
        corpus = court_order_condition(exclude_case_ids=list(scope.focus))
    else:
        corpus = court_order_condition()
    indexed = exists(
        select(text("1"))
        .select_from(text("order_sections xs JOIN research_chunks xc ON xc.body_sha256 = xs.body_sha256"))
        .where(
            text(
                "xs.document_id = documents.id AND xs.replaced_at IS NULL AND xc.retired_at IS NULL "
                "AND xc.form = xs.form AND xc.parser_version = xs.parser_version"
            )
        )
    )
    return PreviewConnector._rank(
        s, budget, and_(corpus, not_(indexed)), func.websearch_to_tsquery("english", question), limit
    )


# ------------------------------------------------------------------------------------------------ fusion


def fuse(lists: dict[str, list[Any]], *, k: int = RRF_K) -> list[tuple[Any, float, set[str]]]:
    """Reciprocal rank fusion: score = Σ 1 / (k + rank) over the lists an item appears in (rank 1-based); the item, its
    score and the names of the lists it came from, best first (ties by first appearance)."""
    score: dict[Any, float] = defaultdict(float)
    where: dict[Any, set[str]] = defaultdict(set)
    first: dict[Any, int] = {}
    pos = 0
    for name, items in lists.items():
        for rank, item in enumerate(items, start=1):
            score[item] += 1.0 / (k + rank)
            where[item].add(name)
            if item not in first:
                first[item] = pos
                pos += 1
    return sorted(((i, score[i], where[i]) for i in score), key=lambda t: (-t[1], first[t[0]]))


def weight(form: str | None, procedural: bool | None) -> float:
    """Decision 18: procedural × 0.5, judgment or final × 1.2, other substantive × 1.0."""
    if procedural:
        return WEIGHT_PROCEDURAL
    if form in ("judgment", "final"):
        return WEIGHT_JUDGMENT
    return WEIGHT_OTHER


def match_of(lists: set[str]) -> str:
    if "words" in lists and "meaning" in lists:
        return "both"
    return "meaning" if "meaning" in lists else "words"


# ------------------------------------------------------------------------------------------------ holders


@dataclass
class Holder:
    """The order a chunk is cited through (decision 18): the newest order in scope, focus cases first, whose current
    reading's text is today's (decision 13)."""

    chunk_id: uuid.UUID
    reading_id: uuid.UUID
    order_id: uuid.UUID
    document_id: uuid.UUID
    case_id: uuid.UUID
    form: str
    procedural: bool
    outcome: str | None
    same_words_in: int


def holders(s: Session, budget: Budget, chunk_ids: list[uuid.UUID], scope: Scope) -> tuple[dict, int]:
    """For each order chunk, its holder in scope; and the number of chunks whose holders in scope all have a changed
    text (`stale_dropped`)."""
    if not chunk_ids:
        return {}, 0
    params: dict[str, Any] = {"ids": list(chunk_ids)}
    where = _holder_where(scope, params)
    focus_rank = "CASE WHEN o.case_id = ANY(:focus) THEN 0 ELSE 1 END, " if scope.kind == "my_cases" else ""
    budget.arm(s)
    rows = s.execute(
        text(
            f"""
            SELECT c.id AS chunk_id, s.id AS reading_id, s.order_id, s.document_id, o.case_id, s.form::text AS form,
                   s.procedural, s.outcome::text AS outcome,
                   (encode(sha256(convert_to(t.full_text, 'UTF8')), 'hex') = s.text_sha256) AS fresh
            FROM research_chunks c
            JOIN order_sections s ON s.body_sha256 = c.body_sha256 AND s.form = c.form
                 AND s.parser_version = c.parser_version
            JOIN orders o ON o.id = s.order_id
            JOIN cases k ON k.id = o.case_id
            JOIN documents d ON d.id = s.document_id
            LEFT JOIN document_text t ON t.document_id = s.document_id
            WHERE c.id = ANY(:ids) AND c.kind = 'order_body' AND d.archived_at IS NULL AND {where}
            ORDER BY c.id, {focus_rank}o.order_date DESC NULLS LAST, o.id
            """
        ),
        params,
    ).all()
    by_chunk: dict[uuid.UUID, list[Any]] = defaultdict(list)
    for r in rows:
        by_chunk[r.chunk_id].append(r)
    out: dict[uuid.UUID, Holder] = {}
    stale = 0
    for cid, rs_ in by_chunk.items():
        fresh = [r for r in rs_ if r.fresh]
        if not fresh:
            stale += 1
            continue
        r = fresh[0]
        out[cid] = Holder(
            cid, r.reading_id, r.order_id, r.document_id, r.case_id, r.form, bool(r.procedural), r.outcome,
            len({x.order_id for x in fresh}) - 1,
        )  # fmt: skip
    return out, stale


def against_state_ok(s: Session, budget: Budget, holder: Holder) -> bool:
    """Decision 20, by rule (owner, 23 Nov 2026): `allowed` or `partly_allowed` with the State as a current respondent,
    or `dismissed` with the State as a current petitioner."""
    if holder.outcome in ("allowed", "partly_allowed"):
        role = "respondent"
    elif holder.outcome == "dismissed":
        role = "petitioner"
    else:
        return False
    budget.arm(s)
    return bool(
        s.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM case_parties p WHERE p.case_id = :c AND p.is_current "
                "AND p.role::text = :r AND p.name ~* :rx)"
            ),
            {"c": holder.case_id, "r": role, "rx": STATE_PARTY_SQL},
        )
    )


# ------------------------------------------------------------------------------------------------ passages


@dataclass
class ResearchPassage:
    """One passage given to the model: a court order's matched chunks read small-to-big (`kind` `order`), a page of an
    order not yet indexed or of a filing (`kind` `page`, today's `Passage`), or a case sheet hit (`kind` `sheet`)."""

    kind: str
    score: float
    match: str
    related: bool = False
    # order passages
    holder: Holder | None = None
    chunk_ids: list[uuid.UUID] = field(default_factory=list)
    para_first: int = 0
    para_last: int = 0
    page: int | None = None
    page_to: int | None = None
    src: tuple[int, int] | None = None
    context_line: str = ""
    text: str = ""
    excerpt: str = ""
    pdf_sha256: str | None = None
    text_sha256: str | None = None
    parser_version: int | None = None
    chunker_version: int | None = None
    model_key: str | None = None
    # page passages (today's search)
    page_passage: Passage | None = None
    # sheet hits
    case_id: uuid.UUID | None = None


@dataclass
class SearchResult:
    passages: list[ResearchPassage]
    kind: str  # hybrid | words_only
    reason: str | None
    counts: dict[str, int]
    fused: int
    stale_dropped: int
    sheet_cases: list[uuid.UUID]


def _reading_rows(s: Session, budget: Budget, reading_ids: list[uuid.UUID]) -> dict[uuid.UUID, Any]:
    if not reading_ids:
        return {}
    budget.arm(s)
    rows = s.execute(
        text(
            """
            SELECT s.id, s.body_text, s.paragraphs, s.pdf_sha256, s.text_sha256, s.parser_version, s.form::text AS form,
                   o.order_date, o.order_no, o.order_judge_name, k.case_no_text, k.cnr, k.coram, k.case_type_text,
                   k.category, k.sub_category
            FROM order_sections s JOIN orders o ON o.id = s.order_id JOIN cases k ON k.id = o.case_id
            WHERE s.id = ANY(:ids)
            """
        ),
        {"ids": list(reading_ids)},
    ).all()
    return {r.id: r for r in rows}


def full_context_line(
    r: Any, part: str, labels: list[str | None], pages: tuple[int | None, int | None]
) -> str:
    """Decision 10's full line, built from held data each time a chunk is read: order date, case number and type, the
    court's category and sub-category, the judge, the form, the part, the paragraphs and the pages."""
    bits: list[str] = []
    if r.order_date:
        bits.append(f"Order dated {r.order_date.strftime('%d.%m.%Y')}")
    number = r.case_no_text or r.cnr
    if number:
        bits.append(str(number))
    cat = ": ".join(str(x).strip() for x in (r.category, r.sub_category) if x)
    if cat:
        bits.append(cat)
    judge = (r.order_judge_name or r.coram or "").strip()
    if judge:
        bits.append(re.sub(r"\s+", " ", judge)[:160])
    short = rc.context_line(r.form, part, labels)
    bits.append(short)
    p1, p2 = pages
    if p1:
        bits.append(f"page {p1}" if not p2 or p2 == p1 else f"pages {p1} to {p2}")
    return " · ".join(bits)


def small_to_big(
    paragraphs: list[dict[str, Any]], body: str, first: int, last: int, part: str, limit: int
) -> tuple[str, int, int]:
    """Decision 19: the matched paragraphs `first..last`, then neighbours of the same part, one after and one before
    in turn, until `limit` characters. Returns the text and the paragraph range read."""
    by_i = {int(p["i"]): p for p in paragraphs}
    same = sorted(i for i, p in by_i.items() if (p.get("part") or "body") == part)
    lo, hi = first, last

    def span(a: int, b: int) -> str:
        ps = [by_i[i] for i in range(a, b + 1) if i in by_i]
        if not ps:
            return ""
        return body[int(ps[0]["txt"][0]) : int(ps[-1]["txt"][1])].strip()

    textv = span(lo, hi)
    if len(textv) > limit:
        return textv[:limit], lo, hi
    after = True
    while True:
        cand = [i for i in same if i > hi][:1] if after else [i for i in same if i < lo][-1:]
        other = [i for i in same if i < lo][-1:] if after else [i for i in same if i > hi][:1]
        pick = cand or other
        if not pick:
            break
        i = pick[0]
        nlo, nhi = (lo, i) if i > hi else (i, hi)
        nxt = span(nlo, nhi)
        if len(nxt) > limit:
            break
        lo, hi, textv = nlo, nhi, nxt
        after = not after
    return textv, lo, hi


def _order_passages(
    s: Session,
    budget: Budget,
    ranked: list[tuple[uuid.UUID, float, set[str]]],
    holders_: dict[uuid.UUID, Holder],
    chunks: dict[uuid.UUID, Any],
    model_key: str | None,
    source_chars: int,
    related: bool,
) -> dict[uuid.UUID, ResearchPassage]:
    """Adjacent chunks of one order joined; at most 2 passages per order; each read small-to-big."""
    readings = _reading_rows(s, budget, list({h.reading_id for h in holders_.values()}))
    out: dict[uuid.UUID, ResearchPassage] = {}
    per_order: dict[uuid.UUID, list[ResearchPassage]] = defaultdict(list)
    for cid, score, lists in ranked:
        h = holders_.get(cid)
        c = chunks.get(cid)
        r = readings.get(h.reading_id) if h else None
        if h is None or c is None or r is None:
            continue
        mine = per_order[h.order_id]
        joined = False
        for p in mine:  # adjacent chunks of the same set become one passage
            if c.part == chunks[p.chunk_ids[0]].part and (
                c.para_first == p.para_last + 1
                or c.para_last + 1 == p.para_first
                or c.seq in _seqs(p, chunks, 1)
            ):
                p.chunk_ids.append(cid)
                p.para_first, p.para_last = min(p.para_first, c.para_first), max(p.para_last, c.para_last)
                p.match = "both" if p.match != match_of(lists) else p.match
                joined = True
                break
        if joined:
            continue
        if len(mine) >= PASSAGES_PER_ORDER:
            continue
        p = ResearchPassage(
            kind="order",
            score=score * weight(h.form, h.procedural),
            match=match_of(lists),
            related=related,
            holder=h,
            chunk_ids=[cid],
            para_first=c.para_first,
            para_last=c.para_last,
            text_sha256=r.text_sha256,
            pdf_sha256=r.pdf_sha256,
            parser_version=r.parser_version,
            chunker_version=c.chunker_version,
            model_key=model_key if "meaning" in lists else None,
        )
        mine.append(p)
        out[cid] = p
    for p in out.values():
        h = p.holder
        r = readings[h.reading_id]
        part = chunks[p.chunk_ids[0]].part
        paras = r.paragraphs or []
        body, _lo, _hi = small_to_big(paras, r.body_text, p.para_first, p.para_last, part, source_chars)
        by_i = {int(x["i"]): x for x in paras}
        matched = [by_i[i] for i in range(p.para_first, p.para_last + 1) if i in by_i]
        if matched:
            p.page = int(matched[0].get("page") or 1)
            p.page_to = int(matched[-1].get("page_to") or matched[-1].get("page") or p.page)
            p.src = (int(matched[0]["src"][0]), int(matched[-1]["src"][1]))
        labels = [by_i[i].get("label") for i in range(p.para_first, p.para_last + 1) if i in by_i]
        p.context_line = full_context_line(r, part, labels, (p.page, p.page_to))
        p.text = body
        first_chunk = chunks[p.chunk_ids[0]]
        p.excerpt = (first_chunk.text or "")[:EXCERPT_CHARS]
    return out


def _seqs(p: ResearchPassage, chunks: dict[uuid.UUID, Any], gap: int) -> set[int]:
    seqs = {chunks[c].seq for c in p.chunk_ids}
    return {q + d for q in seqs for d in (-gap, gap)}


def _chunk_rows(s: Session, budget: Budget, ids: list[uuid.UUID]) -> dict[uuid.UUID, Any]:
    if not ids:
        return {}
    budget.arm(s)
    rows = s.execute(
        text(
            "SELECT id, kind::text AS kind, case_id, part, para_first, para_last, seq, chunker_version, text "
            "FROM research_chunks WHERE id = ANY(:ids)"
        ),
        {"ids": list(ids)},
    ).all()
    return {r.id: r for r in rows}


def passages(
    s: Session,
    request: AskRequest,
    budget: Budget,
    *,
    query: QueryVector,
    dims: int,
    filters: Filters,
    limit: int,
    source_chars: int,
    candidates: int,
    exact_max: int,
    ef_search: int,
    related_only: bool = False,
) -> SearchResult:
    """Decisions 17 to 20 for one question, in the caller's read-only session. `related_only`: the related orders of
    This Case (the focus case's own orders are searched as today by the caller)."""
    question = request.question
    focus = tuple(c.case_id for c in request.scope.focus)
    if related_only:
        scope = Scope("related", focus, Filters())
    elif request.scope.kind == "my_cases":
        scope = Scope("my_cases", focus, filters)
    else:
        scope = Scope("research", (), filters)
    lists: dict[str, list[Any]] = {}
    words = ranked_words(s, budget, question, scope, candidates)
    lists["words"] = words
    meaning: list[uuid.UUID] = []
    if query.vector is not None and query.model_key:
        exact = scope.kind == "my_cases" or (
            filters.any and scope_size(s, budget, scope, exact_max) <= exact_max
        )
        meaning = ranked_meaning(
            s,
            budget,
            query.vector,
            query.model_key,
            dims,
            scope,
            candidates,
            exact=exact,
            ef_search=ef_search,
        )
        lists["meaning"] = meaning
    chunks = _chunk_rows(s, budget, list(dict.fromkeys(words + meaning)))
    order_ids = [c for c, r in chunks.items() if r.kind == "order_body"]
    holders_, stale = holders(s, budget, order_ids, scope)
    # one item per chunk (its holder); a chunk with no fresh holder in scope is dropped
    for name in ("words", "meaning"):
        if name in lists:
            lists[name] = [
                c for c in lists[name] if c in holders_ or chunks.get(c) and chunks[c].kind == "case_sheet"
            ]
    filing_pages: list[Passage] = []
    if scope.kind == "my_cases" and request.scope.filings and not filters.any:
        found = search_passages(s, request, budget, limit=FILING_PASSAGES, text_chars=source_chars)
        order_docs = set(
            s.scalars(
                select(Document.id).where(
                    Document.id.in_([p.document_id for p in found.passages]),
                    court_order_condition(),
                )
            ).all()
        )
        filing_pages = [p for p in found.passages if p.document_id not in order_docs]
        lists["filings"] = [("page", p.document_id, p.page) for p in filing_pages]
    unindexed: list[Passage] = []
    if not filters.any:
        docs = unindexed_docs(s, budget, question, scope, UNINDEXED_DOCS)
        for doc_id, rank in docs:
            for n, headline, _r, page_text in PreviewConnector._pages(
                s, budget, doc_id, "websearch_to_tsquery('english', :q)", question, source_chars
            )[:1]:
                unindexed.append(
                    Passage(
                        doc_id, scope.kind == "related", rank, n, headline[:EXCERPT_CHARS], page_text, None
                    )
                )
        lists["unindexed"] = [("page", p.document_id, p.page) for p in unindexed]
    fused = fuse(lists)
    pages = {("page", p.document_id, p.page): p for p in filing_pages + unindexed}
    ranked_chunks = [(i, sc, ls) for i, sc, ls in fused if isinstance(i, uuid.UUID)]
    order_items = _order_passages(
        s,
        budget,
        [t for t in ranked_chunks if chunks[t[0]].kind == "order_body"],
        holders_,
        chunks,
        query.model_key,
        source_chars,
        scope.kind == "related",
    )
    if filters.against_state:
        order_items = {c: p for c, p in order_items.items() if against_state_ok(s, budget, p.holder)}
    out: list[ResearchPassage] = []
    sheet_cases: list[uuid.UUID] = []
    for item, score, ls in fused:
        if isinstance(item, uuid.UUID):
            c = chunks[item]
            if c.kind == "case_sheet":
                out.append(ResearchPassage("sheet", score, match_of(ls), case_id=c.case_id))
                sheet_cases.append(c.case_id)
            elif item in order_items:
                out.append(order_items[item])
        elif item in pages:
            p = pages[item]
            out.append(ResearchPassage("page", score, "words", related=p.related, page_passage=p))
    out.sort(key=lambda p: -p.score)
    chosen: list[ResearchPassage] = []
    slots = 0
    for p in out:
        if slots >= limit:
            break
        if p in chosen:
            continue
        chosen.append(p)
        slots += 1
        if (
            p.kind == "sheet"
        ):  # a sheet brings its case's best-ranked order passage; the two count as one source
            best = next(
                (q for q in out if q.kind == "order" and q.holder and q.holder.case_id == p.case_id), None
            )
            if best is not None and best not in chosen:
                chosen.append(best)
    return SearchResult(
        passages=chosen,
        kind="hybrid" if "meaning" in lists else "words_only",
        reason=query.reason,
        counts={k: len(v) for k, v in lists.items()},
        fused=len(fused),
        stale_dropped=stale,
        sheet_cases=sheet_cases,
    )


__all__ = [
    "BadFilter",
    "Filters",
    "QueryVector",
    "ResearchPassage",
    "Scope",
    "SearchResult",
    "embed_question",
    "fuse",
    "parse_filters",
    "passages",
    "small_to_big",
    "weight",
]
