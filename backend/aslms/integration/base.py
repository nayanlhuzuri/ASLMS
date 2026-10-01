"""Protocols the services program against. Until the NAPIX field inventory is approved (plan step 3), the
court source hands back the decrypted responses as they are (dicts and lists in the court's own key names),
plus the small references the daily cycle needs to navigate (bench → cause list → case)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class BenchRef:
    bench_id: str
    judge_name: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CauseListRef:
    list_date: date
    bench_id: str
    causelist_id: str | None  # from Cause List Details; None until the live test shows where it comes from
    list_type: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class CourtSource(Protocol):
    name: str

    async def overview(self) -> dict[str, Any]: ...
    async def causelist_benches(self, list_date: date) -> list[BenchRef]: ...
    async def causelist_details(self, list_date: date, bench_id: str) -> list[dict[str, Any]]: ...
    async def show_causelist(self, ref: CauseListRef) -> bytes | dict[str, Any]: ...
    async def case_by_cnr(self, cnr: str) -> dict[str, Any]: ...
    async def current_status(self, cnrs: list[str]) -> list[dict[str, Any]]: ...
    async def show_order(self, cnr: str, order_no: str, order_date: date) -> bytes | dict[str, Any]: ...
    async def show_business(self, cnr: str, business_date: date) -> dict[str, Any]: ...
