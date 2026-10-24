"""The SourceTrace connector interfaces: ingestion (design `sourcetrace-connector`, decision 1) and the Case
Assistant's query contract (design `assistant`, decision 1), two separate protocols. The future HTTP connector
(row 36) implements both; the assistant's preview (`services/assistant_preview.py`) implements only `ask`.

Only court orders and court filings are ever passed to `ingest`; the service (`services/sourcetrace_ingest.py`)
decides that, never an implementation. The query contract is provider-neutral: it names no URL, header or field of
SourceTrace's API (unknown until row 36), and its scope carries court-public facts and document references only,
never a note, a draft, an internal document, a custody remark, the owner or the asking user's name or office.
Implementations live in this package and nowhere else (the preview, which uses no AI and sends nothing out, lives
in the services package by the design)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Protocol, runtime_checkable

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
    """The document itself was refused (type, size, content): failed at once, no retry (decision 7). For a
    question: the question was refused (design `assistant`, decision 1), no retry."""


class SourceTraceProtocolError(SourceTraceError):
    """A malformed answer to a question (design `assistant`, decision 1): stored as `failed`, no retry."""


@runtime_checkable
class SourceTraceConnector(Protocol):
    name: str

    async def ingest(self, item: IngestItem) -> IngestResult: ...


# ------------------------------------------------------------------------------------------------ the query side


@dataclass(frozen=True)
class CaseContext:
    """The court-public facts of one focus case (design `assistant`, decisions 3 and 12). Nothing internal: no owner,
    custody, stage, note, recommendation or `ref_no`."""

    case_id: uuid.UUID
    cnr: str | None
    case_no_text: str | None
    filing_no_text: str | None
    court: str | None
    bench: str | None
    case_type: str | None
    year: int | None
    status: str | None
    parties: tuple[str, ...] = ()
    advocates: tuple[str, ...] = ()
    acts: tuple[str, ...] = ()
    last_hearing_date: date | None = None
    next_hearing_date: date | None = None


@dataclass(frozen=True)
class FilingRef:
    """One court filing the asker may see: the document id, and the reference passed to the connector (the
    document id in preview, the `sourcetrace_ref` in sourcetrace)."""

    document_id: uuid.UUID
    reference: str


@dataclass(frozen=True)
class AskScope:
    """Decision 6: the court orders as a corpus description (never a list), the filings as an allow-list."""

    kind: Literal["case", "my_cases", "research"]
    focus: tuple[CaseContext, ...]
    orders: Literal["focus", "focus_and_related", "all"]
    filings: tuple[FilingRef, ...] = ()
    truncated: bool = False


@dataclass(frozen=True)
class Turn:
    """One earlier question and the connector's own answer in the same conversation."""

    question: str
    answer: str


@dataclass(frozen=True)
class AskRequest:
    """`request_id` is the question's id (an idempotency key)."""

    request_id: uuid.UUID
    question: str
    scope: AskScope
    history: tuple[Turn, ...] = ()


@dataclass(frozen=True)
class Citation:
    """A source of an answer, by reference: the preview names the document id; SourceTrace its own reference,
    mapped back by the service. `locator` is SourceTrace's own, verbatim."""

    reference: str
    document_id: uuid.UUID | None = None
    page: int | None = None
    passage: str | None = None
    related: bool = False
    locator: dict[str, Any] | None = None
    rank: float | None = None


@dataclass(frozen=True)
class Answer:
    text: str
    citations: tuple[Citation, ...] = ()
    outcome: Literal["answered", "no_match"] = "answered"
    info: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] | None = None


@runtime_checkable
class AssistantConnector(Protocol):
    name: str

    async def ask(self, request: AskRequest) -> Answer: ...
