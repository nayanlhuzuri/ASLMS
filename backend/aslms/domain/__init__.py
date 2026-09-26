"""SQLAlchemy models, one module per data group (docs/schema/phase1.md; Phase 2: workflow, sourcetrace).
Every module must be imported here so Alembic and `Base.metadata` see all tables."""

from aslms.db.base import Base
from aslms.domain import (
    alerts,
    cases,
    causelists,
    documents,
    events,
    ops,
    org,
    ownership,
    reference,
    sourcetrace,
    workflow,
)

__all__ = [
    "Base",
    "alerts",
    "causelists",
    "cases",
    "documents",
    "events",
    "ops",
    "org",
    "ownership",
    "reference",
    "sourcetrace",
    "workflow",
]
