"""Case Assistant and legal research through SourceTrace (plan §5.9, Phase 3). Conversations are private to
their user. Until SourceTrace is connected, answers say so and questions are kept."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select

from aslms.api import schemas as S
from aslms.api.deps import Ctx, current_ctx
from aslms.core.config import get_settings
from aslms.core.errors import NotFoundError
from aslms.domain.sourcetrace import AssistantConversation, AssistantMessage
from aslms.domain.workflow import NoteVisibility
from aslms.integration.sourcetrace import get_knowledge_service
from aslms.services import assistant
from aslms.services import cases as case_svc
from aslms.services.scope import require_case_scope

router = APIRouter(tags=["case assistant"])


def _case(ctx: Ctx, case_ref: str):
    case = case_svc.resolve_case_ref(ctx.db, case_ref)
    if case is None:
        raise NotFoundError("case not found")
    return case


def _conv_out(ctx: Ctx, c: AssistantConversation, with_messages: bool = True) -> S.ConversationOut:
    msgs = []
    if with_messages:
        msgs = [
            S.AssistantMessageOut(
                id=m.id, role=m.role, content=m.content, citations=m.citations, created_at=m.created_at
            )
            for m in ctx.db.scalars(
                select(AssistantMessage)
                .where(AssistantMessage.conversation_id == c.id)
                .order_by(AssistantMessage.created_at)
            )
        ]
    return S.ConversationOut(
        id=c.id,
        case_id=c.case_id,
        scope=c.scope.value,
        title=c.title,
        last_message_at=c.last_message_at,
        messages=msgs,
    )


@router.get("/assistant/status")
def status() -> dict[str, object]:
    return {
        "connected": get_settings().sourcetrace_enabled,
        "service": "SourceTrace",
        "detail": "connected" if get_settings().sourcetrace_enabled else "not connected (Phase 3)",
    }


@router.get("/cases/{case_ref}/assistant", response_model=list[S.ConversationOut])
def case_conversations(case_ref: str, ctx: Ctx = Depends(current_ctx)) -> list[S.ConversationOut]:
    case_id = _case(ctx, case_ref).id
    require_case_scope(ctx.db, ctx.principal, case_id)
    rows = ctx.db.scalars(
        select(AssistantConversation)
        .where(AssistantConversation.user_id == ctx.user.id, AssistantConversation.case_id == case_id)
        .order_by(AssistantConversation.updated_at.desc())
    )
    return [_conv_out(ctx, c) for c in rows]


@router.post("/cases/{case_ref}/assistant", response_model=S.ConversationOut)
def ask_case(case_ref: str, body: S.AskIn, ctx: Ctx = Depends(current_ctx)) -> S.ConversationOut:
    case_id = _case(ctx, case_ref).id
    conv, _, _ = assistant.ask(
        ctx.db,
        ctx.principal,
        get_knowledge_service(),
        question=body.question,
        case_id=case_id,
        conversation_id=body.conversation_id,
    )
    return _conv_out(ctx, conv)


@router.get("/research", response_model=list[S.ConversationOut])
def research_conversations(ctx: Ctx = Depends(current_ctx)) -> list[S.ConversationOut]:
    rows = ctx.db.scalars(
        select(AssistantConversation)
        .where(AssistantConversation.user_id == ctx.user.id, AssistantConversation.case_id.is_(None))
        .order_by(AssistantConversation.updated_at.desc())
        .limit(50)
    )
    return [_conv_out(ctx, c, with_messages=False) for c in rows]


@router.post("/research", response_model=S.ConversationOut)
def ask_research(body: S.AskIn, ctx: Ctx = Depends(current_ctx)) -> S.ConversationOut:
    conv, _, _ = assistant.ask(
        ctx.db,
        ctx.principal,
        get_knowledge_service(),
        question=body.question,
        conversation_id=body.conversation_id,
    )
    return _conv_out(ctx, conv)


@router.get("/assistant/conversations/{conversation_id}", response_model=S.ConversationOut)
def get_conversation(conversation_id: uuid.UUID, ctx: Ctx = Depends(current_ctx)) -> S.ConversationOut:
    return _conv_out(ctx, assistant.conversation(ctx.db, ctx.user.id, conversation_id))


@router.post("/assistant/messages/{message_id}/to-note", response_model=S.Ok, status_code=201)
def copy_to_note(message_id: uuid.UUID, body: S.CopyToNoteIn, ctx: Ctx = Depends(current_ctx)) -> S.Ok:
    n = assistant.copy_to_note(ctx.db, ctx.actor, ctx.principal, message_id, NoteVisibility(body.visibility))
    return S.Ok(detail=f"note {n.seq_no} added")
