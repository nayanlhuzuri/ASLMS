"""Group 9 — integration and operations: job runs, the NAPIX call log, verbatim responses, failures and the
resumable fetch queue of the load-and-refresh pipeline."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import (
    Base,
    CreatedAtMixin,
    CreatedByMixin,
    TableClass,
    TimestampMixin,
    pg_enum,
    uuid_fk,
    uuid_pk,
)


class FetchLane(enum.StrEnum):
    """Who asked for a queue row (design `data-load-console`, decision 1), in order of precedence: a person's
    request, the daily cycle, department discovery (design `department-discovery`, decision 6; migration 0017), the
    backdated load. A row asked by two lanes keeps the higher one."""

    REQUEST = "request"
    DAILY = "daily"
    DISCOVERY = "discovery"
    LOAD = "load"


class LoadOrder(enum.StrEnum):
    """What goes first in the backdated load (decision 3)."""

    CASES_FIRST = "cases_first"
    LISTS_FIRST = "lists_first"
    CASES_WITH_ORDERS = "cases_with_orders"


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
    """One row per HTTP attempt (CLAUDE.md: every call is logged). Pruned after the retention period. `called_at`
    is the attempt's own time (design `napix-window`, decision 7)."""

    __tablename__ = "napix_call_log"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (
        Index(
            "ix_napix_call_log_user_called",
            "user_id",
            "called_at",
            postgresql_where=text("user_id IS NOT NULL"),
        ),
    )
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
    # the lane of the queue item that made the call; NULL for calls made by the API (data-load-console, 0014)
    lane: Mapped[FetchLane | None] = mapped_column(pg_enum(FetchLane, "fetch_lane"))
    # the person whose action caused the call; NULL for daily and load work, probes and CLI checks (napix-window, 0015)
    user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, index=False)


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
    PARTY_SEARCH = "party_search"  # design department-discovery, decision 3 (migration 0017)


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
    __table_args__ = (
        UniqueConstraint("kind", "ref"),
        # the claim query's order (design data-load-console, migration 0014)
        Index("ix_fetch_queue_claim", "priority", "created_at", postgresql_where=text("status = 'pending'")),
        Index("ix_fetch_queue_lane_list_date", "lane", "list_date"),
        # only a person's request carries a person (design napix-window, decision 10; migration 0015)
        CheckConstraint("requested_by IS NULL OR lane = 'request'", name="requested_by"),
    )
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
    lane: Mapped[FetchLane] = mapped_column(
        pg_enum(FetchLane, "fetch_lane"), nullable=False, server_default="daily"
    )
    # the cause-list date whose loading queued the row; inherited by the dossiers and order PDFs it spawns
    list_date: Mapped[date | None] = mapped_column(Date)
    # the person who asked for the row's pending run (request lane only); copied to the calls it makes
    requested_by: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True, index=False)


class DataLoadSettings(TimestampMixin, CreatedByMixin, Base):
    """Pause and order of the backdated load, versioned (design `data-load-console`, decision 18): each pause,
    resume or order change inserts a new version and closes the previous one; values are never updated in place
    and rows are never deleted. An empty table means running, `cases_first`, nothing brought forward."""

    __tablename__ = "data_load_settings"
    __table_class__ = TableClass.MASTER
    __table_args__ = (
        CheckConstraint("is_current = (valid_to IS NULL)", name="current"),
        CheckConstraint(
            "(first_from IS NULL) = (first_to IS NULL) AND (first_from IS NULL OR first_from <= first_to)",
            name="first",
        ),
        Index(
            "ix_data_load_settings_current", "is_current", unique=True, postgresql_where=text("is_current")
        ),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    version: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    load_order: Mapped[LoadOrder] = mapped_column(
        pg_enum(LoadOrder, "load_order"), nullable=False, server_default="cases_first"
    )
    first_from: Mapped[date | None] = mapped_column(Date)
    first_to: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
