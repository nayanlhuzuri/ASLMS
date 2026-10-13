"""0016 case stages: appeal / review outcomes and the contempt track

Design `case-stages-extension` ("Data"; docs/schema/schema.md Group 0): a reference-data migration. Seven rows go
into `ref_case_stage` with `ON CONFLICT (code) DO NOTHING`, so a database already seeded with the new `Stage`
members is left as it is; `aslms seed` carries the same labels, phases and sort orders. The rows are hard-coded
here (no application import) so the applied migration stays frozen. No table, column, type or grant changes
(`aslms_app` keeps SELECT / INSERT / UPDATE on `ref_case_stage`, 0001). The downgrade refuses while any
`case_stages` row uses one of the seven codes (legal-record history); otherwise it deletes the seven rows, so a
re-upgrade inserts them active again.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

# (code, label, phase, sort_order) — design decision 1
NEW_STAGES: tuple[tuple[str, str, str, int], ...] = (
    ("review_petition_filed", "Review petition filed", "appeal", 180),
    ("appeal_dismissed", "Appeal or review dismissed", "appeal", 190),
    ("appeal_allowed", "Appeal or review allowed", "appeal", 200),
    ("further_appeal_filed", "Further appeal filed (higher court)", "appeal", 210),
    ("complied_after_dismissal", "Complied after dismissal of appeal or review", "appeal", 220),
    ("vakalatnama_submitted", "Vakalatnama submitted", "contempt", 230),
    ("contempt_disposed", "Contempt disposed", "contempt", 240),
)
CODES = [code for code, _, _, _ in NEW_STAGES]


def upgrade() -> None:
    bind = op.get_bind()
    insert = sa.text(
        "INSERT INTO ref_case_stage (code, label, phase, sort_order, is_active) "
        "VALUES (:code, :label, :phase, :sort_order, true) ON CONFLICT (code) DO NOTHING"
    )
    for code, label, phase, sort_order in NEW_STAGES:
        bind.execute(insert, {"code": code, "label": label, "phase": phase, "sort_order": sort_order})


def downgrade() -> None:
    bind = op.get_bind()
    used = bind.execute(
        sa.text("SELECT count(*) FROM case_stages WHERE stage = ANY(:codes)"), {"codes": CODES}
    ).scalar()
    if used:
        raise RuntimeError(
            f"cannot downgrade 0016: {used} case_stages row(s) use the added stages; the stage history would be lost"
        )
    bind.execute(sa.text("DELETE FROM ref_case_stage WHERE code = ANY(:codes)"), {"codes": CODES})
