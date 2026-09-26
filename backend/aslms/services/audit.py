"""Append-only audit log with a frozen actor snapshot (ground rules 3 and 5)."""

from __future__ import annotations

import ipaddress
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from aslms.domain.events import AuditLog
from aslms.domain.org import User


@dataclass(frozen=True)
class Actor:
    """Who is acting, frozen at the start of the request. `user_id` None means the system itself."""

    user_id: uuid.UUID | None
    name: str
    designation: str | None
    office_code: str | None
    ip: str | None = None
    user_agent: str | None = None

    @classmethod
    def system(cls, name: str = "system") -> Actor:
        return cls(None, name, None, None)

    @classmethod
    def of(cls, user: User, ip: str | None = None, user_agent: str | None = None) -> Actor:
        return cls(
            user.id,
            user.full_name,
            user.designation,
            user.office.code if user.office else None,
            ip,
            user_agent,
        )

    def snapshot(self) -> dict[str, Any]:
        """Columns of ActorSnapshotMixin."""
        return {
            "actor_user_id": self.user_id,
            "actor_name": self.name,
            "actor_designation": self.designation,
            "actor_office_code": self.office_code,
        }


def record(
    session: Session,
    actor: Actor,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    *,
    case_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditLog(
            **actor.snapshot(),
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            case_id=case_id,
            ip=_valid_ip(actor.ip),
            user_agent=(actor.user_agent or "")[:400] or None,
            before=_jsonable(before),
            after=_jsonable(after),
        )
    )


def _valid_ip(ip: str | None) -> str | None:
    """`audit_log.ip` is inet: keep real addresses only (test clients and some proxies send names)."""
    if not ip:
        return None
    try:
        return str(ipaddress.ip_address(ip.split("%", 1)[0]))
    except ValueError:
        return None


def _jsonable(d: dict[str, Any] | None) -> dict[str, Any] | None:
    if d is None:
        return None
    out: dict[str, Any] = {}
    for k, v in d.items():
        out[k] = v if isinstance(v, (str, int, float, bool, type(None), list, dict)) else str(v)
    return out
