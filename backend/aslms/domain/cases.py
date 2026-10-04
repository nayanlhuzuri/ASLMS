"""Group 3 — cases and the dossier blocks. Every field of the Search by CNR and Current Status responses has a
column here (docs/schema/napix_coverage.md §C); the whole response is also kept in `case_snapshots`."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import (
    Base,
    CreatedAtMixin,
    CreatedByMixin,
    RefNoMixin,
    TableClass,
    TimestampMixin,
    pg_enum,
    uuid_fk,
    uuid_pk,
)


class CaseStatus(enum.StrEnum):
    PENDING = "pending"
    DISPOSED = "disposed"
    UNKNOWN = "unknown"


class FirstSeenSource(enum.StrEnum):
    CAUSELIST = "causelist"
    SEARCH = "search"
    DISCOVERY = "discovery"
    LINK = "link"


class Case(TimestampMixin, RefNoMixin, CreatedByMixin, Base):
    __tablename__ = "cases"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (
        # word search (design cases-api, decision 6): the vector is derived by aslms_case_search_vector(id)
        Index("ix_cases_search_vector_gin", "search_vector", postgresql_using="gin"),
        # number search: the printed case number upper-cased without white space
        Index("ix_cases_case_no_compact", text(r"upper(regexp_replace(case_no_text, '\s', '', 'g'))")),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    cnr: Mapped[str | None] = mapped_column(String(16), unique=True)  # null only when provisional
    court_id: Mapped[uuid.UUID] = uuid_fk("courts.id")
    court_est_name: Mapped[str | None] = mapped_column(String(200))
    # identity as the court prints it
    case_type_id: Mapped[uuid.UUID | None] = uuid_fk("case_types.id", nullable=True)
    case_type_text: Mapped[str | None] = mapped_column(String(60))  # type_name_reg / status type_name
    reg_no: Mapped[int | None] = mapped_column(Integer)
    reg_year: Mapped[int | None] = mapped_column(SmallInteger)
    case_no_text: Mapped[str | None] = mapped_column(String(80), index=True)  # "WP(C)/4189/2016"
    filing_case_type_id: Mapped[uuid.UUID | None] = uuid_fk("case_types.id", nullable=True)
    filing_case_type_text: Mapped[str | None] = mapped_column(String(60))  # type_name_fil
    filing_no: Mapped[int | None] = mapped_column(Integer)
    filing_year: Mapped[int | None] = mapped_column(SmallInteger)
    filing_no_text: Mapped[str | None] = mapped_column(String(80))
    filing_date: Mapped[date | None] = mapped_column(Date)  # date_of_filing
    registration_date: Mapped[date | None] = mapped_column(Date)  # dt_regis
    date_first_list: Mapped[date | None] = mapped_column(Date)
    # status
    status: Mapped[CaseStatus] = mapped_column(
        pg_enum(CaseStatus, "case_status"), nullable=False, server_default="unknown", index=True
    )
    disposal_date: Mapped[date | None] = mapped_column(Date)  # date_of_decision
    disposal_nature: Mapped[str | None] = mapped_column(String(200))  # disp_nature
    disposal_type: Mapped[str | None] = mapped_column(String(200))
    short_order: Mapped[str | None] = mapped_column(Text)
    date_filing_disp: Mapped[date | None] = mapped_column(Date)
    reason_for_rej: Mapped[str | None] = mapped_column(Text)
    date_judgement_pronounced: Mapped[date | None] = mapped_column(Date)
    date_judgement_reserved: Mapped[date | None] = mapped_column(Date)
    goshwara_no: Mapped[str | None] = mapped_column(String(10))
    next_hearing_date: Mapped[date | None] = mapped_column(Date, index=True)  # date_next_list
    next_purpose: Mapped[str | None] = mapped_column(String(200))  # purpose_name
    last_hearing_date: Mapped[date | None] = mapped_column(Date)  # date_last_list
    # bench and classification
    bench_id: Mapped[uuid.UUID | None] = uuid_fk("benches.id", nullable=True)
    napix_bench_id: Mapped[int | None] = mapped_column(Integer)
    bench_name: Mapped[str | None] = mapped_column(String(100))
    bench_type_code: Mapped[int | None] = mapped_column(Integer)
    coram: Mapped[str | None] = mapped_column(Text)
    coram_designation: Mapped[str | None] = mapped_column(String(100))  # desgname
    judicial_branch: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(Text)
    category_code: Mapped[int | None] = mapped_column(Integer)
    sub_category: Mapped[str | None] = mapped_column(Text)
    # place and police
    state_id: Mapped[uuid.UUID | None] = uuid_fk("states.id", nullable=True)
    district_id: Mapped[uuid.UUID | None] = uuid_fk("districts.id", nullable=True)
    state_name_as_listed: Mapped[str | None] = mapped_column(String(100))
    district_name_as_listed: Mapped[str | None] = mapped_column(String(100))
    filing_state_code: Mapped[int | None] = mapped_column(Integer)  # document_details.case_state_code
    filing_district_code: Mapped[int | None] = mapped_column(Integer)  # document_details.case_dist_code
    fir_no: Mapped[str | None] = mapped_column(String(40))
    fir_year: Mapped[int | None] = mapped_column(SmallInteger)
    police_station: Mapped[str | None] = mapped_column(String(200))
    police_st_code: Mapped[str | None] = mapped_column(String(20))
    uniform_code: Mapped[str | None] = mapped_column(String(20))
    main_matter_text: Mapped[str | None] = mapped_column(String(200))
    # parties as printed (details in case_parties / case_advocates)
    petitioner_summary: Mapped[str | None] = mapped_column(Text)
    respondent_summary: Mapped[str | None] = mapped_column(Text)
    pet_advocate: Mapped[str | None] = mapped_column(Text)
    res_advocate: Mapped[str | None] = mapped_column(Text)
    # portal state
    is_provisional: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_tracked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    first_seen_source: Mapped[FirstSeenSource] = mapped_column(
        pg_enum(FirstSeenSource, "first_seen_source"), nullable=False, server_default="causelist"
    )
    last_full_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dossier_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    merged_into_case_id: Mapped[uuid.UUID | None] = uuid_fk("cases.id", nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)
    raw: Mapped[dict | None] = mapped_column(JSONB)


class PartyRole(enum.StrEnum):
    PETITIONER = "petitioner"
    RESPONDENT = "respondent"


class CaseParty(TimestampMixin, Base):
    """pet_name / res_name = party_no 1; pet_extra_party / res_extra_party.party_no{n} = party_no n."""

    __tablename__ = "case_parties"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("case_id", "role", "party_no"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    role: Mapped[PartyRole] = mapped_column(pg_enum(PartyRole, "party_role"), nullable=False)
    party_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_normalised: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    address: Mapped[str | None] = mapped_column(Text)
    has_legal_heir: Mapped[bool | None] = mapped_column(Boolean)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class AdvocateSide(enum.StrEnum):
    PETITIONER = "petitioner"
    RESPONDENT = "respondent"


class CaseAdvocate(TimestampMixin, Base):
    __tablename__ = "case_advocates"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("case_id", "side", "name_as_listed"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    side: Mapped[AdvocateSide] = mapped_column(pg_enum(AdvocateSide, "advocate_side"), nullable=False)
    name_as_listed: Mapped[str] = mapped_column(String(300), nullable=False)
    advocate_id: Mapped[uuid.UUID | None] = uuid_fk("advocates.id", nullable=True)
    bar_reg_no: Mapped[str | None] = mapped_column(String(40))
    counsel_code: Mapped[str | None] = mapped_column(String(60), index=True)  # "SC, EDU" when printed
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class HearingSource(enum.StrEnum):
    DOSSIER = "dossier"
    SHOW_BUSINESS = "show_business"
    CAUSELIST = "causelist"


class CaseHearing(TimestampMixin, Base):
    """historyofcasehearing[] plus Show Business for the same business_date."""

    __tablename__ = "case_hearings"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("case_id", "business_date", "purpose"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    business_date: Mapped[date | None] = mapped_column(Date)
    hearing_date: Mapped[date | None] = mapped_column(Date)  # the dossier's "next" for that proceeding
    purpose: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    bench_text: Mapped[str | None] = mapped_column(Text)  # judge_name
    judge_designation: Mapped[str | None] = mapped_column(String(100))  # Show Business desgname
    causelist_type: Mapped[str | None] = mapped_column(String(60))
    case_number_text: Mapped[str | None] = mapped_column(String(80))
    business_text: Mapped[str | None] = mapped_column(Text)
    short_order_text: Mapped[str | None] = mapped_column(Text)
    source: Mapped[HearingSource] = mapped_column(
        pg_enum(HearingSource, "hearing_source"), nullable=False, server_default="dossier"
    )


class CaseAct(TimestampMixin, Base):
    __tablename__ = "case_acts"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("case_id", "act_name_as_listed", "section"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    act_name_as_listed: Mapped[str] = mapped_column(String(300), nullable=False)
    act_id: Mapped[uuid.UUID | None] = uuid_fk("acts.id", nullable=True)
    national_act_code: Mapped[str | None] = mapped_column(String(20))
    section: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")


class CaseApplication(TimestampMixin, Base):
    """iafiling[] (HC spec §6.1.6)."""

    __tablename__ = "case_applications"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("case_id", "ia_number"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    ia_number: Mapped[str] = mapped_column(String(80), nullable=False)
    party_name: Mapped[str | None] = mapped_column(Text)  # ia_pet_name
    status: Mapped[str | None] = mapped_column(String(1))  # ia_pend_disp P/D
    filing_date: Mapped[date | None] = mapped_column(Date)  # date_of_filing
    raw: Mapped[dict | None] = mapped_column(JSONB)


class LowerCourtLevel(enum.StrEnum):
    APPELLATE = "appellate"  # lower_court_*
    TRIAL = "trial"  # trial_lower_court_*


class CaseLowerCourt(TimestampMixin, Base):
    __tablename__ = "case_lower_courts"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("case_id", "level"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    level: Mapped[LowerCourtLevel] = mapped_column(
        pg_enum(LowerCourtLevel, "lower_court_level"), nullable=False
    )
    court_name: Mapped[str | None] = mapped_column(String(300))
    case_no_text: Mapped[str | None] = mapped_column(String(200))
    decision_date: Mapped[date | None] = mapped_column(Date)
    raw: Mapped[dict | None] = mapped_column(JSONB)


class CaseObjection(TimestampMixin, Base):
    """objections{}: objection1, objection2, … with one scrutiny_date / compliance / receipt per block."""

    __tablename__ = "case_objections"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("case_id", "scrutiny_date", "seq"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    seq: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))
    objection: Mapped[str | None] = mapped_column(Text)
    scrutiny_date: Mapped[date] = mapped_column(Date, nullable=False)
    compliance_by_date: Mapped[date | None] = mapped_column(Date)
    receipt_date: Mapped[date | None] = mapped_column(Date)
    raw: Mapped[dict | None] = mapped_column(JSONB)


class CaseTransfer(TimestampMixin, Base):
    """transfer[]: the court's own transfer of a case between courts (not the portal's ownership transfer)."""

    __tablename__ = "case_transfers"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("case_id", "transfer_date", "to_court_text"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    transfer_date: Mapped[date | None] = mapped_column(Date)
    from_court_text: Mapped[str | None] = mapped_column(String(300))
    to_court_text: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")
    raw: Mapped[dict | None] = mapped_column(JSONB)


class CaseWritInfo(TimestampMixin, Base):
    """writinfo[]: appellate cases filed against this case."""

    __tablename__ = "case_writ_info"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("case_id", "appellate_case_number"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    appellate_case_number: Mapped[str] = mapped_column(String(200), nullable=False)
    appellate_authority: Mapped[str | None] = mapped_column(String(200))
    raw: Mapped[dict | None] = mapped_column(JSONB)


class LinkKind(enum.StrEnum):
    MAIN_MATTER = "main_matter"
    CONNECTED = "connected"
    LINKED = "linked"  # link_cases[]
    IA_IN = "ia_in"
    APPEAL_OF = "appeal_of"
    CONTEMPT_OF = "contempt_of"
    WITH = "with"


class LinkSource(enum.StrEnum):
    DOSSIER = "dossier"
    CAUSELIST = "causelist"
    MANUAL = "manual"


class CaseLink(TimestampMixin, Base):
    __tablename__ = "case_links"
    __table_class__ = TableClass.TRANSACTION
    __table_args__ = (UniqueConstraint("from_case_id", "to_case_no_text", "kind"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    from_case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    to_case_id: Mapped[uuid.UUID | None] = uuid_fk("cases.id", nullable=True)
    to_case_no_text: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    to_cnr: Mapped[str | None] = mapped_column(String(16), index=True)
    filing_number_text: Mapped[str | None] = mapped_column(String(200))
    kind: Mapped[LinkKind] = mapped_column(pg_enum(LinkKind, "link_kind"), nullable=False)
    source: Mapped[LinkSource] = mapped_column(
        pg_enum(LinkSource, "link_source"), nullable=False, server_default="dossier"
    )


class SnapshotSource(enum.StrEnum):
    CNR = "cnr"
    CURRENT_STATUS = "current_status"


class CaseSnapshot(CreatedAtMixin, Base):
    """The whole dossier / status block, verbatim, deduplicated by sha256."""

    __tablename__ = "case_snapshots"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (UniqueConstraint("case_id", "payload_sha256"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = uuid_fk("cases.id")
    source: Mapped[SnapshotSource] = mapped_column(pg_enum(SnapshotSource, "snapshot_source"), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
