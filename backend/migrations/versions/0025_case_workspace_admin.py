"""0025 case workspace admin: two seeded labels in plain case words

Design `case-workspace-admin` ("Data"; decision 4): a reference-data migration, the next free number after 0024
(`assistant`). No table, column, type, trigger or grant changes, so it is written by hand as 0016 was (autogenerate
has nothing to compare). Each label changes only while it still holds the seeded text, so a label an administrator
changed is left alone; `aslms seed` carries the same labels for fresh databases (`NOTE_KIND_LABELS`,
`EVENT_TIMELINE_LABELS`). No `audit_log` row: reference-data migrations of the seed's own labels are not audited (0016
precedent). The downgrade reverses each change under the mirror condition.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

# (table, column, code, seeded text, new text) - hard-coded so the applied migration stays frozen
CHANGES: tuple[tuple[str, str, str, str, str], ...] = (
    ("ref_note_kind", "label", "file_noting", "File noting", "Office note"),
    ("ref_event_type", "timeline_label", "custody_moved", "Custody moved", "Case moved"),
)


def _relabel(frm_index: int, to_index: int) -> None:
    bind = op.get_bind()
    for change in CHANGES:
        table, column, code = change[0], change[1], change[2]
        bind.execute(
            sa.text(f"UPDATE {table} SET {column} = :new WHERE code = :code AND {column} = :old"),
            {"new": change[to_index], "old": change[frm_index], "code": code},
        )


def upgrade() -> None:
    _relabel(3, 4)


def downgrade() -> None:
    _relabel(4, 3)
