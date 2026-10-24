"""`FakeSourceTrace` — the test double of the connector (design `sourcetrace-connector`, decision 2). Tests pass
it to the service directly; `get_connector` never returns it.

It records every item it receives and answers with the reference `fake-<first 24 hex of sha256(content)>`, or,
for the next calls, with the scripted outcomes: `ok`, `unavailable`, `rejected`, `timeout` (sleeps past the
caller's timeout), `bad_reference` (an empty reference) and `error` (an unexpected exception). `on_ingest`, when
given, is called with each item before it answers (a test uses it to act while the document row is locked).

The query side (design `assistant`, "Services"): `ask` records every request in `asked` and answers from
`script_ask(...)`: an `Answer` returned as it is, or one of the outcomes `ok`, `unavailable`, `rejected`, `timeout`,
`bad_answer` (a malformed answer), `out_of_scope` (a citation to a reference that is not in the scope) and `error`.
`ok` (and every call after the script) answers citing the first filing of the scope, else `cite` when given."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from collections import deque
from collections.abc import Callable
from typing import Any

from aslms.integration.sourcetrace.connector import (
    Answer,
    AskRequest,
    Citation,
    IngestItem,
    IngestResult,
    SourceTraceRejected,
    SourceTraceUnavailable,
)

OUTCOMES = ("ok", "unavailable", "rejected", "timeout", "bad_reference", "error")
ASK_OUTCOMES = ("ok", "unavailable", "rejected", "timeout", "bad_answer", "out_of_scope", "error")
OUT_OF_SCOPE_REF = "fake-outside-the-scope"


def fake_reference(content: bytes) -> str:
    return f"fake-{hashlib.sha256(content).hexdigest()[:24]}"


class FakeSourceTrace:
    name = "fake"

    def __init__(
        self,
        *,
        timeout_sleep: float = 5.0,
        on_ingest: Callable[[IngestItem], Any] | None = None,
        cite: str | None = None,
    ):
        self.received: list[IngestItem] = []
        self.timeout_sleep = timeout_sleep
        self.on_ingest = on_ingest
        self._script: deque[str] = deque()
        self.asked: list[AskRequest] = []
        self.cite = cite
        self._ask_script: deque[Answer | str] = deque()

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

    # ---------------------------------------------------------------------------------------- the query side

    def script_ask(self, *items: Answer | str) -> FakeSourceTrace:
        """The answers of the next questions, in order (an `Answer` or an outcome); afterwards every one is `ok`."""
        for item in items:
            if not isinstance(item, Answer) and item not in ASK_OUTCOMES:
                raise ValueError(f"unknown outcome {item!r}; an Answer or one of {ASK_OUTCOMES}")
            self._ask_script.append(item)
        return self

    def _default_answer(self, request: AskRequest) -> Answer:
        citations: tuple[Citation, ...] = ()
        if request.scope.filings:
            first = request.scope.filings[0]
            citations = (Citation(reference=first.reference, page=1, passage="fake passage"),)
        elif self.cite:
            citations = (Citation(reference=self.cite, page=1, passage="fake passage"),)
        return Answer(
            text="fake: an answer from the scripted SourceTrace",
            citations=citations,
            info={"engine": "fake"},
            raw={"answer": "fake", "references": [c.reference for c in citations]},
        )

    async def ask(self, request: AskRequest) -> Answer:
        self.asked.append(request)
        item = self._ask_script.popleft() if self._ask_script else "ok"
        if isinstance(item, Answer):
            return item
        if item == "unavailable":
            raise SourceTraceUnavailable("fake: SourceTrace is unavailable", response={"status": 503})
        if item == "rejected":
            raise SourceTraceRejected("fake: question refused", response={"status": 422, "reason": "refused"})
        if item == "timeout":
            await asyncio.sleep(self.timeout_sleep)
        if item == "error":
            raise RuntimeError("fake: unexpected connector failure")
        if item == "bad_answer":
            return {"text": None}  # type: ignore[return-value]  # a malformed answer, on purpose
        if item == "out_of_scope":
            return Answer(
                text="fake: an answer quoting material outside the scope",
                citations=(Citation(reference=OUT_OF_SCOPE_REF, page=3, passage="outside"),),
                raw={"answer": "fake", "references": [OUT_OF_SCOPE_REF]},
            )
        return self._default_answer(request)
