"""My Work on the sidebar Assistant, without a database (design `assistant-ollama-work`, "Tests", unit): the field
allow-list, the module's imports, the twelve strict tool schemas, the keyword table, the count sentences, the IST
periods and the row setting's bounds."""

from __future__ import annotations

import ast
from datetime import date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from aslms.core import clock
from aslms.core.config import Settings
from aslms.domain.org import Office
from aslms.services import assistant_work as work
from aslms.services.reporting_common import ReportConfig

ASLMS = Path(__file__).resolve().parents[2] / "aslms"
TODAY = date(2026, 11, 14)  # a Saturday


def test_work_registry_fields_allow_list_has_no_remark_body_text_reason_or_score():
    assert [q.key for q in work.WORK_QUESTIONS] == [
        "pending_actions",
        "cases_with_me",
        "sent_by_me",
        "my_hearings",
        "listed_tomorrow",
        "my_due_dates",
        "unread_alerts",
        "new_orders",
        "needs_attention",
        "claimed_by_me",
        "department_claimed",
        "awaiting_claim",
    ]
    assert set(work.FIELDS) == set(work.BY_KEY)
    for key, keys in work.FIELDS.items():
        assert keys[:4] == ("case_no", "cnr", "parties", "case_ref"), key
        for banned in (
            "remark",
            "body",
            "note",
            "text",
            "reasons",
            "ref_no",
            "score_signals",
            "score",
            "signals",
        ):
            assert banned not in keys, (key, banned)
    assert work.FIELDS["claimed_by_me"][4:] == ("claimed_on", "via", "department", "status")
    assert work.FIELDS["department_claimed"][4:] == (
        "claimed_on",
        "department",
        "role",
        "assigned_to",
        "status",
    )
    assert work.FIELDS["awaiting_claim"][4:] == ("department", "band", "next_hearing", "last_listed_on")
    assert work.allowed("unread_alerts", {"title": "t", "body": "secret", "ref_no": "X"}) == {"title": "t"}


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text("utf-8"))):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


def test_assistant_work_imports_no_write_or_text_service():
    path = ASLMS / "services" / "assistant_work.py"
    mods = _imports(path)
    for banned in (
        "aslms.services.notes",
        "aslms.services.documents",
        "aslms.services.ownership",
        "aslms.services.stages",
        "aslms.integration",
        "aslms.integration.ollama",
        "aslms.integration.sourcetrace",
        "aslms.services.assistant_ollama",
        "aslms.services.assistant_internal",
    ):
        assert not any(m == banned or m.startswith(banned + ".") for m in mods), banned
    text = path.read_text("utf-8")
    for call in (
        "custody.history",
        "case_note_drafts",
        "CaseNoteDraft",
        "custody.send(",
        "custody.recall(",
        "ownership.",
    ):
        assert call not in text, call


def test_tool_schemas_strict():
    tools = work.tool_schemas()
    assert len(tools) == 12
    assert [t["function"]["name"] for t in tools] == [q.key for q in work.WORK_QUESTIONS]
    for t in tools:
        assert t["type"] == "function"
        params = t["function"]["parameters"]
        assert params["type"] == "object" and params["additionalProperties"] is False
        for prop in params["properties"].values():
            assert prop["type"] in ("string", "integer", "boolean")
            if prop["type"] == "string" and "format" not in prop:
                assert prop.get("enum"), t["function"]["name"]
    by = {t["function"]["name"]: t["function"]["parameters"]["properties"] for t in tools}
    assert by["new_orders"]["days"] == {"type": "integer", "minimum": 1, "maximum": 30}
    assert by["my_hearings"]["from"]["pattern"] == r"^\d{4}-\d{2}-\d{2}$"


def test_validate_choice():
    assert work.validate_choice([], TODAY) is None
    ok = work.validate_choice(
        [{"function": {"name": "claimed_by_me", "arguments": {"period": "last_7_days"}}}], TODAY
    )
    assert ok is not None and ok[0] == "claimed_by_me" and ok[1].period == "last_7_days"
    as_string = work.validate_choice(
        [{"function": {"name": "new_orders", "arguments": '{"days": 3}'}}], TODAY
    )
    assert as_string is not None and as_string[1].days == 3
    for bad in (
        [{"function": {"name": "a", "arguments": {}}}, {"function": {"name": "b", "arguments": {}}}],
        [{"function": {"name": "DROP TABLE cases", "arguments": {}}}],
        [{"function": {"name": "new_orders", "arguments": {"days": 999}}}],
        [{"function": {"name": "new_orders", "arguments": {"days": 3, "sql": "x"}}}],
        [
            {
                "function": {
                    "name": "my_hearings",
                    "arguments": {"range": "dates", "from": "2027-06-01", "to": "2027-06-02"},
                }
            }
        ],
        [
            {
                "function": {
                    "name": "my_hearings",
                    "arguments": {"range": "dates", "from": "2026-11-14", "to": "2026-12-31"},
                }
            }
        ],
        [{"function": {"name": "my_hearings", "arguments": {"range": "today", "from": "2026-11-14"}}}],
        [{"function": {"name": "cases_with_me", "arguments": "not json"}}],
    ):
        assert work.validate_choice(bad, TODAY) is None, bad
    dates = work.validate_choice(
        [
            {
                "function": {
                    "name": "my_due_dates",
                    "arguments": {"range": "dates", "from": "2026-11-20", "to": "2026-12-10"},
                }
            }
        ],
        TODAY,
    )
    assert dates is not None and work.dump(dates[1]) == {
        "range": "dates",
        "from": "2026-11-20",
        "to": "2026-12-10",
    }


def _key(question: str):
    out = work.keyword_choice(question, TODAY)
    return out if out in (None, "ambiguous") else (out[0], work.dump(out[1]))


def test_keyword_choice_table():
    # each example chip maps to its question
    for q in work.WORK_QUESTIONS:
        got = work.keyword_choice(q.example, TODAY)
        assert isinstance(got, tuple) and got[0] == q.key, (q.example, got)
    assert _key("how many cases were claimed by me?") == ("claimed_by_me", {"period": "all"})
    assert _key("How many cases has my department claimed in the last 30 days") == (
        "department_claimed",
        {"period": "last_30_days"},
    )
    assert _key("which cases are waiting to be claimed") == ("awaiting_claim", {"band": "any"})
    assert _key("strong recommendations waiting to be claimed") == ("awaiting_claim", {"band": "strong"})
    assert _key("what did we claim this week")[0] == "department_claimed"
    assert _key("cases i claimed in the past month") == ("claimed_by_me", {"period": "last_30_days"})
    # date and period words
    assert _key("my hearings tomorrow") == ("my_hearings", {"range": "tomorrow"})
    assert _key("my hearings today") == ("my_hearings", {"range": "today"})
    assert _key("my hearings next week") == ("my_hearings", {"range": "next_week"})
    assert _key("what is overdue with me?") == ("pending_actions", {"when": "overdue"})
    assert _key("pending actions") == ("pending_actions", {"when": "all"})
    assert _key("files I sent that are still out") == (
        "sent_by_me",
        {"period": "last_30_days", "still_out": True},
    )
    assert _key("new orders today") == ("new_orders", {"days": 1})
    assert _key("new orders this month") == ("new_orders", {"days": 30})
    # ambiguity and no match
    assert _key("sent alerts") == "ambiguous"
    assert _key("what did the court direct in the last order?") is None
    assert _key("") is None


def _ctx(today: date = TODAY):
    return work.Ctx(None, None, datetime(2026, 11, 14, 6, tzinfo=clock.IST), today, 25, ReportConfig())  # type: ignore[arg-type]


def _r(total: int, **kw) -> work.WorkResult:
    return work.WorkResult(rows=[], total=total, **kw)


def test_count_sentences_plurals_and_departments():
    q = work.BY_KEY
    ctx = _ctx()
    p = work.ClaimPeriodParams(period="last_30_days")
    assert q["claimed_by_me"].count_sentence(_r(0), p, ctx) == "You claimed no cases in the last 30 days."
    assert q["claimed_by_me"].count_sentence(_r(1), p, ctx) == "You claimed 1 case in the last 30 days."
    assert q["claimed_by_me"].count_sentence(_r(14), p, ctx) == "You claimed 14 cases in the last 30 days."
    assert (
        q["claimed_by_me"].count_sentence(_r(3), work.ClaimPeriodParams(), ctx)
        == "You have claimed 3 cases in all."
    )
    edu = Office(code="EDU", name="Education")
    health = Office(code="HEALTH", name="Health")
    one = _r(5, departments=[edu], extra={"per_department": [("Education", 5)]})
    assert (
        q["department_claimed"].count_sentence(one, p, ctx)
        == "Education claimed 5 cases in the last 30 days."
    )
    one.whole = False
    assert (
        q["department_claimed"].count_sentence(one, p, ctx)
        == "Education claimed 5 cases that you can see in the last 30 days."
    )
    two = _r(7, departments=[edu, health], extra={"per_department": [("Education", 4), ("Health", 3)]})
    assert (
        q["department_claimed"].count_sentence(two, p, ctx)
        == "Your departments claimed 7 cases in the last 30 days: Education 4, Health 3."
    )
    b = work.BandParams()
    assert (
        q["awaiting_claim"].count_sentence(_r(0, departments=[edu]), b, ctx)
        == "No cases are recommended to Education and waiting to be claimed."
    )
    assert (
        q["awaiting_claim"].count_sentence(_r(1, departments=[edu]), b, ctx)
        == "1 case is recommended to Education and waiting to be claimed."
    )
    assert q["awaiting_claim"].detail_sentence(_r(3, extra={"strong": 2, "possible": 1}), b, ctx) == (
        "2 strong and 1 possible."
    )
    assert q["pending_actions"].count_sentence(_r(0), work.PendingParams(), ctx) == (
        "You have no files with a pending action."
    )
    assert q["pending_actions"].count_sentence(_r(1), work.PendingParams(when="overdue"), ctx) == (
        "1 file with you is overdue."
    )
    assert q["pending_actions"].count_sentence(_r(1000, scan_capped=True), work.PendingParams(), ctx) == (
        "You have at least 1,000 files with a pending action."
    )
    assert q["pending_actions"].detail_sentence(_r(4, extra={"overdue": 1}), work.PendingParams(), ctx) == (
        "1 of them is overdue."
    )
    assert q["cases_with_me"].count_sentence(_r(1), work.NoParams(), ctx) == "1 case file is with you."
    assert q["cases_with_me"].detail_sentence(
        _r(3, extra={"pending": 2, "overdue": 1}), work.NoParams(), ctx
    ) == ("2 have a pending action; 1 is overdue.")
    assert q["sent_by_me"].count_sentence(_r(2), work.SentParams(), ctx) == (
        "You sent or recalled 2 files in the last 30 days."
    )
    assert q["sent_by_me"].count_sentence(_r(2), work.SentParams(period="all"), ctx) == (
        "You have sent or recalled 2 files in all."
    )
    assert q["sent_by_me"].count_sentence(_r(1), work.SentParams(period="all", still_out=True), ctx) == (
        "1 file you sent is still where you sent them."
    )
    tomorrow = q["listed_tomorrow"].count_sentence(_r(0), work.NoParams(), ctx)
    assert tomorrow == "None of your cases are on tomorrow's cause lists (Sun 15 Nov 2026)."
    assert q["my_hearings"].count_sentence(_r(2), work.RangeParams(range="next_week"), ctx) == (
        "You have 2 hearings next week (Mon 16 Nov 2026 to Sun 22 Nov 2026)."
    )
    assert q["my_hearings"].count_sentence(_r(1), work.RangeParams(range="today"), ctx) == (
        "You have 1 hearing today (Sat 14 Nov 2026)."
    )
    assert q["unread_alerts"].count_sentence(_r(0), work.AlertParams(), ctx) == "You have no unread alerts."
    assert q["new_orders"].count_sentence(_r(3), work.NewOrdersParams(), ctx) == (
        "You have 3 new-order alerts in the last 7 days."
    )
    assert (
        q["needs_attention"].count_sentence(_r(0), work.NoParams(), ctx)
        == "Nothing needs your attention today."
    )
    assert work.shown_line(14, 14) == "Showing all 14."
    assert work.shown_line(41, 25) == "Showing the first 25 of 41. Open the full list for the rest."
    assert work.shown_line(0, 0) is None
    assert work.day(date(2026, 11, 14)) == "Sat 14 Nov 2026"


def test_period_start_ist():
    assert work.period_start("all", TODAY) is None
    s7 = work.period_start("last_7_days", TODAY)
    assert s7 == datetime(2026, 11, 8, tzinfo=clock.IST)
    assert work.period_start("last_30_days", TODAY) == datetime(2026, 10, 16, tzinfo=clock.IST)
    # 23:59 IST six days ago is inside last_7_days, seven days ago is not
    assert datetime(2026, 11, 8, 23, 59, tzinfo=clock.IST) >= s7
    assert datetime(2026, 11, 7, 23, 59, tzinfo=clock.IST) < s7


def test_settings_work_rows_bounds():
    assert Settings(_env_file=None).assistant_work_rows == 25
    assert Settings(_env_file=None, assistant_work_rows=5).assistant_work_rows == 5
    for bad in (4, 26, 0):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, assistant_work_rows=bad)


def test_params_forbid_extra_and_validate():
    with pytest.raises(ValidationError):
        work.NewOrdersParams.model_validate({"days": 0})
    with pytest.raises(ValidationError):
        work.ClaimPeriodParams.model_validate({"period": "all", "extra": 1})
    with pytest.raises(ValidationError):
        work.AlertParams.model_validate({"kind": "not_a_kind"})
    assert work.AlertParams.model_validate({"kind": "new_order"}).kind == "new_order"
    with pytest.raises(ValidationError):
        work.RangeParams.model_validate({"range": "dates", "from": "2026-11-20"})
    assert work.resolve_range(work.RangeParams(range="this_week"), TODAY) == (TODAY, date(2026, 11, 15))
