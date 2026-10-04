"""0005 case search: the derived `cases.search_vector`, its GIN index and the compact case-number index

Design `cases-api` (docs/schema/schema.md Group 3, "Data"): one SQL function `aslms_case_search_vector(case_id)`
(config `simple`, no stemming — names) builds the vector with three weights: A = party names (current
`case_parties`, the party summaries, the distinct cause-list petitioner / respondent texts), B = advocates
(current `case_advocates` names and counsel codes, `pet_advocate` / `res_advocate`, the distinct cause-list
advocate texts), C = identifiers (CNR, case number, filing number, `ref_no`). The vector is refreshed by
`services/cases.py::refresh_search_vector`, never written by hand; this revision backfills every row. No new
table, column, enum or `ref_*` code.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

SEARCH_VECTOR_FUNCTION = r"""
CREATE FUNCTION aslms_case_search_vector(p_case_id uuid) RETURNS tsvector
LANGUAGE sql STABLE AS $$
    SELECT
        setweight(to_tsvector('simple', coalesce(
            (SELECT string_agg(DISTINCT p.name, ' ')
               FROM case_parties p WHERE p.case_id = c.id AND p.is_current), '')
            || ' ' || coalesce(c.petitioner_summary, '')
            || ' ' || coalesce(c.respondent_summary, '')
            || ' ' || coalesce(
            (SELECT string_agg(DISTINCT t.txt, ' ')
               FROM (SELECT e.petitioner_text AS txt FROM causelist_entries e WHERE e.case_id = c.id
                     UNION SELECT e.respondent_text FROM causelist_entries e WHERE e.case_id = c.id) t
              WHERE t.txt IS NOT NULL), '')
        ), 'A')
        || setweight(to_tsvector('simple', coalesce(
            (SELECT string_agg(DISTINCT a.name_as_listed || ' ' || coalesce(a.counsel_code, ''), ' ')
               FROM case_advocates a WHERE a.case_id = c.id AND a.is_current), '')
            || ' ' || coalesce(c.pet_advocate, '')
            || ' ' || coalesce(c.res_advocate, '')
            || ' ' || coalesce(
            (SELECT string_agg(DISTINCT t.txt, ' ')
               FROM (SELECT e.pet_advocate_text AS txt FROM causelist_entries e WHERE e.case_id = c.id
                     UNION SELECT e.res_advocate_text FROM causelist_entries e WHERE e.case_id = c.id) t
              WHERE t.txt IS NOT NULL), '')
        ), 'B')
        || setweight(to_tsvector('simple',
            coalesce(c.cnr, '') || ' ' || coalesce(c.case_no_text, '') || ' '
            || coalesce(c.filing_no_text, '') || ' ' || coalesce(c.ref_no, '')
        ), 'C')
    FROM cases c
    WHERE c.id = p_case_id
$$;
"""


def upgrade() -> None:
    op.execute(SEARCH_VECTOR_FUNCTION)
    op.execute("ALTER FUNCTION aslms_case_search_vector(uuid) OWNER TO aslms_owner")
    op.execute("GRANT EXECUTE ON FUNCTION aslms_case_search_vector(uuid) TO aslms_app")
    op.execute("GRANT EXECUTE ON FUNCTION aslms_case_search_vector(uuid) TO aslms_readonly")
    op.create_index(
        "ix_cases_search_vector_gin", "cases", ["search_vector"], unique=False, postgresql_using="gin"
    )
    op.create_index(
        "ix_cases_case_no_compact",
        "cases",
        [sa.text(r"upper(regexp_replace(case_no_text, '\s', '', 'g'))")],
        unique=False,
    )
    op.execute("UPDATE cases SET search_vector = aslms_case_search_vector(id)")


def downgrade() -> None:
    op.drop_index("ix_cases_case_no_compact", table_name="cases")
    op.drop_index("ix_cases_search_vector_gin", table_name="cases")
    op.execute("DROP FUNCTION IF EXISTS aslms_case_search_vector(uuid)")
    op.execute("UPDATE cases SET search_vector = NULL")
