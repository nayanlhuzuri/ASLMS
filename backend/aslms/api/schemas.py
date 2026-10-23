"""Request and response shapes of the auth, user, access, office, designation, inbox, ownership and case
endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from aslms.domain.reference import OfficeKind, Permission, Role


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    device_token: str | None = Field(None, max_length=200)
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
    must_change_password: bool = False
    profile_confirmed_at: datetime | None = None
    last_login_at: datetime | None
    created_at: datetime
    memberships: list[MembershipOut] = Field(default_factory=list)


class MeOut(BaseModel):
    user: UserOut
    memberships: list[MembershipOut] = Field(default_factory=list)
    functions: list[Permission]


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
    next_step: Literal["ready", "change_password", "confirm_profile"] = "ready"
    device_token: str | None = Field(None, description="issued once, when the device is new; keep it")


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
    email: EmailStr | None = None


class TypeIn(BaseModel):
    role: Role


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=200, description="the policy answers 422 weak_password")


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


class UserTypeLabelOut(BaseModel):
    code: str
    label: str
    description: str | None = None
    assignable: bool


class LabelOut(BaseModel):
    code: str
    label: str


class CaseTypeOut(BaseModel):
    """An active case type of the High Court master (court-public)."""

    case_type_code: int
    short_name: str | None
    full_name: str | None
    type_name: str


class ReferenceLabelsOut(BaseModel):
    """Design `portal-shell`, decision 16a: the database's labels; `assignable` is the caller's."""

    user_types: list[UserTypeLabelOut]
    office_kinds: list[LabelOut]
    ticket_kinds: list[LabelOut]
    alert_kinds: list[LabelOut]  # design portal-workflow, decision 20f: active `ref_alert_kind` rows


class CourtNumberOut(BaseModel):
    """A court number printed in the cause lists of the window (trimmed)."""

    court_no: str
    last_listed: date
    entries: int


class BenchTextOut(BaseModel):
    """A bench (judge names) printed in the cause lists of the window, upper-cased with white space collapsed."""

    text: str
    last_listed: date
    entries: int


class BenchesOut(BaseModel):
    """Design `portal-filters`, decision 12: the court and bench pickers' choices (court-public)."""

    model_config = ConfigDict(populate_by_name=True)

    from_: date = Field(alias="from")
    to: date
    court_numbers: list[CourtNumberOut]
    benches: list[BenchTextOut]


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
    head: HeadIn | None = Field(None, description="required for a Department-tier kind (user-memberships)")


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
    discover: bool | None = Field(
        None,
        description="Search the court (department discovery); left out = on when the text is discoverable",
    )


class RuleWeightPatchIn(BaseModel):
    weight: float | None = None


class DiscoverRulePatchIn(RuleWeightPatchIn):
    """A keyword or name pattern: the weight override and/or `discover` (left out = unchanged)."""

    discover: bool | None = None


class RuleDiscoveryOut(BaseModel):
    """The rule's discovery term (design `department-discovery`): when it was last searched and the cases found."""

    term_id: uuid.UUID
    last_searched_at: datetime | None
    cases_found: int


class KeywordOut(BaseModel):
    id: uuid.UUID
    keyword: str
    office: OfficeRefOut
    weight_override: float | None
    effective_weight: float
    is_active: bool
    updated_at: datetime
    discover: bool
    discoverable: bool
    discovery: RuleDiscoveryOut | None = None
    applies_within_minutes: int | None = None


class KeywordListOut(BaseModel):
    items: list[KeywordOut]
    total: int


class NamePatternIn(BaseModel):
    pattern: str = Field(min_length=1, max_length=300)
    kind: str = Field(pattern="^(exact|prefix|regex)$")
    office_code: str = Field(min_length=1, max_length=40)
    weight: float | None = None
    discover: bool | None = Field(
        None,
        description="Search the court (department discovery); never for a regex; left out = when discoverable",
    )


class NamePatternOut(BaseModel):
    id: uuid.UUID
    pattern: str
    kind: str
    office: OfficeRefOut
    weight_override: float | None
    effective_weight: float
    is_active: bool
    updated_at: datetime
    discover: bool
    discoverable: bool
    discovery: RuleDiscoveryOut | None = None
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


class CaseLastListingOut(BaseModel):
    """The latest cause-list entry of a case (latest date, then the lowest item number)."""

    list_date: date
    list_type: str
    court_no: str | None
    sr_no: int


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
    last_listing: CaseLastListingOut | None


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


class StageBriefOut(BaseModel):
    """The case's current stage (its latest `case_stages` row)."""

    stage: str
    label: str
    phase: str | None


class CustodyHolderBriefOut(BaseModel):
    full_name: str
    designation: str | None = None


class CustodyBriefOut(BaseModel):
    """Where the file is, for a list row (design portal-ui-redesign, A1): no remark (custody-workflow decision 25
    keeps it on the case's custody card). `with_me` is relative to the caller."""

    holder_office: OfficeRefOut | None
    holder_user: CustodyHolderBriefOut | None
    with_me: bool
    pending_action: str
    pending_action_label: str
    since: datetime
    due_date: date | None
    overdue: bool
    overdue_days: int


class AllotmentOut(BaseModel):
    unit: OfficeRefOut | None
    officer: UserRefOut | None


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
    # design portal-ui-redesign, A3: on the Claimed list's items (null elsewhere)
    stage: StageBriefOut | None = None
    custody: CustodyBriefOut | None = None


class MyCaseOut(BaseModel):
    """One row of the caller's own cases (design portal-ui-redesign, A1). `reasons`: which of `allotted`,
    `file` and `claimed` put the row here."""

    case: CaseSummaryOut
    owner_code: str | None
    stage: StageBriefOut | None
    custody: CustodyBriefOut | None
    allotment: AllotmentOut | None
    reasons: list[str]


class MyCaseListOut(BaseModel):
    items: list[MyCaseOut]
    total: int


class MyCaseCountsOut(BaseModel):
    working: int
    files: int
    claimed: int
    disposed: int


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
    office_code: str | None = None
    recommended_high: int | None
    recommended_medium: int | None
    claimed_active: int | None
    claimed_disposed: int | None
    transfers_in_open: int | None
    pool_with_hearing_7d: int | None
    # design portal-ui-redesign, A4: the caller reads this department whole (cases.claim or cases.allot in their
    # membership there, or cases.view_all)
    whole_department: bool = False


class InboxCountsListOut(BaseModel):
    departments: list[InboxCountsOut]


# ------------------------------------------------------------------------------------------------ ownership


class OwnershipActionsOut(BaseModel):
    """Which ownership actions the caller may take on the case now (computed by the actions' own checks; the
    API still decides on every call). `claim_departments`: the caller's departments that may claim; for the
    super admin null ("any active department") only while the case is in the pool, else the recommended
    departments that do not hold it. Each `*_departments` list names the caller's departments for which that
    action passes with the department named; `transfer_from` is the department a transfer would come from."""

    claim: bool
    claim_departments: list[str] | None
    dismiss: bool
    dismiss_departments: list[str]
    suggest: bool
    suggest_departments: list[str]
    allot: bool
    allot_departments: list[str]
    take_over: bool
    take_over_departments: list[str]
    stop_watching: bool
    stop_watching_departments: list[str]
    request_transfer: bool
    transfer_from: str | None
    withdraw_transfer: bool
    decide_transfer: bool


class CaseOwnershipViewOut(BaseModel):
    primary: OwnershipOut | None
    watchers: list[OwnershipOut]
    recommendations: list[RecommendationOut]
    open_transfer: TransferOut | None
    actions: OwnershipActionsOut


class ClaimIn(BaseModel):
    office_code: str | None = Field(
        None,
        min_length=1,
        max_length=40,
        description="the department to act for: one the caller has a membership in (the super admin: any)",
    )
    unit_code: str | None = Field(None, min_length=1, max_length=40)
    officer_user_id: uuid.UUID | None = None
    note: str | None = Field(None, max_length=500)


class DismissIn(BaseModel):
    office_code: str | None = Field(
        None,
        min_length=1,
        max_length=40,
        description="the department to act for: one the caller has a membership in (default: decision 6)",
    )
    reason: str | None = Field(None, max_length=500)


class SuggestIn(BaseModel):
    office_code: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=500)
    from_office_code: str | None = Field(
        None,
        min_length=1,
        max_length=40,
        description="the department the suggestion comes from: one the caller has a membership in "
        "(default: decision 6)",
    )


class SuggestOut(BaseModel):
    own: RecommendationOut | None
    target: RecommendationOut
    target_already_recommended: bool


class AllotIn(BaseModel):
    """Fields left out are not changed; null clears."""

    office_code: str | None = Field(
        None,
        min_length=1,
        max_length=40,
        description="the department to act for: one the caller has a membership in (default: decision 6)",
    )
    unit_code: str | None = Field(None, min_length=1, max_length=40)
    officer_user_id: uuid.UUID | None = None


class TakeOverIn(BaseModel):
    office_code: str | None = Field(
        None,
        min_length=1,
        max_length=40,
        description="the department to act for: one the caller has a membership in (default: decision 6)",
    )
    expected_officer_user_id: uuid.UUID | None = None
    reason: str | None = Field(None, max_length=500)


class TakeOverOut(OwnershipOut):
    taken_from: UserRefOut | None


class StopWatchingIn(BaseModel):
    office_code: str | None = Field(
        None,
        min_length=1,
        max_length=40,
        description="the department to act for: one the caller has a membership in (default: decision 6)",
    )
    reason: str = Field(min_length=1, max_length=500)


class TransferRequestIn(BaseModel):
    to_office_code: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=500)
    stay_as_watcher: bool = False


class TransferDecisionIn(BaseModel):
    note: str | None = Field(None, max_length=500)


# ------------------------------------------------------------------------------------------------ cases (cases-api)


class CaseSearchItemOut(BaseModel):
    """A row of `/cases` and `/cases/search`: court-public summary data of any case, plus what the caller may
    do with it. `visible` says whether the detail endpoints will answer."""

    case: CaseSummaryOut
    visible: bool
    owner_office_code: str | None
    in_pool: bool
    claimable: bool
    match: str | None = None
    dossier_status: str


class CaseSearchListOut(BaseModel):
    items: list[CaseSearchItemOut]
    total: int
    total_capped: bool = False


class CaseIdentityOut(BaseModel):
    cnr: str | None
    court_est_name: str | None
    case_type_id: uuid.UUID | None
    case_type_text: str | None
    reg_no: int | None
    reg_year: int | None
    case_no_text: str | None
    filing_case_type_id: uuid.UUID | None
    filing_case_type_text: str | None
    filing_no: int | None
    filing_year: int | None
    filing_no_text: str | None
    filing_date: date | None
    registration_date: date | None
    date_first_list: date | None


class CaseStatusOut(BaseModel):
    status: str
    disposal_date: date | None
    disposal_nature: str | None
    disposal_type: str | None
    short_order: str | None
    date_filing_disp: date | None
    reason_for_rej: str | None
    date_judgement_pronounced: date | None
    date_judgement_reserved: date | None
    goshwara_no: str | None
    next_hearing_date: date | None
    next_purpose: str | None
    last_hearing_date: date | None


class CaseClassificationOut(BaseModel):
    bench_id: uuid.UUID | None
    napix_bench_id: int | None
    bench_name: str | None
    bench_type_code: int | None
    coram: str | None
    coram_designation: str | None
    judicial_branch: str | None
    category: str | None
    category_code: int | None
    sub_category: str | None


class CasePlaceOut(BaseModel):
    state_id: uuid.UUID | None
    district_id: uuid.UUID | None
    state_name_as_listed: str | None
    district_name_as_listed: str | None
    filing_state_code: int | None
    filing_district_code: int | None
    fir_no: str | None
    fir_year: int | None
    police_station: str | None
    police_st_code: str | None
    uniform_code: str | None
    main_matter_text: str | None


class CasePartiesAsPrintedOut(BaseModel):
    petitioner_summary: str | None
    respondent_summary: str | None
    pet_advocate: str | None
    res_advocate: str | None


class CasePortalOut(BaseModel):
    is_provisional: bool
    is_tracked: bool
    first_seen_source: str
    last_full_refresh_at: datetime | None
    last_status_refresh_at: datetime | None
    dossier_stale: bool
    merged_into_case_id: uuid.UUID | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None


class CourtRefOut(BaseModel):
    est_code: str
    name: str


class BenchRefOut(BaseModel):
    bench_id: int
    judge_names: str | None
    bench_name: str | None


class PartyOut(BaseModel):
    role: str
    party_no: int
    name: str
    address: str | None
    has_legal_heir: bool | None
    is_current: bool


class AdvocateOut(BaseModel):
    side: str
    name_as_listed: str
    counsel_code: str | None
    bar_reg_no: str | None
    is_current: bool


class PartiesOut(BaseModel):
    parties: list[PartyOut]
    advocates: list[AdvocateOut]


class ActOut(BaseModel):
    act_name_as_listed: str
    national_act_code: str | None
    section: str | None


class LowerCourtOut(BaseModel):
    level: str
    court_name: str | None
    case_no_text: str | None
    decision_date: date | None


class ApplicationOut(BaseModel):
    ia_number: str
    party_name: str | None
    status: str | None
    filing_date: date | None


class ObjectionOut(BaseModel):
    seq: int
    objection: str | None
    scrutiny_date: date
    compliance_by_date: date | None
    receipt_date: date | None


class CourtTransferOut(BaseModel):
    transfer_date: date | None
    from_court_text: str | None
    to_court_text: str | None


class WritInfoOut(BaseModel):
    appellate_case_number: str
    appellate_authority: str | None


class PrimaryOwnerOut(BaseModel):
    office_code: str | None
    office_name: str | None
    unit: OfficeRefOut | None
    officer: UserRefOut | None
    claimed_at: datetime


class CaseOwnershipCompactOut(BaseModel):
    primary: PrimaryOwnerOut | None
    watchers: list[str]


class CustodyHolderOut(BaseModel):
    id: uuid.UUID
    full_name: str
    designation: str | None = None


class CustodySentByOut(BaseModel):
    name: str | None
    designation: str | None
    office_code: str | None


class CustodyCardOut(BaseModel):
    """Design custody-workflow, decision 25: the remark only for a working basis or a State-wide reader holding
    `cases.view_private_all` (design alerts-visibility-roles, decision 16)."""

    holder_office: OfficeRefOut | None
    holder_user: CustodyHolderOut | None
    pending_action: str
    pending_action_label: str
    since: datetime
    due_date: date | None
    overdue: bool
    overdue_days: int
    sent_by: CustodySentByOut | None
    reason: str | None
    remark: str | None
    leg_seq_no: int | None
    can_send: bool
    can_recall: bool


class StageBlockOut(BaseModel):
    stage: str
    label: str
    phase: str | None
    response_mode: str
    set_at: datetime
    office_code: str | None


class CaseCountsOut(BaseModel):
    hearings: int
    orders: int
    listings: int
    documents: int
    links: int
    timeline: int
    notes: int
    my_drafts: int


class CaseWorkflowActionsOut(BaseModel):
    """Design portal-workflow, decision 20a: what the caller may do, from the checks the writes run. `note_mode`
    is `draft` when the caller's acting membership holds the file, `permanent` when they may write a note
    otherwise, `null` when they may not write one. `next_dates` (design portal-next-dates, decision 3): the caller
    may confirm, reject and enter next dates on the case."""

    note_mode: Literal["draft", "permanent"] | None
    upload: bool
    set_stage: bool
    next_dates: bool


# ------------------------------------------------------------------------------------------------ next dates


class NextDateOrderOut(BaseModel):
    id: uuid.UUID
    order_no: str
    order_date: date
    document_id: uuid.UUID | None
    phrase: str | None = None
    rule: str | None = None


class NextDatePersonOut(BaseModel):
    name: str | None


class NextDateOut(BaseModel):
    """A next date (design `next-date-extraction`): read from an order, entered by hand (`NXT`), or from the court's
    current status. The note is shown to every reader of the case."""

    id: uuid.UUID
    ref_no: str | None
    next_date: date
    source: str
    confidence: float
    needs_review: bool
    review_status: str
    order: NextDateOrderOut | None
    note: str | None
    reviewed_by: NextDatePersonOut | None
    reviewed_at: datetime | None
    created_by: NextDatePersonOut | None
    created_at: datetime


class CaseNextDateOut(NextDateOut):
    effective: bool


class CaseNextDateListOut(BaseModel):
    items: list[CaseNextDateOut]
    total: int


class NextDateReviewOrderOut(BaseModel):
    id: uuid.UUID
    order_no: str
    order_date: date
    document_id: uuid.UUID | None


class NextDateCaseOut(BaseModel):
    id: uuid.UUID
    ref_no: str
    cnr: str | None
    case_no_text: str | None


class NextDateReviewItemOut(BaseModel):
    kind: Literal["confirm", "enter"]
    id: uuid.UUID = Field(description="the next date id for `confirm`, the order id for `enter`")
    case: NextDateCaseOut
    order: NextDateReviewOrderOut | None
    phrase: str | None
    rule: str | None
    next_date: date | None
    act_by: date
    alert_ref_no: str | None
    departments: list[str]


class NextDateReviewListOut(BaseModel):
    items: list[NextDateReviewItemOut]
    total: int


class NextDateConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NextDateRejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(None, max_length=300)
    next_date: date | None = Field(None, description="the correct date, entered as a manual next date (NXT)")


class NextDateRejectOut(BaseModel):
    rejected: NextDateOut
    entered: NextDateOut | None


class NextDateEnterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    next_date: date
    note: str | None = Field(
        None, max_length=300, description="shown to everyone who can see the case: no internal remarks"
    )
    order: uuid.UUID | None = Field(None, description="an order of the case the date answers")


class CaseDetailOut(BaseModel):
    id: uuid.UUID
    ref_no: str
    identity: CaseIdentityOut
    status: CaseStatusOut
    classification: CaseClassificationOut
    place: CasePlaceOut
    parties_as_printed: CasePartiesAsPrintedOut
    portal: CasePortalOut
    court: CourtRefOut | None
    bench: BenchRefOut | None
    parties: list[PartyOut]
    advocates: list[AdvocateOut]
    acts: list[ActOut]
    lower_courts: list[LowerCourtOut]
    applications: list[ApplicationOut]
    objections: list[ObjectionOut]
    court_transfers: list[CourtTransferOut]
    writ_info: list[WritInfoOut]
    ownership: CaseOwnershipCompactOut
    custody: CustodyCardOut | None
    stage: StageBlockOut | None
    access_basis: list[str]
    claimable: bool
    dossier_status: str
    merged_into_ref_no: str | None
    counts: CaseCountsOut
    workflow: CaseWorkflowActionsOut
    next_date_from_orders: NextDateOut | None = None
    next_dates_to_review: int = 0


class HearingOut(BaseModel):
    business_date: date | None
    hearing_date: date | None
    purpose: str | None
    bench_text: str | None
    judge_designation: str | None
    causelist_type: str | None
    next_date: date | None
    business_text: str | None
    short_order_text: str | None
    case_number_text: str | None
    source: str


class HearingListOut(BaseModel):
    items: list[HearingOut]
    total: int


class OrderOut(BaseModel):
    id: uuid.UUID
    order_no: str
    order_date: date
    kind: str
    order_details: str | None
    order_judge_name: str | None
    date_judgement_pronounced: date | None
    date_judgement_reserved: date | None
    is_reportable: bool | None
    download_status: str
    document_id: uuid.UUID | None
    text_status: str | None = None
    page_count: int | None = None
    next_date_status: str | None = None
    next_date_found: date | None = None
    next_date_rule: str | None = None
    next_date_phrase: str | None = None


class OrderListOut(BaseModel):
    items: list[OrderOut]
    total: int


class ListingOut(BaseModel):
    list_date: date
    list_type: str
    bench_label: str | None
    bench_id: int | None
    court_no: str | None
    sr_no: int
    printed_sr: str | None
    section: str | None
    is_connected: bool
    counsel_codes: list[str]
    remarks: str | None
    source: str


class ListingListOut(BaseModel):
    items: list[ListingOut]
    total: int


class LinkOut(BaseModel):
    direction: str
    kind: str
    case_no_text: str | None
    cnr: str | None
    filing_number_text: str | None
    source: str
    case: CaseSummaryOut | None
    visible: bool


class LinkListOut(BaseModel):
    items: list[LinkOut]


class GraphNodeOut(BaseModel):
    key: str
    case: CaseSummaryOut | None
    case_no_text: str | None
    visible: bool


class GraphEdgeOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    kind: str


class LinkGraphOut(BaseModel):
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]
    truncated: bool


class TimelineOut(BaseModel):
    type: str
    label: str
    icon_key: str | None
    occurred_at: datetime
    actor_name: str | None
    payload: dict[str, Any]


class TimelineListOut(BaseModel):
    items: list[TimelineOut]
    total: int


class CourtSearchCnrIn(BaseModel):
    kind: Literal["cnr"]
    cnr: str = Field(min_length=16, max_length=16, pattern=r"^[A-Za-z]{4}\d{12}$")


class CourtSearchCaseNumberIn(BaseModel):
    kind: Literal["case_number"]
    case_type: str = Field(min_length=1, max_length=60, description="short name (WP(C)) or the master's code")
    reg_no: int = Field(ge=1, le=9_999_999)
    reg_year: int = Field(ge=1950, le=2100)


class CourtSearchPartyIn(BaseModel):
    kind: Literal["party"]
    name: str = Field(
        min_length=3,
        max_length=200,
        pattern=r"^[A-Za-z0-9 .,'&()/-]+$",
        description="letters, digits, spaces and . , ' & ( ) / - (never | or =, the gateway's separators)",
    )
    reg_year: int = Field(ge=1950, le=2100)
    pend_disp: Literal["P", "D", "both"] = "P"


class CourtSearchAdvocateIn(BaseModel):
    """Search by Advocate Name (design `search-court-advocate-filing`, decision 6): the court matches part of a
    name and ignores the honorific (probe P3, P4); the year is required (P2: 606)."""

    kind: Literal["advocate"]
    name: str = Field(
        min_length=3,
        max_length=99,
        pattern=r"^[A-Za-z0-9 .,'&()/-]+$",
        description="letters, digits, spaces and . , ' & ( ) / - (never | or =, the gateway's separators)",
    )
    reg_year: int = Field(ge=1950, le=2100)
    pend_disp: Literal["P", "D", "both"] = "P"


class CourtSearchFilingIn(BaseModel):
    """Search by Filing Number (design `search-court-advocate-filing`, decision 5)."""

    kind: Literal["filing"]
    case_type: str = Field(min_length=1, max_length=60, description="short name (WP(C)) or the master's code")
    fil_no: int = Field(ge=1, le=9_999_999)
    fil_year: int = Field(ge=1950, le=2100)


CourtSearchIn = Annotated[
    CourtSearchCnrIn
    | CourtSearchCaseNumberIn
    | CourtSearchFilingIn
    | CourtSearchPartyIn
    | CourtSearchAdvocateIn,
    Field(discriminator="kind"),
]


class UnmatchedRowOut(BaseModel):
    type_name: str | None = None
    reg_no: str | None = None
    reg_year: str | None = None
    pet_name: str | None = None
    res_name: str | None = None


class CourtSearchOut(BaseModel):
    source: str
    calls: int
    created: int
    items: list[CaseSearchItemOut]
    unmatched: list[UnmatchedRowOut]
    # an advocate search (design safety-fixes, decision 14): distinct CNRs the court returned, new cases being added
    # in the background, new cases beyond the cap that were not stored; 0 for the other kinds
    court_cases: int = 0
    queued: int = 0
    not_stored: int = 0


class ErrorOut(BaseModel):
    code: str
    message: str
    retry_after: int | None = None


# ------------------------------------------------------------------------------------------------ documents


class DocumentOfficeOut(BaseModel):
    code: str
    name: str


class DocumentUploaderOut(BaseModel):
    name: str
    designation: str | None = None
    office_code: str | None = None


class DocumentOrderOut(BaseModel):
    id: uuid.UUID
    order_no: str
    order_date: date
    kind: str


class DocumentCaseOut(BaseModel):
    id: uuid.UUID
    ref_no: str
    cnr: str | None
    case_no_text: str | None


class DocumentOut(BaseModel):
    id: uuid.UUID
    ref_no: str | None
    kind: str
    doc_type: str
    doc_type_label: str
    doc_group: str
    doc_date: date | None
    description: str | None
    original_filename: str | None
    mime: str
    size_bytes: int
    visibility: str
    office: DocumentOfficeOut | None
    uploaded_by: DocumentUploaderOut | None
    uploaded_at: datetime
    virus_scan_status: str
    text_status: str
    page_count: int | None
    text_extracted_at: datetime | None
    sourcetrace_status: str
    sourcetrace_ingested_at: datetime | None = None
    assistant_available: bool
    archived_at: datetime | None
    archive_reason: str | None
    order: DocumentOrderOut | None
    case: DocumentCaseOut | None
    can_manage: bool


class DocumentListOut(BaseModel):
    items: list[DocumentOut]
    total: int


class DocumentTypeOut(BaseModel):
    code: str
    label: str
    doc_group: str
    group_choosable: bool


class UploadLimitsOut(BaseModel):
    """Design portal-workflow, decision 20e: `UPLOAD_MAX_BYTES` and the permitted extensions, for the portal's
    pre-checks (the API still decides by content)."""

    max_bytes: int
    extensions: list[str]


class DocumentTypesOut(BaseModel):
    items: list[DocumentTypeOut]
    upload: UploadLimitsOut


class DocumentSearchItemOut(BaseModel):
    document: DocumentOut
    case: CaseSummaryOut | None
    snippet: str | None
    rank: float


class DocumentSearchOut(BaseModel):
    items: list[DocumentSearchItemOut]
    total: int


class DocumentVisibilityIn(BaseModel):
    visibility: str = Field(..., pattern="^(case_scope|counsel_shared|private_to_office)$")


class DocumentArchiveIn(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


# ------------------------------------------------------------------------------------------------ alerts


class AlertCaseOut(BaseModel):
    id: uuid.UUID
    ref_no: str
    cnr: str | None
    case_no_text: str | None


class AlertItemOut(BaseModel):
    id: uuid.UUID
    ref_no: str
    kind: str
    kind_label: str
    severity: str
    status: str
    title: str
    body: str | None
    due_at: datetime | None
    case: AlertCaseOut | None
    ticket_ref: str | None = None
    data: dict[str, Any]
    notified_at: datetime | None
    read_at: datetime | None
    acknowledged_by: UserRefOut | None
    acknowledged_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    can_act: bool  # design portal-workflow, decision 20d: Acknowledge / Done may be offered
    case_visible: bool  # design portal-files-alerts, decision 6: the caller can open the case now


class AlertDetailOut(AlertItemOut):
    recipients_count: int


class AlertListOut(BaseModel):
    items: list[AlertItemOut]
    total: int


class AlertOpenCountsOut(BaseModel):
    critical: int
    high: int
    normal: int


class AlertCountsOut(BaseModel):
    unread: int
    open: AlertOpenCountsOut


class AlertNoteIn(BaseModel):
    note: Annotated[str | None, Field(max_length=500)] = None


class AlertsReadIn(BaseModel):
    alert_ids: list[uuid.UUID] | None = None
    all: bool = False


class AlertsReadOut(BaseModel):
    marked: int


class CalendarItemOut(BaseModel):
    date: date
    case: AlertCaseOut
    source: str
    court_no: str | None
    item_no: str | None
    purpose: str | None
    critical: bool
    this_week: bool


class CalendarOut(BaseModel):
    items: list[CalendarItemOut]


class MyCalendarItemOut(BaseModel):
    """One of the caller's dates (design `portal-ui-redesign`, A6): a hearing of their case, a due date of a file
    they hold, or a next date waiting for their confirmation; the fields of the other kinds are null."""

    date: date
    kind: Literal["hearing", "action_due", "confirm"]
    case: AlertCaseOut
    critical: bool
    court_no: str | None = None
    item_no: str | None = None
    purpose: str | None = None
    source: str | None = None
    this_week: bool | None = None
    pending_action: str | None = None
    pending_action_label: str | None = None
    overdue: bool | None = None
    next_date_id: uuid.UUID | None = None


class MyCalendarOut(BaseModel):
    items: list[MyCalendarItemOut]


class InAppPrefOut(BaseModel):
    enabled: bool


class EmailPrefOut(BaseModel):
    enabled: bool
    digest: str
    critical_only: bool


class SmsPrefOut(BaseModel):
    available: bool


class NotificationPreferencesOut(BaseModel):
    in_app: InAppPrefOut
    email: EmailPrefOut
    sms: SmsPrefOut


class EmailPrefIn(BaseModel):
    enabled: bool | None = None
    digest: str | None = None
    critical_only: bool | None = None


class InAppPrefIn(BaseModel):
    enabled: bool | None = None


class NotificationPreferencesIn(BaseModel):
    email: EmailPrefIn | None = None
    in_app: InAppPrefIn | None = None
    sms: dict[str, Any] | None = None


# ------------------------------------------------------------------------------------------------ memberships


class MembershipOfficeOut(BaseModel):
    code: str
    name: str
    kind: str


class MembershipOut(BaseModel):
    """One office a person serves in, with its designation and user type (design `user-memberships`)."""

    id: uuid.UUID
    office: MembershipOfficeOut
    department_code: str | None
    designation: str | None
    designation_id: uuid.UUID | None = None
    role: Role
    is_primary: bool
    is_active: bool = True
    valid_from: date | None = None
    valid_to: date | None = None
    end_reason: str | None = None
    functions: list[Permission] | None = None


class MembershipIn(BaseModel):
    office: str = Field(min_length=1, max_length=40, description="the office code")
    role: Role
    designation: str | None = Field(None, max_length=200)
    designation_id: uuid.UUID | None = None


class MembershipPatchIn(BaseModel):
    designation: str | None = Field(None, max_length=200)
    designation_id: uuid.UUID | None = None
    role: Role | None = None


class ExitAssignmentIn(BaseModel):
    key: str = Field(min_length=1, max_length=200)
    to_membership: uuid.UUID
    pending_action: str | None = None
    due_date: date | None = None
    remark: str | None = Field(None, max_length=2000)


class MembershipEndIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    items_fingerprint: str | None = Field(None, max_length=64)
    assignments: list[ExitAssignmentIn] = Field(default_factory=list)


class ExitCaseOut(BaseModel):
    ref_no: str
    case_no: str | None
    cnr: str | None
    court: str | None
    owning_department: str | None
    visible: bool


class ExitItemOut(BaseModel):
    key: str
    kind: str
    case: ExitCaseOut
    ownership_role: str | None = None
    pending_action: str | None = None
    due_date: date | None = None
    since: datetime | None = None
    leg_seq_no: int | None = None
    open_alerts: int


class ExitCountsOut(BaseModel):
    allotments: int
    files: int
    drafts: int
    open_alerts: int


class ExitTargetOut(BaseModel):
    membership: uuid.UUID
    name: str
    designation: str | None
    office_code: str
    role: Role


class ExitPreviewOut(BaseModel):
    items: list[ExitItemOut]
    counts: ExitCountsOut
    items_fingerprint: str
    targets: list[ExitTargetOut]
    primary_after: uuid.UUID | None


class ReassignedOut(BaseModel):
    key: str
    kind: str
    case_ref: str
    to_membership: uuid.UUID


class ExitResultCountsOut(BaseModel):
    allotments: int
    files: int
    notes_finalised: int
    alerts: int


class MembershipEndOut(BaseModel):
    membership: MembershipOut
    reassigned: list[ReassignedOut]
    counts: ExitResultCountsOut


class PrimaryMembershipIn(BaseModel):
    membership: uuid.UUID


class LookupMembershipOut(BaseModel):
    office_code: str
    designation: str | None
    role: Role


class UserLookupOut(BaseModel):
    id: uuid.UUID
    full_name: str
    memberships: list[LookupMembershipOut]


class MembershipFunctionsOut(BaseModel):
    membership_id: uuid.UUID
    role: Role
    type_functions: list[Permission]
    overrides: list[OverrideOut]
    effective: list[Permission]


class MembershipDocumentOut(BaseModel):
    id: uuid.UUID
    ref_no: str | None
    doc_type: str
    doc_date: date | None
    description: str | None
    ticket_ref: str | None
    archived: bool
    attached_by: str | None
    attached_at: datetime


class HeadIn(BaseModel):
    """The head of a department being created or reactivated: an existing login by e-mail, or a new login
    (e-mail, name, password)."""

    email: EmailStr
    full_name: str | None = Field(None, min_length=2, max_length=200)
    designation: str | None = Field(None, max_length=200)
    designation_id: uuid.UUID | None = None
    mobile: str | None = Field(None, max_length=20)
    password: str | None = Field(None, min_length=10, max_length=200)


class OfficeReactivateIn(BaseModel):
    head: HeadIn | None = None


class AdminSwapIn(BaseModel):
    incoming: dict[str, Any] = Field(
        description="{membership} | {user, designation?} | {email, password, full_name, designation?, mobile?}"
    )
    outgoing: Literal["dept_officer", "end"] = "dept_officer"
    reason: str = Field(min_length=3, max_length=500)
    items_fingerprint: str | None = Field(None, max_length=64)
    assignments: list[ExitAssignmentIn] | None = None


class AdminSwapOutgoingOut(BaseModel):
    membership: uuid.UUID | None
    reassigned: list[ReassignedOut] | None = None


class AdminSwapOut(BaseModel):
    admin: MembershipOut
    outgoing: AdminSwapOutgoingOut


# ------------------------------------------------------------------------------------------------ admin tickets


class TicketTargetOut(BaseModel):
    user_name: str | None
    designation: str | None
    role_from: str | None
    role_to: str | None


class TicketPersonOut(BaseModel):
    name: str | None
    designation: str | None
    office_code: str | None


class TicketItemOut(BaseModel):
    ref_no: str
    kind: str
    status: str
    department_code: str | None
    operation: str | None
    target: TicketTargetOut
    requested_by: TicketPersonOut
    created_at: datetime
    age_days: int
    documents_count: int
    decided_at: datetime | None


class TicketCountsOut(BaseModel):
    open: int
    open_by_kind: dict[str, int]
    open_by_department: dict[str, int]
    oldest_open_at: datetime | None
    departments_without_head: int | None = None


class TicketListOut(BaseModel):
    items: list[TicketItemOut]
    total: int
    counts: TicketCountsOut


class TicketDocumentOut(BaseModel):
    id: uuid.UUID
    ref_no: str | None
    doc_type: str
    doc_date: date | None
    description: str | None
    original_filename: str | None
    mime: str
    size_bytes: int
    archived: bool
    archive_reason: str | None
    attached_by: str | None
    attached_at: datetime


class TicketDetailOut(TicketItemOut):
    payload: dict[str, Any]
    request_remark: str | None
    decision_remark: str | None
    result: dict[str, Any] | None
    decided_by: TicketPersonOut | None
    documents: list[TicketDocumentOut]
    outgoing_detail: dict[str, Any] | None
    can_approve: bool
    can_withdraw: bool
    can_attach: bool


class TicketRemarkIn(BaseModel):
    remark: str | None = Field(None, max_length=2000)


class TicketRejectIn(BaseModel):
    remark: str = Field(min_length=3, max_length=2000)


class TicketArchiveIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


# ------------------------------------------------------------------------------------------------ otp and profile


class LoginStepOut(BaseModel):
    step: Literal["otp"] = "otp"
    challenge_id: uuid.UUID
    purpose: str
    sent_to: str
    expires_in: int
    resend_after: int


class OtpVerifyIn(BaseModel):
    challenge_id: uuid.UUID
    code: str = Field(pattern=r"^[0-9]{6}$")
    device_token: str | None = Field(None, max_length=200)
    device_label: str | None = Field(None, max_length=200)


class OtpResendIn(BaseModel):
    challenge_id: uuid.UUID


class ResetRequestIn(BaseModel):
    email: str = Field(min_length=1, max_length=254)


class ResetStepOut(BaseModel):
    challenge_id: uuid.UUID
    expires_in: int
    resend_after: int


class ResetConfirmIn(BaseModel):
    challenge_id: uuid.UUID
    code: str = Field(pattern=r"^[0-9]{6}$")
    new_password: str = Field(min_length=1, max_length=200)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)
    device_token: str | None = Field(None, max_length=200)


class ProfileMembershipOut(BaseModel):
    office: MembershipOfficeOut
    designation: str | None
    role: Role
    is_primary: bool


class ProfileOut(BaseModel):
    email: str
    full_name: str
    mobile: str | None
    memberships: list[ProfileMembershipOut]
    must_change_password: bool
    must_confirm_profile: bool
    profile_confirmed_at: datetime | None
    notification_preferences: NotificationPreferencesOut


class ProfileConfirmIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    mobile: str | None = Field(None, max_length=20, description="mandatory: an Indian 10-digit number")
    notification_preferences: NotificationPreferencesIn | None = None


class ProfilePatchIn(BaseModel):
    full_name: str | None = Field(None, min_length=1, max_length=200)
    mobile: str | None = Field(None, max_length=20)


class DeviceOut(BaseModel):
    id: uuid.UUID
    label: str | None
    user_agent: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    verified_at: datetime | None
    revoked_at: datetime | None
    current: bool


UserOut.model_rebuild()
MeOut.model_rebuild()
TokenOut.model_rebuild()
OfficeCreateIn.model_rebuild()


# ------------------------------------------------------------------------------------------------ workflow
# design custody-workflow: custody, send and recall, stages, notes and drafts


class CodeLabelOut(BaseModel):
    code: str
    label: str


class NoteKindOut(CodeLabelOut):
    selectable: bool


class PendingActionOut(CodeLabelOut):
    sendable: bool


class StageCodeOut(CodeLabelOut):
    phase: str
    sort_order: int


class WorkflowLimitsOut(BaseModel):
    """Design portal-workflow, decision 20e: the settings the note composer follows."""

    note_max_chars: int
    attachments_max_files: int
    note_drafts_max: int


class WorkflowCodesOut(BaseModel):
    note_kinds: list[NoteKindOut]
    pending_actions: list[PendingActionOut]
    stages: list[StageCodeOut]
    response_modes: list[CodeLabelOut]
    custody_reasons: list[CodeLabelOut]
    limits: WorkflowLimitsOut


class CustodyLegOut(BaseModel):
    seq_no: int
    holder_office: OfficeRefOut
    holder_user: UserRefOut | None
    holder_designation: str | None
    reason: str
    reason_label: str
    pending_action: str
    pending_action_label: str
    due_date: date | None
    remark: str | None
    started_at: datetime
    actor_name: str | None
    actor_designation: str | None
    actor_office_code: str | None


class CustodyHistoryOut(BaseModel):
    card: CustodyCardOut | None
    legs: list[CustodyLegOut]
    total: int


class DepartmentRefOut(BaseModel):
    code: str
    name: str


class RecipientOut(BaseModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    designation: str | None
    office_code: str
    office_name: str
    role_label: str


class RecipientListOut(BaseModel):
    departments: list[DepartmentRefOut] = []
    items: list[RecipientOut] = []
    units: list[DepartmentRefOut] = Field(
        default=[], description="with `department`: the active offices inside it (code and name), by path"
    )
    total: int


class CustodySendIn(BaseModel):
    to_membership: uuid.UUID
    pending_action: str = Field(min_length=1, max_length=40)
    due_date: date | None = None
    remark: str = Field(max_length=2000)
    stage: str | None = Field(None, max_length=40)


class CustodyRecallIn(BaseModel):
    remark: str = Field(max_length=2000)


class CustodyMoveOut(BaseModel):
    card: CustodyCardOut | None
    leg: CustodyLegOut
    finalised_notes: list[str]


class HeldItemOut(BaseModel):
    case: CaseSummaryOut
    card: CustodyCardOut | None


class HeldListOut(BaseModel):
    items: list[HeldItemOut]
    total: int


class SentItemOut(BaseModel):
    case: CaseSummaryOut
    leg: CustodyLegOut
    visible: bool  # design portal-workflow, decision 20g: the caller can open the case now


class SentListOut(BaseModel):
    items: list[SentItemOut]
    total: int


class CustodyCountsOut(BaseModel):
    held: int
    due_soon: int
    overdue: int


class HolderDepartmentCountsOut(CustodyCountsOut):
    code: str


class HolderCountsOut(CustodyCountsOut):
    office_code: str
    user_name: str | None
    designation: str | None


class DepartmentCustodySummaryOut(CustodyCountsOut):
    code: str
    by_holder_department: list[HolderDepartmentCountsOut]
    by_holder: list[HolderCountsOut]


class CustodySummaryOut(BaseModel):
    departments: list[DepartmentCustodySummaryOut]


class StageOut(BaseModel):
    id: uuid.UUID
    stage: str
    label: str
    phase: str | None
    response_mode: str
    response_mode_label: str | None
    note: str | None
    office_code: str | None
    set_by: str | None
    set_at: datetime


class StageHistoryOut(BaseModel):
    current: StageOut | None
    history: list[StageOut]
    gaps: list[str]


class StageSetIn(BaseModel):
    stage: str = Field(min_length=1, max_length=40)
    response_mode: str | None = Field(None, max_length=20)
    note: str | None = Field(None, max_length=2000)


class StageSetOut(BaseModel):
    current: StageOut


class NoteAuthorOut(BaseModel):
    name: str | None
    designation: str | None
    office_code: str | None
    role: str


class NoteRefOut(BaseModel):
    ref_no: str
    seq_no: int


class NoteAttachmentOut(BaseModel):
    id: uuid.UUID
    ref_no: str | None
    original_filename: str | None
    doc_type: str
    mime: str
    size_bytes: int
    linked: bool


class NoteOut(BaseModel):
    id: uuid.UUID
    ref_no: str
    seq_no: int
    kind: str
    kind_label: str
    body: str
    visibility: str
    author: NoteAuthorOut
    created_at: datetime
    drafted_at: datetime | None
    custody_leg_seq_no: int | None
    supersedes: NoteRefOut | None
    superseded_by: NoteRefOut | None
    attachments: list[NoteAttachmentOut]
    can_correct: bool  # design portal-workflow, decision 20b
    draft: Literal[False] = False


class NoteListOut(BaseModel):
    items: list[NoteOut]
    total: int


class DraftDocumentOut(BaseModel):
    id: uuid.UUID  # design portal-workflow, decision 20c: an order PDF has no `ref_no`
    ref_no: str | None
    original_filename: str | None
    doc_type: str
    mime: str


class DraftOut(BaseModel):
    id: uuid.UUID
    kind: str
    body: str
    visibility: str
    supersedes: NoteRefOut | None
    documents: list[DraftDocumentOut]
    created_at: datetime
    updated_at: datetime
    draft: Literal[True] = True


class DraftListOut(BaseModel):
    items: list[DraftOut]


class DraftUpdateIn(BaseModel):
    """Fields left out are unchanged; `supersedes: null` turns a correction into a plain draft."""

    kind: str | None = Field(None, max_length=40)
    body: str | None = Field(None, max_length=20_000)
    visibility: str | None = Field(None, max_length=40)
    supersedes: str | None = Field(None, max_length=60)
    document_refs: list[str] | None = None


# ------------------------------------------------------------------------------------------------ SourceTrace


class SourcetraceCountsOut(BaseModel):
    pending: int
    ingested: int
    failed: int
    not_applicable: int


class SourcetraceRunOut(BaseModel):
    started_at: datetime
    finished_at: datetime | None
    status: str
    counters: dict[str, Any]


class SourcetraceStatusOut(BaseModel):
    state: Literal["disabled", "not_implemented", "ready"]
    connector: str | None
    counts: SourcetraceCountsOut
    waiting_cnr: int
    due_now: int
    oldest_pending_at: datetime | None
    last_run: SourcetraceRunOut | None


class SourcetraceCaseOut(BaseModel):
    id: uuid.UUID
    ref_no: str | None
    cnr: str | None = None
    case_no_text: str | None = None


class SourcetraceFailedItemOut(BaseModel):
    document_id: uuid.UUID
    ref_no: str | None = None
    kind: str
    doc_type: str
    doc_date: date | None
    case: SourcetraceCaseOut | None
    attempts: int
    last_error: str | None
    error_family: str | None
    last_attempt_at: datetime | None


class SourcetraceFailedOut(BaseModel):
    total: int
    items: list[SourcetraceFailedItemOut]


class SourcetraceRetryOut(BaseModel):
    document_id: uuid.UUID
    sourcetrace_status: str
    sourcetrace_attempts: int


# ------------------------------------------------------------------ dashboards and reports (reports-dashboards)


class DashboardDepartmentRefOut(BaseModel):
    code: str
    name: str


class DashboardIndexOut(BaseModel):
    me: bool
    departments: list[DashboardDepartmentRefOut]
    state: bool


class DashboardFileOut(BaseModel):
    case: AlertCaseOut
    pending_action: str
    since: datetime
    due_date: date | None
    overdue_days: int
    holder_office_code: str | None


class DashboardHearingOut(BaseModel):
    date: date
    case: AlertCaseOut
    court_no: str | None
    item_no: str | None
    critical: bool


class DashboardHearingsOut(BaseModel):
    total: int
    critical: int
    items: list[DashboardHearingOut]


class DashboardOwnCasesOut(BaseModel):
    department_code: str
    allotted_active: int
    allotted_disposed: int
    counsel_active: int | None = None


class DashboardFilesOut(BaseModel):
    held: int
    with_pending_action: int
    overdue: int
    items: list[DashboardFileOut]


class DashboardAlertOut(BaseModel):
    id: uuid.UUID
    ref_no: str
    kind: str
    kind_label: str
    severity: str
    status: str
    title: str
    due_at: datetime | None
    case: AlertCaseOut | None
    case_visible: bool  # design portal-files-alerts, decision 6
    created_at: datetime


class DashboardAlertsOut(BaseModel):
    unread: int
    open: AlertOpenCountsOut
    items: list[DashboardAlertOut]


class DashboardClaimCountsOut(BaseModel):
    high: int
    medium: int


class DashboardWeekHearingsOut(BaseModel):
    total: int
    within_48h: int


class DashboardFilesWithMeOut(BaseModel):
    total: int
    due_today: int


class DashboardOverdueOut(BaseModel):
    total: int
    oldest_days: int | None


class DashboardHeadlineOut(BaseModel):
    """Design `portal-ui-redesign`, A7: the five headline figures; a null one is not shown (its gate fails)."""

    to_claim: DashboardClaimCountsOut | None
    hearings_week: DashboardWeekHearingsOut
    files_with_me: DashboardFilesWithMeOut
    overdue_actions: DashboardOverdueOut
    next_dates_to_confirm: int | None


class DashboardUpcomingOut(BaseModel):
    date: date
    case: AlertCaseOut
    court_no: str | None
    item_no: str | None
    critical: bool
    this_week: bool


class DashboardMeAttentionOut(BaseModel):
    """One item that needs the caller (A7): an overdue file, a next date to confirm, a file due soon or a file
    received lately."""

    kind: Literal["overdue_action", "confirm_next_date", "due_soon", "file_received"]
    case: AlertCaseOut
    title: str
    date: date | None
    detail: str | None
    pending_action: str | None
    overdue_days: int
    next_date_id: uuid.UUID | None


class DashboardMeOut(BaseModel):
    generated_at: datetime
    cases: list[DashboardOwnCasesOut]
    files: DashboardFilesOut
    alerts: DashboardAlertsOut
    hearings: DashboardHearingsOut
    drafts: int
    headline: DashboardHeadlineOut
    upcoming: list[DashboardUpcomingOut]
    attention: list[DashboardMeAttentionOut]


class DashboardRecommendationsOut(BaseModel):
    high: int
    medium: int
    transfers_in_open: int


class DashboardCasesOut(BaseModel):
    claimed_active: int
    claimed_disposed: int
    watching_active: int
    not_allotted_active: int


class DashboardPendingActionsOut(BaseModel):
    held: int
    due_soon: int
    overdue: int
    no_due_date: int
    items: list[DashboardFileOut] | None = None


class DashboardCustodyOfficeOut(BaseModel):
    holder_department_code: str
    office_code: str
    office_name: str
    held: int
    with_pending_action: int
    overdue: int


class DashboardOrderNextDateOut(BaseModel):
    case: AlertCaseOut
    next_date: date
    source: str
    review_status: str


class DashboardAttentionOut(BaseModel):
    next_dates_to_review: int | None
    recent_order_next_dates: list[DashboardOrderNextDateOut]
    compliance_due_soon: int
    compliance_overdue: int


class DashboardDepartmentOut(BaseModel):
    generated_at: datetime
    department: DashboardDepartmentRefOut
    recommendations: DashboardRecommendationsOut | None
    cases: DashboardCasesOut
    hearings: DashboardHearingsOut
    pending_actions: DashboardPendingActionsOut | None
    custody_by_office: list[DashboardCustodyOfficeOut] | None
    attention: DashboardAttentionOut


class DashboardStateRowOut(BaseModel):
    code: str
    name: str
    is_active: bool
    claimed_active: int
    claimed_disposed: int
    recommended_high: int
    recommended_medium: int
    hearings_7d: int
    pending_actions: int
    overdue_actions: int
    compliance_due_soon: int
    compliance_overdue: int


class DashboardNotClaimedOut(BaseModel):
    active: int
    recommended: int
    hearing_7d: int


class DashboardCodeCountOut(BaseModel):
    code: str
    overdue: int


class DashboardOverdueActionsOut(BaseModel):
    total: int
    by_owner: list[DashboardCodeCountOut]
    by_holder: list[DashboardCodeCountOut]


class DashboardComplianceOut(BaseModel):
    due_soon: int
    overdue: int


class DashboardStateOut(BaseModel):
    generated_at: datetime
    by_department: list[DashboardStateRowOut]
    not_claimed: DashboardNotClaimedOut
    hearings: DashboardHearingsOut
    overdue_actions: DashboardOverdueActionsOut
    compliance: DashboardComplianceOut


class ReportCatalogueItemOut(BaseModel):
    key: str
    title: str
    params: list[str]
    scopes: list[str]
    departments: list[str]


class ReportDepartmentOut(BaseModel):
    code: str
    name: str
    is_active: bool


class ReportCatalogueOut(BaseModel):
    reports: list[ReportCatalogueItemOut]
    departments: list[ReportDepartmentOut]


class ReportColumnOut(BaseModel):
    key: str
    label: str
    kind: str


class ReportSectionOut(BaseModel):
    key: str
    title: str
    columns: list[ReportColumnOut]
    rows: list[dict[str, Any]]
    totals: dict[str, Any] | None
    note: str | None
    total_rows: int
    truncated: bool


class ReportGeneratedByOut(BaseModel):
    name: str
    designation: str | None
    office_code: str | None


class ReportOut(BaseModel):
    key: str
    title: str
    scope: str
    department_code: str | None
    params: dict[str, Any]
    generated_at: datetime
    generated_by: ReportGeneratedByOut
    as_of_note: str
    sections: list[ReportSectionOut]


# ------------------------------------------------------------------ audit log and data health (audit-screens)


class AuditCaseOut(BaseModel):
    id: uuid.UUID
    ref_no: str | None
    cnr: str | None = None
    case_no_text: str | None = None


class AuditActorOut(BaseModel):
    user_id: uuid.UUID | None
    name: str | None
    designation: str | None
    office_code: str | None


class AuditRowOut(BaseModel):
    id: uuid.UUID
    at: datetime
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    case: AuditCaseOut | None
    actor: AuditActorOut
    ip: str | None
    user_agent: str | None
    before: Any = None
    after: Any = None


class AuditPageOut(BaseModel):
    items: list[AuditRowOut]
    next_cursor: str | None


class AuditActionsOut(BaseModel):
    actions: list[str]


class NapixResetOut(BaseModel):
    observed_at: datetime
    previous_at: datetime
    previous_remaining: int
    remaining: int
    precise: bool


class NapixWindowOut(BaseModel):
    """The detected quota window (design `napix-window`, decisions 1-6): the reset is seen in the call log, never
    assumed to be the clock hour."""

    status: Literal["current", "reset_due", "overdue", "unknown"]
    started_at: datetime | None
    observed_at: datetime | None
    next_reset_at: datetime | None
    seconds_to_next_reset: int | None = Field(None, description="negative while due or overdue")
    anchor_at: datetime | None
    calls: int = Field(description="since observed_at; 0 while the reset is due")
    failed: int
    remaining: int | None
    last_reading_at: datetime | None
    recent_resets: list[NapixResetOut] = Field(description="last 6 h, newest first")
    window_seconds: int
    margin_seconds: int
    probe_seconds: int
    reserve: int
    live_reserve: int
    search_floor: int


class UserCallsOut(BaseModel):
    user_id: uuid.UUID
    name: str
    calls: int
    failed: int


class NapixByUserOut(BaseModel):
    window: list[UserCallsOut]
    today: list[UserCallsOut]


class NapixTodayOut(BaseModel):
    calls: int
    failed: int
    by_family: dict[str, int]
    token_unverified: int


class NapixLastFailureOut(BaseModel):
    called_at: datetime
    api: str
    http_status: int | None
    napix_status: int | None
    error_family: str | None


class NapixLastCheckOut(BaseModel):
    called_at: datetime
    ok: bool
    duration_ms: int
    token_verified: bool | None
    error_family: str | None


class NapixHealthOut(BaseModel):
    enabled: bool
    est_code: str
    window: NapixWindowOut
    today: NapixTodayOut
    last_call_at: datetime | None
    last_ok_at: datetime | None
    last_failure: NapixLastFailureOut | None
    last_check: NapixLastCheckOut | None
    by_user: NapixByUserOut | None = Field(
        None, description="NAPIX operators only (admin.napix_refetch or admin.masters_sync); null otherwise"
    )


class LaneCountsOut(BaseModel):
    request: int
    daily: int
    discovery: int  # design department-discovery, decision 13 (e)
    load: int


class QueueKindOut(BaseModel):
    kind: str
    pending: int
    runnable: int
    waiting: int
    running: int
    stale: int
    failed: int
    skipped: int
    done: int
    by_lane: LaneCountsOut


class QueueDepthsOut(BaseModel):
    by_kind: list[QueueKindOut]
    oldest_runnable_at: datetime | None
    failed_total: int


class CauselistDayRowOut(BaseModel):
    status: str
    attempts: int
    finished_at: datetime | None
    last_error: str | None


class DailyCycleDayOut(BaseModel):
    date: date
    label: str
    causelist_day: CauselistDayRowOut | None
    lists_stored: int
    entries_parsed: int
    lists_parse_failed: int


class StatusBatchesOut(BaseModel):
    date: date | str
    done: int
    failed: int
    pending: int
    running: int


class MasterSyncOut(BaseModel):
    master: str
    fetched_at: datetime
    row_count: int


class JobRunOut(BaseModel):
    job: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    counters: dict[str, Any]


class MailOutboxOut(BaseModel):
    email_queued: int
    email_failed: int
    email_oldest_queued_at: datetime | None
    digests_queued: int
    digests_failed: int


class FailureKindOut(BaseModel):
    kind: str
    open: int
    oldest_first_seen: datetime | None


class DocumentsTextNoneOut(BaseModel):
    scanned_pdf: int = Field(description="PDFs without a text layer: scanned, not read")
    image: int = Field(description="JPEG and PNG images: not read")
    doc: int = Field(description="old Word (.doc) files: not read")
    other: int = Field(description="other files with no text in them (an empty Word .docx)")


class DocumentsTextKindOut(BaseModel):
    pending: int
    extracted: int
    failed: int
    none: DocumentsTextNoneOut


class DocumentsTextOut(BaseModel):
    """Design `document-ocr`, decision 4: documents by text status (totals only)."""

    order: DocumentsTextKindOut
    upload: DocumentsTextKindOut
    attachment: DocumentsTextKindOut


class DataHealthOut(BaseModel):
    as_of: datetime
    napix: NapixHealthOut
    queue: QueueDepthsOut
    daily_cycle: list[DailyCycleDayOut]
    status_batches: StatusBatchesOut | None
    masters: list[MasterSyncOut]
    jobs: list[JobRunOut]
    mail: MailOutboxOut
    sourcetrace: SourcetraceStatusOut
    failures: list[FailureKindOut]
    documents_text: DocumentsTextOut


class QueueRowOut(BaseModel):
    id: uuid.UUID
    kind: str
    ref: str
    priority: int
    status: str
    attempts: int
    not_before: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    last_error: str | None
    result: Any = None
    updated_at: datetime | None
    lane: str
    list_date: date | None


class QueueListOut(BaseModel):
    total: int
    items: list[QueueRowOut]


class CallRowOut(BaseModel):
    id: uuid.UUID
    called_at: datetime
    api: str
    http_status: int | None
    napix_status: int | None
    ok: bool
    error_family: str | None
    error: str | None
    duration_ms: int
    token_verified: bool | None
    rate_limit_remaining: int | None
    job_run_id: uuid.UUID | None
    lane: str | None = None
    user_id: uuid.UUID | None = Field(None, description="NAPIX operators only")
    user_name: str | None = Field(None, description="NAPIX operators only")


class CallListOut(BaseModel):
    items: list[CallRowOut]
    next_cursor: str | None


class FailureRowOut(BaseModel):
    id: uuid.UUID
    kind: str
    ref: str
    error: str | None
    error_family: str | None
    first_seen: datetime
    last_seen: datetime
    attempts: int
    resolved_at: datetime | None


class FailureListOut(BaseModel):
    total: int
    items: list[FailureRowOut]


class HealthCheckOut(BaseModel):
    ok: bool
    called_at: datetime
    http_status: int | None
    napix_status: int | None
    error_family: str | None
    duration_ms: int
    token_verified: bool | None
    remaining: int | None


class QueueStateOut(BaseModel):
    kind: str
    ref: str
    queue_id: uuid.UUID | None
    status: str | None
    priority: int | None
    attempts: int
    not_before: datetime | None
    lane: str | None = None
    napix_enabled: bool


class RefetchDayIn(BaseModel):
    date: date
    force: bool = Field(False, description="queue a day already held (done with lists, or skipped) anyway")


class RefetchCaseIn(BaseModel):
    case: str = Field(min_length=1, max_length=200)
    force: bool = Field(False, description="queue a case whose details are already held anyway")


class RefetchOrderIn(BaseModel):
    case: str = Field(min_length=1, max_length=200)
    order_id: uuid.UUID


class RetryFailedIn(BaseModel):
    kind: Literal[
        "masters", "causelist_day", "dossier", "status_batch", "order_pdf", "party_search", "search_rows"
    ]
    lane: Literal["request", "daily", "discovery", "load"] | None = None


class RetryFailedOut(BaseModel):
    kind: str
    retried: int


# ------------------------------------------------------------------------------------------------ the data-load console


class DataLoadSettingsOut(BaseModel):
    version: int
    paused: bool
    load_order: str
    first_from: date | None
    first_to: date | None
    reason: str | None
    changed_at: datetime | None
    changed_by: str | None


class LoadPeriodOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: date = Field(alias="from")
    to: date


class DayTotalsOut(BaseModel):
    calendar: int
    with_lists: int
    no_list: int
    waiting: int
    failed: int
    not_queued: int


class CaseTotalsOut(BaseModel):
    listed: int
    with_details: int
    provisional: int


class OrderTotalsOut(BaseModel):
    referenced: int
    stored: int
    not_available: int
    waiting: int


class LoadTotalsOut(BaseModel):
    days: DayTotalsOut
    cases: CaseTotalsOut
    orders: OrderTotalsOut


class WorkLeftOut(BaseModel):
    kind: str
    pending: int
    runnable: int
    waiting: int
    running: int
    failed: int


class LoadFailureKindOut(BaseModel):
    kind: str
    failed: int


class LoadFailureRowOut(BaseModel):
    id: uuid.UUID
    kind: str
    ref: str
    attempts: int
    last_error: str | None
    finished_at: datetime | None


class LoadFailuresOut(BaseModel):
    by_kind: list[LoadFailureKindOut]
    latest: list[LoadFailureRowOut]


class AllowanceUsedOut(BaseModel):
    load: int
    discovery: int  # design department-discovery, decision 13 (e)
    daily: int
    request: int
    outside_queue: int


class AllowanceOut(BaseModel):
    """The detected quota window (design `napix-window`, decision 6); `used` counts from the observed reset."""

    window_started_at: datetime | None
    next_reset_at: datetime | None
    seconds_to_next_reset: int | None
    window_status: Literal["current", "reset_due", "overdue", "unknown"]
    used: AllowanceUsedOut
    remaining: int | None
    rate_reserve: int
    live_reserve: int
    search_floor: int


class EstimateOut(BaseModel):
    finish_at: datetime | None
    hours: float | None
    calls_needed: float | None
    reason: str | None = Field(None, description="paused | not_enough_history | no_recent_calls")
    basis: dict[str, Any]


class DataLoadOut(BaseModel):
    as_of: datetime
    napix_enabled: bool
    settings: DataLoadSettingsOut
    period: LoadPeriodOut | None
    totals: LoadTotalsOut | None
    work_left: list[WorkLeftOut]
    failures: LoadFailuresOut
    allowance: AllowanceOut
    estimate: EstimateOut


class KindCountsOut(BaseModel):
    causelist_day: int
    dossier: int
    order_pdf: int


class MonthCoverageOut(BaseModel):
    month: str
    days: DayTotalsOut
    lists: int
    entries: int
    lists_parse_failed: int
    cases: CaseTotalsOut
    orders: OrderTotalsOut
    work_left: KindCountsOut
    failed: KindCountsOut
    days_covered_pct: float
    details_pct: float | None


class CoverageOut(BaseModel):
    months: list[MonthCoverageOut]


class LoadRangeIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: date = Field(alias="from")
    to: date


class LoadStartIn(LoadRangeIn):
    held: Literal["skip", "refetch"] | None = Field(
        None, description="what to do with days already held; required when the range has any"
    )


class LoadPreviewOut(BaseModel):
    days: int
    held_with_lists: int
    held_no_list: int
    waiting: int
    failed: int
    not_queued: int
    calls_estimate: float | None
    masters_stale: bool


class LoadStartOut(BaseModel):
    days: int
    queued: int
    held_skipped: int
    held_requeued: int
    revived: int
    masters_queued: bool


class LoadPauseIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class LoadResumeIn(BaseModel):
    reason: str | None = Field(None, max_length=500)


class LoadOrderIn(BaseModel):
    load_order: Literal["cases_first", "lists_first", "cases_with_orders"]
    first_from: date | None = None
    first_to: date | None = None
    reason: str = Field(min_length=3, max_length=500)


class LoadOrderOut(BaseModel):
    settings: DataLoadSettingsOut
    reprioritised: int


class LoadFetchCnrIn(CourtSearchCnrIn):
    force: bool = False


class LoadFetchCaseNumberIn(CourtSearchCaseNumberIn):
    force: bool = False


class LoadFetchPartyIn(CourtSearchPartyIn):
    force: bool = False


LoadFetchIn = Annotated[
    LoadFetchCnrIn | LoadFetchCaseNumberIn | LoadFetchPartyIn, Field(discriminator="kind")
]


class HeldCaseOut(CaseSearchItemOut):
    dossier_fetched_at: datetime | None
    dossier_stale: bool


class FetchDetailsIn(BaseModel):
    cases: list[str] = Field(min_length=1, max_length=200)
    force: bool = False


class FetchDetailItemOut(BaseModel):
    ref: str
    case: CaseSearchItemOut | None
    state: Literal["queued", "already_held", "merged", "no_reference", "not_found"]
    queue: QueueStateOut | None = None
    merged_into_ref_no: str | None = None


class FetchDetailsOut(BaseModel):
    items: list[FetchDetailItemOut]


class DuplicateCaseOut(BaseModel):
    id: uuid.UUID
    ref_no: str
    cnr: str | None
    case_no_text: str | None


class DuplicateItemOut(BaseModel):
    kind: str
    case: DuplicateCaseOut | None
    other: DuplicateCaseOut | None
    at: datetime | None
    reasons: str | None = None


class DuplicatesOut(BaseModel):
    total: int
    items: list[DuplicateItemOut]


class DedupeScanOut(BaseModel):
    merged: int
    needs_review: int
    court_linked: int


# ------------------------------------------------------------------------------------------------ cause lists


class CauselistDateOut(BaseModel):
    date: date
    state: Literal["held", "loading", "no_list", "failed", "not_loaded"]
    lists: int
    benches: int
    entries: int


class CauselistDatesOut(BaseModel):
    """Design `portal-causelist`, decision 4: the dates of a range with lists or a queue row, and the date the
    screen opens on (court-public, the same for every reader)."""

    model_config = ConfigDict(populate_by_name=True)

    from_: date = Field(alias="from")
    to: date
    today: date
    default_date: date
    items: list[CauselistDateOut]


class CauselistOut(BaseModel):
    id: uuid.UUID
    list_type: str
    list_type_text: str | None
    label: str | None
    napix_causelist_id: int | None
    source: str
    entry_count: int
    entries_stored: int
    fetch_status: str
    parse_status: str
    has_pdf: bool


class CauselistBenchOut(BaseModel):
    bench_id: int | None
    label: str | None
    court_nos: list[str]
    source: str
    entries: int
    lists: list[CauselistOut]


class CauselistDayTotalsOut(BaseModel):
    benches: int
    lists: int
    entries: int


class CauselistDayOut(BaseModel):
    """Decision 2: one day's benches in court order with their lists (court-public)."""

    date: date
    state: Literal["held", "loading", "no_list", "failed", "not_loaded"]
    queue_status: str | None
    queue_finished_at: datetime | None
    previous_date: date | None
    next_date: date | None
    totals: CauselistDayTotalsOut
    benches: list[CauselistBenchOut]


class EntryRecommendationOut(BaseModel):
    office_code: str
    band: str
    score: float


class CauselistCountsOut(BaseModel):
    entries: int
    recommended: int
    mine: int
    claimable: int
    claimed: int
    unclaimed: int


class CauselistEntryOut(BaseModel):
    id: uuid.UUID
    causelist_id: uuid.UUID
    list_type: str
    bench_id: int | None
    bench_label: str | None
    court_no: str | None
    sr_no: int
    printed_sr_no: str | None
    section: str | None
    is_connected: bool
    with_text: str | None
    case_no_text: str | None
    cnr: str | None
    petitioner_text: str | None
    respondent_text: str | None
    pet_advocate_text: str | None
    res_advocate_text: str | None
    counsel_codes: list[str]
    remarks: str | None
    source: str
    resolution_status: str
    case: CaseSummaryOut | None
    visible: bool
    owner_office_code: str | None
    held_by_you: Literal["primary", "watcher"] | None
    in_pool: bool
    recommendations: list[EntryRecommendationOut]
    claimable: bool


class CauselistEntriesOut(BaseModel):
    """Decisions 1, 3, 6-8: every stored row of the place in court order, with the portal's facts scoped to the
    caller; `counts` are for the place before `q` and `only`."""

    date: date
    total: int
    counts: CauselistCountsOut
    items: list[CauselistEntryOut]


# ------------------------------------------------------------------------------------------------ department discovery


class DiscoveryRuleOut(BaseModel):
    kind: str  # keyword | exact | prefix
    rule_id: uuid.UUID
    office_code: str
    is_active: bool


class DiscoveryYearsOut(BaseModel):
    done: int
    waiting: int
    failed: int


class DiscoveryTermOut(BaseModel):
    id: uuid.UUID
    term: str
    active: bool
    departments: list[str]
    rules: list[DiscoveryRuleOut]
    years: DiscoveryYearsOut
    last_searched_at: datetime | None
    cases_found: int
    found_last_7_days: int
    full_sweep_queued_at: datetime | None
    recent_sweep_queued_at: datetime | None


class DiscoveryTermListOut(BaseModel):
    items: list[DiscoveryTermOut]
    total: int


class DiscoveryRecommendationOut(BaseModel):
    office_code: str
    band: str
    score: float
    status: str


class DiscoveryCaseOut(BaseModel):
    case: CaseSummaryOut
    reg_year: int
    first_found_at: datetime
    last_found_at: datetime
    owner_office_code: str | None
    recommendation: DiscoveryRecommendationOut | None
    claimable: bool


class DiscoveryCaseListOut(BaseModel):
    items: list[DiscoveryCaseOut]
    total: int


class DiscoverySearchIn(BaseModel):
    """A user's request on the Court search tab: a name (one of the department's terms) and the years to search."""

    name: str = Field(min_length=1, max_length=200)
    years: list[int] = Field(min_length=1, max_length=30)
    force: bool = Field(False, description="search again a name and year searched before")


class DiscoverySearchOut(BaseModel):
    term_id: uuid.UUID
    term: str
    years: list[int]
    queued: bool


class DiscoverySweepIn(BaseModel):
    term_id: uuid.UUID | None = None


class DiscoverySweepOut(BaseModel):
    terms: int
    rows_queued: int


class DiscoverySettingsOut(BaseModel):
    share: int
    from_year: int


class DiscoveryWindowOut(BaseModel):
    status: str
    started_at: datetime | None
    next_reset_at: datetime | None
    discovery_calls: int
    share_left: int


class DiscoveryQueueCountsOut(BaseModel):
    pending: int
    waiting: int
    running: int
    failed: int


class DiscoveryQueueByKindOut(BaseModel):
    party_search: DiscoveryQueueCountsOut
    dossier: DiscoveryQueueCountsOut
    order_pdf: DiscoveryQueueCountsOut


class DiscoveryQueueOut(BaseModel):
    by_kind: DiscoveryQueueByKindOut


class DiscoveryTermCountsOut(BaseModel):
    active: int
    inactive: int


class DiscoveryCaseCountsOut(BaseModel):
    found: int
    created_by_discovery: int
    recommended_from_discovery: int


class DiscoveryFailureOut(BaseModel):
    kind: str
    ref: str
    last_error: str | None
    finished_at: datetime | None


class DiscoverySummaryOut(BaseModel):
    """`GET /admin/discovery`: system figures only, for the Data collection screens."""

    settings: DiscoverySettingsOut
    window: DiscoveryWindowOut
    queue: DiscoveryQueueOut
    terms: DiscoveryTermCountsOut
    cases: DiscoveryCaseCountsOut
    last_searched_at: datetime | None
    latest_failures: list[DiscoveryFailureOut]


# ------------------------------------------------------------------------------------------------ system health

HealthStatus = Literal["ok", "warn", "down", "unknown"]


class FactOut(BaseModel):
    label: str
    value: str


class CallOut(BaseModel):
    """One `napix_call_log` row as the System health screen shows it: who made it is never a name."""

    called_at: datetime
    answered: bool
    ok: bool
    duration_ms: int
    http_status: int | None
    napix_status: int | None
    error_family: str | None
    reason: str
    by: Literal["background", "person", "you"]


class Rate24Out(BaseModel):
    calls: int
    answered: int
    failed: int
    rate: float | None = Field(description="answered / calls; null without calls")
    p50_ms: int | None
    p95_ms: int | None


class Rate7Out(BaseModel):
    calls: int
    answered: int
    failed: int
    rate: float | None


class HourBucketOut(BaseModel):
    hour: datetime = Field(description="the IST hour's start")
    answered: int
    failed: int
    avg_ms: int | None


class ApiTestStateOut(BaseModel):
    available: bool
    reason: str | None
    cost: int = Field(description="court calls one test makes")
    next_allowed_at: datetime | None


class LastTestOut(BaseModel):
    at: datetime
    ok: bool | None
    by_you: bool


class ApiCardOut(BaseModel):
    key: str
    label: str
    label_key: str
    group: str
    status: HealthStatus
    status_word: str
    last_call: CallOut | None
    h24: Rate24Out
    d7: Rate7Out
    hours: list[HourBucketOut] = Field(description="24 IST hours, oldest first")
    test: ApiTestStateOut
    last_test: LastTestOut | None


class ApiGroupOut(BaseModel):
    key: str
    label: str
    cards: list[ApiCardOut]


class CourtSummaryOut(BaseModel):
    working: int
    unsteady: int
    failing: int
    no_recent: int
    total: int


class SystemHealthOut(BaseModel):
    """`GET /admin/system-health` (design `api-health-checker`): the court cards from the call log. Never calls
    NAPIX, never probes services."""

    as_of: datetime
    napix_enabled: bool
    window: NapixWindowOut
    groups: list[ApiGroupOut]
    summary: CourtSummaryOut


class DayBucketOut(BaseModel):
    date: date
    calls: int
    answered: int
    failed: int
    avg_ms: int | None


class SampleOut(BaseModel):
    available: bool
    label: str | None
    values: dict[str, Any] = Field(description="non-personal values only; never a name")
    reason: str | None


class TechnicalOut(BaseModel):
    name: str
    path: str
    method: str
    input_fields: list[str]


class ApiDetailOut(BaseModel):
    card: ApiCardOut
    days: list[DayBucketOut] = Field(description="7 IST days, oldest first")
    recent: list[CallOut] = Field(description="the last 10 calls, newest first")
    sample: SampleOut
    technical: TechnicalOut


class ApiTestInputOut(BaseModel):
    label: str
    values: dict[str, Any]


class ApiTestSummaryOut(BaseModel):
    kind: Literal["rows", "record", "pdf"]
    row_count: int | None
    field_names: list[str]
    facts: list[FactOut]


class EnvelopeItemOut(BaseModel):
    name: str
    shown: str = Field(description="the value as shown: dept_id masked, request_str never")
    note: str
    length: int | None = None


class HeaderOut(BaseModel):
    name: str
    shown: str


class SentRequestOut(BaseModel):
    method: str
    url: str
    plain: str
    envelope: list[EnvelopeItemOut]


class RateLimitOut(BaseModel):
    limit: int | None = None
    remaining: int | None = None


class StructurePathOut(BaseModel):
    path: str
    type: str
    count: int


class StructureOut(BaseModel):
    """An answer's field paths, types and counts; never a value (design `system-health-inspector`, decision 5)."""

    paths: list[StructurePathOut]
    total: int
    more: int
    depth_limited: bool


class InventoryDiffOut(BaseModel):
    checked: bool
    new: list[str] = Field(description="paths not in the field inventory: a field without a home, report it")
    absent: list[str] = Field(description="inventory paths not in this answer (information)")


class ApiTestOut(BaseModel):
    """One court call's outcome, summarised; the payload is never returned. A court failure is `ok: false`."""

    api: str
    ok: bool
    answered: bool
    status: HealthStatus
    reason: str
    http_status: int | None
    napix_status: int | None
    error_family: str | None
    duration_ms: int
    attempts: int
    called_at: datetime
    token_verified: bool | None
    remaining: int | None
    input: ApiTestInputOut
    summary: ApiTestSummaryOut
    request: SentRequestOut
    edited: bool
    rate_limit: RateLimitOut
    structure: StructureOut | None
    inventory_diff: InventoryDiffOut | None
    response_id: uuid.UUID | None
    response_available: bool
    http_meaning: str | None
    napix_meaning: str | None


class ConsoleValuesIn(BaseModel):
    """The console's form: NAPIX parameter name -> value (design `system-health-inspector`, decision 8)."""

    values: dict[str, str | int | None] = Field(default_factory=dict)


class ConsoleFieldOut(BaseModel):
    name: str
    value: str
    prefilled: bool
    source: Literal["settings", "held", "empty"]
    editable: bool
    mandatory: bool = Field(description="as the specification says")
    required: bool = Field(description="the console needs a value")
    format: str
    meaning: str
    hint: str | None


class TemplatesOut(BaseModel):
    curl: str
    note: str


class ConsoleRequestOut(BaseModel):
    """`POST /admin/system-health/napix/{api}/preview`: the request for the form's values. No call."""

    api: str
    label: str
    method: str
    method_note: str | None
    url: str
    plain: str
    plain_sha256: str
    plain_complete: bool
    no_input_note: str | None
    envelope: list[EnvelopeItemOut]
    headers: list[HeaderOut]
    request_token: str | None = Field(description="HMAC-SHA256 under the published hash key; not secret")
    templates: TemplatesOut


class ConsoleSampleOut(BaseModel):
    available: bool
    label: str | None
    reason: str | None


class LastSendOut(BaseModel):
    at: datetime
    by: Literal["you", "person"]
    recorded: bool = Field(description="false for tests before this version: the new facts are null")
    edited: bool | None
    ok: bool
    answered: bool
    status: HealthStatus
    reason: str
    method: str
    url: str
    plain: str | None
    params_sha256: str | None
    http_status: int | None
    http_meaning: str | None
    napix_status: int | None
    napix_meaning: str | None
    error_family: str | None
    duration_ms: int
    attempts: int
    remaining: int | None
    rate_limit: RateLimitOut | None
    window_reset_at: datetime | None
    token_verified: bool | None
    summary: ApiTestSummaryOut | None
    structure: StructureOut | None
    inventory_diff: InventoryDiffOut | None
    response_id: uuid.UUID | None
    response_available: bool
    same_plain_as_form: bool | None


class LatestAnswerOut(BaseModel):
    at: datetime
    by: Literal["you", "person", "background"]
    structure: StructureOut | None
    inventory_diff: InventoryDiffOut | None
    response_id: uuid.UUID | None
    response_available: bool


class DocLinkOut(BaseModel):
    doc: str
    page: int
    section: str
    available: bool = True


class ConsoleOut(ConsoleRequestOut):
    """`GET /admin/system-health/napix/{api}/console`: the request console of one court API. Never calls NAPIX."""

    fields: list[ConsoleFieldOut]
    sample: ConsoleSampleOut
    send: ApiTestStateOut
    last_send: LastSendOut | None
    latest_answer: LatestAnswerOut | None
    doc: DocLinkOut
    full_answer_allowed: bool
    not_saved_note: str
    full_answer_note: str | None


class StoredResponseOut(BaseModel):
    """The verbatim decrypted answer (State-wide viewers only; audited `napix.response_viewed`)."""

    api: str
    source: Literal["send", "latest"]
    response_id: uuid.UUID
    fetched_at: datetime
    last_seen_at: datetime
    token_verified: bool | None
    bytes: int
    payload: Any


class ReferenceInputOut(BaseModel):
    name: str
    mandatory: bool
    required: bool
    format: str
    meaning: str
    note: str | None


class ReferencePathOut(BaseModel):
    path: str
    type: str


class ReferenceOutputsOut(BaseModel):
    kind: Literal["json", "pdf"]
    note: str | None
    paths: list[ReferencePathOut]


class ReferenceStatusOut(BaseModel):
    code: str
    name: str | None
    meaning: str
    listed: bool = Field(description="listed for this API in the specification")


class ReferenceLinkOut(BaseModel):
    doc: str
    page: int
    label: str


class ReferenceOut(BaseModel):
    """`GET /admin/system-health/napix/{api}/reference`: the in-app NAPIX reference. Static."""

    api: str
    inputs: list[ReferenceInputOut]
    outputs: ReferenceOutputsOut
    statuses: list[ReferenceStatusOut]
    build_steps: list[str]
    read_steps: list[str]
    doc: DocLinkOut
    general_links: list[ReferenceLinkOut]


class NapixDocOut(BaseModel):
    doc: str
    title: str
    pages: int
    available: bool


class AcceptedOut(BaseModel):
    at: datetime
    api_label: str
    http_status: int


class TokenRequestOut(BaseModel):
    at: datetime | None
    ok: bool
    outcome: str | None
    http_status: int | None
    duration_ms: int | None
    rate_limit: RateLimitOut


class TokenFailureOut(BaseModel):
    at: datetime | None
    family: str | None


class TokenEndpointOut(BaseModel):
    method: str
    url: str
    body: str
    content_type: str
    auth_note: str


class TokenCheckStateOut(BaseModel):
    allowed: bool
    reason: str | None
    next_allowed_at: datetime | None


class NapixTokenOut(BaseModel):
    """`GET /admin/system-health/token`: the access token's state, read with no call; never the token."""

    status: HealthStatus
    napix_enabled: bool
    shared_store: bool
    held: bool
    ttl_seconds: int | None
    renewing_soon: bool
    valid_until: datetime | None
    expires_at: datetime | None
    obtained_at: datetime | None
    token_type: str | None
    scope: str | None
    accepted_since: AcceptedOut | None
    rejected_since: int
    last_request: TokenRequestOut | None
    last_failure: TokenFailureOut | None
    requests_today: int
    endpoint: TokenEndpointOut
    curl_token: str
    check: TokenCheckStateOut


class NapixTokenCheckOut(BaseModel):
    """`POST /admin/system-health/token/check`: one token request's outcome; never the token."""

    ok: bool
    http_status: int | None
    outcome: str | None
    duration_ms: int
    expires_in: int | None
    rate_limit: RateLimitOut
    token: NapixTokenOut


class ServiceCheckOut(BaseModel):
    key: str
    label: str
    status: HealthStatus
    headline: str
    facts: list[FactOut]
    duration_ms: int


class OverallCountsOut(BaseModel):
    court_working: int
    court_total: int
    services_working: int
    services_total: int
    attention: int
    not_working: int


class OverallOut(BaseModel):
    status: HealthStatus
    sentence_key: Literal["everything_working", "need_attention", "not_working", "not_known"]
    counts: OverallCountsOut


class ServicesOut(BaseModel):
    """`GET /admin/system-health/services`: the ten ASLMS service checks and the overall line. Never calls NAPIX."""

    checked_at: datetime
    overall: OverallOut
    services: list[ServiceCheckOut]
