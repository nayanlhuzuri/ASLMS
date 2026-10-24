"""SourceTrace: the only package where a SourceTrace implementation may live (CLAUDE.md: all AI goes through the
SourceTrace connector interface). Design `sourcetrace-connector`, decisions 1, 2 and 15.

No real implementation exists yet (the SourceTrace API is not documented): `get_connector` returns `None` whatever
the settings, and `connector_state` answers `disabled` or `not_implemented`. The fake (`fake.FakeSourceTrace`) is
for tests only and is never returned here: a fake reference written to the real database would be a fabricated
identifier."""

from __future__ import annotations

import logging
from typing import Literal

from aslms.core.config import Settings
from aslms.integration.sourcetrace.connector import (
    Answer,
    AskRequest,
    AskScope,
    AssistantConnector,
    CaseContext,
    Citation,
    FilingRef,
    IngestItem,
    IngestResult,
    SourceTraceConnector,
    SourceTraceError,
    SourceTraceProtocolError,
    SourceTraceRejected,
    SourceTraceUnavailable,
    Turn,
)

log = logging.getLogger(__name__)

ConnectorState = Literal["disabled", "not_implemented", "ready"]

__all__ = [
    "Answer",
    "AskRequest",
    "AskScope",
    "AssistantConnector",
    "CaseContext",
    "Citation",
    "ConnectorState",
    "FilingRef",
    "IngestItem",
    "IngestResult",
    "SourceTraceConnector",
    "SourceTraceError",
    "SourceTraceProtocolError",
    "SourceTraceRejected",
    "SourceTraceUnavailable",
    "Turn",
    "connector_state",
    "get_assistant_connector",
    "get_connector",
]


def connector_state(settings: Settings) -> ConnectorState:
    """`disabled` while `SOURCETRACE_ENABLED` is false; `not_implemented` when it is true (no HTTP connector
    exists yet). `ready` is unreachable until a real connector is added (follow-up `sourcetrace-http-connector`)."""
    if not settings.sourcetrace_enabled:
        return "disabled"
    return "not_implemented"


def get_connector(settings: Settings) -> SourceTraceConnector | None:
    """The configured connector, or `None` when nothing may be sent. Never the fake."""
    state = connector_state(settings)
    if state == "not_implemented":
        log.warning(
            "SOURCETRACE_ENABLED is set but no SourceTrace connector is implemented yet; nothing is sent"
        )
    return None


def get_assistant_connector(settings: Settings) -> AssistantConnector | None:
    """The real SourceTrace query connector (design `assistant`, decision 2): `None` until row 36 builds it, whatever
    the settings. Never the fake."""
    del settings
    return None
