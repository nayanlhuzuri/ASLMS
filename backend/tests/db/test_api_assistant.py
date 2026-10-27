"""The Case Assistant API (design `assistant`, "Tests", API): every route needs `assistant.use`; the status and
`/me.assistant_mode` by mode; the shapes of a question, its answer, the conversation list and the thread."""

from __future__ import annotations

import uuid

import pytest

from aslms.domain.cases import Case
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
        "scopes": ["case", "my_cases", "research"],
        # design assistant-ollama: no local engine and no internal records outside ollama mode
        "engine": None,
        "internal_records": "never",
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
