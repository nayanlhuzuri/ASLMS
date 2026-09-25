"""SQLAlchemy models, one module per data group (docs/schema/phase1.md).
Every module must be imported here so Alembic and `Base.metadata` see all tables."""

from aslms.db.base import Base
from aslms.domain import alerts, cases, causelists, documents, events, ops, org, ownership, reference

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
]
