"""The SourceTrace connector interface (design `sourcetrace-connector`, decision 1): ingestion only. The query
side (`ask`, `read_order`) is added by the items that use it, once SourceTrace's API shapes are known.

Only court orders and court filings are ever passed to `ingest`; the service (`services/sourcetrace_ingest.py`)
decides that, never an implementation. Implementations live in this package and nowhere else."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from aslms.core.errors import IntegrationError


@dataclass(frozen=True)
class IngestItem:
    """One document to add: its stored bytes and the fixed, court-public metadata (decision 4).
    `document_id` is also the idempotency key (`metadata["external_id"]`)."""

    document_id: uuid.UUID
    content: bytes = field(repr=False)
    mime: str
    filename: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class IngestResult:
    """SourceTrace's reference for the document, stored verbatim (≤ 200 characters), and its answer as sent."""

    reference: str
    raw: dict[str, Any] | None = None


class SourceTraceError(IntegrationError):
    """SourceTrace could not take the document. `response` is SourceTrace's answer, verbatim, when it gave one
    (never anything from `.env`)."""

    def __init__(self, message: str, *, response: dict[str, Any] | None = None, **details: object):
        super().__init__(message, **details)
        self.response = response


class SourceTraceUnavailable(SourceTraceError):
    """Connection failure, 5xx, throttling: retried with back-off (decision 7)."""


class SourceTraceRejected(SourceTraceError):
    """The document itself was refused (type, size, content): failed at once, no retry (decision 7)."""


@runtime_checkable
class SourceTraceConnector(Protocol):
    name: str

    async def ingest(self, item: IngestItem) -> IngestResult: ...
