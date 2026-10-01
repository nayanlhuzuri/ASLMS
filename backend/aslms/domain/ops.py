"""Group 9 — integration and operations: job runs, the NAPIX call log, verbatim responses, failures and the
resumable fetch queue of the load-and-refresh pipeline."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, SmallInteger, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import Base, CreatedAtMixin, TableClass, TimestampMixin, pg_enum, uuid_fk, uuid_pk


class JobStatus(enum.StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class JobRun(CreatedAtMixin, Base):
    __tablename__ = "job_runs"
    __table_class__ = TableClass.DERIVED
    id: Mapped[uuid.UUID] = uuid_pk()
    job: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    run_date: Mapped[date | None] = mapped_column(Date, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"), nullable=False, server_default="running"
    )
    counters: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)


class NapixCallLog(Base):
    """One row per HTTP attempt (CLAUDE.md: every call is logged). Pruned after the retention period."""

    __tablename__ = "napix_call_log"
    __table_class__ = TableClass.DERIVED
    id: Mapped[uuid.UUID] = uuid_pk()
    api: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    params_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    napix_status: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_family: Mapped[str | None] = mapped_column(String(40))
    error: Mapped[str | None] = mapped_column(Text)
    token_verified: Mapped[bool | None] = mapped_column(Boolean)
    rate_limit_remaining: Mapped[int | None] = mapped_column(Integer)
    called_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), index=True
    )
    job_run_id: Mapped[uuid.UUID | None] = uuid_fk("job_runs.id", nullable=True, ondelete="CASCADE")


class NapixResponse(CreatedAtMixin, Base):
    """Every decrypted JSON response, verbatim (the first coverage layer). PDFs go to `documents`."""

    __tablename__ = "napix_responses"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (UniqueConstraint("api", "params_sha256", "payload_sha256"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    api: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    params_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict | list] = mapped_column(JSONB, nullable=False)
    token_verified: Mapped[bool | None] = mapped_column(Boolean)
    job_run_id: Mapped[uuid.UUID | None] = uuid_fk("job_runs.id", nullable=True)


class SourceFailure(TimestampMixin, Base):
    __tablename__ = "source_failures"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (UniqueConstraint("kind", "ref"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    ref: Mapped[str] = mapped_column(String(300), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    error_family: Mapped[str | None] = mapped_column(String(40))
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FetchKind(enum.StrEnum):
    MASTERS = "masters"
    CAUSELIST_DAY = "causelist_day"
    DOSSIER = "dossier"
    STATUS_BATCH = "status_batch"
    ORDER_PDF = "order_pdf"


class FetchStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class FetchQueueItem(TimestampMixin, Base):
    """The resumable work list of the load-and-refresh pipeline; every worker pulls from here."""

    __tablename__ = "fetch_queue"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (UniqueConstraint("kind", "ref"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[FetchKind] = mapped_column(pg_enum(FetchKind, "fetch_kind"), nullable=False)
    ref: Mapped[str] = mapped_column(String(300), nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("50"), index=True)
    status: Mapped[FetchStatus] = mapped_column(
        pg_enum(FetchStatus, "fetch_queue_status"), nullable=False, server_default="pending", index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONB)
    job_run_id: Mapped[uuid.UUID | None] = uuid_fk("job_runs.id", nullable=True)
