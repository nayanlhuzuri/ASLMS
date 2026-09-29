"""ASLMS v2 core schema (DB_STANDARD v1.2, Milestone DB-1).

Fresh history: this revision replaces 0001_phase1_core, 0002_ownership_unit and 0003_phase2_workflow, which
only ever held test data. Everything the standard fixes is here: UUID v7 keys (`uuid_generate_v7()`),
`ref_*` code sets, reference numbers, `set_updated_at()` triggers, the append-only triggers, a `class=`
comment on every table, and the three database roles with their grants. Enum types are created explicitly
so shared types are created once; the code-set columns are plain varchar with a foreign key; the foreign
keys that would form a creation cycle (users <-> offices / designations) are added after the tables.

Revision ID: 0001
Revises:
Create Date: 2026-09-29
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from aslms.core.config import get_settings

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

APPEND_ONLY = ["events", "audit_log", "case_notes", "custody_history", "case_stages"]
WITH_UPDATED_AT = [
    "acts",
    "advocates",
    "alerts",
    "assistant_conversations",
    "benches",
    "case_office_scores",
    "case_ownership",
    "case_types",
    "cases",
    "causelists",
    "counsel_codes",
    "courts",
    "custody",
    "designations",
    "districts",
    "documents",
    "job_runs",
    "next_dates",
    "office_keywords",
    "office_name_patterns",
    "office_watchlist",
    "offices",
    "orders",
    "ownership_transfers",
    "recommendations",
    "ref_alert_kind",
    "ref_case_stage",
    "ref_doc_type",
    "ref_event_type",
    "ref_note_kind",
    "ref_office_kind",
    "ref_record_type",
    "ref_request_kind",
    "ref_role",
    "requests",
    "source_failures",
    "states",
    "user_notification_preferences",
    "users",
]
CASCADE_TABLES = [
    "assistant_messages",
    "case_office_scores",
    "causelist_reconciliations",
    "digests",
    "document_text",
    "napix_call_log",
    "notifications",
    "otp_codes",
    "refresh_tokens",
    "sourcetrace_ingestions",
    "user_notification_preferences",
]
TABLE_CLASS = {
    "offices": "master",
    "designations": "master",
    "users": "master",
    "otp_codes": "derived",
    "refresh_tokens": "derived",
    "user_notification_preferences": "master",
    "next_dates": "transaction",
    "alerts": "transaction",
    "notifications": "derived",
    "digests": "derived",
    "states": "master",
    "districts": "master",
    "acts": "master",
    "advocates": "master",
    "cases": "transaction",
    "case_parties": "transaction",
    "case_advocates": "transaction",
    "case_hearings": "transaction",
    "case_acts": "transaction",
    "case_links": "transaction",
    "case_applications": "transaction",
    "case_lower_courts": "transaction",
    "case_objections": "transaction",
    "case_snapshots": "derived",
    "causelists": "transaction",
    "causelist_entries": "transaction",
    "causelist_reconciliations": "transaction",
    "documents": "transaction",
    "document_text": "transaction",
    "orders": "transaction",
    "events": "derived",
    "audit_log": "derived",
    "job_runs": "derived",
    "napix_call_log": "derived",
    "source_failures": "derived",
    "counsel_codes": "master",
    "office_name_patterns": "master",
    "office_keywords": "master",
    "office_watchlist": "master",
    "case_office_scores": "derived",
    "recommendations": "transaction",
    "case_ownership": "transaction",
    "ownership_transfers": "transaction",
    "courts": "master",
    "benches": "master",
    "case_types": "master",
    "master_sync_runs": "derived",
    "ref_role": "reference",
    "ref_office_kind": "reference",
    "ref_case_stage": "reference",
    "ref_request_kind": "reference",
    "ref_note_kind": "reference",
    "ref_doc_type": "reference",
    "ref_alert_kind": "reference",
    "ref_event_type": "reference",
    "ref_record_type": "reference",
    "ref_sequences": "derived",
    "sourcetrace_ingestions": "derived",
    "assistant_conversations": "transaction",
    "assistant_messages": "transaction",
    "custody": "transaction",
    "custody_history": "derived",
    "requests": "transaction",
    "request_messages": "transaction",
    "case_stages": "transaction",
    "case_notes": "transaction",
    "case_note_attachments": "transaction",
}

FUNCTIONS = """
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- DB_STANDARD Appendix A: UUID v7 (RFC 9562), time-ordered. PostgreSQL 18: replace the body with uuidv7().
CREATE OR REPLACE FUNCTION uuid_generate_v7() RETURNS uuid
LANGUAGE sql VOLATILE PARALLEL SAFE AS $$
  SELECT encode(
    set_bit(set_bit(
      overlay(uuid_send(gen_random_uuid())
              placing substring(int8send((extract(epoch from clock_timestamp())*1000)::bigint) from 3)
              from 1 for 6),
      52, 1), 53, 1), 'hex')::uuid;
$$;

-- DB_STANDARD Appendix B
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END $$;

-- Append-only tables (ground rule 3): the database itself refuses UPDATE and DELETE.
CREATE OR REPLACE FUNCTION aslms_forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME; END $$;
"""


def _q(value: str) -> str:
    return value.replace("'", "''")


def _roles_and_grants() -> None:
    """DB_STANDARD §8. Roles are cluster-wide, so they are created only if absent; passwords come from
    ASLMS_APP_PASSWORD / ASLMS_READONLY_PASSWORD (laptop defaults in .env.example)."""
    s = get_settings()
    app_pw = _q(s.aslms_app_password.get_secret_value())
    ro_pw = _q(s.aslms_readonly_password.get_secret_value())
    op.execute(
        f"""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aslms_owner') THEN
            CREATE ROLE aslms_owner NOLOGIN; END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aslms_app') THEN
            CREATE ROLE aslms_app LOGIN PASSWORD '{app_pw}'; END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aslms_readonly') THEN
            CREATE ROLE aslms_readonly LOGIN PASSWORD '{ro_pw}'; END IF;
        END $$
        """
    )
    op.execute("GRANT aslms_owner TO CURRENT_USER")
    op.execute(f"GRANT CONNECT ON DATABASE {op.get_bind().engine.url.database} TO aslms_app, aslms_readonly")
    op.execute("GRANT USAGE ON SCHEMA public TO aslms_app, aslms_readonly")
    op.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO aslms_owner")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO aslms_readonly")
    op.execute("GRANT EXECUTE ON FUNCTION uuid_generate_v7() TO aslms_app, aslms_readonly")
    for table in TABLE_CLASS:
        rights = "SELECT, INSERT" if table in APPEND_ONLY else "SELECT, INSERT, UPDATE"
        if table in CASCADE_TABLES:
            rights += ", DELETE"
        op.execute(f"GRANT {rights} ON {table} TO aslms_app")


def upgrade() -> None:
    bind = op.get_bind()
    op.execute(FUNCTIONS)
    postgresql.ENUM("petitioner", "respondent", "extra", name="advocate_side").create(bind, checkfirst=True)
    postgresql.ENUM("critical", "high", "normal", name="alert_severity").create(bind, checkfirst=True)
    postgresql.ENUM("open", "acknowledged", "done", "expired", name="alert_status").create(
        bind, checkfirst=True
    )
    postgresql.ENUM("pending", "disposed", "unknown", name="case_status").create(bind, checkfirst=True)
    postgresql.ENUM("napix", "ghc_website", "local_dir", name="causelist_source").create(
        bind, checkfirst=True
    )
    postgresql.ENUM("case", "research", name="conversation_scope").create(bind, checkfirst=True)
    postgresql.ENUM("hc", "dc", name="court_level").create(bind, checkfirst=True)
    postgresql.ENUM(
        "claim",
        "allot",
        "transfer",
        "request_sent",
        "request_answered",
        "request_withdrawn",
        "handover",
        "release",
        name="custody_reason",
    ).create(bind, checkfirst=True)
    postgresql.ENUM("none", "daily", name="digest_mode").create(bind, checkfirst=True)
    postgresql.ENUM("court_record", "court_filing", "internal", name="doc_group").create(
        bind, checkfirst=True
    )
    postgresql.ENUM(
        "court_order", "causelist", "court_filing", "internal", "other", name="document_kind"
    ).create(bind, checkfirst=True)
    postgresql.ENUM("pending", "downloaded", "not_available", "failed", name="download_status").create(
        bind, checkfirst=True
    )
    postgresql.ENUM("napix_details", "pdf_parse", name="entry_source").create(bind, checkfirst=True)
    postgresql.ENUM("tracking_card", "scoped", name="event_visibility").create(bind, checkfirst=True)
    postgresql.ENUM(
        "napix", "ghc_pdf", "order_download", "antivirus", "sourcetrace", "email", "sms", name="failure_kind"
    ).create(bind, checkfirst=True)
    postgresql.ENUM("pending", "fetched", "not_available", "failed", name="fetch_status").create(
        bind, checkfirst=True
    )
    postgresql.ENUM("causelist", "search", "discovery", "link", name="first_seen_source").create(
        bind, checkfirst=True
    )
    postgresql.ENUM(
        "cnr_history", "show_business", "causelist", "current_status", name="hearing_source"
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "daily_cycle",
        "status_refresh",
        "full_refresh",
        "order_download",
        "discovery",
        "master_sync",
        "notifications",
        "napix_check",
        name="job_kind",
    ).create(bind, checkfirst=True)
    postgresql.ENUM("running", "succeeded", "partial", "failed", name="job_status").create(
        bind, checkfirst=True
    )
    postgresql.ENUM(
        "main_matter", "connected", "ia_in", "appeal_of", "contempt_of", "with", name="link_kind"
    ).create(bind, checkfirst=True)
    postgresql.ENUM("cnr_api", "causelist", "manual", name="link_source").create(bind, checkfirst=True)
    postgresql.ENUM("daily", "supplementary", "lawazima", "vacation", "other", name="list_type").create(
        bind, checkfirst=True
    )
    postgresql.ENUM("appellate", "trial", name="lower_court_level").create(bind, checkfirst=True)
    postgresql.ENUM("state", "district", "bench", "case_type", "act", name="master_kind").create(
        bind, checkfirst=True
    )
    postgresql.ENUM(
        "causelist", "current_status", "order_specific", "order_period", "manual", name="next_date_source"
    ).create(bind, checkfirst=True)
    postgresql.ENUM("case_scope", "counsel_shared", "private_to_office", name="note_visibility").create(
        bind, checkfirst=True
    )
    postgresql.ENUM("in_app", "email", "sms", name="notification_channel").create(bind, checkfirst=True)
    postgresql.ENUM("queued", "sent", "failed", "read", name="notification_status").create(
        bind, checkfirst=True
    )
    postgresql.ENUM("interim", "final", "judgment", name="order_kind").create(bind, checkfirst=True)
    postgresql.ENUM("login", "password_reset", "new_device", name="otp_purpose").create(bind, checkfirst=True)
    postgresql.ENUM("primary", "watcher", name="ownership_role").create(bind, checkfirst=True)
    postgresql.ENUM("active", "transferred", "released", name="ownership_status").create(
        bind, checkfirst=True
    )
    postgresql.ENUM("pending", "parsed", "partial", "failed", "not_applicable", name="parse_status").create(
        bind, checkfirst=True
    )
    postgresql.ENUM("petitioner", "respondent", "extra", name="party_role").create(bind, checkfirst=True)
    postgresql.ENUM("exact", "prefix", "regex", name="pattern_kind").create(bind, checkfirst=True)
    postgresql.ENUM(
        "cause_list", "discovery", "suggestion", "link_history", "search", name="recommendation_origin"
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "recommended", "claimed", "dismissed", "suggested_elsewhere", "expired", name="recommendation_status"
    ).create(bind, checkfirst=True)
    postgresql.ENUM("open", "answered", "withdrawn", name="request_status").create(bind, checkfirst=True)
    postgresql.ENUM("resolved", "provisional", "unresolved", name="resolution_status").create(
        bind, checkfirst=True
    )
    postgresql.ENUM("none", "pending", "confirmed", "rejected", name="review_status").create(
        bind, checkfirst=True
    )
    postgresql.ENUM("high", "medium", name="score_band").create(bind, checkfirst=True)
    postgresql.ENUM("cnr_api", "current_status", name="snapshot_source").create(bind, checkfirst=True)
    postgresql.ENUM("not_applicable", "pending", "ingested", "failed", name="sourcetrace_status").create(
        bind, checkfirst=True
    )
    postgresql.ENUM("pending", "done", "failed", "not_applicable", name="text_status").create(
        bind, checkfirst=True
    )
    postgresql.ENUM("requested", "accepted", "declined", "withdrawn", name="transfer_status").create(
        bind, checkfirst=True
    )
    postgresql.ENUM(
        "pending", "clean", "infected", "failed", "not_applicable", name="virus_scan_status"
    ).create(bind, checkfirst=True)
    postgresql.ENUM("case_scope", "counsel_shared", "private_to_office", name="visibility").create(
        bind, checkfirst=True
    )

    op.create_table(
        "acts",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("national_act_code", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_acts")),
        sa.UniqueConstraint("name", name=op.f("uq_acts_name")),
        sa.UniqueConstraint("national_act_code", name=op.f("uq_acts_national_act_code")),
        comment="class=master",
    )
    op.create_table(
        "advocates",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("bar_reg_no", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("name_normalised", sa.String(length=300), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_advocates")),
        sa.UniqueConstraint("bar_reg_no", name=op.f("uq_advocates_bar_reg_no")),
        comment="class=master",
    )
    op.create_index("ix_advocates_name_normalised", "advocates", ["name_normalised"], unique=False)
    op.create_table(
        "courts",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("est_code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("state_code", sa.String(length=8), nullable=False),
        sa.Column("bench_location", sa.String(length=200), nullable=True),
        sa.Column(
            "court_level", postgresql.ENUM("hc", "dc", name="court_level", create_type=False), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_courts")),
        sa.UniqueConstraint("est_code", name=op.f("uq_courts_est_code")),
        comment="class=master",
    )
    op.create_table(
        "designations",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("valid_from", sa.Date(), server_default=sa.text("CURRENT_DATE"), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_designations_created_by_users"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_designations_updated_by_users"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_designations")),
        sa.UniqueConstraint("code", name=op.f("uq_designations_code")),
        comment="class=master",
    )
    op.create_table(
        "job_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column(
            "job",
            postgresql.ENUM(
                "daily_cycle",
                "status_refresh",
                "full_refresh",
                "order_download",
                "discovery",
                "master_sync",
                "notifications",
                "napix_check",
                name="job_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("run_date", sa.Date(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "running", "succeeded", "partial", "failed", name="job_status", create_type=False
            ),
            server_default="running",
            nullable=False,
        ),
        sa.Column("counters", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_runs")),
        comment="class=derived",
    )
    op.create_index(
        "ix_job_runs_job_started", "job_runs", ["job", sa.literal_column("started_at DESC")], unique=False
    )
    op.create_table(
        "master_sync_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column(
            "master",
            postgresql.ENUM(
                "state", "district", "bench", "case_type", "act", name="master_kind", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_master_sync_runs")),
        comment="class=derived",
    )
    op.create_table(
        "ref_alert_kind",
        sa.Column("default_severity", sa.String(length=20), server_default="normal", nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_ref_alert_kind")),
        comment="class=reference",
    )
    op.create_table(
        "ref_case_stage",
        sa.Column("phase", sa.String(length=20), server_default="main", nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_ref_case_stage")),
        comment="class=reference",
    )
    op.create_table(
        "ref_doc_type",
        sa.Column("doc_group", sa.String(length=20), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_ref_doc_type")),
        comment="class=reference",
    )
    op.create_table(
        "ref_event_type",
        sa.Column("timeline_label", sa.String(length=120), nullable=False),
        sa.Column("icon_key", sa.String(length=40), nullable=True),
        sa.Column("is_tracking_card", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_ref_event_type")),
        comment="class=reference",
    )
    op.create_table(
        "ref_note_kind",
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_ref_note_kind")),
        comment="class=reference",
    )
    op.create_table(
        "ref_office_kind",
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_ref_office_kind")),
        comment="class=reference",
    )
    op.create_table(
        "ref_record_type",
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_ref_record_type")),
        comment="class=reference",
    )
    op.create_table(
        "ref_request_kind",
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_ref_request_kind")),
        comment="class=reference",
    )
    op.create_table(
        "ref_role",
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_ref_role")),
        comment="class=reference",
    )
    op.create_table(
        "source_failures",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "napix",
                "ghc_pdf",
                "order_download",
                "antivirus",
                "sourcetrace",
                "email",
                "sms",
                name="failure_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("ref", sa.String(length=300), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="1", nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_failures")),
        comment="class=derived",
    )
    op.create_index(
        "uq_source_failures_open",
        "source_failures",
        ["kind", "ref"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.create_table(
        "states",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("lgd_code", sa.Integer(), nullable=True),
        sa.Column("ecourts_code", sa.String(length=8), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_states")),
        sa.UniqueConstraint("ecourts_code", name=op.f("uq_states_ecourts_code")),
        sa.UniqueConstraint("lgd_code", name=op.f("uq_states_lgd_code")),
        sa.UniqueConstraint("name", name=op.f("uq_states_name")),
        comment="class=master",
    )
    op.create_table(
        "benches",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("court_id", sa.UUID(), nullable=False),
        sa.Column("bench_id", sa.String(length=32), nullable=False),
        sa.Column("judge_names", sa.Text(), nullable=True),
        sa.Column("bench_type", sa.String(length=64), nullable=True),
        sa.Column("first_seen", sa.Date(), nullable=False),
        sa.Column("last_seen", sa.Date(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["court_id"], ["courts.id"], name=op.f("fk_benches_court_id_courts"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_benches")),
        sa.UniqueConstraint("court_id", "bench_id", name=op.f("uq_benches_court_id_bench_id")),
        comment="class=master",
    )
    op.create_index(op.f("ix_benches_court_id"), "benches", ["court_id"], unique=False)
    op.create_table(
        "case_types",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("court_id", sa.UUID(), nullable=False),
        sa.Column("case_type_code", sa.Integer(), nullable=False),
        sa.Column("type_name", sa.String(length=64), nullable=False),
        sa.Column("full_name", sa.String(length=300), nullable=True),
        sa.Column("aliases", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["court_id"], ["courts.id"], name=op.f("fk_case_types_court_id_courts"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_types")),
        sa.UniqueConstraint("court_id", "case_type_code", name=op.f("uq_case_types_court_id_case_type_code")),
        comment="class=master",
    )
    op.create_index(op.f("ix_case_types_court_id"), "case_types", ["court_id"], unique=False)
    op.create_table(
        "districts",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("state_id", sa.UUID(), nullable=False),
        sa.Column("lgd_code", sa.Integer(), nullable=True),
        sa.Column("ecourts_code", sa.String(length=16), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["state_id"], ["states.id"], name=op.f("fk_districts_state_id_states"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_districts")),
        sa.UniqueConstraint("lgd_code", name=op.f("uq_districts_lgd_code")),
        sa.UniqueConstraint("state_id", "name", name=op.f("uq_districts_state_id_name")),
        comment="class=master",
    )
    op.create_index(op.f("ix_districts_state_id"), "districts", ["state_id"], unique=False)
    op.create_table(
        "napix_call_log",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("api", sa.String(length=120), nullable=False),
        sa.Column("params_sha256", sa.String(length=64), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("napix_status", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("job_run_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_run_id"],
            ["job_runs.id"],
            name=op.f("fk_napix_call_log_job_run_id_job_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_napix_call_log")),
        comment="class=derived",
    )
    op.create_index(
        "ix_napix_call_log_called_at", "napix_call_log", [sa.literal_column("called_at DESC")], unique=False
    )
    op.create_index(op.f("ix_napix_call_log_job_run_id"), "napix_call_log", ["job_run_id"], unique=False)
    op.create_table(
        "offices",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("path", sa.String(length=400), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("valid_from", sa.Date(), server_default=sa.text("CURRENT_DATE"), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_offices_created_by_users"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["kind"],
            ["ref_office_kind.code"],
            name=op.f("fk_offices_kind_ref_office_kind"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["offices.id"], name=op.f("fk_offices_parent_id_offices"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_offices_updated_by_users"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_offices")),
        sa.UniqueConstraint("code", name=op.f("uq_offices_code")),
        comment="class=master",
    )
    op.create_index(op.f("ix_offices_path"), "offices", ["path"], unique=False)
    op.create_table(
        "ref_sequences",
        sa.Column("office_code", sa.String(length=20), nullable=False),
        sa.Column("record_type", sa.String(length=10), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("last_value", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["record_type"],
            ["ref_record_type.code"],
            name=op.f("fk_ref_sequences_record_type_ref_record_type"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("office_code", "record_type", "year", name=op.f("pk_ref_sequences")),
        comment="class=derived",
    )
    op.create_table(
        "cases",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("cnr", sa.String(length=16), nullable=True),
        sa.Column("court_id", sa.UUID(), nullable=False),
        sa.Column("case_type_id", sa.UUID(), nullable=True),
        sa.Column("case_type_text", sa.String(length=64), nullable=True),
        sa.Column("reg_no", sa.Integer(), nullable=True),
        sa.Column("reg_year", sa.Integer(), nullable=True),
        sa.Column("case_no_text", sa.String(length=120), nullable=True),
        sa.Column("filing_case_type_id", sa.UUID(), nullable=True),
        sa.Column("filing_no_text", sa.String(length=120), nullable=True),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("registration_date", sa.Date(), nullable=True),
        sa.Column("date_first_list", sa.Date(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM("pending", "disposed", "unknown", name="case_status", create_type=False),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column("disposal_date", sa.Date(), nullable=True),
        sa.Column("disposal_nature", sa.String(length=200), nullable=True),
        sa.Column("disposal_type", sa.String(length=200), nullable=True),
        sa.Column("short_order", sa.Text(), nullable=True),
        sa.Column("date_filing_disp", sa.Date(), nullable=True),
        sa.Column("reason_for_rej", sa.Text(), nullable=True),
        sa.Column("next_hearing_date", sa.Date(), nullable=True),
        sa.Column("next_purpose", sa.String(length=300), nullable=True),
        sa.Column("last_hearing_date", sa.Date(), nullable=True),
        sa.Column("bench_id", sa.UUID(), nullable=True),
        sa.Column("coram", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=300), nullable=True),
        sa.Column("sub_category", sa.String(length=300), nullable=True),
        sa.Column("judicial_branch", sa.String(length=200), nullable=True),
        sa.Column("state_id", sa.UUID(), nullable=True),
        sa.Column("district_id", sa.UUID(), nullable=True),
        sa.Column("fir_no", sa.String(length=64), nullable=True),
        sa.Column("fir_year", sa.Integer(), nullable=True),
        sa.Column("police_station", sa.String(length=200), nullable=True),
        sa.Column("petitioner_summary", sa.Text(), nullable=True),
        sa.Column("respondent_summary", sa.Text(), nullable=True),
        sa.Column("pet_advocate", sa.Text(), nullable=True),
        sa.Column("res_advocate", sa.Text(), nullable=True),
        sa.Column("is_provisional", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_tracked", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "first_seen_source",
            postgresql.ENUM(
                "causelist", "search", "discovery", "link", name="first_seen_source", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("last_full_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("merged_into_case_id", sa.UUID(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ref_no", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(
            ["bench_id"], ["benches.id"], name=op.f("fk_cases_bench_id_benches"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_type_id"],
            ["case_types.id"],
            name=op.f("fk_cases_case_type_id_case_types"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["court_id"], ["courts.id"], name=op.f("fk_cases_court_id_courts"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["district_id"],
            ["districts.id"],
            name=op.f("fk_cases_district_id_districts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["filing_case_type_id"],
            ["case_types.id"],
            name=op.f("fk_cases_filing_case_type_id_case_types"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["merged_into_case_id"],
            ["cases.id"],
            name=op.f("fk_cases_merged_into_case_id_cases"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["state_id"], ["states.id"], name=op.f("fk_cases_state_id_states"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cases")),
        sa.UniqueConstraint("cnr", name=op.f("uq_cases_cnr")),
        sa.UniqueConstraint("ref_no", name=op.f("uq_cases_ref_no")),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_cases_bench_id"), "cases", ["bench_id"], unique=False)
    op.create_index(op.f("ix_cases_case_type_id"), "cases", ["case_type_id"], unique=False)
    op.create_index(op.f("ix_cases_court_id"), "cases", ["court_id"], unique=False)
    op.create_index(
        "ix_cases_court_type_no_year",
        "cases",
        ["court_id", "case_type_id", "reg_no", "reg_year"],
        unique=False,
    )
    op.create_index(op.f("ix_cases_district_id"), "cases", ["district_id"], unique=False)
    op.create_index("ix_cases_next_hearing", "cases", ["next_hearing_date"], unique=False)
    op.create_index(
        "ix_cases_search_vector", "cases", ["search_vector"], unique=False, postgresql_using="gin"
    )
    op.create_table(
        "counsel_codes",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column("weight", sa.Numeric(precision=4, scale=3), server_default="0.950", nullable=False),
        sa.Column("is_generic_state", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_counsel_codes_created_by_users"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["office_id"],
            ["offices.id"],
            name=op.f("fk_counsel_codes_office_id_offices"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_counsel_codes_updated_by_users"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_counsel_codes")),
        sa.UniqueConstraint("code", name=op.f("uq_counsel_codes_code")),
        comment="class=master",
    )
    op.create_index(op.f("ix_counsel_codes_office_id"), "counsel_codes", ["office_id"], unique=False)
    op.create_table(
        "office_keywords",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column("keyword", sa.String(length=200), nullable=False),
        sa.Column("weight", sa.Numeric(precision=4, scale=3), server_default="0.400", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_office_keywords_created_by_users"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["office_id"],
            ["offices.id"],
            name=op.f("fk_office_keywords_office_id_offices"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_office_keywords_updated_by_users"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_office_keywords")),
        sa.UniqueConstraint("office_id", "keyword", name=op.f("uq_office_keywords_office_id_keyword")),
        comment="class=master",
    )
    op.create_index(op.f("ix_office_keywords_office_id"), "office_keywords", ["office_id"], unique=False)
    op.create_table(
        "office_name_patterns",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column("pattern", sa.String(length=300), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM("exact", "prefix", "regex", name="pattern_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("weight", sa.Numeric(precision=4, scale=3), server_default="0.800", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_office_name_patterns_created_by_users"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["office_id"],
            ["offices.id"],
            name=op.f("fk_office_name_patterns_office_id_offices"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_office_name_patterns_updated_by_users"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_office_name_patterns")),
        sa.UniqueConstraint("office_id", "pattern", name=op.f("uq_office_name_patterns_office_id_pattern")),
        comment="class=master",
    )
    op.create_index(
        op.f("ix_office_name_patterns_office_id"), "office_name_patterns", ["office_id"], unique=False
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("mobile", sa.String(length=20), nullable=True),
        sa.Column("password_hash", sa.String(length=300), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("designation", sa.String(length=200), nullable=True),
        sa.Column("designation_id", sa.UUID(), nullable=True),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("must_confirm_profile", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_users_created_by_users"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["designation_id"],
            ["designations.id"],
            name=op.f("fk_users_designation_id_designations"),
            ondelete="RESTRICT",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["office_id"], ["offices.id"], name=op.f("fk_users_office_id_offices"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["role"], ["ref_role.code"], name=op.f("fk_users_role_ref_role"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_users_updated_by_users"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        comment="class=master",
    )
    op.create_index(op.f("ix_users_designation_id"), "users", ["designation_id"], unique=False)
    op.create_index(op.f("ix_users_office_id"), "users", ["office_id"], unique=False)
    op.create_table(
        "assistant_conversations",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column(
            "scope",
            postgresql.ENUM("case", "research", name="conversation_scope", create_type=False),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_assistant_conversations_case_id_cases"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_assistant_conversations_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_conversations")),
        comment="class=transaction",
    )
    op.create_index(
        "ix_assistant_conversations_user_case",
        "assistant_conversations",
        ["user_id", "case_id"],
        unique=False,
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_log_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_audit_log_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
        comment="class=derived",
    )
    op.create_index(
        "ix_audit_log_actor_created",
        "audit_log",
        ["actor_user_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_audit_log_case_created",
        "audit_log",
        ["case_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"], unique=False)
    op.create_table(
        "case_acts",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("act_name_as_listed", sa.String(length=300), nullable=False),
        sa.Column("act_id", sa.UUID(), nullable=True),
        sa.Column("national_act_code", sa.String(length=32), nullable=True),
        sa.Column("section", sa.String(length=200), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["act_id"], ["acts.id"], name=op.f("fk_case_acts_act_id_acts"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_case_acts_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_acts")),
        sa.UniqueConstraint(
            "case_id",
            "act_name_as_listed",
            "section",
            name=op.f("uq_case_acts_case_id_act_name_as_listed_section"),
        ),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_case_acts_act_id"), "case_acts", ["act_id"], unique=False)
    op.create_index(op.f("ix_case_acts_case_id"), "case_acts", ["case_id"], unique=False)
    op.create_table(
        "case_advocates",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column(
            "side",
            postgresql.ENUM("petitioner", "respondent", "extra", name="advocate_side", create_type=False),
            nullable=False,
        ),
        sa.Column("name_as_listed", sa.Text(), nullable=False),
        sa.Column("advocate_id", sa.UUID(), nullable=True),
        sa.Column("bar_reg_no", sa.String(length=64), nullable=True),
        sa.Column("counsel_code", sa.String(length=64), nullable=True),
        sa.Column("is_current", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["advocate_id"],
            ["advocates.id"],
            name=op.f("fk_case_advocates_advocate_id_advocates"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_case_advocates_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_advocates")),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_case_advocates_advocate_id"), "case_advocates", ["advocate_id"], unique=False)
    op.create_index(op.f("ix_case_advocates_case_id"), "case_advocates", ["case_id"], unique=False)
    op.create_index("ix_case_advocates_counsel_code", "case_advocates", ["counsel_code"], unique=False)
    op.create_table(
        "case_applications",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("ia_number", sa.String(length=64), nullable=False),
        sa.Column("party_name", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_case_applications_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_applications")),
        sa.UniqueConstraint("case_id", "ia_number", name=op.f("uq_case_applications_case_id_ia_number")),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_case_applications_case_id"), "case_applications", ["case_id"], unique=False)
    op.create_table(
        "case_hearings",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("purpose", sa.String(length=300), server_default="", nullable=False),
        sa.Column("bench_text", sa.Text(), nullable=True),
        sa.Column("next_date", sa.Date(), nullable=True),
        sa.Column("business_text", sa.Text(), nullable=True),
        sa.Column(
            "source",
            postgresql.ENUM(
                "cnr_history",
                "show_business",
                "causelist",
                "current_status",
                name="hearing_source",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_case_hearings_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_hearings")),
        sa.UniqueConstraint(
            "case_id", "business_date", "purpose", name=op.f("uq_case_hearings_case_id_business_date_purpose")
        ),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_case_hearings_case_id"), "case_hearings", ["case_id"], unique=False)
    op.create_table(
        "case_links",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("from_case_id", sa.UUID(), nullable=False),
        sa.Column("to_case_id", sa.UUID(), nullable=True),
        sa.Column("to_case_no_text", sa.String(length=120), nullable=False),
        sa.Column("to_cnr", sa.String(length=16), nullable=True),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "main_matter",
                "connected",
                "ia_in",
                "appeal_of",
                "contempt_of",
                "with",
                name="link_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "source",
            postgresql.ENUM("cnr_api", "causelist", "manual", name="link_source", create_type=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["from_case_id"], ["cases.id"], name=op.f("fk_case_links_from_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["to_case_id"], ["cases.id"], name=op.f("fk_case_links_to_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_links")),
        sa.UniqueConstraint(
            "from_case_id",
            "to_case_no_text",
            "kind",
            name=op.f("uq_case_links_from_case_id_to_case_no_text_kind"),
        ),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_case_links_from_case_id"), "case_links", ["from_case_id"], unique=False)
    op.create_index(op.f("ix_case_links_to_case_id"), "case_links", ["to_case_id"], unique=False)
    op.create_table(
        "case_lower_courts",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column(
            "level",
            postgresql.ENUM("appellate", "trial", name="lower_court_level", create_type=False),
            nullable=False,
        ),
        sa.Column("court_name", sa.Text(), nullable=True),
        sa.Column("case_no_text", sa.String(length=120), nullable=True),
        sa.Column("decision_date", sa.Date(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_case_lower_courts_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_lower_courts")),
        sa.UniqueConstraint("case_id", "level", name=op.f("uq_case_lower_courts_case_id_level")),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_case_lower_courts_case_id"), "case_lower_courts", ["case_id"], unique=False)
    op.create_table(
        "case_objections",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("objection", sa.Text(), nullable=True),
        sa.Column("scrutiny_date", sa.Date(), nullable=False),
        sa.Column("compliance_by_date", sa.Date(), nullable=True),
        sa.Column("receipt_date", sa.Date(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_case_objections_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_objections")),
        sa.UniqueConstraint(
            "case_id", "scrutiny_date", name=op.f("uq_case_objections_case_id_scrutiny_date")
        ),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_case_objections_case_id"), "case_objections", ["case_id"], unique=False)
    op.create_table(
        "case_office_scores",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column("score", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("signals", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("engine_version", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_case_office_scores_case_id_cases"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["office_id"],
            ["offices.id"],
            name=op.f("fk_case_office_scores_office_id_offices"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_office_scores")),
        sa.UniqueConstraint("case_id", "office_id", name=op.f("uq_case_office_scores_case_id_office_id")),
        comment="class=derived",
    )
    op.create_index(op.f("ix_case_office_scores_case_id"), "case_office_scores", ["case_id"], unique=False)
    op.create_index(
        op.f("ix_case_office_scores_office_id"), "case_office_scores", ["office_id"], unique=False
    )
    op.create_index(
        "ix_case_office_scores_office_score", "case_office_scores", ["office_id", "score"], unique=False
    )
    op.create_table(
        "case_ownership",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM("primary", "watcher", name="ownership_role", create_type=False),
            nullable=False,
        ),
        sa.Column("officer_user_id", sa.UUID(), nullable=True),
        sa.Column("unit_office_id", sa.UUID(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM("active", "transferred", "released", name="ownership_status", create_type=False),
            server_default="active",
            nullable=False,
        ),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_case_ownership_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_case_ownership_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["office_id"],
            ["offices.id"],
            name=op.f("fk_case_ownership_office_id_offices"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["officer_user_id"],
            ["users.id"],
            name=op.f("fk_case_ownership_officer_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["unit_office_id"],
            ["offices.id"],
            name=op.f("fk_case_ownership_unit_office_id_offices"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_ownership")),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_case_ownership_case_id"), "case_ownership", ["case_id"], unique=False)
    op.create_index(op.f("ix_case_ownership_office_id"), "case_ownership", ["office_id"], unique=False)
    op.create_index(
        "ix_case_ownership_office_status", "case_ownership", ["office_id", "status"], unique=False
    )
    op.create_index(
        op.f("ix_case_ownership_officer_user_id"), "case_ownership", ["officer_user_id"], unique=False
    )
    op.create_index(
        op.f("ix_case_ownership_unit_office_id"), "case_ownership", ["unit_office_id"], unique=False
    )
    op.create_index(
        "uq_case_ownership_active_office",
        "case_ownership",
        ["case_id", "office_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "uq_case_ownership_one_primary",
        "case_ownership",
        ["case_id"],
        unique=True,
        postgresql_where=sa.text("role = 'primary' AND status = 'active'"),
    )
    op.create_table(
        "case_parties",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM("petitioner", "respondent", "extra", name="party_role", create_type=False),
            nullable=False,
        ),
        sa.Column("party_no", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_normalised", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("has_legal_heir", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_case_parties_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_parties")),
        sa.UniqueConstraint(
            "case_id", "role", "party_no", name=op.f("uq_case_parties_case_id_role_party_no")
        ),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_case_parties_case_id"), "case_parties", ["case_id"], unique=False)
    op.create_index("ix_case_parties_name_normalised", "case_parties", ["name_normalised"], unique=False)
    op.create_table(
        "case_snapshots",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column(
            "source",
            postgresql.ENUM("cnr_api", "current_status", name="snapshot_source", create_type=False),
            nullable=False,
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_case_snapshots_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_snapshots")),
        sa.UniqueConstraint(
            "case_id", "payload_sha256", name=op.f("uq_case_snapshots_case_id_payload_sha256")
        ),
        comment="class=derived",
    )
    op.create_index(
        "ix_case_snapshots_case_fetched",
        "case_snapshots",
        ["case_id", sa.literal_column("fetched_at DESC")],
        unique=False,
    )
    op.create_index(op.f("ix_case_snapshots_case_id"), "case_snapshots", ["case_id"], unique=False)
    op.create_table(
        "case_stages",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("response_mode", sa.String(length=32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_case_stages_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_case_stages_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["office_id"], ["offices.id"], name=op.f("fk_case_stages_office_id_offices"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["stage"],
            ["ref_case_stage.code"],
            name=op.f("fk_case_stages_stage_ref_case_stage"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_stages")),
        comment="class=transaction",
    )
    op.create_index(
        "ix_case_stages_case_created",
        "case_stages",
        ["case_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "digests",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("digest_date", sa.Date(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alert_ids", postgresql.ARRAY(sa.UUID()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_digests_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_digests")),
        sa.UniqueConstraint("user_id", "digest_date", name=op.f("uq_digests_user_id_digest_date")),
        comment="class=derived",
    )
    op.create_index(op.f("ix_digests_user_id"), "digests", ["user_id"], unique=False)
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=400), nullable=False),
        sa.Column("mime", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("original_filename", sa.String(length=300), nullable=True),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "court_order",
                "causelist",
                "court_filing",
                "internal",
                "other",
                name="document_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("doc_type", sa.String(length=40), nullable=False),
        sa.Column(
            "doc_group",
            postgresql.ENUM("court_record", "court_filing", "internal", name="doc_group", create_type=False),
            nullable=False,
        ),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("doc_date", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "visibility",
            postgresql.ENUM(
                "case_scope", "counsel_shared", "private_to_office", name="visibility", create_type=False
            ),
            server_default="case_scope",
            nullable=False,
        ),
        sa.Column("office_id", sa.UUID(), nullable=True),
        sa.Column(
            "virus_scan_status",
            postgresql.ENUM(
                "pending",
                "clean",
                "infected",
                "failed",
                "not_applicable",
                name="virus_scan_status",
                create_type=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "text_status",
            postgresql.ENUM(
                "pending", "done", "failed", "not_applicable", name="text_status", create_type=False
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("text_extracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "sourcetrace_status",
            postgresql.ENUM(
                "not_applicable",
                "pending",
                "ingested",
                "failed",
                name="sourcetrace_status",
                create_type=False,
            ),
            server_default="not_applicable",
            nullable=False,
        ),
        sa.Column("sourcetrace_ref", sa.String(length=200), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ref_no", sa.String(length=40), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_documents_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_documents_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["doc_type"],
            ["ref_doc_type.code"],
            name=op.f("fk_documents_doc_type_ref_doc_type"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["office_id"], ["offices.id"], name=op.f("fk_documents_office_id_offices"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("ref_no", name=op.f("uq_documents_ref_no")),
        sa.UniqueConstraint("sha256", name=op.f("uq_documents_sha256")),
        comment="class=transaction",
    )
    op.create_index("ix_documents_case_kind", "documents", ["case_id", "kind"], unique=False)
    op.create_index(op.f("ix_documents_office_id"), "documents", ["office_id"], unique=False)
    op.create_index("ix_documents_sourcetrace_status", "documents", ["sourcetrace_status"], unique=False)
    op.create_table(
        "events",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("dedupe_key", sa.String(length=300), nullable=False),
        sa.Column(
            "visibility",
            postgresql.ENUM("tracking_card", "scoped", name="event_visibility", create_type=False),
            server_default="scoped",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name=op.f("fk_events_actor_user_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_events_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["type"], ["ref_event_type.code"], name=op.f("fk_events_type_ref_event_type"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_events_dedupe_key")),
        comment="class=derived",
    )
    op.create_index(
        "ix_events_case_occurred", "events", ["case_id", sa.literal_column("occurred_at DESC")], unique=False
    )
    op.create_index(
        "ix_events_type_occurred", "events", ["type", sa.literal_column("occurred_at DESC")], unique=False
    )
    op.create_table(
        "office_watchlist",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column("cnr", sa.String(length=16), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("weight", sa.Numeric(precision=4, scale=3), server_default="0.750", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_office_watchlist_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_office_watchlist_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["office_id"],
            ["offices.id"],
            name=op.f("fk_office_watchlist_office_id_offices"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_office_watchlist")),
        sa.UniqueConstraint("office_id", "cnr", name=op.f("uq_office_watchlist_office_id_cnr")),
        comment="class=master",
    )
    op.create_index(op.f("ix_office_watchlist_case_id"), "office_watchlist", ["case_id"], unique=False)
    op.create_index(op.f("ix_office_watchlist_office_id"), "office_watchlist", ["office_id"], unique=False)
    op.create_table(
        "otp_codes",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "purpose",
            postgresql.ENUM("login", "password_reset", "new_device", name="otp_purpose", create_type=False),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_otp_codes_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_otp_codes")),
        comment="class=derived",
    )
    op.create_index(op.f("ix_otp_codes_user_id"), "otp_codes", ["user_id"], unique=False)
    op.create_index("ix_otp_codes_user_purpose", "otp_codes", ["user_id", "purpose"], unique=False)
    op.create_table(
        "ownership_transfers",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("from_office_id", sa.UUID(), nullable=False),
        sa.Column("to_office_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "requested", "accepted", "declined", "withdrawn", name="transfer_status", create_type=False
            ),
            server_default="requested",
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("decided_by_user_id", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ref_no", sa.String(length=40), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_ownership_transfers_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_ownership_transfers_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            name=op.f("fk_ownership_transfers_decided_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["from_office_id"],
            ["offices.id"],
            name=op.f("fk_ownership_transfers_from_office_id_offices"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_office_id"],
            ["offices.id"],
            name=op.f("fk_ownership_transfers_to_office_id_offices"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ownership_transfers")),
        sa.UniqueConstraint("ref_no", name=op.f("uq_ownership_transfers_ref_no")),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_ownership_transfers_case_id"), "ownership_transfers", ["case_id"], unique=False)
    op.create_index(
        op.f("ix_ownership_transfers_decided_by_user_id"),
        "ownership_transfers",
        ["decided_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ownership_transfers_from_office_id"), "ownership_transfers", ["from_office_id"], unique=False
    )
    op.create_index(
        op.f("ix_ownership_transfers_to_office_id"), "ownership_transfers", ["to_office_id"], unique=False
    )
    op.create_index(
        "ix_ownership_transfers_to_office_status",
        "ownership_transfers",
        ["to_office_id", "status"],
        unique=False,
    )
    op.create_table(
        "recommendations",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column("score", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column(
            "band", postgresql.ENUM("high", "medium", name="score_band", create_type=False), nullable=False
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "recommended",
                "claimed",
                "dismissed",
                "suggested_elsewhere",
                "expired",
                name="recommendation_status",
                create_type=False,
            ),
            server_default="recommended",
            nullable=False,
        ),
        sa.Column(
            "origin",
            postgresql.ENUM(
                "cause_list",
                "discovery",
                "suggestion",
                "link_history",
                "search",
                name="recommendation_origin",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("suggested_office_id", sa.UUID(), nullable=True),
        sa.Column("acted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_recommendations_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_recommendations_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["office_id"],
            ["offices.id"],
            name=op.f("fk_recommendations_office_id_offices"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["suggested_office_id"],
            ["offices.id"],
            name=op.f("fk_recommendations_suggested_office_id_offices"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendations")),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_recommendations_case_id"), "recommendations", ["case_id"], unique=False)
    op.create_index(op.f("ix_recommendations_office_id"), "recommendations", ["office_id"], unique=False)
    op.create_index(
        "ix_recommendations_office_status", "recommendations", ["office_id", "status"], unique=False
    )
    op.create_index(
        op.f("ix_recommendations_suggested_office_id"),
        "recommendations",
        ["suggested_office_id"],
        unique=False,
    )
    op.create_index(
        "uq_recommendations_active",
        "recommendations",
        ["case_id", "office_id"],
        unique=True,
        postgresql_where=sa.text("status = 'recommended'"),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("device_label", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_refresh_tokens_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
        comment="class=derived",
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)
    op.create_table(
        "requests",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("from_office_id", sa.UUID(), nullable=False),
        sa.Column("to_office_id", sa.UUID(), nullable=False),
        sa.Column("to_user_id", sa.UUID(), nullable=True),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM("open", "answered", "withdrawn", name="request_status", create_type=False),
            server_default="open",
            nullable=False,
        ),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_by_user_id", sa.UUID(), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ref_no", sa.String(length=40), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name=op.f("fk_requests_actor_user_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["answered_by_user_id"],
            ["users.id"],
            name=op.f("fk_requests_answered_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_requests_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["from_office_id"],
            ["offices.id"],
            name=op.f("fk_requests_from_office_id_offices"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["kind"],
            ["ref_request_kind.code"],
            name=op.f("fk_requests_kind_ref_request_kind"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_office_id"],
            ["offices.id"],
            name=op.f("fk_requests_to_office_id_offices"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_user_id"], ["users.id"], name=op.f("fk_requests_to_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_requests")),
        sa.UniqueConstraint("ref_no", name=op.f("uq_requests_ref_no")),
        comment="class=transaction",
    )
    op.create_index("ix_requests_case", "requests", ["case_id"], unique=False)
    op.create_index(op.f("ix_requests_from_office_id"), "requests", ["from_office_id"], unique=False)
    op.create_index("ix_requests_to_office_status", "requests", ["to_office_id", "status"], unique=False)
    op.create_table(
        "user_notification_preferences",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "channel",
            postgresql.ENUM("in_app", "email", "sms", name="notification_channel", create_type=False),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "digest",
            postgresql.ENUM("none", "daily", name="digest_mode", create_type=False),
            server_default="none",
            nullable=False,
        ),
        sa.Column("critical_only", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_notification_preferences_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_notification_preferences")),
        sa.UniqueConstraint(
            "user_id", "channel", name=op.f("uq_user_notification_preferences_user_id_channel")
        ),
        comment="class=master",
    )
    op.create_index(
        op.f("ix_user_notification_preferences_user_id"),
        "user_notification_preferences",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "severity",
            postgresql.ENUM("critical", "high", "normal", name="alert_severity", create_type=False),
            server_default="normal",
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "open", "acknowledged", "done", "expired", name="alert_status", create_type=False
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("source_event_id", sa.UUID(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("acknowledged_by_user_id", sa.UUID(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ref_no", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(
            ["acknowledged_by_user_id"],
            ["users.id"],
            name=op.f("fk_alerts_acknowledged_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_alerts_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["kind"], ["ref_alert_kind.code"], name=op.f("fk_alerts_kind_ref_alert_kind"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_event_id"],
            ["events.id"],
            name=op.f("fk_alerts_source_event_id_events"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_alerts_dedupe_key")),
        sa.UniqueConstraint("ref_no", name=op.f("uq_alerts_ref_no")),
        comment="class=transaction",
    )
    op.create_index(
        op.f("ix_alerts_acknowledged_by_user_id"), "alerts", ["acknowledged_by_user_id"], unique=False
    )
    op.create_index("ix_alerts_case", "alerts", ["case_id"], unique=False)
    op.create_index("ix_alerts_due_status", "alerts", ["due_at", "status"], unique=False)
    op.create_index(op.f("ix_alerts_source_event_id"), "alerts", ["source_event_id"], unique=False)
    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("model_info", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["assistant_conversations.id"],
            name=op.f("fk_assistant_messages_conversation_id_assistant_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_messages")),
        comment="class=transaction",
    )
    op.create_index(
        "ix_assistant_messages_conversation",
        "assistant_messages",
        ["conversation_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "causelists",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("court_id", sa.UUID(), nullable=False),
        sa.Column("list_date", sa.Date(), nullable=False),
        sa.Column("bench_id", sa.String(length=32), server_default="", nullable=False),
        sa.Column("napix_causelist_id", sa.String(length=64), server_default="", nullable=False),
        sa.Column(
            "list_type",
            postgresql.ENUM(
                "daily", "supplementary", "lawazima", "vacation", "other", name="list_type", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=300), nullable=True),
        sa.Column(
            "source",
            postgresql.ENUM("napix", "ghc_website", "local_dir", name="causelist_source", create_type=False),
            nullable=False,
        ),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column(
            "fetch_status",
            postgresql.ENUM(
                "pending", "fetched", "not_available", "failed", name="fetch_status", create_type=False
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "parse_status",
            postgresql.ENUM(
                "pending",
                "parsed",
                "partial",
                "failed",
                "not_applicable",
                name="parse_status",
                create_type=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("entry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["court_id"], ["courts.id"], name=op.f("fk_causelists_court_id_courts"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_causelists_document_id_documents"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_causelists")),
        sa.UniqueConstraint(
            "court_id",
            "list_date",
            "bench_id",
            "napix_causelist_id",
            "source",
            name=op.f("uq_causelists_court_id_list_date_bench_id_napix_causelist_id_source"),
        ),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_causelists_court_id"), "causelists", ["court_id"], unique=False)
    op.create_index(op.f("ix_causelists_document_id"), "causelists", ["document_id"], unique=False)
    op.create_index("ix_causelists_list_date", "causelists", ["list_date"], unique=False)
    op.create_table(
        "custody",
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("holder_office_id", sa.UUID(), nullable=False),
        sa.Column("holder_user_id", sa.UUID(), nullable=True),
        sa.Column("pending_action", sa.String(length=300), nullable=True),
        sa.Column("since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("request_id", sa.UUID(), nullable=True),
        sa.Column("current_leg_id", sa.UUID(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_custody_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["holder_office_id"],
            ["offices.id"],
            name=op.f("fk_custody_holder_office_id_offices"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["holder_user_id"],
            ["users.id"],
            name=op.f("fk_custody_holder_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"], ["requests.id"], name=op.f("fk_custody_request_id_requests"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("case_id", name=op.f("pk_custody")),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_custody_holder_office_id"), "custody", ["holder_office_id"], unique=False)
    op.create_index(op.f("ix_custody_holder_user_id"), "custody", ["holder_user_id"], unique=False)
    op.create_table(
        "custody_history",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("seq_no", sa.Integer(), nullable=False),
        sa.Column("holder_office_id", sa.UUID(), nullable=False),
        sa.Column("holder_office_code", sa.String(length=64), nullable=False),
        sa.Column("holder_user_id", sa.UUID(), nullable=True),
        sa.Column("holder_user_name", sa.String(length=200), nullable=True),
        sa.Column(
            "reason",
            postgresql.ENUM(
                "claim",
                "allot",
                "transfer",
                "request_sent",
                "request_answered",
                "request_withdrawn",
                "handover",
                "release",
                name="custody_reason",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("pending_action", sa.String(length=300), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("request_id", sa.UUID(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_custody_history_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_custody_history_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["holder_office_id"],
            ["offices.id"],
            name=op.f("fk_custody_history_holder_office_id_offices"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["holder_user_id"],
            ["users.id"],
            name=op.f("fk_custody_history_holder_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["requests.id"],
            name=op.f("fk_custody_history_request_id_requests"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custody_history")),
        comment="class=derived",
    )
    op.create_index(
        "ix_custody_history_case_started",
        "custody_history",
        ["case_id", sa.literal_column("started_at DESC")],
        unique=False,
    )
    op.create_index(
        op.f("ix_custody_history_holder_office_id"), "custody_history", ["holder_office_id"], unique=False
    )
    op.create_table(
        "document_text",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("full_text", sa.Text(), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_text_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id", name=op.f("pk_document_text")),
        comment="class=transaction",
    )
    op.create_index(
        "ix_document_text_search_vector",
        "document_text",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("order_no", sa.String(length=32), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM("interim", "final", "judgment", name="order_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("is_reportable", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column(
            "download_status",
            postgresql.ENUM(
                "pending", "downloaded", "not_available", "failed", name="download_status", create_type=False
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("download_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_orders_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_orders_document_id_documents"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint(
            "case_id", "order_no", "order_date", name=op.f("uq_orders_case_id_order_no_order_date")
        ),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_orders_case_id"), "orders", ["case_id"], unique=False)
    op.create_index(op.f("ix_orders_document_id"), "orders", ["document_id"], unique=False)
    op.create_index("ix_orders_download_status", "orders", ["download_status"], unique=False)
    op.create_table(
        "request_messages",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_answer", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_request_messages_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["requests.id"],
            name=op.f("fk_request_messages_request_id_requests"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_request_messages")),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_request_messages_request_id"), "request_messages", ["request_id"], unique=False)
    op.create_table(
        "sourcetrace_ingestions",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("reference", sa.String(length=200), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "metadata_sent", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_sourcetrace_ingestions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sourcetrace_ingestions")),
        comment="class=derived",
    )
    op.create_index(
        "ix_sourcetrace_ingestions_document",
        "sourcetrace_ingestions",
        ["document_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "case_notes",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("seq_no", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "visibility",
            postgresql.ENUM(
                "case_scope", "counsel_shared", "private_to_office", name="note_visibility", create_type=False
            ),
            server_default="case_scope",
            nullable=False,
        ),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column("author_role", sa.String(length=32), nullable=False),
        sa.Column("custody_leg_id", sa.UUID(), nullable=True),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ref_no", sa.String(length=40), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_case_notes_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_case_notes_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["custody_leg_id"],
            ["custody_history.id"],
            name=op.f("fk_case_notes_custody_leg_id_custody_history"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["kind"],
            ["ref_note_kind.code"],
            name=op.f("fk_case_notes_kind_ref_note_kind"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["office_id"], ["offices.id"], name=op.f("fk_case_notes_office_id_offices"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["case_notes.id"],
            name=op.f("fk_case_notes_supersedes_id_case_notes"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_notes")),
        sa.UniqueConstraint("case_id", "seq_no", name=op.f("uq_case_notes_case_id_seq_no")),
        sa.UniqueConstraint("ref_no", name=op.f("uq_case_notes_ref_no")),
        comment="class=transaction",
    )
    op.create_index("ix_case_notes_case_seq", "case_notes", ["case_id", "seq_no"], unique=False)
    op.create_table(
        "causelist_entries",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("causelist_id", sa.UUID(), nullable=False),
        sa.Column("sr_no", sa.Integer(), nullable=False),
        sa.Column("court_no", sa.String(length=32), nullable=True),
        sa.Column("cnr", sa.String(length=16), nullable=True),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("case_no_text", sa.String(length=120), nullable=True),
        sa.Column("petitioner_text", sa.Text(), nullable=True),
        sa.Column("respondent_text", sa.Text(), nullable=True),
        sa.Column("pet_advocate_text", sa.Text(), nullable=True),
        sa.Column("res_advocate_text", sa.Text(), nullable=True),
        sa.Column("counsel_codes", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("with_text", sa.Text(), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column(
            "source",
            postgresql.ENUM("napix_details", "pdf_parse", name="entry_source", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "resolution_status",
            postgresql.ENUM(
                "resolved", "provisional", "unresolved", name="resolution_status", create_type=False
            ),
            server_default="unresolved",
            nullable=False,
        ),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_causelist_entries_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["causelist_id"],
            ["causelists.id"],
            name=op.f("fk_causelist_entries_causelist_id_causelists"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_causelist_entries")),
        sa.UniqueConstraint(
            "causelist_id", "source", "sr_no", name=op.f("uq_causelist_entries_causelist_id_source_sr_no")
        ),
        comment="class=transaction",
    )
    op.create_index("ix_causelist_entries_case", "causelist_entries", ["case_id"], unique=False)
    op.create_index(
        op.f("ix_causelist_entries_causelist_id"), "causelist_entries", ["causelist_id"], unique=False
    )
    op.create_index("ix_causelist_entries_cnr", "causelist_entries", ["cnr"], unique=False)
    op.create_table(
        "causelist_reconciliations",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("causelist_id", sa.UUID(), nullable=False),
        sa.Column("cnr", sa.String(length=16), nullable=False),
        sa.Column("in_napix", sa.Boolean(), nullable=False),
        sa.Column("in_pdf", sa.Boolean(), nullable=False),
        sa.Column("mismatch_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["causelist_id"],
            ["causelists.id"],
            name=op.f("fk_causelist_reconciliations_causelist_id_causelists"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_causelist_reconciliations")),
        sa.UniqueConstraint(
            "causelist_id", "cnr", name=op.f("uq_causelist_reconciliations_causelist_id_cnr")
        ),
        comment="class=transaction",
    )
    op.create_index(
        op.f("ix_causelist_reconciliations_causelist_id"),
        "causelist_reconciliations",
        ["causelist_id"],
        unique=False,
    )
    op.create_table(
        "next_dates",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("next_date", sa.Date(), nullable=False),
        sa.Column(
            "source",
            postgresql.ENUM(
                "causelist",
                "current_status",
                "order_specific",
                "order_period",
                "manual",
                name="next_date_source",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("order_id", sa.UUID(), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("needs_review", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "review_status",
            postgresql.ENUM(
                "none", "pending", "confirmed", "rejected", name="review_status", create_type=False
            ),
            server_default="none",
            nullable=False,
        ),
        sa.Column("reviewed_by_user_id", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ref_no", sa.String(length=40), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_next_dates_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_next_dates_created_by_users"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_next_dates_order_id_orders"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            name=op.f("fk_next_dates_reviewed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_next_dates_updated_by_users"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_next_dates")),
        sa.UniqueConstraint(
            "case_id",
            "next_date",
            "source",
            "order_id",
            name=op.f("uq_next_dates_case_id_next_date_source_order_id"),
        ),
        sa.UniqueConstraint("ref_no", name=op.f("uq_next_dates_ref_no")),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_next_dates_case_id"), "next_dates", ["case_id"], unique=False)
    op.create_index("ix_next_dates_next_date", "next_dates", ["next_date"], unique=False)
    op.create_index(op.f("ix_next_dates_order_id"), "next_dates", ["order_id"], unique=False)
    op.create_index(
        op.f("ix_next_dates_reviewed_by_user_id"), "next_dates", ["reviewed_by_user_id"], unique=False
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("alert_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "channel",
            postgresql.ENUM("in_app", "email", "sms", name="notification_channel", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "queued", "sent", "failed", "read", name="notification_status", create_type=False
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["alert_id"], ["alerts.id"], name=op.f("fk_notifications_alert_id_alerts"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_notifications_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_notifications_dedupe_key")),
        comment="class=derived",
    )
    op.create_index(op.f("ix_notifications_alert_id"), "notifications", ["alert_id"], unique=False)
    op.create_index("ix_notifications_user_status", "notifications", ["user_id", "status"], unique=False)
    op.create_table(
        "case_note_attachments",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("note_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_case_note_attachments_document_id_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["note_id"],
            ["case_notes.id"],
            name=op.f("fk_case_note_attachments_note_id_case_notes"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_note_attachments")),
        sa.UniqueConstraint(
            "note_id", "document_id", name=op.f("uq_case_note_attachments_note_id_document_id")
        ),
        comment="class=transaction",
    )
    op.create_index(
        op.f("ix_case_note_attachments_document_id"), "case_note_attachments", ["document_id"], unique=False
    )
    op.create_index(
        op.f("ix_case_note_attachments_note_id"), "case_note_attachments", ["note_id"], unique=False
    )

    # constraints deferred to break the users <-> offices / designations creation cycle
    op.create_foreign_key(
        "fk_designations_created_by_users",
        "designations",
        "users",
        ["created_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_designations_updated_by_users",
        "designations",
        "users",
        ["updated_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_offices_updated_by_users", "offices", "users", ["updated_by"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_offices_created_by_users", "offices", "users", ["created_by"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_counsel_codes_updated_by_users",
        "counsel_codes",
        "users",
        ["updated_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_counsel_codes_created_by_users",
        "counsel_codes",
        "users",
        ["created_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_office_keywords_updated_by_users",
        "office_keywords",
        "users",
        ["updated_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_office_keywords_created_by_users",
        "office_keywords",
        "users",
        ["created_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_office_name_patterns_updated_by_users",
        "office_name_patterns",
        "users",
        ["updated_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_office_name_patterns_created_by_users",
        "office_name_patterns",
        "users",
        ["created_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_users_created_by_users", "users", "users", ["created_by"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_users_updated_by_users", "users", "users", ["updated_by"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_users_designation_id_designations",
        "users",
        "designations",
        ["designation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_next_dates_created_by_users", "next_dates", "users", ["created_by"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_next_dates_updated_by_users", "next_dates", "users", ["updated_by"], ["id"], ondelete="SET NULL"
    )
    for table in WITH_UPDATED_AT:
        op.execute(
            f"CREATE TRIGGER {table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )
    for table in APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION aslms_forbid_change()"
        )
    _roles_and_grants()


def downgrade() -> None:
    bind = op.get_bind()
    # privileges granted in this database go; the roles are cluster-wide and stay
    op.execute("DROP OWNED BY aslms_app, aslms_readonly, aslms_owner")
    op.drop_constraint("fk_designations_created_by_users", "designations", type_="foreignkey")
    op.drop_constraint("fk_designations_updated_by_users", "designations", type_="foreignkey")
    op.drop_constraint("fk_offices_updated_by_users", "offices", type_="foreignkey")
    op.drop_constraint("fk_offices_created_by_users", "offices", type_="foreignkey")
    op.drop_constraint("fk_counsel_codes_updated_by_users", "counsel_codes", type_="foreignkey")
    op.drop_constraint("fk_counsel_codes_created_by_users", "counsel_codes", type_="foreignkey")
    op.drop_constraint("fk_office_keywords_updated_by_users", "office_keywords", type_="foreignkey")
    op.drop_constraint("fk_office_keywords_created_by_users", "office_keywords", type_="foreignkey")
    op.drop_constraint("fk_office_name_patterns_updated_by_users", "office_name_patterns", type_="foreignkey")
    op.drop_constraint("fk_office_name_patterns_created_by_users", "office_name_patterns", type_="foreignkey")
    op.drop_constraint("fk_users_created_by_users", "users", type_="foreignkey")
    op.drop_constraint("fk_users_updated_by_users", "users", type_="foreignkey")
    op.drop_constraint("fk_users_designation_id_designations", "users", type_="foreignkey")
    op.drop_constraint("fk_next_dates_created_by_users", "next_dates", type_="foreignkey")
    op.drop_constraint("fk_next_dates_updated_by_users", "next_dates", type_="foreignkey")
    op.drop_index(op.f("ix_case_note_attachments_note_id"), table_name="case_note_attachments")
    op.drop_index(op.f("ix_case_note_attachments_document_id"), table_name="case_note_attachments")
    op.drop_table("case_note_attachments")
    op.drop_index("ix_notifications_user_status", table_name="notifications")
    op.drop_index(op.f("ix_notifications_alert_id"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_index(op.f("ix_next_dates_reviewed_by_user_id"), table_name="next_dates")
    op.drop_index(op.f("ix_next_dates_order_id"), table_name="next_dates")
    op.drop_index("ix_next_dates_next_date", table_name="next_dates")
    op.drop_index(op.f("ix_next_dates_case_id"), table_name="next_dates")
    op.drop_table("next_dates")
    op.drop_index(op.f("ix_causelist_reconciliations_causelist_id"), table_name="causelist_reconciliations")
    op.drop_table("causelist_reconciliations")
    op.drop_index("ix_causelist_entries_cnr", table_name="causelist_entries")
    op.drop_index(op.f("ix_causelist_entries_causelist_id"), table_name="causelist_entries")
    op.drop_index("ix_causelist_entries_case", table_name="causelist_entries")
    op.drop_table("causelist_entries")
    op.drop_index("ix_case_notes_case_seq", table_name="case_notes")
    op.drop_table("case_notes")
    op.drop_index("ix_sourcetrace_ingestions_document", table_name="sourcetrace_ingestions")
    op.drop_table("sourcetrace_ingestions")
    op.drop_index(op.f("ix_request_messages_request_id"), table_name="request_messages")
    op.drop_table("request_messages")
    op.drop_index("ix_orders_download_status", table_name="orders")
    op.drop_index(op.f("ix_orders_document_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_case_id"), table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_document_text_search_vector", table_name="document_text", postgresql_using="gin")
    op.drop_table("document_text")
    op.drop_index(op.f("ix_custody_history_holder_office_id"), table_name="custody_history")
    op.drop_index("ix_custody_history_case_started", table_name="custody_history")
    op.drop_table("custody_history")
    op.drop_index(op.f("ix_custody_holder_user_id"), table_name="custody")
    op.drop_index(op.f("ix_custody_holder_office_id"), table_name="custody")
    op.drop_table("custody")
    op.drop_index("ix_causelists_list_date", table_name="causelists")
    op.drop_index(op.f("ix_causelists_document_id"), table_name="causelists")
    op.drop_index(op.f("ix_causelists_court_id"), table_name="causelists")
    op.drop_table("causelists")
    op.drop_index("ix_assistant_messages_conversation", table_name="assistant_messages")
    op.drop_table("assistant_messages")
    op.drop_index(op.f("ix_alerts_source_event_id"), table_name="alerts")
    op.drop_index("ix_alerts_due_status", table_name="alerts")
    op.drop_index("ix_alerts_case", table_name="alerts")
    op.drop_index(op.f("ix_alerts_acknowledged_by_user_id"), table_name="alerts")
    op.drop_table("alerts")
    op.drop_index(
        op.f("ix_user_notification_preferences_user_id"), table_name="user_notification_preferences"
    )
    op.drop_table("user_notification_preferences")
    op.drop_index("ix_requests_to_office_status", table_name="requests")
    op.drop_index(op.f("ix_requests_from_office_id"), table_name="requests")
    op.drop_index("ix_requests_case", table_name="requests")
    op.drop_table("requests")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index(
        "uq_recommendations_active",
        table_name="recommendations",
        postgresql_where=sa.text("status = 'recommended'"),
    )
    op.drop_index(op.f("ix_recommendations_suggested_office_id"), table_name="recommendations")
    op.drop_index("ix_recommendations_office_status", table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_office_id"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_case_id"), table_name="recommendations")
    op.drop_table("recommendations")
    op.drop_index("ix_ownership_transfers_to_office_status", table_name="ownership_transfers")
    op.drop_index(op.f("ix_ownership_transfers_to_office_id"), table_name="ownership_transfers")
    op.drop_index(op.f("ix_ownership_transfers_from_office_id"), table_name="ownership_transfers")
    op.drop_index(op.f("ix_ownership_transfers_decided_by_user_id"), table_name="ownership_transfers")
    op.drop_index(op.f("ix_ownership_transfers_case_id"), table_name="ownership_transfers")
    op.drop_table("ownership_transfers")
    op.drop_index("ix_otp_codes_user_purpose", table_name="otp_codes")
    op.drop_index(op.f("ix_otp_codes_user_id"), table_name="otp_codes")
    op.drop_table("otp_codes")
    op.drop_index(op.f("ix_office_watchlist_office_id"), table_name="office_watchlist")
    op.drop_index(op.f("ix_office_watchlist_case_id"), table_name="office_watchlist")
    op.drop_table("office_watchlist")
    op.drop_index("ix_events_type_occurred", table_name="events")
    op.drop_index("ix_events_case_occurred", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_documents_sourcetrace_status", table_name="documents")
    op.drop_index(op.f("ix_documents_office_id"), table_name="documents")
    op.drop_index("ix_documents_case_kind", table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_digests_user_id"), table_name="digests")
    op.drop_table("digests")
    op.drop_index("ix_case_stages_case_created", table_name="case_stages")
    op.drop_table("case_stages")
    op.drop_index(op.f("ix_case_snapshots_case_id"), table_name="case_snapshots")
    op.drop_index("ix_case_snapshots_case_fetched", table_name="case_snapshots")
    op.drop_table("case_snapshots")
    op.drop_index("ix_case_parties_name_normalised", table_name="case_parties")
    op.drop_index(op.f("ix_case_parties_case_id"), table_name="case_parties")
    op.drop_table("case_parties")
    op.drop_index(
        "uq_case_ownership_one_primary",
        table_name="case_ownership",
        postgresql_where=sa.text("role = 'primary' AND status = 'active'"),
    )
    op.drop_index(
        "uq_case_ownership_active_office",
        table_name="case_ownership",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_index(op.f("ix_case_ownership_unit_office_id"), table_name="case_ownership")
    op.drop_index(op.f("ix_case_ownership_officer_user_id"), table_name="case_ownership")
    op.drop_index("ix_case_ownership_office_status", table_name="case_ownership")
    op.drop_index(op.f("ix_case_ownership_office_id"), table_name="case_ownership")
    op.drop_index(op.f("ix_case_ownership_case_id"), table_name="case_ownership")
    op.drop_table("case_ownership")
    op.drop_index("ix_case_office_scores_office_score", table_name="case_office_scores")
    op.drop_index(op.f("ix_case_office_scores_office_id"), table_name="case_office_scores")
    op.drop_index(op.f("ix_case_office_scores_case_id"), table_name="case_office_scores")
    op.drop_table("case_office_scores")
    op.drop_index(op.f("ix_case_objections_case_id"), table_name="case_objections")
    op.drop_table("case_objections")
    op.drop_index(op.f("ix_case_lower_courts_case_id"), table_name="case_lower_courts")
    op.drop_table("case_lower_courts")
    op.drop_index(op.f("ix_case_links_to_case_id"), table_name="case_links")
    op.drop_index(op.f("ix_case_links_from_case_id"), table_name="case_links")
    op.drop_table("case_links")
    op.drop_index(op.f("ix_case_hearings_case_id"), table_name="case_hearings")
    op.drop_table("case_hearings")
    op.drop_index(op.f("ix_case_applications_case_id"), table_name="case_applications")
    op.drop_table("case_applications")
    op.drop_index("ix_case_advocates_counsel_code", table_name="case_advocates")
    op.drop_index(op.f("ix_case_advocates_case_id"), table_name="case_advocates")
    op.drop_index(op.f("ix_case_advocates_advocate_id"), table_name="case_advocates")
    op.drop_table("case_advocates")
    op.drop_index(op.f("ix_case_acts_case_id"), table_name="case_acts")
    op.drop_index(op.f("ix_case_acts_act_id"), table_name="case_acts")
    op.drop_table("case_acts")
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
    op.drop_index("ix_audit_log_case_created", table_name="audit_log")
    op.drop_index("ix_audit_log_actor_created", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_assistant_conversations_user_case", table_name="assistant_conversations")
    op.drop_table("assistant_conversations")
    op.drop_index(op.f("ix_users_office_id"), table_name="users")
    op.drop_index(op.f("ix_users_designation_id"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_office_name_patterns_office_id"), table_name="office_name_patterns")
    op.drop_table("office_name_patterns")
    op.drop_index(op.f("ix_office_keywords_office_id"), table_name="office_keywords")
    op.drop_table("office_keywords")
    op.drop_index(op.f("ix_counsel_codes_office_id"), table_name="counsel_codes")
    op.drop_table("counsel_codes")
    op.drop_index("ix_cases_search_vector", table_name="cases", postgresql_using="gin")
    op.drop_index("ix_cases_next_hearing", table_name="cases")
    op.drop_index(op.f("ix_cases_district_id"), table_name="cases")
    op.drop_index("ix_cases_court_type_no_year", table_name="cases")
    op.drop_index(op.f("ix_cases_court_id"), table_name="cases")
    op.drop_index(op.f("ix_cases_case_type_id"), table_name="cases")
    op.drop_index(op.f("ix_cases_bench_id"), table_name="cases")
    op.drop_table("cases")
    op.drop_table("ref_sequences")
    op.drop_index(op.f("ix_offices_path"), table_name="offices")
    op.drop_table("offices")
    op.drop_index(op.f("ix_napix_call_log_job_run_id"), table_name="napix_call_log")
    op.drop_index("ix_napix_call_log_called_at", table_name="napix_call_log")
    op.drop_table("napix_call_log")
    op.drop_index(op.f("ix_districts_state_id"), table_name="districts")
    op.drop_table("districts")
    op.drop_index(op.f("ix_case_types_court_id"), table_name="case_types")
    op.drop_table("case_types")
    op.drop_index(op.f("ix_benches_court_id"), table_name="benches")
    op.drop_table("benches")
    op.drop_table("states")
    op.drop_index(
        "uq_source_failures_open",
        table_name="source_failures",
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.drop_table("source_failures")
    op.drop_table("ref_role")
    op.drop_table("ref_request_kind")
    op.drop_table("ref_record_type")
    op.drop_table("ref_office_kind")
    op.drop_table("ref_note_kind")
    op.drop_table("ref_event_type")
    op.drop_table("ref_doc_type")
    op.drop_table("ref_case_stage")
    op.drop_table("ref_alert_kind")
    op.drop_table("master_sync_runs")
    op.drop_index("ix_job_runs_job_started", table_name="job_runs")
    op.drop_table("job_runs")
    op.drop_table("designations")
    op.drop_table("courts")
    op.drop_index("ix_advocates_name_normalised", table_name="advocates")
    op.drop_table("advocates")
    op.drop_table("acts")

    postgresql.ENUM(name="advocate_side").drop(bind, checkfirst=True)
    postgresql.ENUM(name="alert_severity").drop(bind, checkfirst=True)
    postgresql.ENUM(name="alert_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="case_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="causelist_source").drop(bind, checkfirst=True)
    postgresql.ENUM(name="conversation_scope").drop(bind, checkfirst=True)
    postgresql.ENUM(name="court_level").drop(bind, checkfirst=True)
    postgresql.ENUM(name="custody_reason").drop(bind, checkfirst=True)
    postgresql.ENUM(name="digest_mode").drop(bind, checkfirst=True)
    postgresql.ENUM(name="doc_group").drop(bind, checkfirst=True)
    postgresql.ENUM(name="document_kind").drop(bind, checkfirst=True)
    postgresql.ENUM(name="download_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="entry_source").drop(bind, checkfirst=True)
    postgresql.ENUM(name="event_visibility").drop(bind, checkfirst=True)
    postgresql.ENUM(name="failure_kind").drop(bind, checkfirst=True)
    postgresql.ENUM(name="fetch_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="first_seen_source").drop(bind, checkfirst=True)
    postgresql.ENUM(name="hearing_source").drop(bind, checkfirst=True)
    postgresql.ENUM(name="job_kind").drop(bind, checkfirst=True)
    postgresql.ENUM(name="job_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="link_kind").drop(bind, checkfirst=True)
    postgresql.ENUM(name="link_source").drop(bind, checkfirst=True)
    postgresql.ENUM(name="list_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="lower_court_level").drop(bind, checkfirst=True)
    postgresql.ENUM(name="master_kind").drop(bind, checkfirst=True)
    postgresql.ENUM(name="next_date_source").drop(bind, checkfirst=True)
    postgresql.ENUM(name="note_visibility").drop(bind, checkfirst=True)
    postgresql.ENUM(name="notification_channel").drop(bind, checkfirst=True)
    postgresql.ENUM(name="notification_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="order_kind").drop(bind, checkfirst=True)
    postgresql.ENUM(name="otp_purpose").drop(bind, checkfirst=True)
    postgresql.ENUM(name="ownership_role").drop(bind, checkfirst=True)
    postgresql.ENUM(name="ownership_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="parse_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="party_role").drop(bind, checkfirst=True)
    postgresql.ENUM(name="pattern_kind").drop(bind, checkfirst=True)
    postgresql.ENUM(name="recommendation_origin").drop(bind, checkfirst=True)
    postgresql.ENUM(name="recommendation_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="request_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="resolution_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="review_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="score_band").drop(bind, checkfirst=True)
    postgresql.ENUM(name="snapshot_source").drop(bind, checkfirst=True)
    postgresql.ENUM(name="sourcetrace_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="text_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="transfer_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="virus_scan_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="visibility").drop(bind, checkfirst=True)
    op.execute("DROP FUNCTION IF EXISTS aslms_forbid_change()")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    op.execute("DROP FUNCTION IF EXISTS uuid_generate_v7()")
