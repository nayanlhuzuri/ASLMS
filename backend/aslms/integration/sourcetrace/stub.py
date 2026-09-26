"""Stand-in for SourceTrace that satisfies `KnowledgeService`. It never sends anything anywhere: ingestion is
refused with a clear message, next-date reading returns "needs manual review", and questions get no answer.
Replace with the real connector in Phase 2; nothing else changes because services only see the protocol."""

from __future__ import annotations

from datetime import date
from typing import Any

from aslms.core.errors import IntegrationError


class SourceTraceStub:
    name = "sourcetrace_stub"

    async def ingest(self, *, document_id: str, content: bytes, mime: str, metadata: dict[str, Any]) -> str:
        raise IntegrationError("SourceTrace is not connected (Phase 2)")

    async def next_date(self, *, sourcetrace_ref: str, order_date: date) -> dict[str, Any]:
        return {"next_date": None, "needs_review": True, "reason": "SourceTrace not connected"}

    async def ask(self, *, question: str, context: dict[str, Any]) -> dict[str, Any]:
        return {"answer": None, "citations": [], "reason": "SourceTrace not connected (Phase 3)"}
