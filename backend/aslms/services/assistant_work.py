"""My Work on the sidebar Assistant (design `assistant-ollama-work`, decisions 3 to 13): twelve fixed questions about
the asker's own work, each answered from the existing service of the screen that shows those facts, run with the
asker's own rights.

- `WORK_QUESTIONS` is the code registry (decision 3): a key, a label, an example, a strict parameter model
  (`extra="forbid"`), the guard of its screen's route, the service it calls, the allow-listed fields (`FIELDS`,
  decision 10), the full-list link and the count sentence. Adding a question is a code change with its own test.
- The answer is written by the server (decision 4): the count sentence first, at most one detail sentence, the shown
  line, then at most `ASSISTANT_WORK_ROWS` rows. The text names no case; cases appear only in the rows, stored as
  `work_row` citations holding snapshots of allow-listed fields (decision 9).
- The services are called as their screens call them (decision 5), in one read-only transaction with a statement
  timeout; three of them gained one optional period keyword each (`custody.sent(since=)`,
  `inbox.claimed(claimed_since=)`, `my_cases.claimed_by_me(since=)`). Two questions keep a row filter
  (`pending_actions` with `when=all`, `new_orders`).
- The local model only chooses the question (decision 8): `tool_schemas` are the twelve functions, `validate_choice`
  accepts exactly one valid call, and `keyword_choice` is the fixed fallback table.

This module imports no connector and no model client; it never reads note, remark or document contents, alert
bodies or recommendation reasons, and it writes nothing."""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from aslms.core import clock
from aslms.domain.org import Office, User
from aslms.domain.reference import AlertKind, Permission
from aslms.services import access, alerts, calendar, custody, dashboard, inbox, my_cases, visibility
from aslms.services.reporting_common import ReportConfig

ENGINE = "work_list"
CONNECTOR = "work"
WORK_VERSION = 1
WORK_SLOT_WAIT_SECONDS = 5.0  # decision 8.1: the short wait for the model's slot
WORK_CHOICE_SECONDS = 10.0  # decision 8.2: the choice's share of the question's time
WORK_SCAN_ROWS = 1000  # decision 5: the most rows the adapter pages through
WORK_PAGE = 100
WORK_STATEMENT_MS = 10_000  # decision 13: `SET LOCAL statement_timeout`
PARTIES_CHARS = 160

NO_LIST = "You do not have this list."
NO_DEPARTMENT = "This question is about your department's cases, and you do not belong to a department."
NO_MATCH_TEXT = (
    "This tab answers questions about your own work: pending actions and due dates, cases with you or sent by you, "
    "your hearings and tomorrow's listings, unread alerts, new orders, what needs attention, the cases you or your "
    "department claimed, and the cases waiting to be claimed. Try one of the examples, or ask about court orders in "
    "My Cases or All Court Orders."
)
TIMEOUT_TEXT = "Your lists took too long to read; try again."
ERROR_TEXT = "Your lists could not be read because of an unexpected error; try again."
HIDDEN_ROW = "A case you can no longer open"
CLAIMED_BY_ME_NOTE = (
    "Counted as on your Case Inbox's My Cases tab: cases your department holds that you claimed or whose transfer "
    "you accepted."
)


def system_line(today: date) -> str:
    """Decision 8.2: the one system line of the tools call."""
    return (
        "Choose the one function that answers the officer's question about their own work. If none fits, call no "
        f"function. Today is {day(today)}."
    )


# ------------------------------------------------------------------------------------------------ words


def day(d: date | None) -> str:
    """As on the portal: `Fri 14 Nov 2026`."""
    if d is None:
        return "-"
    return f"{d:%a} {d.day} {d:%b} {d.year}"


def _n(n: int, *, capped: bool = False) -> str:
    return f"at least {n:,}" if capped else f"{n:,}"


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _period_words(period: str) -> str:
    return {"last_7_days": "in the last 7 days", "last_30_days": "in the last 30 days"}.get(period, "in all")


def period_start(period: str, today: date) -> datetime | None:
    """Decision 5's periods in IST days: `last_7_days` from today - 6 at 00:00 IST, `last_30_days` from today - 29,
    `all` no bound."""
    if period == "last_7_days":
        return clock.ist_midnight(today - timedelta(days=6))
    if period == "last_30_days":
        return clock.ist_midnight(today - timedelta(days=29))
    return None


def _ist_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        v = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return v.astimezone(clock.IST).date()
    return value


def _iso(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


# ------------------------------------------------------------------------------------------------ parameters

Period = Literal["last_7_days", "last_30_days", "all"]
Range = Literal["today", "tomorrow", "this_week", "next_week", "dates"]
MAX_DATES_SPAN = 30  # at most 31 days, both ends counted
MAX_DATES_REACH = 62  # within 62 days of today


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NoParams(_Params):
    pass


class PendingParams(_Params):
    when: Literal["overdue", "due_this_week", "all"] = "all"


class SentParams(_Params):
    period: Period = "last_30_days"
    still_out: bool = False


class RangeParams(_Params):
    range: Range = "this_week"
    from_: date | None = Field(None, alias="from")
    to: date | None = None

    @model_validator(mode="after")
    def _dates(self) -> RangeParams:
        if self.range == "dates":
            if self.from_ is None or self.to is None:
                raise ValueError("range dates needs from and to")
            if self.to < self.from_ or (self.to - self.from_).days > MAX_DATES_SPAN:
                raise ValueError("from and to are at most 31 days, to on or after from")
        elif self.from_ is not None or self.to is not None:
            raise ValueError("from and to go only with range dates")
        return self


class AlertParams(_Params):
    kind: str = "any"

    @model_validator(mode="after")
    def _kind(self) -> AlertParams:
        if self.kind != "any" and self.kind not in {k.value for k in AlertKind}:
            raise ValueError("kind is an alert kind or any")
        return self


class NewOrdersParams(_Params):
    days: int = Field(7, ge=1, le=30)


class ClaimPeriodParams(_Params):
    period: Period = "all"


class BandParams(_Params):
    band: Literal["strong", "possible", "any"] = "any"


def dump(params: BaseModel) -> dict[str, Any]:
    """The parameters as stored and audited: enums, dates and small numbers."""
    return params.model_dump(mode="json", by_alias=True, exclude_none=True)


def dates_ok(params: BaseModel, today: date) -> bool:
    """Decision 8.2: the bounds of `dates` against the IST today."""
    if isinstance(params, RangeParams) and params.range == "dates":
        assert params.from_ is not None and params.to is not None
        reach = timedelta(days=MAX_DATES_REACH)
        return abs(params.from_ - today) <= reach and abs(params.to - today) <= reach
    return True


def resolve_range(params: RangeParams, today: date) -> tuple[date, date]:
    """Today, tomorrow, this week (today to Sunday), next week (Monday to Sunday) or the given dates."""
    if params.range == "today":
        return today, today
    if params.range == "tomorrow":
        t = today + timedelta(days=1)
        return t, t
    if params.range == "next_week":
        monday = today + timedelta(days=7 - today.weekday())
        return monday, monday + timedelta(days=6)
    if params.range == "dates":
        assert params.from_ is not None and params.to is not None
        return params.from_, params.to
    return today, today + timedelta(days=6 - today.weekday())


def range_words(params: RangeParams, today: date) -> str:
    start, end = resolve_range(params, today)
    if params.range == "dates":
        return f"from {day(start)} to {day(end)}"
    words = {"today": "today", "tomorrow": "tomorrow", "this_week": "this week", "next_week": "next week"}
    when = day(start) if start == end else f"{day(start)} to {day(end)}"
    return f"{words[params.range]} ({when})"


# ------------------------------------------------------------------------------------------------ fields (decision 10)

COMMON_FIELDS = ("case_no", "cnr", "parties", "case_ref")
FIELDS: dict[str, tuple[str, ...]] = {
    "pending_actions": (
        *COMMON_FIELDS,
        "pending_action_label",
        "due_date",
        "overdue_days",
        "due_soon",
        "since",
        "sent_by",
    ),
    "cases_with_me": (
        *COMMON_FIELDS,
        "pending_action_label",
        "due_date",
        "overdue_days",
        "due_soon",
        "since",
        "sent_by",
    ),
    "sent_by_me": (*COMMON_FIELDS, "date", "action", "to", "pending_action_label", "due_date", "still_there"),
    "my_hearings": (*COMMON_FIELDS, "date", "court_no", "item_no", "bench", "approximate"),
    "listed_tomorrow": (*COMMON_FIELDS, "date", "court_no", "item_no", "bench", "approximate"),
    "my_due_dates": (*COMMON_FIELDS, "date", "kind_label", "pending_action_label"),
    "unread_alerts": (*COMMON_FIELDS, "date", "kind_label", "severity", "title"),
    "new_orders": (*COMMON_FIELDS, "date", "kind_label", "severity", "title"),
    "needs_attention": (*COMMON_FIELDS, "kind_label", "title", "date", "detail", "overdue_days"),
    "claimed_by_me": (*COMMON_FIELDS, "claimed_on", "via", "department", "status"),
    "department_claimed": (*COMMON_FIELDS, "claimed_on", "department", "role", "assigned_to", "status"),
    "awaiting_claim": (*COMMON_FIELDS, "department", "band", "next_hearing", "last_listed_on"),
}
NEVER_FIELDS = ("remark", "body", "note", "text", "reasons", "ref_no", "score_signals")
ATTENTION_LABELS = {
    "overdue_action": "Overdue",
    "confirm_next_date": "Next Date to Enter",
    "due_soon": "Due Soon",
    "ready_to_close": "Ready to Close",
    "file_received": "Case Received",
}
DUE_KIND_LABELS = {"action_due": "Pending Action Due", "confirm": "Next Date to Confirm"}


def allowed(key: str, fields: dict[str, Any] | None) -> dict[str, Any]:
    """`fields` filtered through the question's allow-list (also applied at every read)."""
    keep = FIELDS.get(key, ())
    return {k: v for k, v in (fields or {}).items() if k in keep}


def _parties(pet: str | None, res: str | None) -> str | None:
    if not pet and not res:
        return None
    text_ = f"{pet or '-'} v {res or '-'}"
    return text_ if len(text_) <= PARTIES_CHARS else text_[: PARTIES_CHARS - 1].rstrip() + "…"


def _case_fields(case: dict[str, Any] | None) -> dict[str, Any]:
    """The common fields from a case summary (`inbox.summaries`) or a case reference (`calendar.case_ref`); parties
    only where the service gives them. Never `ref_no`."""
    if not case:
        return {"case_no": None, "cnr": None, "parties": None, "case_ref": None}
    return {
        "case_no": case.get("case_no_text"),
        "cnr": case.get("cnr"),
        "parties": _parties(case.get("petitioner_summary"), case.get("respondent_summary")),
        "case_ref": str(case["id"]) if case.get("id") else None,
    }


def _office_names(session: Session, codes: set[str | None]) -> dict[str, str]:
    want = {c for c in codes if c}
    if not want:
        return {}
    return {o.code: o.name for o in session.scalars(select(Office).where(Office.code.in_(want))).all()}


def _sent_by(sent: dict[str, Any] | None, names: dict[str, str]) -> dict[str, Any] | None:
    if not sent:
        return None
    code = sent.get("office_code")
    return {
        "name": sent.get("name"),
        "designation": sent.get("designation"),
        "office_name": names.get(code, code) if code else None,
    }


# ------------------------------------------------------------------------------------------------ results


@dataclass
class WorkRow:
    case_id: uuid.UUID | None
    fields: dict[str, Any]


@dataclass
class WorkResult:
    rows: list[WorkRow] = field(default_factory=list)
    total: int = 0
    extra: dict[str, Any] = field(default_factory=dict)
    scan_capped: bool = False
    departments: list[Office] = field(default_factory=list)
    whole: bool = True  # department_claimed only
    href_department: str | None = None


@dataclass
class Ctx:
    session: Session
    user: User
    now: datetime
    today: date
    rows_cap: int
    cfg: ReportConfig


@dataclass(frozen=True)
class WorkQuestion:
    key: str
    label: str
    example: str
    params: type[BaseModel]
    list_label: str
    run: Callable[[Ctx, Any], WorkResult]
    count_sentence: Callable[[WorkResult, Any, Ctx], str]
    full_list_href: Callable[[Any, WorkResult, Ctx], str]
    detail_sentence: Callable[[WorkResult, Any, Ctx], str | None] = lambda r, p, c: None
    guard: tuple[Permission, ...] = (Permission.CASES_VIEW_SCOPE, Permission.CASES_VIEW_ALL)
    department_rule: Permission | None = None  # 11 and 12: the function each department membership must hold
    none_sentence: str | None = None
    keywords: tuple[str, ...] = ()
    detail_newline: bool = False


@dataclass
class WorkAnswer:
    outcome: str  # answered | no_match | failed
    content: str
    citations: list[dict[str, Any]] | None = None
    info: dict[str, Any] = field(default_factory=dict)
    family: str | None = None


# ------------------------------------------------------------------------------------------------ paging


def _scan(
    fetch: Callable[[int, int], inbox.Page],
    *,
    keep: Callable[[dict[str, Any]], bool] | None = None,
    stop: Callable[[dict[str, Any]], bool] | None = None,
) -> tuple[list[dict[str, Any]], int, bool]:
    """Pages through a service at `WORK_PAGE` rows a page, at most `WORK_SCAN_ROWS`, keeping the rows `keep` accepts
    and stopping at the first row `stop` names. Returns the kept rows, their count and whether the cap was reached
    with rows left."""
    kept: list[dict[str, Any]] = []
    offset = 0
    while offset < WORK_SCAN_ROWS:
        page = fetch(min(WORK_PAGE, WORK_SCAN_ROWS - offset), offset)
        for item in page.items:
            if stop is not None and stop(item):
                return kept, len(kept), False
            if keep is None or keep(item):
                kept.append(item)
        offset += len(page.items)
        if not page.items or offset >= page.total:
            return kept, len(kept), False
    return kept, len(kept), True


def _first(fetch: Callable[[int, int], inbox.Page], cap: int) -> tuple[list[dict[str, Any]], int]:
    page = fetch(cap, 0)
    return page.items, page.total


# ------------------------------------------------------------------------------------------------ the runs


def _held_row(item: dict[str, Any], names: dict[str, str]) -> WorkRow:
    card = item.get("card") or {}
    return WorkRow(
        _case_id(item.get("case")),
        {
            **_case_fields(item.get("case")),
            "pending_action_label": card.get("pending_action_label"),
            "due_date": _iso(card.get("due_date")),
            "overdue_days": card.get("overdue_days") or 0,
            "due_soon": bool(card.get("due_soon")),
            "since": _iso(_ist_date(card.get("since"))),
            "sent_by": _sent_by(card.get("sent_by"), names),
        },
    )


def _case_id(case: dict[str, Any] | None) -> uuid.UUID | None:
    raw = (case or {}).get("id")
    if raw is None:
        return None
    return raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))


def _held_rows(ctx: Ctx, items: list[dict[str, Any]]) -> list[WorkRow]:
    names = _office_names(
        ctx.session, {((i.get("card") or {}).get("sent_by") or {}).get("office_code") for i in items}
    )
    return [_held_row(i, names) for i in items[: ctx.rows_cap]]


def run_pending_actions(ctx: Ctx, p: PendingParams) -> WorkResult:
    s, u = ctx.session, ctx.user
    if p.when == "overdue":
        items, total = _first(
            lambda lim, off: custody.held(s, u, scope="me", overdue=True, limit=lim, offset=off), ctx.rows_cap
        )
        return WorkResult(_held_rows(ctx, items), total)
    if p.when == "due_this_week":
        items, total = _first(
            lambda lim, off: my_cases.mine(
                s, u, view="files", action="due_week", closure="open", limit=lim, offset=off
            ),
            ctx.rows_cap,
        )
        names = _office_names(
            s, {((i.get("custody") or {}).get("sent_by") or {}).get("office_code") for i in items}
        )
        rows = [
            _held_row({"case": i.get("case"), "card": i.get("custody") or {}}, names)
            for i in items[: ctx.rows_cap]
        ]
        return WorkResult(rows, total)
    kept, total, capped = _scan(
        lambda lim, off: custody.held(s, u, scope="me", limit=lim, offset=off),
        keep=lambda i: ((i.get("card") or {}).get("pending_action") or "none") != "none",
    )
    overdue = custody.held(s, u, scope="me", overdue=True, limit=1).total
    return WorkResult(_held_rows(ctx, kept), total, {"overdue": overdue}, scan_capped=capped)


def run_cases_with_me(ctx: Ctx, p: NoParams) -> WorkResult:
    s, u = ctx.session, ctx.user
    kept, total, capped = _scan(lambda lim, off: custody.held(s, u, scope="me", limit=lim, offset=off))
    cards = [i.get("card") or {} for i in kept]
    extra = {
        "pending": sum(1 for c in cards if (c.get("pending_action") or "none") != "none"),
        "overdue": sum(1 for c in cards if c.get("overdue")),
    }
    return WorkResult(_held_rows(ctx, kept), total, extra, scan_capped=capped)


def _sent_row(item: dict[str, Any]) -> WorkRow:
    leg = item.get("leg") or {}
    office = leg.get("holder_office") or {}
    to = ", ".join(x for x in (leg.get("holder_designation"), office.get("name")) if x) or None
    return WorkRow(
        _case_id(item.get("case")),
        {
            **_case_fields(item.get("case")),
            "date": _iso(_ist_date(leg.get("started_at"))),
            "action": "Recalled" if leg.get("reason") == "recalled" else "Sent",
            "to": to,
            "pending_action_label": leg.get("pending_action_label"),
            "due_date": _iso(leg.get("due_date")),
            "still_there": item.get("current"),
        },
    )


def run_sent_by_me(ctx: Ctx, p: SentParams) -> WorkResult:
    s, u = ctx.session, ctx.user
    since = period_start(p.period, ctx.today)
    items, total = _first(
        lambda lim, off: custody.sent(s, u, still_out=p.still_out, since=since, limit=lim, offset=off),
        ctx.rows_cap,
    )
    extra: dict[str, Any] = {}
    if not p.still_out:
        extra["still_out"] = custody.sent(s, u, still_out=True, since=since, limit=1).total
    return WorkResult([_sent_row(i) for i in items[: ctx.rows_cap]], total, extra)


def _calendar(ctx: Ctx, start: date, end: date) -> list[dict[str, Any]]:
    from aslms.services import next_dates  # next_dates imports calendar

    return calendar.my_calendar(
        ctx.session,
        ctx.user,
        from_=start,
        to=end,
        now=ctx.now,
        critical_hours=ctx.cfg.critical_hours,
        sitting_time=ctx.cfg.sitting_time,
        review_cfg=next_dates.NextDateConfig.from_settings(),
    )


def _hearing_row(item: dict[str, Any]) -> WorkRow:
    return WorkRow(
        _case_id(item.get("case")),
        {
            **_case_fields(item.get("case")),
            "date": _iso(item.get("date")),
            "court_no": item.get("court_no"),
            "item_no": item.get("item_no"),
            "bench": item.get("bench"),
            "approximate": bool(item.get("approximate")),
        },
    )


def run_my_hearings(ctx: Ctx, p: RangeParams) -> WorkResult:
    start, end = resolve_range(p, ctx.today)
    items = [i for i in _calendar(ctx, start, end) if i["kind"] == "hearing"]
    return WorkResult([_hearing_row(i) for i in items[: ctx.rows_cap]], len(items))


def run_listed_tomorrow(ctx: Ctx, p: NoParams) -> WorkResult:
    t = ctx.today + timedelta(days=1)
    items = [i for i in _calendar(ctx, t, t) if i["kind"] == "hearing"]
    return WorkResult([_hearing_row(i) for i in items[: ctx.rows_cap]], len(items))


def run_my_due_dates(ctx: Ctx, p: RangeParams) -> WorkResult:
    start, end = resolve_range(p, ctx.today)
    items = [i for i in _calendar(ctx, start, end) if i["kind"] in ("action_due", "confirm")]
    rows = [
        WorkRow(
            _case_id(i.get("case")),
            {
                **_case_fields(i.get("case")),
                "date": _iso(i.get("date")),
                "kind_label": DUE_KIND_LABELS[i["kind"]],
                "pending_action_label": i.get("pending_action_label"),
            },
        )
        for i in items[: ctx.rows_cap]
    ]
    extra = {
        "actions": sum(1 for i in items if i["kind"] == "action_due"),
        "confirm": sum(1 for i in items if i["kind"] == "confirm"),
    }
    return WorkResult(rows, len(items), extra)


def _alert_row(item: dict[str, Any]) -> WorkRow:
    return WorkRow(
        _case_id(item.get("case")),
        {
            **_case_fields(item.get("case")),
            "date": _iso(_ist_date(item.get("notified_at") or item.get("created_at"))),
            "kind_label": item.get("kind_label"),
            "severity": item.get("severity"),
            "title": item.get("title"),
        },
    )


def run_unread_alerts(ctx: Ctx, p: AlertParams) -> WorkResult:
    s, u = ctx.session, ctx.user
    kind = None if p.kind == "any" else p.kind
    items, total = _first(
        lambda lim, off: alerts.list_for_user(
            s, u, unread=True, status="open", kind=kind, limit=lim, offset=off
        ),
        ctx.rows_cap,
    )
    extra: dict[str, Any] = {}
    if kind is not None:
        extra["kind_label"] = alerts._labels(s).get(kind, kind)
    return WorkResult([_alert_row(i) for i in items[: ctx.rows_cap]], total, extra)


def run_new_orders(ctx: Ctx, p: NewOrdersParams) -> WorkResult:
    s, u = ctx.session, ctx.user
    since = clock.ist_midnight(ctx.today - timedelta(days=p.days - 1))

    def older(item: dict[str, Any]) -> bool:
        at = item.get("notified_at") or item.get("created_at")
        return at is not None and at < since

    kept, total, capped = _scan(
        lambda lim, off: alerts.list_for_user(
            s, u, kind=AlertKind.NEW_ORDER.value, status="all", limit=lim, offset=off
        ),
        stop=older,
    )
    cases = {str((i.get("case") or {}).get("id")) for i in kept if (i.get("case") or {}).get("id")}
    return WorkResult(
        [_alert_row(i) for i in kept[: ctx.rows_cap]], total, {"cases": len(cases)}, scan_capped=capped
    )


def run_needs_attention(ctx: Ctx, p: NoParams) -> WorkResult:
    out = dashboard.personal_headline(
        ctx.session, ctx.user, now=ctx.now, cfg=replace(ctx.cfg, list_size=WORK_SCAN_ROWS)
    )
    attention = out.get("attention") or []
    rows = [
        WorkRow(
            _case_id(a.get("case")),
            {
                **_case_fields(a.get("case")),
                "kind_label": ATTENTION_LABELS.get(a.get("kind"), a.get("kind")),
                "title": a.get("title"),
                "date": _iso(a.get("date")),
                "detail": a.get("detail"),
                "overdue_days": a.get("overdue_days") or 0,
            },
        )
        for a in attention[: ctx.rows_cap]
    ]
    return WorkResult(
        rows,
        len(attention),
        {"headline": out.get("headline") or {}},
        scan_capped=len(attention) >= WORK_SCAN_ROWS,
    )


def run_claimed_by_me(ctx: Ctx, p: ClaimPeriodParams) -> WorkResult:
    s, u = ctx.session, ctx.user
    since = period_start(p.period, ctx.today)
    items, total = _first(
        lambda lim, off: my_cases.claimed_by_me(s, u, since=since, limit=lim, offset=off), ctx.rows_cap
    )
    rows = [
        WorkRow(
            _case_id(i.get("case")),
            {
                **_case_fields(i.get("case")),
                "claimed_on": _iso(_ist_date(i.get("claimed_at"))),
                "via": "Transfer Accepted" if i.get("via") == "transfer" else "Claimed",
                "department": i.get("office_code"),
                "status": (i.get("case") or {}).get("status"),
            },
        )
        for i in items[: ctx.rows_cap]
    ]
    return WorkResult(rows, total)


def _departments(session: Session, user: User, rule: Permission) -> tuple[list[access.Member], bool]:
    """Decision 6: each department among the asker's memberships once, in membership order, where the membership
    holds `rule`; and whether the asker has any department at all."""
    seen: set[uuid.UUID] = set()
    out: list[access.Member] = []
    any_department = False
    for m in access.members(session, user):
        if m.department is None:
            continue
        any_department = True
        if m.department.id in seen or not m.holds(rule):
            continue
        seen.add(m.department.id)
        out.append(m)
    return out, any_department


def _assigned(item: dict[str, Any]) -> dict[str, Any] | None:
    unit = (item.get("unit") or {}).get("name")
    officer = (item.get("officer") or {}).get("full_name")
    if not unit and not officer:
        return None
    return {"unit": unit, "officer": officer}


def run_department_claimed(ctx: Ctx, p: ClaimPeriodParams) -> WorkResult:
    s, u = ctx.session, ctx.user
    since = period_start(p.period, ctx.today)
    members, _ = _departments(s, u, Permission.CASES_VIEW_SCOPE)
    view_all = access.has(s, u, Permission.CASES_VIEW_ALL)
    result = WorkResult()
    whole_all = True
    for m in members:
        dept = m.department
        assert dept is not None
        room = max(0, ctx.rows_cap - len(result.rows))
        page = inbox.claimed(
            s, u, office=dept.code, case_state="all", claimed_since=since, limit=max(1, room), offset=0
        )
        whole = view_all or visibility.whole_department(s, m)
        whole_all = whole_all and whole
        tab = whole or m.holds(Permission.CUSTODY_TRACK)
        if tab and result.href_department is None:
            result.href_department = dept.code
        result.departments.append(dept)
        result.extra.setdefault("per_department", []).append((dept.name, page.total))
        result.total += page.total
        for i in page.items[:room]:
            result.rows.append(
                WorkRow(
                    _case_id(i.get("case")),
                    {
                        **_case_fields(i.get("case")),
                        "claimed_on": _iso(_ist_date(i.get("claimed_at"))),
                        "department": dept.code,
                        "role": "Watcher" if i.get("role") == "watcher" else "Primary",
                        "assigned_to": _assigned(i),
                        "status": (i.get("case") or {}).get("status"),
                    },
                )
            )
    result.whole = whole_all
    return result


def run_awaiting_claim(ctx: Ctx, p: BandParams) -> WorkResult:
    s, u = ctx.session, ctx.user
    band = {"strong": "high", "possible": "medium"}.get(p.band)
    members, _ = _departments(s, u, Permission.CASES_CLAIM)
    result = WorkResult()
    strong = possible = 0
    for m in members:
        dept = m.department
        assert dept is not None
        room = max(0, ctx.rows_cap - len(result.rows))
        page = inbox.recommended(s, u, office=dept.code, band=band, limit=max(1, room), offset=0)
        strong += inbox.recommended(s, u, office=dept.code, band="high", limit=1).total
        possible += inbox.recommended(s, u, office=dept.code, band="medium", limit=1).total
        result.departments.append(dept)
        result.extra.setdefault("per_department", []).append((dept.name, page.total))
        result.total += page.total
        for i in page.items[:room]:
            case = i.get("case") or {}
            nh = case.get("next_hearing") or None
            result.rows.append(
                WorkRow(
                    _case_id(case),
                    {
                        **_case_fields(case),
                        "department": dept.code,
                        "band": "Strong" if i.get("band") == "high" else "Possible",
                        "next_hearing": (
                            {"date": _iso(nh.get("date")), "kind": nh.get("basis")}
                            if nh and nh.get("date")
                            else None
                        ),
                        "last_listed_on": _iso(case.get("last_listed_on")),
                    },
                )
            )
    if members:
        result.href_department = members[0].department.code  # type: ignore[union-attr]
    result.extra.update({"strong": strong, "possible": possible})
    return result


# ------------------------------------------------------------------------------------------------ the sentences


def _count_pending(r: WorkResult, p: PendingParams, ctx: Ctx) -> str:
    n, cap = r.total, r.scan_capped
    if p.when == "overdue":
        if n == 0:
            return "No files with you are overdue."
        return f"{_n(n, capped=cap)} {_plural(n, 'file with you is', 'files with you are')} overdue."
    if p.when == "due_this_week":
        if n == 0:
            return "You have no files with a pending action due in the next 7 days."
        return f"You have {_n(n)} {_plural(n, 'file', 'files')} with a pending action due in the next 7 days."
    if n == 0:
        return "You have no files with a pending action."
    return f"You have {_n(n, capped=cap)} {_plural(n, 'file', 'files')} with a pending action."


def _detail_pending(r: WorkResult, p: PendingParams, ctx: Ctx) -> str | None:
    k = int(r.extra.get("overdue") or 0)
    if p.when != "all" or k == 0 or r.total == 0:
        return None
    return f"{k:,} of them {_plural(k, 'is', 'are')} overdue."


def _count_with_me(r: WorkResult, p: NoParams, ctx: Ctx) -> str:
    n = r.total
    if n == 0:
        return "No case files are with you."
    return f"{_n(n, capped=r.scan_capped)} case {_plural(n, 'file is', 'files are')} with you."


def _detail_with_me(r: WorkResult, p: NoParams, ctx: Ctx) -> str | None:
    k, j = int(r.extra.get("pending") or 0), int(r.extra.get("overdue") or 0)
    if not k and not j:
        return None
    return f"{k:,} {_plural(k, 'has', 'have')} a pending action; {j:,} {_plural(j, 'is', 'are')} overdue."


def _count_sent(r: WorkResult, p: SentParams, ctx: Ctx) -> str:
    n = r.total
    if p.still_out:
        sent = "sent" if p.period == "all" else f"sent {_period_words(p.period)}"
        if n == 0:
            return f"No files you {sent} are still where you sent them."
        return f"{_n(n)} {_plural(n, 'file', 'files')} you {sent} {_plural(n, 'is', 'are')} still where you sent them."
    files = "no files" if n == 0 else f"{_n(n)} {_plural(n, 'file', 'files')}"
    if p.period == "all":
        return f"You have sent or recalled {files} in all."
    return f"You sent or recalled {files} {_period_words(p.period)}."


def _detail_sent(r: WorkResult, p: SentParams, ctx: Ctx) -> str | None:
    k = int(r.extra.get("still_out") or 0)
    if p.still_out or k == 0 or r.total == 0:
        return None
    return f"{k:,} {_plural(k, 'is', 'are')} still where you sent them."


def _count_hearings(r: WorkResult, p: RangeParams, ctx: Ctx) -> str:
    n = r.total
    what = "no hearings" if n == 0 else f"{_n(n)} {_plural(n, 'hearing', 'hearings')}"
    return f"You have {what} {range_words(p, ctx.today)}."


def _count_tomorrow(r: WorkResult, p: NoParams, ctx: Ctx) -> str:
    n = r.total
    when = day(ctx.today + timedelta(days=1))
    if n == 0:
        return f"None of your cases are on tomorrow's cause lists ({when})."
    return f"{_n(n)} of your cases {_plural(n, 'is', 'are')} on tomorrow's cause lists ({when})."


def _count_due(r: WorkResult, p: RangeParams, ctx: Ctx) -> str:
    n = r.total
    what = "no due dates" if n == 0 else f"{_n(n)} due {_plural(n, 'date', 'dates')}"
    return f"You have {what} {range_words(p, ctx.today)}."


def _detail_due(r: WorkResult, p: RangeParams, ctx: Ctx) -> str | None:
    k, j = int(r.extra.get("actions") or 0), int(r.extra.get("confirm") or 0)
    if r.total == 0:
        return None
    return f"{k:,} pending {_plural(k, 'action', 'actions')} and {j:,} next {_plural(j, 'date', 'dates')} to confirm."


def _count_unread(r: WorkResult, p: AlertParams, ctx: Ctx) -> str:
    n = r.total
    label = r.extra.get("kind_label")
    what = f"unread {label} " if label else "unread "
    count = "no" if n == 0 else _n(n)
    return f"You have {count} {what}{_plural(n, 'alert', 'alerts')}."


def _count_new_orders(r: WorkResult, p: NewOrdersParams, ctx: Ctx) -> str:
    n = r.total
    when = "in the last day" if p.days == 1 else f"in the last {p.days} days"
    count = "no" if n == 0 else _n(n, capped=r.scan_capped)
    return f"You have {count} new-order {_plural(n, 'alert', 'alerts')} {when}."


def _detail_new_orders(r: WorkResult, p: NewOrdersParams, ctx: Ctx) -> str | None:
    k = int(r.extra.get("cases") or 0)
    if r.total == 0 or k == 0:
        return None
    return f"{_plural(r.total, 'It names', 'They name')} {k:,} {_plural(k, 'case', 'cases')}."


def _count_attention(r: WorkResult, p: NoParams, ctx: Ctx) -> str:
    n = r.total
    if n == 0:
        return "Nothing needs your attention today."
    return f"{_n(n, capped=r.scan_capped)} {_plural(n, 'thing needs', 'things need')} your attention today."


def _detail_attention(r: WorkResult, p: NoParams, ctx: Ctx) -> str | None:
    h = r.extra.get("headline") or {}
    parts = [
        f"Files with you: {int((h.get('files_with_me') or {}).get('total') or 0):,}",
        f"overdue: {int((h.get('overdue_actions') or {}).get('total') or 0):,}",
        f"hearings in the next 7 days: {int((h.get('hearings_week') or {}).get('total') or 0):,}",
    ]
    if h.get("next_dates_to_confirm") is not None:
        parts.append(f"next dates to confirm: {int(h['next_dates_to_confirm']):,}")
    claim = h.get("to_claim")
    if claim is not None:
        parts.append(f"cases to claim: {int(claim.get('high') or 0) + int(claim.get('medium') or 0):,}")
    return "; ".join(parts) + "."


def _count_claimed_by_me(r: WorkResult, p: ClaimPeriodParams, ctx: Ctx) -> str:
    n = r.total
    cases = "no cases" if n == 0 else f"{_n(n)} {_plural(n, 'case', 'cases')}"
    if p.period == "all":
        return f"You have claimed {cases} in all."
    return f"You claimed {cases} {_period_words(p.period)}."


def _detail_claimed_by_me(r: WorkResult, p: ClaimPeriodParams, ctx: Ctx) -> str | None:
    return CLAIMED_BY_ME_NOTE


def _split(r: WorkResult) -> str:
    return ", ".join(f"{name} {k:,}" for name, k in r.extra.get("per_department") or [])


def _count_department_claimed(r: WorkResult, p: ClaimPeriodParams, ctx: Ctx) -> str:
    n = r.total
    see = "" if r.whole else " that you can see"
    cases = "no cases" if n == 0 else f"{_n(n)} {_plural(n, 'case', 'cases')}"
    if len(r.departments) >= 2:
        if p.period == "all":
            return f"Your departments have claimed {cases}{see} in all: {_split(r)}."
        return f"Your departments claimed {cases}{see} {_period_words(p.period)}: {_split(r)}."
    name = r.departments[0].name if r.departments else "Your department"
    if p.period == "all":
        return f"{name} has claimed {cases}{see} in all."
    return f"{name} claimed {cases}{see} {_period_words(p.period)}."


def _count_awaiting(r: WorkResult, p: BandParams, ctx: Ctx) -> str:
    n = r.total
    band = {"strong": "strongly ", "possible": "possibly "}.get(p.band, "")
    if len(r.departments) >= 2:
        count = "No cases are" if n == 0 else f"{_n(n)} {_plural(n, 'case is', 'cases are')}"
        return f"{count} {band}recommended to your departments and waiting to be claimed: {_split(r)}."
    name = r.departments[0].name if r.departments else "your department"
    count = "No cases are" if n == 0 else f"{_n(n)} {_plural(n, 'case is', 'cases are')}"
    return f"{count} {band}recommended to {name} and waiting to be claimed."


def _detail_awaiting(r: WorkResult, p: BandParams, ctx: Ctx) -> str | None:
    s, q = int(r.extra.get("strong") or 0), int(r.extra.get("possible") or 0)
    if not s and not q:
        return None
    return f"{s:,} strong and {q:,} possible."


def shown_line(total: int, shown: int, *, capped: bool = False) -> str | None:
    """Decision 4.3: "Showing all 14." or "Showing the first 25 of 41. Open the full list for the rest."."""
    if total <= 0 or shown <= 0:
        return None
    if shown >= total and not capped:
        return "Showing it." if total == 1 else f"Showing all {total:,}."
    return f"Showing the first {shown:,} of {_n(total, capped=capped)}. Open the full list for the rest."


# ------------------------------------------------------------------------------------------------ the links


def _href_pending(p: PendingParams, r: WorkResult, ctx: Ctx) -> str:
    return "/inbox/with-me?overdue=true" if p.when == "overdue" else "/inbox/with-me"


def _href_sent(p: SentParams, r: WorkResult, ctx: Ctx) -> str:
    return "/inbox/sent" if p.still_out else "/inbox/sent?earlier=true"


def _href_range(p: RangeParams, r: WorkResult, ctx: Ctx) -> str:
    start, _ = resolve_range(p, ctx.today)
    return f"/calendar?day={start.isoformat()}"


def _href_tomorrow(p: NoParams, r: WorkResult, ctx: Ctx) -> str:
    return f"/calendar?day={(ctx.today + timedelta(days=1)).isoformat()}"


def _href_unread(p: AlertParams, r: WorkResult, ctx: Ctx) -> str:
    return "/alerts?unread=true" + ("" if p.kind == "any" else f"&kind={p.kind}")


def _href_department(p: ClaimPeriodParams, r: WorkResult, ctx: Ctx) -> str:
    if r.href_department:
        return f"/inbox/department?department={r.href_department}"
    return "/inbox/my-cases"


def _href_awaiting(p: BandParams, r: WorkResult, ctx: Ctx) -> str:
    band = {"strong": "&band=high", "possible": "&band=medium"}.get(p.band, "")
    return f"/claim/recommended?department={r.href_department or ''}{band}"


# ------------------------------------------------------------------------------------------------ the registry


def _const(value: str) -> Callable[[Any, WorkResult, Ctx], str]:
    return lambda p, r, c: value


CLAIM_GUARD = (Permission.CASES_VIEW_SCOPE,)
WORK_QUESTIONS: tuple[WorkQuestion, ...] = (
    WorkQuestion(
        key="pending_actions",
        label="Pending Actions With Me",
        example="Which of my cases has a pending action due this week?",
        params=PendingParams,
        list_label="Case Inbox · With Me",
        run=run_pending_actions,
        count_sentence=_count_pending,
        detail_sentence=_detail_pending,
        full_list_href=_href_pending,
    ),
    WorkQuestion(
        key="cases_with_me",
        label="Files With Me",
        example="Which case files are with me?",
        params=NoParams,
        list_label="Case Inbox · With Me",
        run=run_cases_with_me,
        count_sentence=_count_with_me,
        detail_sentence=_detail_with_me,
        full_list_href=_const("/inbox/with-me"),
    ),
    WorkQuestion(
        key="sent_by_me",
        label="Files I Sent or Recalled",
        example="Cases I sent in the last 7 days",
        params=SentParams,
        list_label="Case Inbox · Sent by Me",
        run=run_sent_by_me,
        count_sentence=_count_sent,
        detail_sentence=_detail_sent,
        full_list_href=_href_sent,
    ),
    WorkQuestion(
        key="my_hearings",
        label="Hearings of My Cases",
        example="My hearings next week",
        params=RangeParams,
        list_label="My Calendar · Hearings",
        run=run_my_hearings,
        count_sentence=_count_hearings,
        full_list_href=_href_range,
    ),
    WorkQuestion(
        key="listed_tomorrow",
        label="My Cases Listed Tomorrow",
        example="Which of my cases are listed tomorrow?",
        params=NoParams,
        list_label="My Calendar · Tomorrow",
        run=run_listed_tomorrow,
        count_sentence=_count_tomorrow,
        full_list_href=_href_tomorrow,
    ),
    WorkQuestion(
        key="my_due_dates",
        label="My Due Dates",
        example="What are my due dates this week?",
        params=RangeParams,
        list_label="My Calendar · Due Dates",
        run=run_my_due_dates,
        count_sentence=_count_due,
        detail_sentence=_detail_due,
        full_list_href=_href_range,
    ),
    WorkQuestion(
        key="unread_alerts",
        label="My Unread Alerts",
        example="Do I have unread alerts?",
        params=AlertParams,
        list_label="Alerts · Unread",
        run=run_unread_alerts,
        count_sentence=_count_unread,
        full_list_href=_href_unread,
    ),
    WorkQuestion(
        key="new_orders",
        label="New Orders in My Cases",
        example="Any new orders in my cases this week?",
        params=NewOrdersParams,
        list_label="Alerts · New Orders",
        run=run_new_orders,
        count_sentence=_count_new_orders,
        detail_sentence=_detail_new_orders,
        full_list_href=_const("/alerts?kind=new_order"),
    ),
    WorkQuestion(
        key="needs_attention",
        label="What Needs My Attention",
        example="What needs my attention today?",
        params=NoParams,
        list_label="Dashboard · Needs Your Attention",
        run=run_needs_attention,
        count_sentence=_count_attention,
        detail_sentence=_detail_attention,
        full_list_href=_const("/"),
    ),
    WorkQuestion(
        key="claimed_by_me",
        label="Cases I Claimed",
        example="How many cases were claimed by me?",
        params=ClaimPeriodParams,
        list_label="Case Inbox · My Cases · Claimed by Me",
        run=run_claimed_by_me,
        count_sentence=_count_claimed_by_me,
        detail_sentence=_detail_claimed_by_me,
        full_list_href=_const("/inbox/my-cases"),
        guard=CLAIM_GUARD,
        detail_newline=True,
    ),
    WorkQuestion(
        key="department_claimed",
        label="Cases My Department Claimed",
        example="How many cases has my department claimed in the last 30 days?",
        params=ClaimPeriodParams,
        list_label="Case Inbox · Department",
        run=run_department_claimed,
        count_sentence=_count_department_claimed,
        full_list_href=_href_department,
        guard=CLAIM_GUARD,
        department_rule=Permission.CASES_VIEW_SCOPE,
    ),
    WorkQuestion(
        key="awaiting_claim",
        label="Cases Waiting to Be Claimed",
        example="Which cases are waiting to be claimed?",
        params=BandParams,
        list_label="Case Claim · Recommended",
        run=run_awaiting_claim,
        count_sentence=_count_awaiting,
        detail_sentence=_detail_awaiting,
        full_list_href=_href_awaiting,
        guard=(Permission.CASES_CLAIM,),
        department_rule=Permission.CASES_CLAIM,
    ),
)
BY_KEY: dict[str, WorkQuestion] = {q.key: q for q in WORK_QUESTIONS}


# ------------------------------------------------------------------------------------------------ the guards


def guard_refusal(session: Session, user: User, q: WorkQuestion) -> str | None:
    """Decision 3: None when the asker passes the question's guard, otherwise the fixed sentence. For 11 and 12 a
    login with no department (a State-wide reader too) gets the no-department sentence; one whose departments all
    fail the rule gets "You do not have this list."."""
    if not any(access.has(session, user, g) for g in q.guard):
        return NO_LIST
    if q.department_rule is not None:
        members, any_department = _departments(session, user, q.department_rule)
        if not any_department:
            return NO_DEPARTMENT
        if not members:
            return NO_LIST
    return None


def passes(session: Session, user: User, key: str) -> bool:
    q = BY_KEY.get(key)
    return q is not None and guard_refusal(session, user, q) is None


def available(session: Session, user: User) -> list[WorkQuestion]:
    """The questions whose guard the asker passes (`GET /assistant/status` `work_questions`)."""
    return [q for q in WORK_QUESTIONS if guard_refusal(session, user, q) is None]


# ------------------------------------------------------------------------------------------------ the tools


_PERIOD_SCHEMA = {"type": "string", "enum": ["last_7_days", "last_30_days", "all"]}
_DATE_SCHEMA = {"type": "string", "format": "date", "pattern": r"^\d{4}-\d{2}-\d{2}$"}
_RANGE_PROPS = {
    "range": {"type": "string", "enum": ["today", "tomorrow", "this_week", "next_week", "dates"]},
    "from": {**_DATE_SCHEMA, "description": "with range dates only (YYYY-MM-DD)"},
    "to": {**_DATE_SCHEMA, "description": "with range dates only (YYYY-MM-DD), at most 31 days after from"},
}
_PROPS: dict[str, dict[str, Any]] = {
    "pending_actions": {"when": {"type": "string", "enum": ["overdue", "due_this_week", "all"]}},
    "cases_with_me": {},
    "sent_by_me": {"period": _PERIOD_SCHEMA, "still_out": {"type": "boolean"}},
    "my_hearings": _RANGE_PROPS,
    "listed_tomorrow": {},
    "my_due_dates": _RANGE_PROPS,
    "unread_alerts": {"kind": {"type": "string", "enum": ["any", *[k.value for k in AlertKind]]}},
    "new_orders": {"days": {"type": "integer", "minimum": 1, "maximum": 30}},
    "needs_attention": {},
    "claimed_by_me": {"period": _PERIOD_SCHEMA},
    "department_claimed": {"period": _PERIOD_SCHEMA},
    "awaiting_claim": {"band": {"type": "string", "enum": ["strong", "possible", "any"]}},
}


def tool_schemas() -> list[dict[str, Any]]:
    """Ollama `tools`: one function per question, with JSON schemas of enums, `YYYY-MM-DD` dates and
    `additionalProperties: false`."""
    return [
        {
            "type": "function",
            "function": {
                "name": q.key,
                "description": f"{q.label}. Example: {q.example}",
                "parameters": {
                    "type": "object",
                    "properties": _PROPS[q.key],
                    "required": [],
                    "additionalProperties": False,
                },
            },
        }
        for q in WORK_QUESTIONS
    ]


def validate_choice(tool_calls: list[dict[str, Any]] | None, today: date) -> tuple[str, BaseModel] | None:
    """Decision 8.2: exactly one call, a name on the allow-list and arguments passing the question's strict model
    (and the date bounds against today); otherwise None."""
    calls = list(tool_calls or [])
    if len(calls) != 1 or not isinstance(calls[0], dict):
        return None
    fn = calls[0].get("function")
    if not isinstance(fn, dict):
        return None
    name, args = fn.get("name"), fn.get("arguments", {})
    if not isinstance(name, str) or name not in BY_KEY:
        return None
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except ValueError:
            return None
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return None
    try:
        params = BY_KEY[name].params.model_validate(args)
    except ValidationError:
        return None
    if not dates_ok(params, today):
        return None
    return name, params


# ------------------------------------------------------------------------------------------------ the keyword table


def _rx(*phrases: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(phrases) + r")\b")


_DEPT_CLAIMED = _rx(
    "department claimed",
    "department has claimed",
    "we claimed",
    "our department claimed",
    "claimed by my department",
    "claimed by our department",
)
_CLAIM_WORD = _rx("claimed", "claim")
_DEPT_WORD = _rx("department", "departments", "we", "our")
# (rank, key, pattern): rank 1 the specific phrases, rank 2 the general words, rank 3 the most general
_RULES: tuple[tuple[int, str, re.Pattern[str]], ...] = (
    (
        1,
        "awaiting_claim",
        _rx("waiting to be claimed", "to be claimed", "to claim", "recommended to", "recommendations"),
    ),
    (1, "claimed_by_me", _rx("claimed by me", "i claimed", "did i claim", "my claims", "have i claimed")),
    (1, "new_orders", _rx("new orders?")),
    (1, "my_due_dates", _rx("due dates?", "dates? to confirm", "next dates? to confirm")),
    (2, "pending_actions", _rx("pending", "overdue", "due")),
    (2, "sent_by_me", _rx("sent", "recalled", "send")),
    (2, "unread_alerts", _rx("alerts?", "unread")),
    (2, "my_hearings", _rx("hearings?")),
    (2, "needs_attention", _rx("attention")),
    (3, "cases_with_me", _rx("with me", "my files")),
    (3, "needs_attention", _rx("today")),
)
_LISTED = _rx("list", "lists", "listed", "cause list", "cause lists")


def _matches(q: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    if _DEPT_CLAIMED.search(q) or (
        _CLAIM_WORD.search(q) and _DEPT_WORD.search(q) and "to be claimed" not in q
    ):
        found.append((1, "department_claimed"))
    if "tomorrow" in q and _LISTED.search(q):
        found.append((1, "listed_tomorrow"))
    for rank, key, pattern in _RULES:
        if key == "claimed_by_me" and any(k == "department_claimed" for _, k in found):
            continue  # "claimed" with "department", "we" or "our" goes to department_claimed first
        if (
            key == "awaiting_claim"
            and any(k == "department_claimed" for _, k in found)
            and not re.search(r"\b(waiting to be claimed|to be claimed|recommended to|recommendations)\b", q)
        ):
            continue
        if pattern.search(q):
            found.append((rank, key))
    return found


def _period(q: str) -> str | None:
    if re.search(r"\b(7 days|past week|week)\b", q):
        return "last_7_days"
    if re.search(r"\b(30 days|past month|month)\b", q):
        return "last_30_days"
    return None


def _range(q: str) -> dict[str, Any]:
    if re.search(r"\bnext week\b", q):
        return {"range": "next_week"}
    if re.search(r"\btomorrow\b", q):
        return {"range": "tomorrow"}
    if re.search(r"\btoday\b", q):
        return {"range": "today"}
    return {"range": "this_week"}


def _params_for(key: str, q: str) -> dict[str, Any]:
    if key == "pending_actions":
        if re.search(r"\boverdue\b", q):
            return {"when": "overdue"}
        if re.search(r"\b(this week|week|7 days)\b", q):
            return {"when": "due_this_week"}
        return {}
    if key == "sent_by_me":
        out: dict[str, Any] = {}
        period = _period(q)
        if period:
            out["period"] = period
        elif re.search(r"\b(ever|in all|all)\b", q):
            out["period"] = "all"
        if re.search(r"\b(still|not returned|still out)\b", q):
            out["still_out"] = True
        return out
    if key in ("my_hearings", "my_due_dates"):
        return _range(q)
    if key == "new_orders":
        if re.search(r"\btoday\b", q):
            return {"days": 1}
        if re.search(r"\b(30 days|past month|month)\b", q):
            return {"days": 30}
        return {}
    if key in ("claimed_by_me", "department_claimed"):
        period = _period(q)
        return {"period": period} if period else {}
    if key == "awaiting_claim":
        if re.search(r"\bstrong(ly)?\b", q):
            return {"band": "strong"}
        if re.search(r"\bpossible\b", q):
            return {"band": "possible"}
        return {}
    return {}


def keyword_choice(question: str, today: date) -> tuple[str, BaseModel] | None | Literal["ambiguous"]:
    """Decision 8.3: the ordered keyword table. The lowest rank with a match decides; two questions at that rank are
    `ambiguous`; no match is None. Dates come only from fixed words."""
    q = re.sub(r"\s+", " ", (question or "").lower().replace("’", "'")).strip()
    found = _matches(q)
    if not found:
        return None
    best = min(rank for rank, _ in found)
    keys = list(dict.fromkeys(k for rank, k in found if rank == best))
    if len(keys) != 1:
        return "ambiguous"
    key = keys[0]
    try:
        params = BY_KEY[key].params.model_validate(_params_for(key, q))
    except ValidationError:
        return None
    return key, params


# ------------------------------------------------------------------------------------------------ the answer


def no_question() -> WorkAnswer:
    """Decision 8.4: no question chosen; no service runs."""
    return WorkAnswer(outcome="no_match", content=NO_MATCH_TEXT, citations=None, info={"question": None})


def _citations(key: str, q: WorkQuestion, rows: list[WorkRow], as_of: datetime) -> list[dict[str, Any]]:
    return [
        {
            "source_kind": "work_row",
            "label": f"S{i}",
            "cited": True,
            "case_id": str(r.case_id) if r.case_id else None,
            "work": {
                "question": key,
                "list_label": q.list_label,
                "as_of": as_of.isoformat(),
                "fields": allowed(key, r.fields),
            },
        }
        for i, r in enumerate(rows, start=1)
    ]


def compose(q: WorkQuestion, result: WorkResult, params: Any, ctx: Ctx) -> str:
    """Decision 4: the count sentence, at most one detail sentence, the shown line. Names no case."""
    shown = min(len(result.rows), ctx.rows_cap)
    first = q.count_sentence(result, params, ctx)
    parts = [first[:1].upper() + first[1:]]
    detail = q.detail_sentence(result, params, ctx)
    if detail:
        parts.append(detail)
    line = shown_line(result.total, shown, capped=result.scan_capped)
    if line:
        parts.append(line)
    return "\n".join(parts)


def answer(
    session_factory: sessionmaker,
    user: User,
    key: str,
    params: BaseModel,
    *,
    rows_cap: int,
    now: datetime | None = None,
    cfg: ReportConfig | None = None,
) -> WorkAnswer:
    """Decisions 3 to 10 and 13: the guard (its fixed sentence when it fails, no service run), then the question in
    one read-only session with `statement_timeout`, the content and the citations. A service out of time is a failed
    answer, family `timeout`; any other error family `error` (logged by the caller by class only)."""
    q = BY_KEY[key]
    now = now or clock.now_utc()
    today = clock.today_ist(now)
    cap = max(1, min(int(rows_cap), 25))
    started = time.monotonic()
    info: dict[str, Any] = {"question": key, "params": dump(params), "list_label": q.list_label}
    with session_factory() as s:
        try:
            s.execute(text("SET TRANSACTION READ ONLY"))
            s.execute(text(f"SET LOCAL statement_timeout = {WORK_STATEMENT_MS}"))
            u = s.get(User, user.id)
            refusal = guard_refusal(s, u, q)
            if refusal is not None:
                info.update({"total": 0, "shown": 0, "scan_capped": False, "departments": []})
                info["run_ms"] = int((time.monotonic() - started) * 1000)
                return WorkAnswer(outcome="no_match", content=refusal, citations=None, info=info)
            ctx = Ctx(s, u, now, today, cap, cfg or ReportConfig.from_settings())
            result = q.run(ctx, params)
            result.rows = result.rows[:cap]
            content = compose(q, result, params, ctx)
            citations = _citations(key, q, result.rows, now)
            info.update(
                {
                    "total": int(result.total),
                    "shown": len(result.rows),
                    "scan_capped": bool(result.scan_capped),
                    "departments": [d.code for d in result.departments],
                    "full_list_href": q.full_list_href(params, result, ctx),
                }
            )
        except OperationalError as exc:
            words = str(exc).lower()
            info["run_ms"] = int((time.monotonic() - started) * 1000)
            if "statement timeout" in words or "canceling statement" in words:
                return WorkAnswer(outcome="failed", content=TIMEOUT_TEXT, info=info, family="timeout")
            raise
        finally:
            s.rollback()
    info["run_ms"] = int((time.monotonic() - started) * 1000)
    return WorkAnswer(outcome="answered", content=content, citations=citations, info=info)
