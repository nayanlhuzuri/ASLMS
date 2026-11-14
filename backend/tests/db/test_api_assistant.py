"""The Case Assistant API (design `assistant`, "Tests", API): every route needs `assistant.use`; the status and
`/me.assistant_mode` by mode; the shapes of a question, its answer, the conversation list and the thread."""

from __future__ import annotations

import uuid

import pytest

from aslms.domain.cases import Case
from aslms.services import assistant_work as work
from tests.db import alerts_support as h
from tests.db import assistant_support as sup
from tests.db import docs_support as ds
from tests.db import workflow_support as w
from tests.db.world import make_case


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path, assistant_mode="preview")
    client.app.state.assistant_config = sup.CONFIG
    yield client
    client.__exit__(None, None, None)


@pytest.fixture()
def case_ids(world, api):
    with world.Session() as s:
        a = w.claimed_case(s, world, officer="edu_off1", case_no="WP(C)/11/2026")
        other = make_case(s, case_no="WP(C)/22/2026")
        h.claim(s, world, "health_admin", other)
        o, _ = sup.order(
            s,
            api.store,
            a,
            ["The petition is admitted.", "The State shall file an affidavit on the gecko plan."],
        )
        sup.order(s, api.store, other, ["Orders on the gecko plan of the health department."], order_no="3")
        filing = sup.filing(s, api.store, a, world.office(s, "EDU"), ["The gecko petition as filed."])
        s.commit()
        return {"a": a.id, "a_ref": a.ref_no, "order": o.id, "filing": filing.id}


ROUTES = [
    ("get", "/assistant/status", None),
    ("post", "/assistant/ask", {"question": "gecko", "scope": "research"}),
    ("get", "/assistant/conversations", None),
    ("get", f"/assistant/conversations/{uuid.uuid4()}", None),
    ("get", f"/assistant/court-orders/{uuid.uuid4()}", None),
    ("get", f"/assistant/court-orders/{uuid.uuid4()}/file", None),
]


def test_endpoints_need_assistant_use(world, api):
    hdr = ds.login(api, "edu_auditor")  # the Auditor lost assistant.use (design alerts-visibility-roles)
    for method, url, body in ROUTES:
        r = api.request(method.upper(), url, headers=hdr, json=body)
        assert r.status_code == 403, (url, r.status_code)
    for method, url, body in ROUTES:
        assert api.request(method.upper(), url, json=body).status_code == 401, url


def test_status_and_me_assistant_mode(world, api, tmp_path):
    hdr = ds.login(api, "edu_off1")
    assert api.get("/me", headers=hdr).json()["assistant_mode"] == "preview"
    st = api.get("/assistant/status", headers=hdr).json()
    assert st == {
        "mode": "preview",
        "state": "preview",
        "banner": "Preview: passages found in the court records, not an AI answer. Questions are searched as "
        "words; no AI is used.",
        "limits": {
            "questions_per_hour": 30,
            "used_last_hour": 0,
            "question_max_chars": 2000,
            "messages_per_conversation": 200,
        },
        # design assistant-ollama-work: My Work in preview mode, with the questions the caller may ask (an officer
        # without cases.claim is not offered the waiting recommendations)
        "scopes": ["case", "my_cases", "research", "my_work"],
        # design assistant-ollama: no local engine and no internal records outside ollama mode
        "engine": None,
        "internal_records": "never",
        "work_questions": [
            {"key": q.key, "label": q.label, "example": q.example}
            for q in work.WORK_QUESTIONS
            if q.key != "awaiting_claim"
        ],
    }
    # preview with APP_ENV=prod answers off too: a unit test (a prod app refuses the test database superuser)
    for mode, extra, me_mode, state in (
        ("off", {}, "off", "off"),
        ("sourcetrace", {"sourcetrace_enabled": True}, "off", "not_implemented"),
    ):
        other = ds.make_api(world, tmp_path / mode, assistant_mode=mode, **extra)
        try:
            oh = ds.login(other, "edu_off1")
            assert other.get("/me", headers=oh).json()["assistant_mode"] == me_mode
            body = other.get("/assistant/status", headers=oh).json()
            assert body["state"] == state and body["banner"] is None
            assert body["scopes"] == ["case", "my_cases", "research"] and body["work_questions"] == []
        finally:
            other.__exit__(None, None, None)


def test_ask_and_read_back_shapes(world, api, case_ids):
    hdr = ds.login(api, "edu_off1")
    r = api.post(
        "/assistant/ask",
        headers=hdr,
        json={"question": "gecko", "scope": "case", "case": case_ids["a_ref"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    conv = body["conversation"]
    assert conv["scope"] == "case" and conv["case"]["id"] == str(case_ids["a"])
    assert conv["title"] == "gecko" and conv["message_count"] == 2
    q, a = body["question"], body["answer"]
    assert q["role"] == "user" and q["content"] == "gecko" and q["citations"] == []
    assert a["role"] == "assistant" and a["reply_to_id"] == q["id"] and a["mode"] == "preview"
    assert a["outcome"] == "answered" and a["error"] is None and a["hidden_reason"] is None
    cit = a["citations"][0]
    assert set(cit) == {
        "document_id",
        "order_id",
        "case",
        "source_kind",
        "doc_type_label",
        "doc_date",
        "order_no",
        "page",
        "passage",
        "related",
        "available",
        "unavailable_reason",
        "open",
        # design assistant-ollama: the local model's fields, empty on a preview answer
        "label",
        "cited",
        "context",
        "note",
        "internal",
        "what",
        "visibility",
        # design assistant-ollama-work: a My Work row's fields, null on a court citation
        "work",
    }
    assert cit["case"]["visible"] is True and cit["available"] is True
    kinds = {c["source_kind"] for c in a["citations"]}
    assert kinds == {"court_order", "court_filing"}
    filing = next(c for c in a["citations"] if c["source_kind"] == "court_filing")
    assert filing["open"] == {
        "kind": "document",
        "href": f"/documents/{case_ids['filing']}/file?disposition=inline",
    }
    related = [c for c in a["citations"] if c["related"]]
    assert related and related[0]["case"]["id"] is None and related[0]["open"]["kind"] == "court_order"
    # continue the conversation, then read it back
    r2 = api.post(
        "/assistant/ask",
        headers=hdr,
        json={
            "question": "gecko plan",
            "scope": "case",
            "case": str(case_ids["a"]),
            "conversation_id": conv["id"],
            "include_related": False,
        },
    )
    assert r2.status_code == 200 and r2.json()["conversation"]["message_count"] == 4
    lst = api.get("/assistant/conversations", headers=hdr, params={"scope": "case"}).json()
    assert lst["total"] == 1 and lst["items"][0]["id"] == conv["id"]
    assert api.get("/assistant/conversations", headers=hdr, params={"scope": "research"}).json()["total"] == 0
    by_case = api.get("/assistant/conversations", headers=hdr, params={"case": case_ids["a_ref"]}).json()
    assert by_case["total"] == 1
    assert api.get("/assistant/conversations", headers=hdr, params={"case": "NOPE"}).json()["total"] == 0
    thread = api.get(f"/assistant/conversations/{conv['id']}", headers=hdr).json()
    assert [m["role"] for m in thread["messages"]] == ["user", "assistant", "user", "assistant"]
    assert thread["has_more"] is False
    page = api.get(f"/assistant/conversations/{conv['id']}", headers=hdr, params={"limit": 2}).json()
    assert page["has_more"] is True and [m["content"] for m in page["messages"]][0] == "gecko plan"
    older = api.get(
        f"/assistant/conversations/{conv['id']}",
        headers=hdr,
        params={"limit": 2, "before": page["messages"][0]["id"]},
    ).json()
    assert [m["role"] for m in older["messages"]] == ["user", "assistant"] and older["has_more"] is False
    assert api.get(f"/assistant/conversations/{uuid.uuid4()}", headers=hdr).status_code == 404
    with world.Session() as s:
        assert s.get(Case, case_ids["a"]) is not None


# ------------------------------------------------------------------------------------------------ My Work (design assistant-ollama-work)


def test_status_scopes_by_mode_and_work_questions_by_guard(world, api, tmp_path):
    admin = api.get("/assistant/status", headers=ds.login(api, "edu_admin")).json()
    assert [q["key"] for q in admin["work_questions"]] == [q.key for q in work.WORK_QUESTIONS]
    root = api.get("/assistant/status", headers=ds.login(api, "root")).json()
    keys = [q["key"] for q in root["work_questions"]]
    assert "department_claimed" not in keys and "awaiting_claim" not in keys  # no department of their own
    local = ds.make_api(
        world, tmp_path / "ollama", assistant_mode="ollama", assistant_ollama_url="http://127.0.0.1:9"
    )
    try:
        from tests.db import ollama_support as ol
        from tests.fakes.ollama import FakeOllama

        local.app.state.assistant_connector = ol.connector(world, FakeOllama())
        body = local.get("/assistant/status", headers=ds.login(local, "edu_off1")).json()
        assert body["scopes"] == ["case", "my_cases", "research", "my_work"] and body["work_questions"]
    finally:
        local.__exit__(None, None, None)


def test_ask_my_work_shape_work_and_suggest_work(world, api, case_ids):
    hdr = ds.login(api, "edu_admin")
    q = "how many cases were claimed by me?"
    r = api.post("/assistant/ask", headers=hdr, json={"question": q, "scope": "my_work"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["conversation"]["scope"] == "my_work" and body["conversation"]["case"] is None
    a = body["answer"]
    assert a["mode"] == "preview" and a["outcome"] == "answered" and a["suggest_work"] is False
    assert a["engine"] is None and a["checks"] is None
    assert a["content"].splitlines()[0] == "You have claimed 1 case in all."
    assert a["work"] == {
        "question": "claimed_by_me",
        "label": "Cases I Claimed",
        "chosen_by": "keyword",
        "total": 1,
        "shown": 1,
        "list_label": "Case Inbox · My Cases · Claimed by Me",
        "full_list_href": "/inbox/my-cases",
        "scan_capped": False,
    }
    # refusals before anything is stored
    bad = api.post(
        "/assistant/ask",
        headers=hdr,
        json={"question": "how many cases?", "scope": "my_work", "case": str(case_ids["a"])},
    )
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "scope_mismatch"
    extra = api.post(
        "/assistant/ask", headers=hdr, json={"question": "how many?", "scope": "my_work", "question_key": "x"}
    )
    assert extra.status_code == 422
    # the trigger: the same question in My Cases is answered from court records and offers My Work
    court = api.post("/assistant/ask", headers=hdr, json={"question": q, "scope": "my_cases"})
    assert court.status_code == 200 and court.json()["answer"]["suggest_work"] is True
    assert court.json()["answer"]["work"] is None
    lst = api.get("/assistant/conversations", headers=hdr, params={"scope": "my_work"}).json()
    assert lst["total"] == 1 and lst["items"][0]["scope"] == "my_work"


def test_thread_work_row_citation_shape_and_open_kinds(world, api, case_ids):
    with world.Session() as s:
        rec = make_case(s, case_no="WP(C)/33/2026")
        h.recommend(s, world, rec, "EDU")
        s.commit()
    hdr = ds.login(api, "edu_admin")
    mine = api.post(
        "/assistant/ask", headers=hdr, json={"question": "cases i claimed", "scope": "my_work"}
    ).json()
    waiting = api.post(
        "/assistant/ask",
        headers=hdr,
        json={
            "question": "which cases are waiting to be claimed?",
            "scope": "my_work",
            "conversation_id": mine["conversation"]["id"],
        },
    )
    assert waiting.status_code == 200, waiting.text
    thread = api.get(f"/assistant/conversations/{mine['conversation']['id']}", headers=hdr).json()
    answers = [m for m in thread["messages"] if m["role"] == "assistant"]
    row = answers[0]["citations"][0]
    assert row["source_kind"] == "work_row" and row["label"] == "S1" and row["available"] is True
    assert row["open"] == {"kind": "case_tab", "href": f"/cases/{case_ids['a']}"}
    assert row["case"]["id"] == str(case_ids["a"]) and row["case"]["case_no_text"] == "WP(C)/11/2026"
    assert set(row["work"]) == {"list_label", "as_of", "fields"}
    assert set(row["work"]["fields"]) <= set(work.FIELDS["claimed_by_me"])
    assert row["work"]["fields"]["via"] == "Claimed" and row["work"]["fields"]["department"] == "EDU"
    claim_row = answers[1]["citations"][0]
    assert claim_row["open"] == {"kind": "claim", "href": f"/claim/recommended?department=EDU&case={rec.id}"}
    assert claim_row["work"]["fields"]["band"] == "Strong"
    assert answers[1]["work"]["full_list_href"] == "/claim/recommended?department=EDU"


def test_case_tab_conversations_of_other_scopes_listed_on_page(world, api, case_ids):
    """The case tab's former flow created My Cases and All Court Orders conversations without a case; the sidebar
    page lists them by scope (design assistant-ollama-work, decision 2). Nothing is migrated."""
    hdr = ds.login(api, "edu_off1")
    for scope in ("my_cases", "research"):
        r = api.post("/assistant/ask", headers=hdr, json={"question": "gecko", "scope": scope})
        assert r.status_code == 200, r.text
        assert r.json()["conversation"]["case"] is None
        lst = api.get("/assistant/conversations", headers=hdr, params={"scope": scope}).json()
        assert lst["total"] == 1 and lst["items"][0]["id"] == r.json()["conversation"]["id"]
