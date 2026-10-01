"""0002 acts: natural key (national_act_code, name)

The live NAPIX act master (4,677 rows, 1 Oct 2026) repeats a national act code for several acts (375 codes
carry two to four different names) and repeats names under different codes, so neither column is unique on
its own; the pair is (4,652 distinct pairs, 25 exact repeats).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-01
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_acts_national_act_code", "acts", type_="unique")
    op.drop_constraint("uq_acts_name", "acts", type_="unique")
    op.create_unique_constraint("uq_acts_national_act_code_name", "acts", ["national_act_code", "name"])
    op.create_index("ix_acts_national_act_code", "acts", ["national_act_code"])
    op.create_index("ix_acts_name", "acts", ["name"])


def downgrade() -> None:
    op.drop_index("ix_acts_name", table_name="acts")
    op.drop_index("ix_acts_national_act_code", table_name="acts")
    op.drop_constraint("uq_acts_national_act_code_name", "acts", type_="unique")
    op.create_unique_constraint("uq_acts_name", "acts", ["name"])
    op.create_unique_constraint("uq_acts_national_act_code", "acts", ["national_act_code"])
