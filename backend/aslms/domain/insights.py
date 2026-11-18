"""State Insights (design `state-insights`, row 258, migration 0039): the groupings Insights counts by, the derived
per-case readings and the printed department names mapped to offices (docs/schema/schema.md, "State Insights").

- `insight_groups` (master): subject groups (`subject`) and kinds of case (`family`); reserved rows cannot be
  deactivated or recoded (trigger `insight_groups_fixed`); written only by `services/insights_groups.py`.
- `insight_subject_categories` (master): the court's subject categories and their subject group (NULL = Not Grouped).
- `insight_case_type_groups` (master): the kind of case of each case type (a type without a row is `other`).
- `insight_case_facts` (derived): one row per case, the readings by rule (`services/insights_facts.py`), updated in
  place and never deleted. The two department-id arrays carry no FK (decision 13, the deviation in DB_STANDARD §2).
- `office_title_names` (master): a printed department phrase mapped to an office, managed with `admin.keywords`."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from aslms.db.base import (
    Base,
    CreatedByMixin,
    DeactivateMixin,
    TableClass,
    TimestampMixin,
    uuid_fk,
    uuid_pk,
)

# decision 14: the two groupings of one master
GROUP_KINDS = ("subject", "family")


# decision 6: the stored bases (`claimed` is evaluated live, never stored)
STATE_BASES = ("party", "officer", "counsel", "title", "writ")


class InsightGroup(TimestampMixin, DeactivateMixin, CreatedByMixin, Base):
    """A subject group or a kind of case (decision 14). Never deleted; `kind`, `code` and `is_reserved` never
    change (trigger `insight_groups_fixed`)."""

    __tablename__ = "insight_groups"
    __table_class__ = TableClass.MASTER
    __table_args__ = (
        CheckConstraint("kind IN ('subject', 'family')", name="kind"),
        CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,39}$'", name="code"),
        CheckConstraint("is_active = (deactivated_at IS NULL)", name="active"),
        CheckConstraint("NOT is_reserved OR is_active", name="reserved"),
        UniqueConstraint("kind", "code", name="uq_insight_groups_kind_code"),
        UniqueConstraint("id", "kind", name="uq_insight_groups_id_kind"),
        Index("uq_insight_groups_kind_label", "kind", text("lower(label::text)"), unique=True),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_reserved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class InsightSubjectCategory(TimestampMixin, CreatedByMixin, Base):
    """A court's subject category (the five-digit code it prints) and its subject group; NULL = Not Grouped."""

    __tablename__ = "insight_subject_categories"
    __table_class__ = TableClass.MASTER
    __table_args__ = (
        CheckConstraint("category_code BETWEEN 1 AND 99999", name="code"),
        CheckConstraint("group_kind = 'subject'", name="kind"),
        UniqueConstraint("court_id", "category_code"),
        ForeignKeyConstraint(
            ["group_id", "group_kind"],
            ["insight_groups.id", "insight_groups.kind"],
            ondelete="RESTRICT",
            name="fk_insight_subject_categories_group_id_insight_groups",
        ),
        Index("ix_insight_subject_categories_group_id", "group_id"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    court_id: Mapped[uuid.UUID] = uuid_fk("courts.id", index=False)
    category_code: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    group_kind: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'subject'"))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class InsightCaseTypeGroup(TimestampMixin, CreatedByMixin, Base):
    """The kind of case of one case type (a case type without a row is of kind `other`)."""

    __tablename__ = "insight_case_type_groups"
    __table_class__ = TableClass.MASTER
    __table_args__ = (
        CheckConstraint("group_kind = 'family'", name="kind"),
        ForeignKeyConstraint(
            ["group_id", "group_kind"],
            ["insight_groups.id", "insight_groups.kind"],
            ondelete="RESTRICT",
            name="fk_insight_case_type_groups_group_id_insight_groups",
        ),
        Index("ix_insight_case_type_groups_group_id", "group_id"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    case_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("case_types.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_kind: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'family'"))


class InsightCaseFact(TimestampMixin, Base):
    """The readings by rule of one case (decisions 6 to 13). Status, dates, the next hearing, ownership,
    recommendations, custody and closures are never stored here: Insights reads them live."""

    __tablename__ = "insight_case_facts"
    __table_class__ = TableClass.DERIVED
    __table_args__ = (
        CheckConstraint(
            "state_basis <@ ARRAY['party','officer','counsel','title','writ']::varchar[]", name="basis"
        ),
        CheckConstraint("original_writ_case_id IS NULL OR original_writ_text IS NOT NULL", name="writ"),
        CheckConstraint("orders_count >= 0", name="orders"),
        Index("ix_insight_case_facts_built_at", "built_at"),
        Index(
            "ix_insight_case_facts_main_case_id",
            "main_case_id",
            postgresql_where=text("main_case_id IS NOT NULL"),
        ),
        Index(
            "ix_insight_case_facts_original_writ",
            "original_writ_case_id",
            postgresql_where=text("original_writ_case_id IS NOT NULL"),
        ),
        Index(
            "ix_insight_case_facts_title_order_id",
            "title_order_id",
            postgresql_where=text("title_order_id IS NOT NULL"),
        ),
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="RESTRICT"), primary_key=True
    )
    category_code: Mapped[int | None] = mapped_column(Integer)
    subject_category_code: Mapped[int | None] = mapped_column(Integer)
    main_case_id: Mapped[uuid.UUID | None] = uuid_fk("cases.id", nullable=True, index=False)
    state_basis: Mapped[list[str]] = mapped_column(
        ARRAY(String(10)), nullable=False, server_default=text("'{}'")
    )
    title_phrases: Mapped[list[str]] = mapped_column(
        ARRAY(String(200)), nullable=False, server_default=text("'{}'")
    )
    # decision 13: Department-tier office ids, no FK (PostgreSQL has none on array elements)
    named_title_department_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'")
    )
    named_counsel_department_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'")
    )
    posts: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False, server_default=text("'{}'"))
    counsel_codes: Mapped[list[str]] = mapped_column(
        ARRAY(String(120)), nullable=False, server_default=text("'{}'")
    )
    government_codes: Mapped[list[str]] = mapped_column(
        ARRAY(String(120)), nullable=False, server_default=text("'{}'")
    )
    original_writ_text: Mapped[str | None] = mapped_column(String(60))
    original_writ_case_id: Mapped[uuid.UUID | None] = uuid_fk("cases.id", nullable=True, index=False)
    latest_order_on: Mapped[date | None] = mapped_column(Date)
    orders_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    title_order_id: Mapped[uuid.UUID | None] = uuid_fk("orders.id", nullable=True, index=False)
    reader_version: Mapped[str] = mapped_column(String(20), nullable=False)
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OfficeTitleName(TimestampMixin, DeactivateMixin, CreatedByMixin, Base):
    """A printed department phrase (decision 8's normal form) mapped to an office (decision 9). Managed with
    `admin.keywords` in the office subtree; every change audited (`title_name.*`). Never deleted."""

    __tablename__ = "office_title_names"
    __table_class__ = TableClass.MASTER
    __table_args__ = (
        CheckConstraint("phrase ~ '^[A-Z0-9][A-Z0-9 ()&.,/-]{2,199}$'", name="phrase"),
        CheckConstraint("is_active = (deactivated_at IS NULL)", name="active"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    office_id: Mapped[uuid.UUID] = uuid_fk("offices.id")
    phrase: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
