"""The single way to append an event (ground rule 3). Idempotent on `dedupe_key`."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from aslms.core.time import now_utc
from aslms.domain.events import Event, EventType, EventVisibility

TRACKING_CARD_TYPES = frozenset(
    {
        EventType.LISTED,
        EventType.LISTED_SUPPLEMENTARY,
        EventType.HEARING_DATE_CHANGED,
        EventType.STATUS_CHANGED,
        EventType.CASE_CREATED,
        EventType.CASE_CLAIMED,
        EventType.OWNERSHIP_TRANSFERRED,
    }
)


def emit(
    session: Session,
    type: EventType,
    dedupe_key: str,
    *,
    case_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    actor_user_id: uuid.UUID | None = None,
    occurred_at: datetime | None = None,
    visibility: EventVisibility | None = None,
) -> uuid.UUID | None:
    """Appends the event unless one with the same `dedupe_key` exists. Returns the new id, or None if it was
    a duplicate — callers use that to avoid repeating side effects (alerts, notifications)."""
    vis = visibility or (
        EventVisibility.TRACKING_CARD if type in TRACKING_CARD_TYPES else EventVisibility.SCOPED
    )
    stmt = (
        insert(Event)
        .values(
            type=type,
            dedupe_key=dedupe_key[:300],
            case_id=case_id,
            payload=payload or {},
            actor_user_id=actor_user_id,
            occurred_at=occurred_at or now_utc(),
            visibility=vis,
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(Event.id)
    )
    return session.execute(stmt).scalar_one_or_none()


def timeline(
    session: Session, case_id: uuid.UUID, *, tracking_only: bool = False, limit: int = 200
) -> list[Event]:
    q = select(Event).where(Event.case_id == case_id)
    if tracking_only:
        q = q.where(Event.visibility == EventVisibility.TRACKING_CARD)
    return list(session.scalars(q.order_by(Event.occurred_at.desc()).limit(limit)))
