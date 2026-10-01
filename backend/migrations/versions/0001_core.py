"""0001 core: the whole approved schema (DB_STANDARD v1.2, schema.md, napix_coverage.md)

Revision ID: 0001
Revises:
Create Date: 2026-10-01 14:36:51.701150
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# --- static facts from the models at generation time (DB_STANDARD v1.2) ---------------------------------
ENUM_TYPES: dict[str, list[str]] = {
    "otp_purpose": ["login", "password_reset", "new_device"],
    "notification_channel": ["in_app", "email", "sms"],
    "digest_mode": ["none", "daily"],
    "next_date_source": ["causelist", "current_status", "order_specific", "order_period", "manual"],
    "review_status": ["not_needed", "pending", "confirmed", "rejected"],
    "alert_severity": ["critical", "high", "normal"],
    "alert_status": ["open", "acknowledged", "done", "expired"],
    "notification_status": ["queued", "sent", "failed", "read"],
    "assistant_scope": ["case", "research"],
    "message_role": ["user", "assistant", "system"],
    "case_status": ["pending", "disposed", "unknown"],
    "first_seen_source": ["causelist", "search", "discovery", "link"],
    "party_role": ["petitioner", "respondent"],
    "advocate_side": ["petitioner", "respondent"],
    "hearing_source": ["dossier", "show_business", "causelist"],
    "lower_court_level": ["appellate", "trial"],
    "link_kind": ["main_matter", "connected", "linked", "ia_in", "appeal_of", "contempt_of", "with"],
    "link_source": ["dossier", "causelist", "manual"],
    "snapshot_source": ["cnr", "current_status"],
    "list_type": ["daily", "supplementary", "lawazima", "vacation", "other"],
    "list_source": ["napix", "ghc_website", "local_dir"],
    "fetch_status": ["pending", "fetched", "failed", "not_available"],
    "parse_status": ["pending", "parsed", "failed", "empty"],
    "entry_source": ["napix_details", "pdf_parse"],
    "resolution_status": ["resolved", "provisional", "unresolved"],
    "court_level": ["hc", "dc"],
    "district_kind": ["district", "agency"],
    "master_kind": ["state", "district", "bench", "case_type", "act"],
    "doc_kind": ["causelist", "order", "upload", "attachment"],
    "doc_group": ["court_record", "court_filing", "internal"],
    "doc_visibility": ["case_scope", "counsel_shared", "private_to_office"],
    "scan_status": ["pending", "clean", "infected", "failed", "skipped"],
    "text_status": ["pending", "extracted", "failed", "none"],
    "sourcetrace_status": ["not_applicable", "pending", "ingested", "failed"],
    "order_kind": ["interim", "final", "judgment"],
    "download_status": ["pending", "stored", "failed", "not_available"],
    "event_visibility": ["tracking_card", "scoped"],
    "job_status": ["running", "succeeded", "partial", "failed"],
    "fetch_kind": ["masters", "causelist_day", "dossier", "status_batch", "order_pdf"],
    "fetch_queue_status": ["pending", "running", "done", "failed", "skipped"],
    "pattern_kind": ["exact", "prefix", "regex"],
    "score_band": ["high", "medium"],
    "recommendation_status": ["recommended", "claimed", "dismissed", "suggested_elsewhere", "expired"],
    "recommendation_origin": ["cause_list", "rescore", "search", "suggestion", "watchlist"],
    "ownership_role": ["primary", "watcher"],
    "ownership_status": ["active", "transferred", "released"],
    "transfer_status": ["requested", "accepted", "declined", "withdrawn"],
    "pending_action": ["none", "examine", "reply", "file", "comply", "review"],
    "request_status": ["open", "answered", "withdrawn"],
    "response_mode": ["department", "counsel", "none"],
    "note_source": ["user", "system"],
}
USE_ALTER_FKS = [
    ("fk_designations_created_by_users", "designations", "users", ["created_by"], ["id"], "SET NULL"),
    ("fk_designations_updated_by_users", "designations", "users", ["updated_by"], ["id"], "SET NULL"),
    ("fk_offices_created_by_users", "offices", "users", ["created_by"], ["id"], "SET NULL"),
    ("fk_offices_updated_by_users", "offices", "users", ["updated_by"], ["id"], "SET NULL"),
    ("fk_causelists_document_id_documents", "causelists", "documents", ["document_id"], ["id"], "RESTRICT"),
    ("fk_counsel_codes_updated_by_users", "counsel_codes", "users", ["updated_by"], ["id"], "SET NULL"),
    ("fk_counsel_codes_created_by_users", "counsel_codes", "users", ["created_by"], ["id"], "SET NULL"),
    ("fk_office_keywords_updated_by_users", "office_keywords", "users", ["updated_by"], ["id"], "SET NULL"),
    ("fk_office_keywords_created_by_users", "office_keywords", "users", ["created_by"], ["id"], "SET NULL"),
    (
        "fk_office_name_patterns_updated_by_users",
        "office_name_patterns",
        "users",
        ["updated_by"],
        ["id"],
        "SET NULL",
    ),
    (
        "fk_office_name_patterns_created_by_users",
        "office_name_patterns",
        "users",
        ["created_by"],
        ["id"],
        "SET NULL",
    ),
    ("fk_users_designation_id_designations", "users", "designations", ["designation_id"], ["id"], "RESTRICT"),
    ("fk_users_updated_by_users", "users", "users", ["updated_by"], ["id"], "SET NULL"),
    ("fk_users_created_by_users", "users", "users", ["created_by"], ["id"], "SET NULL"),
    ("fk_cases_created_by_users", "cases", "users", ["created_by"], ["id"], "SET NULL"),
    ("fk_cases_updated_by_users", "cases", "users", ["updated_by"], ["id"], "SET NULL"),
    ("fk_alerts_source_event_id_events", "alerts", "events", ["source_event_id"], ["id"], "RESTRICT"),
    ("fk_audit_log_actor_user_id_users", "audit_log", "users", ["actor_user_id"], ["id"], "SET NULL"),
    (
        "fk_case_ownership_actor_user_id_users",
        "case_ownership",
        "users",
        ["actor_user_id"],
        ["id"],
        "SET NULL",
    ),
    ("fk_case_stages_actor_user_id_users", "case_stages", "users", ["actor_user_id"], ["id"], "SET NULL"),
    (
        "fk_custody_current_leg_id_custody_history",
        "custody",
        "custody_history",
        ["current_leg_id"],
        ["id"],
        "RESTRICT",
    ),
    ("fk_custody_request_id_requests", "custody", "requests", ["request_id"], ["id"], "RESTRICT"),
    (
        "fk_custody_history_actor_user_id_users",
        "custody_history",
        "users",
        ["actor_user_id"],
        ["id"],
        "SET NULL",
    ),
    (
        "fk_custody_history_request_id_requests",
        "custody_history",
        "requests",
        ["request_id"],
        ["id"],
        "RESTRICT",
    ),
    ("fk_documents_actor_user_id_users", "documents", "users", ["actor_user_id"], ["id"], "SET NULL"),
    (
        "fk_office_watchlist_actor_user_id_users",
        "office_watchlist",
        "users",
        ["actor_user_id"],
        ["id"],
        "SET NULL",
    ),
    (
        "fk_ownership_transfers_actor_user_id_users",
        "ownership_transfers",
        "users",
        ["actor_user_id"],
        ["id"],
        "SET NULL",
    ),
    (
        "fk_recommendations_actor_user_id_users",
        "recommendations",
        "users",
        ["actor_user_id"],
        ["id"],
        "SET NULL",
    ),
    ("fk_requests_actor_user_id_users", "requests", "users", ["actor_user_id"], ["id"], "SET NULL"),
    ("fk_case_notes_actor_user_id_users", "case_notes", "users", ["actor_user_id"], ["id"], "SET NULL"),
    (
        "fk_request_messages_actor_user_id_users",
        "request_messages",
        "users",
        ["actor_user_id"],
        ["id"],
        "SET NULL",
    ),
    ("fk_next_dates_created_by_users", "next_dates", "users", ["created_by"], ["id"], "SET NULL"),
    ("fk_next_dates_updated_by_users", "next_dates", "users", ["updated_by"], ["id"], "SET NULL"),
]
MUTABLE_TABLES = [
    "acts",
    "advocates",
    "alerts",
    "assistant_conversations",
    "benches",
    "case_acts",
    "case_advocates",
    "case_applications",
    "case_hearings",
    "case_links",
    "case_lower_courts",
    "case_objections",
    "case_ownership",
    "case_parties",
    "case_transfers",
    "case_types",
    "case_writ_info",
    "cases",
    "causelists",
    "counsel_codes",
    "courts",
    "custody",
    "designations",
    "districts",
    "document_text",
    "documents",
    "fetch_queue",
    "high_courts",
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
APPEND_ONLY_TABLES = ["events", "audit_log", "case_notes", "custody_history", "case_stages"]
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
ALL_TABLES = [
    "acts",
    "advocates",
    "alerts",
    "assistant_conversations",
    "assistant_messages",
    "audit_log",
    "benches",
    "case_acts",
    "case_advocates",
    "case_applications",
    "case_hearings",
    "case_links",
    "case_lower_courts",
    "case_note_attachments",
    "case_notes",
    "case_objections",
    "case_office_scores",
    "case_ownership",
    "case_parties",
    "case_snapshots",
    "case_stages",
    "case_transfers",
    "case_types",
    "case_writ_info",
    "cases",
    "causelist_bench_days",
    "causelist_entries",
    "causelist_reconciliations",
    "causelists",
    "counsel_codes",
    "courts",
    "custody",
    "custody_history",
    "designations",
    "digests",
    "districts",
    "document_text",
    "documents",
    "events",
    "fetch_queue",
    "high_courts",
    "job_runs",
    "master_sync_runs",
    "napix_call_log",
    "napix_responses",
    "next_dates",
    "notifications",
    "office_keywords",
    "office_name_patterns",
    "office_watchlist",
    "offices",
    "orders",
    "otp_codes",
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
    "ref_sequences",
    "refresh_tokens",
    "request_messages",
    "requests",
    "source_failures",
    "sourcetrace_ingestions",
    "states",
    "user_notification_preferences",
    "users",
]

UUID_V7 = """
CREATE OR REPLACE FUNCTION uuid_generate_v7() RETURNS uuid
LANGUAGE sql VOLATILE PARALLEL SAFE AS $$
  SELECT encode(
    set_bit(set_bit(
      overlay(uuid_send(gen_random_uuid())
              placing substring(int8send((extract(epoch from clock_timestamp())*1000)::bigint) from 3)
              from 1 for 6),
      52, 1), 53, 1), 'hex')::uuid;
$$;
"""
SET_UPDATED_AT = """
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END $$;
"""
FORBID_CHANGE = """
CREATE OR REPLACE FUNCTION aslms_forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'table % is append-only (ASLMS)', TG_TABLE_NAME USING ERRCODE = 'restrict_violation';
END $$;
"""
ROLES = """
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aslms_owner') THEN CREATE ROLE aslms_owner NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aslms_app') THEN CREATE ROLE aslms_app LOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aslms_readonly') THEN CREATE ROLE aslms_readonly LOGIN; END IF;
END $$;
"""


def _set_role_passwords() -> None:
    """Passwords come from .env (ASLMS_APP_PASSWORD, ASLMS_READONLY_PASSWORD); unset means the role keeps
    whatever it has (no login possible until an administrator sets one). Never logged."""
    from aslms.core.config import get_settings

    s = get_settings()
    for role, secret in (("aslms_app", s.aslms_app_password), ("aslms_readonly", s.aslms_readonly_password)):
        if secret is not None and secret.get_secret_value():
            pw = secret.get_secret_value().replace("'", "''")
            op.execute(f"ALTER ROLE {role} PASSWORD '{pw}'")


def _create_enum_types() -> None:
    bind = op.get_bind()
    for name, values in ENUM_TYPES.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)


def _drop_enum_types() -> None:
    bind = op.get_bind()
    for name in ENUM_TYPES:
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)


def upgrade() -> None:
    op.execute(UUID_V7)
    op.execute(SET_UPDATED_AT)
    op.execute(FORBID_CHANGE)
    _create_enum_types()
    _create_tables()
    for name, table, referent, cols, refcols, ondelete in USE_ALTER_FKS:
        op.create_foreign_key(name, table, referent, cols, refcols, ondelete=ondelete)
    for table in MUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION aslms_forbid_change()"
        )
    op.execute(ROLES)
    _set_role_passwords()
    op.execute("GRANT USAGE ON SCHEMA public TO aslms_owner, aslms_app, aslms_readonly")
    op.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO aslms_owner")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO aslms_readonly")
    op.execute("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO aslms_app")
    op.execute("REVOKE ALL ON alembic_version FROM aslms_app, aslms_readonly")
    op.execute(f"REVOKE UPDATE ON {', '.join(APPEND_ONLY_TABLES + ['napix_call_log'])} FROM aslms_app")
    op.execute(f"GRANT DELETE ON {', '.join(CASCADE_TABLES)} TO aslms_app")


def downgrade() -> None:
    for name, table, _referent, _cols, _refcols, _ondelete in reversed(USE_ALTER_FKS):
        op.drop_constraint(name, table, type_="foreignkey")
    _drop_tables()
    _drop_enum_types()
    op.execute("DROP FUNCTION IF EXISTS aslms_forbid_change()")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    op.execute("DROP FUNCTION IF EXISTS uuid_generate_v7()")
    # roles are cluster-wide and shared with other databases: kept


def _create_tables() -> None:
    op.create_table(
        "acts",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("national_act_code", sa.String(length=20), nullable=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_acts")),
        sa.UniqueConstraint("name", name=op.f("uq_acts_name")),
        sa.UniqueConstraint("national_act_code", name=op.f("uq_acts_national_act_code")),
        comment="class=master",
    )
    op.create_table(
        "advocates",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("bar_reg_no", sa.String(length=40), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("name_normalised", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_advocates")),
        sa.UniqueConstraint("bar_reg_no", name=op.f("uq_advocates_bar_reg_no")),
        comment="class=master",
    )
    op.create_index(op.f("ix_advocates_name_normalised"), "advocates", ["name_normalised"], unique=False)
    op.create_table(
        "designations",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("valid_from", sa.Date(), server_default=sa.text("current_date"), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_designations")),
        sa.UniqueConstraint("code", name=op.f("uq_designations_code")),
        comment="class=master",
    )
    op.create_table(
        "high_courts",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("napix_state_code", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_high_courts")),
        sa.UniqueConstraint("name", name=op.f("uq_high_courts_name")),
        sa.UniqueConstraint("napix_state_code", name=op.f("uq_high_courts_napix_state_code")),
        comment="class=master",
    )
    op.create_table(
        "job_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("job", sa.String(length=60), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
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
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_runs")),
        comment="class=derived",
    )
    op.create_index(op.f("ix_job_runs_job"), "job_runs", ["job"], unique=False)
    op.create_index(op.f("ix_job_runs_run_date"), "job_runs", ["run_date"], unique=False)
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
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("row_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("inserted", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("deactivated", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_master_sync_runs")),
        comment="class=derived",
    )
    op.create_table(
        "ref_alert_kind",
        sa.Column("default_severity", sa.String(length=20), server_default="normal", nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_ref_case_stage")),
        comment="class=reference",
    )
    op.create_table(
        "ref_doc_type",
        sa.Column("doc_group", sa.String(length=20), server_default="court_filing", nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_ref_doc_type")),
        comment="class=reference",
    )
    op.create_table(
        "ref_event_type",
        sa.Column("timeline_label", sa.String(length=120), nullable=True),
        sa.Column("icon_key", sa.String(length=40), nullable=True),
        sa.Column("is_tracking_card", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_ref_role")),
        comment="class=reference",
    )
    op.create_table(
        "source_failures",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("ref", sa.String(length=300), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("error_family", sa.String(length=40), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_failures")),
        sa.UniqueConstraint("kind", "ref", name=op.f("uq_source_failures_kind_ref")),
        comment="class=derived",
    )
    op.create_index(op.f("ix_source_failures_kind"), "source_failures", ["kind"], unique=False)
    op.create_table(
        "states",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("lgd_code", sa.Integer(), nullable=True),
        sa.Column("ecourts_code", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_states")),
        sa.UniqueConstraint("ecourts_code", name=op.f("uq_states_ecourts_code")),
        sa.UniqueConstraint("lgd_code", name=op.f("uq_states_lgd_code")),
        sa.UniqueConstraint("name", name=op.f("uq_states_name")),
        comment="class=master",
    )
    op.create_table(
        "courts",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("est_code", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("high_court_id", sa.UUID(), nullable=True),
        sa.Column("napix_bench_no", sa.Integer(), nullable=True),
        sa.Column("bench_location", sa.String(length=200), nullable=True),
        sa.Column(
            "court_level",
            postgresql.ENUM("hc", "dc", name="court_level", create_type=False),
            server_default="hc",
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["high_court_id"],
            ["high_courts.id"],
            name=op.f("fk_courts_high_court_id_high_courts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_courts")),
        sa.UniqueConstraint("est_code", name=op.f("uq_courts_est_code")),
        comment="class=master",
    )
    op.create_index(op.f("ix_courts_high_court_id"), "courts", ["high_court_id"], unique=False)
    op.create_table(
        "districts",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("state_id", sa.UUID(), nullable=False),
        sa.Column("high_court_id", sa.UUID(), nullable=True),
        sa.Column("lgd_code", sa.Integer(), nullable=True),
        sa.Column("ecourts_code", sa.Integer(), nullable=True),
        sa.Column("ecourts_name", sa.String(length=100), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM("district", "agency", name="district_kind", create_type=False),
            server_default="district",
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["high_court_id"],
            ["high_courts.id"],
            name=op.f("fk_districts_high_court_id_high_courts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["state_id"], ["states.id"], name=op.f("fk_districts_state_id_states"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_districts")),
        sa.UniqueConstraint(
            "high_court_id", "ecourts_code", name=op.f("uq_districts_high_court_id_ecourts_code")
        ),
        sa.UniqueConstraint("lgd_code", name=op.f("uq_districts_lgd_code")),
        sa.UniqueConstraint("state_id", "name", name=op.f("uq_districts_state_id_name")),
        comment="class=master",
    )
    op.create_index(op.f("ix_districts_high_court_id"), "districts", ["high_court_id"], unique=False)
    op.create_index(op.f("ix_districts_state_id"), "districts", ["state_id"], unique=False)
    op.create_table(
        "fetch_queue",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "masters",
                "causelist_day",
                "dossier",
                "status_batch",
                "order_pdf",
                name="fetch_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("ref", sa.String(length=300), nullable=False),
        sa.Column("priority", sa.SmallInteger(), server_default=sa.text("50"), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "running",
                "done",
                "failed",
                "skipped",
                name="fetch_queue_status",
                create_type=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("job_run_id", sa.UUID(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_run_id"],
            ["job_runs.id"],
            name=op.f("fk_fetch_queue_job_run_id_job_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fetch_queue")),
        sa.UniqueConstraint("kind", "ref", name=op.f("uq_fetch_queue_kind_ref")),
        comment="class=derived",
    )
    op.create_index(op.f("ix_fetch_queue_job_run_id"), "fetch_queue", ["job_run_id"], unique=False)
    op.create_index(op.f("ix_fetch_queue_not_before"), "fetch_queue", ["not_before"], unique=False)
    op.create_index(op.f("ix_fetch_queue_priority"), "fetch_queue", ["priority"], unique=False)
    op.create_index(op.f("ix_fetch_queue_status"), "fetch_queue", ["status"], unique=False)
    op.create_table(
        "napix_call_log",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("api", sa.String(length=80), nullable=False),
        sa.Column("params_sha256", sa.String(length=64), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("napix_status", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error_family", sa.String(length=40), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("token_verified", sa.Boolean(), nullable=True),
        sa.Column("rate_limit_remaining", sa.Integer(), nullable=True),
        sa.Column("called_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("job_run_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["job_run_id"],
            ["job_runs.id"],
            name=op.f("fk_napix_call_log_job_run_id_job_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_napix_call_log")),
        comment="class=derived",
    )
    op.create_index(op.f("ix_napix_call_log_api"), "napix_call_log", ["api"], unique=False)
    op.create_index(op.f("ix_napix_call_log_called_at"), "napix_call_log", ["called_at"], unique=False)
    op.create_index(op.f("ix_napix_call_log_job_run_id"), "napix_call_log", ["job_run_id"], unique=False)
    op.create_table(
        "napix_responses",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("api", sa.String(length=80), nullable=False),
        sa.Column("params_sha256", sa.String(length=64), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("token_verified", sa.Boolean(), nullable=True),
        sa.Column("job_run_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_run_id"],
            ["job_runs.id"],
            name=op.f("fk_napix_responses_job_run_id_job_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_napix_responses")),
        sa.UniqueConstraint(
            "api",
            "params_sha256",
            "payload_sha256",
            name=op.f("uq_napix_responses_api_params_sha256_payload_sha256"),
        ),
        comment="class=derived",
    )
    op.create_index(op.f("ix_napix_responses_api"), "napix_responses", ["api"], unique=False)
    op.create_index(op.f("ix_napix_responses_job_run_id"), "napix_responses", ["job_run_id"], unique=False)
    op.create_table(
        "offices",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "state",
                "central",
                "department",
                "directorate",
                "advocate_general",
                "unit",
                name="officekind",
                native_enum=False,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("path", sa.String(length=400), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("valid_from", sa.Date(), server_default=sa.text("current_date"), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["kind"],
            ["ref_office_kind.code"],
            name=op.f("fk_offices_kind_ref_office_kind"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["offices.id"], name=op.f("fk_offices_parent_id_offices"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_offices")),
        sa.UniqueConstraint("code", name=op.f("uq_offices_code")),
        comment="class=master",
    )
    op.create_index(op.f("ix_offices_kind"), "offices", ["kind"], unique=False)
    op.create_index(op.f("ix_offices_parent_id"), "offices", ["parent_id"], unique=False)
    op.create_index(op.f("ix_offices_path"), "offices", ["path"], unique=False)
    op.create_table(
        "ref_sequences",
        sa.Column("office_code", sa.String(length=20), nullable=False),
        sa.Column("record_type", sa.String(length=10), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("last_value", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
        "benches",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("court_id", sa.UUID(), nullable=False),
        sa.Column("bench_id", sa.Integer(), nullable=False),
        sa.Column("judge_names", sa.Text(), nullable=True),
        sa.Column("bench_name", sa.String(length=100), nullable=True),
        sa.Column("bench_type_code", sa.Integer(), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.Column("type_name", sa.String(length=300), nullable=False),
        sa.Column("short_name", sa.String(length=60), nullable=True),
        sa.Column("full_name", sa.String(length=300), nullable=True),
        sa.Column("aliases", postgresql.ARRAY(sa.String(length=60)), server_default="{}", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["court_id"], ["courts.id"], name=op.f("fk_case_types_court_id_courts"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_types")),
        sa.UniqueConstraint("court_id", "case_type_code", name=op.f("uq_case_types_court_id_case_type_code")),
        comment="class=master",
    )
    op.create_index(op.f("ix_case_types_court_id"), "case_types", ["court_id"], unique=False)
    op.create_index(op.f("ix_case_types_short_name"), "case_types", ["short_name"], unique=False)
    op.create_table(
        "causelist_bench_days",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("court_id", sa.UUID(), nullable=False),
        sa.Column("list_date", sa.Date(), nullable=False),
        sa.Column("bench_id", sa.Integer(), nullable=False),
        sa.Column("judge_names_as_listed", sa.Text(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["court_id"],
            ["courts.id"],
            name=op.f("fk_causelist_bench_days_court_id_courts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_causelist_bench_days")),
        sa.UniqueConstraint(
            "court_id",
            "list_date",
            "bench_id",
            name=op.f("uq_causelist_bench_days_court_id_list_date_bench_id"),
        ),
        comment="class=transaction",
    )
    op.create_index(
        op.f("ix_causelist_bench_days_court_id"), "causelist_bench_days", ["court_id"], unique=False
    )
    op.create_index(
        op.f("ix_causelist_bench_days_list_date"), "causelist_bench_days", ["list_date"], unique=False
    )
    op.create_table(
        "causelists",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("court_id", sa.UUID(), nullable=False),
        sa.Column("list_date", sa.Date(), nullable=False),
        sa.Column("bench_id", sa.Integer(), nullable=True),
        sa.Column("napix_causelist_id", sa.Integer(), nullable=True),
        sa.Column(
            "list_type",
            postgresql.ENUM(
                "daily", "supplementary", "lawazima", "vacation", "other", name="list_type", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("list_type_text", sa.String(length=100), nullable=True),
        sa.Column("bench_label", sa.Text(), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column(
            "source",
            postgresql.ENUM("napix", "ghc_website", "local_dir", name="list_source", create_type=False),
            nullable=False,
        ),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column(
            "fetch_status",
            postgresql.ENUM(
                "pending", "fetched", "failed", "not_available", name="fetch_status", create_type=False
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "parse_status",
            postgresql.ENUM("pending", "parsed", "failed", "empty", name="parse_status", create_type=False),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("entry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["court_id"], ["courts.id"], name=op.f("fk_causelists_court_id_courts"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_causelists")),
        sa.UniqueConstraint(
            "court_id",
            "list_date",
            "bench_id",
            "napix_causelist_id",
            "source",
            "list_type",
            name=op.f("uq_causelists_court_id_list_date_bench_id_napix_causelist_id_source_list_type"),
            postgresql_nulls_not_distinct=True,
        ),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_causelists_court_id"), "causelists", ["court_id"], unique=False)
    op.create_index(op.f("ix_causelists_document_id"), "causelists", ["document_id"], unique=False)
    op.create_index(op.f("ix_causelists_list_date"), "causelists", ["list_date"], unique=False)
    op.create_table(
        "counsel_codes",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("code", sa.String(length=60), nullable=False),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column(
            "weight", sa.Numeric(precision=4, scale=3), server_default=sa.text("0.950"), nullable=False
        ),
        sa.Column("is_generic_state", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["office_id"],
            ["offices.id"],
            name=op.f("fk_counsel_codes_office_id_offices"),
            ondelete="RESTRICT",
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
        sa.Column(
            "weight", sa.Numeric(precision=4, scale=3), server_default=sa.text("0.400"), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["office_id"],
            ["offices.id"],
            name=op.f("fk_office_keywords_office_id_offices"),
            ondelete="RESTRICT",
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
        sa.Column(
            "weight", sa.Numeric(precision=4, scale=3), server_default=sa.text("0.800"), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["office_id"],
            ["offices.id"],
            name=op.f("fk_office_name_patterns_office_id_offices"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_office_name_patterns")),
        sa.UniqueConstraint(
            "office_id", "pattern", "kind", name=op.f("uq_office_name_patterns_office_id_pattern_kind")
        ),
        comment="class=master",
    )
    op.create_index(
        op.f("ix_office_name_patterns_office_id"), "office_name_patterns", ["office_id"], unique=False
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("mobile", sa.String(length=20), nullable=True),
        sa.Column("password_hash", sa.String(length=300), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("designation", sa.String(length=200), nullable=True),
        sa.Column("designation_id", sa.UUID(), nullable=True),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "state_oversight",
                "dept_head",
                "dept_admin",
                "dept_officer",
                "directorate_user",
                "referral_reviewer",
                "standing_counsel",
                "central_operator",
                "auditor",
                name="role",
                native_enum=False,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("must_confirm_profile", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("valid_from", sa.Date(), server_default=sa.text("current_date"), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["office_id"], ["offices.id"], name=op.f("fk_users_office_id_offices"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["role"], ["ref_role.code"], name=op.f("fk_users_role_ref_role"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        comment="class=master",
    )
    op.create_index(op.f("ix_users_designation_id"), "users", ["designation_id"], unique=False)
    op.create_index(op.f("ix_users_office_id"), "users", ["office_id"], unique=False)
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)
    op.create_table(
        "cases",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("cnr", sa.String(length=16), nullable=True),
        sa.Column("court_id", sa.UUID(), nullable=False),
        sa.Column("court_est_name", sa.String(length=200), nullable=True),
        sa.Column("case_type_id", sa.UUID(), nullable=True),
        sa.Column("case_type_text", sa.String(length=60), nullable=True),
        sa.Column("reg_no", sa.Integer(), nullable=True),
        sa.Column("reg_year", sa.SmallInteger(), nullable=True),
        sa.Column("case_no_text", sa.String(length=80), nullable=True),
        sa.Column("filing_case_type_id", sa.UUID(), nullable=True),
        sa.Column("filing_case_type_text", sa.String(length=60), nullable=True),
        sa.Column("filing_no", sa.Integer(), nullable=True),
        sa.Column("filing_year", sa.SmallInteger(), nullable=True),
        sa.Column("filing_no_text", sa.String(length=80), nullable=True),
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
        sa.Column("date_judgement_pronounced", sa.Date(), nullable=True),
        sa.Column("date_judgement_reserved", sa.Date(), nullable=True),
        sa.Column("goshwara_no", sa.String(length=10), nullable=True),
        sa.Column("next_hearing_date", sa.Date(), nullable=True),
        sa.Column("next_purpose", sa.String(length=200), nullable=True),
        sa.Column("last_hearing_date", sa.Date(), nullable=True),
        sa.Column("bench_id", sa.UUID(), nullable=True),
        sa.Column("napix_bench_id", sa.Integer(), nullable=True),
        sa.Column("bench_name", sa.String(length=100), nullable=True),
        sa.Column("bench_type_code", sa.Integer(), nullable=True),
        sa.Column("coram", sa.Text(), nullable=True),
        sa.Column("coram_designation", sa.String(length=100), nullable=True),
        sa.Column("judicial_branch", sa.String(length=200), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("category_code", sa.Integer(), nullable=True),
        sa.Column("sub_category", sa.Text(), nullable=True),
        sa.Column("state_id", sa.UUID(), nullable=True),
        sa.Column("district_id", sa.UUID(), nullable=True),
        sa.Column("state_name_as_listed", sa.String(length=100), nullable=True),
        sa.Column("district_name_as_listed", sa.String(length=100), nullable=True),
        sa.Column("filing_state_code", sa.Integer(), nullable=True),
        sa.Column("filing_district_code", sa.Integer(), nullable=True),
        sa.Column("fir_no", sa.String(length=40), nullable=True),
        sa.Column("fir_year", sa.SmallInteger(), nullable=True),
        sa.Column("police_station", sa.String(length=200), nullable=True),
        sa.Column("police_st_code", sa.String(length=20), nullable=True),
        sa.Column("uniform_code", sa.String(length=20), nullable=True),
        sa.Column("main_matter_text", sa.String(length=200), nullable=True),
        sa.Column("petitioner_summary", sa.Text(), nullable=True),
        sa.Column("respondent_summary", sa.Text(), nullable=True),
        sa.Column("pet_advocate", sa.Text(), nullable=True),
        sa.Column("res_advocate", sa.Text(), nullable=True),
        sa.Column("is_provisional", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_tracked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "first_seen_source",
            postgresql.ENUM(
                "causelist", "search", "discovery", "link", name="first_seen_source", create_type=False
            ),
            server_default="causelist",
            nullable=False,
        ),
        sa.Column("last_full_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dossier_stale", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("merged_into_case_id", sa.UUID(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ref_no", sa.String(length=40), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
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
    op.create_index(op.f("ix_cases_case_no_text"), "cases", ["case_no_text"], unique=False)
    op.create_index(op.f("ix_cases_case_type_id"), "cases", ["case_type_id"], unique=False)
    op.create_index(op.f("ix_cases_court_id"), "cases", ["court_id"], unique=False)
    op.create_index(op.f("ix_cases_district_id"), "cases", ["district_id"], unique=False)
    op.create_index(op.f("ix_cases_filing_case_type_id"), "cases", ["filing_case_type_id"], unique=False)
    op.create_index(op.f("ix_cases_merged_into_case_id"), "cases", ["merged_into_case_id"], unique=False)
    op.create_index(op.f("ix_cases_next_hearing_date"), "cases", ["next_hearing_date"], unique=False)
    op.create_index(op.f("ix_cases_state_id"), "cases", ["state_id"], unique=False)
    op.create_index(op.f("ix_cases_status"), "cases", ["status"], unique=False)
    op.create_table(
        "causelist_reconciliations",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("causelist_id", sa.UUID(), nullable=False),
        sa.Column("cnr", sa.String(length=16), nullable=True),
        sa.Column("in_napix", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("in_pdf", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("mismatch_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["causelist_id"],
            ["causelists.id"],
            name=op.f("fk_causelist_reconciliations_causelist_id_causelists"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_causelist_reconciliations")),
        comment="class=derived",
    )
    op.create_index(
        op.f("ix_causelist_reconciliations_causelist_id"),
        "causelist_reconciliations",
        ["causelist_id"],
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
        "otp_codes",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "purpose",
            postgresql.ENUM("login", "password_reset", "new_device", name="otp_purpose", create_type=False),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(length=300), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_otp_codes_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_otp_codes")),
        comment="class=derived",
    )
    op.create_index(op.f("ix_otp_codes_user_id"), "otp_codes", ["user_id"], unique=False)
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=300), nullable=False),
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
        "user_notification_preferences",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "channel",
            postgresql.ENUM("in_app", "email", "sms", name="notification_channel", create_type=False),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "digest",
            postgresql.ENUM("none", "daily", name="digest_mode", create_type=False),
            server_default="none",
            nullable=False,
        ),
        sa.Column("critical_only", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "hearing_due",
                "next_date_changed",
                "new_order",
                "status_changed",
                "compliance_due",
                "request_due",
                "recommendation",
                name="alertkind",
                native_enum=False,
                length=40,
            ),
            nullable=False,
        ),
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
        sa.Column("dedupe_key", sa.String(length=300), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_alerts_dedupe_key")),
        sa.UniqueConstraint("ref_no", name=op.f("uq_alerts_ref_no")),
        comment="class=transaction",
    )
    op.create_index(
        op.f("ix_alerts_acknowledged_by_user_id"), "alerts", ["acknowledged_by_user_id"], unique=False
    )
    op.create_index(op.f("ix_alerts_case_id"), "alerts", ["case_id"], unique=False)
    op.create_index(op.f("ix_alerts_due_at"), "alerts", ["due_at"], unique=False)
    op.create_index(op.f("ix_alerts_kind"), "alerts", ["kind"], unique=False)
    op.create_index(op.f("ix_alerts_source_event_id"), "alerts", ["source_event_id"], unique=False)
    op.create_index(op.f("ix_alerts_status"), "alerts", ["status"], unique=False)
    op.create_table(
        "assistant_conversations",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column(
            "scope",
            postgresql.ENUM("case", "research", name="assistant_scope", create_type=False),
            server_default="case",
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
        op.f("ix_assistant_conversations_case_id"), "assistant_conversations", ["case_id"], unique=False
    )
    op.create_index(
        op.f("ix_assistant_conversations_user_id"), "assistant_conversations", ["user_id"], unique=False
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=60), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=40), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_audit_log_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
        comment="class=derived",
    )
    op.create_index(op.f("ix_audit_log_action"), "audit_log", ["action"], unique=False)
    op.create_index(op.f("ix_audit_log_case_id"), "audit_log", ["case_id"], unique=False)
    op.create_index(op.f("ix_audit_log_entity_id"), "audit_log", ["entity_id"], unique=False)
    op.create_table(
        "case_acts",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("act_name_as_listed", sa.String(length=300), nullable=False),
        sa.Column("act_id", sa.UUID(), nullable=True),
        sa.Column("national_act_code", sa.String(length=20), nullable=True),
        sa.Column("section", sa.String(length=200), server_default="", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
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
            postgresql.ENUM("petitioner", "respondent", name="advocate_side", create_type=False),
            nullable=False,
        ),
        sa.Column("name_as_listed", sa.String(length=300), nullable=False),
        sa.Column("advocate_id", sa.UUID(), nullable=True),
        sa.Column("bar_reg_no", sa.String(length=40), nullable=True),
        sa.Column("counsel_code", sa.String(length=60), nullable=True),
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
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
        sa.UniqueConstraint(
            "case_id", "side", "name_as_listed", name=op.f("uq_case_advocates_case_id_side_name_as_listed")
        ),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_case_advocates_advocate_id"), "case_advocates", ["advocate_id"], unique=False)
    op.create_index(op.f("ix_case_advocates_case_id"), "case_advocates", ["case_id"], unique=False)
    op.create_index(op.f("ix_case_advocates_counsel_code"), "case_advocates", ["counsel_code"], unique=False)
    op.create_table(
        "case_applications",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("ia_number", sa.String(length=80), nullable=False),
        sa.Column("party_name", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=1), nullable=True),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
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
        sa.Column("business_date", sa.Date(), nullable=True),
        sa.Column("hearing_date", sa.Date(), nullable=True),
        sa.Column("purpose", sa.String(length=200), server_default="", nullable=False),
        sa.Column("bench_text", sa.Text(), nullable=True),
        sa.Column("judge_designation", sa.String(length=100), nullable=True),
        sa.Column("causelist_type", sa.String(length=60), nullable=True),
        sa.Column("case_number_text", sa.String(length=80), nullable=True),
        sa.Column("business_text", sa.Text(), nullable=True),
        sa.Column("short_order_text", sa.Text(), nullable=True),
        sa.Column(
            "source",
            postgresql.ENUM(
                "dossier", "show_business", "causelist", name="hearing_source", create_type=False
            ),
            server_default="dossier",
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
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
        sa.Column("to_case_no_text", sa.String(length=200), server_default="", nullable=False),
        sa.Column("to_cnr", sa.String(length=16), nullable=True),
        sa.Column("filing_number_text", sa.String(length=200), nullable=True),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "main_matter",
                "connected",
                "linked",
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
            postgresql.ENUM("dossier", "causelist", "manual", name="link_source", create_type=False),
            server_default="dossier",
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
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
    op.create_index(op.f("ix_case_links_to_cnr"), "case_links", ["to_cnr"], unique=False)
    op.create_table(
        "case_lower_courts",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column(
            "level",
            postgresql.ENUM("appellate", "trial", name="lower_court_level", create_type=False),
            nullable=False,
        ),
        sa.Column("court_name", sa.String(length=300), nullable=True),
        sa.Column("case_no_text", sa.String(length=200), nullable=True),
        sa.Column("decision_date", sa.Date(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
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
        sa.Column("seq", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("objection", sa.Text(), nullable=True),
        sa.Column("scrutiny_date", sa.Date(), nullable=False),
        sa.Column("compliance_by_date", sa.Date(), nullable=True),
        sa.Column("receipt_date", sa.Date(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_case_objections_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_objections")),
        sa.UniqueConstraint(
            "case_id", "scrutiny_date", "seq", name=op.f("uq_case_objections_case_id_scrutiny_date_seq")
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
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("engine_version", sa.String(length=20), nullable=False),
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
    op.create_table(
        "case_ownership",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM("primary", "watcher", name="ownership_role", create_type=False),
            server_default="primary",
            nullable=False,
        ),
        sa.Column("officer_user_id", sa.UUID(), nullable=True),
        sa.Column("unit_office_id", sa.UUID(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM("active", "transferred", "released", name="ownership_status", create_type=False),
            server_default="active",
            nullable=False,
        ),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=40), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
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
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_ownership")),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_case_ownership_case_id"), "case_ownership", ["case_id"], unique=False)
    op.create_index(op.f("ix_case_ownership_office_id"), "case_ownership", ["office_id"], unique=False)
    op.create_index(
        op.f("ix_case_ownership_officer_user_id"), "case_ownership", ["officer_user_id"], unique=False
    )
    op.create_index(op.f("ix_case_ownership_status"), "case_ownership", ["status"], unique=False)
    op.create_index(
        op.f("ix_case_ownership_unit_office_id"), "case_ownership", ["unit_office_id"], unique=False
    )
    op.create_table(
        "case_parties",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM("petitioner", "respondent", name="party_role", create_type=False),
            nullable=False,
        ),
        sa.Column("party_no", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_normalised", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("has_legal_heir", sa.Boolean(), nullable=True),
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
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
    op.create_index(
        op.f("ix_case_parties_name_normalised"), "case_parties", ["name_normalised"], unique=False
    )
    op.create_table(
        "case_snapshots",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column(
            "source",
            postgresql.ENUM("cnr", "current_status", name="snapshot_source", create_type=False),
            nullable=False,
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
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
    op.create_index(op.f("ix_case_snapshots_case_id"), "case_snapshots", ["case_id"], unique=False)
    op.create_table(
        "case_stages",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column(
            "stage",
            sa.Enum(
                "notice_received",
                "parawise_comments_sought",
                "parawise_comments_received",
                "counsel_briefed",
                "affidavit_drafted",
                "affidavit_vetted",
                "affidavit_filed",
                "hearing_pending",
                "order_received",
                "order_under_examination",
                "compliance_in_progress",
                "compliance_reported",
                "appeal_under_consideration",
                "appeal_filed",
                "contempt_notice",
                "contempt_reply_filed",
                "closed",
                name="stage",
                native_enum=False,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column(
            "response_mode",
            postgresql.ENUM("department", "counsel", "none", name="response_mode", create_type=False),
            server_default="department",
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=40), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
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
    op.create_index(op.f("ix_case_stages_case_id"), "case_stages", ["case_id"], unique=False)
    op.create_index(op.f("ix_case_stages_office_id"), "case_stages", ["office_id"], unique=False)
    op.create_index(op.f("ix_case_stages_stage"), "case_stages", ["stage"], unique=False)
    op.create_table(
        "case_transfers",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("transfer_date", sa.Date(), nullable=True),
        sa.Column("from_court_text", sa.String(length=300), nullable=True),
        sa.Column("to_court_text", sa.String(length=300), server_default="", nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_case_transfers_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_transfers")),
        sa.UniqueConstraint(
            "case_id",
            "transfer_date",
            "to_court_text",
            name=op.f("uq_case_transfers_case_id_transfer_date_to_court_text"),
        ),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_case_transfers_case_id"), "case_transfers", ["case_id"], unique=False)
    op.create_table(
        "case_writ_info",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("appellate_case_number", sa.String(length=200), nullable=False),
        sa.Column("appellate_authority", sa.String(length=200), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name=op.f("fk_case_writ_info_case_id_cases"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_writ_info")),
        sa.UniqueConstraint(
            "case_id", "appellate_case_number", name=op.f("uq_case_writ_info_case_id_appellate_case_number")
        ),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_case_writ_info_case_id"), "case_writ_info", ["case_id"], unique=False)
    op.create_table(
        "causelist_entries",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("causelist_id", sa.UUID(), nullable=False),
        sa.Column("sr_no", sa.Integer(), nullable=False),
        sa.Column("printed_sr_no", sa.String(length=20), nullable=True),
        sa.Column("court_no", sa.String(length=20), nullable=True),
        sa.Column("bench_text", sa.Text(), nullable=True),
        sa.Column("section", sa.String(length=200), nullable=True),
        sa.Column("cnr", sa.String(length=16), nullable=True),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("case_no_text", sa.String(length=200), nullable=True),
        sa.Column("is_connected", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("petitioner_text", sa.Text(), nullable=True),
        sa.Column("respondent_text", sa.Text(), nullable=True),
        sa.Column("pet_advocate_text", sa.Text(), nullable=True),
        sa.Column("res_advocate_text", sa.Text(), nullable=True),
        sa.Column(
            "counsel_codes", postgresql.ARRAY(sa.String(length=60)), server_default="{}", nullable=False
        ),
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
    op.create_index(op.f("ix_causelist_entries_case_id"), "causelist_entries", ["case_id"], unique=False)
    op.create_index(
        op.f("ix_causelist_entries_case_no_text"), "causelist_entries", ["case_no_text"], unique=False
    )
    op.create_index(
        op.f("ix_causelist_entries_causelist_id"), "causelist_entries", ["causelist_id"], unique=False
    )
    op.create_index(op.f("ix_causelist_entries_cnr"), "causelist_entries", ["cnr"], unique=False)
    op.create_table(
        "custody",
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("holder_office_id", sa.UUID(), nullable=False),
        sa.Column("holder_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "pending_action",
            postgresql.ENUM(
                "none",
                "examine",
                "reply",
                "file",
                "comply",
                "review",
                name="pending_action",
                create_type=False,
            ),
            server_default="none",
            nullable=False,
        ),
        sa.Column("since", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
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
        sa.PrimaryKeyConstraint("case_id", name=op.f("pk_custody")),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_custody_current_leg_id"), "custody", ["current_leg_id"], unique=False)
    op.create_index(op.f("ix_custody_holder_office_id"), "custody", ["holder_office_id"], unique=False)
    op.create_index(op.f("ix_custody_holder_user_id"), "custody", ["holder_user_id"], unique=False)
    op.create_index(op.f("ix_custody_request_id"), "custody", ["request_id"], unique=False)
    op.create_table(
        "custody_history",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("seq_no", sa.Integer(), nullable=False),
        sa.Column("holder_office_id", sa.UUID(), nullable=False),
        sa.Column("holder_office_code", sa.String(length=40), nullable=False),
        sa.Column("holder_user_id", sa.UUID(), nullable=True),
        sa.Column("holder_user_name", sa.String(length=200), nullable=True),
        sa.Column("reason", sa.String(length=60), nullable=False),
        sa.Column(
            "pending_action",
            postgresql.ENUM(
                "none",
                "examine",
                "reply",
                "file",
                "comply",
                "review",
                name="pending_action",
                create_type=False,
            ),
            server_default="none",
            nullable=False,
        ),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("request_id", sa.UUID(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=40), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custody_history")),
        sa.UniqueConstraint("case_id", "seq_no", name=op.f("uq_custody_history_case_id_seq_no")),
        comment="class=derived",
    )
    op.create_index(op.f("ix_custody_history_case_id"), "custody_history", ["case_id"], unique=False)
    op.create_index(
        op.f("ix_custody_history_holder_office_id"), "custody_history", ["holder_office_id"], unique=False
    )
    op.create_index(
        op.f("ix_custody_history_holder_user_id"), "custody_history", ["holder_user_id"], unique=False
    )
    op.create_index(op.f("ix_custody_history_request_id"), "custody_history", ["request_id"], unique=False)
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=400), nullable=False),
        sa.Column("mime", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("original_filename", sa.String(length=300), nullable=True),
        sa.Column(
            "kind",
            postgresql.ENUM("causelist", "order", "upload", "attachment", name="doc_kind", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "doc_type",
            sa.Enum(
                "causelist",
                "order",
                "judgment",
                "petition",
                "affidavit",
                "counter_affidavit",
                "rejoinder",
                "written_submission",
                "parawise_comments",
                "legal_opinion",
                "compliance_report",
                "correspondence",
                "other",
                name="doctype",
                native_enum=False,
                length=40,
            ),
            nullable=False,
        ),
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
                "case_scope", "counsel_shared", "private_to_office", name="doc_visibility", create_type=False
            ),
            server_default="case_scope",
            nullable=False,
        ),
        sa.Column("office_id", sa.UUID(), nullable=True),
        sa.Column(
            "virus_scan_status",
            postgresql.ENUM(
                "pending", "clean", "infected", "failed", "skipped", name="scan_status", create_type=False
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "text_status",
            postgresql.ENUM("pending", "extracted", "failed", "none", name="text_status", create_type=False),
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
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ref_no", sa.String(length=40), nullable=True),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=40), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
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
            ["office_id"], ["offices.id"], name=op.f("fk_documents_office_id_offices"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("ref_no", name=op.f("uq_documents_ref_no")),
        sa.UniqueConstraint("sha256", name=op.f("uq_documents_sha256")),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_documents_case_id"), "documents", ["case_id"], unique=False)
    op.create_index(op.f("ix_documents_doc_type"), "documents", ["doc_type"], unique=False)
    op.create_index(op.f("ix_documents_office_id"), "documents", ["office_id"], unique=False)
    op.create_table(
        "events",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column(
            "type",
            sa.Enum(
                "case_created",
                "case_updated",
                "case_disposed",
                "case_linked",
                "listed",
                "listed_supplementary",
                "next_date_extracted",
                "next_date_changed",
                "status_changed",
                "order_found",
                "order_stored",
                "document_uploaded",
                "recommendation_made",
                "claimed",
                "dismissed",
                "suggested_elsewhere",
                "transfer_requested",
                "transfer_decided",
                "ownership_released",
                "allotted",
                "custody_moved",
                "request_sent",
                "request_answered",
                "stage_set",
                "note_added",
                "alert_raised",
                "source_failed",
                "masters_synced",
                "config_changed",
                name="eventtype",
                native_enum=False,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
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
    op.create_index(op.f("ix_events_actor_user_id"), "events", ["actor_user_id"], unique=False)
    op.create_index(op.f("ix_events_case_id"), "events", ["case_id"], unique=False)
    op.create_index(op.f("ix_events_occurred_at"), "events", ["occurred_at"], unique=False)
    op.create_index(op.f("ix_events_type"), "events", ["type"], unique=False)
    op.create_table(
        "office_watchlist",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column("cnr", sa.String(length=16), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "weight", sa.Numeric(precision=4, scale=3), server_default=sa.text("0.750"), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=40), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
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
    op.create_index(op.f("ix_office_watchlist_cnr"), "office_watchlist", ["cnr"], unique=False)
    op.create_index(op.f("ix_office_watchlist_office_id"), "office_watchlist", ["office_id"], unique=False)
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
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=40), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
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
                "rescore",
                "search",
                "suggestion",
                "watchlist",
                name="recommendation_origin",
                create_type=False,
            ),
            server_default="cause_list",
            nullable=False,
        ),
        sa.Column("suggested_office_id", sa.UUID(), nullable=True),
        sa.Column("acted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=40), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
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
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendations")),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_recommendations_case_id"), "recommendations", ["case_id"], unique=False)
    op.create_index(op.f("ix_recommendations_office_id"), "recommendations", ["office_id"], unique=False)
    op.create_index(op.f("ix_recommendations_status"), "recommendations", ["status"], unique=False)
    op.create_index(
        op.f("ix_recommendations_suggested_office_id"),
        "recommendations",
        ["suggested_office_id"],
        unique=False,
    )
    op.create_table(
        "requests",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "report",
                "parawise_comments",
                "documents",
                "opinion",
                "instructions",
                "compliance",
                "clarification",
                "other",
                name="requestkind",
                native_enum=False,
                length=40,
            ),
            nullable=False,
        ),
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
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=40), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
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
    op.create_index(
        op.f("ix_requests_answered_by_user_id"), "requests", ["answered_by_user_id"], unique=False
    )
    op.create_index(op.f("ix_requests_case_id"), "requests", ["case_id"], unique=False)
    op.create_index(op.f("ix_requests_from_office_id"), "requests", ["from_office_id"], unique=False)
    op.create_index(op.f("ix_requests_kind"), "requests", ["kind"], unique=False)
    op.create_index(op.f("ix_requests_status"), "requests", ["status"], unique=False)
    op.create_index(op.f("ix_requests_to_office_id"), "requests", ["to_office_id"], unique=False)
    op.create_index(op.f("ix_requests_to_user_id"), "requests", ["to_user_id"], unique=False)
    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM("user", "assistant", "system", name="message_role", create_type=False),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model_info", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        op.f("ix_assistant_messages_conversation_id"), "assistant_messages", ["conversation_id"], unique=False
    )
    op.create_table(
        "case_notes",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("seq_no", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "general",
                "decision",
                "instruction",
                "hearing",
                "counsel_advice",
                "compliance",
                "file_noting",
                "correction",
                name="notekind",
                native_enum=False,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "visibility",
            postgresql.ENUM(
                "case_scope", "counsel_shared", "private_to_office", name="doc_visibility", create_type=False
            ),
            server_default="case_scope",
            nullable=False,
        ),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column("author_role", sa.String(length=40), nullable=False),
        sa.Column("custody_leg_id", sa.UUID(), nullable=True),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column(
            "source",
            postgresql.ENUM("user", "system", name="note_source", create_type=False),
            server_default="user",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ref_no", sa.String(length=40), nullable=False),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=40), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
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
    op.create_index(op.f("ix_case_notes_case_id"), "case_notes", ["case_id"], unique=False)
    op.create_index(op.f("ix_case_notes_custody_leg_id"), "case_notes", ["custody_leg_id"], unique=False)
    op.create_index(op.f("ix_case_notes_kind"), "case_notes", ["kind"], unique=False)
    op.create_index(op.f("ix_case_notes_office_id"), "case_notes", ["office_id"], unique=False)
    op.create_index(op.f("ix_case_notes_supersedes_id"), "case_notes", ["supersedes_id"], unique=False)
    op.create_table(
        "document_text",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("full_text", sa.Text(), nullable=True),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
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
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("alert_id", sa.UUID(), nullable=False),
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
        sa.Column("dedupe_key", sa.String(length=300), nullable=False),
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
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False)
    op.create_table(
        "orders",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("order_no", sa.String(length=20), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM("interim", "final", "judgment", name="order_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("order_details", sa.String(length=200), nullable=True),
        sa.Column("order_judge_name", sa.Text(), nullable=True),
        sa.Column("date_judgement_pronounced", sa.Date(), nullable=True),
        sa.Column("date_judgement_reserved", sa.Date(), nullable=True),
        sa.Column("is_reportable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column(
            "download_status",
            postgresql.ENUM(
                "pending", "stored", "failed", "not_available", name="download_status", create_type=False
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("download_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
    op.create_index(op.f("ix_orders_download_status"), "orders", ["download_status"], unique=False)
    op.create_index(op.f("ix_orders_order_date"), "orders", ["order_date"], unique=False)
    op.create_table(
        "request_messages",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_answer", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_designation", sa.String(length=200), nullable=True),
        sa.Column("actor_office_code", sa.String(length=40), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
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
        sa.Column("attempt", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("reference", sa.String(length=200), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata_sent", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        op.f("ix_sourcetrace_ingestions_document_id"), "sourcetrace_ingestions", ["document_id"], unique=False
    )
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
        sa.Column(
            "confidence", sa.Numeric(precision=4, scale=3), server_default=sa.text("1.000"), nullable=False
        ),
        sa.Column("needs_review", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "review_status",
            postgresql.ENUM(
                "not_needed", "pending", "confirmed", "rejected", name="review_status", create_type=False
            ),
            server_default="not_needed",
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
            ["order_id"], ["orders.id"], name=op.f("fk_next_dates_order_id_orders"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            name=op.f("fk_next_dates_reviewed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_next_dates")),
        sa.UniqueConstraint(
            "case_id",
            "next_date",
            "source",
            "order_id",
            name=op.f("uq_next_dates_case_id_next_date_source_order_id"),
            postgresql_nulls_not_distinct=True,
        ),
        sa.UniqueConstraint("ref_no", name=op.f("uq_next_dates_ref_no")),
        comment="class=transaction",
    )
    op.create_index(op.f("ix_next_dates_case_id"), "next_dates", ["case_id"], unique=False)
    op.create_index(op.f("ix_next_dates_next_date"), "next_dates", ["next_date"], unique=False)
    op.create_index(op.f("ix_next_dates_order_id"), "next_dates", ["order_id"], unique=False)
    op.create_index(
        op.f("ix_next_dates_reviewed_by_user_id"), "next_dates", ["reviewed_by_user_id"], unique=False
    )


def _drop_tables() -> None:
    op.drop_index(op.f("ix_next_dates_reviewed_by_user_id"), table_name="next_dates")
    op.drop_index(op.f("ix_next_dates_order_id"), table_name="next_dates")
    op.drop_index(op.f("ix_next_dates_next_date"), table_name="next_dates")
    op.drop_index(op.f("ix_next_dates_case_id"), table_name="next_dates")
    op.drop_table("next_dates")
    op.drop_index(op.f("ix_case_note_attachments_note_id"), table_name="case_note_attachments")
    op.drop_index(op.f("ix_case_note_attachments_document_id"), table_name="case_note_attachments")
    op.drop_table("case_note_attachments")
    op.drop_index(op.f("ix_sourcetrace_ingestions_document_id"), table_name="sourcetrace_ingestions")
    op.drop_table("sourcetrace_ingestions")
    op.drop_index(op.f("ix_request_messages_request_id"), table_name="request_messages")
    op.drop_table("request_messages")
    op.drop_index(op.f("ix_orders_order_date"), table_name="orders")
    op.drop_index(op.f("ix_orders_download_status"), table_name="orders")
    op.drop_index(op.f("ix_orders_document_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_case_id"), table_name="orders")
    op.drop_table("orders")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_alert_id"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("document_text")
    op.drop_index(op.f("ix_case_notes_supersedes_id"), table_name="case_notes")
    op.drop_index(op.f("ix_case_notes_office_id"), table_name="case_notes")
    op.drop_index(op.f("ix_case_notes_kind"), table_name="case_notes")
    op.drop_index(op.f("ix_case_notes_custody_leg_id"), table_name="case_notes")
    op.drop_index(op.f("ix_case_notes_case_id"), table_name="case_notes")
    op.drop_table("case_notes")
    op.drop_index(op.f("ix_assistant_messages_conversation_id"), table_name="assistant_messages")
    op.drop_table("assistant_messages")
    op.drop_index(op.f("ix_requests_to_user_id"), table_name="requests")
    op.drop_index(op.f("ix_requests_to_office_id"), table_name="requests")
    op.drop_index(op.f("ix_requests_status"), table_name="requests")
    op.drop_index(op.f("ix_requests_kind"), table_name="requests")
    op.drop_index(op.f("ix_requests_from_office_id"), table_name="requests")
    op.drop_index(op.f("ix_requests_case_id"), table_name="requests")
    op.drop_index(op.f("ix_requests_answered_by_user_id"), table_name="requests")
    op.drop_table("requests")
    op.drop_index(op.f("ix_recommendations_suggested_office_id"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_status"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_office_id"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_case_id"), table_name="recommendations")
    op.drop_table("recommendations")
    op.drop_index(op.f("ix_ownership_transfers_to_office_id"), table_name="ownership_transfers")
    op.drop_index(op.f("ix_ownership_transfers_from_office_id"), table_name="ownership_transfers")
    op.drop_index(op.f("ix_ownership_transfers_decided_by_user_id"), table_name="ownership_transfers")
    op.drop_index(op.f("ix_ownership_transfers_case_id"), table_name="ownership_transfers")
    op.drop_table("ownership_transfers")
    op.drop_index(op.f("ix_office_watchlist_office_id"), table_name="office_watchlist")
    op.drop_index(op.f("ix_office_watchlist_cnr"), table_name="office_watchlist")
    op.drop_index(op.f("ix_office_watchlist_case_id"), table_name="office_watchlist")
    op.drop_table("office_watchlist")
    op.drop_index(op.f("ix_events_type"), table_name="events")
    op.drop_index(op.f("ix_events_occurred_at"), table_name="events")
    op.drop_index(op.f("ix_events_case_id"), table_name="events")
    op.drop_index(op.f("ix_events_actor_user_id"), table_name="events")
    op.drop_table("events")
    op.drop_index(op.f("ix_documents_office_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_doc_type"), table_name="documents")
    op.drop_index(op.f("ix_documents_case_id"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_custody_history_request_id"), table_name="custody_history")
    op.drop_index(op.f("ix_custody_history_holder_user_id"), table_name="custody_history")
    op.drop_index(op.f("ix_custody_history_holder_office_id"), table_name="custody_history")
    op.drop_index(op.f("ix_custody_history_case_id"), table_name="custody_history")
    op.drop_table("custody_history")
    op.drop_index(op.f("ix_custody_request_id"), table_name="custody")
    op.drop_index(op.f("ix_custody_holder_user_id"), table_name="custody")
    op.drop_index(op.f("ix_custody_holder_office_id"), table_name="custody")
    op.drop_index(op.f("ix_custody_current_leg_id"), table_name="custody")
    op.drop_table("custody")
    op.drop_index(op.f("ix_causelist_entries_cnr"), table_name="causelist_entries")
    op.drop_index(op.f("ix_causelist_entries_causelist_id"), table_name="causelist_entries")
    op.drop_index(op.f("ix_causelist_entries_case_no_text"), table_name="causelist_entries")
    op.drop_index(op.f("ix_causelist_entries_case_id"), table_name="causelist_entries")
    op.drop_table("causelist_entries")
    op.drop_index(op.f("ix_case_writ_info_case_id"), table_name="case_writ_info")
    op.drop_table("case_writ_info")
    op.drop_index(op.f("ix_case_transfers_case_id"), table_name="case_transfers")
    op.drop_table("case_transfers")
    op.drop_index(op.f("ix_case_stages_stage"), table_name="case_stages")
    op.drop_index(op.f("ix_case_stages_office_id"), table_name="case_stages")
    op.drop_index(op.f("ix_case_stages_case_id"), table_name="case_stages")
    op.drop_table("case_stages")
    op.drop_index(op.f("ix_case_snapshots_case_id"), table_name="case_snapshots")
    op.drop_table("case_snapshots")
    op.drop_index(op.f("ix_case_parties_name_normalised"), table_name="case_parties")
    op.drop_index(op.f("ix_case_parties_case_id"), table_name="case_parties")
    op.drop_table("case_parties")
    op.drop_index(op.f("ix_case_ownership_unit_office_id"), table_name="case_ownership")
    op.drop_index(op.f("ix_case_ownership_status"), table_name="case_ownership")
    op.drop_index(op.f("ix_case_ownership_officer_user_id"), table_name="case_ownership")
    op.drop_index(op.f("ix_case_ownership_office_id"), table_name="case_ownership")
    op.drop_index(op.f("ix_case_ownership_case_id"), table_name="case_ownership")
    op.drop_table("case_ownership")
    op.drop_index(op.f("ix_case_office_scores_office_id"), table_name="case_office_scores")
    op.drop_index(op.f("ix_case_office_scores_case_id"), table_name="case_office_scores")
    op.drop_table("case_office_scores")
    op.drop_index(op.f("ix_case_objections_case_id"), table_name="case_objections")
    op.drop_table("case_objections")
    op.drop_index(op.f("ix_case_lower_courts_case_id"), table_name="case_lower_courts")
    op.drop_table("case_lower_courts")
    op.drop_index(op.f("ix_case_links_to_cnr"), table_name="case_links")
    op.drop_index(op.f("ix_case_links_to_case_id"), table_name="case_links")
    op.drop_index(op.f("ix_case_links_from_case_id"), table_name="case_links")
    op.drop_table("case_links")
    op.drop_index(op.f("ix_case_hearings_case_id"), table_name="case_hearings")
    op.drop_table("case_hearings")
    op.drop_index(op.f("ix_case_applications_case_id"), table_name="case_applications")
    op.drop_table("case_applications")
    op.drop_index(op.f("ix_case_advocates_counsel_code"), table_name="case_advocates")
    op.drop_index(op.f("ix_case_advocates_case_id"), table_name="case_advocates")
    op.drop_index(op.f("ix_case_advocates_advocate_id"), table_name="case_advocates")
    op.drop_table("case_advocates")
    op.drop_index(op.f("ix_case_acts_case_id"), table_name="case_acts")
    op.drop_index(op.f("ix_case_acts_act_id"), table_name="case_acts")
    op.drop_table("case_acts")
    op.drop_index(op.f("ix_audit_log_entity_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_case_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_action"), table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index(op.f("ix_assistant_conversations_user_id"), table_name="assistant_conversations")
    op.drop_index(op.f("ix_assistant_conversations_case_id"), table_name="assistant_conversations")
    op.drop_table("assistant_conversations")
    op.drop_index(op.f("ix_alerts_status"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_source_event_id"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_kind"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_due_at"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_case_id"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_acknowledged_by_user_id"), table_name="alerts")
    op.drop_table("alerts")
    op.drop_index(
        op.f("ix_user_notification_preferences_user_id"), table_name="user_notification_preferences"
    )
    op.drop_table("user_notification_preferences")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index(op.f("ix_otp_codes_user_id"), table_name="otp_codes")
    op.drop_table("otp_codes")
    op.drop_index(op.f("ix_digests_user_id"), table_name="digests")
    op.drop_table("digests")
    op.drop_index(op.f("ix_causelist_reconciliations_causelist_id"), table_name="causelist_reconciliations")
    op.drop_table("causelist_reconciliations")
    op.drop_index(op.f("ix_cases_status"), table_name="cases")
    op.drop_index(op.f("ix_cases_state_id"), table_name="cases")
    op.drop_index(op.f("ix_cases_next_hearing_date"), table_name="cases")
    op.drop_index(op.f("ix_cases_merged_into_case_id"), table_name="cases")
    op.drop_index(op.f("ix_cases_filing_case_type_id"), table_name="cases")
    op.drop_index(op.f("ix_cases_district_id"), table_name="cases")
    op.drop_index(op.f("ix_cases_court_id"), table_name="cases")
    op.drop_index(op.f("ix_cases_case_type_id"), table_name="cases")
    op.drop_index(op.f("ix_cases_case_no_text"), table_name="cases")
    op.drop_index(op.f("ix_cases_bench_id"), table_name="cases")
    op.drop_table("cases")
    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_index(op.f("ix_users_office_id"), table_name="users")
    op.drop_index(op.f("ix_users_designation_id"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_office_name_patterns_office_id"), table_name="office_name_patterns")
    op.drop_table("office_name_patterns")
    op.drop_index(op.f("ix_office_keywords_office_id"), table_name="office_keywords")
    op.drop_table("office_keywords")
    op.drop_index(op.f("ix_counsel_codes_office_id"), table_name="counsel_codes")
    op.drop_table("counsel_codes")
    op.drop_index(op.f("ix_causelists_list_date"), table_name="causelists")
    op.drop_index(op.f("ix_causelists_document_id"), table_name="causelists")
    op.drop_index(op.f("ix_causelists_court_id"), table_name="causelists")
    op.drop_table("causelists")
    op.drop_index(op.f("ix_causelist_bench_days_list_date"), table_name="causelist_bench_days")
    op.drop_index(op.f("ix_causelist_bench_days_court_id"), table_name="causelist_bench_days")
    op.drop_table("causelist_bench_days")
    op.drop_index(op.f("ix_case_types_short_name"), table_name="case_types")
    op.drop_index(op.f("ix_case_types_court_id"), table_name="case_types")
    op.drop_table("case_types")
    op.drop_index(op.f("ix_benches_court_id"), table_name="benches")
    op.drop_table("benches")
    op.drop_table("ref_sequences")
    op.drop_index(op.f("ix_offices_path"), table_name="offices")
    op.drop_index(op.f("ix_offices_parent_id"), table_name="offices")
    op.drop_index(op.f("ix_offices_kind"), table_name="offices")
    op.drop_table("offices")
    op.drop_index(op.f("ix_napix_responses_job_run_id"), table_name="napix_responses")
    op.drop_index(op.f("ix_napix_responses_api"), table_name="napix_responses")
    op.drop_table("napix_responses")
    op.drop_index(op.f("ix_napix_call_log_job_run_id"), table_name="napix_call_log")
    op.drop_index(op.f("ix_napix_call_log_called_at"), table_name="napix_call_log")
    op.drop_index(op.f("ix_napix_call_log_api"), table_name="napix_call_log")
    op.drop_table("napix_call_log")
    op.drop_index(op.f("ix_fetch_queue_status"), table_name="fetch_queue")
    op.drop_index(op.f("ix_fetch_queue_priority"), table_name="fetch_queue")
    op.drop_index(op.f("ix_fetch_queue_not_before"), table_name="fetch_queue")
    op.drop_index(op.f("ix_fetch_queue_job_run_id"), table_name="fetch_queue")
    op.drop_table("fetch_queue")
    op.drop_index(op.f("ix_districts_state_id"), table_name="districts")
    op.drop_index(op.f("ix_districts_high_court_id"), table_name="districts")
    op.drop_table("districts")
    op.drop_index(op.f("ix_courts_high_court_id"), table_name="courts")
    op.drop_table("courts")
    op.drop_table("states")
    op.drop_index(op.f("ix_source_failures_kind"), table_name="source_failures")
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
    op.drop_index(op.f("ix_job_runs_run_date"), table_name="job_runs")
    op.drop_index(op.f("ix_job_runs_job"), table_name="job_runs")
    op.drop_table("job_runs")
    op.drop_table("high_courts")
    op.drop_table("designations")
    op.drop_index(op.f("ix_advocates_name_normalised"), table_name="advocates")
    op.drop_table("advocates")
    op.drop_table("acts")
