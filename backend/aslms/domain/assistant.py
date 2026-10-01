"""Phase 3 — the Case Assistant's conversation storage (answers come through SourceTrace)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import Base, CreatedAtMixin, TableClass, TimestampMixin, pg_enum, uuid_fk, uuid_pk


class AssistantScope(enum.StrEnum):
    CASE = "case"
    RESEARCH = "research"


class AssistantConversation(TimestampMixin, Base):
    __tablename__ = "assistant_conversations"
    __table_class__ = TableClass.TRANSACTION
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    case_id: Mapped[uuid.UUID | None] = uuid_fk("cases.id", nullable=True)
    scope: Mapped[AssistantScope] = mapped_column(
        pg_enum(AssistantScope, "assistant_scope"), nullable=False, server_default="case"
    )
    title: Mapped[str | None] = mapped_column(String(300))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class AssistantMessage(CreatedAtMixin, Base):
    __tablename__ = "assistant_messages"
    __table_class__ = TableClass.TRANSACTION
    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = uuid_fk("assistant_conversations.id", ondelete="CASCADE")
    role: Mapped[MessageRole] = mapped_column(pg_enum(MessageRole, "message_role"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list | None] = mapped_column(JSONB)
    model_info: Mapped[dict | None] = mapped_column(JSONB)
