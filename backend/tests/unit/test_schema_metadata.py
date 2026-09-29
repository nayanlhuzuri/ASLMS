"""The model modules are the executable form of docs/schema/phase1.md (docs/schema/schema.md after DB-1): every
table listed there must exist, and nothing else may sneak in without updating the document."""

from __future__ import annotations

from aslms.domain import Base

PHASE1_TABLES = {
    # group 1 — organisation and auth
    "offices",
    "users",
    "otp_codes",
    "refresh_tokens",
    "user_notification_preferences",
    # group 2 — reference
    "courts",
    "benches",
    "case_types",
    "master_sync_runs",
    # group 3 — cases
    "cases",
    "case_parties",
    "case_advocates",
    "case_hearings",
    "case_acts",
    "case_links",
    "case_snapshots",
    # group 4 — cause lists
    "causelists",
    "causelist_entries",
    "causelist_reconciliations",
    # group 5 — ownership
    "counsel_codes",
    "office_name_patterns",
    "office_keywords",
    "office_watchlist",
    "case_office_scores",
    "recommendations",
    "case_ownership",
    "ownership_transfers",
    # group 6 — documents
    "documents",
    "document_text",
    "orders",
    # group 7 — alerts
    "next_dates",
    "alerts",
    "notifications",
    "digests",
    # group 8 — events and audit
    "events",
    "audit_log",
    # group 9 — operations
    "job_runs",
    "napix_call_log",
    "source_failures",
}

DB1_TABLES = {
    # DB_STANDARD §7 code sets and §3 sequences
    "ref_role",
    "ref_office_kind",
    "ref_case_stage",
    "ref_request_kind",
    "ref_note_kind",
    "ref_doc_type",
    "ref_alert_kind",
    "ref_event_type",
    "ref_record_type",
    "ref_sequences",
    # masters
    "designations",
    "states",
    "districts",
    "acts",
    "advocates",
    # §10 dossier tables
    "case_applications",
    "case_lower_courts",
    "case_objections",
}

PHASE2_TABLES = {
    "custody",
    "custody_history",
    "requests",
    "request_messages",
    "case_stages",
    "case_notes",
    "case_note_attachments",
    "sourcetrace_ingestions",
    "assistant_conversations",
    "assistant_messages",
}


def test_phase1_tables_match_document() -> None:
    assert set(Base.metadata.tables) == PHASE1_TABLES | PHASE2_TABLES | DB1_TABLES
    assert len(PHASE1_TABLES) == 39 and len(PHASE2_TABLES) == 10 and len(DB1_TABLES) == 18


def test_every_table_has_uuid_primary_key_or_document_fk() -> None:
    """DB_STANDARD §2: `id uuid` v7, or the parent's id for 1:1 tables; `ref_*` tables use `code`."""
    for name, table in Base.metadata.tables.items():
        pk = [c.name for c in table.primary_key.columns]
        if name.startswith("ref_"):
            assert pk == ["code"] or name == "ref_sequences", f"{name} has an unexpected primary key {pk}"
            continue
        assert pk in (["id"], ["document_id"], ["case_id"]), f"{name} has an unexpected primary key {pk}"
        if pk == ["id"]:
            assert table.c.id.server_default.arg.text == "uuid_generate_v7()", name


def test_every_table_declares_its_class() -> None:
    for name, table in Base.metadata.tables.items():
        assert table.comment and table.comment.startswith("class="), name


def test_append_only_tables_have_dedupe_or_actor() -> None:
    events = Base.metadata.tables["events"]
    assert events.c.dedupe_key.unique
    audit = Base.metadata.tables["audit_log"]
    assert {"actor_user_id", "actor_name", "actor_designation", "actor_office_code"} <= set(audit.c.keys())


def test_cnr_is_nullable_only_for_provisional_cases() -> None:
    cases = Base.metadata.tables["cases"]
    assert cases.c.cnr.nullable and cases.c.cnr.unique
    assert not cases.c.is_provisional.nullable
