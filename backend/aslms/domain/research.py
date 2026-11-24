"""The research index (design `research-index`, Data; docs/schema/schema.md Group 6; DB_STANDARD §13): chunks of court
orders cut by their structure and one case sheet per case, and the vectors the local embedding model made of them.

Both tables are derived and re-buildable, written only by `services/research_index.py` (chunks) and
`services/research_embed.py` (vectors), from current `order_sections` readings and court-public case fields; never from
notes, file remarks, internal documents or drafts. A row never changes except to be retired once (`retired_at`,
`retire_reason`; trigger `*_retire_once`); never deleted (no DELETE grant)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import Base, HalfVec, TableClass, TimestampMixin, pg_enum, uuid_fk, uuid_pk
from aslms.domain.documents import OrderKind


class ResearchChunkKind(enum.StrEnum):
    ORDER_BODY = "order_body"
    CASE_SHEET = "case_sheet"


class ResearchRetireReason(enum.StrEnum):
    """Why a chunk or a vector stopped being current (design `research-index`, decisions 7, 11, 12 and 13)."""

    READING_GONE = "reading_gone"  # no current reading holds the chunk set's key any more
    SHEET_CHANGED = "sheet_changed"  # a case sheet's text changed: a new sheet replaced it
    CHUNKER_VERSION = "chunker_version"  # cut again under a new chunker version
    CASE_MERGED = "case_merged"  # the sheet's case was merged into another
    MODEL_CHANGED = "model_changed"  # a vector of a key that is no longer live, retired by the rebuild
    CHUNK_RETIRED = "chunk_retired"  # a vector no current chunk uses any more
    REBUILT = "rebuilt"  # retired by `aslms research-index rebuild --chunks`


class ResearchChunk(TimestampMixin, Base):
    """One chunk of a court order's cleaned body (`order_body`: a run of whole paragraphs inside one part, or an interim
    order's whole body), or one case sheet (`case_sheet`). A chunk set belongs to the key (body_sha256, form,
    parser_version, chunker_version) and is shared by every current reading with that key; pages and `src` offsets are
    read from each reading's own paragraphs when a chunk is cited (decision 13)."""

    __tablename__ = "research_chunks"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (
        CheckConstraint(
            "(kind = 'order_body' AND body_sha256 IS NOT NULL AND form IS NOT NULL AND parser_version IS NOT NULL "
            "AND first_reading_id IS NOT NULL AND part IS NOT NULL AND para_first IS NOT NULL AND para_last IS NOT "
            "NULL AND txt_start IS NOT NULL AND txt_end IS NOT NULL AND case_id IS NULL AND sheet_sha256 IS NULL) "
            "OR (kind = 'case_sheet' AND case_id IS NOT NULL AND sheet_sha256 IS NOT NULL AND body_sha256 IS NULL "
            "AND form IS NULL AND parser_version IS NULL AND first_reading_id IS NULL AND part IS NULL AND "
            "para_first IS NULL AND para_last IS NULL AND txt_start IS NULL AND txt_end IS NULL)",
            name="shape",
        ),
        CheckConstraint("(retired_at IS NULL) = (retire_reason IS NULL)", name="retired"),
        CheckConstraint("txt_start IS NULL OR (0 <= txt_start AND txt_start < txt_end)", name="span"),
        Index(
            "ix_research_chunks_set_current",
            "body_sha256",
            "form",
            "parser_version",
            "chunker_version",
            "seq",
            unique=True,
            postgresql_where=text("kind = 'order_body' AND retired_at IS NULL"),
        ),
        Index(
            "ix_research_chunks_sheet_current",
            "case_id",
            unique=True,
            postgresql_where=text("kind = 'case_sheet' AND retired_at IS NULL"),
        ),
        Index(
            "ix_research_chunks_key",
            "body_sha256",
            "form",
            "parser_version",
            postgresql_where=text("retired_at IS NULL"),
        ),
        Index("ix_research_chunks_embed_sha256", "embed_sha256", postgresql_where=text("retired_at IS NULL")),
        Index(
            "ix_research_chunks_search_vector_gin",
            "search_vector",
            postgresql_using="gin",
            postgresql_where=text("retired_at IS NULL"),
        ),
        Index("ix_research_chunks_case_id", "case_id", postgresql_where=text("case_id IS NOT NULL")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[ResearchChunkKind] = mapped_column(
        pg_enum(ResearchChunkKind, "research_chunk_kind"), nullable=False
    )
    body_sha256: Mapped[str | None] = mapped_column(String(64))
    form: Mapped[OrderKind | None] = mapped_column(pg_enum(OrderKind, "order_kind"))
    parser_version: Mapped[int | None] = mapped_column(SmallInteger)
    chunker_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    seq: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    first_reading_id: Mapped[uuid.UUID | None] = uuid_fk("order_sections.id", nullable=True)
    case_id: Mapped[uuid.UUID | None] = uuid_fk("cases.id", nullable=True, index=False)
    part: Mapped[str | None] = mapped_column(String(30))
    para_first: Mapped[int | None] = mapped_column(SmallInteger)
    para_last: Mapped[int | None] = mapped_column(SmallInteger)
    txt_start: Mapped[int | None] = mapped_column(Integer)
    txt_end: Mapped[int | None] = mapped_column(Integer)
    split: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    context_line: Mapped[str] = mapped_column(String(200), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sheet_sha256: Mapped[str | None] = mapped_column(String(64))
    embed_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    chars: Mapped[int] = mapped_column(Integer, nullable=False)
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english'::regconfig, text)", persisted=True)
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retire_reason: Mapped[ResearchRetireReason | None] = mapped_column(
        pg_enum(ResearchRetireReason, "research_retire_reason")
    )


class ResearchEmbedding(TimestampMixin, Base):
    """One vector of one exact embedding input under one model key. Joined to its chunks by `input_sha256` =
    `research_chunks.embed_sha256` with no foreign key (DB_STANDARD §13); `first_chunk_id` keeps the chain. A changed
    model is a new key, never an overwrite; retired, never deleted."""

    __tablename__ = "research_embeddings"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (
        CheckConstraint("dims BETWEEN 64 AND 4000 AND vector_dims(embedding) = dims", name="dims"),
        CheckConstraint("(retired_at IS NULL) = (retire_reason IS NULL)", name="retired"),
        Index(
            "ix_research_embeddings_current",
            "input_sha256",
            "model_key",
            unique=True,
            postgresql_where=text("retired_at IS NULL"),
        ),
        Index("ix_research_embeddings_model_key", "model_key", postgresql_where=text("retired_at IS NULL")),
        Index(
            "ix_research_embeddings_hnsw_768",
            text("(embedding::halfvec(768)) halfvec_cosine_ops"),
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_where=text("dims = 768 AND retired_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    first_chunk_id: Mapped[uuid.UUID] = uuid_fk("research_chunks.id")
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    model_digest: Mapped[str] = mapped_column(String(80), nullable=False)
    model_key: Mapped[str] = mapped_column(String(180), nullable=False)
    profile: Mapped[str] = mapped_column(String(40), nullable=False)
    dims: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(HalfVec(), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retire_reason: Mapped[ResearchRetireReason | None] = mapped_column(
        pg_enum(ResearchRetireReason, "research_retire_reason")
    )
