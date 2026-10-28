"""The case's one next hearing (design `next-date-direct`, decisions 4 to 8, 12 and 14): one server-made value that the
case header, the rail, every list, the calendar, the alerts and the Case Assistant read.

`compute(session, case_ids, today=...)` gives, for each live case (T = today in IST, O = the latest `order_date` of
the case's orders, or none):
1. the court's record — the earliest date d ≥ T and d > O among `cases.next_hearing_date` (NAPIX `date_next_list`)
   and the case's current cause-list listings: basis `court`, exact (d > O strictly: on the day an order is passed,
   NAPIX and that day's list still show the hearing just held);
2. else the latest order's reading — the latest (`created_at`, then `id`) `order_specific` / `order_period` row among
   `not_needed`, `pending` and `confirmed`, used when its date is ≥ T: basis `order` (`list_on_date`), `around`
   (periods, qualified and returnable dates) or `confirmed` (a row a person confirmed before this item);
3. else the court's last given date, passed (owner, 28 Oct 2026: court dates are ultimatums) — a court date after O
   but before T, else a dated reading of the latest order before T, with its own basis;
4. else the latest open `manual` row dated ≥ T: basis `manual`;
5. else none.
The discrepancy flag (decision 5): basis `court` and an exact (`order` / `confirmed`) reading of step 2 that gives a
different date.

`refresh` stores the value in the six derived columns of `cases` (never `next_hearing_date`, the court's verbatim
value), supersedes and audits open manual rows a court-given date outranks (decision 7) and emits
`next_date_differs` when the flag appears. Court information only: nothing here calls NAPIX, SourceTrace or any AI;
the value is read by everyone who may see the case (decision 14)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from aslms.core import clock
from aslms.domain.alerts import Alert, AlertStatus, NextDate, NextDateSource, ReviewStatus
from aslms.domain.cases import COURT_GIVEN_BASES, Case, NextHearingBasis
from aslms.domain.causelists import CURRENT_LIST, Causelist, CauselistEntry
from aslms.domain.documents import Order
from aslms.domain.reference import AlertKind, EventType
from aslms.services import next_date_rules as rules
from aslms.services.audit import Actor, write_audit

log = logging.getLogger(__name__)

FAILURE_KIND = "next_hearing_refresh"
DEFAULT_BATCH = 5000
CHUNK = 500  # cases locked and written per statement in the batch paths
ORDER_SOURCES = (NextDateSource.ORDER_SPECIFIC, NextDateSource.ORDER_PERIOD)
OPEN_REVIEW = (ReviewStatus.NOT_NEEDED, ReviewStatus.PENDING, ReviewStatus.CONFIRMED)
EXACT_BASES = (NextHearingBasis.ORDER, NextHearingBasis.CONFIRMED)
COLUMNS = (
    "next_hearing_on",
    "next_hearing_basis",
    "next_hearing_next_date_id",
    "next_hearing_differs_on",
    "next_hearing_differs_id",
    "next_hearing_set_at",
)
SYSTEM_ACTOR = "next_hearing"


@dataclass(frozen=True)
class NextHearing:
    date: date
    basis: NextHearingBasis
    next_date_id: uuid.UUID | None = None
    differs_on: date | None = None
    differs_id: uuid.UUID | None = None

    @property
    def court_given(self) -> bool:
        return self.basis in COURT_GIVEN_BASES


@dataclass
class RefreshResult:
    refreshed: int = 0
    changed: int = 0
    differs_set: int = 0
    differs_cleared: int = 0
    manual_superseded: int = 0
    skipped_locked: int = 0
    values: dict[uuid.UUID, NextHearing | None] = field(default_factory=dict)

    def counters(self) -> dict[str, int]:
        return {
            "refreshed": self.refreshed,
            "changed": self.changed,
            "differs_set": self.differs_set,
            "differs_cleared": self.differs_cleared,
            "manual_superseded": self.manual_superseded,
            "skipped_locked": self.skipped_locked,
        }

    def add(self, other: RefreshResult) -> None:
        for name in (
            "refreshed",
            "changed",
            "differs_set",
            "differs_cleared",
            "manual_superseded",
            "skipped_locked",
        ):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.values.update(other.values)


@dataclass(frozen=True)
class _Reading:
    id: uuid.UUID
    date: date
    basis: NextHearingBasis
    order_date: date | None


def _now() -> datetime:
    return datetime.now(UTC)


def _ids(case_ids: Iterable[Any]) -> list[uuid.UUID]:
    return sorted(
        dict.fromkeys(i if isinstance(i, uuid.UUID) else uuid.UUID(str(i)) for i in case_ids if i is not None)
    )


def reading_basis(source: Any, review_status: Any, rule: str | None) -> NextHearingBasis:
    """Decision 1: `confirmed` for a row a person confirmed; `order` for a plain written date (`list_on_date`);
    `around` for periods, qualified and returnable dates."""
    if ReviewStatus(review_status) == ReviewStatus.CONFIRMED:
        return NextHearingBasis.CONFIRMED
    if rule == rules.LIST_ON_DATE:
        return NextHearingBasis.ORDER
    if rule in rules.AROUND_RULES:
        return NextHearingBasis.AROUND
    return (
        NextHearingBasis.ORDER
        if NextDateSource(source) == NextDateSource.ORDER_SPECIFIC
        else NextHearingBasis.AROUND
    )


# ------------------------------------------------------------------------------------------------ compute


def compute(
    session: Session, case_ids: Iterable[Any], *, today: date | None = None
) -> dict[uuid.UUID, NextHearing | None]:
    """Decisions 4 and 5 for the given cases in five set-based queries, merged in Python. Merged cases get None."""
    today = today or clock.today_ist()
    ids = _ids(case_ids)
    if not ids:
        return {}
    court = {
        cid: nhd
        for cid, nhd in session.execute(
            select(Case.id, Case.next_hearing_date).where(
                Case.id.in_(ids), Case.merged_into_case_id.is_(None)
            )
        ).all()
    }
    latest_order = (
        select(Order.case_id.label("case_id"), func.max(Order.order_date).label("o"))
        .where(Order.case_id.in_(ids))
        .group_by(Order.case_id)
        .subquery("latest_order")
    )
    orders = {cid: o for cid, o in session.execute(select(latest_order.c.case_id, latest_order.c.o)).all()}
    listings = {
        cid: (ahead, passed)
        for cid, ahead, passed in session.execute(
            select(
                CauselistEntry.case_id,
                func.min(Causelist.list_date).filter(Causelist.list_date >= today),
                func.max(Causelist.list_date).filter(Causelist.list_date < today),
            )
            .join(Causelist, Causelist.id == CauselistEntry.causelist_id)
            .outerjoin(latest_order, latest_order.c.case_id == CauselistEntry.case_id)
            .where(
                CauselistEntry.case_id.in_(ids),
                CURRENT_LIST,
                or_(latest_order.c.o.is_(None), Causelist.list_date > latest_order.c.o),
            )
            .group_by(CauselistEntry.case_id)
        ).all()
    }
    readings: dict[uuid.UUID, _Reading] = {}
    for row_id, cid, d, source, status, rule, order_date in session.execute(
        select(
            NextDate.id,
            NextDate.case_id,
            NextDate.next_date,
            NextDate.source,
            NextDate.review_status,
            Order.next_date_rule,
            Order.order_date,
        )
        .outerjoin(Order, Order.id == NextDate.order_id)
        .where(
            NextDate.case_id.in_(ids),
            NextDate.source.in_(ORDER_SOURCES),
            NextDate.review_status.in_(OPEN_REVIEW),
        )
        .ext(distinct_on(NextDate.case_id))
        .order_by(NextDate.case_id, NextDate.created_at.desc(), NextDate.id.desc())
    ).all():
        readings[cid] = _Reading(row_id, d, reading_basis(source, status, rule), order_date)
    manual = {
        cid: (row_id, d)
        for row_id, cid, d in session.execute(
            select(NextDate.id, NextDate.case_id, NextDate.next_date)
            .where(
                NextDate.case_id.in_(ids),
                NextDate.source == NextDateSource.MANUAL,
                NextDate.review_status.in_(OPEN_REVIEW),
                NextDate.next_date >= today,
            )
            .ext(distinct_on(NextDate.case_id))
            .order_by(NextDate.case_id, NextDate.created_at.desc(), NextDate.id.desc())
        ).all()
    }
    out: dict[uuid.UUID, NextHearing | None] = {}
    for cid in ids:
        if cid not in court:
            out[cid] = None
            continue
        out[cid] = _merge(
            today,
            nhd=court[cid],
            o=orders.get(cid),
            listing=listings.get(cid, (None, None)),
            reading=readings.get(cid),
            manual=manual.get(cid),
        )
    return out


def _merge(
    today: date,
    *,
    nhd: date | None,
    o: date | None,
    listing: tuple[date | None, date | None],
    reading: _Reading | None,
    manual: tuple[uuid.UUID, date] | None,
) -> NextHearing | None:
    def after_order(d: date | None) -> bool:
        return d is not None and (o is None or d > o)

    ahead = [d for d in (nhd, listing[0]) if after_order(d) and d >= today]
    reading_ahead = reading if reading is not None and reading.date >= today else None
    if ahead:
        d = min(ahead)
        if reading_ahead is not None and reading_ahead.basis in EXACT_BASES and reading_ahead.date != d:
            return NextHearing(d, NextHearingBasis.COURT, None, reading_ahead.date, reading_ahead.id)
        return NextHearing(d, NextHearingBasis.COURT)
    if reading_ahead is not None:
        return NextHearing(reading_ahead.date, reading_ahead.basis, reading_ahead.id)
    passed = [d for d in (nhd, listing[1]) if after_order(d) and d < today]
    if passed:
        return NextHearing(max(passed), NextHearingBasis.COURT)
    if reading is not None and reading.order_date is not None and reading.order_date == o:
        return NextHearing(reading.date, reading.basis, reading.id)
    if manual is not None:
        return NextHearing(manual[1], NextHearingBasis.MANUAL, manual[0])
    return None


def court_given(session: Session, case: Case | uuid.UUID, *, today: date | None = None) -> bool:
    """Decision 6: recomputed for the one case (never the stored column); basis `court`, `order`, `around` or
    `confirmed`."""
    case_id = case if isinstance(case, uuid.UUID) else case.id
    session.flush()
    value = compute(session, [case_id], today=today).get(case_id)
    return value is not None and value.court_given


# ------------------------------------------------------------------------------------------------ refresh


def _stored(session: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple]:
    return {
        r[0]: tuple(r[1:])
        for r in session.execute(
            select(
                Case.id,
                Case.next_hearing_on,
                Case.next_hearing_basis,
                Case.next_hearing_next_date_id,
                Case.next_hearing_differs_on,
                Case.next_hearing_differs_id,
            ).where(Case.id.in_(ids))
        ).all()
    }


def _as_tuple(v: NextHearing | None) -> tuple:
    if v is None:
        return (None, None, None, None, None)
    return (v.date, v.basis, v.next_date_id, v.differs_on, v.differs_id)


def _expire_cached(session: Session, ids: Iterable[uuid.UUID]) -> None:
    for cid in ids:
        cached = session.identity_map.get(session.identity_key(Case, cid))
        if cached is not None:
            session.expire(cached, list(COLUMNS))


def refresh(
    session: Session,
    case_ids: Iterable[Any],
    *,
    today: date | None = None,
    actor: Actor | None = None,
    skip_locked: bool = False,
) -> RefreshResult:
    """Locks the cases in id order (`FOR UPDATE`; with `skip_locked` a case another transaction holds is left for a
    later run), computes, writes the six columns (`next_hearing_set_at` always), supersedes and audits the open manual
    rows a court-given date outranks (decision 7) and emits `next_date_differs` when the flag appears (decision 5)."""
    today = today or clock.today_ist()
    result = RefreshResult()
    ids = _ids(case_ids)
    if not ids:
        return result
    session.flush()
    for start in range(0, len(ids), CHUNK):
        result.add(_refresh_chunk(session, ids[start : start + CHUNK], today, actor, skip_locked))
    return result


def _refresh_chunk(
    session: Session, ids: list[uuid.UUID], today: date, actor: Actor | None, skip_locked: bool
) -> RefreshResult:
    result = RefreshResult()
    locked = list(
        session.scalars(
            select(Case.id).where(Case.id.in_(ids)).order_by(Case.id).with_for_update(skip_locked=skip_locked)
        ).all()
    )
    result.skipped_locked = len(ids) - len(locked)
    if not locked:
        return result
    before = _stored(session, locked)
    values = compute(session, locked, today=today)
    now = _now()
    params = []
    for cid in locked:
        new = values.get(cid)
        old = before.get(cid, (None,) * 5)
        new_t = _as_tuple(new)
        if new_t != tuple(old):
            result.changed += 1
        if new_t[3] is not None and (old[3], old[4]) != (new_t[3], new_t[4]):
            result.differs_set += 1
        elif new_t[3] is None and old[3] is not None:
            result.differs_cleared += 1
        params.append(
            {
                "id": cid,
                "next_hearing_on": new_t[0],
                "next_hearing_basis": new_t[1],
                "next_hearing_next_date_id": new_t[2],
                "next_hearing_differs_on": new_t[3],
                "next_hearing_differs_id": new_t[4],
                "next_hearing_set_at": now,
            }
        )
    session.execute(update(Case), params, execution_options={"synchronize_session": False})
    _expire_cached(session, locked)
    result.refreshed = len(locked)
    result.values = values
    given = [cid for cid in locked if values.get(cid) is not None and values[cid].court_given]
    if given:
        result.manual_superseded = _supersede_manual(session, given, values, actor)
    for cid in locked:
        new = values.get(cid)
        old = before.get(cid, (None,) * 5)
        if (
            new is not None
            and new.differs_on is not None
            and (old[3], old[4]) != (new.differs_on, new.differs_id)
        ):
            _differs_event(session, cid, new)
    session.flush()
    return result


def _supersede_manual(
    session: Session,
    case_ids: list[uuid.UUID],
    values: dict[uuid.UUID, NextHearing | None],
    actor: Actor | None,
) -> int:
    """Decision 7: open manual rows of cases that now have a court-given date → `superseded` (system closure,
    `updated_by` NULL), one audit row each (never the note text)."""
    rows = list(
        session.scalars(
            select(NextDate)
            .where(
                NextDate.case_id.in_(case_ids),
                NextDate.source == NextDateSource.MANUAL,
                NextDate.review_status.in_(OPEN_REVIEW),
            )
            .order_by(NextDate.case_id, NextDate.created_at, NextDate.id)
            .with_for_update()
        ).all()
    )
    if not rows:
        return 0
    actor = actor or Actor.system(SYSTEM_ACTOR)
    order_refs = _order_refs(session, {values[r.case_id].next_date_id for r in rows if values[r.case_id]})
    for row in rows:
        value = values[row.case_id]
        before = {
            "next_date": row.next_date,
            "source": NextDateSource(row.source).value,
            "review_status": ReviewStatus(row.review_status).value,
            "order_id": row.order_id,
            "ref_no": row.ref_no,
        }
        row.review_status = ReviewStatus.SUPERSEDED
        row.updated_by = None
        session.flush()
        replaced_by: dict[str, Any] = {"basis": value.basis.value, "date": value.date}
        if value.basis == NextHearingBasis.COURT:
            replaced_by["court_date"] = value.date
        else:
            replaced_by["next_date_id"] = value.next_date_id
            replaced_by["order"] = order_refs.get(value.next_date_id)
        write_audit(
            session,
            actor,
            "next_date.superseded_by_court",
            "next_date",
            row.id,
            case_id=row.case_id,
            before=before,
            after={**before, "review_status": ReviewStatus.SUPERSEDED.value, "replaced_by": replaced_by},
        )
    return len(rows)


def _order_refs(session: Session, next_date_ids: set[uuid.UUID | None]) -> dict[uuid.UUID, dict[str, Any]]:
    ids = [i for i in next_date_ids if i is not None]
    if not ids:
        return {}
    return {
        nd_id: {"order_id": oid, "order_no": no, "order_date": od}
        for nd_id, oid, no, od in session.execute(
            select(NextDate.id, Order.id, Order.order_no, Order.order_date)
            .join(Order, Order.id == NextDate.order_id)
            .where(NextDate.id.in_(ids))
        ).all()
    }


def _differs_event(session: Session, case_id: uuid.UUID, value: NextHearing) -> None:
    from aslms.services.cases import emit_event

    case = session.get(Case, case_id)
    ref = _order_refs(session, {value.differs_id}).get(value.differs_id, {})
    emit_event(
        session,
        EventType.NEXT_DATE_DIFFERS,
        case,
        {
            "court_date": value.date,
            "order_next_date": value.differs_on,
            "next_date_id": str(value.differs_id),
            "order_id": str(ref.get("order_id")) if ref.get("order_id") else None,
            "order_no": ref.get("order_no"),
            "order_date": ref.get("order_date"),
        },
        dedupe=f"next_date_differs:{case_id}:{value.date}:{ref.get('order_date') or value.differs_on}",
    )


def refresh_after_court_change(session: Session, case_ids: Iterable[Any]) -> RefreshResult | None:
    """The court's record for these cases may have changed (a dossier, Current Status, a cause list, a merge):
    refresh inside a savepoint. A failure is recorded in `source_failures` (kind `next_hearing_refresh`, ref the case
    id) and never fails the court data; `refresh_due` retries it within five minutes."""
    ids = _ids(case_ids)
    if not ids:
        return None
    try:
        with session.begin_nested():
            return refresh(session, ids)
    except Exception as exc:  # noqa: BLE001 - the next hearing never fails the court data
        log.exception("next-hearing refresh failed for %d case(s)", len(ids))
        from aslms.services import source_failures

        for cid in ids:
            try:
                with session.begin_nested():
                    source_failures.record(
                        session, FAILURE_KIND, str(cid), f"{exc.__class__.__name__}: {exc}"[:2000]
                    )
            except Exception:  # noqa: BLE001
                log.exception("next-hearing failure not recorded")
        return None


def _resolve_failures(session: Session, ids: Iterable[uuid.UUID]) -> None:
    refs = [str(i) for i in ids]
    if refs:
        session.execute(
            sql_text(
                "UPDATE source_failures SET resolved_at = now() "
                "WHERE kind = :k AND ref = ANY(:r) AND resolved_at IS NULL"
            ),
            {"k": FAILURE_KIND, "r": refs},
        )


def rollover_condition(today: date):
    """Cases whose stored value may change with time alone: a date that has passed since it was computed (a value
    already passed when computed is stable), or a differing order date that has passed."""
    set_day = func.date(func.timezone("Asia/Kolkata", Case.next_hearing_set_at))
    return or_(
        and_(Case.next_hearing_on < today, Case.next_hearing_on >= set_day),
        Case.next_hearing_differs_on < today,
    )


def refresh_due(session: Session, *, today: date | None = None, batch: int = DEFAULT_BATCH) -> dict[str, int]:
    """The 5-minute job's part (Jobs): rollovers, cases with an unresolved `next_hearing_refresh` failure, then up to
    `batch` cases never computed (backfill). Case locks taken with `SKIP LOCKED`."""
    today = today or clock.today_ist()
    batch = max(1, int(batch))
    live = Case.merged_into_case_id.is_(None)
    rolled = list(
        session.scalars(
            select(Case.id)
            .where(live, Case.next_hearing_set_at.is_not(None), rollover_condition(today))
            .order_by(Case.next_hearing_set_at, Case.id)
            .limit(batch)
        ).all()
    )
    failed = [
        uuid.UUID(r)
        for r in session.scalars(
            sql_text(
                "SELECT DISTINCT ref FROM source_failures WHERE kind = :k AND resolved_at IS NULL LIMIT :n"
            ).bindparams(k=FAILURE_KIND, n=batch)
        ).all()
        if _is_uuid(r)
    ]
    first = refresh(session, [*rolled, *failed], today=today, skip_locked=True)
    _resolve_failures(session, [i for i in failed if i in first.values])
    unset = list(
        session.scalars(
            select(Case.id).where(live, Case.next_hearing_set_at.is_(None)).order_by(Case.id).limit(batch)
        ).all()
    )
    second = refresh(session, unset, today=today, skip_locked=True)
    return {
        "hearing_refreshed": first.refreshed,
        "hearing_backfilled": second.refreshed,
        "hearing_changed": first.changed + second.changed,
        "hearing_manual_superseded": first.manual_superseded + second.manual_superseded,
    }


def _is_uuid(v: Any) -> bool:
    try:
        uuid.UUID(str(v))
    except ValueError:
        return False
    return True


def refresh_all(
    session: Session,
    *,
    today: date | None = None,
    case_id: uuid.UUID | None = None,
    page: int = DEFAULT_BATCH,
) -> RefreshResult:
    """`aslms next-dates hearing-refresh --all | --case`: every live case (keyset pages), or one."""
    today = today or clock.today_ist()
    total = RefreshResult()
    if case_id is not None:
        total.add(refresh(session, [case_id], today=today))
        total.values = {}
        return total
    last: uuid.UUID | None = None
    while True:
        stmt = select(Case.id).where(Case.merged_into_case_id.is_(None)).order_by(Case.id).limit(page)
        if last is not None:
            stmt = stmt.where(Case.id > last)
        ids = list(session.scalars(stmt).all())
        if not ids:
            break
        part = refresh(session, ids, today=today)
        part.values = {}
        total.add(part)
        last = ids[-1]
    return total


def preview_all(session: Session, *, today: date | None = None, page: int = DEFAULT_BATCH) -> dict[str, int]:
    """The dry run of `hearing-refresh`: how many live cases would change, by new basis; writes nothing."""
    today = today or clock.today_ist()
    out: dict[str, int] = {"cases": 0, "would_change": 0}
    last: uuid.UUID | None = None
    while True:
        stmt = select(Case.id).where(Case.merged_into_case_id.is_(None)).order_by(Case.id).limit(page)
        if last is not None:
            stmt = stmt.where(Case.id > last)
        ids = list(session.scalars(stmt).all())
        if not ids:
            break
        before = _stored(session, ids)
        values = compute(session, ids, today=today)
        for cid in ids:
            out["cases"] += 1
            v = values.get(cid)
            key = f"basis_{v.basis.value}" if v is not None else "basis_none"
            out[key] = out.get(key, 0) + 1
            if _as_tuple(v) != tuple(before.get(cid, (None,) * 5)):
                out["would_change"] += 1
        last = ids[-1]
    return out


def status_counts(session: Session) -> dict[str, int]:
    """`aslms next-dates status`: live cases by stored basis, the flagged count and the cases never computed."""
    live = Case.merged_into_case_id.is_(None)
    out = {
        (b.value if b is not None else "none"): int(n)
        for b, n in session.execute(
            select(Case.next_hearing_basis, func.count())
            .where(live, Case.next_hearing_set_at.is_not(None))
            .group_by(Case.next_hearing_basis)
        ).all()
    }
    out["differs"] = int(
        session.scalar(select(func.count()).where(live, Case.next_hearing_differs_on.is_not(None))) or 0
    )
    out["unset"] = int(
        session.scalar(select(func.count()).where(live, Case.next_hearing_set_at.is_(None))) or 0
    )
    return out


# ------------------------------------------------------------------------------------------------ the API shape


def _value(v: Any) -> Any:
    return v.value if hasattr(v, "value") else v


def _order_out(order: Order | None) -> dict[str, Any] | None:
    if order is None:
        return None
    return {
        "id": order.id,
        "order_no": order.order_no,
        "order_date": order.order_date,
        "document_id": order.document_id,
    }


def outs(
    session: Session, cases: list[Case], *, detail: bool = False, today: date | None = None
) -> dict[uuid.UUID, dict[str, Any] | None]:
    """`NextHearingOut` for each case (list form; `detail` adds `phrase`, `court_date` and `reported_at`), from the
    stored columns in one query for the rows and orders of a page. A case never computed (the backfill has not
    reached it) is computed on the spot, without writing."""
    today = today or clock.today_ist()
    if not cases:
        return {}
    values: dict[uuid.UUID, NextHearing | None] = {}
    unset = [c.id for c in cases if c.next_hearing_set_at is None]
    live = compute(session, unset, today=today) if unset else {}
    for c in cases:
        if c.next_hearing_set_at is None:
            values[c.id] = live.get(c.id)
        elif c.next_hearing_on is None:
            values[c.id] = None
        else:
            values[c.id] = NextHearing(
                c.next_hearing_on,
                NextHearingBasis(c.next_hearing_basis),
                c.next_hearing_next_date_id,
                c.next_hearing_differs_on,
                c.next_hearing_differs_id,
            )
    row_ids = {
        i for v in values.values() if v is not None for i in (v.next_date_id, v.differs_id) if i is not None
    }
    rows = (
        {r.id: r for r in session.scalars(select(NextDate).where(NextDate.id.in_(row_ids))).all()}
        if row_ids
        else {}
    )
    order_ids = {r.order_id for r in rows.values() if r.order_id is not None}
    orders = (
        {o.id: o for o in session.scalars(select(Order).where(Order.id.in_(order_ids))).all()}
        if order_ids
        else {}
    )
    reported = (
        _reported_at(
            session,
            [i for v in values.values() if v is not None for i in (v.next_date_id, v.differs_id) if i],
        )
        if detail
        else {}
    )
    out: dict[uuid.UUID, dict[str, Any] | None] = {}
    for c in cases:
        v = values.get(c.id)
        if v is None:
            out[c.id] = None
            continue
        row = rows.get(v.next_date_id) if v.next_date_id else None
        order = orders.get(row.order_id) if row is not None and row.order_id else None
        item: dict[str, Any] = {
            "date": v.date,
            "basis": v.basis.value,
            "approximate": v.basis == NextHearingBasis.AROUND,
            "basis_words": (
                rules.describe(order.next_date_rule, order.next_date_phrase, order.order_date, row.next_date)
                if order is not None and v.basis == NextHearingBasis.AROUND
                else None
            ),
            "order": _order_out(order),
            "rule": order.next_date_rule if order is not None else None,
            "differs": None,
        }
        if v.differs_id is not None:
            drow = rows.get(v.differs_id)
            dorder = orders.get(drow.order_id) if drow is not None and drow.order_id else None
            item["differs"] = {"date": v.differs_on, "order": _order_out(dorder)}
        if detail:
            phrase_order = order
            if phrase_order is None and v.differs_id is not None:
                drow = rows.get(v.differs_id)
                phrase_order = orders.get(drow.order_id) if drow is not None and drow.order_id else None
            item["phrase"] = phrase_order.next_date_phrase if phrase_order is not None else None
            item["court_date"] = c.next_hearing_date
            item["reported_at"] = reported.get(v.next_date_id) or (
                reported.get(v.differs_id) if v.differs_id else None
            )
        out[c.id] = item
    return out


def _reported_at(session: Session, next_date_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
    """The open `next_date_reported` alerts of these rows (decision 17: "Reported as possibly wrong on <date>")."""
    if not next_date_ids:
        return {}
    out: dict[uuid.UUID, datetime] = {}
    for key, created in session.execute(
        select(Alert.dedupe_key, Alert.created_at).where(*open_report_alerts(next_date_ids))
    ).all():
        out[report_alert_row_id(key)] = created
    return out


def report_alert_key(next_date_id: uuid.UUID | str, n: int = 1) -> str:
    """Decision 17: `next_date_reported:<next_date id>` for the first report of a reading; a later report, after
    the earlier one was closed (kept, corrected elsewhere, expired), takes `:<n>` (n = 2, 3, ...) because
    `alerts.dedupe_key` is unique across every status (Deviation 16)."""
    base = f"{AlertKind.NEXT_DATE_REPORTED.value}:{next_date_id}"
    return base if n <= 1 else f"{base}:{n}"


def report_alert_row_id(key: str) -> uuid.UUID:
    return uuid.UUID(key.split(":")[1])


def open_report_alerts(next_date_ids: Iterable[uuid.UUID | str]) -> list[Any]:
    """The WHERE terms of the open `next_date_reported` alerts of these rows, whatever their key's number."""
    ids = [str(i) for i in next_date_ids]
    return [
        Alert.kind == AlertKind.NEXT_DATE_REPORTED,
        Alert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]),
        func.split_part(Alert.dedupe_key, ":", 2).in_(ids),
    ]


PRIVATE_BASES = (NextHearingBasis.MANUAL.value, NextHearingBasis.CONFIRMED.value)


def court_public(out: dict[str, Any] | None) -> dict[str, Any] | None:
    """The next hearing as it may be shown on a row the caller cannot open (search, cause lists, links, discovery,
    the Assistant's court-record view): only the tiers read from the court's own record and order text. A date
    entered by hand (`manual`) or a reading a person confirmed (`confirmed`) is a department's record and is
    blanked; the discrepancy flag and the report mark are dropped (Deviation 15)."""
    if not out or out.get("basis") in PRIVATE_BASES:
        return None
    clean = {**out, "differs": None}
    if "reported_at" in clean:
        clean["reported_at"] = None
    return clean


def next_hearing_out(session: Session, case: Case, *, detail: bool = False) -> dict[str, Any] | None:
    return outs(session, [case], detail=detail).get(case.id)


def describe_case(session: Session, case: Case) -> dict[str, Any] | None:
    """The detail form for one case (the Case Assistant's reader, decision 11)."""
    return next_hearing_out(session, case, detail=True)


def plain(d: date | None) -> str:
    return d.strftime("%d %b %Y") if d is not None else "?"


def words(out: dict[str, Any] | None) -> str:
    """One plain line for the Assistant and alert texts: "Around 11 Mar 2026 (after 3 weeks, order of 18 Feb 2026)",
    "25 Nov 2026 (court's records)", "20 Nov 2026 (order of 12 Oct 2026)", "No next hearing known"."""
    if not out:
        return "No next hearing known"
    d = out.get("date")
    d = date.fromisoformat(d) if isinstance(d, str) else d
    basis = out.get("basis")
    order = out.get("order") or {}
    od = order.get("order_date")
    od = date.fromisoformat(od) if isinstance(od, str) else od
    if basis == NextHearingBasis.COURT.value:
        return f"{plain(d)} (court's records)"
    if basis == NextHearingBasis.AROUND.value:
        bits = [b for b in (out.get("basis_words"), f"order of {plain(od)}" if od else None) if b]
        return f"Around {plain(d)}" + (f" ({', '.join(bits)})" if bits else "")
    if basis in (NextHearingBasis.ORDER.value, NextHearingBasis.CONFIRMED.value):
        return f"{plain(d)} (order of {plain(od)})" if od else f"{plain(d)} (from an order)"
    if basis == NextHearingBasis.MANUAL.value:
        return f"{plain(d)} (entered by hand; the court has given no date)"
    return plain(d)
