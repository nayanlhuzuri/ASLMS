"""0036 office kinds: six new office types under a department, and Directorate widened

Design `offices-import` ("Data"; decisions 1-3; docs/schema/schema.md Group 0 and Group 1): a reference-data
migration, the next free number after 0035 (`close-case`). Six rows go into `ref_office_kind` with
`ON CONFLICT (code) DO NOTHING`, so a database already seeded with the new `OfficeKind` members is left as it is;
`directorate` is relabelled "Directorate / Commissionerate" with its description only while it still reads
"Directorate", so a label an administrator edited is kept (the precedent of 0025 and 0030). `aslms seed` carries the
same labels, descriptions and sort orders (`OFFICE_KIND_COLUMNS`). The rows are hard-coded here (no application
import) so the applied migration stays frozen. No table, column, type, trigger or grant changes (`aslms_app` keeps
its grants on `ref_office_kind`, 0001). No `audit_log` row (the 0016 precedent).

The downgrade refuses while any `offices` row uses one of the six kinds (restore needed, runbook section 6);
otherwise it deletes the six rows and gives `directorate` back its old label while it still holds the new one.

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

# (code, label, description, sort_order) - design decision 1, the workbook's "What It Covers" text
NEW_KINDS: tuple[tuple[str, str, str, int], ...] = (
    (
        "board_corporation",
        "Board / Corporation",
        "State public sector companies, corporations, boards and federations that act in their own name.",
        41,
    ),
    (
        "statutory_authority",
        "Statutory Authority / Commission",
        "Bodies set up by law: commissions, authorities, tribunals, regulatory and statutory boards and councils.",
        42,
    ),
    (
        "society_mission",
        "Society / Mission / Project",
        "Registered societies, missions and externally aided projects.",
        43,
    ),
    ("institution", "Institution", "Universities, colleges, training and research institutes.", 44),
    ("local_body", "Local Body", "Municipal corporations and municipal boards.", 45),
    (
        "autonomous_council",
        "Autonomous Council",
        "Autonomous and territorial councils under the Sixth Schedule.",
        46,
    ),
)
CODES = [code for code, _, _, _ in NEW_KINDS]
DIRECTORATE_OLD = "Directorate"
DIRECTORATE_NEW = "Directorate / Commissionerate"
DIRECTORATE_DESCRIPTION = (
    "Heads of department under a department: directorates, commissionerates, inspectorates, controllers, "
    "registrars, police and similar headquarters."
)


def upgrade() -> None:
    bind = op.get_bind()
    insert = sa.text(
        "INSERT INTO ref_office_kind (code, label, description, sort_order, is_active) "
        "VALUES (:code, :label, :description, :sort_order, true) ON CONFLICT (code) DO NOTHING"
    )
    for code, label, description, sort_order in NEW_KINDS:
        bind.execute(
            insert, {"code": code, "label": label, "description": description, "sort_order": sort_order}
        )
    bind.execute(
        sa.text(
            "UPDATE ref_office_kind SET label = :new, description = :description "
            "WHERE code = 'directorate' AND label = :old"
        ),
        {"new": DIRECTORATE_NEW, "old": DIRECTORATE_OLD, "description": DIRECTORATE_DESCRIPTION},
    )


def downgrade() -> None:
    bind = op.get_bind()
    used = bind.execute(
        sa.text("SELECT count(*) FROM offices WHERE kind = ANY(:codes)"), {"codes": CODES}
    ).scalar()
    if used:
        raise RuntimeError(
            f"cannot downgrade 0036: {used} office(s) use the added kinds; restore a backup instead "
            "(runbook section 6)"
        )
    bind.execute(sa.text("DELETE FROM ref_office_kind WHERE code = ANY(:codes)"), {"codes": CODES})
    bind.execute(
        sa.text(
            "UPDATE ref_office_kind SET label = :old, "
            "description = CASE WHEN description = :description THEN NULL ELSE description END "
            "WHERE code = 'directorate' AND label = :new"
        ),
        {"new": DIRECTORATE_NEW, "old": DIRECTORATE_OLD, "description": DIRECTORATE_DESCRIPTION},
    )
