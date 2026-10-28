"""The Cause list screen (design `portal-causelist`): the dates with what is known about each, one day's benches
and lists in court order, the day's entries as published with the portal's own facts per row, and the original
cause-list PDF.

Read-only: nothing here writes a row, audits or calls NAPIX. The published list is court-public (decision 1), so
every stored row of the chosen date is returned to any reader of cases; what the portal adds on each row is scoped
on the server and computed in SQL for the page — `visible` (`visibility.visible_case_condition`), `in_pool`
(`visibility.never_owned`), `held_by_you` (one of the caller's departments holds an active row), the
recommendations the caller is shown (`ownership.shown_recommendations_condition`, decision 6) and `claimable`
(`ownership.claimable_condition`, decision 7). Nothing is filtered in Python."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Numeric,
    String,
    and_,
    case,
    cast,
    exists,
    false,
    func,
    literal,
    nulls_last,
    or_,
    select,
)
from sqlalchemy.orm import Session, aliased

from aslms.domain.cases import Case
from aslms.domain.causelists import CURRENT_LIST, Causelist, CauselistBenchDay, CauselistEntry, ListType
from aslms.domain.documents import DocKind, Document
from aslms.domain.ops import FetchKind, FetchQueueItem
from aslms.domain.ops import FetchStatus as QueueStatus
from aslms.domain.org import Office, User
from aslms.domain.ownership import (
    CaseOwnership,
    OwnershipRole,
    OwnershipStatus,
    Recommendation,
)
from aslms.domain.reference import Permission
from aslms.services import access, case_filters, inbox, queue
from aslms.services.access import Member
from aslms.services.audit_search import to_ist
from aslms.services.case_filters import CaseFilterError, ParsedQuery
from aslms.services.documents import ServedFile, serve_stored
from aslms.services.ownership import claimable_condition, shown_recommendations_condition
from aslms.services.reporting_common import today_ist
from aslms.services.storage import LocalStore
from aslms.services.visibility import never_owned, visible_case_condition

ORDER_OF_LIST_TYPE: tuple[str, ...] = (
    ListType.DAILY.value,
    ListType.SUPPLEMENTARY.value,
    ListType.LAWAZIMA.value,
    ListType.VACATION.value,
    ListType.OTHER.value,
)
LIST_TYPES = ORDER_OF_LIST_TYPE
ONLY_VALUES: tuple[str, ...] = ("recommended", "mine", "claimable", "unclaimed", "claimed", "visible")
DAY_STATES: tuple[str, ...] = ("held", "loading", "no_list", "failed", "not_loaded")
COUNT_NAMES: tuple[str, ...] = ("recommended", "mine", "claimable", "claimed", "unclaimed")
DEFAULT_LIMIT = 200
MAX_LIMIT = 500
MAX_RANGE_DAYS = 400
DEFAULT_BACK_DAYS = 60
DEFAULT_AHEAD_DAYS = 7
MAX_COURT_NO = case_filters.MAX_COURT_NO
MIN_QUERY = case_filters.MIN_QUERY
WORD_COLUMNS = (
    CauselistEntry.case_no_text,
    CauselistEntry.petitioner_text,
    CauselistEntry.respondent_text,
    CauselistEntry.pet_advocate_text,
    CauselistEntry.res_advocate_text,
)


class CauselistViewError(ValueError):
    """Bad input (HTTP 400 with the message)."""


class CauselistNotFound(LookupError):
    """No such cause list (HTTP 404)."""


class NotAllowed(PermissionError):
    """The caller lacks the read functions or the file function (HTTP 403)."""


class NoPdf(LookupError):
    """The list has no stored PDF (HTTP 404 `no_pdf` with the list's `fetch_status`)."""

    def __init__(self, fetch_status: str) -> None:
        super().__init__("the court's PDF of this cause list is not available")
        self.fetch_status = fetch_status


def _value(v: Any) -> Any:
    return v.value if hasattr(v, "value") else v


# ------------------------------------------------------------------------------------------------ ordering


def court_sort_key(court_no: str | None) -> tuple[bool, int, bool, str]:
    """Court numbers numerically (`2` before `10` before `111`), then as text, none last — the Python twin of
    `court_order_sql`."""
    text_ = court_no.strip() if court_no is not None else None
    digits = "".join(c for c in (text_ or "") if c.isdigit())
    number = int(digits) if digits else None
    return (number is None, number or 0, text_ is None, text_ or "")


def court_number_sql(col: Any) -> ColumnElement:
    """`NULLIF(regexp_replace(trim(court_no), '\\D', '', 'g'), '')::numeric` — the number in a court number."""
    return cast(
        func.nullif(func.regexp_replace(func.trim(col), r"\D", "", "g"), ""),
        Numeric,
    )


def court_order_sql(col: Any) -> list:
    return [nulls_last(court_number_sql(col).asc()), nulls_last(func.trim(col).asc())]


def list_type_rank(value: Any) -> int:
    v = _value(value)
    return ORDER_OF_LIST_TYPE.index(v) if v in ORDER_OF_LIST_TYPE else len(ORDER_OF_LIST_TYPE)


def list_type_rank_sql(col: Any) -> ColumnElement:
    return case(
        *[(cast(col, String) == v, i) for i, v in enumerate(ORDER_OF_LIST_TYPE)],
        else_=len(ORDER_OF_LIST_TYPE),
    )


def _list_key(cl: Causelist) -> tuple:
    n = cl.napix_causelist_id
    return (list_type_rank(cl.list_type), n is None, n or 0, str(cl.id))


# ------------------------------------------------------------------------------------------------ dates


def _queue_row(session: Session, list_date: date) -> FetchQueueItem | None:
    return queue.get_state(session, FetchKind.CAUSELIST_DAY, list_date.isoformat())


def _state_of(has_lists: bool, queue_status: Any) -> str:
    """Decision 4. A queue row done with nothing stored counts as `no_list` (deviation 2)."""
    if has_lists:
        return "held"
    if queue_status is None:
        return "not_loaded"
    status = QueueStatus(_value(queue_status))
    if status in (QueueStatus.PENDING, QueueStatus.RUNNING):
        return "loading"
    if status == QueueStatus.FAILED:
        return "failed"
    return "no_list"


def day_state(session: Session, list_date: date) -> tuple[str, FetchQueueItem | None]:
    """Decision 4: `held`, `loading`, `no_list`, `failed` or `not_loaded`, with the day's queue row."""
    has_lists = bool(session.scalar(select(exists().where(Causelist.list_date == list_date, CURRENT_LIST))))
    row = _queue_row(session, list_date)
    return _state_of(has_lists, row.status if row is not None else None), row


def _default_date(session: Session, today: date) -> date:
    """The first date on or after today with lists, else the latest date with lists, else today."""
    upcoming = session.scalar(
        select(func.min(Causelist.list_date)).where(Causelist.list_date >= today, CURRENT_LIST)
    )
    if upcoming is not None:
        return upcoming
    latest = session.scalar(select(func.max(Causelist.list_date)).where(CURRENT_LIST))
    return latest or today


def dates(
    session: Session,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """The dates of a range (default today − 60 to today + 7, IST; one bound alone spans 67 days) with lists or a `causelist_day` queue row,
    each with its state and its counts of lists, benches and stored entries; and the date the screen opens on."""
    today = today or today_ist()
    span = timedelta(days=DEFAULT_BACK_DAYS + DEFAULT_AHEAD_DAYS)
    if date_from is None and date_to is None:
        start, end = today - timedelta(days=DEFAULT_BACK_DAYS), today + timedelta(days=DEFAULT_AHEAD_DAYS)
    elif date_to is None:
        start, end = date_from, date_from + span
    elif date_from is None:
        start, end = date_to - span, date_to
    else:
        start, end = date_from, date_to
    if start > end:
        raise CauselistViewError("from is after to")
    if (end - start).days > MAX_RANGE_DAYS:
        raise CauselistViewError(f"the range is at most {MAX_RANGE_DAYS} days")
    stored = (
        select(CauselistEntry.causelist_id, func.count().label("n"))
        .group_by(CauselistEntry.causelist_id)
        .subquery()
    )
    lists = session.execute(
        select(Causelist.list_date, Causelist.id, Causelist.bench_id, func.coalesce(stored.c.n, 0))
        .outerjoin(stored, stored.c.causelist_id == Causelist.id)
        .where(Causelist.list_date >= start, Causelist.list_date <= end, CURRENT_LIST)
    ).all()
    bench_days = session.execute(
        select(CauselistBenchDay.list_date, CauselistBenchDay.bench_id).where(
            CauselistBenchDay.list_date >= start, CauselistBenchDay.list_date <= end
        )
    ).all()
    queue_rows = session.execute(
        select(FetchQueueItem.ref, FetchQueueItem.status).where(
            FetchQueueItem.kind == FetchKind.CAUSELIST_DAY,
            FetchQueueItem.ref >= start.isoformat(),
            FetchQueueItem.ref <= end.isoformat(),
        )
    ).all()
    per: dict[date, dict[str, Any]] = {}

    def slot(d: date) -> dict[str, Any]:
        return per.setdefault(d, {"lists": 0, "entries": 0, "benches": set(), "queue": None})

    for d, list_id, bench_id, n in lists:
        s = slot(d)
        s["lists"] += 1
        s["entries"] += int(n)
        s["benches"].add(("bench", bench_id) if bench_id is not None else ("list", list_id))
    for ref, status in queue_rows:
        try:
            d = date.fromisoformat(ref)
        except ValueError:
            continue
        slot(d)["queue"] = status
    for d, bench_id in bench_days:
        if d in per:
            per[d]["benches"].add(("bench", bench_id))
    items = [
        {
            "date": d,
            "state": _state_of(s["lists"] > 0, s["queue"]),
            "lists": s["lists"],
            "benches": len(s["benches"]),
            "entries": s["entries"],
        }
        for d, s in sorted(per.items())
    ]
    return {
        "from": start,
        "to": end,
        "today": today,
        "default_date": _default_date(session, today),
        "items": items,
    }


# ------------------------------------------------------------------------------------------------ one day


def _list_out(cl: Causelist, stored: int) -> dict[str, Any]:
    return {
        "id": cl.id,
        "list_type": _value(cl.list_type),
        "list_type_text": cl.list_type_text,
        "label": cl.label,
        "napix_causelist_id": cl.napix_causelist_id,
        "source": _value(cl.source),
        "entry_count": cl.entry_count,
        "entries_stored": stored,
        "fetch_status": _value(cl.fetch_status),
        "parse_status": _value(cl.parse_status),
        "has_pdf": cl.document_id is not None,
        # design court-data-freshness, decision 17: a corrected list and its earlier version
        "version": cl.version,
        "supersedes_id": cl.supersedes_id,
        "superseded_at": to_ist(cl.superseded_at),
        "superseded": cl.superseded_at is not None,
        "corrected_at": to_ist(cl.fetched_at) if (cl.version or 1) > 1 else None,
        "last_checked_at": to_ist(cl.last_checked_at),
    }


def day(session: Session, list_date: date) -> dict[str, Any]:
    """Decision 2: the benches that sat or published a list on the date — NAPIX lists grouped by bench, benches
    of `causelist_bench_days` without a list, each court-wide website file as a bench of its own — ordered by
    their smallest court number, then bench id; lists in type order, then NAPIX list id."""
    state, row = day_state(session, list_date)
    lists = list(
        session.scalars(select(Causelist).where(Causelist.list_date == list_date, CURRENT_LIST)).all()
    )
    ids = [cl.id for cl in lists]
    stored: dict[uuid.UUID, int] = {}
    courts: dict[uuid.UUID, set[str]] = {}
    if ids:
        for cid, n in session.execute(
            select(CauselistEntry.causelist_id, func.count())
            .where(CauselistEntry.causelist_id.in_(ids))
            .group_by(CauselistEntry.causelist_id)
        ).all():
            stored[cid] = int(n)
        for cid, court in session.execute(
            select(CauselistEntry.causelist_id, func.trim(CauselistEntry.court_no))
            .where(CauselistEntry.causelist_id.in_(ids), CauselistEntry.court_no.isnot(None))
            .distinct()
        ).all():
            if court:
                courts.setdefault(cid, set()).add(court)
    bench_days = session.execute(
        select(CauselistBenchDay.bench_id, CauselistBenchDay.judge_names_as_listed).where(
            CauselistBenchDay.list_date == list_date
        )
    ).all()
    groups: dict[tuple[str, Any], list[Causelist]] = {}
    for cl in lists:
        key = ("bench", cl.bench_id) if cl.bench_id is not None else ("list", cl.id)
        groups.setdefault(key, []).append(cl)
    sat = {bench_id: names for bench_id, names in bench_days}
    for bench_id in sat:
        groups.setdefault(("bench", bench_id), [])
    benches: list[dict[str, Any]] = []
    for (kind, ident), members in groups.items():
        members.sort(key=_list_key)
        court_nos = sorted({c for cl in members for c in courts.get(cl.id, set())}, key=court_sort_key)
        label = next((cl.bench_label for cl in members if cl.bench_label), None)
        if label is None and kind == "bench":
            label = sat.get(ident)
        benches.append(
            {
                "bench_id": ident if kind == "bench" else None,
                "label": label,
                "court_nos": court_nos,
                "source": _value(members[0].source) if members else "napix",
                "entries": sum(stored.get(cl.id, 0) for cl in members),
                "lists": [_list_out(cl, stored.get(cl.id, 0)) for cl in members],
            }
        )
    benches.sort(
        key=lambda b: (
            court_sort_key(b["court_nos"][0] if b["court_nos"] else None),
            b["bench_id"] is None,
            b["bench_id"] or 0,
            str(b["lists"][0]["id"]) if b["lists"] else "",
        )
    )
    previous_date = session.scalar(
        select(func.max(Causelist.list_date)).where(Causelist.list_date < list_date, CURRENT_LIST)
    )
    next_date = session.scalar(
        select(func.min(Causelist.list_date)).where(Causelist.list_date > list_date, CURRENT_LIST)
    )
    return {
        "date": list_date,
        "state": state,
        "queue_status": _value(row.status) if row is not None else None,
        "queue_finished_at": to_ist(row.finished_at) if row is not None else None,
        "previous_date": previous_date,
        "next_date": next_date,
        "totals": {
            "benches": len(benches),
            "lists": len(lists),
            "entries": sum(b["entries"] for b in benches),
        },
        "benches": benches,
    }


# ------------------------------------------------------------------------------------------------ entries


def _parse_q(q: str | None) -> ParsedQuery | None:
    raw = (q or "").strip()
    if not raw:
        return None
    try:
        return case_filters.parse_query(raw)
    except CaseFilterError as exc:
        raise CauselistViewError(str(exc)) from exc


def _validate(
    session: Session,
    list_date: date,
    *,
    bench_id: int | None,
    list_id: uuid.UUID | None,
    list_type: str | None,
    court_no: str | None,
    only: str | None,
    limit: int,
    offset: int,
) -> tuple[str | None, str | None, str | None]:
    if bench_id is not None and list_id is not None:
        raise CauselistViewError("give bench_id or list_id, not both")
    if list_id is not None:
        found = session.scalar(
            select(Causelist.id).where(Causelist.id == list_id, Causelist.list_date == list_date)
        )
        if found is None:
            raise CauselistViewError(f"list_id is not a cause list of {list_date.isoformat()}")
    lt = (list_type or "").strip().lower() or None
    if lt is not None and lt not in LIST_TYPES:
        raise CauselistViewError("list_type is one of " + ", ".join(LIST_TYPES))
    on = (only or "").strip().lower() or None
    if on is not None and on not in ONLY_VALUES:
        raise CauselistViewError("only is one of " + ", ".join(ONLY_VALUES))
    court = (court_no or "").strip() or None
    if court is not None and len(court) > MAX_COURT_NO:
        raise CauselistViewError(f"court_no is at most {MAX_COURT_NO} characters")
    if not (1 <= int(limit) <= MAX_LIMIT):
        raise CauselistViewError(f"limit is between 1 and {MAX_LIMIT}")
    if int(offset) < 0:
        raise CauselistViewError("offset is not negative")
    return lt, on, court


def _words_condition(words: list[str]) -> ColumnElement[bool]:
    """Every word a case-insensitive word prefix (`~* ('\\m' || :word)`, the word bound) of the row's printed
    case number, parties, advocates or counsel codes."""
    codes = func.array_to_string(CauselistEntry.counsel_codes, " ")
    per_word = []
    for word in words:
        pattern = literal("\\m", String).concat(literal(word, String)).self_group()
        per_word.append(or_(*[col.op("~*", is_comparison=True)(pattern) for col in (*WORD_COLUMNS, codes)]))
    return and_(*per_word) if per_word else false()


def _query_condition(session: Session, p: ParsedQuery) -> ColumnElement[bool]:
    """Decision 8: a CNR matches the row's or its case's; an id, `ref_no` or case number the row's case (a case
    number also the printed number of a row without a case); other words the printed row."""
    if p.kind == "cnr":
        return or_(CauselistEntry.cnr == p.cnr, Case.cnr == p.cnr)
    if p.kind == "id":
        return Case.id == p.id
    if p.kind == "ref_no":
        return Case.ref_no == p.ref_no
    if p.kind == "number":
        printed = f"{p.type_compact}/{p.reg_no}/{p.reg_year}"
        return or_(
            and_(Case.id.isnot(None), case_filters.number_condition(session, p, Case)),
            case_filters.compact_sql(CauselistEntry.case_no_text) == printed,
        )
    return _words_condition(p.words)


def _row_conditions(session: Session, user: User | Member) -> dict[str, ColumnElement[bool]]:
    """The per-row facts over the joined `Case` (NULL for a row without a case), each a boolean in SQL."""
    has_case = Case.id.isnot(None)
    dept_ids = [d.id for d in access.departments(session, user)]
    mine = (
        exists().where(
            CaseOwnership.case_id == Case.id,
            CaseOwnership.office_id.in_(dept_ids),
            CaseOwnership.status == OwnershipStatus.ACTIVE,
        )
        if dept_ids
        else false()
    )
    claimed = exists().where(
        CaseOwnership.case_id == Case.id,
        CaseOwnership.role == OwnershipRole.PRIMARY,
        CaseOwnership.status == OwnershipStatus.ACTIVE,
    )
    recommended = exists().where(
        Recommendation.case_id == Case.id, shown_recommendations_condition(session, user)
    )
    return {
        "visible": and_(has_case, visible_case_condition(session, user)),
        "in_pool": and_(has_case, never_owned()),
        "recommended": and_(has_case, recommended),
        "mine": and_(has_case, mine),
        "claimable": and_(has_case, claimable_condition(session, user)),
        "claimed": and_(has_case, claimed),
        "unclaimed": and_(has_case, never_owned()),
    }


def _held_by_you_sql(session: Session, user: User | Member) -> ColumnElement:
    dept_ids = [d.id for d in access.departments(session, user)]
    if not dept_ids:
        return literal(None, String)

    def held(role: OwnershipRole) -> ColumnElement[bool]:
        return exists().where(
            CaseOwnership.case_id == Case.id,
            CaseOwnership.office_id.in_(dept_ids),
            CaseOwnership.role == role,
            CaseOwnership.status == OwnershipStatus.ACTIVE,
        )

    return case(
        (held(OwnershipRole.PRIMARY), literal("primary", String)),
        (held(OwnershipRole.WATCHER), literal("watcher", String)),
        else_=literal(None, String),
    )


def _place(
    list_date: date,
    *,
    bench_id: int | None,
    list_id: uuid.UUID | None,
    list_type: str | None,
    court_no: str | None,
) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = [Causelist.list_date == list_date]
    if bench_id is not None:
        conds.append(Causelist.bench_id == bench_id)
    if list_id is not None:
        conds.append(Causelist.id == list_id)  # an earlier version can be opened by its id (decision 12)
    else:
        conds.append(CURRENT_LIST)
    if list_type is not None:
        conds.append(Causelist.list_type == ListType(list_type))
    if court_no is not None:
        conds.append(func.trim(CauselistEntry.court_no) == court_no)
    return conds


def entries(
    session: Session,
    user: User | Member,
    list_date: date,
    *,
    bench_id: int | None = None,
    list_id: uuid.UUID | None = None,
    list_type: str | None = None,
    court_no: str | None = None,
    q: str | None = None,
    only: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Decisions 1, 3, 6–8: every stored row of the place (date, bench or list, list type, court), narrowed by
    `q` and `only`, in court order, each with the portal's facts for the caller; the counts are for the place."""
    lt, on, court = _validate(
        session,
        list_date,
        bench_id=bench_id,
        list_id=list_id,
        list_type=list_type,
        court_no=court_no,
        only=only,
        limit=limit,
        offset=offset,
    )
    parsed = _parse_q(q)
    raw_case = aliased(Case, name="raw_case")
    # a row of a merged case points to the survivor (decision 7: a merged case is never claimable)
    case_id = func.coalesce(
        select(raw_case.merged_into_case_id).where(raw_case.id == CauselistEntry.case_id).scalar_subquery(),
        CauselistEntry.case_id,
    )
    facts = _row_conditions(session, user)
    place = _place(list_date, bench_id=bench_id, list_id=list_id, list_type=lt, court_no=court)

    def base(*columns: Any):
        return (
            select(*columns)
            .select_from(CauselistEntry)
            .join(Causelist, Causelist.id == CauselistEntry.causelist_id)
            .outerjoin(Case, Case.id == case_id)
            .where(*place)
        )

    count_row = session.execute(
        base(
            func.count().label("entries"),
            *[func.count().filter(facts[name]).label(name) for name in COUNT_NAMES],
        )
    ).one()
    counts = {"entries": int(count_row.entries), **{n: int(getattr(count_row, n)) for n in COUNT_NAMES}}
    narrowing: list[ColumnElement[bool]] = []
    if parsed is not None:
        narrowing.append(_query_condition(session, parsed))
    if on is not None:
        narrowing.append(facts[on])
    total = int(session.scalar(base(func.count()).where(*narrowing)) or 0)
    stmt = (
        base(
            CauselistEntry,
            Causelist.list_type,
            Causelist.bench_id,
            Causelist.bench_label,
            Case.id.label("case_id"),
            facts["visible"].label("visible"),
            facts["in_pool"].label("in_pool"),
            facts["claimable"].label("claimable"),
            _held_by_you_sql(session, user).label("held_by_you"),
        )
        .where(*narrowing)
        .order_by(
            *court_order_sql(CauselistEntry.court_no),
            nulls_last(Causelist.bench_id.asc()),
            list_type_rank_sql(Causelist.list_type),
            nulls_last(Causelist.napix_causelist_id.asc()),
            Causelist.id,
            CauselistEntry.source,
            CauselistEntry.sr_no,
            CauselistEntry.id,
        )
        .limit(int(limit))
        .offset(int(offset))
    )
    rows = session.execute(stmt).all()
    case_ids = sorted({r.case_id for r in rows if r.case_id is not None})
    cases = list(session.scalars(select(Case).where(Case.id.in_(case_ids))).all()) if case_ids else []
    hidden = {r.case_id for r in rows if r.case_id is not None and not r.visible}
    summaries = inbox.summaries(session, cases, hidden=hidden)
    owners = inbox.primary_codes(session, case_ids)
    recs: dict[uuid.UUID, list[dict[str, Any]]] = {}
    if case_ids:
        for cid, code, band, score in session.execute(
            select(Recommendation.case_id, Office.code, Recommendation.band, Recommendation.score)
            .join(Office, Office.id == Recommendation.office_id)
            .where(Recommendation.case_id.in_(case_ids), shown_recommendations_condition(session, user))
            .order_by(Recommendation.case_id, Recommendation.score.desc(), Office.code)
        ).all():
            recs.setdefault(cid, []).append(
                {"office_code": code, "band": _value(band), "score": float(score)}
            )
    items = []
    for r in rows:
        e: CauselistEntry = r[0]
        cid = r.case_id
        items.append(
            {
                "id": e.id,
                "causelist_id": e.causelist_id,
                "list_type": _value(r.list_type),
                "bench_id": r.bench_id,
                "bench_label": r.bench_label,
                "court_no": e.court_no,
                "sr_no": e.sr_no,
                "printed_sr_no": e.printed_sr_no,
                "section": e.section,
                "is_connected": e.is_connected,
                "with_text": e.with_text,
                "case_no_text": e.case_no_text,
                "cnr": e.cnr,
                "petitioner_text": e.petitioner_text,
                "respondent_text": e.respondent_text,
                "pet_advocate_text": e.pet_advocate_text,
                "res_advocate_text": e.res_advocate_text,
                "counsel_codes": list(e.counsel_codes or []),
                "remarks": e.remarks,
                "source": _value(e.source),
                "resolution_status": _value(e.resolution_status),
                "case": summaries.get(cid) if cid is not None else None,
                "visible": bool(r.visible),
                "owner_office_code": owners.get(cid) if cid is not None else None,
                "held_by_you": r.held_by_you,
                "in_pool": bool(r.in_pool),
                "recommendations": recs.get(cid, []) if cid is not None else [],
                "claimable": bool(r.claimable),
            }
        )
    named = session.get(Causelist, list_id) if list_id is not None else None
    return {
        "date": list_date,
        "total": total,
        "counts": counts,
        "items": items,
        "list": _list_out(named, counts["entries"]) if named is not None else None,
    }


# ------------------------------------------------------------------------------------------------ the PDF


def file_name(cl: Causelist) -> str:
    bench = f"bench-{cl.bench_id}" if cl.bench_id is not None else "court-wide"
    return f"Causelist_{cl.list_date.isoformat()}_{bench}_{_value(cl.list_type)}.pdf"


def list_file(
    session: Session,
    user: User | Member,
    causelist_id: uuid.UUID,
    *,
    store: LocalStore,
    disposition: str = "attachment",
) -> ServedFile:
    """Decision 9: the list's original PDF for a reader of cases holding `documents.view` (inline) or
    `documents.download` (attachment). A court record published by the court: not audited."""
    disposition = (disposition or "attachment").strip().lower()
    if disposition not in ("inline", "attachment"):
        raise CauselistViewError("disposition must be inline or attachment")
    if not (
        access.has(session, user, Permission.CASES_VIEW_SCOPE)
        or access.has(session, user, Permission.CASES_VIEW_ALL)
    ):
        raise NotAllowed("cases.view_scope or cases.view_all is not enabled for you")
    permission = Permission.DOCUMENTS_VIEW if disposition == "inline" else Permission.DOCUMENTS_DOWNLOAD
    if not access.has(session, user, permission):
        raise NotAllowed(f"{permission.value} is not enabled for you")
    cl = session.get(Causelist, causelist_id)
    if cl is None:
        raise CauselistNotFound("no such cause list")
    doc = session.get(Document, cl.document_id) if cl.document_id is not None else None
    if doc is None or DocKind(doc.kind) != DocKind.CAUSELIST:
        raise NoPdf(_value(cl.fetch_status))
    return serve_stored(session, doc, disposition, store=store, filename=file_name(cl))


__all__ = [
    "COUNT_NAMES",
    "DAY_STATES",
    "LIST_TYPES",
    "ONLY_VALUES",
    "ORDER_OF_LIST_TYPE",
    "CauselistNotFound",
    "CauselistViewError",
    "NoPdf",
    "NotAllowed",
    "court_sort_key",
    "dates",
    "day",
    "day_state",
    "entries",
    "list_file",
]
