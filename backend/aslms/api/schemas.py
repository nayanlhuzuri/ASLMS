"""Pydantic request/response models (the API contract the Next.js portal is built against)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# E-mail shape only: pydantic's Email rejects reserved domains such as `.local`, which the seed and demo
# accounts use, and government mail domains vary. Delivery itself proves the address.
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_lower=True, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    ),
]

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    total: int
    page: int
    size: int
    items: list[T]


class Ok(BaseModel):
    ok: bool = True
    detail: str | None = None


# ------------------------------------------------------------------ auth
class LoginIn(BaseModel):
    email: Email
    password: str


class Challenge(BaseModel):
    challenge_id: uuid.UUID
    detail: str = "A one-time password has been sent to your e-mail."
    resend_after: int = 120  # seconds before "Resend code" may be used


class ResendIn(BaseModel):
    challenge_id: uuid.UUID


class VerifyIn(BaseModel):
    challenge_id: uuid.UUID
    code: str = Field(min_length=6, max_length=6)


class Tokens(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshIn(BaseModel):
    refresh_token: str


class ForgotIn(BaseModel):
    email: Email


class ResetIn(BaseModel):
    challenge_id: uuid.UUID
    code: str
    new_password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


# ------------------------------------------------------------------ org
class OfficeOut(ORM):
    id: uuid.UUID
    code: str
    name: str
    kind: str
    parent_id: uuid.UUID | None
    path: str
    is_active: bool


class OfficeIn(BaseModel):
    code: str
    name: str
    kind: str
    parent_id: uuid.UUID | None = None


class OfficePatch(BaseModel):
    name: str | None = None
    is_active: bool | None = None


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    designation: str | None
    mobile: str | None
    office_id: uuid.UUID
    role: str
    is_active: bool
    must_confirm_profile: bool
    last_login_at: datetime | None


class MeOut(UserOut):
    office: OfficeOut
    department: OfficeOut | None
    read_only: bool
    can_claim: bool
    can_admin: bool


class UserIn(BaseModel):
    email: Email
    full_name: str
    office_id: uuid.UUID
    role: str
    password: str
    designation: str | None = None
    mobile: str | None = None


class UserPatch(BaseModel):
    full_name: str | None = None
    designation: str | None = None
    mobile: str | None = None
    office_id: uuid.UUID | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


class PreferenceOut(BaseModel):
    channel: str
    enabled: bool
    digest: str
    critical_only: bool


class PreferenceIn(BaseModel):
    channel: str
    enabled: bool = True
    digest: str = "none"
    critical_only: bool = False


class ProfileIn(BaseModel):
    full_name: str | None = None
    designation: str | None = None
    mobile: str | None = None


# ------------------------------------------------------------------ cases
class OwnerRef(BaseModel):
    office_id: str
    code: str
    name: str


class Owners(BaseModel):
    primary: OwnerRef | None = None
    watchers: list[OwnerRef] = []


class CustodyOut(BaseModel):
    """Where the case is right now (eOffice-style custody), part of the tracking card."""

    holder_office: OwnerRef
    holder_user: str | None
    pending_action: str | None
    since: datetime
    due_date: date | None
    days_pending: int
    overdue: bool


class CaseCard(BaseModel):
    """Tracking card: visible to every signed-in user."""

    id: uuid.UUID
    cnr: str | None
    case_no: str | None
    filing_no: str | None
    case_type: str | None
    reg_year: int | None
    status: str
    is_provisional: bool
    petitioner: str | None
    respondent: str | None
    next_hearing_date: date | None
    next_purpose: str | None
    last_hearing_date: date | None
    disposal_date: date | None
    court: str | None = None
    owners: Owners = Owners()
    custody: CustodyOut | None = None
    stage: str | None = None
    in_scope: bool = False


class PartyOut(ORM):
    role: str
    party_no: int
    name: str
    address: str | None


class AdvocateOut(ORM):
    side: str
    name: str
    counsel_code: str | None


class HearingOut(ORM):
    business_date: date
    purpose: str
    bench_text: str | None
    next_date: date | None
    business_text: str | None
    source: str


class ActOut(ORM):
    act_name: str
    section: str


class LinkOut(BaseModel):
    kind: str
    direction: str  # out | in
    case_no: str | None
    cnr: str | None
    case_id: uuid.UUID | None
    status: str | None = None


class OrderOut(ORM):
    id: uuid.UUID
    order_no: str
    order_date: date
    kind: str
    is_reportable: bool
    download_status: str
    document_id: uuid.UUID | None


class DocumentOut(ORM):
    id: uuid.UUID
    kind: str
    doc_type: str
    doc_group: str
    original_filename: str | None
    mime: str
    size_bytes: int
    doc_date: date | None
    description: str | None
    visibility: str
    virus_scan_status: str
    text_status: str
    sourcetrace_status: str
    actor_name: str | None
    actor_designation: str | None
    actor_office_code: str | None
    created_at: datetime


class NextDateOut(ORM):
    id: uuid.UUID
    next_date: date
    source: str
    order_id: uuid.UUID | None
    confidence: float | None
    needs_review: bool
    review_status: str
    note: str | None
    created_at: datetime


class OwnershipOut(BaseModel):
    id: uuid.UUID
    office: OwnerRef
    role: str
    status: str
    unit: OwnerRef | None
    officer: dict[str, Any] | None
    claimed_at: datetime
    claimed_by: str | None


class CaseDetail(CaseCard):
    filing_date: date | None = None
    registration_date: date | None = None
    disposal_nature: str | None = None
    coram: str | None = None
    category: str | None = None
    judicial_branch: str | None = None
    pet_advocate: str | None = None
    res_advocate: str | None = None
    is_tracked: bool = False
    last_full_refresh_at: datetime | None = None
    last_status_refresh_at: datetime | None = None
    first_seen_source: str | None = None
    parties: list[PartyOut] = []
    advocates: list[AdvocateOut] = []
    acts: list[ActOut] = []
    ownership: list[OwnershipOut] = []
    latest_order: OrderOut | None = None
    next_dates: list[NextDateOut] = []


class EventOut(ORM):
    id: uuid.UUID
    type: str
    occurred_at: datetime
    payload: dict[str, Any]
    visibility: str


class ListingOut(BaseModel):
    list_date: date
    list_type: str
    source: str
    court_no: str | None
    sr_no: int
    case_no: str | None
    section: str | None
    bench: str | None
    counsel_codes: list[str]
    causelist_id: uuid.UUID


class SignalOut(BaseModel):
    """One reason behind a department's score."""

    kind: str  # counsel_code | name_pattern | keyword | watchlist | link_history | suggested_unit
    value: str
    weight: float
    office: str | None = None
    matched_text: str | None = None


class ScoreOut(BaseModel):
    office: OwnerRef
    score: float
    signals: list[SignalOut]
    computed_at: datetime


# ------------------------------------------------------------------ ownership
class ClaimIn(BaseModel):
    office_id: uuid.UUID | None = None  # required only for the central operator
    reason: str | None = None


class DismissIn(BaseModel):
    office_id: uuid.UUID | None = None
    reason: str
    suggest_office_id: uuid.UUID | None = None


class TransferIn(BaseModel):
    office_id: uuid.UUID | None = None
    to_office_id: uuid.UUID
    reason: str


class DecideIn(BaseModel):
    office_id: uuid.UUID | None = None
    reason: str | None = None


class AllotIn(BaseModel):
    office_id: uuid.UUID | None = None
    unit_office_id: uuid.UUID | None = None
    officer_user_id: uuid.UUID | None = None


class ReleaseIn(BaseModel):
    office_id: uuid.UUID | None = None
    reason: str


class ListingRef(BaseModel):
    """The latest cause-list appearance of the recommended case."""

    list_date: date
    list_type: str
    court_no: str | None
    item: str | None
    section: str | None


class RecommendationOut(BaseModel):
    id: uuid.UUID
    case: CaseCard
    score: float
    band: str
    origin: str
    signals: list[SignalOut]
    listing: ListingRef | None = None
    reason: str | None
    created_at: datetime


class TransferOut(BaseModel):
    id: uuid.UUID
    case: CaseCard
    direction: str  # incoming | outgoing
    from_office: OwnerRef
    to_office: OwnerRef
    status: str
    reason: str | None
    requested_by: str | None
    created_at: datetime
    decided_at: datetime | None


# ------------------------------------------------------------------ alerts & notifications
class AlertOut(ORM):
    id: uuid.UUID
    case_id: uuid.UUID | None
    kind: str
    due_at: datetime | None
    severity: str
    status: str
    title: str
    body: str | None
    created_at: datetime


class NotificationOut(ORM):
    id: uuid.UUID
    alert_id: uuid.UUID | None
    case_id: uuid.UUID | None = None
    channel: str
    status: str
    title: str
    body: str | None
    created_at: datetime
    read_at: datetime | None


class CalendarItem(BaseModel):
    date: date
    case: CaseCard
    purpose: str | None
    severity: str


class ReviewIn(BaseModel):
    confirm: bool
    next_date: date | None = None
    note: str | None = None


# ------------------------------------------------------------------ cause lists
class CauseListOut(ORM):
    id: uuid.UUID
    list_date: date
    list_type: str
    source: str
    bench_id: str
    label: str | None
    entry_count: int
    parse_status: str
    fetched_at: datetime | None
    document_id: uuid.UUID | None


class EntryOut(ORM):
    id: uuid.UUID
    sr_no: int
    court_no: str | None
    cnr: str | None
    case_id: uuid.UUID | None
    case_no_text: str | None
    petitioner_text: str | None
    respondent_text: str | None
    pet_advocate_text: str | None
    res_advocate_text: str | None
    counsel_codes: list[str]
    remarks: str | None
    source: str
    resolution_status: str
    raw: dict[str, Any] | None


# ------------------------------------------------------------------ administration
class CounselCodeIn(BaseModel):
    code: str
    office_id: uuid.UUID
    weight: float = 0.95
    is_generic_state: bool = False
    notes: str | None = None


class CounselCodeOut(ORM):
    id: uuid.UUID
    code: str
    office_id: uuid.UUID
    weight: float
    is_generic_state: bool
    notes: str | None
    is_active: bool


class PatternIn(BaseModel):
    office_id: uuid.UUID
    pattern: str
    kind: str = "exact"
    weight: float = 0.80


class PatternOut(ORM):
    id: uuid.UUID
    office_id: uuid.UUID
    pattern: str
    kind: str
    weight: float
    is_active: bool


class KeywordIn(BaseModel):
    office_id: uuid.UUID
    keyword: str
    weight: float = 0.40


class KeywordOut(ORM):
    id: uuid.UUID
    office_id: uuid.UUID
    keyword: str
    weight: float
    is_active: bool


class WatchIn(BaseModel):
    office_id: uuid.UUID | None = None
    cnr: str
    reason: str | None = None


class WatchOut(ORM):
    id: uuid.UUID
    office_id: uuid.UUID
    cnr: str
    case_id: uuid.UUID | None
    reason: str | None
    is_active: bool
    created_at: datetime


class CaseTypeOut(ORM):
    id: uuid.UUID
    case_type_code: int
    type_name: str
    full_name: str | None
    aliases: list[str]


class AuditOut(ORM):
    id: uuid.UUID
    created_at: datetime
    actor_name: str | None
    actor_designation: str | None
    actor_office_code: str | None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    case_id: uuid.UUID | None
    ip: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None


class JobIn(BaseModel):
    job: str  # daily_cycle | status_refresh | full_refresh | master_sync | discovery | rescore | alerts
    list_date: date | None = None


# ------------------------------------------------------------------ Phase 2: workflow and notes
class CustodyLegOut(BaseModel):
    seq_no: int
    holder_office: str
    holder_user: str | None
    reason: str
    pending_action: str | None
    due_date: date | None
    started_at: datetime
    moved_by: str | None
    moved_by_office: str | None


class RequestIn(BaseModel):
    kind: str
    to_office_id: uuid.UUID
    to_user_id: uuid.UUID | None = None
    subject: str
    body: str | None = None
    due_date: date | None = None


class RequestMessageOut(BaseModel):
    id: uuid.UUID
    body: str
    is_answer: bool
    author: str | None
    author_office: str | None
    created_at: datetime


class RequestOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    case_no: str | None = None
    kind: str
    from_office: OwnerRef
    to_office: OwnerRef
    to_user: str | None
    subject: str
    body: str | None
    due_date: date | None
    status: str
    overdue: bool
    requested_by: str | None
    created_at: datetime
    answered_at: datetime | None
    messages: list[RequestMessageOut] = []


class AnswerIn(BaseModel):
    body: str


class MessageIn(BaseModel):
    body: str


class WithdrawIn(BaseModel):
    reason: str | None = None


class StageIn(BaseModel):
    stage: str
    note: str | None = None
    response_mode: str | None = None


class StageOut(BaseModel):
    id: uuid.UUID
    stage: str
    response_mode: str | None
    note: str | None
    set_by: str | None
    set_by_office: str | None
    created_at: datetime


class StageSetOut(StageOut):
    skipped: list[str] = []


class HandoverIn(BaseModel):
    to_office_id: uuid.UUID
    to_user_id: uuid.UUID | None = None
    note: str
    pending_action: str | None = None
    due_date: date | None = None


class NoteAttachmentOut(BaseModel):
    document_id: uuid.UUID
    filename: str | None
    mime: str
    size_bytes: int
    virus_scan_status: str


class NoteOut(BaseModel):
    id: uuid.UUID
    seq_no: int
    kind: str
    body: str
    visibility: str
    author: str | None
    author_designation: str | None
    author_office: str | None
    author_role: str
    custody_leg_seq: int | None
    supersedes_seq: int | None
    superseded_by: list[int]
    source: str | None
    created_at: datetime
    attachments: list[NoteAttachmentOut] = []


class AskIn(BaseModel):
    question: str
    conversation_id: uuid.UUID | None = None


class AssistantMessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    citations: list[dict[str, Any]]
    created_at: datetime


class ConversationOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID | None
    scope: str
    title: str | None
    last_message_at: datetime | None
    messages: list[AssistantMessageOut] = []


class CopyToNoteIn(BaseModel):
    visibility: str = "case_scope"


# ------------------------------------------------------------------ typed responses (previously loose dicts)
class UnitCount(BaseModel):
    unit: str
    cases: int


class DepartmentCount(BaseModel):
    office_id: str
    code: str
    name: str
    pending: int


class DashboardOut(BaseModel):
    role: str
    cases_in_scope: int
    pending_cases: int
    hearings_48h: int
    hearings_week: int
    unread_notifications: int
    open_critical_alerts: int
    undelivered_email: int
    recommended_high: int | None = None
    recommended_total: int | None = None
    transfers_incoming: int | None = None
    by_unit: list[UnitCount] | None = None
    unclaimed_pending: int | None = None
    unclaimed_listed_week: int | None = None
    by_department: list[DepartmentCount] | None = None
    allotted_to_me: int | None = None


class CauseListDateOut(BaseModel):
    date: date
    lists: int
    entries: int


class UnmappedCodeOut(BaseModel):
    code: str
    seen: int


class FailureOut(BaseModel):
    id: uuid.UUID
    kind: str
    ref: str
    error: str
    attempts: int
    first_seen: datetime
    last_seen: datetime
    resolved_at: datetime | None


class ReportOut(BaseModel):
    title: str
    rows: list[dict[str, Any]]


class JobRunOut(BaseModel):
    job: str
    run_date: date | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    counters: dict[str, Any]
    error: str | None


class NapixCallStat(BaseModel):
    api: str
    calls: int
    ok: int
    avg_ms: int


class OpenFailure(BaseModel):
    id: str
    kind: str
    ref: str
    error: str
    attempts: int
    first_seen: datetime
    last_seen: datetime


class CauseListStat(BaseModel):
    date: date
    source: str
    lists: int
    entries: int


class EntrySourceStat(BaseModel):
    source: str
    entries: int
    with_cnr: int
    cnr_rate: float


class DataHealthOut(BaseModel):
    jobs: list[JobRunOut]
    napix_calls: list[NapixCallStat]
    open_failures: list[OpenFailure]
    cause_lists: list[CauseListStat]
    entries_by_source: list[EntrySourceStat]
    orders: dict[str, int]


class ConfigOut(BaseModel):
    """Settings the portal needs (no secrets)."""

    upload_max_mb: int
    allowed_upload_types: list[str]
    napix_enabled: bool
    sourcetrace_enabled: bool
    score_strong_threshold: float
    score_possible_threshold: float
    app_env: str
