"""0022 alerts, visibility and roles: two alert kinds and two changed access defaults

Design `alerts-visibility-roles`, decision 18 and "Data"; docs/schema/schema.md, Group 0 row `ref_alert_kind` and Group 1
row `role_permissions`. A reference-data and access-default migration modelled on 0016 and 0018: hard-coded rows, no
application import, frozen once applied. Autogenerate finds nothing (no table, column, type or index changes); no
grant changes (`aslms_app` already has SELECT / INSERT / UPDATE on `role_permissions` and `ref_alert_kind` and INSERT
on `audit_log` and `events`). The design note names it 0021; that number went to `ownership-refinements`, so it is
0022 by build order (the owner's approval).

(a) `ref_alert_kind` gets `new_note` ("New note", `normal`, sort 130) and `listed_tomorrow` ("Listed for tomorrow",
    `critical`, sort 140), `ON CONFLICT (code) DO NOTHING`; the seed carries the same labels and severities.
(b) Only on an already seeded database (`role_permissions` has rows; a fresh database gets the new defaults from the
    seed that follows `alembic upgrade head`), for `dept_head` / `custody.recall` (false -> true) and `auditor` /
    `assistant.use` (true -> false): the row is changed only while it still holds the old default, `updated_by IS
    NULL` and no `access.matrix` audit row exists for that type and function. Each change writes one audit row
    `access.matrix_default_changed` and one `access_changed` event; a row left alone writes one audit row
    `access.matrix_default_kept` with `reason: "customised"`.
(c) On a seeded database, one audit row `access.rule_changed` dates the moment State oversight and the central operator
    stopped reading private records (a rule, not a matrix row; the function `cases.view_private_all` and its matrix
    rows are "missing rows" the seed inserts).

The downgrade restores each value 0022 changed whose matrix row still holds the new value and has no later
`access.matrix` audit row (one audit row each, `migration: "0022-downgrade"`), then deletes the two alert kinds if no
alert uses them. Audit rows are append-only and stay.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-22
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

MIGRATION = "0022"
DESIGN = "alerts-visibility-roles"
ACTOR_NAME = "migration 0022"
ALERT_KINDS = (
    ("new_note", "New note", "normal", 130),
    ("listed_tomorrow", "Listed for tomorrow", "critical", 140),
)
# (type, function, old default, new default) — design decision 17
CHANGES = (
    ("dept_head", "custody.recall", False, True),
    ("auditor", "assistant.use", True, False),
)
RULE = {
    "rule": "private_records_state_wide",
    "function": "cases.view_private_all",
    "default_types": ["auditor"],
    "always": ["super_admin"],
    "withdrawn_from": ["state_oversight", "central_operator"],
    "migration": MIGRATION,
}

_AUDIT = sa.text(
    "INSERT INTO audit_log (action, entity_type, entity_id, actor_name, before, after) "
    "VALUES (:action, :entity_type, :entity_id, :actor_name, CAST(:before AS jsonb), CAST(:after AS jsonb))"
)


def _audit(bind, action: str, entity_type: str, entity_id, before, after) -> None:
    bind.execute(
        _AUDIT,
        {
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor_name": ACTOR_NAME,
            "before": json.dumps(before) if before is not None else None,
            "after": json.dumps(after) if after is not None else None,
        },
    )


def _matrix_audited(bind, role: str, permission: str, after_time=None) -> bool:
    sql = (
        "SELECT EXISTS (SELECT 1 FROM audit_log WHERE action = 'access.matrix' "
        "AND after->>'role' = :r AND after->>'permission' = :p"
    )
    params = {"r": role, "p": permission}
    if after_time is not None:
        sql += " AND created_at > :t"
        params["t"] = after_time
    return bool(bind.execute(sa.text(sql + ")"), params).scalar())


def upgrade() -> None:
    bind = op.get_bind()
    # (a) the alert kinds
    for code, label, severity, sort_order in ALERT_KINDS:
        bind.execute(
            sa.text(
                "INSERT INTO ref_alert_kind (code, label, default_severity, sort_order, is_active) "
                "VALUES (:code, :label, :severity, :sort_order, true) ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "label": label, "severity": severity, "sort_order": sort_order},
        )
    if not bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM role_permissions)")).scalar():
        return  # a fresh database: the seed inserts the new defaults directly
    # (b) the two changed defaults
    for role, permission, old, new in CHANGES:
        row = bind.execute(
            sa.text(
                "SELECT id, is_enabled, updated_by FROM role_permissions WHERE role = :r AND permission = :p"
            ),
            {"r": role, "p": permission},
        ).first()
        if row is None:
            continue  # the seed inserts the missing row with the new default
        untouched = (
            row.is_enabled is old and row.updated_by is None and not _matrix_audited(bind, role, permission)
        )
        if untouched:
            bind.execute(
                sa.text("UPDATE role_permissions SET is_enabled = :v WHERE id = :id"),
                {"v": new, "id": row.id},
            )
            _audit(
                bind,
                "access.matrix_default_changed",
                "role_permission",
                row.id,
                {"is_enabled": old},
                {
                    "role": role,
                    "permission": permission,
                    "is_enabled": new,
                    "migration": MIGRATION,
                    "design": DESIGN,
                },
            )
            bind.execute(
                sa.text(
                    "INSERT INTO events (type, payload, dedupe_key, visibility) "
                    "VALUES ('access_changed', CAST(:payload AS jsonb), :key, 'scoped') "
                    "ON CONFLICT (dedupe_key) DO NOTHING"
                ),
                {
                    "payload": json.dumps({"role": role, "permission": permission, "is_enabled": new}),
                    "key": f"access_matrix_default:{MIGRATION}:{role}:{permission}",
                },
            )
        else:
            _audit(
                bind,
                "access.matrix_default_kept",
                "role_permission",
                row.id,
                {"is_enabled": row.is_enabled},
                {
                    "role": role,
                    "permission": permission,
                    "is_enabled": row.is_enabled,
                    "reason": "customised",
                    "migration": MIGRATION,
                    "design": DESIGN,
                },
            )
    # (c) the private-records rule
    _audit(bind, "access.rule_changed", "access_rule", None, None, RULE)


def downgrade() -> None:
    bind = op.get_bind()
    changed = bind.execute(
        sa.text(
            "SELECT entity_id, after->>'role' AS role, after->>'permission' AS permission, created_at "
            "FROM audit_log WHERE action = 'access.matrix_default_changed' AND after->>'migration' = :m "
            "ORDER BY created_at"
        ),
        {"m": MIGRATION},
    ).all()
    olds = {(r, p): old for r, p, old, _ in CHANGES}
    news = {(r, p): new for r, p, _, new in CHANGES}
    for entity_id, role, permission, created_at in changed:
        key = (role, permission)
        if key not in olds:
            continue
        row = bind.execute(
            sa.text("SELECT id, is_enabled FROM role_permissions WHERE id = :id"), {"id": entity_id}
        ).first()
        if row is None or row.is_enabled is not news[key]:
            continue
        if _matrix_audited(bind, role, permission, after_time=created_at):
            continue
        bind.execute(
            sa.text("UPDATE role_permissions SET is_enabled = :v WHERE id = :id"),
            {"v": olds[key], "id": row.id},
        )
        _audit(
            bind,
            "access.matrix_default_changed",
            "role_permission",
            row.id,
            {"is_enabled": news[key]},
            {
                "role": role,
                "permission": permission,
                "is_enabled": olds[key],
                "migration": f"{MIGRATION}-downgrade",
                "design": DESIGN,
            },
        )
    for code, _, _, _ in ALERT_KINDS:
        bind.execute(
            sa.text(
                "DELETE FROM ref_alert_kind WHERE code = :code "
                "AND NOT EXISTS (SELECT 1 FROM alerts WHERE kind = :code)"
            ),
            {"code": code},
        )
