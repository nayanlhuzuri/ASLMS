"""The two read-only additions of design `research-index-portal` (decision 1, "Services", "Tests", backend): the
filter choices built from current court-order readings (acts by key with the most common printed name, citations
with the most common case name, `q` and `limit`, the statement timeout answering not ready, the 6-hour cache and its
single build, the guard) and the filters a question was asked with on question messages only. No model, no NAPIX:
the chat and embedding models are `FakeOllama`."""

from __future__ import annotations

import itertools
import re
from datetime import UTC, date, datetime

import pytest
import sqlalchemy as sa

from aslms.domain.documents import OrderKind, OrderSectionReplaceReason
from aslms.services import order_parse
from aslms.services import research_embed as remb
from aslms.services import research_search as rsearch
from aslms.services.assistant_ollama import OllamaConnector
from tests.db import docs_support as ds
from tests.db import ollama_support as ol
from tests.db import research_support as rs
from tests.db import workflow_support as w
from tests.db.world import make_case

_FACTS: dict[str, dict] = {}
_SEQ = itertools.count(1)
TAG = re.compile(r"factstag(\d+)x")


@pytest.fixture(autouse=True)
def _fresh_choices(monkeypatch):
    """Readings never change once written (a trigger refuses it), so the facts a test needs are given to row 250's
    reader: an order whose text carries `factstag<n>x` is read with the acts and judgments registered under n."""
    real_acts, real_judgments = order_parse.acts, order_parse.judgments

    def pick(name, real):
        def read(body, loc):
            m = TAG.search(body or "")
            return list(_FACTS[m.group(1)].get(name, [])) if m else real(body, loc)

        return read

    monkeypatch.setattr(order_parse, "acts", pick("acts", real_acts))
    monkeypatch.setattr(order_parse, "judgments", pick("judgments", real_judgments))
    rsearch.reset_filter_choices()
    yield
    rsearch.reset_filter_choices()
    _FACTS.clear()


def _act(act: str) -> dict:
    return {
        "act": act,
        "act_key": order_parse._act_key(act),
        "provisions": ["Section 3"],
        "kind": "act",
        "count": 1,
    }


def _cite(citation: str, name: str | None) -> dict:
    return {"citation": citation, "reporter": "SCC", "year": 2006, "case_name": name, "count": 1}


def _order_with(s, facts: dict):
    n = str(next(_SEQ))
    _FACTS[n] = facts
    c = make_case(s, case_no=f"WP(C)/{900 + int(n)}/2025")
    body = f"1.      Heard learned counsel for the parties in the matter factstag{n}x." + "\n"
    return rs.court_order(s, c, body=body, day=date(2025, 1, 1 + int(n) % 27))


def _readings(world, facts: list[dict], *, replaced: dict | None = None) -> None:
    """One court order per item of `facts`, read by row 250's job with those facts; `replaced`, when given, is one
    more order whose reading is then marked replaced (text gone) and must never be counted."""
    with world.Session() as s:
        orders = [_order_with(s, f) for f in facts]
        last = _order_with(s, replaced) if replaced else None
        rs.read_orders(s)
        for order in orders:
            assert rs.reading(s, order) is not None
        if last is not None:
            r = rs.reading(s, last)
            r.replaced_at = datetime.now(UTC)
            r.replace_reason = OrderSectionReplaceReason.TEXT_GONE
        s.commit()


def _choices(world, kind, q=None, limit=20):
    with world.Session() as s:
        return rsearch.filter_choices(s, kind, q, limit)


def test_filter_choices_acts_counts_and_label(world):
    lrr = "Assam Land Revenue Regulation, 1886"
    _readings(
        world,
        [
            {"acts": [_act(lrr)]},
            {"acts": [_act(lrr), _act("Constitution of India")]},
            {"acts": [_act("Assam Land Revenue Regulation. 1886")]},  # printed another way, the same key
        ],
        replaced={"acts": [_act(lrr)]},
    )
    out = _choices(world, "act")
    assert out["kind"] == "act" and out["ready"] is True
    by = {i["value"]: i for i in out["items"]}
    key = order_parse._act_key(lrr)
    assert key == "assam land revenue regulation 1886"
    assert by[key]["orders"] == 3  # the replaced reading is not counted
    assert by[key]["label"] == lrr  # the most common printed name
    assert by[key]["detail"] is None
    assert out["items"][0]["value"] == key  # most named first


def test_filter_choices_cites_with_case_name(world):
    _readings(
        world,
        [
            {"judgments": [_cite("(2006) 4 SCC 1", "Secretary, State of Karnataka v. Umadevi")]},
            {"judgments": [_cite("(2006) 4 SCC 1", "Secretary, State of Karnataka v. Umadevi")]},
            {"judgments": [_cite("(2006) 4 SCC 1", "Umadevi"), _cite("AIR 1950 SC 27", None)]},
        ],
    )
    by = {i["value"]: i for i in _choices(world, "cites")["items"]}
    assert by["(2006) 4 SCC 1"]["detail"] == "Secretary, State of Karnataka v. Umadevi"
    assert by["(2006) 4 SCC 1"]["label"] == "(2006) 4 SCC 1" and by["(2006) 4 SCC 1"]["orders"] == 3
    assert by["AIR 1950 SC 27"]["detail"] is None and by["AIR 1950 SC 27"]["orders"] == 1


def test_filter_choices_q_and_limit(world):
    _readings(
        world,
        [
            {
                "judgments": [_cite("(2006) 4 SCC 1", "State of Karnataka v. Umadevi")],
                "acts": [_act("Arms Act")],
            },
            {"judgments": [_cite("(2006) 4 SCC 1", None)], "acts": [_act("Assam Land Revenue Regulation")]},
            {"judgments": [_cite("AIR 1950 SC 27", "A.K. Gopalan v. State of Madras")]},
        ],
    )
    assert [i["value"] for i in _choices(world, "cites", "umadevi")["items"]] == ["(2006) 4 SCC 1"]  # detail
    assert [i["value"] for i in _choices(world, "cites", "4   scc")["items"]] == ["(2006) 4 SCC 1"]  # value
    assert [i["value"] for i in _choices(world, "cites", "a k gopalan")["items"]] == ["AIR 1950 SC 27"]
    assert [i["value"] for i in _choices(world, "cites", "State of")["items"]] == [
        "(2006) 4 SCC 1",  # named by 2 orders
        "AIR 1950 SC 27",
    ]
    assert [i["value"] for i in _choices(world, "act", "LAND-revenue")["items"]] == [
        "assam land revenue regulation"
    ]
    assert len(_choices(world, "cites", limit=1)["items"]) == 1
    assert rsearch.CHOICES_LIMIT_MAX == 50 and rsearch.CHOICES_LIMIT == 20
    _readings(world, [{"judgments": [_cite(f"({1950 + i}) 1 SCC {i}", None) for i in range(55)]}])
    rsearch.reset_filter_choices()
    assert len(_choices(world, "cites", limit=500)["items"]) == rsearch.CHOICES_LIMIT_MAX
    assert len(_choices(world, "cites")["items"]) == rsearch.CHOICES_LIMIT
    with pytest.raises(ValueError):
        _choices(world, "notes")


def test_filter_choices_constants():
    assert rsearch.CHOICES_SQL_SECONDS == 15
    assert rsearch.CHOICES_CACHE_SECONDS == 21600


def test_filter_choices_timeout_not_ready(world, monkeypatch):
    _readings(world, [{"acts": [_act("Arms Act")]}])
    monkeypatch.setitem(
        rsearch._CHOICES_SQL,
        "act",
        "SELECT 'x' AS value, 'x' AS label, NULL AS detail, 1 AS orders FROM pg_sleep(3)",
    )
    monkeypatch.setattr(rsearch, "CHOICES_SQL_SECONDS", 1)
    assert _choices(world, "act") == {"kind": "act", "ready": False, "items": []}
    monkeypatch.undo()
    out = _choices(world, "act")  # the next call builds the list
    assert out["ready"] is True and [i["value"] for i in out["items"]] == ["arms act"]


def test_filter_choices_cache_and_single_build(world, monkeypatch):
    _readings(world, [{"acts": [_act("Arms Act")]}])
    assert _choices(world, "act")["ready"] is True
    ran = []
    real = rsearch.text

    def spy(sql, *a, **kw):
        ran.append(sql)
        return real(sql, *a, **kw)

    monkeypatch.setattr(rsearch, "text", spy)
    assert [i["value"] for i in _choices(world, "act", "arms")["items"]] == ["arms act"]
    assert ran == []  # within the cache time no statement runs
    # one build at a time: while another request holds the build, this one answers not ready
    rsearch.reset_filter_choices()
    lock = rsearch._choices_locks["act"]
    assert lock.acquire(blocking=False)
    try:
        assert _choices(world, "act") == {"kind": "act", "ready": False, "items": []}
    finally:
        lock.release()
    assert ran == []
    # an expired copy is built again
    monkeypatch.setattr(rsearch, "CHOICES_CACHE_SECONDS", -1)
    assert _choices(world, "act")["ready"] is True and len(ran) >= 1


def test_filter_choices_guard(world, tmp_path):
    api = ds.make_api(world, tmp_path)
    try:
        _readings(world, [{"acts": [_act("Arms Act")]}])
        auditor = ds.login(api, "edu_auditor")  # no assistant.use
        assert api.get("/assistant/filter-choices?kind=act", headers=auditor).status_code == 403
        assert api.get("/assistant/filter-choices?kind=act").status_code == 401
        h = ds.login(api, "edu_off1")
        assert api.get("/assistant/filter-choices?kind=notes", headers=h).status_code == 422
        assert api.get("/assistant/filter-choices", headers=h).status_code == 422
        assert api.get("/assistant/filter-choices?kind=act&limit=51", headers=h).status_code == 422
        assert api.get(f"/assistant/filter-choices?kind=act&q={'x' * 101}", headers=h).status_code == 422
        got = api.get("/assistant/filter-choices?kind=act&q=arms", headers=h)
        assert got.status_code == 200, got.text
        assert got.json() == {
            "kind": "act",
            "ready": True,
            "items": [{"value": "arms act", "label": "Arms Act", "detail": None, "orders": 1}],
        }
    finally:
        api.__exit__(None, None, None)


def test_message_filters_on_questions_only(world, tmp_path):
    fake = rs.fake()
    with world.Session() as s:
        a = w.claimed_case(s, world, officer="edu_off1", case_no="WP(C)/501/2025")
        rs.court_order(
            s, a, body=rs.PENSION_BODY, heading="JUDGMENT", kind=OrderKind.JUDGMENT, day=date(2025, 3, 12)
        )
        rs.read_orders(s)
        s.commit()
    remb.backfill(world.Session, fake.client(), rs.settings(), pause_ms=0, sleep=lambda _x: None)
    api = ds.make_api(world, tmp_path, assistant_mode="ollama", assistant_ollama_url="http://127.0.0.1:9",
                      research_index_enabled=True)  # fmt: skip
    try:
        api.app.state.assistant_config = ol.CONFIG
        fake.default = "The respondents must release the retiral benefits [S1]."
        api.app.state.assistant_connector = OllamaConnector(
            world.Session, rs.settings(), client=fake.client()
        )
        h = ds.login(api, "edu_off1")
        filters = {"forms": ["judgment"], "against_state": True, "from": "2024-01-01", "to": "2026-01-31"}
        r = api.post(
            "/assistant/ask",
            headers=h,
            json={"question": "pension release", "scope": "research", "filters": filters},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["question"]["filters"] == {**filters, "substantive_only": None, "outcomes": None,
                                               "cites": None, "act": None}  # fmt: skip
        assert body["answer"]["filters"] is None
        conv = body["conversation"]["id"]
        r2 = api.post(
            "/assistant/ask",
            headers=h,
            json={"question": "pension release again", "scope": "research", "conversation_id": conv},
        )
        assert r2.status_code == 200, r2.text
        thread = api.get(f"/assistant/conversations/{conv}", headers=h).json()
        users = [m for m in thread["messages"] if m["role"] == "user"]
        assert users[0]["filters"]["forms"] == ["judgment"] and users[0]["filters"]["from"] == "2024-01-01"
        assert users[1]["filters"] is None  # a question without filters
        assert all(m["filters"] is None for m in thread["messages"] if m["role"] == "assistant")
    finally:
        api.__exit__(None, None, None)


def test_choices_sql_reads_current_readings_only():
    for sql in rsearch._CHOICES_SQL.values():
        assert "replaced_at IS NULL" in sql and "order_sections" in sql
        assert sa.text(sql) is not None
