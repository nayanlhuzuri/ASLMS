"""Next dates from orders (design `next-date-extraction`): the reader, the review queue, confirm / reject and manual
next dates (`NXT`).

- The reader (decisions 4-6, 8, 14, 16): `read_pending` takes pending orders whose document text is extracted (or
  known to be absent), oldest first; per order (one savepoint) it takes the case row lock, re-reads the order
  `FOR UPDATE`, reads the stored text by rule (`next_date_rules`), records the reading on the order and, only for the
  case's current order with a date today or later, writes a `next_dates` row (`order_specific` / `order_period`)
  and supersedes the case's other pending rows; a current order without a usable date supersedes the open rows of
  older orders instead (Deviation 11).
- Firm only when two sources agree (the owner's second decision of 17 Oct 2026, option B): a row is `not_needed`
  only when its date equals the court's own date for the case (`cases.next_hearing_date`, or a cause-list entry of
  the case on that date); every other reading is `pending` for a person to confirm. `match_court_dates` closes a
  pending row as soon as a matching court date arrives (system closure to `not_needed`, `needs_review` kept true,
  no reviewer; its review alert closed `done`, reason `matched`): at every reader run, and from the dossier,
  Current Status and cause-list paths through `match_after_court_change`.
  It emits `next_date_extracted` for every row and for every *enter* item. Pending rows whose date passed expire.
  The reading is system work: no audit row (recorded in `job_runs` and the events); failures go to
  `source_failures` (kind `next_date_read`). Court text only: nothing is sent to SourceTrace, NAPIX or any AI.
- The queue (decisions 7, 10, 17): *confirm* items (pending rows) and *enter* items (an `unclear` / `no_text` current
  order dated within `NEXT_DATE_UNCLEAR_DAYS`, with no manual date since it was read), only for claimed cases, only
  where a membership holding `next_dates.review` has a working basis.
- Writes (decisions 10-12, 15): `confirm`, `reject` (with an optional replacement date) and `enter` take the case
  row lock, need the function, a visible case, a claim and a working basis in the same membership; they close the
  order's review alert, emit `next_date_reviewed` / `next_date_entered` and audit `next_date.*` (the note's length
  and hash, never its text).
- Reads (decisions 9, 18): `effective_for_case` (the latest manual / order row among not-needed, pending and
  confirmed, used only when it is not pending), `case_next_dates`, `next_date_out`."""

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
    cast,
    exists,
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
from aslms.domain.cases import Case
from aslms.domain.causelists import CURRENT_LIST, Causelist, CauselistEntry
from aslms.domain.documents import Document, DocumentText, Order, OrderNextDateStatus, TextStatus
from aslms.domain.ops import JobRun, JobStatus
from aslms.domain.org import Office, User
from aslms.domain.ownership import CaseOwnership, OwnershipRole, OwnershipStatus
from aslms.domain.reference import AlertKind, EventType, Permission, RecordType
from aslms.services import access, calendar, case_filters, visibility
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
ENTER_STATUSES = (OrderNextDateStatus.UNCLEAR, OrderNextDateStatus.NO_TEXT)
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


def queue_subquery(
    session: Session,
    case_condition: ColumnElement[bool],
    *,
    today: date,
    cfg: NextDateConfig,
    kind: str | None = None,
    filters: CaseFilters | None = None,
):
    """Decision 7: the union of *confirm* rows and *enter* orders as (kind, id, case_id, order_id, act_by,
    next_date) over live claimed cases matching `case_condition` and the shared case filters."""
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
            )
            .join(Case, Case.id == NextDate.case_id)
            .where(NextDate.review_status == ReviewStatus.PENDING, NextDate.next_date >= today, *base)
        )
    if kind in (None, "enter"):
        manual_since = answered_condition()
        parts.append(
            select(
                literal("enter").label("kind"),
                Order.id.label("id"),
                Order.case_id.label("case_id"),
                Order.id.label("order_id"),
                (Order.order_date + literal(cfg.unclear_days)).label("act_by"),
                cast(null(), Date).label("next_date"),
            )
            .join(Case, Case.id == Order.case_id)
            .where(
                Order.next_date_status.in_(ENTER_STATUSES),
                Order.order_date >= today - timedelta(days=cfg.unclear_days),
                current_order_condition(),
                ~manual_since,
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
        # firm only when the court's own date agrees (owner's second decision of 17 Oct 2026, point 1)
        firm = court_date_matches(session, case.id, reading.date)
        status = ReviewStatus.NOT_NEEDED if firm else ReviewStatus.PENDING
        new_id = session.execute(
            pg_insert(NextDate.__table__)
            .values(
                case_id=case.id,
                next_date=reading.date,
                source=source.value,
                order_id=order.id,
                confidence=reading.confidence,
                needs_review=not firm,
                review_status=status.value,
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
            if firm and ReviewStatus(row.review_status) == ReviewStatus.PENDING:  # read again after a reread
                row.review_status = ReviewStatus.NOT_NEEDED
                counters["matched"] = counters.get("matched", 0) + 1
        counters["superseded"] = counters.get("superseded", 0) + supersede(session, case.id, keep=row.id)
        review = ReviewStatus(row.review_status) == ReviewStatus.PENDING
        if review:
            counters["review_items"] = counters.get("review_items", 0) + 1
        _extracted_event(session, case, order, reading, row, review)
    else:
        # the latest order gives no date to use: the dates of older orders stop (Deviation 11)
        counters["superseded"] = counters.get("superseded", 0) + supersede_older(session, order)
        if (
            reading.status in (rules.UNCLEAR, rules.NO_TEXT)
            and order.order_date >= today - timedelta(days=cfg.unclear_days)
            and not _answered(session, order)
        ):
            counters["review_items"] = counters.get("review_items", 0) + 1
            _extracted_event(session, case, order, reading, None, True)
    session.flush()
    return reading.status


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
    result = session.execute(
        update(NextDate)
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
        .values(review_status=ReviewStatus.SUPERSEDED)
        .execution_options(synchronize_session="fetch")
    )
    return int(result.rowcount or 0)


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
    run.status = JobStatus.PARTIAL if counters["failed"] else JobStatus.SUCCEEDED
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
                case_id = session.scalar(select(Order.case_id).where(Order.id == oid))
                if court_date_matches(session, case_id, reading.date):
                    out["would_be_firm"] += 1
            elif (
                current
                and reading.status in (rules.UNCLEAR, rules.NO_TEXT)
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
        select(q.c.kind, q.c.id, q.c.case_id, q.c.order_id, q.c.act_by, q.c.next_date)
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
    actor = access.actor_as(actor, member)
    row = _insert_manual(session, actor, member, case, next_date=next_date, note=text_, order_id=oid)
    close_moot_review_alerts(session, case.id, "entered", actor_user_id=actor.user_id, cfg=cfg)
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
    """Decision 9: the latest manual / order row among not-needed, pending and confirmed; None when it is pending."""
    case_id = case if isinstance(case, uuid.UUID) else case.id
    row = session.scalar(
        select(NextDate)
        .where(
            NextDate.case_id == case_id,
            NextDate.source.in_(EFFECTIVE_SOURCES),
            NextDate.review_status.in_(OPEN_REVIEW),
        )
        .order_by(NextDate.created_at.desc(), NextDate.id.desc())
        .limit(1)
    )
    if row is None or ReviewStatus(row.review_status) == ReviewStatus.PENDING:
        return None
    return row


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
