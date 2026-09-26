"""Pydantic request/response models (the API contract the Next.js portal is built against)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

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
    email: EmailStr
    password: str


class Challenge(BaseModel):
    challenge_id: uuid.UUID
    detail: str = "A one-time password has been sent to your e-mail."


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
    email: EmailStr


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
    email: EmailStr
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


class ScoreOut(BaseModel):
    office: OwnerRef
    score: float
    signals: list[dict[str, Any]]
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


class RecommendationOut(BaseModel):
    id: uuid.UUID
    case: CaseCard
    score: float
    band: str
    origin: str
    signals: list[dict[str, Any]]
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
