"""SourceTrace, the in-house RAG service (plan §3.2). Endpoint shapes are pending; `get_knowledge_service()`
returns the stub until SOURCETRACE_ENABLED is true and a real client is written against the published API."""

from __future__ import annotations

from aslms.core.config import get_settings
from aslms.integration.sourcetrace.stub import SourceTraceStub


def get_knowledge_service() -> SourceTraceStub:
    if get_settings().sourcetrace_enabled:
        raise NotImplementedError(
            "SourceTrace API shapes are not available yet; keep SOURCETRACE_ENABLED=false"
        )
    return SourceTraceStub()
