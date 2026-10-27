"""Phase 3 — the Case Assistant's conversation storage (design `assistant`; answers come through the connector
contract: the preview's full-text search in dev and test, a local Ollama model (design `assistant-ollama`), SourceTrace
once row 36 builds its connector).

A conversation belongs to one user and is never deleted; its messages are append-only (trigger
`aslms_forbid_change`, migration 0024). Written only by `services/assistant.py`. Never holds secrets or note drafts;
internal records of one case are cited by reference only, on ollama answers of a case-tab conversation switched on
(`internal_included_at`, design `assistant-ollama`, decisions 3, 4 and 9)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import Base, CreatedAtMixin, TableClass, TimestampMixin, pg_enum, uuid_fk, uuid_pk


class AssistantScope(enum.StrEnum):
    CASE = "case"
    RESEARCH = "research"
    MY_CASES = "my_cases"  # migration 0024


class AssistantConversation(TimestampMixin, Base):
    __tablename__ = "assistant_conversations"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (
        CheckConstraint("(scope = 'case') = (case_id IS NOT NULL)", name="case_scope"),
        # design assistant-ollama, decision 4 (migration 0032): the switch only on a case-tab conversation; the trigger
        # `assistant_conversations_internal_once` keeps it set once, never cleared or moved
        CheckConstraint("internal_included_at IS NULL OR scope = 'case'", name="internal_case"),
        Index(
            "ix_assistant_conversations_user_last",
            "user_id",
            text("last_message_at DESC NULLS LAST"),
        ),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id", index=False)
    case_id: Mapped[uuid.UUID | None] = uuid_fk("cases.id", nullable=True)
    scope: Mapped[AssistantScope] = mapped_column(
        pg_enum(AssistantScope, "assistant_scope"), nullable=False, server_default="case"
    )
    title: Mapped[str | None] = mapped_column(String(300))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    internal_included_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"  # never written


class AssistantMessage(CreatedAtMixin, Base):
    __tablename__ = "assistant_messages"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (
        CheckConstraint(
            "(role = 'user' AND reply_to_id IS NULL AND mode IS NULL AND outcome IS NULL) OR "
            "(role = 'assistant' AND reply_to_id IS NOT NULL AND mode IN ('preview', 'sourcetrace', 'ollama') "
            "AND outcome IN ('answered', 'no_match', 'failed'))",
            name="role_shape",
        ),
        CheckConstraint("(outcome = 'failed') = (error_family IS NOT NULL)", name="failure"),
        CheckConstraint("role <> 'user' OR char_length(content) BETWEEN 3 AND 2000", name="length"),
        Index(
            "ix_assistant_messages_reply_to",
            "reply_to_id",
            unique=True,
            postgresql_where=text("reply_to_id IS NOT NULL"),
        ),
        Index("ix_assistant_messages_conversation_created", "conversation_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = uuid_fk(
        "assistant_conversations.id", ondelete="CASCADE", index=False
    )
    role: Mapped[MessageRole] = mapped_column(pg_enum(MessageRole, "message_role"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    reply_to_id: Mapped[uuid.UUID | None] = uuid_fk("assistant_messages.id", nullable=True, index=False)
    mode: Mapped[str | None] = mapped_column(String(20))
    connector: Mapped[str | None] = mapped_column(String(40))
    outcome: Mapped[str | None] = mapped_column(String(20))
    error_family: Mapped[str | None] = mapped_column(String(40))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    scope_info: Mapped[dict | None] = mapped_column(JSONB)
    citations: Mapped[list | None] = mapped_column(JSONB)
    model_info: Mapped[dict | None] = mapped_column(JSONB)
    response: Mapped[dict | None] = mapped_column(JSONB)
