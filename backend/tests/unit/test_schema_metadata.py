"""The model modules are the executable form of docs/schema/phase1.md: every table listed there must exist,
and nothing else may sneak in without updating the document."""

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
    assert set(Base.metadata.tables) == PHASE1_TABLES | PHASE2_TABLES
    assert len(PHASE1_TABLES) == 39 and len(PHASE2_TABLES) == 10


def test_every_table_has_uuid_primary_key_or_document_fk() -> None:
    for name, table in Base.metadata.tables.items():
        pk = [c.name for c in table.primary_key.columns]
        assert pk in (["id"], ["document_id"], ["case_id"]), f"{name} has an unexpected primary key {pk}"


def test_append_only_tables_have_dedupe_or_actor() -> None:
    events = Base.metadata.tables["events"]
    assert events.c.dedupe_key.unique
    audit = Base.metadata.tables["audit_log"]
    assert {"actor_user_id", "actor_name", "actor_designation", "actor_office_code"} <= set(audit.c.keys())


def test_cnr_is_nullable_only_for_provisional_cases() -> None:
    cases = Base.metadata.tables["cases"]
    assert cases.c.cnr.nullable and cases.c.cnr.unique
    assert not cases.c.is_provisional.nullable
