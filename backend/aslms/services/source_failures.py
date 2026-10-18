"""`source_failures` (derived; unique (kind, ref)): the one upsert every caller shares (design `safety-fixes`,
decision 10). A repeat bumps `attempts` and `last_seen` and clears `resolved_at`; `resolve` closes the open row of
(kind, ref). Queue rows that fail for good are mirrored here as `fetch_<kind>` by `services/queue.py`."""

from __future__ import annotations

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from aslms.domain.ops import SourceFailure

MAX_REF = 300
MAX_ERROR = 2000
MAX_FAMILY = 40


def record(session: Session, kind: str, ref: str, error: str, family: str | None = None) -> None:
    """Insert the failure of (kind, ref), or bump the existing row and reopen it."""
    stmt = pg_insert(SourceFailure).values(
        kind=kind,
        ref=ref[:MAX_REF],
        error=(error or "")[:MAX_ERROR],
        error_family=family[:MAX_FAMILY] if family else None,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["kind", "ref"],
        set_={
            "error": stmt.excluded.error,
            "error_family": func.coalesce(stmt.excluded.error_family, SourceFailure.error_family),
            "last_seen": func.now(),
            "attempts": SourceFailure.attempts + 1,
            "resolved_at": None,
        },
    )
    session.execute(stmt)


def resolve(session: Session, kind: str, ref: str) -> int:
    """Mark the open failure of (kind, ref) resolved; the number of rows closed (0 or 1)."""
    n = session.execute(
        update(SourceFailure)
        .where(
            SourceFailure.kind == kind,
            SourceFailure.ref == ref[:MAX_REF],
            SourceFailure.resolved_at.is_(None),
        )
        .values(resolved_at=func.now())
        .execution_options(synchronize_session=False)
    ).rowcount
    return n or 0
