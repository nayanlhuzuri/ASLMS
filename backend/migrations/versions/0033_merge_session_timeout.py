"""0033 merge session timeout: joins 0031 and 0032 into one head, no schema change

Row 169 (`session-timeout`) was built on its own branch from 0030 and holds 0031. Row 188 (`assistant-ollama`) was
built from 0030 too, merged first and applied to the dev database as 0032 on 28 Oct 2026. Neither file is edited: this
revision names both as parents so the chain has a single head. The deploy applies 0031 and then this revision to a
database at 0032. There is no schema, data or grant change, so no audit row; the downgrade does nothing.

Revision ID: 0033
Revises: 0031, 0032
Create Date: 2026-10-28
"""

from __future__ import annotations

revision = "0033"
down_revision = ("0031", "0032")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
