"""0027 partial code match: the partial counsel-code weight and a new scoring-settings version

Design `partial-code-match` ("Data"; decisions 11 and 18); docs/schema/schema.md, row `scoring_settings`. The design
note names it 0026; that number went to `portal_ui_polish_2`, so it is 0027 by build order (the note allows the next
free number). Written by hand: one column, two CHECKs and a data step, hard-coded with no application import, so it
stays frozen once applied. No table, type, trigger or grant changes (`aslms_app` already has SELECT / INSERT / UPDATE
on `scoring_settings` and INSERT on `audit_log` and `events`).

Upgrade:
1. `weight_counsel_code_partial numeric(4,3) NULL` (NULL only on versions written before this migration).
2. When a current settings row exists: it is closed and version n + 1 is inserted with the five weights and both
   thresholds copied. Its partial weight is 0.600 when `possible <= 0.600 < strong` and `0.600 < counsel_code`;
   otherwise the midpoint of the thresholds rounded to 3 decimals, lowered to 0.001 below the counsel-code weight if
   needed. One audit row `scoring_settings.update` (actor `migration 0027`, before and after in the service's
   `summary` shape, `after.migration = "0027"`) and one `config_changed` event, as `scoring_settings.update` writes
   them. An empty table gets nothing: `aslms seed` inserts version 1 with all six weights.
3. CHECKs `ck_scoring_settings_partial` (NULL or > 0 and <= 1) and `ck_scoring_settings_partial_current` (a current
   row has the weight).

Downgrade: both constraints and the column are dropped. The version inserted by the upgrade stays (values are never
deleted; its other values equal the previous version's), and one audit row `scoring_settings.update` is written with
`after.migration = "0027-downgrade"`.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-26
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

MIGRATION = "0027"
ACTOR_NAME = "migration 0027"
DEFAULT_PARTIAL = Decimal("0.600")
STEP = Decimal("0.001")
KINDS = ("counsel_code", "name_pattern", "watchlist", "linked_case", "keyword")

_AUDIT = sa.text(
    "INSERT INTO audit_log (action, entity_type, entity_id, actor_name, before, after) "
    "VALUES (:action, :entity_type, :entity_id, :actor_name, CAST(:before AS jsonb), CAST(:after AS jsonb))"
)


def _audit(bind, entity_id, before, after) -> None:
    bind.execute(
        _AUDIT,
        {
            "action": "scoring_settings.update",
            "entity_type": "scoring_settings",
            "entity_id": entity_id,
            "actor_name": ACTOR_NAME,
            "before": json.dumps(before) if before is not None else None,
            "after": json.dumps(after) if after is not None else None,
        },
    )


def _f(value) -> float:
    return round(float(value), 3)


def _summary(row, partial: Decimal | None) -> dict:
    weights = {k: _f(getattr(row, f"weight_{k}")) for k in KINDS}
    if partial is not None:
        weights = {"counsel_code": weights["counsel_code"], "counsel_code_partial": _f(partial)} | {
            k: v for k, v in weights.items() if k != "counsel_code"
        }
    return {
        "version": row.version,
        "weights": weights,
        "threshold_strong": _f(row.threshold_strong),
        "threshold_possible": _f(row.threshold_possible),
    }


def partial_weight(counsel_code: Decimal, strong: Decimal, possible: Decimal) -> Decimal:
    """0.600 inside the possible band and below the counsel-code weight; otherwise the thresholds' midpoint, lowered
    to 0.001 below the counsel-code weight when needed."""
    if possible <= DEFAULT_PARTIAL < strong and DEFAULT_PARTIAL < counsel_code:
        return DEFAULT_PARTIAL
    value = ((possible + strong) / 2).quantize(STEP, rounding=ROUND_HALF_UP)
    if value >= counsel_code:
        value = counsel_code - STEP
    return value


def upgrade() -> None:
    op.add_column(
        "scoring_settings", sa.Column("weight_counsel_code_partial", sa.Numeric(4, 3), nullable=True)
    )
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT id, version, weight_counsel_code, weight_name_pattern, weight_watchlist, weight_linked_case, "
            "weight_keyword, threshold_strong, threshold_possible FROM scoring_settings WHERE is_current "
            "FOR UPDATE"
        )
    ).first()
    if row is not None:
        partial = partial_weight(
            Decimal(str(row.weight_counsel_code)),
            Decimal(str(row.threshold_strong)),
            Decimal(str(row.threshold_possible)),
        )
        reason = f"Partial counsel-code match added (design partial-code-match), partial weight {partial}"
        bind.execute(
            sa.text("UPDATE scoring_settings SET is_current = false, valid_to = now() WHERE id = :id"),
            {"id": row.id},
        )
        new_id = bind.execute(
            sa.text(
                "INSERT INTO scoring_settings (version, weight_counsel_code, weight_name_pattern, "
                "weight_watchlist, weight_linked_case, weight_keyword, weight_counsel_code_partial, "
                "threshold_strong, threshold_possible, reason, is_current, created_by, updated_by) "
                "VALUES (:version, :cc, :np, :wl, :lc, :kw, :partial, :strong, :possible, :reason, true, "
                "NULL, NULL) RETURNING id"
            ),
            {
                "version": row.version + 1,
                "cc": row.weight_counsel_code,
                "np": row.weight_name_pattern,
                "wl": row.weight_watchlist,
                "lc": row.weight_linked_case,
                "kw": row.weight_keyword,
                "partial": partial,
                "strong": row.threshold_strong,
                "possible": row.threshold_possible,
                "reason": reason,
            },
        ).scalar_one()
        after = _summary(row, partial)
        after["version"] = row.version + 1
        _audit(bind, new_id, _summary(row, None), {**after, "reason": reason, "migration": MIGRATION})
        bind.execute(
            sa.text(
                "INSERT INTO events (type, payload, dedupe_key, visibility) "
                "SELECT 'config_changed', CAST(:payload AS jsonb), :key, 'scoped' "
                "WHERE EXISTS (SELECT 1 FROM ref_event_type WHERE code = 'config_changed') "
                "ON CONFLICT (dedupe_key) DO NOTHING"
            ),
            {
                "payload": json.dumps(
                    {
                        "entity": "scoring_settings",
                        "id": str(new_id),
                        "action": "update",
                        "version": row.version + 1,
                    }
                ),
                "key": f"scoring_settings:{new_id}",
            },
        )
    op.create_check_constraint(
        op.f("ck_scoring_settings_partial"),
        "scoring_settings",
        "weight_counsel_code_partial IS NULL OR "
        "(weight_counsel_code_partial > 0 AND weight_counsel_code_partial <= 1)",
    )
    op.create_check_constraint(
        op.f("ck_scoring_settings_partial_current"),
        "scoring_settings",
        "NOT is_current OR weight_counsel_code_partial IS NOT NULL",
    )


def downgrade() -> None:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT id, version, weight_counsel_code, weight_name_pattern, weight_watchlist, weight_linked_case, "
            "weight_keyword, weight_counsel_code_partial, threshold_strong, threshold_possible "
            "FROM scoring_settings WHERE is_current"
        )
    ).first()
    op.drop_constraint(op.f("ck_scoring_settings_partial_current"), "scoring_settings", type_="check")
    op.drop_constraint(op.f("ck_scoring_settings_partial"), "scoring_settings", type_="check")
    op.drop_column("scoring_settings", "weight_counsel_code_partial")
    if row is not None:
        _audit(
            bind,
            row.id,
            _summary(row, row.weight_counsel_code_partial),
            {**_summary(row, None), "migration": f"{MIGRATION}-downgrade"},
        )
