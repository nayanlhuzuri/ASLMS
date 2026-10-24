"""The Case Assistant (design `assistant`): the mode switch, questions and answers, private append-only
conversations, the hourly limit, the court-record view of a cited order, and the check.

- Modes (decision 2): `ASSISTANT_MODE` = `off` / `preview` / `sourcetrace`. `assistant_state` answers `off`,
  `preview`, `not_implemented` (sourcetrace chosen, no connector until row 36) or `ready`; `assistant_connector`
  returns the preview only in `preview`, the real connector only when `ready`, otherwise None, and every question is
  then refused with `AssistantOff` before anything is stored. The fake is never returned. Preview is refused in prod.
- A question (decisions 5, 6, 9, 10, 12) runs as three short steps so no transaction is held across the call (safe
  under PgBouncer transaction mode): **A** validates, locks the user and the conversation, checks the in-flight rule
  (one unanswered question per user across conversations) and the hourly limit, stores the question with its
  `scope_info` and writes `assistant.asked`; **the call** goes to the connector outside any transaction (one retry
  after `SourceTraceUnavailable`, never after a timeout, a refusal or a malformed answer); **B** stores the answer, maps and re-checks its citations, and writes `assistant.answered`. A connector
  failure is stored as an answer with outcome `failed`, never raised.
- Scope (decisions 3 to 6, `assistant_sources`): court orders are court-public (every assistant user, every case);
  court filings follow the ordinary document visibility; notes, attachments, internal and admin documents, custody
  remarks, drafts and cause lists are never in reach. Every citation is re-checked against the scope that was sent;
  one outside it withholds the whole answer (outcome `failed`, family `scope`).
- Conversations (decision 8) belong to one user: no read path for anyone else, a case conversation only while its
  case is visible, filing citations re-checked at every read (an answer that drew on a filing the reader can no
  longer see is hidden). Messages are append-only; conversations are never deleted.
- Audit (decision 10): `assistant.asked` and `assistant.answered` carry digests, ids and counts, never the text;
  `assistant.court_order_opened` for every opening of the court-record view. Reading a conversation writes nothing.

With `services/assistant_preview.py`, the only Case Assistant module that imports the connector."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import and_, exists, func, literal, or_, select, text
from sqlalchemy.orm import Session, aliased, sessionmaker

from aslms.core.config import Settings
from aslms.domain.assistant import AssistantConversation, AssistantMessage, AssistantScope, MessageRole
from aslms.domain.cases import Case
from aslms.domain.documents import Document, Order, SourcetraceStatus
from aslms.domain.org import User
from aslms.domain.reference import Permission, RefDocType
from aslms.integration.sourcetrace import (
    Answer,
    AskRequest,
    AskScope,
    AssistantConnector,
    CaseContext,
    Citation,
    FilingRef,
    SourceTraceProtocolError,
    SourceTraceRejected,
    SourceTraceUnavailable,
    Turn,
    connector_state,
    get_assistant_connector,
)
from aslms.services import access, visibility
from aslms.services import assistant_sources as src
from aslms.services.assistant_preview import PreviewConnector, PreviewTooBroad
from aslms.services.audit import Actor, write_audit
from aslms.services.documents import ServedFile, serve_stored
from aslms.services.filetypes import INLINE_MIMES
from aslms.services.inbox import Page, clamp
from aslms.services.storage import LocalStore
from aslms.services.visibility import NotVisibleCase
from aslms.services.workflow_common import digest

log = logging.getLogger(__name__)

State = Literal["off", "preview", "not_implemented", "ready"]
SCOPES = ("case", "my_cases", "research")
MIN_QUESTION = 3
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
MAX_ANSWER = 20_000
MAX_PASSAGE = 1000
TITLE_CHARS = 80
IN_FLIGHT_EXTRA_SECONDS = 15
HOUR = timedelta(hours=1)
PREVIEW_BANNER = "Preview: passages found in the court records, not an AI answer. Questions are searched as words; no AI is used."
SOURCETRACE_BANNER = (
    "Answers come from SourceTrace. Check every source before relying on it. Do not type note text or internal "
    "remarks into a question."
)
HIDDEN_REASON = "This answer drew on a document you can no longer see."
UNAVAILABLE = "This source is no longer available."
WITHHELD = "The answer drew on material outside your reach and was withheld."
FAILURE_MESSAGES = {
    "unavailable": "The Case Assistant service is unavailable; try again later.",
    "rejected": "The Case Assistant service refused the question.",
    "protocol": "The Case Assistant service gave an answer that could not be read.",
    "scope": WITHHELD,
    "error": "The question could not be answered because of an unexpected error.",
}
ANSWERED_OUTCOMES = ("answered", "no_match")

_warned = {"prod_preview": False}


# ------------------------------------------------------------------------------------------------ errors


class AssistantError(ValueError):
    """A refused question (HTTP status and code on the class); nothing is stored."""

    code, http_status = "assistant_error", 400

    def __init__(self, message: str, **extra: Any):
        super().__init__(message)
        self.extra = extra


class AssistantOff(AssistantError):
    code, http_status = "assistant_off", 503


class BadQuestion(AssistantError):
    code, http_status = "bad_question", 422


class ScopeMismatch(AssistantError):
    code, http_status = "scope_mismatch", 422


class ConversationFull(AssistantError):
    code, http_status = "conversation_full", 409


class QuestionInFlight(AssistantError):
    code, http_status = "question_in_flight", 409


class AssistantLimit(AssistantError):
    code, http_status = "assistant_limit", 429

    def __init__(self, message: str, *, retry_after: int):
        super().__init__(message, retry_after=retry_after)
        self.retry_after = retry_after


class ConversationNotFound(LookupError):
    """Not the caller's conversation, or a case conversation whose case they can no longer see (HTTP 404)."""


class CourtOrderNotFound(LookupError):
    """Not in the court-order corpus, or not cited in the caller's own answer (HTTP 404)."""


# ------------------------------------------------------------------------------------------------ the switch


@dataclass(frozen=True)
class AssistantConfig:
    questions_per_hour: int = 30
    question_max_chars: int = 2000
    messages_per_conversation: int = 200
    timeout_seconds: float = 45.0
    history_turns: int = 6
    max_focus_cases: int = 1000
    max_filing_sources: int = 1000
    retry_delay: float = 2.0

    @classmethod
    def from_settings(cls, settings: Settings) -> AssistantConfig:
        return cls(
            questions_per_hour=settings.assistant_questions_per_hour,
            question_max_chars=settings.assistant_question_max_chars,
            messages_per_conversation=settings.assistant_messages_per_conversation,
            timeout_seconds=settings.assistant_timeout_seconds,
            history_turns=settings.assistant_history_turns,
            max_focus_cases=settings.assistant_max_focus_cases,
            max_filing_sources=settings.assistant_max_filing_sources,
        )


def assistant_state(settings: Settings) -> State:
    """Decision 2. Preview in `APP_ENV=prod` answers `off`, with one warning log (decision 7)."""
    mode = getattr(settings, "assistant_mode", "off") or "off"
    if mode == "preview":
        if settings.is_prod:
            if not _warned["prod_preview"]:
                _warned["prod_preview"] = True
                log.warning("ASSISTANT_MODE=preview is refused with APP_ENV=prod; the Case Assistant is off")
            return "off"
        return "preview"
    if mode == "sourcetrace":
        return "ready" if connector_state(settings) == "ready" else "not_implemented"
    return "off"


def portal_mode(settings: Settings) -> str:
    """`/me.assistant_mode`: the state reduced to `off` / `preview` / `sourcetrace`."""
    state = assistant_state(settings)
    return {"preview": "preview", "ready": "sourcetrace"}.get(state, "off")


def assistant_connector(settings: Settings, session_factory: sessionmaker) -> AssistantConnector | None:
    """The preview only in `preview`, the real connector only when `ready`, otherwise None. Never the fake."""
    state = assistant_state(settings)
    if state == "preview":
        return PreviewConnector(session_factory, settings)
    if state == "ready":
        return get_assistant_connector(settings)
    return None


def mode_of(connector: AssistantConnector) -> str:
    return "preview" if isinstance(connector, PreviewConnector) else "sourcetrace"


def banner(settings: Settings) -> str | None:
    state = assistant_state(settings)
    if state == "preview":
        return PREVIEW_BANNER
    if state == "ready":
        return SOURCETRACE_BANNER
    return None


def _value(v: Any) -> Any:
    return v.value if hasattr(v, "value") else v


def _used_last_hour(session: Session, user_id: uuid.UUID, now: datetime) -> tuple[int, datetime | None]:
    count, oldest = session.execute(
        select(func.count(), func.min(AssistantMessage.created_at))
        .select_from(AssistantMessage)
        .join(AssistantConversation, AssistantConversation.id == AssistantMessage.conversation_id)
        .where(
            AssistantConversation.user_id == user_id,
            AssistantMessage.role == MessageRole.USER,
            AssistantMessage.created_at > now - HOUR,
        )
    ).one()
    return int(count or 0), oldest


def status(session: Session, user: User, settings: Settings) -> dict[str, Any]:
    """`GET /assistant/status`: the mode, the state, the banner, the limits with the caller's questions of the
    last hour, and the scopes."""
    now = session.scalar(select(func.now()))
    used, _ = _used_last_hour(session, user.id, now)
    state = assistant_state(settings)
    return {
        "mode": settings.assistant_mode,
        "state": state,
        "banner": banner(settings),
        "limits": {
            "questions_per_hour": settings.assistant_questions_per_hour,
            "used_last_hour": used,
            "question_max_chars": settings.assistant_question_max_chars,
            "messages_per_conversation": settings.assistant_messages_per_conversation,
        },
        "scopes": list(SCOPES),
    }


# ------------------------------------------------------------------------------------------------ asking


@dataclass
class _Prepared:
    conversation_id: uuid.UUID
    question_id: uuid.UUID
    new_conversation: bool
    mode: str
    scope: str
    case_id: uuid.UUID | None
    orders: str
    focus_ids: list[uuid.UUID] | None
    filing_ids: set[uuid.UUID]
    request: AskRequest


@dataclass
class _Result:
    ok: bool
    answer: Answer | None = None
    family: str | None = None
    message: str | None = None
    raw: dict[str, Any] | None = None
    duration_ms: int = 0
    attempts: int = 1


@dataclass(frozen=True)
class AskResult:
    conversation_id: uuid.UUID
    question_id: uuid.UUID
    answer_id: uuid.UUID
    outcome: str
    extra: dict[str, Any] = field(default_factory=dict)


def _lock_user(session: Session, user_id: uuid.UUID) -> None:
    """One question of a user at a time across conversations (the hourly count cannot be raced)."""
    session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"assistant:{user_id}", 0))))


def _in_flight(session: Session, user_id: uuid.UUID, now: datetime, config: AssistantConfig) -> bool:
    """Any of the user's questions, in any conversation, still waiting for its answer within the answer time and
    a margin (review finding 3): one unanswered question per user, so new conversations cannot multiply the load."""
    answer = aliased(AssistantMessage, name="asst_answer")
    window = timedelta(seconds=config.timeout_seconds + IN_FLIGHT_EXTRA_SECONDS)
    return bool(
        session.scalar(
            select(
                exists(
                    select(literal(1))
                    .select_from(AssistantMessage)
                    .join(AssistantConversation, AssistantConversation.id == AssistantMessage.conversation_id)
                    .where(
                        AssistantConversation.user_id == user_id,
                        AssistantMessage.role == MessageRole.USER,
                        AssistantMessage.created_at > now - window,
                        ~exists().where(answer.reply_to_id == AssistantMessage.id),
                    )
                )
            )
        )
    )


def _clean_question(question: str | None, config: AssistantConfig) -> str:
    """The question, trimmed: refused when it holds a control character (NUL and the rest, review finding 11; tab,
    line feed and carriage return are allowed) or is too short or too long."""
    raw = question or ""
    if CONTROL_CHARS.search(raw):
        raise BadQuestion("a question may not contain control characters", reason="control_characters")
    q = raw.strip()
    if not (MIN_QUESTION <= len(q) <= config.question_max_chars):
        raise BadQuestion(f"a question is {MIN_QUESTION} to {config.question_max_chars} characters")
    return q


def _filing_ids(citations: list[dict[str, Any]] | None) -> list[uuid.UUID]:
    return [
        uuid.UUID(str(c["document_id"]))
        for c in citations or []
        if c.get("source_kind") == "court_filing" and c.get("document_id")
    ]


def _history(
    session: Session, user: User, conversation_id: uuid.UUID, connector_name: str, turns: int
) -> list[Turn]:
    """Decision 12: the last `turns` question and answer pairs of the conversation, only the connector's own answers
    that are still shown to the asker (answered or no match, no filing citation the asker can no longer see)."""
    if turns <= 0:
        return []
    answer = aliased(AssistantMessage, name="hist_answer")
    rows = session.execute(
        select(AssistantMessage.content, answer.content, answer.citations)
        .join(answer, answer.reply_to_id == AssistantMessage.id)
        .where(
            AssistantMessage.conversation_id == conversation_id,
            AssistantMessage.role == MessageRole.USER,
            answer.outcome.in_(ANSWERED_OUTCOMES),
            answer.connector == connector_name,
        )
        .order_by(AssistantMessage.created_at.desc())
        .limit(turns)
    ).all()
    visible = src.visible_filings(session, user, [d for _, _, cits in rows for d in _filing_ids(cits)])
    out = [Turn(question=q, answer=a) for q, a, cits in rows if all(d in visible for d in _filing_ids(cits))]
    return list(reversed(out))


def _orders_corpus(scope: str, include_related: bool) -> str:
    if scope == "research":
        return "all"
    if scope == "case" and include_related:
        return "focus_and_related"
    return "focus"


def _prepare(
    Session: sessionmaker,
    actor: Actor,
    user: User,
    *,
    question: str,
    scope: str,
    case: Case | uuid.UUID | None,
    conversation_id: uuid.UUID | None,
    include_related: bool,
    connector: AssistantConnector,
    config: AssistantConfig,
    via: str | None,
) -> _Prepared:
    """Transaction A (decision 9)."""
    mode = mode_of(connector)
    with Session() as s:
        u = s.get(User, user.id)
        if scope not in SCOPES:
            raise BadQuestion("scope is one of case, my_cases, research")
        if scope != "case" and case is not None:
            raise ScopeMismatch("only a case-scope question names a case")  # before any lookup (finding 6)
        case_row: Case | None = None
        if scope == "case":
            if case is None:
                raise BadQuestion("a case-scope question names its case")
            # an unknown case and one the caller cannot see are refused alike, before the question is read
            case_row = s.get(Case, case.id if isinstance(case, Case) else case)
            if case_row is None or not visibility.can_view_case(s, u, case_row):
                raise NotVisibleCase("no such case")
        q = _clean_question(question, config)
        _lock_user(s, u.id)
        now = s.scalar(select(func.now()))
        conv: AssistantConversation | None = None
        if conversation_id is not None:
            conv = s.scalar(
                select(AssistantConversation)
                .where(AssistantConversation.id == conversation_id, AssistantConversation.user_id == u.id)
                .with_for_update()
            )
            if conv is None:
                raise ConversationNotFound("no such conversation")
            if _value(conv.scope) != scope or conv.case_id != (case_row.id if case_row else None):
                raise ScopeMismatch("the question's scope or case differs from the conversation's")
            count = int(
                s.scalar(
                    select(func.count())
                    .select_from(AssistantMessage)
                    .where(AssistantMessage.conversation_id == conv.id)
                )
                or 0
            )
            if count + 2 > config.messages_per_conversation:
                raise ConversationFull("this conversation is full; start a new conversation")
        if _in_flight(s, u.id, now, config):
            raise QuestionInFlight("your last question is still being answered; wait for its answer")
        used, oldest = _used_last_hour(s, u.id, now)
        if used >= config.questions_per_hour:
            wait = (oldest + HOUR - now).total_seconds() if oldest is not None else 60
            raise AssistantLimit(
                f"{config.questions_per_hour} questions an hour is the limit",
                retry_after=max(1, math.ceil(wait)),
            )
        new = conv is None
        if conv is None:
            conv = AssistantConversation(
                user_id=u.id,
                case_id=case_row.id if case_row else None,
                scope=AssistantScope(scope),
                title=q[:TITLE_CHARS],
            )
            s.add(conv)
            s.flush()
        focus_ids, focus_truncated = src.focus_cases(s, u, scope, case_row, limit=config.max_focus_cases)
        filings, filings_truncated = src.filing_allow_list(
            s,
            u,
            focus_ids,
            "preview" if mode == "preview" else "sourcetrace",
            limit=config.max_filing_sources,
        )
        orders = _orders_corpus(scope, include_related)
        contexts = src.case_contexts(s, focus_ids or [])
        history = [] if new else _history(s, u, conv.id, str(connector.name), config.history_turns)
        truncated = focus_truncated or filings_truncated
        scope_info = {
            "kind": scope,
            "case_id": str(case_row.id) if case_row else None,
            "include_related": bool(include_related) if scope == "case" else False,
            "orders": orders,
            "focus_cases": len(focus_ids or []),
            "filings_passed": len(filings),
            "truncated": truncated,
        }
        msg = AssistantMessage(
            conversation_id=conv.id,
            role=MessageRole.USER,
            content=q,
            scope_info=scope_info,
            model_info={"via": via} if via else None,
        )
        s.add(msg)
        conv.last_message_at = now
        s.flush()
        after: dict[str, Any] = {
            "conversation_id": conv.id,
            "new_conversation": new,
            "scope": scope,
            "mode": mode,
            "question": digest(q),
            "include_related": scope_info["include_related"],
            "focus_cases": scope_info["focus_cases"],
            "filings_passed": scope_info["filings_passed"],
            "truncated": truncated,
        }
        if via:
            after["as_user_id"] = u.id
            after["via"] = via
        write_audit(
            s,
            actor,
            "assistant.asked",
            "assistant_message",
            msg.id,
            case_id=case_row.id if case_row else None,
            after=after,
        )
        request = AskRequest(
            request_id=msg.id,
            question=q,
            scope=AskScope(
                kind=scope,  # type: ignore[arg-type]
                focus=tuple(CaseContext(**c) for c in contexts),
                orders=orders,  # type: ignore[arg-type]
                filings=tuple(FilingRef(document_id=d, reference=r) for d, r in filings),
                truncated=truncated,
            ),
            history=tuple(history),
        )
        prepared = _Prepared(
            conversation_id=conv.id,
            question_id=msg.id,
            new_conversation=new,
            mode=mode,
            scope=scope,
            case_id=case_row.id if case_row else None,
            orders=orders,
            focus_ids=focus_ids,
            filing_ids={d for d, _ in filings},
            request=request,
        )
        s.commit()
    return prepared


def _valid(answer: Any) -> bool:
    return (
        isinstance(answer, Answer)
        and isinstance(answer.text, str)
        and answer.outcome in ANSWERED_OUTCOMES
        and isinstance(answer.citations, tuple | list)
        and all(isinstance(c, Citation) and isinstance(c.reference, str) for c in answer.citations)
        and (answer.raw is None or isinstance(answer.raw, dict))
        and isinstance(answer.info, dict)
    )


async def _call(
    connector: AssistantConnector,
    request: AskRequest,
    config: AssistantConfig,
    *,
    conversation_id: uuid.UUID | None = None,
) -> _Result:
    """The call, outside any transaction: the time budget `timeout_seconds`; one retry after
    `SourceTraceUnavailable` after `retry_delay`, only while the budget allows; none after a timeout, a refusal or
    a malformed answer (a person is waiting). An unexpected failure is logged by its class, the conversation id and
    the question's digest only: an exception's text or traceback can carry the question or bound parameters."""

    started = time.monotonic()
    deadline = started + config.timeout_seconds
    attempts = 0
    q_digest = digest(request.question)

    def took() -> int:
        return int((time.monotonic() - started) * 1000)

    while True:
        attempts += 1
        remaining = max(0.001, deadline - time.monotonic())
        try:
            answer = await asyncio.wait_for(connector.ask(request), timeout=remaining)
        except PreviewTooBroad as exc:
            return _Result(False, family="timeout", message=str(exc), duration_ms=took(), attempts=attempts)
        except TimeoutError:
            return _Result(
                False,
                family="timeout",
                message=f"No answer came within {config.timeout_seconds:g} seconds; try again later.",
                duration_ms=took(),
                attempts=attempts,
            )
        except SourceTraceUnavailable as exc:
            if attempts == 1 and deadline - time.monotonic() > config.retry_delay:
                await asyncio.sleep(config.retry_delay)
                continue
            return _Result(
                False,
                family="unavailable",
                message=FAILURE_MESSAGES["unavailable"],
                raw=exc.response,
                duration_ms=took(),
                attempts=attempts,
            )
        except SourceTraceRejected as exc:
            return _Result(
                False,
                family="rejected",
                message=FAILURE_MESSAGES["rejected"],
                raw=exc.response,
                duration_ms=took(),
                attempts=attempts,
            )
        except SourceTraceProtocolError as exc:
            return _Result(
                False,
                family="protocol",
                message=FAILURE_MESSAGES["protocol"],
                raw=exc.response,
                duration_ms=took(),
                attempts=attempts,
            )
        except Exception as exc:  # noqa: BLE001 — any connector failure is a stored, failed answer
            log.error(
                "the Case Assistant connector failed: %s (conversation %s, question sha256 %s, %d characters)",
                type(exc).__name__,
                conversation_id,
                q_digest["sha256"],
                q_digest["length"],
            )
            return _Result(
                False,
                family="error",
                message=FAILURE_MESSAGES["error"],
                duration_ms=took(),
                attempts=attempts,
            )
        if not _valid(answer):
            return _Result(
                False,
                family="protocol",
                message=FAILURE_MESSAGES["protocol"],
                duration_ms=took(),
                attempts=attempts,
            )
        return _Result(True, answer=answer, duration_ms=took(), attempts=attempts)


def _order_for(
    session: Session, doc: Document, focus_ids: list[uuid.UUID] | None
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """The order a court-order document is cited as: one of the focus cases' first, then its own case's, then the
    latest; never of a merged case."""
    oc = aliased(Case, name="cite_case")
    stmt = (
        select(Order.id, Order.case_id)
        .join(oc, oc.id == Order.case_id)
        .where(Order.document_id == doc.id, oc.merged_into_case_id.is_(None))
    )
    ranks = []
    if focus_ids:
        ranks.append(Order.case_id.in_(focus_ids).desc())
    if doc.case_id is not None:
        ranks.append((Order.case_id == doc.case_id).desc())
    row = session.execute(stmt.order_by(*ranks, Order.order_date.desc(), Order.id).limit(1)).first()
    return (row[0], row[1]) if row else (None, None)


def _map_citations(
    session: Session, user: User, prepared: _Prepared, citations: tuple[Citation, ...] | list[Citation]
) -> list[dict[str, Any]]:
    """Decisions 6, 8 and 12: each citation to a document (preview: by document id; sourcetrace: by
    `sourcetrace_ref`), re-checked against the scope that was sent; `NotCitable` for any outside it."""
    out: list[dict[str, Any]] = []
    for c in citations:
        doc_id: uuid.UUID | None
        if prepared.mode == "preview":
            try:
                doc_id = c.document_id or uuid.UUID(c.reference)
            except ValueError:
                doc_id = None
        else:
            doc_id = session.scalar(
                select(Document.id)
                .where(
                    Document.sourcetrace_ref == c.reference,
                    Document.sourcetrace_status == SourcetraceStatus.INGESTED,
                )
                .limit(1)
            )
        if doc_id is None:
            raise src.NotCitable("a citation names no document held in ASLMS")
        kind = src.assert_citable(
            session,
            user,
            doc_id,
            prepared.filing_ids,
            orders=prepared.orders,  # type: ignore[arg-type]
            focus_case_ids=prepared.focus_ids,
        )
        doc = session.get(Document, doc_id)
        order_id, case_id = (None, doc.case_id)
        related = False
        if kind == "court_order":
            order_id, case_id = _order_for(session, doc, prepared.focus_ids)
            if prepared.focus_ids:
                related = bool(
                    session.scalar(select(exists(src.related_documents([doc_id], prepared.focus_ids))))
                )
        item: dict[str, Any] = {
            "document_id": str(doc_id),
            "order_id": str(order_id) if order_id else None,
            "case_id": str(case_id) if case_id else None,
            "source_kind": kind,
            "page": c.page if isinstance(c.page, int) and c.page > 0 else None,
            "passage": (c.passage or "")[:MAX_PASSAGE] or None,
            "rank": c.rank,
            "related": related,
        }
        if c.locator is not None:
            item["locator"] = c.locator
        out.append(item)
    return out


def _record(
    Session: sessionmaker,
    actor: Actor,
    user: User,
    prepared: _Prepared,
    connector: AssistantConnector,
    result: _Result,
    via: str | None,
) -> tuple[uuid.UUID, str]:
    """Transaction B (decision 9)."""
    with Session() as s:
        u = s.get(User, user.id)
        conv = s.get(AssistantConversation, prepared.conversation_id)
        citations: list[dict[str, Any]] | None = None
        if result.ok and result.answer is not None:
            try:
                citations = _map_citations(s, u, prepared, result.answer.citations)
            except src.NotCitable:
                result = _Result(
                    False,
                    family="scope",
                    message=WITHHELD,
                    raw=result.answer.raw,
                    duration_ms=result.duration_ms,
                    attempts=result.attempts,
                )
        if result.ok and result.answer is not None:
            outcome = result.answer.outcome
            content = result.answer.text[:MAX_ANSWER]
            info = dict(result.answer.info or {})
            raw = result.answer.raw
            family = None
        else:
            outcome, content, info, raw, family = (
                "failed",
                result.message or "failed",
                {},
                result.raw,
                result.family,
            )
        if via:
            info["via"] = via
        msg = AssistantMessage(
            conversation_id=conv.id,
            role=MessageRole.ASSISTANT,
            content=content,
            reply_to_id=prepared.question_id,
            mode=prepared.mode,
            connector=str(getattr(connector, "name", "unknown"))[:40],
            outcome=outcome,
            error_family=family,
            duration_ms=result.duration_ms,
            citations=citations,
            model_info=info or None,
            response=raw if prepared.mode == "sourcetrace" else None,
        )
        s.add(msg)
        conv.last_message_at = s.scalar(select(func.now()))
        s.flush()
        write_audit(
            s,
            actor,
            "assistant.answered",
            "assistant_message",
            msg.id,
            case_id=prepared.case_id,
            after={
                "question_id": prepared.question_id,
                "conversation_id": conv.id,
                "mode": prepared.mode,
                "connector": msg.connector,
                "outcome": outcome,
                "error_family": family,
                "duration_ms": result.duration_ms,
                "attempts": result.attempts,
                "answer": digest(content),
                "citations": [
                    {"document_id": c["document_id"], "order_id": c["order_id"]} for c in citations or []
                ],
            },
        )
        answer_id = msg.id
        s.commit()
    return answer_id, outcome


async def ask(
    Session: sessionmaker,
    actor: Actor,
    user: User,
    *,
    question: str,
    scope: str,
    case: Case | uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    include_related: bool = True,
    connector: AssistantConnector | None,
    config: AssistantConfig,
    via: str | None = None,
) -> AskResult:
    """Decisions 5, 6, 9, 10 and 12: refusals before storing raise (`AssistantOff`, `BadQuestion`, `ScopeMismatch`,
    `ConversationFull`, `QuestionInFlight`, `AssistantLimit`, `NotVisibleCase`, `ConversationNotFound`); a
    connector failure is stored as a `failed` answer and returned."""
    if connector is None:
        raise AssistantOff("the Case Assistant is off")
    prepared = _prepare(
        Session,
        actor,
        user,
        question=question,
        scope=scope,
        case=case,
        conversation_id=conversation_id,
        include_related=include_related,
        connector=connector,
        config=config,
        via=via,
    )
    result = await _call(connector, prepared.request, config, conversation_id=prepared.conversation_id)
    answer_id, outcome = _record(Session, actor, user, prepared, connector, result, via)
    return AskResult(
        conversation_id=prepared.conversation_id,
        question_id=prepared.question_id,
        answer_id=answer_id,
        outcome=outcome,
    )


# ------------------------------------------------------------------------------------------------ reading


def _case_brief(case: Case | None) -> dict[str, Any] | None:
    if case is None:
        return None
    return {"id": case.id, "ref_no": case.ref_no, "case_no_text": case.case_no_text}


def _message_counts(session: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    return dict(
        session.execute(
            select(AssistantMessage.conversation_id, func.count())
            .where(AssistantMessage.conversation_id.in_(ids))
            .group_by(AssistantMessage.conversation_id)
        ).all()
    )


def conversation_out(
    session: Session, conv: AssistantConversation, *, count: int | None = None, case: Case | None = None
) -> dict[str, Any]:
    if case is None and conv.case_id is not None:
        case = session.get(Case, conv.case_id)
    if count is None:
        count = _message_counts(session, [conv.id]).get(conv.id, 0)
    return {
        "id": conv.id,
        "scope": _value(conv.scope),
        "case": _case_brief(case),
        "title": conv.title,
        "last_message_at": conv.last_message_at,
        "created_at": conv.created_at,
        "message_count": int(count or 0),
    }


def _sighted_case(session: Session, user: User):
    """A conversation without a case, or one whose case the reader can still see (correlated on the row)."""
    return or_(
        AssistantConversation.case_id.is_(None),
        exists(
            select(literal(1))
            .select_from(Case)
            .where(Case.id == AssistantConversation.case_id, visibility.visible_case_condition(session, user))
        ),
    )


def conversations(
    session: Session,
    user: User,
    *,
    scope: str | None = None,
    case: Case | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> Page:
    """The caller's own conversations, newest first; case conversations of cases they can no longer see are left
    out. Writes nothing."""
    stmt = select(AssistantConversation).where(
        AssistantConversation.user_id == user.id, _sighted_case(session, user)
    )
    if scope:
        if scope not in SCOPES:
            raise BadQuestion("scope is one of case, my_cases, research")
        stmt = stmt.where(AssistantConversation.scope == AssistantScope(scope))
    if case is not None:
        stmt = stmt.where(AssistantConversation.case_id == case.id)
    limit, offset = clamp(limit, offset)
    total = int(session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
    rows = list(
        session.scalars(
            stmt.order_by(
                AssistantConversation.last_message_at.desc().nulls_last(),
                AssistantConversation.created_at.desc(),
                AssistantConversation.id,
            )
            .limit(limit)
            .offset(offset)
        ).all()
    )
    counts = _message_counts(session, [c.id for c in rows])
    cases = {
        c.id: c
        for c in session.scalars(
            select(Case).where(Case.id.in_([r.case_id for r in rows if r.case_id]))
        ).all()
    }
    return Page(
        [conversation_out(session, r, count=counts.get(r.id, 0), case=cases.get(r.case_id)) for r in rows],
        total,
    )


def own_conversation(session: Session, user: User, conversation_id: uuid.UUID) -> AssistantConversation:
    conv = session.scalar(
        select(AssistantConversation).where(
            AssistantConversation.id == conversation_id, AssistantConversation.user_id == user.id
        )
    )
    if conv is None:
        raise ConversationNotFound("no such conversation")
    if conv.case_id is not None and not visibility.can_view_case(session, user, conv.case_id):
        raise ConversationNotFound("no such conversation")
    return conv


def _uuid(v: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(v)) if v else None
    except ValueError:
        return None


def _unavailable(kind: str) -> dict[str, Any]:
    """A source the reader can no longer reach (review finding 2): only that it is unavailable, nothing that names
    it (no document, order, type, date, page, case number or CNR)."""
    return {
        "document_id": None,
        "order_id": None,
        "case": {"id": None, "case_no_text": None, "cnr": None, "visible": False},
        "source_kind": kind,
        "doc_type_label": None,
        "doc_date": None,
        "order_no": None,
        "page": None,
        "passage": None,
        "related": False,
        "available": False,
        "unavailable_reason": UNAVAILABLE,
        "open": None,
    }


def _document_openable_cases(session: Session, user: User, case_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """The cases among `case_ids` seen through a membership that itself holds `documents.view` (review finding 8):
    the ordinary order file route applies the document rule per membership, so the login's union of functions is
    not enough. Court records pass every record setting, so the case's sight is the whole rule."""
    if not case_ids:
        return set()
    conds = [
        cond
        for member in access.members(session, user)
        if member.holds(Permission.DOCUMENTS_VIEW)
        for _, cond in visibility.member_bases(session, member)
    ]
    if not conds:
        return set()
    return set(session.scalars(select(Case.id).where(Case.id.in_(case_ids), or_(*conds))).all())


def messages_out(session: Session, user: User, msgs: list[AssistantMessage]) -> list[dict[str, Any]]:
    """`MessageOut` for each message: filing citations re-checked against the reader's current document visibility
    (decision 8). A failing one shows only that it is unavailable and hides the answer's text. Court-order citations
    are court-public and stay shown while the order is still in the court-order corpus (the document a current court
    record, not archived, the order's case not merged); otherwise they show unavailable too."""
    cits = [(m, c) for m in msgs for c in (m.citations or [])]
    doc_ids = {d for _, c in cits if (d := _uuid(c.get("document_id")))}
    order_ids = {o for _, c in cits if (o := _uuid(c.get("order_id")))}
    filings = src.visible_filings(session, user, [d for m in msgs for d in _filing_ids(m.citations)])
    docs = (
        {d.id: d for d in session.scalars(select(Document).where(Document.id.in_(doc_ids))).all()}
        if doc_ids
        else {}
    )
    orders = (
        {o.id: o for o in session.scalars(select(Order).where(Order.id.in_(order_ids))).all()}
        if order_ids
        else {}
    )
    order_docs = {
        d for _, c in cits if c.get("source_kind") != "court_filing" and (d := _uuid(c.get("document_id")))
    }
    in_corpus = set(session.scalars(src.court_order_documents(order_docs)).all()) if order_docs else set()
    case_ids = {k for _, c in cits if (k := _uuid(c.get("case_id")))} | {o.case_id for o in orders.values()}
    cases = (
        {c.id: c for c in session.scalars(select(Case).where(Case.id.in_(case_ids))).all()}
        if case_ids
        else {}
    )
    visible = (
        set(
            session.scalars(
                select(Case.id).where(Case.id.in_(case_ids), visibility.visible_case_condition(session, user))
            ).all()
        )
        if case_ids
        else set()
    )
    labels = {r.code: r.label for r in session.scalars(select(RefDocType)).all()}
    openable = _document_openable_cases(session, user, visible)

    def citation_out(m: AssistantMessage, c: dict[str, Any]) -> dict[str, Any]:
        doc_id = _uuid(c.get("document_id"))
        order_id = _uuid(c.get("order_id"))
        case_id = _uuid(c.get("case_id"))
        doc = docs.get(doc_id) if doc_id else None
        order = orders.get(order_id) if order_id else None
        kind = c.get("source_kind") or "court_order"
        if kind == "court_filing":
            if doc is None or doc_id not in filings:
                return _unavailable(kind)
            open_ = {
                "kind": "document",
                "href": f"/documents/{doc_id}/file?disposition="
                + ("inline" if doc.mime in INLINE_MIMES else "attachment"),
            }
        else:
            if doc is None or order is None or order.document_id != doc_id or doc_id not in in_corpus:
                return _unavailable(kind)
            case_id = order.case_id
            order_case = cases.get(case_id)
            if order_case is None or order_case.merged_into_case_id is not None:
                return _unavailable(kind)
            if case_id in openable:
                open_ = {
                    "kind": "document",
                    "href": f"/cases/{case_id}/orders/{order_id}/file?disposition=inline",
                }
            else:
                open_ = {"kind": "court_order", "href": f"/assistant/court-orders/{order_id}?message={m.id}"}
        case = cases.get(case_id) if case_id else None
        case_visible = case_id in visible
        doc_type = _value(doc.doc_type)
        return {
            "document_id": doc_id,
            "order_id": order_id,
            "case": {
                "id": case_id if case_visible else None,
                "case_no_text": case.case_no_text if case else None,
                "cnr": case.cnr if case else None,
                "visible": case_visible,
            },
            "source_kind": kind,
            "doc_type_label": labels.get(doc_type, doc_type) if doc_type else None,
            "doc_date": order.order_date if order is not None else doc.doc_date,
            "order_no": order.order_no if order is not None else None,
            "page": c.get("page"),
            "passage": c.get("passage"),
            "related": bool(c.get("related")),
            "available": True,
            "unavailable_reason": None,
            "open": open_,
        }

    out = []
    for m in msgs:
        items = [citation_out(m, c) for c in (m.citations or [])]
        hidden = any(not i["available"] for i in items if i["source_kind"] == "court_filing")
        role = _value(m.role)
        out.append(
            {
                "id": m.id,
                "role": role,
                "created_at": m.created_at,
                "content": None if hidden else m.content,
                "hidden_reason": HIDDEN_REASON if hidden else None,
                "mode": m.mode,
                "outcome": m.outcome,
                "error": (
                    {"family": m.error_family, "message": m.content} if m.outcome == "failed" else None
                ),
                "reply_to_id": m.reply_to_id,
                "citations": items,
            }
        )
    return out


def conversation(
    session: Session,
    user: User,
    conversation_id: uuid.UUID,
    *,
    before: uuid.UUID | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """The conversation with its messages, oldest first (the latest `limit` before the message `before`), filing
    citations re-checked (decision 8). Writes nothing."""
    conv = own_conversation(session, user, conversation_id)
    limit = max(1, min(int(limit or 50), 200))
    stmt = select(AssistantMessage).where(AssistantMessage.conversation_id == conv.id)
    if before is not None:
        mark = session.scalar(
            select(AssistantMessage).where(
                AssistantMessage.id == before, AssistantMessage.conversation_id == conv.id
            )
        )
        if mark is None:
            raise ConversationNotFound("no such message in this conversation")
        stmt = stmt.where(
            or_(
                AssistantMessage.created_at < mark.created_at,
                and_(AssistantMessage.created_at == mark.created_at, AssistantMessage.id < mark.id),
            )
        )
    rows = list(
        session.scalars(
            stmt.order_by(AssistantMessage.created_at.desc(), AssistantMessage.id.desc()).limit(limit + 1)
        ).all()
    )
    has_more = len(rows) > limit
    msgs = list(reversed(rows[:limit]))
    return {
        "conversation": conversation_out(session, conv),
        "messages": messages_out(session, user, msgs),
        "has_more": has_more,
    }


def message(session: Session, user: User, message_id: uuid.UUID) -> dict[str, Any]:
    """One of the caller's own messages as `MessageOut` (after `ask`)."""
    msg = session.get(AssistantMessage, message_id)
    if msg is None:
        raise ConversationNotFound("no such message")
    own_conversation(session, user, msg.conversation_id)
    return messages_out(session, user, [msg])[0]


# ------------------------------------------------------------------------------------------------ the court-record view


@dataclass
class _CitedOrder:
    order: Order
    document: Document
    case: Case
    message_id: uuid.UUID


def _cited_order(
    session: Session, user: User, order_id: uuid.UUID, message_id: uuid.UUID | None
) -> _CitedOrder:
    """Decision 11: the order's document is in the court-order corpus, and the answer `message_id` is one of the
    caller's own and cites this order. Otherwise `CourtOrderNotFound`."""
    if message_id is None:
        raise CourtOrderNotFound("no such order")
    cited = session.scalar(
        select(AssistantMessage.id)
        .join(AssistantConversation, AssistantConversation.id == AssistantMessage.conversation_id)
        .where(
            AssistantMessage.id == message_id,
            AssistantMessage.role == MessageRole.ASSISTANT,
            AssistantConversation.user_id == user.id,
            AssistantMessage.citations.contains([{"order_id": str(order_id)}]),
        )
    )
    if cited is None:
        raise CourtOrderNotFound("no such order")
    order = session.get(Order, order_id)
    if order is None or order.document_id is None:
        raise CourtOrderNotFound("no such order")
    in_corpus = session.scalar(
        select(literal(True))
        .select_from(Document)
        .where(Document.id == order.document_id, src.court_order_condition())
    )
    case = session.get(Case, order.case_id)
    if not in_corpus or case is None or case.merged_into_case_id is not None:
        raise CourtOrderNotFound("no such order")
    return _CitedOrder(order, session.get(Document, order.document_id), case, message_id)


def _opened(
    session: Session,
    actor: Actor,
    cited: _CitedOrder,
    *,
    what: str,
    disposition: str | None,
    case_visible: bool,
) -> None:
    write_audit(
        session,
        actor,
        "assistant.court_order_opened",
        "order",
        cited.order.id,
        case_id=cited.case.id,
        after={
            "document_id": cited.document.id,
            "what": what,
            "disposition": disposition,
            "message_id": cited.message_id,
            "case_visible": case_visible,
        },
    )


def court_order_view(
    session: Session, actor: Actor, user: User, order_id: uuid.UUID, message_id: uuid.UUID | None
) -> dict[str, Any]:
    """Decision 11: the order (number, date, kind, judge) and the case's court-public facts, never the owner,
    recommendations, custody, stage, notes, documents, alerts or `ref_no`. Audited."""
    cited = _cited_order(session, user, order_id, message_id)
    case_visible = visibility.can_view_case(session, user, cited.case)
    facts = src.case_contexts(session, [cited.case.id])[0]
    facts.pop("case_id", None)
    facts["parties"] = list(facts["parties"])
    facts["advocates"] = list(facts["advocates"])
    facts["acts"] = list(facts["acts"])
    _opened(session, actor, cited, what="facts", disposition=None, case_visible=case_visible)
    o = cited.order
    return {
        "order": {
            "id": o.id,
            "order_no": o.order_no,
            "order_date": o.order_date,
            "kind": _value(o.kind),
            "judge": o.order_judge_name,
        },
        "case": facts,
        "case_visible": case_visible,
    }


def court_order_file(
    session: Session,
    actor: Actor,
    user: User,
    order_id: uuid.UUID,
    message_id: uuid.UUID | None,
    *,
    store: LocalStore,
    disposition: str = "inline",
) -> ServedFile:
    """Decision 11: the order PDF from the store (inline only for PDF), after the same checks; audited once the
    file is known to be there."""
    disposition = (disposition or "inline").strip().lower()
    if disposition not in ("inline", "attachment"):
        raise BadQuestion("disposition must be inline or attachment")
    cited = _cited_order(session, user, order_id, message_id)
    served = serve_stored(session, cited.document, disposition, store=store)
    _opened(
        session,
        actor,
        cited,
        what="file",
        disposition=disposition,
        case_visible=visibility.can_view_case(session, user, cited.case),
    )
    return served


# ------------------------------------------------------------------------------------------------ the check


def check(session: Session) -> dict[str, int]:
    """`aslms assistant check`: stored citations naming a document that is not a court order or a court filing (a
    note attachment, an internal, admin or cause-list document, a private one, or none at all), and conversations
    with a case scope but no case. Both must be 0."""
    bad_citations = int(
        session.scalar(
            text(
                """
                SELECT count(*)
                FROM assistant_messages m
                CROSS JOIN LATERAL jsonb_array_elements(
                    CASE WHEN jsonb_typeof(m.citations) = 'array' THEN m.citations ELSE '[]'::jsonb END
                ) AS c(value)
                LEFT JOIN documents d ON d.id::text = c.value ->> 'document_id'
                WHERE NOT coalesce(
                    (d.kind = 'order' AND d.doc_group = 'court_record')
                    OR (d.kind = 'upload' AND d.doc_group = 'court_filing' AND d.visibility <> 'private_to_office'),
                    false
                )
                """
            )
        )
        or 0
    )
    orphan = int(
        session.scalar(
            select(func.count())
            .select_from(AssistantConversation)
            .where(
                AssistantConversation.scope == AssistantScope.CASE, AssistantConversation.case_id.is_(None)
            )
        )
        or 0
    )
    return {"citations_out_of_rule": bad_citations, "case_conversations_without_case": orphan}
