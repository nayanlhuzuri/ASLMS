"""0026 portal ui polish 2: the full user-type names, their Table 1 descriptions and a unique name index

Design `portal-ui-polish-2` ("Data"; decisions 7, 8 and 11): a reference-data migration, the next free number after
0025 (`case_workspace_admin`). Written by hand as 0016 and 0025 were: the only schema object is the unique index
`uq_ref_role_label_lower` on `lower(label)`, declared on `RefRole` too so the models and the migrations stay equal.

Upgrade: each `ref_role` label changes only while it still holds the seeded text, so a label an administrator changed
is left alone; each description is set only where it is NULL; then the index is created (the ten labels are distinct
after the updates). Downgrade: the index is dropped, each label goes back where it still holds the new text, each
description goes back to NULL where it still holds the seeded text. No table, column, type, trigger or grant changes
(`aslms_app` keeps UPDATE on reference tables, 0001). No `audit_log` row: reference-data migrations of the seed's own
labels are not audited (0016 and 0025 precedent). `aslms seed` carries the same labels and descriptions for fresh
databases (`ROLE_LABELS`, `ROLE_DESCRIPTIONS`, on insert only).

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

# (code, seeded label, new label) - hard-coded so the applied migration stays frozen; `auditor` keeps "Auditor"
LABELS: tuple[tuple[str, str, str], ...] = (
    ("super_admin", "Super admin", "Super Administrator"),
    ("state_oversight", "State oversight", "State Oversight Officer"),
    ("dept_head", "Dept head", "Head of Department"),
    ("dept_admin", "Dept admin", "Department Administrator"),
    ("dept_officer", "Dept officer", "Department Officer"),
    ("directorate_user", "Directorate user", "Directorate Officer"),
    ("referral_reviewer", "Referral reviewer", "Referral Reviewer"),
    ("standing_counsel", "Standing counsel", "Standing Counsel"),
    ("central_operator", "Central operator", "Central Operator"),
)

# (code, description) - the plan's Table 1 wording (decision 8)
DESCRIPTIONS: tuple[tuple[str, str], ...] = (
    ("super_admin", "Holds every function and manages access for the whole State."),
    ("state_oversight", "Read-only view of all cases, with the State dashboards and reports."),
    ("dept_head", "All cases of the department and its directorates, with approvals and oversight."),
    (
        "dept_admin",
        "Manages the department's users, counsel codes and keywords; reviews recommendations and claims cases.",
    ),
    (
        "dept_officer",
        "Works on allotted cases: moves the case, adds notes and documents, and receives alerts.",
    ),
    ("directorate_user", "Works on the cases of their own directorate."),
    (
        "referral_reviewer",
        "Reviews cases with a department officer's reviewing functions, without ownership or the case's movement.",
    ),
    ("standing_counsel", "Cases they appear in, with the notes and documents shared with counsel."),
    ("central_operator", "Looks after unclaimed cases and data quality."),
    ("auditor", "Read-only case records and the audit log."),
)

INDEX = "uq_ref_role_label_lower"


def upgrade() -> None:
    bind = op.get_bind()
    relabel = sa.text("UPDATE ref_role SET label = :new WHERE code = :code AND label = :old")
    for code, old, new in LABELS:
        bind.execute(relabel, {"code": code, "old": old, "new": new})
    describe = sa.text("UPDATE ref_role SET description = :text WHERE code = :code AND description IS NULL")
    for code, text in DESCRIPTIONS:
        bind.execute(describe, {"code": code, "text": text})
    op.create_index(INDEX, "ref_role", [sa.text("lower((label)::text)")], unique=True)


def downgrade() -> None:
    op.drop_index(INDEX, table_name="ref_role")
    bind = op.get_bind()
    relabel = sa.text("UPDATE ref_role SET label = :old WHERE code = :code AND label = :new")
    for code, old, new in LABELS:
        bind.execute(relabel, {"code": code, "old": old, "new": new})
    clear = sa.text("UPDATE ref_role SET description = NULL WHERE code = :code AND description = :text")
    for code, text in DESCRIPTIONS:
        bind.execute(clear, {"code": code, "text": text})
