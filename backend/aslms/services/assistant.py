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

Design `assistant-ollama` (round 1) adds the fourth mode `ollama`, a local model on Government servers, allowed in
prod (a cloud model name or address answers `off`): readiness and a slot before transaction A (503 `assistant_loading`,
`assistant_unavailable`, `assistant_busy`, nothing stored), court information in every scope, the citation check, and
the switch "Include This Case's Internal Records" (`include_internal`): a one-way server-side state of one case-tab
conversation, after which that conversation's questions also read that case's internal records the asker may open
(`assistant_internal`), never drafts and never another case's. Internal citations hold references, are accepted only
under five conditions, and are re-checked at every read (an answer that drew on a record the reader can no longer see
is hidden).

With `services/assistant_preview.py` and `services/assistant_ollama.py`, the only Case Assistant modules that import
the connector."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import and_, exists, func, literal, or_, select, text
from sqlalchemy.orm import Session, aliased, sessionmaker

from aslms.core import clock
from aslms.core.config import Settings
from aslms.domain.assistant import AssistantConversation, AssistantMessage, AssistantScope, MessageRole
from aslms.domain.cases import Case
from aslms.domain.documents import Document, Order, SourcetraceStatus
from aslms.domain.org import User
from aslms.domain.reference import Permission, RefDocType, RefNoteKind
from aslms.domain.workflow import CaseNote
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
from aslms.services import assistant_facts as quick_facts
from aslms.services import assistant_internal as internal_records
from aslms.services import assistant_ollama as ollama
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
MAX_CONTEXT = 12_000
TITLE_CHARS = 80
IN_FLIGHT_EXTRA_SECONDS = 15
HOUR = timedelta(hours=1)
PREVIEW_BANNER = "Preview: passages found in the court records, not an AI answer. Questions are searched as words; no AI is used."
SOURCETRACE_BANNER = (
    "Answers come from SourceTrace. Check every source before relying on it. Do not type note text or internal "
    "remarks into a question."
)
OLLAMA_BANNER = (
    "Answers are written by a local AI model on the Government's own servers, from the records found. The model can "
    "make mistakes: check every answer against the cited order or record before relying on it."
)
HIDDEN_REASON = "This answer drew on a document you can no longer see."
HIDDEN_INTERNAL = "This answer drew on a record you can no longer see."
NEW_TITLE = "New Conversation"
INTERNAL_KINDS = internal_records.INTERNAL_KINDS
COURT_KINDS = ("court_order", "court_filing")
SOURCE_KINDS = ("court_order", "court_filing", "case_details", "note", "file_movement", "department_document")
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

_warned = {"prod_preview": False, "cloud": False}


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


class AssistantLoading(AssistantError):
    """Design `assistant-ollama`, decision 13: the model is held but not loaded; a load has started."""

    code, http_status = "assistant_loading", 503

    def __init__(
        self,
        message: str = "The Case Assistant is starting; try again in a minute.",
        *,
        retry_after: int = 30,
    ):
        super().__init__(message, retry_after=retry_after)
        self.retry_after = retry_after


class AssistantUnavailable(AssistantError):
    code, http_status = "assistant_unavailable", 503


class AssistantBusy(AssistantError):
    code, http_status = "assistant_busy", 503

    def __init__(
        self, message: str = "The Case Assistant is busy; try again shortly.", *, retry_after: int = 5
    ):
        super().__init__(message, retry_after=retry_after)
        self.retry_after = retry_after


class InternalUnavailable(AssistantError):
    """The switch outside ollama mode."""

    code, http_status = "internal_unavailable", 422


class InternalNotPermitted(AssistantError):
    """The switch without the case page's read guard."""

    code, http_status = "internal_not_permitted", 403


class NoInternalRecords(AssistantError):
    code, http_status = "no_internal_records", 422


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
    if mode == "ollama":
        # design assistant-ollama, decision 12: a cloud model name or address is never used (preflight refuses it)
        if ollama.cloud_problems(settings):
            if not _warned["cloud"]:
                _warned["cloud"] = True
                log.warning(
                    "ASSISTANT_MODE=ollama with a cloud model or address is refused; the Case Assistant is off"
                )
            return "off"
        return "ready"
    return "off"


def _mode_name(settings: Settings) -> str:
    return (getattr(settings, "assistant_mode", "off") or "off").strip().lower()


def portal_mode(settings: Settings) -> str:
    """`/me.assistant_mode`: the state reduced to `off` / `preview` / `sourcetrace` / `ollama`."""
    state = assistant_state(settings)
    if state == "preview":
        return "preview"
    if state == "ready":
        return "ollama" if _mode_name(settings) == "ollama" else "sourcetrace"
    return "off"


def assistant_connector(settings: Settings, session_factory: sessionmaker) -> AssistantConnector | None:
    """The preview only in `preview`, the Ollama connector (one per process) in `ollama`, the real SourceTrace
    connector only when `ready`, otherwise None. Never the fake."""
    state = assistant_state(settings)
    if state == "preview":
        return PreviewConnector(session_factory, settings)
    if state == "ready":
        if _mode_name(settings) == "ollama":
            return ollama.get_connector(settings, session_factory)
        return get_assistant_connector(settings)
    return None


def mode_of(connector: AssistantConnector) -> str:
    if isinstance(connector, PreviewConnector):
        return "preview"
    if isinstance(connector, ollama.OllamaConnector):
        return "ollama"
    return "sourcetrace"


def banner(settings: Settings) -> str | None:
    state = assistant_state(settings)
    if state == "preview":
        return PREVIEW_BANNER
    if state == "ready":
        return OLLAMA_BANNER if _mode_name(settings) == "ollama" else SOURCETRACE_BANNER
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


def engine(connector: AssistantConnector | None) -> dict[str, Any] | None:
    """`status.engine` (design `assistant-ollama`, decision 13): the local model's readiness (which may start a
    load), or None for the other engines."""
    if not isinstance(connector, ollama.OllamaConnector):
        return None
    r = connector.readiness()
    return {"kind": "ollama", "model": connector.model, "readiness": r.state, "reason": r.reason}


def status(
    session: Session, user: User, settings: Settings, connector: AssistantConnector | None = None
) -> dict[str, Any]:
    """`GET /assistant/status`: the mode, the state, the banner, the limits with the caller's questions of the
    last hour, the scopes, the engine and where internal records may be included (`switch` in ollama mode, on the
    case tab only; `never` otherwise)."""
    now = session.scalar(select(func.now()))
    used, _ = _used_last_hour(session, user.id, now)
    state = assistant_state(settings)
    is_ollama = isinstance(connector, ollama.OllamaConnector)
    return {
        "mode": "ollama" if is_ollama else settings.assistant_mode,
        "state": "ready" if is_ollama else state,
        "banner": OLLAMA_BANNER if is_ollama else banner(settings),
        "engine": engine(connector),
        "internal_records": "switch" if is_ollama else "never",
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
    details: bool = False
    internal_on: bool = False
    internal: internal_records.InternalRecords | None = None
    question: str = ""
    facts: tuple[str, ...] | None = (
        None  # design assistant-polish: a quick fact answered from the case record
    )


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
    session: Session,
    user: User,
    conversation_id: uuid.UUID,
    connector_name: str,
    turns: int,
    conversation: AssistantConversation | None = None,
    *,
    outcomes: tuple[str, ...] = ANSWERED_OUTCOMES,
) -> list[Turn]:
    """Decision 12: the last `turns` question and answer pairs of the conversation, only the connector's own answers
    that are still shown to the asker (answered or no match, no filing citation the asker can no longer see, and —
    design `assistant-ollama`, decision 10 — no internal citation the asker can no longer see). One conversation id
    only: history never crosses conversations. Design `assistant-polish`, decision 2: `outcomes` narrows the turns
    (`("answered",)` for the Ollama connector, so a `no_match` answer and its question are never fed back)."""
    if turns <= 0:
        return []
    answer = aliased(AssistantMessage, name="hist_answer")
    rows = session.execute(
        select(AssistantMessage.content, answer.content, answer.citations)
        .join(answer, answer.reply_to_id == AssistantMessage.id)
        .where(
            AssistantMessage.conversation_id == conversation_id,
            AssistantMessage.role == MessageRole.USER,
            answer.outcome.in_(outcomes),
            answer.connector == connector_name,
        )
        .order_by(AssistantMessage.created_at.desc())
        .limit(turns)
    ).all()
    visible = src.visible_filings(session, user, [d for _, _, cits in rows for d in _filing_ids(cits)])
    conv = conversation or session.get(AssistantConversation, conversation_id)

    def shown(cits: list[dict[str, Any]] | None) -> bool:
        if not all(d in visible for d in _filing_ids(cits)):
            return False
        return all(
            internal_records.recheck(session, user, conv, c)
            for c in cits or []
            if c.get("source_kind") in INTERNAL_KINDS
        )

    out = [Turn(question=q, answer=a) for q, a, cits in rows if shown(cits)]
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
    facts: tuple[str, ...] | None = None,
) -> _Prepared:
    """Transaction A (decision 9). Design `assistant-polish`, decision 14: for a quick fact (`facts`) unchanged apart
    from the audit's `quick_fact`, and nothing gathered for a model (no case details, internal records or history)."""
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
        if conv is not None and conv.title == NEW_TITLE and not conv.last_message_at:
            conv.title = q[:TITLE_CHARS]  # the first question of an empty conversation switched on before it
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
            mode if mode in ("preview", "ollama") else "sourcetrace",
            limit=config.max_filing_sources,
        )
        # design assistant-ollama, decisions 4 and 5: case details need the case page's read guard; internal records
        # only in ollama mode, for the stored case-scope conversation switched on before this question, of its case
        details = mode == "ollama" and not facts and internal_records.read_guard(s, u)
        internal_on = (
            not facts
            and mode == "ollama"
            and scope == "case"
            and not new
            and conv.internal_included_at is not None
            and case_row is not None
            and conv.case_id == case_row.id
        )
        internal = (
            internal_records.gather(
                s,
                u,
                case_row,
                q,
                budget_chars=int(getattr(connector, "settings", None).assistant_ollama_internal_chars),
            )
            if internal_on
            else None
        )
        orders = _orders_corpus(scope, include_related)
        contexts = src.case_contexts(s, focus_ids or [])
        history = (
            []
            if new or facts
            else _history(
                s,
                u,
                conv.id,
                str(connector.name),
                config.history_turns,
                conv,
                outcomes=("answered",) if mode == "ollama" else ANSWERED_OUTCOMES,
            )
        )
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
        if facts:
            after["quick_fact"] = list(facts)
        elif mode == "ollama":
            after["internal"] = internal_on
            after["internal_supplied"] = {
                k: int((internal.counts if internal else {}).get(k, 0)) for k in INTERNAL_KINDS
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
            details=details,
            internal_on=internal_on,
            internal=internal,
            question=q,
            facts=facts,
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
    invoke: Any = None,
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
            call = invoke() if invoke is not None else connector.ask(request)
            answer = await asyncio.wait_for(call, timeout=remaining)
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
    if prepared.facts:
        return _map_facts(prepared, citations)
    if prepared.mode == "ollama":
        return _map_ollama(session, user, prepared, citations)
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


def _map_facts(prepared: _Prepared, citations: tuple[Citation, ...] | list[Citation]) -> list[dict[str, Any]]:
    """Design `assistant-polish`, decision 14: a quick-fact answer cites exactly one source, the Case Details of the
    conversation's own case, label `S1`, in every mode; anything else is `NotCitable`."""
    items = list(citations)
    if len(items) != 1 or prepared.case_id is None:
        raise src.NotCitable("a quick fact cites only its case's Case Details")
    c = items[0]
    record = dict(c.record or {})
    if c.source_kind != "case_details" or str(record.get("case_id")) != str(prepared.case_id):
        raise src.NotCitable("a quick fact cites only its case's Case Details")
    return [quick_facts.citation(prepared.case_id)]


def _internal_set(prepared: _Prepared) -> dict[str, set]:
    """What transaction A gathered (decision 8, the fifth condition)."""
    rec = prepared.internal
    if rec is None:
        return {"note": set(), "file_movement": set(), "department_document": set()}
    return {
        "note": {str(n.note_id) for n in rec.notes},
        "file_movement": {str(rec.case_id)} if rec.file_movement is not None else set(),
        "department_document": {str(d.document_id) for d in rec.documents},
    }


def _map_ollama(
    session: Session, user: User, prepared: _Prepared, citations: tuple[Citation, ...] | list[Citation]
) -> list[dict[str, Any]]:
    """Design `assistant-ollama`, decision 8: every supplied source stored as a citation with `label`, `cited` and
    `source_kind`. Court kinds by document id, re-checked as the preview's; Case Details only of the focus case or a
    case of a supplied court source; an internal kind only when the mode is ollama, the conversation is scope `case`,
    it was switched on before this question's transaction A, the record belongs to the conversation's case and was in
    the set gathered there. Otherwise `NotCitable` (the whole answer is withheld). References only, never text."""
    gathered = _internal_set(prepared)
    court: list[dict[str, Any]] = []
    rest: list[tuple[int, dict[str, Any]]] = []
    for pos, c in enumerate(citations):
        kind = c.source_kind or "court_order"
        if kind not in SOURCE_KINDS:
            raise src.NotCitable("a citation of an unknown kind")
        base = {"source_kind": kind, "label": c.label, "cited": bool(c.cited)}
        if kind in COURT_KINDS:
            sub = _Prepared(**{**prepared.__dict__, "mode": "preview"})
            item = _map_citations(session, user, sub, [replace(c, label=None)])[0]
            verified = item["source_kind"]  # the rule's own answer, not the connector's word
            item.update(base)
            item["source_kind"] = verified
            if c.context:
                item["context"] = c.context[:MAX_CONTEXT]
            court.append(item)
            rest.append((pos, item))
            continue
        record = dict(c.record or {})
        if kind == "case_details":
            rest.append((pos, {**base, "case_id": record.get("case_id"), **_details_ref(record)}))
            continue
        if not (
            prepared.mode == "ollama"
            and prepared.scope == "case"
            and prepared.internal_on
            and prepared.case_id is not None
        ):
            raise src.NotCitable("internal records are outside this conversation's reach")
        if kind == "note":
            ref = str(record.get("note_id") or "")
            note = session.get(CaseNote, _uuid(ref)) if _uuid(ref) else None
            if note is None or note.case_id != prepared.case_id or ref not in gathered["note"]:
                raise src.NotCitable("a note outside the gathered set")
            chars = record.get("chars") or [0, 0]
            rest.append(
                (pos, {**base, "case_id": str(prepared.case_id), "note_id": ref, "chars": list(chars)[:2]})
            )
        elif kind == "file_movement":
            ref = str(record.get("case_id") or "")
            if ref != str(prepared.case_id) or ref not in gathered["file_movement"]:
                raise src.NotCitable("a file movement outside the gathered set")
            rest.append(
                (
                    pos,
                    {
                        **base,
                        "case_id": ref,
                        "legs": list(record.get("legs") or [])[:2],
                        "remarks": bool(record.get("remarks")),
                    },
                )
            )
        else:
            ref = str(record.get("document_id") or c.document_id or "")
            doc = session.get(Document, _uuid(ref)) if _uuid(ref) else None
            if doc is None or doc.case_id != prepared.case_id or ref not in gathered["department_document"]:
                raise src.NotCitable("a department document outside the gathered set")
            rest.append(
                (
                    pos,
                    {
                        **base,
                        "case_id": str(prepared.case_id),
                        "document_id": ref,
                        "page": c.page if isinstance(c.page, int) and c.page > 0 else None,
                        "what": record.get("what") if record.get("what") in ("note_attachment",) else None,
                    },
                )
            )
    court_cases = {str(i.get("case_id")) for i in court if i.get("case_id")}
    allowed_cases = court_cases | {str(f) for f in (prepared.focus_ids or [])}
    for _pos, item in rest:
        if item["source_kind"] == "case_details" and str(item.get("case_id")) not in allowed_cases:
            raise src.NotCitable("case details of a case outside the sources")
    return [item for _pos, item in sorted(rest, key=lambda t: t[0])]


def _details_ref(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "hearings": int(record.get("hearings") or 0),
        "listings": int(record.get("listings") or 0),
        "compact": bool(record.get("compact")),
    }


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
            if prepared.facts:
                info = {"engine": quick_facts.ENGINE, "facts": list(prepared.facts)}
            elif prepared.mode == "ollama":
                info = {"engine": "ollama", "model": getattr(connector, "model", None)}
        is_model = prepared.mode == "ollama" and not prepared.facts
        if (
            is_model
            and prepared.scope == "case"
            and not prepared.internal_on
            and outcome in ANSWERED_OUTCOMES
            and prepared.case_id is not None
        ):
            # decision 4: a deterministic keyword check, no model call; a suggestion only, never a switch
            case_row = s.get(Case, prepared.case_id)
            info["suggest_internal"] = bool(
                internal_records.suggests(prepared.question)
                and internal_records.visible_count(s, u, case_row) > 0
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
            response=raw if prepared.mode in ("sourcetrace", "ollama") and not prepared.facts else None,
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
                    {"document_id": c.get("document_id"), "order_id": c.get("order_id")}
                    for c in citations or []
                    if c.get("source_kind", "court_order") in COURT_KINDS
                ],
                **(_ollama_audit(info, citations) if is_model else {}),
                **({"facts": list(prepared.facts)} if prepared.facts else {}),
            },
        )
        answer_id = msg.id
        s.commit()
    return answer_id, outcome


def _ollama_audit(info: dict[str, Any], citations: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Decision 18: counts per source kind, never text."""
    supplied = {k: 0 for k in SOURCE_KINDS}
    cited = {k: 0 for k in SOURCE_KINDS}
    for c in citations or []:
        k = c.get("source_kind")
        if k in supplied:
            supplied[k] += 1
            if c.get("cited", True):
                cited[k] += 1
    return {
        "model": info.get("model"),
        "sources_supplied": supplied,
        "cited": cited,
        "invalid_markers": int(info.get("invalid_markers") or 0),
        "overlap_prev": info.get("overlap_prev"),  # design assistant-polish, decision 8: a number, never text
    }


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
    connector failure is stored as a `failed` answer and returned.

    Design `assistant-polish`, decision 14: a quick fact on the case tab (scope `case`, a recognised question, the
    asker holding the case page's read guard) skips the model's admission, runs transaction A unchanged, is answered
    from the case's court record in a read-only session, and is stored by transaction B with the connector `facts`."""
    if connector is None:
        raise AssistantOff("the Case Assistant is off")
    facts = _quick_facts(Session, user, question=question, scope=scope, case=case)
    if facts:
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
            facts=facts,
        )
        result = _facts_result(Session, prepared)
        answer_id, outcome = _record(Session, actor, user, prepared, FACTS_CONNECTOR, result, via)
        return AskResult(
            conversation_id=prepared.conversation_id,
            question_id=prepared.question_id,
            answer_id=answer_id,
            outcome=outcome,
        )
    slot = await _admit(connector)
    try:
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
        invoke = None
        if isinstance(connector, ollama.OllamaConnector):
            if prepared.scope == "case":

                def invoke():
                    return connector.ask_case(prepared.request, prepared.internal, details=prepared.details)

            else:

                def invoke():
                    return connector.ask(prepared.request, details=prepared.details)

        result = await _call(
            connector, prepared.request, config, conversation_id=prepared.conversation_id, invoke=invoke
        )
        answer_id, outcome = _record(Session, actor, user, prepared, connector, result, via)
    finally:
        if slot is not None:
            slot.release()
    return AskResult(
        conversation_id=prepared.conversation_id,
        question_id=prepared.question_id,
        answer_id=answer_id,
        outcome=outcome,
    )


class _FactsConnector:
    """The stand-in stored as an answer's connector when a quick fact was answered from the case record (no model)."""

    name = quick_facts.CONNECTOR
    model = None


FACTS_CONNECTOR = _FactsConnector()


def _quick_facts(
    Session: sessionmaker, user: User, *, question: str, scope: str, case: Case | uuid.UUID | None
) -> tuple[str, ...] | None:
    """Design `assistant-polish`, decisions 10 and 11: the facts asked, only on scope `case` and only for an asker
    holding the case page's read guard (checked in a short read); otherwise None (the ordinary path)."""
    if scope != "case" or case is None or not isinstance(question, str):
        return None
    facts = quick_facts.recognise(question)
    if not facts:
        return None
    with Session() as s:
        u = s.get(User, user.id)
        allowed = u is not None and internal_records.read_guard(s, u)
        s.rollback()
    return facts if allowed else None


def _facts_result(Session: sessionmaker, prepared: _Prepared) -> _Result:
    """The quick-fact answer built in a read-only session; an unexpected error is a stored `failed` answer, logged by
    its class only."""
    started = time.monotonic()
    try:
        with Session() as s:
            s.execute(text("SET TRANSACTION READ ONLY"))
            try:
                fa = quick_facts.answer(s, prepared.case_id, prepared.facts or (), today=clock.today_ist())
            finally:
                s.rollback()
    except Exception as exc:  # noqa: BLE001 — stored as a failed answer, never raised
        log.error(
            "a quick fact could not be answered: %s (conversation %s)",
            type(exc).__name__,
            prepared.conversation_id,
        )
        return _Result(
            False,
            family="error",
            message=FAILURE_MESSAGES["error"],
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    c = fa.citation
    answer = Answer(
        text=fa.text,
        citations=(
            Citation(
                reference=f"case_details:{c['case_id']}",
                source_kind="case_details",
                label=c["label"],
                cited=True,
                record={k: c[k] for k in ("case_id", "hearings", "listings", "compact")},
            ),
        ),
        outcome="answered",
        info=dict(fa.info),
    )
    return _Result(True, answer=answer, duration_ms=int((time.monotonic() - started) * 1000))


async def _admit(connector: AssistantConnector) -> ollama.Slot | None:
    """Design `assistant-ollama`, decision 13: readiness, then a slot, before transaction A. None of the three
    refusals is stored, counted or audited."""
    if not isinstance(connector, ollama.OllamaConnector):
        return None
    try:
        return await connector.admission()
    except ollama.ModelLoading as exc:
        raise AssistantLoading() from exc
    except ollama.ModelUnavailable as exc:
        raise AssistantUnavailable(
            "The Case Assistant model is not available; try again later.", reason=exc.reason
        ) from exc
    except ollama.ModelBusy as exc:
        raise AssistantBusy() from exc


# ------------------------------------------------------------------------------------------------ the switch


def include_internal(
    Session: sessionmaker,
    actor: Actor,
    user: User,
    *,
    case: Case | uuid.UUID,
    conversation_id: uuid.UUID | None = None,
    mode: str,
) -> dict[str, Any]:
    """Design `assistant-ollama`, decision 4: switch on "Include This Case's Internal Records" for the asker's own
    scope-`case` conversation of `case` (or a new empty one, titled "New Conversation"). Ollama mode only
    (`InternalUnavailable`); the case visible (`NotVisibleCase`) and the read guard held (`InternalNotPermitted`); at
    least one internal record the asker may open (`NoInternalRecords`); another user's conversation is
    `ConversationNotFound`, another case's or scope's `ScopeMismatch`. Under the conversation's row lock (the lock
    transaction A takes); set once from NULL and audited `assistant.internal_included` (ids only); a repeat is
    idempotent with no second audit row."""
    if mode != "ollama":
        raise InternalUnavailable("internal records can be included only when the local model answers")
    with Session() as s:
        u = s.get(User, user.id)
        case_row = s.get(Case, case.id if isinstance(case, Case) else case)
        if case_row is None or not visibility.can_view_case(s, u, case_row):
            raise NotVisibleCase("no such case")
        conv: AssistantConversation | None = None
        if conversation_id is not None:
            conv = s.scalar(
                select(AssistantConversation)
                .where(AssistantConversation.id == conversation_id, AssistantConversation.user_id == u.id)
                .with_for_update()
            )
            if conv is None:
                raise ConversationNotFound("no such conversation")
            if _value(conv.scope) != "case" or conv.case_id != case_row.id:
                raise ScopeMismatch("the conversation is not this case's case-tab conversation")
        if not internal_records.read_guard(s, u):
            raise InternalNotPermitted("you cannot open this case's notes and file movement")
        if conv is not None and conv.internal_included_at is not None:
            return {
                "conversation_id": conv.id,
                "case_id": case_row.id,
                "internal_included_at": conv.internal_included_at,
                "new_conversation": False,
            }
        if internal_records.visible_count(s, u, case_row) <= 0:
            raise NoInternalRecords("you can open no internal record of this case")
        new = conv is None
        now = s.scalar(select(func.now()))
        if conv is None:
            conv = AssistantConversation(
                user_id=u.id, case_id=case_row.id, scope=AssistantScope.CASE, title=NEW_TITLE
            )
            s.add(conv)
            s.flush()
        conv.internal_included_at = now
        s.flush()
        after: dict[str, Any] = {
            "conversation_id": conv.id,
            "case_id": case_row.id,
            "new_conversation": new,
        }
        if actor.user_id is None or actor.user_id != u.id:
            after["as_user_id"] = u.id
        write_audit(
            s,
            actor,
            "assistant.internal_included",
            "assistant_conversation",
            conv.id,
            case_id=case_row.id,
            after=after,
        )
        out = {
            "conversation_id": conv.id,
            "case_id": case_row.id,
            "internal_included_at": now,
            "new_conversation": new,
        }
        s.commit()
    return out


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
        "internal_included_at": conv.internal_included_at,
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
        "label": None,
        "cited": True,
        "context": None,
        "note": None,
        "internal": False,
        "what": None,
        "visibility": None,
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


def _internal_out(
    session: Session,
    user: User,
    conv: AssistantConversation | None,
    c: dict[str, Any],
    doc_labels: dict[str, str],
    note_labels: dict[str, str],
) -> dict[str, Any]:
    """Design `assistant-ollama`, decision 9: an internal citation re-checked under the reader's current rules and its
    text re-rendered from the record; one that fails names nothing."""
    kind = c.get("source_kind")
    if conv is None or not internal_records.recheck(session, user, conv, c):
        return {**_unavailable(kind), "label": c.get("label"), "cited": bool(c.get("cited", True))}
    case = session.get(Case, conv.case_id)
    context = internal_records.render(session, user, conv, c)
    note_out = None
    open_: dict[str, Any] | None = None
    record_visibility: str | None = None
    doc_id = _uuid(c.get("document_id"))
    doc_type_label = None
    doc_date = None
    if kind == "note":
        note = session.get(CaseNote, _uuid(c.get("note_id")))
        kind_code = _value(note.kind)
        note_out = {
            "id": note.id,
            "seq_no": note.seq_no,
            "kind_label": note_labels.get(kind_code, kind_code),
            "corrected_by_seq_no": internal_records.corrected_later(session, user, note.id),
        }
        doc_date = note.created_at.date() if note.created_at else None
        record_visibility = _value(note.visibility)
        open_ = {"kind": "case_tab", "href": f"/cases/{case.id}/notes#note-{note.seq_no}"}
    elif kind == "file_movement":
        open_ = {"kind": "case_tab", "href": f"/cases/{case.id}/custody"}
        # a remark is read only with a working basis: the narrowest setting; the legs alone are the case's
        record_visibility = "private_to_office" if c.get("remarks") else "case_scope"
    else:
        doc = session.get(Document, doc_id)
        dt = _value(doc.doc_type)
        doc_type_label = doc_labels.get(dt, dt) if dt else None
        doc_date = doc.doc_date
        record_visibility = _value(doc.visibility)
        open_ = {
            "kind": "document",
            "href": f"/documents/{doc_id}/file?disposition="
            + ("inline" if doc.mime in INLINE_MIMES else "attachment"),
        }
    return {
        "document_id": doc_id,
        "order_id": None,
        "case": {"id": case.id, "case_no_text": case.case_no_text, "cnr": case.cnr, "visible": True},
        "source_kind": kind,
        "doc_type_label": doc_type_label,
        "doc_date": doc_date,
        "order_no": None,
        "page": c.get("page"),
        "passage": None,
        "related": False,
        "available": True,
        "unavailable_reason": None,
        "open": open_,
        "label": c.get("label"),
        "cited": bool(c.get("cited", True)),
        "context": context,
        "note": note_out,
        "internal": True,
        "what": c.get("what"),
        "visibility": record_visibility,
    }


def _details_out(session: Session, user: User, c: dict[str, Any], visible: set[uuid.UUID]) -> dict[str, Any]:
    """A Case Details citation: the court-public facts re-read from the court tables at read time."""
    case_id = _uuid(c.get("case_id"))
    case = session.get(Case, case_id) if case_id else None
    if case is None or case.merged_into_case_id is not None:
        return {**_unavailable("case_details"), "label": c.get("label"), "cited": bool(c.get("cited", True))}
    compact = bool(c.get("compact"))
    n = int(c.get("hearings") or 0)
    rows = src.case_details(session, [case.id], hearings=n, listings=int(c.get("listings") or 0))
    context = ollama.details_text(rows[0], compact=compact) if rows else None
    case_visible = case.id in visible
    return {
        "document_id": None,
        "order_id": None,
        "case": {
            "id": case.id if case_visible else None,
            "case_no_text": case.case_no_text,
            "cnr": case.cnr,
            "visible": case_visible,
        },
        "source_kind": "case_details",
        "doc_type_label": None,
        "doc_date": None,
        "order_no": None,
        "page": None,
        "passage": None,
        "related": False,
        "available": True,
        "unavailable_reason": None,
        "open": {"kind": "case_tab", "href": f"/cases/{case.id}/details"} if case_visible else None,
        "label": c.get("label"),
        "cited": bool(c.get("cited", True)),
        "context": context,
        "note": None,
        "internal": False,
        "what": None,
        "visibility": None,
    }


def messages_out(session: Session, user: User, msgs: list[AssistantMessage]) -> list[dict[str, Any]]:
    """`MessageOut` for each message: filing citations re-checked against the reader's current document visibility
    (decision 8). A failing one shows only that it is unavailable and hides the answer's text. Court-order citations
    are court-public and stay shown while the order is still in the court-order corpus (the document a current court
    record, not archived, the order's case not merged); otherwise they show unavailable too. Design
    `assistant-ollama`, decision 9: internal citations re-checked under the reader's current rules (a failing one,
    cited or not, hides the answer), their text re-rendered from the record; Case Details re-read from the court
    tables."""
    convs = (
        {
            c.id: c
            for c in session.scalars(
                select(AssistantConversation).where(
                    AssistantConversation.id.in_({m.conversation_id for m in msgs})
                )
            ).all()
        }
        if msgs
        else {}
    )
    note_labels = {r.code: r.label for r in session.scalars(select(RefNoteKind)).all()}
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
        kind = c.get("source_kind") or "court_order"
        if kind in INTERNAL_KINDS:
            return _internal_out(session, user, convs.get(m.conversation_id), c, labels, note_labels)
        if kind == "case_details":
            return _details_out(session, user, c, visible)
        extra = {
            "label": c.get("label"),
            "cited": bool(c.get("cited", True)),
            "context": c.get("context"),
            "note": None,
            "internal": False,
            "what": None,
            "visibility": None,
        }
        doc_id = _uuid(c.get("document_id"))
        order_id = _uuid(c.get("order_id"))
        case_id = _uuid(c.get("case_id"))
        doc = docs.get(doc_id) if doc_id else None
        order = orders.get(order_id) if order_id else None
        if kind == "court_filing":
            if doc is None or doc_id not in filings:
                return {**_unavailable(kind), "label": extra["label"], "cited": extra["cited"]}
            open_ = {
                "kind": "document",
                "href": f"/documents/{doc_id}/file?disposition="
                + ("inline" if doc.mime in INLINE_MIMES else "attachment"),
            }
        else:
            if doc is None or order is None or order.document_id != doc_id or doc_id not in in_corpus:
                return {**_unavailable(kind), "label": extra["label"], "cited": extra["cited"]}
            case_id = order.case_id
            order_case = cases.get(case_id)
            if order_case is None or order_case.merged_into_case_id is not None:
                return {**_unavailable(kind), "label": extra["label"], "cited": extra["cited"]}
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
            **extra,
        }

    out = []
    for m in msgs:
        items = [citation_out(m, c) for c in (m.citations or [])]
        hidden_internal = any(not i["available"] for i in items if i["source_kind"] in INTERNAL_KINDS)
        hidden = hidden_internal or any(
            not i["available"] for i in items if i["source_kind"] == "court_filing"
        )
        role = _value(m.role)
        info = m.model_info or {}
        is_facts = m.connector == quick_facts.CONNECTOR
        is_ollama = m.mode == "ollama" and not is_facts
        out.append(
            {
                "id": m.id,
                "role": role,
                "created_at": m.created_at,
                "content": None if hidden else m.content,
                "hidden_reason": (HIDDEN_INTERNAL if hidden_internal else HIDDEN_REASON) if hidden else None,
                "engine": (
                    {"kind": quick_facts.ENGINE, "model": None}
                    if is_facts
                    else ({"kind": "ollama", "model": info.get("model")} if is_ollama else None)
                ),
                "checks": (
                    {
                        "invalid_markers": int(info.get("invalid_markers") or 0),
                        "cut_short": bool(info.get("cut_short")),
                    }
                    if is_ollama
                    else None
                ),
                "internal_used": any(
                    i["source_kind"] in INTERNAL_KINDS and i.get("cited", True) for i in items
                ),
                "suggest_internal": bool(info.get("suggest_internal")),
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
    """`aslms assistant check`: (1) court-kind citations naming a document that is not a court order or a court
    filing (a note attachment, an internal, admin or cause-list document, a private one, or none at all); (2)
    conversations with a case scope but no case; and (design `assistant-ollama`, "Data") (3) internal-kind citations on
    an answer whose mode is not `ollama`, whose conversation's scope is not `case`, or whose question was created before
    the conversation's `internal_included_at` (or with it null); (4) internal-kind citations naming a record of
    another case than the conversation's; (5) citations naming a record kind outside the six of round 1. All must be
    0."""
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
                WHERE coalesce(c.value ->> 'source_kind', 'court_order') IN ('court_order', 'court_filing')
                AND NOT coalesce(
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
    internal_out_of_reach = int(
        session.scalar(
            text(
                """
                SELECT count(*)
                FROM assistant_messages m
                JOIN assistant_conversations cv ON cv.id = m.conversation_id
                JOIN assistant_messages q ON q.id = m.reply_to_id
                CROSS JOIN LATERAL jsonb_array_elements(
                    CASE WHEN jsonb_typeof(m.citations) = 'array' THEN m.citations ELSE '[]'::jsonb END
                ) AS c(value)
                WHERE c.value ->> 'source_kind' IN ('note', 'file_movement', 'department_document')
                AND (
                    m.mode IS DISTINCT FROM 'ollama'
                    OR cv.scope::text <> 'case'
                    OR cv.internal_included_at IS NULL
                    OR q.created_at < cv.internal_included_at
                )
                """
            )
        )
        or 0
    )
    internal_other_case = int(
        session.scalar(
            text(
                """
                SELECT count(*)
                FROM assistant_messages m
                JOIN assistant_conversations cv ON cv.id = m.conversation_id
                CROSS JOIN LATERAL jsonb_array_elements(
                    CASE WHEN jsonb_typeof(m.citations) = 'array' THEN m.citations ELSE '[]'::jsonb END
                ) AS c(value)
                LEFT JOIN case_notes n ON c.value ->> 'source_kind' = 'note' AND n.id::text = c.value ->> 'note_id'
                LEFT JOIN documents d
                    ON c.value ->> 'source_kind' = 'department_document' AND d.id::text = c.value ->> 'document_id'
                WHERE c.value ->> 'source_kind' IN ('note', 'file_movement', 'department_document')
                AND NOT coalesce(
                    CASE c.value ->> 'source_kind'
                        WHEN 'note' THEN n.case_id = cv.case_id
                        WHEN 'department_document' THEN d.case_id = cv.case_id
                        ELSE (c.value ->> 'case_id') = cv.case_id::text
                    END,
                    false
                )
                """
            )
        )
        or 0
    )
    unknown_kind = int(
        session.scalar(
            text(
                """
                SELECT count(*)
                FROM assistant_messages m
                CROSS JOIN LATERAL jsonb_array_elements(
                    CASE WHEN jsonb_typeof(m.citations) = 'array' THEN m.citations ELSE '[]'::jsonb END
                ) AS c(value)
                WHERE coalesce(c.value ->> 'source_kind', 'court_order') NOT IN (
                    'court_order', 'court_filing', 'case_details', 'note', 'file_movement', 'department_document'
                )
                """
            )
        )
        or 0
    )
    return {
        "citations_out_of_rule": bad_citations,
        "case_conversations_without_case": orphan,
        "internal_citations_out_of_reach": internal_out_of_reach,
        "internal_citations_of_another_case": internal_other_case,
        "citations_of_unknown_kind": unknown_kind,
    }
