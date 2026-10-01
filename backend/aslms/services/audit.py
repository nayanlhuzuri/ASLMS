"""The audit trail (CLAUDE.md: every significant action writes an `audit_log` row). One helper, used by every
service that changes ownership, custody, notes, uploads, users, access or configuration. The row is
append-only (trigger `aslms_forbid_change`)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from aslms.domain.events import AuditLog


@dataclass(frozen=True)
class Actor:
    """Who is acting, frozen at write time (DB_STANDARD §5). `system` for jobs and the CLI."""

    user_id: uuid.UUID | None
    name: str
    designation: str | None = None
    office_code: str | None = None
    ip: str | None = None
    user_agent: str | None = None

    @classmethod
    def system(cls, name: str = "system") -> Actor:
        return cls(None, name)


def snapshot(actor: Actor) -> dict[str, Any]:
    return {
        "actor_user_id": actor.user_id,
        "actor_name": actor.name[:200],
        "actor_designation": (actor.designation or None) and actor.designation[:200],
        "actor_office_code": (actor.office_code or None) and actor.office_code[:40],
    }


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str)) if value is not None else None


def write_audit(
    session: Session,
    actor: Actor,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    *,
    before: Any = None,
    after: Any = None,
    case_id: uuid.UUID | None = None,
) -> AuditLog:
    row = AuditLog(
        action=action[:80],
        entity_type=entity_type[:60],
        entity_id=entity_id,
        case_id=case_id,
        ip=(actor.ip or None) and actor.ip[:64],
        user_agent=(actor.user_agent or None) and actor.user_agent[:400],
        before=_jsonable(before),
        after=_jsonable(after),
        **snapshot(actor),
    )
    session.add(row)
    session.flush()
    return row
