"""Group 9 — integration and operations: job runs, the NAPIX call log and source failures.
These feed the "data collection health" report and the administration attention screen."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import Base, CreatedAtMixin, TableClass, TimestampMixin, pg_enum, uuid_fk, uuid_pk


class JobKind(enum.StrEnum):
    DAILY_CYCLE = "daily_cycle"
    STATUS_REFRESH = "status_refresh"
    FULL_REFRESH = "full_refresh"
    ORDER_DOWNLOAD = "order_download"
    DISCOVERY = "discovery"
    MASTER_SYNC = "master_sync"
    NOTIFICATIONS = "notifications"
    NAPIX_CHECK = "napix_check"


class JobStatus(enum.StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class JobRun(TimestampMixin, Base):
    __tablename__ = "job_runs"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (Index("ix_job_runs_job_started", "job", text("started_at DESC")),)

    id: Mapped[uuid.UUID] = uuid_pk()
    job: Mapped[JobKind] = mapped_column(pg_enum(JobKind, "job_kind"), nullable=False)
    run_date: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"), nullable=False, server_default=JobStatus.RUNNING.value
    )
    counters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)


class NapixCallLog(CreatedAtMixin, Base):
    __tablename__ = "napix_call_log"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (Index("ix_napix_call_log_called_at", text("called_at DESC")),)

    id: Mapped[uuid.UUID] = uuid_pk()
    api: Mapped[str] = mapped_column(String(120), nullable=False)
    params_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    napix_status: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    job_run_id: Mapped[uuid.UUID | None] = uuid_fk("job_runs.id", nullable=True, ondelete="CASCADE")


class FailureKind(enum.StrEnum):
    NAPIX = "napix"
    GHC_PDF = "ghc_pdf"
    ORDER_DOWNLOAD = "order_download"
    ANTIVIRUS = "antivirus"
    SOURCETRACE = "sourcetrace"
    EMAIL = "email"
    SMS = "sms"


class SourceFailure(TimestampMixin, Base):
    """One row per failing thing (keyed by kind + ref), updated on every retry, closed when it succeeds."""

    __tablename__ = "source_failures"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (
        Index(
            "uq_source_failures_open",
            "kind",
            "ref",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[FailureKind] = mapped_column(pg_enum(FailureKind, "failure_kind"), nullable=False)
    ref: Mapped[str] = mapped_column(String(300), nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
