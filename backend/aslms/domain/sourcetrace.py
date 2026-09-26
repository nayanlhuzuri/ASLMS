"""Phase 2/3 — SourceTrace links (plan §3.2, §5.9, Table 8): ingestion attempts per document, and each user's
Case Assistant conversations. The research index itself lives in SourceTrace."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import Base, CreatedAtMixin, TimestampMixin, pg_enum, uuid_fk, uuid_pk


class SourceTraceIngestion(CreatedAtMixin, Base):
    """One row per attempt to send a document (court order or court filing — never notes or internal
    documents) to the SourceTrace ingestion API."""

    __tablename__ = "sourcetrace_ingestions"
    __table_args__ = (Index("ix_sourcetrace_ingestions_document", "document_id", text("created_at DESC")),)

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = uuid_fk("documents.id", index=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    ok: Mapped[bool] = mapped_column(nullable=False)
    reference: Mapped[str | None] = mapped_column(String(200))
    error: Mapped[str | None] = mapped_column(Text)
    metadata_sent: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class ConversationScope(enum.StrEnum):
    CASE = "case"
    RESEARCH = "research"


class AssistantConversation(TimestampMixin, Base):
    """Visible only to its user (plan §5.9)."""

    __tablename__ = "assistant_conversations"
    __table_args__ = (Index("ix_assistant_conversations_user_case", "user_id", "case_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id", index=False)
    case_id: Mapped[uuid.UUID | None] = uuid_fk("cases.id", nullable=True, index=False)
    scope: Mapped[ConversationScope] = mapped_column(
        pg_enum(ConversationScope, "conversation_scope"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(300))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssistantMessage(CreatedAtMixin, Base):
    __tablename__ = "assistant_messages"
    __table_args__ = (Index("ix_assistant_messages_conversation", "conversation_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = uuid_fk("assistant_conversations.id", index=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default="[]")
    model_info: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
