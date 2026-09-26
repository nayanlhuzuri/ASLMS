"""phase2 workflow

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26 21:39:06.235399
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'custody_moved'")
    op.execute("ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'request_sent'")
    op.execute("ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'request_answered'")
    op.execute("ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'request_withdrawn'")
    op.execute("ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'stage_changed'")
    op.execute("ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'note_added'")
    op.execute("ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'file_added'")
    op.execute("ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'document_ingested'")
    op.execute("ALTER TYPE alert_kind ADD VALUE IF NOT EXISTS 'request_due'")
    postgresql.ENUM(
        "notice_received",
        "records_received",
        "response_mode_decided",
        "inputs_awaited",
        "inputs_received",
        "referral_views_awaited",
        "instructions_sent",
        "affidavit_filed",
        "order_under_examination",
        "compliance_in_progress",
        "complied",
        "appeal_review_under_consideration",
        "appeal_review_instructed",
        "appeal_review_filed",
        "contempt_notice_received",
        "vakalatnama_sent",
        "appearance_entered",
        name="case_stage",
    ).create(bind, checkfirst=True)
    postgresql.ENUM("case", "research", name="conversation_scope").create(bind, checkfirst=True)
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
    postgresql.ENUM(
        "general",
        "handover",
        "instruction",
        "opinion",
        "hearing_note",
        "compliance",
        "decision",
        "system",
        name="note_kind",
    ).create(bind, checkfirst=True)
    postgresql.ENUM("case_scope", "counsel_shared", "private_to_office", name="note_visibility").create(
        bind, checkfirst=True
    )
    postgresql.ENUM(
        "records",
        "report",
        "instructions",
        "views",
        "signature",
        "implementation",
        "brief",
        "other",
        name="request_kind",
    ).create(bind, checkfirst=True)
    postgresql.ENUM("open", "answered", "withdrawn", name="request_status").create(bind, checkfirst=True)

    op.create_table(
        "assistant_conversations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_assistant_conversations_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_conversations")),
    )
    op.create_index(
        "ix_assistant_conversations_user_case",
        "assistant_conversations",
        ["user_id", "case_id"],
        unique=False,
    )
    op.create_table(
        "case_stages",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column(
            "stage",
            postgresql.ENUM(
                "notice_received",
                "records_received",
                "response_mode_decided",
                "inputs_awaited",
                "inputs_received",
                "referral_views_awaited",
                "instructions_sent",
                "affidavit_filed",
                "order_under_examination",
                "compliance_in_progress",
                "complied",
                "appeal_review_under_consideration",
                "appeal_review_instructed",
                "appeal_review_filed",
                "contempt_notice_received",
                "vakalatnama_sent",
                "appearance_entered",
                name="case_stage",
                create_type=False,
            ),
            nullable=False,
        ),
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
            ["case_id"], ["cases.id"], name=op.f("fk_case_stages_case_id_cases"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["office_id"], ["offices.id"], name=op.f("fk_case_stages_office_id_offices"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_stages")),
    )
    op.create_index(
        "ix_case_stages_case_created",
        "case_stages",
        ["case_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "requests",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "records",
                "report",
                "instructions",
                "views",
                "signature",
                "implementation",
                "brief",
                "other",
                name="request_kind",
                create_type=False,
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
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
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
            ["case_id"], ["cases.id"], name=op.f("fk_requests_case_id_cases"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["from_office_id"],
            ["offices.id"],
            name=op.f("fk_requests_from_office_id_offices"),
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
    )
    op.create_index("ix_requests_case", "requests", ["case_id"], unique=False)
    op.create_index(op.f("ix_requests_from_office_id"), "requests", ["from_office_id"], unique=False)
    op.create_index("ix_requests_to_office_status", "requests", ["to_office_id", "status"], unique=False)
    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
    )
    op.create_index(
        "ix_assistant_messages_conversation",
        "assistant_messages",
        ["conversation_id", "created_at"],
        unique=False,
    )
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
            ["case_id"], ["cases.id"], name=op.f("fk_custody_case_id_cases"), ondelete="CASCADE"
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
            ["request_id"], ["requests.id"], name=op.f("fk_custody_request_id_requests"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("case_id", name=op.f("pk_custody")),
    )
    op.create_index(op.f("ix_custody_holder_office_id"), "custody", ["holder_office_id"], unique=False)
    op.create_index(op.f("ix_custody_holder_user_id"), "custody", ["holder_user_id"], unique=False)
    op.create_table(
        "custody_history",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
            ["case_id"], ["cases.id"], name=op.f("fk_custody_history_case_id_cases"), ondelete="CASCADE"
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
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custody_history")),
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
        "request_messages",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_request_messages")),
    )
    op.create_index(op.f("ix_request_messages_request_id"), "request_messages", ["request_id"], unique=False)
    op.create_table(
        "sourcetrace_ingestions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
    )
    op.create_index(
        "ix_sourcetrace_ingestions_document",
        "sourcetrace_ingestions",
        ["document_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "case_notes",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("seq_no", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "general",
                "handover",
                "instruction",
                "opinion",
                "hearing_note",
                "compliance",
                "decision",
                "system",
                name="note_kind",
                create_type=False,
            ),
            nullable=False,
        ),
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
            ["case_id"], ["cases.id"], name=op.f("fk_case_notes_case_id_cases"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["custody_leg_id"],
            ["custody_history.id"],
            name=op.f("fk_case_notes_custody_leg_id_custody_history"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["office_id"], ["offices.id"], name=op.f("fk_case_notes_office_id_offices"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["case_notes.id"],
            name=op.f("fk_case_notes_supersedes_id_case_notes"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_notes")),
        sa.UniqueConstraint("case_id", "seq_no", name=op.f("uq_case_notes_case_id_seq_no")),
    )
    op.create_index("ix_case_notes_case_seq", "case_notes", ["case_id", "seq_no"], unique=False)
    op.create_table(
        "case_note_attachments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_note_attachments")),
        sa.UniqueConstraint(
            "note_id", "document_id", name=op.f("uq_case_note_attachments_note_id_document_id")
        ),
    )
    op.create_index(
        op.f("ix_case_note_attachments_document_id"), "case_note_attachments", ["document_id"], unique=False
    )
    op.create_index(
        op.f("ix_case_note_attachments_note_id"), "case_note_attachments", ["note_id"], unique=False
    )

    # append-only (ground rule 3): the noting trail, custody legs and stage history are never edited
    for table in ("case_notes", "custody_history", "case_stages"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION aslms_forbid_change()"
        )


def downgrade() -> None:
    # values added to event_type / alert_kind stay (PostgreSQL cannot drop enum values)
    op.drop_index(op.f("ix_case_note_attachments_note_id"), table_name="case_note_attachments")
    op.drop_index(op.f("ix_case_note_attachments_document_id"), table_name="case_note_attachments")
    op.drop_table("case_note_attachments")
    op.drop_index("ix_case_notes_case_seq", table_name="case_notes")
    op.drop_table("case_notes")
    op.drop_index("ix_sourcetrace_ingestions_document", table_name="sourcetrace_ingestions")
    op.drop_table("sourcetrace_ingestions")
    op.drop_index(op.f("ix_request_messages_request_id"), table_name="request_messages")
    op.drop_table("request_messages")
    op.drop_index(op.f("ix_custody_history_holder_office_id"), table_name="custody_history")
    op.drop_index("ix_custody_history_case_started", table_name="custody_history")
    op.drop_table("custody_history")
    op.drop_index(op.f("ix_custody_holder_user_id"), table_name="custody")
    op.drop_index(op.f("ix_custody_holder_office_id"), table_name="custody")
    op.drop_table("custody")
    op.drop_index("ix_assistant_messages_conversation", table_name="assistant_messages")
    op.drop_table("assistant_messages")
    op.drop_index("ix_requests_to_office_status", table_name="requests")
    op.drop_index(op.f("ix_requests_from_office_id"), table_name="requests")
    op.drop_index("ix_requests_case", table_name="requests")
    op.drop_table("requests")
    op.drop_index("ix_case_stages_case_created", table_name="case_stages")
    op.drop_table("case_stages")
    op.drop_index("ix_assistant_conversations_user_case", table_name="assistant_conversations")
    op.drop_table("assistant_conversations")
    bind = op.get_bind()
    postgresql.ENUM(name="request_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="request_kind").drop(bind, checkfirst=True)
    postgresql.ENUM(name="note_visibility").drop(bind, checkfirst=True)
    postgresql.ENUM(name="note_kind").drop(bind, checkfirst=True)
    postgresql.ENUM(name="custody_reason").drop(bind, checkfirst=True)
    postgresql.ENUM(name="conversation_scope").drop(bind, checkfirst=True)
    postgresql.ENUM(name="case_stage").drop(bind, checkfirst=True)
