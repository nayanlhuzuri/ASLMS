"""Group 0 — code sets (`ref_*`) and reference-number sequences (DB_STANDARD §3, §7).

The Python enums are the ORM type of the business columns; their values are the codes stored in the
database and seeded into the `ref_*` rows."""

from __future__ import annotations

import enum

from sqlalchemy import Boolean, ForeignKey, Index, Integer, SmallInteger, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import Base, TableClass, TimestampMixin


# ---------------------------------------------------------------------- the eight user-facing code sets
class Role(enum.StrEnum):
    """The user type. `super_admin` holds every function and manages access; the others get the functions
    the type matrix (`role_permissions`) enables plus their own grants (`user_permissions`)."""

    SUPER_ADMIN = "super_admin"
    STATE_OVERSIGHT = "state_oversight"
    DEPT_HEAD = "dept_head"
    DEPT_ADMIN = "dept_admin"
    DEPT_OFFICER = "dept_officer"
    DIRECTORATE_USER = "directorate_user"
    REFERRAL_REVIEWER = "referral_reviewer"
    STANDING_COUNSEL = "standing_counsel"
    CENTRAL_OPERATOR = "central_operator"
    AUDITOR = "auditor"


class OfficeKind(enum.StrEnum):
    STATE = "state"
    CENTRAL = "central"
    DEPARTMENT = "department"
    DIRECTORATE = "directorate"
    ADVOCATE_GENERAL = "advocate_general"
    UNIT = "unit"


class Stage(enum.StrEnum):
    NOTICE_RECEIVED = "notice_received"
    PARAWISE_COMMENTS_SOUGHT = "parawise_comments_sought"
    PARAWISE_COMMENTS_RECEIVED = "parawise_comments_received"
    COUNSEL_BRIEFED = "counsel_briefed"
    AFFIDAVIT_DRAFTED = "affidavit_drafted"
    AFFIDAVIT_VETTED = "affidavit_vetted"
    AFFIDAVIT_FILED = "affidavit_filed"
    HEARING_PENDING = "hearing_pending"
    ORDER_RECEIVED = "order_received"
    ORDER_UNDER_EXAMINATION = "order_under_examination"
    COMPLIANCE_IN_PROGRESS = "compliance_in_progress"
    COMPLIANCE_REPORTED = "compliance_reported"
    APPEAL_UNDER_CONSIDERATION = "appeal_under_consideration"
    APPEAL_FILED = "appeal_filed"
    CONTEMPT_NOTICE = "contempt_notice"
    CONTEMPT_REPLY_FILED = "contempt_reply_filed"
    CLOSED = "closed"
    # case-stages-extension (migration 0016): appeal / review outcomes and the contempt track
    REVIEW_PETITION_FILED = "review_petition_filed"
    APPEAL_DISMISSED = "appeal_dismissed"
    APPEAL_ALLOWED = "appeal_allowed"
    FURTHER_APPEAL_FILED = "further_appeal_filed"
    COMPLIED_AFTER_DISMISSAL = "complied_after_dismissal"
    VAKALATNAMA_SUBMITTED = "vakalatnama_submitted"
    CONTEMPT_DISPOSED = "contempt_disposed"


class NoteKind(enum.StrEnum):
    GENERAL = "general"
    DECISION = "decision"
    INSTRUCTION = "instruction"
    HEARING = "hearing"
    COUNSEL_ADVICE = "counsel_advice"
    COMPLIANCE = "compliance"
    FILE_NOTING = "file_noting"
    CORRECTION = "correction"  # retired by custody-workflow: a correction carries the original's kind
    OPINION = "opinion"
    HAND_OVER = "hand_over"


class DocType(enum.StrEnum):
    CAUSELIST = "causelist"
    ORDER = "order"
    JUDGMENT = "judgment"
    PETITION = "petition"
    AFFIDAVIT = "affidavit"
    COUNTER_AFFIDAVIT = "counter_affidavit"
    REJOINDER = "rejoinder"
    WRITTEN_SUBMISSION = "written_submission"
    REPLY = "reply"
    INTERLOCUTORY_APPLICATION = "interlocutory_application"
    ANNEXURE = "annexure"
    PARAWISE_COMMENTS = "parawise_comments"
    LEGAL_OPINION = "legal_opinion"
    COMPLIANCE_REPORT = "compliance_report"
    CORRESPONDENCE = "correspondence"
    INSTRUCTIONS_TO_COUNSEL = "instructions_to_counsel"
    OTHER = "other"
    GOVERNMENT_ORDER = "government_order"  # supporting order of an admin ticket (design user-memberships)


class AlertKind(enum.StrEnum):
    HEARING_DUE = "hearing_due"
    NEXT_DATE_CHANGED = "next_date_changed"
    NEW_ORDER = "new_order"
    STATUS_CHANGED = "status_changed"
    COMPLIANCE_DUE = "compliance_due"
    REQUEST_DUE = "request_due"  # retired by custody-workflow (no requests)
    RECOMMENDATION = "recommendation"
    OWNERSHIP = "ownership"  # allotted, taken over, transfer requested / decided
    NEW_DOCUMENT = "new_document"
    ADMIN_TICKET = "admin_ticket"  # case-less: an admin ticket opened or decided (design user-memberships)
    WORKFLOW = (
        "workflow"  # file received, file recalled, due / overdue (design custody-workflow, decision 23)
    )
    NEXT_DATE_REVIEW = "next_date_review"  # a next date to confirm or enter (design next-date-extraction)
    NEW_NOTE = "new_note"  # a permanent note added on the case (design alerts-visibility-roles)
    LISTED_TOMORROW = "listed_tomorrow"  # on the next day's cause lists (design alerts-visibility-roles)
    NEXT_DATE_REPORTED = (
        "next_date_reported"  # a next date read from an order reported as wrong (next-date-direct)
    )


class EventType(enum.StrEnum):
    CASE_CREATED = "case_created"
    CASE_UPDATED = "case_updated"
    CASE_DISPOSED = "case_disposed"
    CASE_LINKED = "case_linked"
    LISTED = "listed"
    LISTED_SUPPLEMENTARY = "listed_supplementary"
    NEXT_DATE_EXTRACTED = "next_date_extracted"
    NEXT_DATE_CHANGED = "next_date_changed"
    STATUS_CHANGED = "status_changed"
    ORDER_FOUND = "order_found"
    ORDER_STORED = "order_stored"
    DOCUMENT_UPLOADED = "document_uploaded"
    RECOMMENDATION_MADE = "recommendation_made"
    CLAIMED = "claimed"
    DISMISSED = "dismissed"
    SUGGESTED_ELSEWHERE = "suggested_elsewhere"
    TRANSFER_REQUESTED = "transfer_requested"
    TRANSFER_DECIDED = "transfer_decided"
    OWNERSHIP_RELEASED = "ownership_released"
    ALLOTTED = "allotted"
    CUSTODY_MOVED = "custody_moved"
    REQUEST_SENT = "request_sent"  # retired by custody-workflow
    REQUEST_ANSWERED = "request_answered"  # retired by custody-workflow
    STAGE_SET = "stage_set"
    NOTE_ADDED = "note_added"
    ALERT_RAISED = "alert_raised"
    SOURCE_FAILED = "source_failed"
    MASTERS_SYNCED = "masters_synced"
    CONFIG_CHANGED = "config_changed"
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    ACCESS_CHANGED = "access_changed"
    CASE_TAKEN_OVER = "case_taken_over"
    CASE_MERGED = "case_merged"  # a provisional row merged into the row holding its CNR (data-load-console)
    NEXT_DATE_REVIEWED = "next_date_reviewed"  # confirm / reject of a read next date (next-date-extraction)
    NEXT_DATE_ENTERED = "next_date_entered"  # a manual next date (`NXT`) entered (next-date-extraction)
    RECOMMENDATION_CLOSED = (
        "recommendation_closed"  # closed by another department's claim (ownership-refinements)
    )
    LISTING_CHANGED = (
        "listing_changed"  # a corrected cause list moved, added or removed the case (court-data-freshness)
    )
    NEXT_DATE_DIFFERS = "next_date_differs"  # an exact order date differs from the court's record (next-date-direct, decision 5)


class Permission(enum.StrEnum):
    """The functions of the application, switched on or off per user type (`role_permissions`) and per user
    (`user_permissions`). The part before the dot is the module."""

    # users and access
    USERS_VIEW = "users.view"
    USERS_CREATE = "users.create"
    USERS_EDIT = "users.edit"
    USERS_SET_TYPE = "users.set_type"
    USERS_ENABLE_DISABLE = "users.enable_disable"
    USERS_GRANT = "users.grant"
    USERS_RESET_PASSWORD = "users.reset_password"
    USERS_PROPOSE_HEAD = "users.propose_head"
    ACCESS_MANAGE_TYPES = "access.manage_types"
    # administration
    OFFICES_MANAGE = "offices.manage"
    ADMIN_COUNSEL_CODES = "admin.counsel_codes"
    ADMIN_KEYWORDS = "admin.keywords"
    ADMIN_WATCHLIST = "admin.watchlist"
    ADMIN_MASTERS_SYNC = "admin.masters_sync"
    ADMIN_NAPIX_REFETCH = "admin.napix_refetch"
    ADMIN_CONFIG = "admin.config"
    ADMIN_DESIGNATIONS = "admin.designations"
    ADMIN_SCORING = "admin.scoring"
    ADMIN_TICKETS = "admin.tickets"  # reserved: the super admin's ticket panel, never granted
    ADMIN_SOURCETRACE = (
        "admin.sourcetrace"  # SourceTrace ingestion status and retries (sourcetrace-connector)
    )
    ADMIN_DATA_LOAD = "admin.data_load"  # the backdated load and duplicate checks (data-load-console)
    ADMIN_SERVICE_HEALTH = "admin.service_health"  # the System health screen (api-health-checker)
    # cases and ownership
    CASES_VIEW_SCOPE = "cases.view_scope"
    CASES_VIEW_ALL = "cases.view_all"
    CASES_VIEW_PRIVATE_ALL = (
        "cases.view_private_all"  # with view_all: private records too (alerts-visibility-roles)
    )
    CASES_SEARCH_COURT = "cases.search_court"
    CASES_CLAIM = "cases.claim"
    CASES_DISMISS = "cases.dismiss"
    CASES_SUGGEST_ELSEWHERE = "cases.suggest_elsewhere"
    CASES_TRANSFER_REQUEST = "cases.transfer_request"
    CASES_TRANSFER_DECIDE = "cases.transfer_decide"
    CASES_ALLOT = "cases.allot"
    CASES_RELEASE = "cases.release"
    CASES_TAKE_OVER = "cases.take_over"
    # custody and workflow
    CUSTODY_MOVE = "custody.move"
    CUSTODY_RECALL = "custody.recall"  # call a case of the own department back (custody-workflow, decision 6)
    CUSTODY_TRACK = "custody.track"  # pending and overdue files of the department (decision 24a)
    REQUESTS_SEND = "requests.send"  # retired by custody-workflow (sending the file replaces requests)
    REQUESTS_ANSWER = "requests.answer"  # retired by custody-workflow
    STAGES_SET = "stages.set"
    NOTES_ADD = "notes.add"
    NOTES_VIEW_COUNSEL_SHARED = "notes.view_counsel_shared"
    NOTES_VIEW_PRIVATE_OFFICE = "notes.view_private_office"
    # documents
    DOCUMENTS_UPLOAD = "documents.upload"
    DOCUMENTS_VIEW = "documents.view"
    DOCUMENTS_DOWNLOAD = "documents.download"
    # alerts and dates
    ALERTS_ACKNOWLEDGE = "alerts.acknowledge"
    NEXT_DATES_REVIEW = "next_dates.review"
    NEXT_DATES_REPORT_WRONG = "next_dates.report_wrong"  # report a misread order date (next-date-direct)
    NEXT_DATES_CORRECT = "next_dates.correct"  # correct a misread order date (next-date-direct)
    # reports and dashboards
    REPORTS_DEPARTMENT = "reports.department"
    REPORTS_STATE = "reports.state"
    DASHBOARD_STATE = "dashboard.state"
    # assistant and audit
    ASSISTANT_USE = "assistant.use"
    AUDIT_VIEW = "audit.view"

    @property
    def module(self) -> str:
        return self.value.split(".", 1)[0]


class RecordType(enum.StrEnum):
    CASE = "CASE"
    REQ = "REQ"  # retired by custody-workflow
    NOTE = "NOTE"
    DOC = "DOC"
    TRF = "TRF"
    NXT = "NXT"
    ALR = "ALR"
    TKT = "TKT"


class TicketKind(enum.StrEnum):
    """Requests that need the super admin's decision (design `user-memberships`, decision 17)."""

    HEAD_CHANGE = "head_change"


# ---------------------------------------------------------------------- tables
class RefMixin(TimestampMixin):
    __table_class__ = TableClass.REFERENCE
    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class RefRole(RefMixin, Base):
    """The user types. The label is unique without regard to case (design portal-ui-polish-2, decision 11; migration
    0026), so Edit Name can never give two types the same name."""

    __tablename__ = "ref_role"
    __table_args__ = (Index("uq_ref_role_label_lower", text("lower(label::text)"), unique=True),)


class RefOfficeKind(RefMixin, Base):
    __tablename__ = "ref_office_kind"


class RefCaseStage(RefMixin, Base):
    __tablename__ = "ref_case_stage"
    phase: Mapped[str] = mapped_column(String(20), nullable=False, server_default="main")


class RefNoteKind(RefMixin, Base):
    __tablename__ = "ref_note_kind"


class RefDocType(RefMixin, Base):
    __tablename__ = "ref_doc_type"
    doc_group: Mapped[str] = mapped_column(String(20), nullable=False, server_default="court_filing")


class RefAlertKind(RefMixin, Base):
    __tablename__ = "ref_alert_kind"
    default_severity: Mapped[str] = mapped_column(String(20), nullable=False, server_default="normal")


class RefEventType(RefMixin, Base):
    __tablename__ = "ref_event_type"
    timeline_label: Mapped[str | None] = mapped_column(String(120))
    icon_key: Mapped[str | None] = mapped_column(String(40))
    is_tracking_card: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class RefRecordType(RefMixin, Base):
    __tablename__ = "ref_record_type"


class RefTicketKind(RefMixin, Base):
    __tablename__ = "ref_ticket_kind"


class RefPermission(RefMixin, Base):
    __tablename__ = "ref_permission"
    module: Mapped[str] = mapped_column(String(40), nullable=False, index=True)


class RefSequence(Base):
    """One counter per (office, record type, year); see DB_STANDARD Appendix C."""

    __tablename__ = "ref_sequences"
    __table_class__ = TableClass.DERIVED
    office_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    record_type: Mapped[str] = mapped_column(
        String(10), ForeignKey("ref_record_type.code", ondelete="RESTRICT"), primary_key=True
    )
    year: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


REF_TABLES: dict[str, tuple[type, type[enum.Enum]]] = {
    "ref_role": (RefRole, Role),
    "ref_office_kind": (RefOfficeKind, OfficeKind),
    "ref_case_stage": (RefCaseStage, Stage),
    "ref_note_kind": (RefNoteKind, NoteKind),
    "ref_doc_type": (RefDocType, DocType),
    "ref_alert_kind": (RefAlertKind, AlertKind),
    "ref_event_type": (RefEventType, EventType),
    "ref_record_type": (RefRecordType, RecordType),
    "ref_permission": (RefPermission, Permission),
    "ref_ticket_kind": (RefTicketKind, TicketKind),
}

# Codes kept as Python members (old rows still load) but retired: `aslms seed` sets their `ref_*` rows
# `is_active = false` and disables the matrix rows of retired functions; access ignores them (design
# `custody-workflow`, decisions 15 and 22).
RETIRED_CODES: dict[str, frozenset[str]] = {
    "ref_note_kind": frozenset({NoteKind.CORRECTION.value}),
    "ref_alert_kind": frozenset({AlertKind.REQUEST_DUE.value}),
    "ref_event_type": frozenset({EventType.REQUEST_SENT.value, EventType.REQUEST_ANSWERED.value}),
    "ref_record_type": frozenset({RecordType.REQ.value}),
    "ref_permission": frozenset({Permission.REQUESTS_SEND.value, Permission.REQUESTS_ANSWER.value}),
}
RETIRED_PERMISSIONS = frozenset({Permission.REQUESTS_SEND, Permission.REQUESTS_ANSWER})
