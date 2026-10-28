"""Next dates from orders (design `next-date-extraction`): the reader, the review queue, confirm / reject and manual
next dates (`NXT`).

- The reader (decisions 4-6, 8, 14, 16): `read_pending` takes pending orders whose document text is extracted (or
  known to be absent), oldest first; per order (one savepoint) it takes the case row lock, re-reads the order
  `FOR UPDATE`, reads the stored text by rule (`next_date_rules`), records the reading on the order and, only for the
  case's current order with a date today or later, writes a `next_dates` row (`order_specific` / `order_period`)
  and supersedes the case's other pending rows; a current order without a usable date supersedes the open rows of
  older orders instead (Deviation 11).
- Shown directly (design `next-date-direct`, decisions 1 to 3, superseding the owner's option B of 17 Oct 2026):
  every dated reading of the current order is `not_needed` with `needs_review = false`; it is the court-given date
  from orders, exact for `list_on_date`, around for periods, qualified and returnable dates. No code path writes
  `pending` any more; `match_court_dates` still closes old pending rows a court date matches, and `direct_apply`
  (`aslms next-dates direct`) retires them once. Each reading refreshes the case's one next hearing
  (`next_hearing.refresh`).
  It emits `next_date_extracted` for every row and for every *enter* item. Pending rows whose date passed expire.
  The reading is system work: no audit row (recorded in `job_runs` and the events); failures go to
  `source_failures` (kind `next_date_read`). Court text only: nothing is sent to SourceTrace, NAPIX or any AI.
- The queue (next-date-direct, decisions 2 and 9): *enter* items only - the current order of a claimed, not disposed
  case with no next hearing from the court, read `unclear`, `none` or `no_text` or with its reading marked wrong,
  dated within `NEXT_DATE_UNCLEAR_DAYS`, with no manual date answering it; only where a membership holding
  `next_dates.review` has a working basis. *confirm* items no longer exist (the kind is accepted and empty).
- Writes (decisions 10-12, 15; next-date-direct decision 6): `confirm`, `reject` (with an optional replacement date)
  and `enter` take the case row lock, need the function, a visible case, a claim and a working basis in the same
  membership, and answer 409 `court_date_fixed` while the case has a court-given next date; they close the order's
  review alert, emit `next_date_reviewed` / `next_date_entered`, audit `next_date.*` (the note's length and hash,
  never its text) and refresh the case's next hearing.
- Misread readings (next-date-direct, decisions 17 and 18): `report_wrong` (an alert to the holders of
  `next_dates.correct`), `correct` (the reading `rejected`, an optional `manual` date) and `keep`.
- Reads (decisions 9, 18): `effective_for_case` (the latest open order reading, else the latest open manual row: the
  "Next Date From Orders" card), `case_next_dates`, `next_date_out`."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Date,
    String,
    and_,
    case,
    cast,
    exists,
    false,
    func,
    literal,
    null,
    or_,
    select,
    true,
    union_all,
    update,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, aliased

from aslms.core import clock
from aslms.core.config import Settings, get_settings
from aslms.domain.alerts import Alert, AlertStatus, NextDate, NextDateSource, ReviewStatus
from aslms.domain.cases import Case, CaseStatus, NextHearingBasis
from aslms.domain.causelists import CURRENT_LIST, Causelist, CauselistEntry
from aslms.domain.documents import Document, DocumentText, Order, OrderNextDateStatus, TextStatus
from aslms.domain.ops import JobRun, JobStatus
from aslms.domain.org import Office, User
from aslms.domain.ownership import CaseOwnership, OwnershipRole, OwnershipStatus
from aslms.domain.reference import AlertKind, EventType, Permission, RecordType
from aslms.services import access, calendar, case_filters, next_hearing, visibility
from aslms.services import next_date_rules as rules
from aslms.services.access import Member
from aslms.services.alert_rules import IST
from aslms.services.audit import Actor, write_audit
from aslms.services.case_filters import CaseFilters
from aslms.services.cases import emit_event, ref_no_from_url
from aslms.services.matching import record_failure
from aslms.services.refno import allocate_ref_no
from aslms.services.workflow_common import (
    acting_member,
    bad,
    clean_text,
    conflict,
    digest,
    lock_case,
    require_function,
    require_owned,
    require_visible_basis,
    value,
)

log = logging.getLogger(__name__)

JOB = "next_dates_read"
FAILURE_KIND = "next_date_read"
MATCH_FAILURE_KIND = "next_date_match"
NOTE_MAX = 300
ORDER_SOURCES = (NextDateSource.ORDER_SPECIFIC, NextDateSource.ORDER_PERIOD)
EFFECTIVE_SOURCES = (NextDateSource.MANUAL, *ORDER_SOURCES)
OPEN_REVIEW = (ReviewStatus.NOT_NEEDED, ReviewStatus.PENDING, ReviewStatus.CONFIRMED)
CLOSED_REVIEW = (ReviewStatus.REJECTED, ReviewStatus.SUPERSEDED, ReviewStatus.EXPIRED)
# next-date-direct, decision 2: an order that gives no next date at all ("not mentioned") asks a person too
ENTER_STATUSES = (OrderNextDateStatus.UNCLEAR, OrderNextDateStatus.NONE, OrderNextDateStatus.NO_TEXT)
REVIEW_READINGS = (rules.UNCLEAR, rules.NONE, rules.NO_TEXT)
MARKED_WRONG = "marked_wrong"
REASON_MIN, REASON_MAX = 10, 300
COURT_DATE_FIXED = "The court has given the next date for this case, so it cannot be changed."
NOT_ORDER_READING = "Only a next date read from the latest order can be reported or corrected."
READABLE_TEXT = (TextStatus.EXTRACTED, TextStatus.NONE)
KINDS = ("confirm", "enter")
DEFAULT_LIMIT, MAX_LIMIT = 50, 200
COUNTERS = (
    "claimed",
    "specific",
    "period",
    "unclear",
    "none",
    "no_text",
    "rows_written",
    "review_items",
    "superseded",
    "expired",
    "matched",
    "skipped",
    "failed",
)


@dataclass(frozen=True)
class NextDateConfig:
    """Decision 20's settings, always from `Settings` (`NEXT_DATE_*`, validated at start): no hidden defaults; a
    caller without one uses `from_settings()`."""

    batch: int
    unclear_days: int
    max_ahead_days: int

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> NextDateConfig:
        s = settings or get_settings()
        return cls(
            batch=s.next_date_batch,
            unclear_days=s.next_date_unclear_days,
            max_ahead_days=s.next_date_max_ahead_days,
        )


class NextDateNotFound(LookupError):
    """No next date for the given id or reference (HTTP 404)."""


@dataclass
class Page:
    items: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0


def _now() -> datetime:
    return datetime.now(UTC)


def today_ist(now: datetime | None = None) -> date:
    return clock.today_ist(now)


def clamp(limit: int | None, offset: int | None) -> tuple[int, int]:
    return max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT)), max(0, int(offset or 0))


# ------------------------------------------------------------------------------------------------ conditions


def claimed_condition() -> ColumnElement[bool]:
    """Decision 7: the case has an active primary owner."""
    return exists().where(
        CaseOwnership.case_id == Case.id,
        CaseOwnership.status == OwnershipStatus.ACTIVE,
        CaseOwnership.role == OwnershipRole.PRIMARY,
    )


def review_condition(session: Session, who: User | Member | Office) -> ColumnElement[bool]:
    """Over `cases`: for a department, its claimed cases (the dashboard count); for a caller, the cases on which a
    membership holding `next_dates.review` has a working basis (decision 10)."""
    if isinstance(who, Office):
        return exists().where(
            CaseOwnership.case_id == Case.id,
            CaseOwnership.office_id == who.id,
            CaseOwnership.status == OwnershipStatus.ACTIVE,
            CaseOwnership.role == OwnershipRole.PRIMARY,
        )
    return visibility.working_condition_for(session, who, Permission.NEXT_DATES_REVIEW)


def answered_condition(order=Order) -> ColumnElement[bool]:
    """Over `orders`: a manual next date answers the order — one linked to it (`order_id`, which survives a
    `--reread`), or any manual date of the case entered since the order was read (decision 7)."""
    return exists().where(
        NextDate.case_id == order.case_id,
        NextDate.source == NextDateSource.MANUAL,
        or_(NextDate.order_id == order.id, NextDate.created_at >= order.next_date_read_at),
    )


def current_order_condition(order=Order) -> ColumnElement[bool]:
    """No order of the case has a later `order_date` (decision 5)."""
    later = aliased(Order)
    return ~exists().where(later.case_id == order.case_id, later.order_date > order.order_date)


def marked_wrong_condition(order=Order) -> ColumnElement[bool]:
    """Over `orders` (next-date-direct, decision 18): a reading of the order was rejected (marked wrong) and no
    reading of it is open any more."""
    rejected = aliased(NextDate)
    open_ = aliased(NextDate)
    return and_(
        exists().where(
            rejected.order_id == order.id,
            rejected.source.in_(ORDER_SOURCES),
            rejected.review_status == ReviewStatus.REJECTED,
        ),
        ~exists().where(
            open_.order_id == order.id,
            open_.source.in_(ORDER_SOURCES),
            open_.review_status.in_(OPEN_REVIEW),
        ),
    )


def no_court_date_condition() -> ColumnElement[bool]:
    """Over `cases` (next-date-direct, decision 2): the case's one next hearing is empty or entered by hand."""
    return or_(Case.next_hearing_basis.is_(None), Case.next_hearing_basis == NextHearingBasis.MANUAL)


def queue_subquery(
    session: Session,
    case_condition: ColumnElement[bool],
    *,
    today: date,
    cfg: NextDateConfig,
    kind: str | None = None,
    filters: CaseFilters | None = None,
):
    """Decision 7 as changed by next-date-direct (decisions 2 and 9): *enter* orders as (kind, id, case_id,
    order_id, act_by, next_date, reason) over live claimed cases matching `case_condition` and the shared case
    filters. The *confirm* part is kept for the shape and returns no row."""
    if kind is not None and kind not in KINDS:
        raise bad("kind must be confirm or enter")
    base = [
        Case.merged_into_case_id.is_(None),
        claimed_condition(),
        case_condition,
        *case_filters.conditions(session, filters),
    ]
    parts = []
    if kind in (None, "confirm"):
        parts.append(
            select(
                literal("confirm").label("kind"),
                NextDate.id.label("id"),
                NextDate.case_id.label("case_id"),
                NextDate.order_id.label("order_id"),
                NextDate.next_date.label("act_by"),
                NextDate.next_date.label("next_date"),
                cast(null(), String).label("reason"),
            )
            .join(Case, Case.id == NextDate.case_id)
            # next-date-direct, decision 9: a court-given reading is never confirmed, so no confirm item
            .where(
                false(), NextDate.review_status == ReviewStatus.PENDING, NextDate.next_date >= today, *base
            )
        )
    if kind in (None, "enter"):
        manual_since = answered_condition()
        wrong = marked_wrong_condition()
        parts.append(
            select(
                literal("enter").label("kind"),
                Order.id.label("id"),
                Order.case_id.label("case_id"),
                Order.id.label("order_id"),
                (Order.order_date + literal(cfg.unclear_days)).label("act_by"),
                cast(null(), Date).label("next_date"),
                case(
                    (Order.next_date_status.in_(ENTER_STATUSES), cast(Order.next_date_status, String)),
                    else_=literal(MARKED_WRONG),
                ).label("reason"),
            )
            .join(Case, Case.id == Order.case_id)
            .where(
                or_(Order.next_date_status.in_(ENTER_STATUSES), wrong),
                Order.order_date >= today - timedelta(days=cfg.unclear_days),
                current_order_condition(),
                ~manual_since,
                Case.status != CaseStatus.DISPOSED,
                no_court_date_condition(),
                *base,
            )
        )
    return (parts[0] if len(parts) == 1 else union_all(*parts)).subquery("queue")


def queue_count(
    session: Session,
    who: User | Member | Office,
    *,
    today: date | None = None,
    cfg: NextDateConfig | None = None,
    case_id: uuid.UUID | None = None,
) -> int:
    q = queue_subquery(
        session,
        review_condition(session, who),
        today=today or today_ist(),
        cfg=cfg or NextDateConfig.from_settings(),
    )
    stmt = select(func.count()).select_from(q)
    if case_id is not None:
        stmt = stmt.where(q.c.case_id == case_id)
    return int(session.scalar(stmt) or 0)


def order_has_item(session: Session, order_id: uuid.UUID, *, today: date, cfg: NextDateConfig) -> bool:
    """The order still has a queue item (a pending row read from it, or it is an *enter* item)."""
    q = queue_subquery(session, true(), today=today, cfg=cfg)
    return bool(session.scalar(select(exists().where(q.c.order_id == order_id))))


# ------------------------------------------------------------------------------------------------ the court's date


def court_date_condition(case_id: Any, day: Any) -> ColumnElement[bool]:
    """`day` is the court's own date for the case (owner's second decision of 17 Oct 2026, point 1): the case's
    `next_hearing_date` (NAPIX `date_next_list`, from the dossier or Current Status), or a cause-list entry of the
    case on a list of that date."""
    return or_(
        exists().where(Case.id == case_id, Case.next_hearing_date == day),
        exists().where(
            CauselistEntry.case_id == case_id,
            Causelist.id == CauselistEntry.causelist_id,
            Causelist.list_date == day,
            CURRENT_LIST,
        ),
    )


def court_date_matches(session: Session, case_id: uuid.UUID, day: date) -> bool:
    return bool(session.scalar(select(court_date_condition(literal(case_id), literal(day)))))


def match_court_dates(
    session: Session,
    *,
    case_ids: list[uuid.UUID] | None = None,
    today: date | None = None,
    cfg: NextDateConfig | None = None,
) -> int:
    """Point 2: pending order rows (of `case_ids`, or of every case) dated today or later whose date the court now
    gives too -> `not_needed` (a system closure: `needs_review` stays true and records that the text alone was not
    enough; no reviewer, no review time); the review alerts of their orders that have no queue item left are closed
    `done`, reason `matched`. Returns the number of rows matched."""
    today = today or today_ist()
    stmt = update(NextDate).where(
        NextDate.review_status == ReviewStatus.PENDING,
        NextDate.source.in_(ORDER_SOURCES),
        NextDate.next_date >= today,
        court_date_condition(NextDate.case_id, NextDate.next_date),
    )
    if case_ids is not None:
        ids = list(dict.fromkeys(i for i in case_ids if i is not None))
        if not ids:
            return 0
        stmt = stmt.where(NextDate.case_id.in_(ids))
    matched = session.execute(
        stmt.values(review_status=ReviewStatus.NOT_NEEDED, updated_by=None)
        .returning(NextDate.id, NextDate.case_id)
        .execution_options(synchronize_session=False)
    ).all()
    if not matched:
        return 0
    for row_id, _ in matched:  # the session may hold these rows: let them be read again
        cached = session.identity_map.get(session.identity_key(NextDate, row_id))
        if cached is not None:
            session.expire(cached)
    cfg = cfg or NextDateConfig.from_settings()
    for case_id in dict.fromkeys(case_id for _, case_id in matched):
        close_moot_review_alerts(session, case_id, "matched", today=today, cfg=cfg)
    session.flush()
    return len(matched)


def matched_by_court(session: Session, next_date_id: Any) -> bool:
    """The row was a suggestion that the court's own date made firm (`not_needed` without a person's review)."""
    row_id = _uuid(next_date_id)
    row = session.get(NextDate, row_id) if row_id else None
    return bool(
        row is not None
        and NextDateSource(row.source) in ORDER_SOURCES
        and ReviewStatus(row.review_status) == ReviewStatus.NOT_NEEDED
        and row.needs_review
        and row.reviewed_at is None
    )


def match_after_court_change(session: Session, case_ids) -> int:
    """The court's date for these cases may have changed (a dossier, a Current Status block, a cause list): their
    pending suggestions that it now matches become firm. Inside a savepoint; a failure is recorded in
    `source_failures` (kind `next_date_match`) and never fails the court data (the reader run matches every case
    again within five minutes)."""
    ids = list(dict.fromkeys(i for i in case_ids if i is not None))
    if not ids:
        return 0
    try:
        with session.begin_nested():
            return match_court_dates(session, case_ids=ids)
    except Exception as exc:  # noqa: BLE001 - matching never fails the court data
        log.exception("next-date match failed for %d case(s)", len(ids))
        try:
            with session.begin_nested():
                record_failure(session, MATCH_FAILURE_KIND, str(ids[0]), f"{exc.__class__.__name__}: {exc}")
        except Exception:  # noqa: BLE001
            log.exception("next-date match failure not recorded")
        return 0


# ------------------------------------------------------------------------------------------------ the reader


def is_current(session: Session, order: Order) -> bool:
    return not session.scalar(
        select(exists().where(Order.case_id == order.case_id, Order.order_date > order.order_date))
    )


def _reading_of(session: Session, order: Order, cfg: NextDateConfig) -> rules.Reading:
    doc = session.get(Document, order.document_id) if order.document_id else None
    if doc is None or TextStatus(doc.text_status) == TextStatus.NONE:
        return rules.Reading(rules.NO_TEXT, needs_review=True)
    dt = session.get(DocumentText, doc.id)
    return rules.read_order_text(
        dt.full_text if dt else None, order.order_date, max_ahead_days=cfg.max_ahead_days
    )


def supersede(
    session: Session, case_id: uuid.UUID, *, keep: uuid.UUID | None = None, by: uuid.UUID | None = None
) -> int:
    """Decision 8: the case's other pending rows → `superseded` (a system closure: no reviewer, no time)."""
    stmt = update(NextDate).where(NextDate.case_id == case_id, NextDate.review_status == ReviewStatus.PENDING)
    if keep is not None:
        stmt = stmt.where(NextDate.id != keep)
    result = session.execute(
        stmt.values(review_status=ReviewStatus.SUPERSEDED, updated_by=by).execution_options(
            synchronize_session="fetch"
        )
    )
    return int(result.rowcount or 0)


def _extracted_event(
    session: Session, case: Case, order: Order, reading: rules.Reading, row: NextDate | None, review: bool
) -> None:
    emit_event(
        session,
        EventType.NEXT_DATE_EXTRACTED,
        case,
        {
            "order_id": str(order.id),
            "order_no": order.order_no,
            "order_date": order.order_date,
            "status": reading.status,
            "rule": reading.rule,
            "next_date": reading.date,
            "next_date_id": str(row.id) if row is not None else None,
            "review": review,
        },
        dedupe=f"next_date_extracted:{order.id}:{rules.RULES_VERSION}",
    )


def read_order(
    session: Session,
    order: Order,
    *,
    today: date,
    cfg: NextDateConfig | None = None,
    counters: dict[str, int] | None = None,
) -> str:
    """Decisions 4-6, 8 and 14 for one order (the caller holds the case and order locks). Returns the status."""
    cfg = cfg or NextDateConfig.from_settings()
    counters = counters if counters is not None else {}
    reading = _reading_of(session, order, cfg)
    order.next_date_status = OrderNextDateStatus(reading.status)
    order.next_date_found = reading.date
    order.next_date_rule = reading.rule
    order.next_date_phrase = reading.phrase[: rules.PHRASE_MAX] if reading.phrase else None
    order.next_date_rules_version = rules.RULES_VERSION
    # the database clock, the clock of a manual row's `created_at` that the *enter* rule compares it with
    order.next_date_read_at = func.now()
    session.flush()
    counters[reading.status] = counters.get(reading.status, 0) + 1
    if not is_current(session, order):
        return reading.status
    case = session.get(Case, order.case_id)
    if (
        reading.status in (rules.SPECIFIC, rules.PERIOD)
        and reading.date is not None
        and reading.date >= today
    ):
        source = (
            NextDateSource.ORDER_SPECIFIC if reading.status == rules.SPECIFIC else NextDateSource.ORDER_PERIOD
        )
        # next-date-direct, decision 3: the reading of the current order is shown directly, no court match needed
        new_id = session.execute(
            pg_insert(NextDate.__table__)
            .values(
                case_id=case.id,
                next_date=reading.date,
                source=source.value,
                order_id=order.id,
                confidence=reading.confidence,
                needs_review=False,
                review_status=ReviewStatus.NOT_NEEDED.value,
            )
            .on_conflict_do_nothing()
            .returning(NextDate.__table__.c.id)
        ).scalar()
        if new_id is not None:
            counters["rows_written"] = counters.get("rows_written", 0) + 1
            row = session.get(NextDate, new_id)
        else:
            row = session.scalar(
                select(NextDate).where(
                    NextDate.case_id == case.id,
                    NextDate.next_date == reading.date,
                    NextDate.source == source,
                    NextDate.order_id == order.id,
                )
            )
            if ReviewStatus(row.review_status) == ReviewStatus.PENDING:  # read again after a reread
                row.review_status = ReviewStatus.NOT_NEEDED
                row.needs_review = False
                counters["matched"] = counters.get("matched", 0) + 1
        counters["superseded"] = counters.get("superseded", 0) + supersede(session, case.id, keep=row.id)
        # the newer order's date replaces the dates of older orders (Deviation 11, kept for dated readings too)
        counters["superseded"] = counters.get("superseded", 0) + supersede_older(session, order)
        next_hearing.refresh(session, [case.id], today=today)
        _extracted_event(session, case, order, reading, row, False)
    else:
        # the latest order gives no date to use: the dates of older orders stop (Deviation 11)
        counters["superseded"] = counters.get("superseded", 0) + supersede_older(session, order)
        next_hearing.refresh(session, [case.id], today=today)
        if reading.status in REVIEW_READINGS and is_enter_item(session, case, order, today=today, cfg=cfg):
            counters["review_items"] = counters.get("review_items", 0) + 1
            _extracted_event(session, case, order, reading, None, True)
    session.flush()
    return reading.status


def is_enter_item(session: Session, case: Case, order: Order, *, today: date, cfg: NextDateConfig) -> bool:
    """Decision 2's conditions for one order read without a usable date: recent, not answered by a manual date, the
    case not disposed and with no next hearing from the court. An unclear or scanned order is an item claimed or not
    (as before; the event scan checks the owner); an order that gives no date at all only on a claimed case, so the
    pool's many final and procedural orders raise no event."""
    if order.order_date < today - timedelta(days=cfg.unclear_days) or _answered(session, order):
        return False
    if CaseStatus(case.status) == CaseStatus.DISPOSED:
        return False
    if OrderNextDateStatus(order.next_date_status) == OrderNextDateStatus.NONE and not session.scalar(
        select(claimed_condition()).where(Case.id == case.id)
    ):
        return False
    return not next_hearing.court_given(session, case, today=today)


def _answered(session: Session, order: Order) -> bool:
    """A manual next date already answers this order (e.g. entered before a `--reread`): no new *enter* item."""
    return bool(
        session.scalar(
            select(
                exists().where(
                    NextDate.case_id == order.case_id,
                    NextDate.source == NextDateSource.MANUAL,
                    NextDate.order_id == order.id,
                )
            )
        )
    )


def supersede_older(session: Session, order: Order) -> int:
    """Deviation 11: the case's current order was read without a usable date (`none`, `unclear`, `no_text`, or a
    date already past), so every open (`not_needed`, `pending`, `confirmed`) order or manual row that answers an
    older order, and every manual row without an order entered before this order's date, → `superseded` (a system
    closure; a confirmed row keeps its reviewer and review time). Rows of orders of the same date and manual
    answers to this order stay."""
    older = select(Order.id).where(Order.case_id == order.case_id, Order.order_date < order.order_date)
    start = datetime.combine(order.order_date, time.min, tzinfo=IST)
    rows = list(
        session.scalars(
            select(NextDate)
            .where(
                NextDate.case_id == order.case_id,
                NextDate.source.in_(EFFECTIVE_SOURCES),
                NextDate.review_status.in_(OPEN_REVIEW),
                or_(
                    NextDate.order_id.in_(older),
                    and_(
                        NextDate.source == NextDateSource.MANUAL,
                        NextDate.order_id.is_(None),
                        NextDate.created_at < start,
                    ),
                ),
            )
            .order_by(NextDate.created_at, NextDate.id)
            .with_for_update()
        ).all()
    )
    for row in rows:
        before = _snapshot(row)
        row.review_status = ReviewStatus.SUPERSEDED
        session.flush()
        # next-date-direct, decision 7: a person's record (a manual or confirmed date) closed by the system is audited
        if NextDateSource(row.source) == NextDateSource.MANUAL or row.reviewed_at is not None:
            write_audit(
                session,
                Actor.system(next_hearing.SYSTEM_ACTOR),
                "next_date.superseded_by_court",
                "next_date",
                row.id,
                case_id=row.case_id,
                before=before,
                after={
                    **_snapshot(row),
                    "replaced_by": {
                        "basis": "newer_order",
                        "order": {
                            "order_id": order.id,
                            "order_no": order.order_no,
                            "order_date": order.order_date,
                        },
                    },
                },
            )
    return len(rows)


def expire_stale(session: Session, today: date) -> int:
    """Decision 8: pending rows whose date passed → `expired`."""
    result = session.execute(
        update(NextDate)
        .where(NextDate.review_status == ReviewStatus.PENDING, NextDate.next_date < today)
        .values(review_status=ReviewStatus.EXPIRED)
        .execution_options(synchronize_session="fetch")
    )
    return int(result.rowcount or 0)


def candidates(session: Session, *, batch: int, order_id: uuid.UUID | None = None) -> list[uuid.UUID]:
    stmt = (
        select(Order.id)
        .join(Document, Document.id == Order.document_id)
        .where(Order.next_date_status == OrderNextDateStatus.PENDING, Document.text_status.in_(READABLE_TEXT))
    )
    if order_id is not None:
        stmt = stmt.where(Order.id == order_id)
    return list(session.scalars(stmt.order_by(Order.created_at, Order.id).limit(max(1, int(batch)))).all())


def read_pending(
    session: Session,
    *,
    batch: int | None = None,
    now: datetime | None = None,
    order_id: uuid.UUID | None = None,
    cfg: NextDateConfig | None = None,
) -> dict[str, int]:
    """Decision 16: candidates without locks, then per order (one savepoint) the case lock, the order re-read
    `FOR UPDATE` and skipped unless still pending; then `expire_stale`."""
    cfg = cfg or NextDateConfig.from_settings()
    now = now or _now()
    today = today_ist(now)
    counters = dict.fromkeys(COUNTERS, 0)
    # suggestions the court's date now confirms (point 2), before the batch takes any case lock
    counters["matched"] = match_court_dates(session, today=today, cfg=cfg)
    ids = candidates(session, batch=batch or cfg.batch, order_id=order_id)
    counters["claimed"] = len(ids)
    for oid in ids:
        try:
            with session.begin_nested():
                case_id = session.scalar(select(Order.case_id).where(Order.id == oid))
                session.execute(select(Case.id).where(Case.id == case_id).with_for_update())
                order = session.scalar(
                    select(Order)
                    .where(Order.id == oid)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if (
                    order is None
                    or OrderNextDateStatus(order.next_date_status) != OrderNextDateStatus.PENDING
                ):
                    counters["skipped"] += 1
                    continue
                read_order(session, order, today=today, cfg=cfg, counters=counters)
                session.execute(
                    sql_text(
                        "UPDATE source_failures SET resolved_at = now() "
                        "WHERE kind = :k AND ref = :r AND resolved_at IS NULL"
                    ),
                    {"k": FAILURE_KIND, "r": str(oid)},
                )
        except Exception as exc:  # noqa: BLE001 — one bad order must not stop the run; it is recorded
            counters["failed"] += 1
            log.exception("next-date reader: order %s failed", oid)
            record_failure(session, FAILURE_KIND, str(oid), f"{exc.__class__.__name__}: {exc}"[:2000])
    counters["expired"] = expire_stale(session, today)
    session.flush()
    # next-date-direct (Jobs): rollovers, failed refreshes and the backfill of the case's one next hearing
    if order_id is None:
        counters.update(next_hearing.refresh_due(session, today=today))
    return counters


def run_job(
    session: Session, *, cfg: NextDateConfig | None = None, now: datetime | None = None
) -> dict[str, int]:
    """The 5-minute job: one `job_runs` row (`partial` when an order failed)."""
    now = now or _now()
    run = JobRun(job=JOB, run_date=today_ist(now), started_at=now)
    session.add(run)
    session.flush()
    try:
        counters = read_pending(session, now=now, cfg=cfg)
    except Exception as exc:
        run.status, run.error = JobStatus.FAILED, f"{exc.__class__.__name__}: {exc}"[:2000]
        run.finished_at = _now()
        session.flush()
        raise
    run.counters = counters
    run.status = JobStatus.PARTIAL if counters.get("failed") else JobStatus.SUCCEEDED
    run.finished_at = _now()
    session.flush()
    return counters


def dry_run(
    session: Session,
    *,
    limit: int | None = None,
    now: datetime | None = None,
    cfg: NextDateConfig | None = None,
    page: int = 500,
) -> dict[str, Any]:
    """`aslms next-dates read --dry-run`: reads the pending orders' text and counts what a run would record, writing
    nothing (keyset pages, read-only)."""
    cfg = cfg or NextDateConfig.from_settings()
    today = today_ist(now or _now())
    out: dict[str, Any] = {
        "read": 0,
        "by_status": {},
        "by_rule": {},
        "would_write": 0,
        "would_be_firm": 0,
        "would_ask": 0,
    }
    last: tuple[datetime, uuid.UUID] | None = None
    while limit is None or out["read"] < limit:
        stmt = (
            select(
                Order.id,
                Order.created_at,
                Order.order_date,
                Document.text_status,
                DocumentText.full_text,
                current_order_condition().label("current"),
            )
            .join(Document, Document.id == Order.document_id)
            .outerjoin(DocumentText, DocumentText.document_id == Document.id)
            .where(
                Order.next_date_status == OrderNextDateStatus.PENDING, Document.text_status.in_(READABLE_TEXT)
            )
            .order_by(Order.created_at, Order.id)
            .limit(page if limit is None else min(page, limit - out["read"]))
        )
        if last is not None:
            stmt = stmt.where(
                (Order.created_at > last[0]) | ((Order.created_at == last[0]) & (Order.id > last[1]))
            )
        rows = session.execute(stmt).all()
        if not rows:
            break
        for oid, created, order_date, text_status, full_text, current in rows:
            out["read"] += 1
            if TextStatus(text_status) == TextStatus.NONE:
                reading = rules.Reading(rules.NO_TEXT, needs_review=True)
            else:
                reading = rules.read_order_text(full_text, order_date, max_ahead_days=cfg.max_ahead_days)
            out["by_status"][reading.status] = out["by_status"].get(reading.status, 0) + 1
            key = f"{reading.status}/{reading.rule or '-'}"
            out["by_rule"][key] = out["by_rule"].get(key, 0) + 1
            if current and reading.date is not None and reading.date >= today:
                out["would_write"] += 1
                out["would_be_firm"] += 1  # next-date-direct: every dated current reading is shown directly
            elif (
                current
                and reading.status in REVIEW_READINGS
                and order_date >= today - timedelta(days=cfg.unclear_days)
            ):
                out["would_ask"] += 1
            last = (created, oid)
    return out


def reread(session: Session, actor: Actor, *, all_versions: bool = False) -> int:
    """Orders read under an older `RULES_VERSION` (or every read order) back to `pending`; audited
    `next_dates.reread` (system actor `cli`, the count)."""
    stmt = update(Order).where(Order.next_date_status != OrderNextDateStatus.PENDING)
    if not all_versions:
        stmt = stmt.where(
            (Order.next_date_rules_version.is_(None)) | (Order.next_date_rules_version < rules.RULES_VERSION)
        )
    result = session.execute(
        stmt.values(
            next_date_status=OrderNextDateStatus.PENDING,
            next_date_found=None,
            next_date_rule=None,
            next_date_phrase=None,
            next_date_rules_version=None,
            next_date_read_at=None,
        ).execution_options(synchronize_session=False)
    )
    n = int(result.rowcount or 0)
    write_audit(
        session,
        actor,
        "next_dates.reread",
        "orders",
        None,
        after={"orders": n, "all_versions": all_versions, "rules_version": rules.RULES_VERSION},
    )
    session.flush()
    return n


# ------------------------------------------------------------------------------------------------ the queue


def _departments_by_case(
    session: Session, user: User | Member, case_ids: set[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """For each case, the departments of the caller's memberships that hold the function and work on it."""
    members = [
        m for m in access.members(session, user) if m.holds(Permission.NEXT_DATES_REVIEW) and m.department
    ]
    conds = [(m, visibility.member_working_condition(session, m)) for m in members]
    conds = [(m, c) for m, c in conds if c is not None]
    if not case_ids or not conds:
        return {}
    rows = session.execute(
        select(Case.id, *[c.label(f"m{i}") for i, (_, c) in enumerate(conds)]).where(Case.id.in_(case_ids))
    ).all()
    out: dict[uuid.UUID, list[str]] = {}
    for row in rows:
        codes: list[str] = []
        for (m, _), flag in zip(conds, row[1:], strict=True):
            if flag and m.department.code not in codes:
                codes.append(m.department.code)
        out[row[0]] = codes
    return out


def _open_review_alerts(session: Session, order_ids: set[uuid.UUID]) -> dict[str, Alert]:
    if not order_ids:
        return {}
    keys = [review_alert_key(o) for o in order_ids]
    rows = session.scalars(
        select(Alert).where(
            Alert.dedupe_key.in_(keys), Alert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED])
        )
    ).all()
    return {a.dedupe_key: a for a in rows}


def review_alert_key(order_id: uuid.UUID | str) -> str:
    return f"{AlertKind.NEXT_DATE_REVIEW.value}:{order_id}"


def review_items(
    session: Session,
    user: User | Member,
    *,
    kind: str | None = None,
    filters: CaseFilters | None = None,
    limit: int | None = None,
    offset: int | None = None,
    today: date | None = None,
    cfg: NextDateConfig | None = None,
) -> Page:
    """`GET /next-dates/review` (decisions 7, 10, 17): sorted by `act_by`, then the case."""
    require_function(session, user, Permission.NEXT_DATES_REVIEW)
    cfg = cfg or NextDateConfig.from_settings()
    today = today or today_ist()
    q = queue_subquery(
        session, review_condition(session, user), today=today, cfg=cfg, kind=kind, filters=filters
    )
    total = int(session.scalar(select(func.count()).select_from(q)) or 0)
    limit, offset = clamp(limit, offset)
    rows = session.execute(
        select(q.c.kind, q.c.id, q.c.case_id, q.c.order_id, q.c.act_by, q.c.next_date, q.c.reason)
        .join(Case, Case.id == q.c.case_id)
        .order_by(q.c.act_by, Case.ref_no, q.c.id)
        .limit(limit)
        .offset(offset)
    ).all()
    case_ids = {r.case_id for r in rows}
    order_ids = {r.order_id for r in rows if r.order_id is not None}
    cases = (
        {c.id: c for c in session.scalars(select(Case).where(Case.id.in_(case_ids))).all()}
        if case_ids
        else {}
    )
    orders = (
        {o.id: o for o in session.scalars(select(Order).where(Order.id.in_(order_ids))).all()}
        if order_ids
        else {}
    )
    alerts = _open_review_alerts(session, order_ids)
    depts = _departments_by_case(session, user, case_ids)
    items = []
    for r in rows:
        order = orders.get(r.order_id)
        alert = alerts.get(review_alert_key(r.order_id)) if r.order_id else None
        items.append(
            {
                "kind": r.kind,
                "id": r.id,
                "case": calendar.case_ref(cases[r.case_id]),
                "order": _order_ref(order),
                "phrase": order.next_date_phrase if order else None,
                "rule": order.next_date_rule if order else None,
                "next_date": r.next_date,
                "act_by": r.act_by,
                "reason": r.reason,
                "alert_ref_no": alert.ref_no if alert else None,
                "departments": depts.get(r.case_id, []),
            }
        )
    return Page(items, total)


def _order_ref(order: Order | None) -> dict[str, Any] | None:
    if order is None:
        return None
    return {
        "id": order.id,
        "order_no": order.order_no,
        "order_date": order.order_date,
        "document_id": order.document_id,
    }


# ------------------------------------------------------------------------------------------------ writes


def resolve_next_date(session: Session, ref: str | uuid.UUID) -> NextDate:
    """A next date by its uuid or `ref_no` (slash or dash form)."""
    row = None
    if isinstance(ref, uuid.UUID):
        row = session.get(NextDate, ref)
    else:
        s = (ref or "").strip()
        try:
            row = session.get(NextDate, uuid.UUID(s))
        except ValueError:
            ref_no = ref_no_from_url(s)
            if ref_no is not None:
                row = session.scalar(select(NextDate).where(NextDate.ref_no == ref_no))
    if row is None:
        raise NextDateNotFound("no such next date")
    return row


def _check_visible(session: Session, user: User | Member, case: Case) -> None:
    """Decision 10, first part: the function (403) and a visible case (404), before any field is checked (400), so
    a caller who cannot see the case learns nothing from the field errors."""
    require_function(session, user, Permission.NEXT_DATES_REVIEW)
    require_visible_basis(session, user, case)


def _check_working(session: Session, user: User | Member, case: Case) -> Member:
    """Decision 10, second part, in the order of `stages.set`: the case row lock, a claim (409 `not_owned`), a
    working basis and the function in one membership (403)."""
    lock_case(session, case)
    require_owned(session, case)
    return acting_member(session, user, case, Permission.NEXT_DATES_REVIEW)


def _check_write(session: Session, user: User | Member, case: Case) -> Member:
    _check_visible(session, user, case)
    return _check_working(session, user, case)


def check_no_court_date(session: Session, case: Case, *, today: date | None = None) -> None:
    """Next-date-direct, decision 6: for every user and every type, nothing is entered, confirmed or rejected while
    the case has a court-given next date (recomputed for the case under its lock, never the stored column). A refused
    attempt writes no audit row."""
    if next_hearing.court_given(session, case, today=today or today_ist()):
        raise conflict("court_date_fixed", COURT_DATE_FIXED)


def check_date(d: date | None, *, today: date, cfg: NextDateConfig, name: str = "next_date") -> date:
    if d is None:
        raise bad(f"{name} is required")
    if d < today:
        raise bad(f"{name} cannot be in the past")
    if d > today + timedelta(days=cfg.max_ahead_days):
        raise bad(f"{name} is at most {cfg.max_ahead_days} days ahead")
    return d


def _locked_row(session: Session, row_id: uuid.UUID) -> NextDate:
    return session.scalar(
        select(NextDate)
        .where(NextDate.id == row_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def close_moot_review_alerts(
    session: Session,
    case_id: uuid.UUID,
    reason: str,
    *,
    status: AlertStatus = AlertStatus.DONE,
    actor_user_id: uuid.UUID | None = None,
    today: date | None = None,
    cfg: NextDateConfig | None = None,
) -> int:
    """Closes the case's open `next_date_review` alerts whose order has no queue item left."""
    from aslms.services.alerts import close_alert

    today = today or today_ist()
    cfg = cfg or NextDateConfig.from_settings()
    n = 0
    for a in session.scalars(
        select(Alert)
        .where(
            Alert.case_id == case_id,
            Alert.kind == AlertKind.NEXT_DATE_REVIEW,
            Alert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
        )
        .with_for_update()
    ).all():
        order_id = _uuid((a.data or {}).get("order_id"))
        if order_id is None or not order_has_item(session, order_id, today=today, cfg=cfg):
            close_alert(session, a, status, reason, actor_user_id=actor_user_id)
            n += 1
    return n


def _uuid(v: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(v)) if v else None
    except ValueError:
        return None


def _snapshot(row: NextDate) -> dict[str, Any]:
    return {
        "next_date": row.next_date,
        "source": value(row.source),
        "review_status": value(row.review_status),
        "order_id": row.order_id,
    }


def confirm(
    session: Session,
    actor: Actor,
    user: User | Member,
    next_date_id: uuid.UUID | str,
    *,
    cfg: NextDateConfig | None = None,
) -> NextDate:
    """Decision 12: a pending row → `confirmed` (409 `not_pending` otherwise)."""
    cfg = cfg or NextDateConfig.from_settings()
    row = resolve_next_date(session, next_date_id)
    case = session.get(Case, row.case_id)
    member = _check_write(session, user, case)
    check_no_court_date(session, case)
    row = _locked_row(session, row.id)
    if ReviewStatus(row.review_status) != ReviewStatus.PENDING:
        raise conflict("not_pending", "the next date is not waiting for review")
    if row.next_date < today_ist():  # point 4: a date already passed is not confirmed
        raise conflict("date_passed", "the next date has already passed")
    actor = access.actor_as(actor, member)
    before = _snapshot(row)
    row.review_status = ReviewStatus.CONFIRMED
    row.reviewed_by_user_id = actor.user_id
    row.reviewed_at = _now()
    row.updated_by = actor.user_id
    session.flush()
    close_moot_review_alerts(session, case.id, "confirmed", actor_user_id=actor.user_id, cfg=cfg)
    _reviewed_event(session, case, row, "confirm", member, actor)
    write_audit(
        session,
        actor,
        "next_date.confirm",
        "next_date",
        row.id,
        case_id=case.id,
        before=before,
        after={**_snapshot(row), "office_code": member.office.code},
    )
    next_hearing.refresh(session, [case.id])
    return row


def reject(
    session: Session,
    actor: Actor,
    user: User | Member,
    next_date_id: uuid.UUID | str,
    *,
    note: str | None = None,
    replacement: date | None = None,
    cfg: NextDateConfig | None = None,
) -> tuple[NextDate, NextDate | None]:
    """Decision 12: a pending row → `rejected` with an optional note; an optional replacement date writes the manual
    row of decision 11 linked to the same order, in the same transaction."""
    cfg = cfg or NextDateConfig.from_settings()
    row = resolve_next_date(session, next_date_id)
    case = session.get(Case, row.case_id)
    _check_visible(session, user, case)  # 404 before any field error
    text_ = clean_text(note, "note", min_len=1, max_len=NOTE_MAX, required=False)
    if replacement is not None:
        check_date(replacement, today=today_ist(), cfg=cfg)
    member = _check_working(session, user, case)
    check_no_court_date(session, case)
    row = _locked_row(session, row.id)
    if ReviewStatus(row.review_status) != ReviewStatus.PENDING:
        raise conflict("not_pending", "the next date is not waiting for review")
    actor = access.actor_as(actor, member)
    before = _snapshot(row)
    row.review_status = ReviewStatus.REJECTED
    row.reviewed_by_user_id = actor.user_id
    row.reviewed_at = _now()
    row.updated_by = actor.user_id
    row.note = text_
    session.flush()
    _reviewed_event(session, case, row, "reject", member, actor)
    write_audit(
        session,
        actor,
        "next_date.reject",
        "next_date",
        row.id,
        case_id=case.id,
        before=before,
        after={
            **_snapshot(row),
            "office_code": member.office.code,
            "note": digest(text_) if text_ else None,
            "replacement": replacement,
        },
    )
    entered = None
    if replacement is not None:
        entered = _insert_manual(
            session, actor, member, case, next_date=replacement, note=None, order_id=row.order_id
        )
    close_moot_review_alerts(session, case.id, "rejected", actor_user_id=actor.user_id, cfg=cfg)
    next_hearing.refresh(session, [case.id])
    return row, entered


def enter(
    session: Session,
    actor: Actor,
    user: User | Member,
    case: Case,
    *,
    next_date: date | None,
    note: str | None = None,
    order_id: uuid.UUID | str | None = None,
    member: Member | None = None,
    cfg: NextDateConfig | None = None,
) -> NextDate:
    """Decision 11: a manual next date (`NXT` on the acting office); supersedes the case's pending rows and closes
    their review alerts. `member`: the caller has checked the rules and holds the case lock."""
    cfg = cfg or NextDateConfig.from_settings()
    if member is None:
        _check_visible(session, user, case)  # 404 before any field error
    check_date(next_date, today=today_ist(), cfg=cfg)
    text_ = clean_text(note, "note", min_len=1, max_len=NOTE_MAX, required=False)
    oid = None
    if order_id is not None and str(order_id).strip():
        oid = _uuid(order_id)
        order = session.get(Order, oid) if oid else None
        if order is None or order.case_id != case.id:
            raise bad("order is not an order of this case")
    if member is None:
        member = _check_working(session, user, case)
    check_no_court_date(session, case)
    actor = access.actor_as(actor, member)
    row = _insert_manual(session, actor, member, case, next_date=next_date, note=text_, order_id=oid)
    close_moot_review_alerts(session, case.id, "entered", actor_user_id=actor.user_id, cfg=cfg)
    next_hearing.refresh(session, [case.id])
    return row


def _insert_manual(
    session: Session,
    actor: Actor,
    member: Member,
    case: Case,
    *,
    next_date: date,
    note: str | None,
    order_id: uuid.UUID | None,
) -> NextDate:
    same = session.scalar(
        select(NextDate.id).where(
            NextDate.case_id == case.id,
            NextDate.next_date == next_date,
            NextDate.source == NextDateSource.MANUAL,
            NextDate.order_id.is_not_distinct_from(order_id),
        )
    )
    if same is not None:
        raise conflict("already_entered", "this next date was already entered for the case")
    office = member.office
    row = NextDate(
        ref_no=allocate_ref_no(session, office.code, RecordType.NXT.value),
        case_id=case.id,
        next_date=next_date,
        source=NextDateSource.MANUAL,
        order_id=order_id,
        confidence=1.0,
        needs_review=False,
        review_status=ReviewStatus.NOT_NEEDED,
        note=note,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    session.add(row)
    session.flush()
    supersede(session, case.id, keep=row.id, by=actor.user_id)
    emit_event(
        session,
        EventType.NEXT_DATE_ENTERED,
        case,
        {
            "next_date_id": str(row.id),
            "ref_no": row.ref_no,
            "next_date": next_date,
            "order_id": str(order_id) if order_id else None,
            "office_code": office.code,
        },
        dedupe=f"next_date_entered:{row.id}",
        actor_user_id=actor.user_id,
    )
    write_audit(
        session,
        actor,
        "next_date.enter",
        "next_date",
        row.id,
        case_id=case.id,
        after={
            "ref_no": row.ref_no,
            "next_date": next_date,
            "order_id": order_id,
            "office_code": office.code,
            "note": digest(note) if note else None,
        },
    )
    return row


def _reviewed_event(
    session: Session, case: Case, row: NextDate, action: str, member: Member, actor: Actor
) -> None:
    emit_event(
        session,
        EventType.NEXT_DATE_REVIEWED,
        case,
        {
            "next_date_id": str(row.id),
            "action": action,
            "next_date": row.next_date,
            "office_code": member.office.code,
        },
        dedupe=f"next_date_reviewed:{row.id}",
        actor_user_id=actor.user_id,
    )


# ------------------------------------------------------------------------------------------------ reads


def effective_for_case(session: Session, case: Case | uuid.UUID) -> NextDate | None:
    """The "Next Date From Orders" card (next-date-direct, decision 4's ranking): the latest open order reading
    (not-needed, pending or confirmed: a reading is shown directly), else the latest open manual row."""
    case_id = case if isinstance(case, uuid.UUID) else case.id
    for sources in (ORDER_SOURCES, (NextDateSource.MANUAL,)):
        row = session.scalar(
            select(NextDate)
            .where(
                NextDate.case_id == case_id,
                NextDate.source.in_(sources),
                NextDate.review_status.in_(OPEN_REVIEW),
            )
            .order_by(NextDate.created_at.desc(), NextDate.id.desc())
            .limit(1)
        )
        if row is not None:
            return row
    return None


def next_date_out(
    session: Session, row: NextDate, *, users: dict[uuid.UUID, User] | None = None
) -> dict[str, Any]:
    order = session.get(Order, row.order_id) if row.order_id else None

    def name(uid: uuid.UUID | None) -> dict[str, Any] | None:
        if uid is None:
            return None
        u = (users or {}).get(uid) or session.get(User, uid)
        return {"name": u.full_name} if u is not None else None

    return {
        "id": row.id,
        "ref_no": row.ref_no,
        "next_date": row.next_date,
        "source": value(row.source),
        "confidence": float(row.confidence),
        "needs_review": row.needs_review,
        "review_status": value(row.review_status),
        "order": (
            {**_order_ref(order), "phrase": order.next_date_phrase, "rule": order.next_date_rule}
            if order is not None
            else None
        ),
        "note": row.note,
        "reviewed_by": name(row.reviewed_by_user_id),
        "reviewed_at": row.reviewed_at,
        "created_by": name(row.created_by),
        "created_at": row.created_at,
    }


def case_next_dates(
    session: Session, user: User | Member, case: Case, *, limit: int | None = None, offset: int | None = None
) -> Page:
    """`GET /cases/{ref}/next-dates`: every source, newest first, the effective row flagged."""
    visibility.require_visible(session, user, case)
    stmt = select(NextDate).where(NextDate.case_id == case.id)
    total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    limit, offset = clamp(limit, offset)
    rows = session.scalars(
        stmt.order_by(NextDate.created_at.desc(), NextDate.id.desc()).limit(limit).offset(offset)
    ).all()
    effective = effective_for_case(session, case)
    return Page(
        [
            {**next_date_out(session, r), "effective": effective is not None and r.id == effective.id}
            for r in rows
        ],
        total,
    )


def to_review_for_case(
    session: Session, user: User | Member, case: Case, *, cfg: NextDateConfig | None = None
) -> int:
    """Decision 18: the case's queue items the caller may act on; 0 without the function."""
    if not access.has(session, user, Permission.NEXT_DATES_REVIEW):
        return 0
    return queue_count(session, user, case_id=case.id, cfg=cfg or NextDateConfig.from_settings())


def status_report(
    session: Session, *, today: date | None = None, cfg: NextDateConfig | None = None
) -> dict[str, Any]:
    """`aslms next-dates status`: orders by reading status and rule, rows by source and review status, the queue by
    kind (every claimed case)."""
    today = today or today_ist()
    cfg = cfg or NextDateConfig.from_settings()
    orders = [
        (value(s), r, int(n))
        for s, r, n in session.execute(
            select(Order.next_date_status, Order.next_date_rule, func.count())
            .group_by(Order.next_date_status, Order.next_date_rule)
            .order_by(Order.next_date_status, Order.next_date_rule)
        ).all()
    ]
    rows = [
        (value(s), value(r), int(n))
        for s, r, n in session.execute(
            select(NextDate.source, NextDate.review_status, func.count())
            .group_by(NextDate.source, NextDate.review_status)
            .order_by(NextDate.source, NextDate.review_status)
        ).all()
    ]
    q = queue_subquery(session, true(), today=today, cfg=cfg)
    queue = {k: int(n) for k, n in session.execute(select(q.c.kind, func.count()).group_by(q.c.kind)).all()}
    return {
        "orders": orders,
        "rows": rows,
        "queue": {k: queue.get(k, 0) for k in KINDS},
        "rules_version": rules.RULES_VERSION,
        "next_hearing": next_hearing.status_counts(session),
    }


def sample(
    session: Session, *, status: str, rule: str | None = None, n: int = 20, seed: int = 1
) -> list[dict[str, Any]]:
    """`aslms next-dates sample`: a reproducible random sample of read orders for the hand check."""
    try:
        st = OrderNextDateStatus(status)
    except ValueError as exc:
        raise bad(f"unknown status {status!r}") from exc
    stmt = (
        select(Order, Case)
        .join(Case, Case.id == Order.case_id)
        .where(Order.next_date_status == st)
        .order_by(func.md5(func.concat(cast(Order.id, String), str(seed))))
        .limit(max(1, min(int(n), 200)))
    )
    if rule:
        stmt = stmt.where(Order.next_date_rule == rule)
    return [
        {
            "order_date": o.order_date,
            "cnr": c.cnr,
            "case_no_text": c.case_no_text,
            "order_no": o.order_no,
            "status": value(o.next_date_status),
            "rule": o.next_date_rule,
            "date": o.next_date_found,
            "phrase": o.next_date_phrase,
            "document_id": o.document_id,
        }
        for o, c in session.execute(stmt).all()
    ]


# ------------------------------------------------------------------------------------------------ misread readings
# next-date-direct, decisions 17 to 19: report a wrong reading, correct it, or keep it


def reportable_row(session: Session, case: Case, *, today: date | None = None) -> NextDate | None:
    """Decision 17's row: the case's latest order reading (decision 4, step 2) - the latest open `order_specific` /
    `order_period` row, dated today or later."""
    today = today or today_ist()
    row = session.scalar(
        select(NextDate)
        .where(
            NextDate.case_id == case.id,
            NextDate.source.in_(ORDER_SOURCES),
            NextDate.review_status.in_(OPEN_REVIEW),
        )
        .order_by(NextDate.created_at.desc(), NextDate.id.desc())
        .limit(1)
    )
    if row is None or row.next_date < today:
        return None
    return row


def _reason(value_: str | None) -> str:
    return clean_text(value_, "reason", min_len=REASON_MIN, max_len=REASON_MAX, required=True)


def _check_oversight(session: Session, user: User | Member, case: Case, permission: Permission) -> None:
    """The function (403) and a visible case (404); no working basis: reporting and correcting are oversight."""
    require_function(session, user, permission)
    visibility.require_visible(session, user, case)


def _acting_office(session: Session, user: User | Member, permission: Permission) -> Office:
    """The office acting for the caller: the first membership holding the function (for the super admin, their own
    office)."""
    members = access.members(session, user)
    for m in members:
        if m.holds(permission):
            return m.office
    if members:
        return members[0].office
    raise access.Forbidden(f"{permission.value} is not enabled for you")


def _member_holding(session: Session, user: User | Member, permission: Permission) -> Member | None:
    for m in access.members(session, user):
        if m.holds(permission):
            return m
    return None


def correctors(session: Session, case: Case) -> list[User]:
    """The active holders of `next_dates.correct` who may see the case (the super admin always)."""
    from aslms.domain.org import UserMembership

    out: list[User] = []
    for m, u in session.execute(
        select(UserMembership, User)
        .join(User, User.id == UserMembership.user_id)
        .where(UserMembership.is_active.is_(True), User.is_active.is_(True))
        .order_by(User.email, UserMembership.id)
    ).all():
        if any(x.id == u.id for x in out):
            continue
        if access.member_of(session, m, u).holds(Permission.NEXT_DATES_CORRECT) and visibility.can_view_case(
            session, u, case
        ):
            out.append(u)
    return out


def _report_alert(session: Session, row: NextDate) -> Alert | None:
    return session.scalars(
        select(Alert).where(*next_hearing.open_report_alerts([row.id])).with_for_update()
    ).first()


def _new_report_key(session: Session, case: Case, row: NextDate) -> str:
    """Decision 17 with Deviation 16: the first report of a reading takes `next_date_reported:<id>`; a report after
    the earlier ones were closed takes the next free number, so it raises a new alert instead of finding the closed
    one (the key is unique across every status). Read under the case lock."""
    keys = set(
        session.scalars(
            select(Alert.dedupe_key).where(
                Alert.case_id == case.id, Alert.kind == AlertKind.NEXT_DATE_REPORTED
            )
        ).all()
    )
    n = 1
    while next_hearing.report_alert_key(row.id, n) in keys:
        n += 1
    return next_hearing.report_alert_key(row.id, n)


def _reading_snapshot(session: Session, row: NextDate) -> dict[str, Any]:
    order = session.get(Order, row.order_id) if row.order_id else None
    return {
        **_snapshot(row),
        "order_no": order.order_no if order else None,
        "order_date": order.order_date if order else None,
        "rule": order.next_date_rule if order else None,
        "phrase": order.next_date_phrase if order else None,
    }


def report_wrong(
    session: Session,
    actor: Actor,
    user: User | Member,
    next_date_id: uuid.UUID | str,
    *,
    reason: str | None,
) -> Alert:
    """Decision 17: one `next_date_reported` alert to the correctors; no date changes."""
    from aslms.domain.alerts import Severity
    from aslms.services.alerts import raise_alert

    row = resolve_next_date(session, next_date_id)
    case = session.get(Case, row.case_id)
    _check_oversight(session, user, case, Permission.NEXT_DATES_REPORT_WRONG)
    text_ = _reason(reason)
    lock_case(session, case)
    row = _locked_row(session, row.id)
    current = reportable_row(session, case)
    if current is None or current.id != row.id:
        raise conflict("not_reportable", NOT_ORDER_READING)
    if _report_alert(session, row) is not None:
        raise conflict(
            "already_reported", "This date has already been reported and is waiting for correction."
        )
    office = _ownership_office(session, case) or _acting_office(
        session, user, Permission.NEXT_DATES_REPORT_WRONG
    )
    reporter_office = _acting_office(session, user, Permission.NEXT_DATES_REPORT_WRONG)
    order = session.get(Order, row.order_id) if row.order_id else None
    reporter = session.get(User, actor.user_id) if actor.user_id else None
    alert, _ = raise_alert(
        session,
        case=case,
        kind=AlertKind.NEXT_DATE_REPORTED,
        key=_new_report_key(session, case, row),
        office=office,
        severity=Severity.NORMAL,
        data={
            "next_date_id": row.id,
            "order_id": row.order_id,
            "document_id": order.document_id if order else None,
            "order_no": order.order_no if order else None,
            "order_date": order.order_date if order else None,
            "hearing_date": row.next_date,
            "rule": order.next_date_rule if order else None,
            "reporter_name": reporter.full_name if reporter else actor.name,
            "reporter_office_code": reporter_office.code,
            "reason": text_,
        },
        recipients=lambda: correctors(session, case),
    )
    write_audit(
        session,
        actor,
        "next_date.report_wrong",
        "next_date",
        row.id,
        case_id=case.id,
        after={**_snapshot(row), "alert_ref_no": alert.ref_no, "reason": digest(text_)},
    )
    return alert


def _ownership_office(session: Session, case: Case) -> Office | None:
    from aslms.services.workflow_common import primary_owner

    owner = primary_owner(session, case)
    return session.get(Office, owner.office_id) if owner is not None else None


def correct(
    session: Session,
    actor: Actor,
    user: User | Member,
    next_date_id: uuid.UUID | str,
    *,
    reason: str | None,
    next_date: date | None = None,
    cfg: NextDateConfig | None = None,
) -> tuple[NextDate, NextDate | None]:
    """Decision 18: the reading becomes `rejected` (the reason in `note`, reviewer and time set; the order's reading
    columns untouched); with a date, a `manual` row on the corrector's office linked to the same order. Open report
    alerts close `done` / `corrected`; event `next_date_reviewed` (action `corrected`); audit `next_date.correct`."""
    from aslms.services.alerts import close_alert

    cfg = cfg or NextDateConfig.from_settings()
    row = resolve_next_date(session, next_date_id)
    case = session.get(Case, row.case_id)
    _check_oversight(session, user, case, Permission.NEXT_DATES_CORRECT)
    text_ = _reason(reason)
    if next_date is not None:
        check_date(next_date, today=today_ist(), cfg=cfg)
    lock_case(session, case)
    row = _locked_row(session, row.id)
    current = reportable_row(session, case)
    if current is None or current.id != row.id:
        raise conflict("not_order_reading", NOT_ORDER_READING)
    member = _member_holding(session, user, Permission.NEXT_DATES_CORRECT)
    office = (
        member.office if member is not None else _acting_office(session, user, Permission.NEXT_DATES_CORRECT)
    )
    if member is not None:
        actor = access.actor_as(actor, member)
    before = _reading_snapshot(session, row)
    row.review_status = ReviewStatus.REJECTED
    row.reviewed_by_user_id = actor.user_id
    row.reviewed_at = _now()
    row.updated_by = actor.user_id
    row.note = text_
    session.flush()
    entered = None
    if next_date is not None:
        entered = _insert_corrected(session, actor, office, case, row, next_date=next_date)
    for alert in session.scalars(
        select(Alert).where(*next_hearing.open_report_alerts([row.id])).with_for_update()
    ).all():
        close_alert(session, alert, AlertStatus.DONE, "corrected", actor_user_id=actor.user_id)
    emit_event(
        session,
        EventType.NEXT_DATE_REVIEWED,
        case,
        {
            "next_date_id": str(row.id),
            "action": "corrected",
            "next_date": row.next_date,
            "corrected_to": next_date,
            "office_code": office.code,
        },
        dedupe=f"next_date_reviewed:{row.id}",
        actor_user_id=actor.user_id,
    )
    write_audit(
        session,
        actor,
        "next_date.correct",
        "next_date",
        row.id,
        case_id=case.id,
        before=before,
        after={
            **_reading_snapshot(session, row),
            "office_code": office.code,
            "reason": digest(text_),
            "entered_ref_no": entered.ref_no if entered is not None else None,
            "entered_date": next_date,
        },
    )
    close_moot_review_alerts(session, case.id, "corrected", actor_user_id=actor.user_id, cfg=cfg)
    next_hearing.refresh(session, [case.id])
    return row, entered


def _insert_corrected(
    session: Session, actor: Actor, office: Office, case: Case, row: NextDate, *, next_date: date
) -> NextDate:
    """The corrected date: a `manual` row (`NXT` on the corrector's office) linked to the order of the reading."""
    entered = NextDate(
        ref_no=allocate_ref_no(session, office.code, RecordType.NXT.value),
        case_id=case.id,
        next_date=next_date,
        source=NextDateSource.MANUAL,
        order_id=row.order_id,
        confidence=1.0,
        needs_review=False,
        review_status=ReviewStatus.NOT_NEEDED,
        note=None,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    session.add(entered)
    session.flush()
    emit_event(
        session,
        EventType.NEXT_DATE_ENTERED,
        case,
        {
            "next_date_id": str(entered.id),
            "ref_no": entered.ref_no,
            "next_date": next_date,
            "order_id": str(row.order_id) if row.order_id else None,
            "office_code": office.code,
            "corrects": str(row.id),
        },
        dedupe=f"next_date_entered:{entered.id}",
        actor_user_id=actor.user_id,
    )
    return entered


def keep(
    session: Session,
    actor: Actor,
    user: User | Member,
    next_date_id: uuid.UUID | str,
    *,
    note: str | None = None,
) -> int:
    """Decision 18, "Reading Is Right": the open report alerts close `done` / `kept`; the reading stays."""
    from aslms.services.alerts import close_alert

    row = resolve_next_date(session, next_date_id)
    case = session.get(Case, row.case_id)
    _check_oversight(session, user, case, Permission.NEXT_DATES_CORRECT)
    text_ = clean_text(note, "note", min_len=1, max_len=NOTE_MAX, required=False)
    lock_case(session, case)
    alerts = list(
        session.scalars(
            select(Alert).where(*next_hearing.open_report_alerts([row.id])).with_for_update()
        ).all()
    )
    if not alerts:
        raise conflict("not_reported", "There is no open report on this date.")
    member = _member_holding(session, user, Permission.NEXT_DATES_CORRECT)
    if member is not None:
        actor = access.actor_as(actor, member)
    for alert in alerts:
        close_alert(session, alert, AlertStatus.DONE, "kept", actor_user_id=actor.user_id)
    write_audit(
        session,
        actor,
        "next_date.report_kept",
        "next_date",
        row.id,
        case_id=case.id,
        after={
            **_snapshot(row),
            "alerts": [a.ref_no for a in alerts],
            "note": digest(text_) if text_ else None,
        },
    )
    return len(alerts)


def report_still_current(session: Session, alert: Alert, *, today: date | None = None) -> bool:
    """The hourly sweep (decision 17): a report stays open while its row is still the case's reportable row."""
    row_id = _uuid((alert.data or {}).get("next_date_id"))
    case = session.get(Case, alert.case_id) if alert.case_id else None
    if row_id is None or case is None:
        return False
    current = reportable_row(session, case, today=today)
    return current is not None and current.id == row_id


# ------------------------------------------------------------------------------------------------ direct apply
# next-date-direct, decision 13: `aslms next-dates direct [--apply]`


def direct_apply(
    session: Session, *, apply: bool, today: date | None = None, cfg: NextDateConfig | None = None
) -> dict[str, Any]:
    """Re-evaluates the old suggestions once. The dry run counts and writes nothing; `apply` writes, refreshes every
    live case and audits `next_dates.direct_apply` (actor `cli`)."""
    from aslms.services.alerts import close_alert

    today = today or today_ist()
    cfg = cfg or NextDateConfig.from_settings()
    current = current_order_condition()
    pending_current = (
        select(NextDate)
        .join(Order, Order.id == NextDate.order_id)
        .where(
            NextDate.review_status == ReviewStatus.PENDING,
            NextDate.source.in_(ORDER_SOURCES),
            NextDate.next_date >= today,
            current,
        )
        .order_by(NextDate.case_id, NextDate.created_at, NextDate.id)
    )
    shown = list(session.scalars(pending_current).all())
    left = int(
        session.scalar(
            select(func.count())
            .select_from(NextDate)
            .where(NextDate.review_status == ReviewStatus.PENDING, NextDate.source.in_(ORDER_SOURCES))
        )
        or 0
    ) - len(shown)
    none_orders = list(
        session.scalars(
            select(Order)
            .join(Case, Case.id == Order.case_id)
            .where(
                Order.next_date_status == OrderNextDateStatus.NONE,
                Order.order_date >= today - timedelta(days=cfg.unclear_days),
                current,
                Case.merged_into_case_id.is_(None),
                Case.status != CaseStatus.DISPOSED,
            )
            .order_by(Order.case_id, Order.id)
        ).all()
    )
    rejected_current = session.execute(
        select(NextDate.id, NextDate.case_id, NextDate.next_date, Case.ref_no)
        .join(Order, Order.id == NextDate.order_id)
        .join(Case, Case.id == NextDate.case_id)
        .where(
            NextDate.review_status == ReviewStatus.REJECTED,
            NextDate.source.in_(ORDER_SOURCES),
            NextDate.next_date >= today,
            current,
        )
        .order_by(Case.ref_no)
    ).all()
    out: dict[str, Any] = {
        "apply": apply,
        "pending_shown_directly": len(shown),
        "pending_left_to_expire": max(0, left),
        "enter_items_added": 0,
        "manual_superseded": 0,
        "confirmed_differs": 0,
        "rejected_kept": len(rejected_current),
        "cases_refreshed": 0,
        "conflicts": [],
    }
    conflicts: list[dict[str, Any]] = [
        {"case": ref, "kind": "rejected_kept", "next_date_id": str(nid), "date": d.isoformat()}
        for nid, _, d, ref in rejected_current
    ]
    if not apply:
        manual_rows = session.execute(
            select(NextDate.case_id, Case.ref_no)
            .join(Case, Case.id == NextDate.case_id)
            .where(NextDate.source == NextDateSource.MANUAL, NextDate.review_status.in_(OPEN_REVIEW))
        ).all()
        given = (
            next_hearing.compute(session, [cid for cid, _ in manual_rows], today=today) if manual_rows else {}
        )
        for cid, ref in manual_rows:
            if given.get(cid) is not None and given[cid].court_given:
                out["manual_superseded"] += 1
                conflicts.append({"case": ref, "kind": "manual_superseded"})
        for o in none_orders:
            case = session.get(Case, o.case_id)
            if is_enter_item(session, case, o, today=today, cfg=cfg):
                out["enter_items_added"] += 1
        out["conflicts"] = conflicts
        return out
    # 1. pending readings of current orders dated today or later -> shown directly
    for row in shown:
        row.review_status = ReviewStatus.NOT_NEEDED
        row.needs_review = False
        row.updated_by = None
        session.flush()
        for alert in session.scalars(
            select(Alert)
            .where(
                Alert.dedupe_key == review_alert_key(row.order_id),
                Alert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
            )
            .with_for_update()
        ).all():
            close_alert(session, alert, AlertStatus.DONE, "shown_directly")
    # 4. every live case (before 3: the enter rule reads the refreshed value); supersedes and audits manual rows
    superseded_before = {
        r
        for (r,) in session.execute(
            select(NextDate.id).where(
                NextDate.source == NextDateSource.MANUAL, NextDate.review_status.in_(OPEN_REVIEW)
            )
        ).all()
    }
    refreshed = next_hearing.refresh_all(session, today=today)
    out["cases_refreshed"] = refreshed.refreshed
    out["manual_superseded"] = refreshed.manual_superseded
    if superseded_before:
        for nid, ref in session.execute(
            select(NextDate.id, Case.ref_no)
            .join(Case, Case.id == NextDate.case_id)
            .where(NextDate.id.in_(superseded_before), NextDate.review_status == ReviewStatus.SUPERSEDED)
        ).all():
            conflicts.append({"case": ref, "kind": "manual_superseded", "next_date_id": str(nid)})
    # 3. current `none` orders that are now enter items get their review event
    for o in none_orders:
        case = session.get(Case, o.case_id)
        if is_enter_item(session, case, o, today=today, cfg=cfg):
            reading = rules.Reading(rules.NONE, phrase=o.next_date_phrase)
            _extracted_event(session, case, o, reading, None, True)
            out["enter_items_added"] += 1
    # 5. confirmed rows whose date differs from the court's (now flagged)
    for ref, differs_on in session.execute(
        select(Case.ref_no, Case.next_hearing_differs_on)
        .join(NextDate, NextDate.id == Case.next_hearing_differs_id)
        .where(NextDate.review_status == ReviewStatus.CONFIRMED)
    ).all():
        out["confirmed_differs"] += 1
        conflicts.append({"case": ref, "kind": "confirmed_differs", "date": differs_on.isoformat()})
    out["conflicts"] = conflicts
    # 6. one audit row
    write_audit(
        session,
        Actor.system("cli"),
        "next_dates.direct_apply",
        "next_dates",
        None,
        after={k: v for k, v in out.items() if k != "conflicts"} | {"conflicts": len(conflicts)},
    )
    session.flush()
    return out


def hearing_refresh(
    session: Session, *, case: Case | None = None, dry_run: bool = False, today: date | None = None
) -> dict[str, Any]:
    """`aslms next-dates hearing-refresh [--all | --case REF] [--dry-run]`: repair and backfill at once; audited
    `next_dates.hearing_refresh` with the counts when it writes."""
    today = today or today_ist()
    if dry_run:
        if case is not None:
            value = next_hearing.compute(session, [case.id], today=today).get(case.id)
            return {"dry_run": True, "case": case.ref_no, "basis": value.basis.value if value else None}
        return {"dry_run": True, **next_hearing.preview_all(session, today=today)}
    result = next_hearing.refresh_all(session, today=today, case_id=case.id if case is not None else None)
    counts = {"dry_run": False, **result.counters()}
    write_audit(
        session,
        Actor.system("cli"),
        "next_dates.hearing_refresh",
        "cases",
        case.id if case is not None else None,
        case_id=case.id if case is not None else None,
        after={k: v for k, v in counts.items() if k != "dry_run"} | {"case": case.ref_no if case else None},
    )
    session.flush()
    return counts
