"""0030 claim assign wording: two seeded labels read "Assign" in place of "Allot"

Design `claim-assign-wording` ("Data"; decision 8): a reference-data migration, the next free number after 0029
(`office-head-picker`). No table, column, type, trigger or grant changes, so it is written by hand as 0016 and 0025
were (autogenerate has nothing to compare). Each value changes only while it still holds the seeded text, so a
description the Super Administrator changed with Edit Name is left alone; `aslms seed` carries the same texts for
fresh databases (`EVENT_TYPE_LABELS`, `EVENT_TIMELINE_LABELS`, `ROLE_DESCRIPTIONS`). No `audit_log` row:
reference-data migrations of the seed's own labels are not audited (0016 and 0025 precedent). The codes (`allotted`,
`dept_officer`) do not change. The downgrade reverses each change under the mirror condition.

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

# (table, column, code, seeded text, new text) - hard-coded so the applied migration stays frozen
CHANGES: tuple[tuple[str, str, str, str, str], ...] = (
    ("ref_event_type", "label", "allotted", "Allotted", "Assigned"),
    ("ref_event_type", "timeline_label", "allotted", "Allotted", "Assigned"),
    (
        "ref_role",
        "description",
        "dept_officer",
        "Works on allotted cases: moves the case, adds notes and documents, and receives alerts.",
        "Works on cases assigned to them: moves the case, adds notes and documents, and receives alerts.",
    ),
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
