"""The System health screen's court cards (design `api-health-checker`, decisions 3, 4, 10, 14): the catalogue of the
17 NAPIX High Court APIs the integration layer uses, each card's last result and figures read from `napix_call_log`
over the last 7 days (IST) with no call made, the status rules and the overall line.

- **Answered** is a call with `ok`, or one the court refused as "not found" (`NapixNotFound`) or a bad input
  (`NapixInputError`): the court replied, so the API is up. Every other row failed.
- **Figures** come from two grouped queries over `called_at >= now() - 7 days` (`ix_napix_call_log_called_at`): one by
  (api, IST hour) and one with `percentile_cont` over 24 h; the last three calls per API from a third, all under the
  report statement timeout. `cnr_alt` and the three unused APIs are not cards, so their rows are never counted.
- **Who** made a call reads "background work", "a person" or "your test"; never a name.
- The test's state on each card (available, reason, next allowed time) uses the same rules as the test's guard
  (`services/napix_api_check.py`): the per-API interval counted from the audit rows `napix.api_tested` (the Connection
  check also from the data-health connectivity check), and the caller's hourly cap. Read-only; never calls NAPIX."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from aslms.core.config import Settings
from aslms.domain.ops import COUNTED_CALL_SQL
from aslms.domain.org import User
from aslms.integration.base import CauseListRef
from aslms.integration.napix.hc import API, NapixHighCourt
from aslms.services import data_health, napix_samples, napix_window
from aslms.services.access import Member
from aslms.services.audit_search import to_ist
from aslms.services.reporting_common import IST_ZONE, with_timeout

TEST_ACTION = "napix.api_tested"
TOKEN_ACTION = "napix.token_checked"
# the per-person hourly cap counts sends and token checks together (design system-health-inspector, decision 8)
CAP_ACTIONS = (TEST_ACTION, TOKEN_ACTION)
WINDOW = timedelta(days=7)
DAY = timedelta(hours=24)
ANSWERED_FAMILIES = ("NapixNotFound", "NapixInputError")
SLOW_P95_MS = 20_000  # half the 40 s NAPIX timeout (decision 4)
STATUS_WORDS = {"ok": "Working", "warn": "Unsteady", "down": "Failing", "unknown": "No recent calls"}
SERVICE_WORDS = {"ok": "Working", "warn": "Unsteady", "down": "Not working", "unknown": "Not known"}
RANK = {"unknown": 0, "ok": 1, "warn": 2, "down": 3}
GROUPS: tuple[tuple[str, str], ...] = (
    ("masters", "Connection and masters"),
    ("causelists", "Cause lists"),
    ("cases", "Case details"),
    ("searches", "Searches"),
)


class UnknownApi(LookupError):
    """No card has this key (HTTP 404 `not_found`)."""


Invoke = Callable[[NapixHighCourt, dict[str, Any]], Any]


@dataclass(frozen=True)
class ApiEntry:
    key: str
    label_key: str
    label: str
    group: str
    method: str
    input_fields: tuple[str, ...]
    kind: str  # the summary: rows, record or pdf (decision 9)
    invoke: Invoke

    @property
    def path(self) -> str:
        return API[self.key]

    @property
    def chooser(self) -> Callable:
        return napix_samples.CHOOSERS[self.key]


def _ref(v: dict[str, Any]) -> CauseListRef:
    return CauseListRef(v["list_date"], v["bench_id"], v["causelist_id"], None)


CATALOGUE: tuple[ApiEntry, ...] = (
    ApiEntry("overview", "connection_check", "Connection check", "masters", "GET", (), "record",
             lambda hc, v: hc.overview()),
    ApiEntry("state", "high_courts", "High Courts list", "masters", "GET", (), "rows",
             lambda hc, v: hc.state_master()),
    ApiEntry("district", "districts", "Districts list", "masters", "GET", ("state_code",), "rows",
             lambda hc, v: hc.district_master()),
    ApiEntry("bench_master", "benches", "Benches list", "masters", "GET", ("state_code",), "rows",
             lambda hc, v: hc.bench_master()),
    ApiEntry("case_type", "case_types", "Case types list", "masters", "GET", ("est_code",), "rows",
             lambda hc, v: hc.case_type_master()),
    ApiEntry("act", "acts", "Acts list", "masters", "GET", (), "rows", lambda hc, v: hc.act_master()),
    ApiEntry("causelist_bench", "causelist_benches", "Benches sitting on a day", "causelists", "GET",
             ("est_code", "causelist_date"), "rows", lambda hc, v: hc.causelist_benches(v["list_date"])),
    ApiEntry("causelist_details", "causelist_details", "Lists of a bench", "causelists", "GET",
             ("est_code", "causelist_date", "bench_id"), "rows",
             lambda hc, v: hc.causelist_details(v["list_date"], v["bench_id"])),
    ApiEntry("show_causelist", "causelist_pdf", "Cause list PDF", "causelists", "GET",
             ("est_code", "bench_id", "causelist_id", "causelist_date"), "pdf",
             lambda hc, v: hc.show_causelist(_ref(v))),
    ApiEntry("cnr", "case_by_cnr", "Case details by CNR", "cases", "GET", ("cino",), "record",
             lambda hc, v: hc.case_by_cnr(v["cnr"], fallback=False)),
    ApiEntry("current_status", "case_status", "Case status", "cases", "POST", ("cino",), "record",
             lambda hc, v: hc.current_status([v["cnr"]])),
    ApiEntry("order", "order_pdf", "Order PDF", "cases", "GET", ("cino", "order_no", "order_date"), "pdf",
             lambda hc, v: hc.show_order(v["cnr"], v["order_no"], v["order_date"])),
    ApiEntry("show_business", "hearing_business", "Hearing business", "cases", "GET", ("cino", "business_date"),
             "record", lambda hc, v: hc.show_business(v["cnr"], v["business_date"])),
    ApiEntry("case_search", "search_case_number", "Search by case number", "searches", "GET",
             ("est_code", "case_type", "reg_no", "reg_year"), "rows",
             lambda hc, v: hc.search_case_number(int(v["case_type"]), int(v["reg_no"]), int(v["reg_year"]))),
    ApiEntry("filing", "search_filing_number", "Search by filing number", "searches", "GET",
             ("est_code", "case_type", "fil_no", "fil_year"), "rows",
             lambda hc, v: hc.search_filing(int(v["case_type"]), int(v["fil_no"]), int(v["fil_year"]))),
    ApiEntry("party_name", "search_party_name", "Search by party name", "searches", "GET",
             ("est_code", "pend_disp", "litigant_name", "reg_year"), "rows",
             lambda hc, v: hc.search_party(v["name"], int(v["reg_year"]), v["pend_disp"])),
    ApiEntry("advocate_name", "search_advocate_name", "Search by advocate name", "searches", "GET",
             ("est_code", "pend_disp", "advocate_name", "reg_year"), "rows",
             lambda hc, v: hc.search_advocate(v["name"], int(v["reg_year"]), v["pend_disp"])),
)  # fmt: skip
BY_KEY: dict[str, ApiEntry] = {e.key: e for e in CATALOGUE}
BY_PATH: dict[str, ApiEntry] = {e.path: e for e in CATALOGUE}
PATHS: list[str] = [e.path for e in CATALOGUE]


def entry(key: str) -> ApiEntry:
    try:
        return BY_KEY[key]
    except KeyError:
        raise UnknownApi(f"no court API card {key!r}") from None


# ------------------------------------------------------------------------------------------------ status rules


def card_status(last: dict[str, Any] | None, h24: dict[str, Any]) -> str:
    """Decision 4, pure. `last` = {`answered`, `last3_all_failed`} of the latest call in 7 days (None: none);
    `h24` = {`calls`, `answered`, `p95_ms`}."""
    if last is None:
        return "unknown"
    calls = int(h24.get("calls") or 0)
    answered = int(h24.get("answered") or 0)
    rate = answered / calls if calls else None
    last_failed = not last.get("answered")
    if last_failed and (
        (calls >= 3 and rate is not None and rate < 0.5) or bool(last.get("last3_all_failed"))
    ):
        return "down"
    p95 = h24.get("p95_ms")
    if (
        last_failed
        or (calls >= 5 and rate is not None and rate < 0.9)
        or (p95 is not None and p95 > SLOW_P95_MS)
    ):
        return "warn"
    return "ok"


def plain_reason(
    error_family: str | None, napix_status: int | None = None, http_status: int | None = None
) -> str:
    """A readable reason for a call's outcome (decision 9); never the error text."""
    if error_family is None:
        if http_status == 401:
            return "The court's sign-in had expired; ASLMS renewed it and asked again"
        if http_status is not None and http_status != 200:
            return f"The court's gateway answered HTTP {http_status}"
        return "The court answered"
    if error_family == "NapixNotFound":
        return "The court answered: no record found for this input"
    if error_family == "NapixInputError":
        code = f" (court status {napix_status})" if napix_status else ""
        return f"The court answered but did not accept the input{code}"
    if error_family == "NapixEmptyResponse":
        return "The court sent an empty answer (a known intermittent fault of the gateway)"
    if error_family == "NapixUnavailable":
        if napix_status == 629:
            return "The court reported an unexpected error (court status 629)"
        if http_status == 429:
            return "The court's gateway refused the call: too many calls (HTTP 429)"
        if http_status:
            return f"The court's service is busy or down (HTTP {http_status})"
        return "The court could not be reached or did not answer in time"
    if error_family == "NapixGatewayError":
        return "The gateway answered instead of the court (a wrong address or an API not subscribed)"
    if error_family == "NapixAuthError":
        return "The court refused ASLMS's credentials or key"
    if error_family == "NapixProtocolError":
        return "The court's answer could not be read (encryption or format)"
    return "The court could not be reached"


def _who(user_id: uuid.UUID | None, me: uuid.UUID | None) -> str:
    if user_id is None:
        return "background"
    return "you" if me is not None and user_id == me else "person"


# ------------------------------------------------------------------------------------------------ the readings

_ANSWERED_SQL = "(ok OR error_family IN ('NapixNotFound', 'NapixInputError'))"
# the rows that are API calls: a token renewal's 401 step (`http_status` 401, no family) is left out of the rates, the
# percentiles, the last-three rule and the last calls; the quota window and per-person counts keep it (design
# api-health-checker-followups, decision 5)
_COUNTED_SQL = COUNTED_CALL_SQL


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _ist_hour(at: datetime) -> datetime:
    """The IST hour start of `at`, naive (as `date_trunc('hour', called_at AT TIME ZONE 'Asia/Kolkata')`)."""
    return at.astimezone(IST_ZONE).replace(minute=0, second=0, microsecond=0, tzinfo=None)


def _hourly(
    session: Session, since: datetime, paths: list[str]
) -> dict[str, dict[datetime, tuple[int, int, float]]]:
    rows = session.execute(
        text(
            f"""
            SELECT api, date_trunc('hour', called_at AT TIME ZONE 'Asia/Kolkata') AS h, count(*) AS calls,
                count(*) FILTER (WHERE {_ANSWERED_SQL}) AS answered, avg(duration_ms) AS avg_ms
            FROM napix_call_log
            WHERE called_at >= :since AND api = ANY(:apis) AND {_COUNTED_SQL}
            GROUP BY api, h
            """
        ),
        {"since": since, "apis": paths},
    ).all()
    out: dict[str, dict[datetime, tuple[int, int, float]]] = defaultdict(dict)
    for api, h, calls, answered, avg_ms in rows:
        out[api][h] = (int(calls), int(answered), float(avg_ms or 0))
    return out


def _day(session: Session, since: datetime, paths: list[str]) -> dict[str, dict[str, Any]]:
    rows = session.execute(
        text(
            f"""
            SELECT api, count(*) AS calls, count(*) FILTER (WHERE {_ANSWERED_SQL}) AS answered,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms) AS p50,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95
            FROM napix_call_log
            WHERE called_at >= :since AND api = ANY(:apis) AND {_COUNTED_SQL}
            GROUP BY api
            """
        ),
        {"since": since, "apis": paths},
    ).all()
    return {
        api: {
            "calls": int(calls),
            "answered": int(answered),
            "p50_ms": int(round(p50)) if p50 is not None else None,
            "p95_ms": int(round(p95)) if p95 is not None else None,
        }
        for api, calls, answered, p50, p95 in rows
    }


_CALL_COLUMNS = "called_at, ok, error_family, duration_ms, http_status, napix_status, user_id"


def _latest(session: Session, since: datetime, paths: list[str], per_api: int = 3) -> dict[str, list[dict]]:
    rows = session.execute(
        text(
            f"""
            SELECT api, {_CALL_COLUMNS}, answered FROM (
                SELECT api, {_CALL_COLUMNS}, {_ANSWERED_SQL} AS answered,
                    row_number() OVER (PARTITION BY api ORDER BY called_at DESC, id DESC) AS rn
                FROM napix_call_log
                WHERE called_at >= :since AND api = ANY(:apis) AND {_COUNTED_SQL}
            ) t
            WHERE rn <= :n
            ORDER BY api, called_at DESC
            """
        ),
        {"since": since, "apis": paths, "n": per_api},
    ).mappings()
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        out[r["api"]].append(dict(r))
    return out


def _recent(session: Session, since: datetime, path: str, limit: int = 10) -> list[dict]:
    return [
        dict(r)
        for r in session.execute(
            text(
                f"""
                SELECT {_CALL_COLUMNS}, {_ANSWERED_SQL} AS answered FROM napix_call_log
                WHERE called_at >= :since AND api = :api AND {_COUNTED_SQL}
                ORDER BY called_at DESC, id DESC
                LIMIT :n
                """
            ),
            {"since": since, "api": path, "n": limit},
        ).mappings()
    ]


def _call_out(row: dict, me: uuid.UUID | None) -> dict[str, Any]:
    return {
        "called_at": to_ist(row["called_at"]),
        "answered": bool(row["answered"]),
        "ok": bool(row["ok"]),
        "duration_ms": int(row["duration_ms"] or 0),
        "http_status": row["http_status"],
        "napix_status": row["napix_status"],
        "error_family": row["error_family"],
        "reason": plain_reason(row["error_family"], row["napix_status"], row["http_status"]),
        "by": _who(row["user_id"], me),
    }


def _rate(answered: int, calls: int) -> float | None:
    return round(answered / calls, 4) if calls else None


# ------------------------------------------------------------------------------------------------ the test's limits


def last_tests(session: Session, since: datetime) -> dict[str, dict[str, Any]]:
    """The latest `napix.api_tested` row per API key since `since` (`ix_audit_log_created_at`)."""
    rows = session.execute(
        text(
            """
            SELECT DISTINCT ON (after->>'api') after->>'api' AS api, created_at, (after->>'ok')::boolean AS ok,
                actor_user_id
            FROM audit_log
            WHERE action = :action AND created_at >= :since
            ORDER BY after->>'api', created_at DESC, id DESC
            """
        ),
        {"action": TEST_ACTION, "since": since},
    ).mappings()
    return {r["api"]: dict(r) for r in rows}


def user_tests(session: Session, user_id: uuid.UUID | None, now: datetime) -> tuple[int, datetime | None]:
    """The caller's sends and token checks in the last hour and the oldest of them (`ix_audit_log_actor_created`)."""
    if user_id is None:
        return 0, None
    n, oldest = session.execute(
        text(
            """
            SELECT count(*), min(created_at) FROM audit_log
            WHERE actor_user_id = :uid AND action = ANY(:actions) AND created_at >= :since
            """
        ),
        {"uid": user_id, "actions": list(CAP_ACTIONS), "since": now - timedelta(hours=1)},
    ).one()
    return int(n or 0), oldest


def api_allowed_at(
    session: Session,
    settings: Settings,
    key: str,
    now: datetime,
    tests: dict[str, dict[str, Any]] | None = None,
    last_check: datetime | None = None,
) -> datetime | None:
    """When the next test of this API is allowed by the per-API interval (None: now). The Connection check also
    waits for the data-health connectivity check (`napix_admin.last_check_at`), and the other way round."""
    if tests is None:
        tests = last_tests(session, now - timedelta(seconds=settings.health_test_api_min_seconds))
    candidates: list[datetime] = []
    last = tests.get(key)
    if last is not None:
        candidates.append(last["created_at"] + timedelta(seconds=settings.health_test_api_min_seconds))
    if key == "overview":
        from aslms.services.napix_admin import last_check_at

        check = last_check if last_check is not None else last_check_at(session)
        if check is not None:
            wait = max(settings.health_test_api_min_seconds, settings.napix_health_check_min_seconds)
            candidates.append(check + timedelta(seconds=wait))
    at = max(candidates, default=None)
    return at if at is not None and at > now else None


def user_allowed_at(
    settings: Settings, count: int, oldest: datetime | None, now: datetime
) -> datetime | None:
    if count < settings.health_test_per_user_hour or oldest is None:
        return None
    at = oldest + timedelta(hours=1)
    return at if at > now else None


def _user_id(user: User | Member | None) -> uuid.UUID | None:
    return napix_window.user_id_of(user) if user is not None else None


# ------------------------------------------------------------------------------------------------ cards


def _figures(session: Session, now: datetime, *, hourly: bool = True) -> dict[str, Any]:
    since = now - WINDOW
    return {
        "hourly": _hourly(session, since, PATHS) if hourly else {},
        "day": _day(session, now - DAY, PATHS),
        "latest": _latest(session, since, PATHS),
    }


def _hours(buckets: dict[datetime, tuple[int, int, float]], now: datetime) -> list[dict[str, Any]]:
    top = _ist_hour(now)
    out = []
    for i in range(23, -1, -1):
        h = top - timedelta(hours=i)
        calls, answered, avg_ms = buckets.get(h, (0, 0, 0.0))
        out.append(
            {
                "hour": h.replace(tzinfo=IST_ZONE),
                "answered": answered,
                "failed": calls - answered,
                "avg_ms": int(round(avg_ms)) if calls else None,
            }
        )
    return out


def _days(buckets: dict[datetime, tuple[int, int, float]], now: datetime) -> list[dict[str, Any]]:
    today = now.astimezone(IST_ZONE).date()
    sums: dict[date, list[float]] = defaultdict(lambda: [0, 0, 0.0])
    for h, (calls, answered, avg_ms) in buckets.items():
        s = sums[h.date()]
        s[0] += calls
        s[1] += answered
        s[2] += avg_ms * calls
    out = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        calls, answered, total_ms = sums.get(d, [0, 0, 0.0])
        out.append(
            {
                "date": d,
                "calls": int(calls),
                "answered": int(answered),
                "failed": int(calls - answered),
                "avg_ms": int(round(total_ms / calls)) if calls else None,
            }
        )
    return out


def _status_of(latest: list[dict], h24: dict[str, Any]) -> str:
    if not latest:
        return card_status(None, h24)
    last3 = latest[:3]
    return card_status(
        {
            "answered": bool(latest[0]["answered"]),
            "last3_all_failed": len(last3) == 3 and not any(r["answered"] for r in last3),
        },
        h24,
    )


def _card(
    e: ApiEntry,
    figures: dict[str, Any],
    now: datetime,
    me: uuid.UUID | None,
    test: dict[str, Any],
    last_test: dict[str, Any] | None,
) -> dict[str, Any]:
    buckets = figures["hourly"].get(e.path, {})
    day = figures["day"].get(e.path, {"calls": 0, "answered": 0, "p50_ms": None, "p95_ms": None})
    latest = figures["latest"].get(e.path, [])
    d7_calls = sum(c for c, _a, _m in buckets.values())
    d7_answered = sum(a for _c, a, _m in buckets.values())
    h24 = {
        "calls": day["calls"],
        "answered": day["answered"],
        "failed": day["calls"] - day["answered"],
        "rate": _rate(day["answered"], day["calls"]),
        "p50_ms": day["p50_ms"],
        "p95_ms": day["p95_ms"],
    }
    status = _status_of(latest, h24)
    return {
        "key": e.key,
        "label": e.label,
        "label_key": e.label_key,
        "group": e.group,
        "status": status,
        "status_word": STATUS_WORDS[status],
        "last_call": _call_out(latest[0], me) if latest else None,
        "h24": h24,
        "d7": {
            "calls": d7_calls,
            "answered": d7_answered,
            "failed": d7_calls - d7_answered,
            "rate": _rate(d7_answered, d7_calls),
        },
        "hours": _hours(buckets, now),
        "test": test,
        "last_test": last_test,
    }


def _test_states(
    session: Session,
    settings: Settings,
    user: User | Member | None,
    now: datetime,
    keys: list[str],
    need_sample: bool = True,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any] | None]]:
    from aslms.services.napix_admin import last_check_at

    me = _user_id(user)
    week = last_tests(session, now - WINDOW)
    count, oldest = user_tests(session, me, now)
    cap_at = user_allowed_at(settings, count, oldest, now)
    check_at = last_check_at(session)
    switch = bool(settings.napix_configured)
    states: dict[str, dict[str, Any]] = {}
    lasts: dict[str, dict[str, Any] | None] = {}
    for key in keys:
        have, why = napix_samples.exists(session, settings, key) if need_sample else (True, None)
        api_at = api_allowed_at(session, settings, key, now, week, check_at)
        next_at = max((t for t in (api_at, cap_at) if t is not None), default=None)
        if not switch:
            reason = "Court calls are switched off on this server (NAPIX_ENABLED is false)"
        elif not have:
            reason = why
        elif cap_at is not None and (api_at is None or cap_at >= api_at):
            reason = f"You have made {count} tests in the last hour; the limit is {settings.health_test_per_user_hour}"
        elif next_at is not None:
            reason = "The next test of this API is not yet allowed"
        else:
            reason = None
        states[key] = {
            "available": switch and have and next_at is None,
            "reason": reason,
            "cost": 1,
            "next_allowed_at": to_ist(next_at),
        }
        t = week.get(key)
        lasts[key] = (
            {
                "at": to_ist(t["created_at"]),
                "ok": t["ok"],
                "by_you": me is not None and t["actor_user_id"] == me,
            }
            if t is not None
            else None
        )
    return states, lasts


def send_state(
    session: Session, settings: Settings, user: User | Member | None, key: str, now: datetime | None = None
) -> dict[str, Any]:
    """The console's Send state of one API (available, reason, cost, next allowed time): the card's `test` rules
    without the held-sample condition, since a send of typed values needs none (design system-health-inspector,
    decision 8); whether every value is typed is the form's own check."""
    states, _lasts = _test_states(session, settings, user, _now(now), [key], need_sample=False)
    return states[key]


def napix_cards(
    session: Session, settings: Settings, user: User | Member | None, now: datetime | None = None
) -> dict[str, Any]:
    """`SystemHealthOut`: the switch, the detected window, the four groups with their cards and the summary."""
    now = _now(now)
    with_timeout(session, settings.report_statement_timeout_seconds)
    window = napix_window.current(session, settings, now)
    figures = _figures(session, now)
    me = _user_id(user)
    tests, lasts = _test_states(session, settings, user, now, [e.key for e in CATALOGUE])
    cards = [_card(e, figures, now, me, tests[e.key], lasts[e.key]) for e in CATALOGUE]
    groups = [
        {"key": g, "label": label, "cards": [c for c in cards if c["group"] == g]} for g, label in GROUPS
    ]
    return {
        "as_of": to_ist(now),
        "napix_enabled": bool(settings.napix_configured),
        "window": data_health.window_block(session, settings, now, window),
        "groups": groups,
        "summary": summary(cards),
    }


def summary(cards: list[dict[str, Any]]) -> dict[str, int]:
    by = defaultdict(int)
    for c in cards:
        by[c["status"]] += 1
    return {
        "working": by["ok"],
        "unsteady": by["warn"],
        "failing": by["down"],
        "no_recent": by["unknown"],
        "total": len(cards),
    }


def api_detail(
    session: Session, settings: Settings, user: User | Member | None, key: str, now: datetime | None = None
) -> dict[str, Any]:
    """`ApiDetailOut`: the card, 7 daily buckets, the last 10 calls, the sample the test would use (labelled by the
    caller's visibility) and the technical details. Raises `UnknownApi`."""
    e = entry(key)
    now = _now(now)
    with_timeout(session, settings.report_statement_timeout_seconds)
    since = now - WINDOW
    figures = {
        "hourly": _hourly(session, since, [e.path]),
        "day": _day(session, now - DAY, [e.path]),
        "latest": _latest(session, since, [e.path]),
    }
    me = _user_id(user)
    tests, lasts = _test_states(session, settings, user, now, [e.key])
    card = _card(e, figures, now, me, tests[e.key], lasts[e.key])
    chosen = napix_samples.choose(session, settings, e.key, user)
    if isinstance(chosen, napix_samples.NoSample):
        sample = {"available": False, "label": None, "values": {}, "reason": chosen.reason}
    else:
        sample = {"available": True, "label": chosen.label, "values": chosen.public_values(), "reason": None}
    return {
        "card": card,
        "days": _days(figures["hourly"].get(e.path, {}), now),
        "recent": [_call_out(r, me) for r in _recent(session, since, e.path)],
        "sample": sample,
        "technical": {
            "name": e.key,
            "path": e.path,
            "method": e.method,
            "input_fields": list(e.input_fields),
        },
    }


def court_statuses(session: Session, settings: Settings, now: datetime | None = None) -> list[str]:
    """The court cards' statuses only (for the overall line of the services answer)."""
    now = _now(now)
    with_timeout(session, settings.report_statement_timeout_seconds)
    figures = _figures(session, now, hourly=False)
    out = []
    for e in CATALOGUE:
        day = figures["day"].get(e.path, {"calls": 0, "answered": 0, "p95_ms": None})
        out.append(_status_of(figures["latest"].get(e.path, []), day))
    return out


# ------------------------------------------------------------------------------------------------ the overall line


def overall(court: list[str], services: list[str]) -> dict[str, Any]:
    """Decision 10: the worst status across both sections. `unknown` never counts; a court card counts at most as
    `warn` (the court's service is outside ASLMS), though its own card stays red."""
    capped = ["warn" if s == "down" else s for s in court]
    known = [s for s in capped + list(services) if s != "unknown"]
    status = max(known, key=lambda s: RANK[s], default="unknown")
    not_working = sum(1 for s in services if s == "down")
    attention = sum(1 for s in capped if s == "warn") + sum(1 for s in services if s == "warn")
    if status == "down":
        key = "not_working"
    elif status == "warn":
        key = "need_attention"
    elif status == "ok":
        key = "everything_working"
    else:
        key = "not_known"
    return {
        "status": status,
        "sentence_key": key,
        "counts": {
            "court_working": sum(1 for s in court if s == "ok"),
            "court_total": len(court),
            "services_working": sum(1 for s in services if s == "ok"),
            "services_total": len(services),
            "attention": attention,
            "not_working": not_working,
        },
    }
