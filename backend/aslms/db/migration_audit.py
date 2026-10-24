"""Audit rows and events written by reference-data migrations (design `followups-oct`, decision 19;
`docs/DB_STANDARD.md`, migrations section).

A reference-data migration (0016, 0018, 0022 and the next ones) changes rows, not schema, and records what it changed
in `audit_log` and, where a timeline needs it, in `events`. Audit is append-only, so a migration that is downgraded and
applied again must not write its rows twice for one application, yet must record a real re-application, and its
events must be raised again. The rules:
- an **application** of revision R begins at the latest downgrade past R, recorded as an audit row `system.migrated`
  whose `before.revision >= R` and whose `after.revision < R` (or empty, the base). `record_downgrade` writes that
  row; the downgrade of a migration that uses this module calls it last;
- `audit_once(bind, action, key, revision=R, ...)` writes an audit row only when this application has no row with the
  same `action` and `after.migration_key = key`;
- `event_key(migration, application_no(bind, R), ...)` puts the application counter into an event's dedupe key, so a
  real re-application raises its event once more.

Plain SQL on the migration's connection, no ORM and no application import beyond this module, so a migration stays
frozen once applied. Rows are stamped with `clock_timestamp()` so their order holds inside one transaction (alembic
runs every migration of an upgrade in one)."""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa

ACTOR_PREFIX = "migration "

_SINCE = sa.text(
    "SELECT max(created_at) FROM audit_log WHERE action = 'system.migrated' "
    "AND before->>'revision' >= :rev AND COALESCE(after->>'revision', '') < :rev"
)
_DOWNGRADES = sa.text(
    "SELECT count(*) FROM audit_log WHERE action = 'system.migrated' "
    "AND before->>'revision' >= :rev AND COALESCE(after->>'revision', '') < :rev"
)
_INSERT = sa.text(
    "INSERT INTO audit_log (action, entity_type, entity_id, actor_name, before, after, created_at) "
    "VALUES (:action, :entity_type, :entity_id, :actor_name, CAST(:before AS jsonb), CAST(:after AS jsonb), "
    "clock_timestamp())"
)


def _json(value: Any) -> str | None:
    return json.dumps(value, default=str) if value is not None else None


def application_start(bind: Any, revision: str):
    """When the current application of `revision` began: the latest recorded downgrade past it, or None (the first
    application)."""
    return bind.execute(_SINCE, {"rev": revision}).scalar()


def application_no(bind: Any, revision: str) -> int:
    """1 for the first application of `revision`, 2 after one recorded downgrade past it, and so on."""
    return int(bind.execute(_DOWNGRADES, {"rev": revision}).scalar() or 0) + 1


def audit_once(
    bind: Any,
    action: str,
    key: str,
    *,
    revision: str,
    entity_type: str,
    entity_id: Any = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> bool:
    """Writes the audit row `action` with `after.migration_key = key` unless this application of `revision` already
    has one; True when written. The actor is `migration <revision>`."""
    since = application_start(bind, revision)
    sql = "SELECT EXISTS (SELECT 1 FROM audit_log WHERE action = :action AND after->>'migration_key' = :key"
    params: dict[str, Any] = {"action": action, "key": key}
    if since is not None:
        sql += " AND created_at > :since"
        params["since"] = since
    if bind.execute(sa.text(sql + ")"), params).scalar():
        return False
    bind.execute(
        _INSERT,
        {
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor_name": f"{ACTOR_PREFIX}{revision}",
            "before": _json(before),
            "after": _json({**(after or {}), "migration": revision, "migration_key": key}),
        },
    )
    return True


def event_key(migration: str, application: int, *parts: Any) -> str:
    """An event dedupe key carrying the application counter: `<migration>:<application>:<part>:...`."""
    return ":".join([migration, str(application), *(str(p) for p in parts)])


def record_downgrade(bind: Any, revision: str, down_revision: str | None) -> None:
    """The audit row `system.migrated` of a downgrade past `revision` (the last step of such a migration's
    downgrade): the next upgrade is a new application. A downgrade of a reference-data migration is a restore, not
    `alembic downgrade` (docs/operations.md section 6); this row records one when it happens anyway."""
    bind.execute(
        _INSERT,
        {
            "action": "system.migrated",
            "entity_type": "database",
            "entity_id": None,
            "actor_name": f"{ACTOR_PREFIX}{revision}",
            "before": _json({"revision": revision}),
            "after": _json({"revision": down_revision, "downgrade": True}),
        },
    )
