"""Protocols and plain data records exchanged between the integration layer and the services.
Services depend on these, never on a concrete client, so a source can be swapped or stubbed in tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class BenchRef:
    bench_id: str
    judge_names: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CauseListRef:
    """One cause-list publication for (date, bench) as the source reports it."""

    list_date: date
    bench_id: str
    causelist_id: str
    list_type: str  # daily | supplementary | lawazima | vacation | other
    label: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CauseListRow:
    """One listed case as returned by Cause List Details (if it returns rows) or parsed from the PDF."""

    sr_no: int
    cnr: str | None
    case_no_text: str | None
    court_no: str | None
    petitioner_text: str | None
    respondent_text: str | None
    pet_advocate_text: str | None
    res_advocate_text: str | None
    with_text: str | None = None
    remarks: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderRef:
    order_no: str
    order_date: date | None
    kind: str  # interim | final | judgment
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PartyRef:
    role: str  # petitioner | respondent | extra
    party_no: int
    name: str
    address: str | None = None


@dataclass(frozen=True)
class CaseRecord:
    """Normalised full case record from Search by CNR."""

    cnr: str
    case_type_text: str | None
    reg_no: int | None
    reg_year: int | None
    filing_no_text: str | None
    filing_date: date | None
    registration_date: date | None
    status: str  # pending | disposed | unknown
    disposal_date: date | None
    disposal_nature: str | None
    next_hearing_date: date | None
    next_purpose: str | None
    last_hearing_date: date | None
    bench_id: str | None
    coram: str | None
    category: str | None
    judicial_branch: str | None
    petitioner_summary: str | None
    respondent_summary: str | None
    pet_advocate: str | None
    res_advocate: str | None
    parties: list[PartyRef]
    acts: list[dict[str, str | None]]
    orders: list[OrderRef]
    hearings: list[dict[str, Any]]
    linked_case_nos: list[str]
    linked_cnrs: list[str]
    fetched_at: datetime
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StatusRecord:
    """Cheap current status from the bulk Current Status API."""

    cnr: str
    status: str
    next_hearing_date: date | None
    next_purpose: str | None
    last_hearing_date: date | None
    disposal_date: date | None
    disposal_nature: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class CourtSource(Protocol):
    """What the daily cycle, tracker and search need from a court data source."""

    name: str

    async def causelist_benches(self, list_date: date) -> list[BenchRef]: ...
    async def causelists_for_bench(self, list_date: date, bench_id: str) -> list[CauseListRef]: ...
    async def causelist_rows(self, ref: CauseListRef) -> list[CauseListRow] | None: ...
    async def causelist_pdf(self, ref: CauseListRef) -> bytes | None: ...
    async def case_by_cnr(self, cnr: str) -> CaseRecord | None: ...
    async def current_status(self, cnrs: list[str]) -> list[StatusRecord]: ...
    async def order_pdf(self, cnr: str, order: OrderRef) -> bytes | None: ...
    async def business(self, cnr: str, business_date: date) -> dict[str, Any] | None: ...


@runtime_checkable
class KnowledgeService(Protocol):
    """SourceTrace connector. Real endpoints are pending; `sourcetrace/stub.py` implements this until then."""

    async def ingest(
        self, *, document_id: str, content: bytes, mime: str, metadata: dict[str, Any]
    ) -> str: ...
    async def next_date(self, *, sourcetrace_ref: str, order_date: date) -> dict[str, Any]: ...
    async def ask(self, *, question: str, context: dict[str, Any]) -> dict[str, Any]: ...


@runtime_checkable
class VirusScanner(Protocol):
    def scan(self, content: bytes) -> tuple[str, str | None]:
        """Returns (status: clean | infected | failed, detail)."""
        ...


@runtime_checkable
class Mailer(Protocol):
    def send(self, *, to: str, subject: str, body: str) -> None: ...


@runtime_checkable
class SmsGateway(Protocol):
    def send(self, *, to: str, text: str) -> None: ...
