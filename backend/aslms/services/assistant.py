"""Case Assistant and general research (plan §5.9, Phase 3), against the `KnowledgeService` interface.

The portal passes the case's context (CNR, details, and references to its orders and court filings that were
ingested) — never notes or internal documents. Conversations are stored per user, visible only to that user.
An answer can be copied, with its references, into a new case note (kind `opinion`, source `assistant`).
Until SourceTrace is connected the stub answers that the assistant is not available; questions are still
stored so nothing is lost."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.core.errors import ForbiddenError, IntegrationError, NotFoundError, ValidationError
from aslms.core.time import now_utc
from aslms.domain.cases import Case
from aslms.domain.documents import Document, Order, SourceTraceStatus
from aslms.domain.sourcetrace import AssistantConversation, AssistantMessage, ConversationScope
from aslms.domain.workflow import NoteKind, NoteVisibility
from aslms.services import notes
from aslms.services.audit import Actor
from aslms.services.scope import Principal, require_case_scope

NOT_CONNECTED = (
    "The Case Assistant is not connected yet. It is powered by SourceTrace, the in-house research service, "
    "which arrives in Phase 3. Your question has been saved."
)


def case_context(session: Session, case: Case) -> dict[str, Any]:
    ingested = session.scalars(
        select(Document).where(
            Document.case_id == case.id, Document.sourcetrace_status == SourceTraceStatus.INGESTED
        )
    ).all()
    orders = session.scalars(
        select(Order).where(Order.case_id == case.id).order_by(Order.order_date.desc())
    ).all()
    return {
        "cnr": case.cnr,
        "case_number": case.case_no_text,
        "status": case.status.value,
        "petitioner": case.petitioner_summary,
        "respondent": case.respondent_summary,
        "next_hearing_date": case.next_hearing_date.isoformat() if case.next_hearing_date else None,
        "orders": [
            {"order_no": o.order_no, "date": o.order_date.isoformat(), "kind": o.kind.value}
            for o in orders[:50]
        ],
        "documents": [
            {
                "reference": d.sourcetrace_ref,
                "type": d.doc_type.value,
                "date": d.doc_date.isoformat() if d.doc_date else None,
            }
            for d in ingested
        ],
    }


def conversation(session: Session, user_id: uuid.UUID, conversation_id: uuid.UUID) -> AssistantConversation:
    conv = session.get(AssistantConversation, conversation_id)
    if conv is None or conv.user_id != user_id:
        raise NotFoundError("conversation not found")
    return conv


def ask(
    session: Session,
    p: Principal,
    ks,
    *,
    question: str,
    case_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
) -> tuple[AssistantConversation, AssistantMessage, AssistantMessage]:
    q = (question or "").strip()
    if not q:
        raise ValidationError("ask a question")
    if len(q) > 4000:
        raise ValidationError("the question is too long")
    case = None
    if case_id:
        case = session.get(Case, case_id)
        if case is None:
            raise NotFoundError("case not found")
        require_case_scope(session, p, case.id)
    conv = conversation(session, p.user_id, conversation_id) if conversation_id else None
    if conv is None:
        conv = AssistantConversation(
            user_id=p.user_id,
            case_id=case.id if case else None,
            scope=ConversationScope.CASE if case else ConversationScope.RESEARCH,
            title=q[:120],
        )
        session.add(conv)
        session.flush()
    elif conv.case_id != (case.id if case else None):
        raise ValidationError("this conversation belongs to another case")
    user_msg = AssistantMessage(conversation_id=conv.id, role="user", content=q)
    session.add(user_msg)
    context = case_context(session, case) if case else {}
    try:
        ans = asyncio.run(ks.ask(question=q, context=context))
    except IntegrationError as e:
        ans = {"answer": None, "citations": [], "reason": str(e)}
    text = ans.get("answer") or NOT_CONNECTED
    bot = AssistantMessage(
        conversation_id=conv.id,
        role="assistant",
        content=text,
        citations=ans.get("citations") or [],
        model_info={k: v for k, v in ans.items() if k in ("model", "version", "reason")},
    )
    session.add(bot)
    conv.last_message_at = now_utc()
    session.flush()
    return conv, user_msg, bot


def copy_to_note(
    session: Session,
    actor: Actor,
    p: Principal,
    message_id: uuid.UUID,
    visibility: NoteVisibility = NoteVisibility.CASE_SCOPE,
):
    msg = session.get(AssistantMessage, message_id)
    if msg is None or msg.role != "assistant":
        raise NotFoundError("answer not found")
    conv = conversation(session, p.user_id, msg.conversation_id)
    if conv.case_id is None:
        raise ValidationError("only answers about a case can be copied into its notes")
    if msg.content == NOT_CONNECTED:
        raise ForbiddenError("there is no answer to copy")
    refs = (
        "\n".join(f"- {c.get('title') or c.get('reference')}" for c in msg.citations) if msg.citations else ""
    )
    body = msg.content + (f"\n\nReferences:\n{refs}" if refs else "")
    case = session.get(Case, conv.case_id)
    return notes.add_note(
        session,
        actor,
        p,
        case,
        notes.NoteIn(kind=NoteKind.OPINION, body=body, visibility=visibility, source="assistant"),
    )
