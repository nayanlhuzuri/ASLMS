"""The Case Assistant's preview (design `assistant`, decision 7): `PreviewConnector` implements the connector's
`ask` by PostgreSQL full-text search over the stored text of the court records in the request's scope, so the owner
can check the assistant now, without SourceTrace and without any model.

No AI and no model of any kind: no neural network, no embedding, no generated text, nothing trained. It is
PostgreSQL's built-in text search (dictionary stemming, word-frequency ranking and verbatim excerpts, as document
search has used since row 4); nothing leaves the server, and the only text it adds is a fixed template. This module
imports nothing outside the standard library, SQLAlchemy and `aslms` (a unit test checks it).

1. Query: `websearch_to_tsquery('english', question)`; a question of only stop words is `no_match`.
2. Documents: ranked by `ts_rank`, then `doc_date` descending: the top 5 for the focus (case or my cases), with
   related orders the top 3 court orders of other cases ranked apart, for research the top 6 overall.
3. Fallback: when the case or my-cases corpus has no match under the all-words query, once more with any word
   (`to_tsquery('simple', <the question's lexemes joined by ' | '>)`). Research never falls back, and neither do
   the related orders of the case scope: they are searched with the all-words query only, last, in a savepoint of
   their own, so their timeout or failure drops the related section and never the focus answer (`info.related` is
   then `dropped`).
4. Passages: the pages (`\\f`-separated, at most 300 per document) that match, the best 2 by rank, each with
   `ts_headline`; the page number for PDFs, none for Word files.
5. Limits: at most `ASSISTANT_PREVIEW_PASSAGES` passages; everything in a read-only transaction of its own. The whole
   search has one time budget, `ASSISTANT_TIMEOUT_SECONDS` less a margin for storing the answer: before every
   statement the budget is checked and `statement_timeout` is set to `ASSISTANT_PREVIEW_SQL_MS` or what is left of
   the budget, whichever is less, so the statements together cannot outrun the answer limit. When the waiting call
   gives up (its own timeout), a flag stops the search before its next statement. A timeout or a spent budget
   raises `PreviewTooBroad`.

The nature conditions of the corpus are applied again here (a second check after the service's): court orders by
`assistant_sources.court_order_condition`, filings only from the allow-list the request carries and only while they
are still court filings that are not private and not archived."""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import Select, and_, func, or_, select, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from aslms.domain.documents import Document, DocumentText
from aslms.integration.sourcetrace.connector import Answer, AskRequest, Citation
from aslms.services.assistant_sources import court_order_condition, filing_base_condition

NAME = "preview"
ENGINE = "postgresql_full_text"
PREVIEW_LINE = "Preview: passages found in the court records, not an AI answer."
NO_MATCH_LINE = "No passage in the court records of this scope matched the words of your question."
STOP_WORDS_LINE = "Use more specific words: every word of the question is too common to search."
TOO_BROAD = "The question is too broad for the preview; add more specific words."
FOCUS_DOCS = 5
RELATED_DOCS = 3
RESEARCH_DOCS = 6
PAGES_PER_DOC = 2
MAX_PAGES = 300
TEXT_CHARS = 200_000
MAX_PASSAGE = 1000
HEADLINE = "MaxWords=60, MinWords=25, MaxFragments=1, StartSel=[[, StopSel=]]"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MARGIN_SECONDS = 2.0  # of the answer limit, kept for storing the answer (at most a quarter of it)
STRICT_SQL = "websearch_to_tsquery('english', :q)"


class PreviewTooBroad(TimeoutError):
    """The search ran past `ASSISTANT_PREVIEW_SQL_MS` or its whole budget (outcome `failed`, family `timeout`)."""

    def __init__(self, message: str = TOO_BROAD):
        super().__init__(message)


def _is_timeout(exc: Exception) -> bool:
    words = str(exc).lower()
    return "statement timeout" in words or "canceling statement" in words


def budget_seconds(timeout_seconds: float) -> float:
    """The whole search's time: the answer limit less `MARGIN_SECONDS` (at most a quarter of the limit)."""
    return timeout_seconds - min(MARGIN_SECONDS, timeout_seconds / 4)


class _Budget:
    """One search's time (review finding 5): `arm` runs before every statement, refuses once the deadline has passed
    or the waiting call has given up, and keeps `statement_timeout` at no more than what is left."""

    def __init__(self, seconds: float, statement_ms: int, cancel: threading.Event | None = None):
        self.deadline = time.monotonic() + seconds
        self.statement_ms = int(statement_ms)
        self.cancel = cancel if cancel is not None else threading.Event()
        self.armed: int | None = None

    def arm(self, s: Session) -> None:
        if self.cancel.is_set():
            raise PreviewTooBroad()
        left = int((self.deadline - time.monotonic()) * 1000)
        if left <= 0:
            raise PreviewTooBroad()
        want = max(1, min(self.statement_ms, left))
        if self.armed is None or want < self.armed:
            s.execute(text(f"SET LOCAL statement_timeout = {want}"))
            self.armed = want


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def answer_text(passages: int, documents: int, match: str) -> str:
    """The fixed template (never composed): the preview line, then the count line or the no-match line."""
    if passages == 0:
        return f"{PREVIEW_LINE}\n{NO_MATCH_LINE}"
    words = "all" if match == "all" else "any"
    return (
        f"{PREVIEW_LINE}\n{_plural(passages, 'passage')} from {_plural(documents, 'document')} matched {words} of "
        "the words of your question."
    )


class PreviewConnector:
    """`AssistantConnector` over PostgreSQL full-text search. `before_search`, when given, is called with the
    session after the time limit is set (a test sleeps there to reach the limit)."""

    name = NAME

    def __init__(
        self,
        session_factory: sessionmaker,
        settings: Any,
        *,
        before_search: Callable[[Session], Any] | None = None,
    ):
        self.session_factory = session_factory
        self.passages = int(getattr(settings, "assistant_preview_passages", 8))
        self.sql_ms = int(getattr(settings, "assistant_preview_sql_ms", 8000))
        self.budget_seconds = budget_seconds(float(getattr(settings, "assistant_timeout_seconds", 45.0)))
        self.before_search = before_search

    async def ask(self, request: AskRequest) -> Answer:
        cancel = threading.Event()
        try:
            return await asyncio.to_thread(self._ask, request, cancel)
        finally:
            cancel.set()  # the caller gave up (or the search is over): no statement after this one

    # ------------------------------------------------------------------------------------------------ the search

    def _ask(self, request: AskRequest, cancel: threading.Event | None = None) -> Answer:
        budget = _Budget(self.budget_seconds, self.sql_ms, cancel)
        with self.session_factory() as s:
            try:
                s.execute(text("SET TRANSACTION READ ONLY"))
                budget.arm(s)
                if self.before_search is not None:
                    self.before_search(s)
                return self._search(s, request, budget)
            except OperationalError as exc:
                if _is_timeout(exc):
                    raise PreviewTooBroad() from exc
                raise
            finally:
                s.rollback()

    def _search(self, s: Session, request: AskRequest, budget: _Budget) -> Answer:
        question = request.question
        budget.arm(s)
        nodes = s.scalar(select(func.numnode(func.websearch_to_tsquery("english", question))))
        if not nodes:
            return Answer(
                text=f"{PREVIEW_LINE}\n{STOP_WORDS_LINE}",
                outcome="no_match",
                info={"engine": ENGINE, "match": "all", "reason": "stop_words"},
            )
        scope = request.scope
        focus_ids = [c.case_id for c in scope.focus]
        filing_ids = [f.document_id for f in scope.filings]
        all_q = func.websearch_to_tsquery("english", question)
        match = "all"
        if scope.kind == "research":
            docs = self._rank(s, budget, self._corpus(None, filing_ids), all_q, RESEARCH_DOCS)
        else:
            corpus = self._corpus(focus_ids, filing_ids)
            docs = self._rank(s, budget, corpus, all_q, FOCUS_DOCS)
            if not docs:
                lexemes = self._lexemes(s, budget, question)
                if lexemes:
                    match = "any"
                    docs = self._rank(s, budget, corpus, func.to_tsquery("simple", lexemes), FOCUS_DOCS)
        q_sql, q_param = (
            (STRICT_SQL, question)
            if match == "all"
            else ("to_tsquery('simple', :q)", self._lexemes(s, budget, question))
        )
        candidates: list[tuple[uuid.UUID, bool, float, list[tuple[int, str, float]]]] = [
            (doc_id, False, rank, self._pages(s, budget, doc_id, q_sql, q_param)) for doc_id, rank in docs
        ]
        info: dict[str, Any] = {"engine": ENGINE, "match": match}
        if scope.kind != "research" and scope.orders == "focus_and_related" and focus_ids:
            related = self._related(s, budget, question, focus_ids)
            if related is None:
                info["related"] = "dropped"
            else:
                candidates.extend(related)
        budget.arm(s)
        mimes = dict(
            s.execute(
                select(Document.id, Document.mime).where(Document.id.in_([c[0] for c in candidates]))
            ).all()
        )
        citations = self._pick(candidates, mimes)
        n_docs = len({c.document_id for c in citations})
        return Answer(
            text=answer_text(len(citations), n_docs, match),
            citations=tuple(citations),
            outcome="answered" if citations else "no_match",
            info=info,
        )

    def _related(
        self, s: Session, budget: _Budget, question: str, focus_ids: list[uuid.UUID]
    ) -> list[tuple[uuid.UUID, bool, float, list[tuple[int, str, float]]]] | None:
        """The related orders of other cases (review finding 4): the all-words query only, never the any-word
        fallback, in a savepoint of their own. Their timeout, a spent budget or a database failure rolls the savepoint
        back and answers None (the section is dropped); the focus answer stands."""
        try:
            with s.begin_nested():
                docs = self._rank(
                    s,
                    budget,
                    court_order_condition(exclude_case_ids=focus_ids),
                    func.websearch_to_tsquery("english", question),
                    RELATED_DOCS,
                )
                return [
                    (doc_id, True, rank, self._pages(s, budget, doc_id, STRICT_SQL, question))
                    for doc_id, rank in docs
                ]
        except (SQLAlchemyError, PreviewTooBroad):
            budget.armed = None  # the savepoint's rollback also undid a `SET LOCAL` made inside it
            return None

    def _corpus(self, focus_ids: list[uuid.UUID] | None, filing_ids: list[uuid.UUID]):
        """The request's corpus, checked again: court orders of the focus (or all, for research), or filings of the
        allow-list that are still court filings, not private and not archived."""
        orders = court_order_condition(focus_case_ids=focus_ids)
        filings = filing_base_condition(document_ids=filing_ids)
        return or_(orders, filings)

    def _rank(self, s: Session, budget: _Budget, corpus, q, limit: int) -> list[tuple[uuid.UUID, float]]:
        budget.arm(s)
        rank = func.ts_rank(DocumentText.search_vector, q)
        stmt: Select = (
            select(Document.id, rank)
            .join(DocumentText, DocumentText.document_id == Document.id)
            .where(
                and_(
                    DocumentText.search_vector.is_not(None),
                    DocumentText.search_vector.op("@@")(q),
                    corpus,
                )
            )
            .order_by(rank.desc(), Document.doc_date.desc().nulls_last(), Document.id)
            .limit(limit)
        )
        return [(doc_id, float(r or 0)) for doc_id, r in s.execute(stmt).all()]

    @staticmethod
    def _lexemes(s: Session, budget: _Budget, question: str) -> str:
        """The question's lexemes (English stemming, as the stored vectors), each quoted, joined by ' | '."""
        budget.arm(s)
        return (
            s.scalar(
                text(
                    "SELECT string_agg(quote_literal(lexeme), ' | ' ORDER BY lexeme) "
                    "FROM unnest(to_tsvector('english', :q))"
                ),
                {"q": question},
            )
            or ""
        )

    @staticmethod
    def _pages(
        s: Session, budget: _Budget, doc_id: uuid.UUID, q_sql: str, q_param: str
    ) -> list[tuple[int, str, float]]:
        budget.arm(s)
        rows = s.execute(
            text(
                f"""
                WITH q AS (SELECT {q_sql} AS query)
                SELECT p.n, ts_headline('english', p.page, q.query, :headline) AS passage,
                       ts_rank(to_tsvector('english', p.page), q.query) AS rank
                FROM document_text t
                CROSS JOIN q
                CROSS JOIN LATERAL string_to_table(left(t.full_text, :chars), E'\\f') WITH ORDINALITY AS p(page, n)
                WHERE t.document_id = :doc AND p.n <= :max_pages AND to_tsvector('english', p.page) @@ q.query
                ORDER BY rank DESC, p.n
                LIMIT :per_doc
                """
            ),
            {
                "q": q_param,
                "headline": HEADLINE,
                "chars": TEXT_CHARS,
                "doc": doc_id,
                "max_pages": MAX_PAGES,
                "per_doc": PAGES_PER_DOC,
            },
        ).all()
        return [(int(n), (passage or "").strip(), float(rank or 0)) for n, passage, rank in rows]

    def _pick(
        self,
        candidates: list[tuple[uuid.UUID, bool, float, list[tuple[int, str, float]]]],
        mimes: dict[uuid.UUID, str],
    ) -> list[Citation]:
        """At most `passages`: first the best page of every document (focus, then related), then the second
        pages; returned in document order."""
        chosen: dict[uuid.UUID, list[Citation]] = {}
        budget = self.passages
        for round_ in range(PAGES_PER_DOC):
            for doc_id, related, rank, pages in candidates:
                if budget <= 0 or round_ >= len(pages):
                    continue
                n, passage, page_rank = pages[round_]
                page = None if mimes.get(doc_id) == DOCX_MIME else n
                chosen.setdefault(doc_id, []).append(
                    Citation(
                        reference=str(doc_id),
                        document_id=doc_id,
                        page=page,
                        passage=passage[:MAX_PASSAGE] or None,
                        related=related,
                        rank=round(rank, 6),
                    )
                )
                budget -= 1
        out: list[Citation] = []
        for doc_id, _related, _rank, _pages in candidates:
            out.extend(chosen.get(doc_id, []))
        return out
