"""0020 deployment monitoring: `aslms_readonly` joins `pg_monitor`

Design `deployment-checklist`, Part B (row 77, `deployment-monitoring`), decision 27 and "Data"; docs/schema/schema.md,
Conventions, the Roles bullet. The Prometheus postgres exporter and the ASLMS operations exporter connect as
`aslms_readonly`. The exporter reads the statistics views (`pg_stat_activity` of other roles, `pg_stat_bgwriter`,
database sizes), which need the predefined role `pg_monitor`. It gives statistics only: no table right beyond the
SELECT the role already has, no write and no DDL. No table, column, type or reference code changes, so autogenerate
found nothing. The migration runs as the cluster superuser (`init` / `migrate`), which may grant a predefined role.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-19
"""

from __future__ import annotations

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("GRANT pg_monitor TO aslms_readonly")


def downgrade() -> None:
    op.execute("REVOKE pg_monitor FROM aslms_readonly")
