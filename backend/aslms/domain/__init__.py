"""SQLAlchemy models, one module per data group of docs/schema/schema.md. Importing this package registers
every table on `Base.metadata` (Alembic autogenerate and the metadata tests rely on it)."""

from aslms.domain import (  # noqa: F401
    alerts,
    assistant,
    cases,
    causelists,
    courts,
    documents,
    events,
    insights,
    ops,
    org,
    ownership,
    reference,
    research,
    tickets,
    workflow,
)
