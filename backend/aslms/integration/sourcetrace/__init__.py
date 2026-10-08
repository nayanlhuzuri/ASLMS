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
    IngestItem,
    IngestResult,
    SourceTraceConnector,
    SourceTraceError,
    SourceTraceRejected,
    SourceTraceUnavailable,
)

log = logging.getLogger(__name__)

ConnectorState = Literal["disabled", "not_implemented", "ready"]

__all__ = [
    "ConnectorState",
    "IngestItem",
    "IngestResult",
    "SourceTraceConnector",
    "SourceTraceError",
    "SourceTraceRejected",
    "SourceTraceUnavailable",
    "connector_state",
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
