"""Request and response shapes of the auth, user, access, office and designation endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from aslms.domain.reference import OfficeKind, Permission, Role


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    device_label: str | None = Field(None, max_length=200)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=400)


class OfficeOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    kind: str
    path: str
    is_active: bool = True

    @classmethod
    def from_office(cls, office: Any) -> OfficeOut:
        return cls(
            id=office.id,
            code=office.code,
            name=office.name,
            kind=str(office.kind.value),
            path=office.path,
            is_active=office.is_active,
        )


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    office: OfficeOut
    designation: str | None
    mobile: str | None
    is_active: bool
    must_confirm_profile: bool
    last_login_at: datetime | None
    created_at: datetime


class MeOut(BaseModel):
    user: UserOut
    functions: list[Permission]


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class UserCreateIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    full_name: str = Field(min_length=2, max_length=200)
    role: Role
    office_code: str = Field(min_length=1, max_length=40)
    designation: str | None = Field(None, max_length=200)
    designation_id: uuid.UUID | None = None
    mobile: str | None = Field(None, max_length=20)
    functions: list[Permission] = Field(
        default_factory=list, description="extra functions granted at creation"
    )


class UserPatchIn(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=200)
    designation: str | None = Field(None, max_length=200)
    designation_id: uuid.UUID | None = None
    mobile: str | None = Field(None, max_length=20)


class TypeIn(BaseModel):
    role: Role


class PasswordIn(BaseModel):
    password: str = Field(min_length=10, max_length=200)


class OverrideIn(BaseModel):
    effect: str | None = Field(None, pattern="^(grant|deny)$", description="grant, deny, or null to reset")
    reason: str | None = Field(None, max_length=500)


class OverrideOut(BaseModel):
    permission: Permission
    effect: str
    is_active: bool
    granted_by_user_id: uuid.UUID | None
    reason: str | None
    valid_to: datetime | None = None


class UserFunctionsOut(BaseModel):
    user_id: uuid.UUID
    role: Role
    functions: list[Permission]
    overrides: list[OverrideOut]


class PermissionOut(BaseModel):
    code: Permission
    module: str
    label: str
    description: str | None
    is_active: bool


class MatrixEntryIn(BaseModel):
    enabled: bool


# ------------------------------------------------------------------------------------------------ offices


class OfficeCountsOut(BaseModel):
    children: int
    users: int
    ownership: int
    custody: int


class OfficeNodeOut(OfficeOut):
    tier: str
    depth: int
    users_active: int
    children: list[OfficeNodeOut] = Field(default_factory=list)


class OfficeDetailOut(OfficeOut):
    tier: str
    depth: int
    parent_code: str | None
    notes: str | None
    deactivated_at: datetime | None
    valid_from: date
    valid_to: date | None
    created_at: datetime
    updated_at: datetime
    counts: OfficeCountsOut


class OfficeCreateIn(BaseModel):
    code: str = Field(
        min_length=2,
        max_length=40,
        description="the Secretariat's code, upper-cased, immutable; `<PARENT>-<CHILD>` is the convention",
    )
    name: str = Field(min_length=1, max_length=200)
    kind: OfficeKind
    parent_code: str = Field(min_length=1, max_length=40)
    notes: str | None = Field(None, max_length=4000)
    valid_from: date | None = None


class OfficePatchIn(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    notes: str | None = Field(None, max_length=4000)
    valid_from: date | None = None


class DepartmentAdminIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    full_name: str = Field(min_length=2, max_length=200)
    designation: str | None = Field(None, max_length=200)
    designation_id: uuid.UUID | None = None
    mobile: str | None = Field(None, max_length=20)


class DesignationOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    sort_order: int
    is_active: bool


class DesignationCreateIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    sort_order: int | None = Field(None, ge=0, le=100000)


class DesignationPatchIn(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    sort_order: int | None = Field(None, ge=0, le=100000)


# ------------------------------------------------------------------------------------------------ matching rules


class OfficeRefOut(BaseModel):
    code: str
    name: str


class UserRefOut(BaseModel):
    id: uuid.UUID
    full_name: str


class ScoringWeightsIn(BaseModel):
    counsel_code: float = Field(gt=0, le=1)
    name_pattern: float = Field(gt=0, le=1)
    watchlist: float = Field(gt=0, le=1)
    linked_case: float = Field(gt=0, le=1)
    keyword: float = Field(gt=0, le=1)


class ScoringThresholdsIn(BaseModel):
    strong: float = Field(gt=0, le=1)
    possible: float = Field(gt=0, le=1)


class ScoringSettingsIn(BaseModel):
    weights: ScoringWeightsIn
    thresholds: ScoringThresholdsIn
    reason: str = Field(min_length=1, max_length=2000)
    expected_version: int = Field(ge=0)


class ScoringSettingsOut(BaseModel):
    version: int
    weights: dict[str, float]
    thresholds: dict[str, float]
    reason: str | None
    valid_from: datetime | None
    valid_to: datetime | None = None
    updated_by: UserRefOut | None = None
    engine_version: str


class ScoringSettingsSavedOut(ScoringSettingsOut):
    changed: bool
    rescore_dispatched: bool
    applies_within_minutes: int = 15


class ScoringSettingsHistoryOut(BaseModel):
    items: list[ScoringSettingsOut]
    total: int


class CounselCodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=60)
    office_code: str = Field(min_length=1, max_length=40)
    weight: float | None = None
    is_generic_state: bool = False
    notes: str | None = Field(None, max_length=4000)


class CounselCodePatchIn(BaseModel):
    office_code: str | None = Field(None, min_length=1, max_length=40)
    weight: float | None = None
    notes: str | None = Field(None, max_length=4000)


class CounselCodeOut(BaseModel):
    id: uuid.UUID
    code: str
    office: OfficeRefOut
    weight_override: float | None
    effective_weight: float
    is_generic_state: bool
    notes: str | None
    is_active: bool
    updated_at: datetime
    applies_within_minutes: int | None = None


class CounselCodeListOut(BaseModel):
    items: list[CounselCodeOut]
    total: int


class UnmappedCodeOut(BaseModel):
    code: str
    entries: int
    last_listed: date | None
    example_case_ref: str | None


class KeywordIn(BaseModel):
    keyword: str = Field(min_length=1, max_length=200)
    office_code: str = Field(min_length=1, max_length=40)
    weight: float | None = None


class RuleWeightPatchIn(BaseModel):
    weight: float | None = None


class KeywordOut(BaseModel):
    id: uuid.UUID
    keyword: str
    office: OfficeRefOut
    weight_override: float | None
    effective_weight: float
    is_active: bool
    updated_at: datetime
    applies_within_minutes: int | None = None


class KeywordListOut(BaseModel):
    items: list[KeywordOut]
    total: int


class NamePatternIn(BaseModel):
    pattern: str = Field(min_length=1, max_length=300)
    kind: str = Field(pattern="^(exact|prefix|regex)$")
    office_code: str = Field(min_length=1, max_length=40)
    weight: float | None = None


class NamePatternOut(BaseModel):
    id: uuid.UUID
    pattern: str
    kind: str
    office: OfficeRefOut
    weight_override: float | None
    effective_weight: float
    is_active: bool
    updated_at: datetime
    applies_within_minutes: int | None = None


class NamePatternListOut(BaseModel):
    items: list[NamePatternOut]
    total: int


class WatchIn(BaseModel):
    cnr: str = Field(min_length=16, max_length=16)
    office_code: str | None = Field(None, min_length=1, max_length=40)
    reason: str | None = Field(None, max_length=2000)
    weight: float | None = None


class WatchPatchIn(BaseModel):
    reason: str | None = Field(None, max_length=2000)
    weight: float | None = None


class WatchOut(BaseModel):
    id: uuid.UUID
    cnr: str
    case_ref: str | None
    office: OfficeRefOut
    reason: str | None
    weight_override: float | None
    effective_weight: float
    is_active: bool
    updated_at: datetime
    dossier_queued: bool | None = None


class WatchListOut(BaseModel):
    items: list[WatchOut]
    total: int


class CaseScoreOut(BaseModel):
    office: OfficeRefOut
    score: float
    band: str | None
    signals: list[dict[str, Any]]
    computed_at: datetime
    engine_version: str


# ------------------------------------------------------------------------------------------------ inbox


class CaseSummaryOut(BaseModel):
    id: uuid.UUID
    ref_no: str
    cnr: str | None
    case_no_text: str | None
    is_provisional: bool
    petitioner_summary: str | None
    respondent_summary: str | None
    status: str
    next_hearing_date: date | None
    last_listed_on: date | None


class RecommendationOut(BaseModel):
    id: uuid.UUID
    case: CaseSummaryOut
    office_code: str | None
    score: float
    band: str
    status: str
    origin: str
    signals: list[dict[str, Any]]
    suggested_by_office_code: str | None
    reason: str | None
    created_at: datetime
    acted_at: datetime | None
    current_owner_code: str | None


class RecommendationListOut(BaseModel):
    items: list[RecommendationOut]
    total: int


class OwnershipOut(BaseModel):
    id: uuid.UUID
    case: CaseSummaryOut
    office_code: str | None
    role: str
    status: str
    unit: OfficeRefOut | None
    officer: UserRefOut | None
    claimed_at: datetime
    allotted_at: datetime | None
    released_at: datetime | None
    release_reason: str | None


class OwnershipListOut(BaseModel):
    items: list[OwnershipOut]
    total: int


class PoolCaseOut(BaseModel):
    case: CaseSummaryOut
    best_score: float | None
    best_office_code: str | None
    dismissed_by: list[str]


class PoolListOut(BaseModel):
    items: list[PoolCaseOut]
    total: int


class TransferOut(BaseModel):
    id: uuid.UUID
    ref_no: str
    case: CaseSummaryOut
    from_office_code: str | None
    to_office_code: str | None
    status: str
    reason: str | None
    stay_as_watcher: bool
    decision_note: str | None
    requested_by: UserRefOut | None
    requested_at: datetime
    decided_by: UserRefOut | None
    decided_at: datetime | None
    withdrawn_at: datetime | None


class TransferListOut(BaseModel):
    items: list[TransferOut]
    total: int


class InboxCountsOut(BaseModel):
    recommended_high: int | None
    recommended_medium: int | None
    claimed_active: int | None
    claimed_disposed: int | None
    transfers_in_open: int | None
    pool_with_hearing_7d: int | None


# ------------------------------------------------------------------------------------------------ ownership


class CaseOwnershipViewOut(BaseModel):
    primary: OwnershipOut | None
    watchers: list[OwnershipOut]
    recommendations: list[RecommendationOut]
    open_transfer: TransferOut | None


class ClaimIn(BaseModel):
    office_code: str | None = Field(None, min_length=1, max_length=40, description="super admin only")
    unit_code: str | None = Field(None, min_length=1, max_length=40)
    officer_user_id: uuid.UUID | None = None
    note: str | None = Field(None, max_length=500)


class DismissIn(BaseModel):
    reason: str | None = Field(None, max_length=500)


class SuggestIn(BaseModel):
    office_code: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=500)


class SuggestOut(BaseModel):
    own: RecommendationOut | None
    target: RecommendationOut
    target_already_recommended: bool


class AllotIn(BaseModel):
    """Fields left out are not changed; null clears."""

    unit_code: str | None = Field(None, min_length=1, max_length=40)
    officer_user_id: uuid.UUID | None = None


class TakeOverIn(BaseModel):
    expected_officer_user_id: uuid.UUID | None = None
    reason: str | None = Field(None, max_length=500)


class TakeOverOut(OwnershipOut):
    taken_from: UserRefOut | None


class StopWatchingIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class TransferRequestIn(BaseModel):
    to_office_code: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=500)
    stay_as_watcher: bool = False


class TransferDecisionIn(BaseModel):
    note: str | None = Field(None, max_length=500)
