"""`FakeSourceTrace` — the test double of the connector (design `sourcetrace-connector`, decision 2). Tests pass
it to the service directly; `get_connector` never returns it.

It records every item it receives and answers with the reference `fake-<first 24 hex of sha256(content)>`, or,
for the next calls, with the scripted outcomes: `ok`, `unavailable`, `rejected`, `timeout` (sleeps past the
caller's timeout), `bad_reference` (an empty reference) and `error` (an unexpected exception). `on_ingest`, when
given, is called with each item before it answers (a test uses it to act while the document row is locked)."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from collections import deque
from collections.abc import Callable
from typing import Any

from aslms.integration.sourcetrace.connector import (
    IngestItem,
    IngestResult,
    SourceTraceRejected,
    SourceTraceUnavailable,
)

OUTCOMES = ("ok", "unavailable", "rejected", "timeout", "bad_reference", "error")


def fake_reference(content: bytes) -> str:
    return f"fake-{hashlib.sha256(content).hexdigest()[:24]}"


class FakeSourceTrace:
    name = "fake"

    def __init__(
        self,
        *,
        timeout_sleep: float = 5.0,
        on_ingest: Callable[[IngestItem], Any] | None = None,
    ):
        self.received: list[IngestItem] = []
        self.timeout_sleep = timeout_sleep
        self.on_ingest = on_ingest
        self._script: deque[str] = deque()

    def __repr__(self) -> str:
        return f"FakeSourceTrace(received={len(self.received)}, scripted={list(self._script)})"

    def script(self, *outcomes: str) -> FakeSourceTrace:
        """The answers of the next calls, in order; afterwards every call is `ok`."""
        for o in outcomes:
            if o not in OUTCOMES:
                raise ValueError(f"unknown outcome {o!r}; one of {OUTCOMES}")
            self._script.append(o)
        return self

    async def ingest(self, item: IngestItem) -> IngestResult:
        self.received.append(item)
        if self.on_ingest is not None:
            result = self.on_ingest(item)
            if inspect.isawaitable(result):
                await result
        outcome = self._script.popleft() if self._script else "ok"
        if outcome == "unavailable":
            raise SourceTraceUnavailable("fake: SourceTrace is unavailable", response={"status": 503})
        if outcome == "rejected":
            raise SourceTraceRejected("fake: document refused", response={"status": 422, "reason": "refused"})
        if outcome == "timeout":
            await asyncio.sleep(self.timeout_sleep)
        if outcome == "error":
            raise RuntimeError("fake: unexpected connector failure")
        if outcome == "bad_reference":
            return IngestResult(reference="", raw={"reference": ""})
        ref = fake_reference(item.content)
        return IngestResult(
            reference=ref, raw={"reference": ref, "external_id": item.metadata.get("external_id")}
        )
