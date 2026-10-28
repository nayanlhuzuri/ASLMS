"""The Case Assistant answered by a local Ollama model, against the database (design `assistant-ollama`, round 1,
"Tests", database and API). Ollama is `FakeOllama` (an `httpx.MockTransport`); no test calls a real model. Unique
planted words prove what reached the fake: court information in every scope; internal records of one case only after
the switch on its case tab, only what the asker may open on the case page, never drafts and never another case's; the
citation check; readiness, the slot and the cold start; audit and logs without text; the check; migration 0032."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from typer.testing import CliRunner

from aslms.domain.assistant import AssistantConversation, AssistantMessage, AssistantScope, MessageRole
from aslms.domain.cases import Case
from aslms.domain.documents import Document, Visibility
from aslms.domain.events import AuditLog
from aslms.domain.org import PermissionEffect
from aslms.domain.reference import Permission
from aslms.domain.workflow import CaseNote, CaseStage, Custody, CustodyHistory
from aslms.integration.sourcetrace import Answer, Citation
from aslms.integration.sourcetrace.fake import FakeSourceTrace
from aslms.services import access, custody, notes
from aslms.services import assistant as svc
from aslms.services import assistant_internal as internal
from aslms.services import documents as documents_svc
from aslms.services.assistant_ollama import CUT_SHORT_LINE, NO_ANSWER_TEXT, SYSTEM_PROMPT
from aslms.services.assistant_preview import NO_MATCH_LINE
from aslms.services.audit import Actor
from aslms.services.visibility import NotVisibleCase
from tests.db import assistant_support as sup
from tests.db import docs_support as ds
from tests.db import ollama_support as ol
from tests.db.conftest import alembic_config, head_revision, wipe, wipe_if_migrated
from tests.fakes.ollama import Delay, FakeOllama, chat_reply

W = ol.WORDS
INTERNAL_WORDS = (W["saved"], W["private"], W["remark"], W["internal"], W["restricted"])


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path, assistant_mode="ollama", assistant_ollama_url="http://127.0.0.1:9")
    client.app.state.assistant_config = ol.CONFIG
    fake = FakeOllama()
    client.fake = fake
    client.app.state.assistant_connector = ol.connector(world, fake)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture()
def scene(world, api) -> ol.Scene:
    return ol.build(world, api.store)


def _conn(world, **over):
    return ol.connector(world, FakeOllama(), **over)


def _msg(world, result) -> AssistantMessage:
    return sup.answer(world, result)


def _audits(world, action: str) -> list[AuditLog]:
    with world.Session() as s:
        return list(
            s.scalars(sa.select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)).all()
        )


def _conv(world, conv_id) -> AssistantConversation:
    with world.Session() as s:
        c = s.get(AssistantConversation, conv_id)
        s.expunge(c)
        return c


# ------------------------------------------------------------------------------------------------ court information


def test_ollama_case_scope_answer_cites_supplied_sources(world, scene):
    conn = _conn(world)
    r = ol.ask(world, "edu_admin", "affidavit quokka", "case", conn, case=scene.a, include_related=False)
    msg = _msg(world, r)
    assert r.outcome == "answered", (msg.content, msg.model_info, conn.fake.chats)
    assert msg.mode == "ollama" and msg.connector == "ollama"
    assert msg.model_info["model"] == "qwen3.5:4b" and msg.model_info["engine"] == "ollama"
    assert msg.model_info["prompt_version"] == 2
    labels = [c["label"] for c in msg.citations]
    assert labels == [f"S{i}" for i in range(1, len(labels) + 1)]
    first = msg.citations[0]
    assert first["source_kind"] == "case_details" and first["cited"] is True  # the fake cites [S1]
    court = [c for c in msg.citations if c["source_kind"] == "court_order"]
    assert court and court[0]["document_id"] == str(scene.order_doc) and court[0]["page"] in (1, 2)
    assert "affidavit" in court[0]["context"] and court[0]["passage"]
    body = conn.fake.chats[0]
    assert body["think"] is False and body["stream"] is False
    assert body["options"] == {"temperature": 0, "num_ctx": 16384, "num_predict": 800}
    assert body["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert msg.response["message"]["content"].endswith("[S1].")
    out = sup.read(world, "edu_admin", r)
    assert out["engine"] == {"kind": "ollama", "model": "qwen3.5:4b"}
    assert out["checks"] == {"invalid_markers": 0, "cut_short": False} and out["internal_used"] is False


def test_case_details_source_in_every_scope_court_public_only(world, scene):
    from tests.db.world import add_listing

    with world.Session() as s:
        a = s.get(Case, scene.a)
        a.next_hearing_date = w_date(2026, 5, 4)
        add_listing(s, a, w_date(2026, 3, 12), court_no="7")
        s.commit()
    conn = _conn(world)
    ol.ask(world, "edu_admin", "affidavit quokka", "case", conn, case=scene.a, include_related=False)
    sent = conn.fake.chats[0]["messages"][-1]["content"]
    assert "Case Details (Court Record)" in sent and "Next date (court): 04 May 2026" in sent
    assert "Listings (latest first)" in sent and "court 7" in sent
    lowered = sent.lower()
    for banned in ("owner", "stage", "recommend", "custody", "aslms/", "claimed", "education"):
        assert banned not in lowered, banned
    conn2 = _conn(world)
    ol.ask(world, "edu_admin", "affidavit quokka", "research", conn2)
    sent2 = conn2.fake.chats[0]["messages"][-1]["content"]
    assert "Case Details (Court Record)" in sent2 and "Listings" not in sent2  # compact in other scopes


def w_date(y, m, d):
    from datetime import date

    return date(y, m, d)


def test_ollama_filing_follows_document_visibility(world, scene):
    with world.Session() as s:
        a = s.get(Case, scene.a)
        sup.filing(s, scene.store, a, world.office(s, "EDU"), ["the gecko petition as filed"])
        s.commit()
    conn = _conn(world)
    ol.ask(world, "edu_admin", "gecko petition", "case", conn, case=scene.a)
    assert "gecko" in conn.fake.sent_text()
    conn2 = _conn(world)
    r = ol.ask(world, "health_off", "gecko petition", "research", conn2)
    assert "gecko" not in conn2.fake.sent_text() and r.outcome == "no_match"


# ------------------------------------------------------------------------------------------------ the switch


def test_internal_refused_before_the_switch(world, scene):
    conn = _conn(world)
    r = ol.ask(world, "edu_admin", "what is our stand on the quokka scheme", "case", conn, case=scene.a)
    text = conn.fake.sent_text()
    for word in (*INTERNAL_WORDS, W["draft"]):
        assert word not in text, word
    for header in ("Note (Internal)", "File Movement (Internal)", "Department Document (Internal)"):
        assert header not in text
    msg = _msg(world, r)
    assert all(c["source_kind"] not in internal.INTERNAL_KINDS for c in msg.citations)
    asked = _audits(world, "assistant.asked")[-1]
    assert asked.after["internal"] is False


def test_switch_audited_and_applies_from_then_on(world, scene, api):
    hdr = ds.login(api, "edu_admin")
    first = api.post(
        "/assistant/ask",
        headers=hdr,
        json={
            "question": "what did the court direct on the quokka scheme",
            "scope": "case",
            "case": str(scene.a),
        },
    )
    assert first.status_code == 200, first.text
    conv_id = first.json()["conversation"]["id"]
    assert first.json()["conversation"]["internal_included_at"] is None
    before = len(api.fake.chats)
    r = api.post(
        "/assistant/internal-records", headers=hdr, json={"case": str(scene.a), "conversation_id": conv_id}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["conversation_id"] == conv_id and body["new_conversation"] is False
    assert len(api.fake.chats) == before  # no model call
    rows = _audits(world, "assistant.internal_included")
    assert len(rows) == 1 and rows[0].case_id == scene.a and rows[0].entity_type == "assistant_conversation"
    assert rows[0].after == {"conversation_id": conv_id, "case_id": str(scene.a), "new_conversation": False}
    again = api.post(
        "/assistant/internal-records", headers=hdr, json={"case": str(scene.a), "conversation_id": conv_id}
    )
    assert again.status_code == 200 and again.json()["internal_included_at"] == body["internal_included_at"]
    assert len(_audits(world, "assistant.internal_included")) == 1
    second = api.post(
        "/assistant/ask",
        headers=hdr,
        json={
            "question": "what is our stand on the quokka scheme",
            "scope": "case",
            "case": str(scene.a),
            "conversation_id": conv_id,
        },
    )
    assert second.status_code == 200, second.text
    last = api.fake.chats[-1]["messages"][-1]["content"]
    assert "(Internal)" in last and W["saved"] in last and W["remark"] in last
    thread = api.get(f"/assistant/conversations/{conv_id}", headers=hdr).json()
    assert thread["conversation"]["internal_included_at"] == body["internal_included_at"]
    answers = [m for m in thread["messages"] if m["role"] == "assistant"]
    assert all(c["source_kind"] not in internal.INTERNAL_KINDS for c in answers[0]["citations"])
    assert any(c["source_kind"] in internal.INTERNAL_KINDS for c in answers[1]["citations"])


def test_switch_from_fresh_tab_creates_switched_on_conversation(world, scene):
    out = ol.switch(world, "edu_admin", scene.a)
    assert out["new_conversation"] is True
    conv = _conv(world, out["conversation_id"])
    assert conv.title == svc.NEW_TITLE and conv.internal_included_at is not None
    assert conv.scope == AssistantScope.CASE and conv.case_id == scene.a
    conn = _conn(world)
    ol.ask(
        world,
        "edu_admin",
        "our stand on the quokka scheme",
        "case",
        conn,
        case=scene.a,
        conversation_id=conv.id,
    )
    assert _conv(world, conv.id).title == "our stand on the quokka scheme"
    assert W["saved"] in conn.fake.sent_text()


def test_switch_refused_for_another_case_and_other_scopes(world, scene):
    conn = _conn(world)
    r_case = ol.ask(world, "edu_admin", "quokka scheme", "case", conn, case=scene.a)
    r_mine = ol.ask(world, "edu_admin", "quokka scheme", "my_cases", conn)
    r_research = ol.ask(world, "edu_admin", "quokka scheme", "research", conn)
    for conv_id, case in ((r_case.conversation_id, scene.b), (r_mine.conversation_id, scene.a)):
        with pytest.raises(svc.ScopeMismatch):
            ol.switch(world, "edu_admin", case, conv_id)
    with pytest.raises(svc.ScopeMismatch):
        ol.switch(world, "edu_admin", scene.a, r_research.conversation_id)
    with pytest.raises(svc.ConversationNotFound):
        ol.switch(world, "edu_off1", scene.a, r_case.conversation_id)
    for cid in (r_case.conversation_id, r_mine.conversation_id, r_research.conversation_id):
        assert _conv(world, cid).internal_included_at is None
    assert _audits(world, "assistant.internal_included") == []


def test_internal_refused_from_sidebar_and_other_scopes(world, scene, api):
    out = ol.switch(world, "edu_admin", scene.a)
    assert out["conversation_id"]
    for scope in ("my_cases", "research"):
        conn = _conn(world)
        r = ol.ask(world, "edu_admin", "our stand on the quokka scheme", scope, conn)
        text = conn.fake.sent_text()
        assert all(word not in text for word in INTERNAL_WORDS), scope
        assert all(c["source_kind"] not in internal.INTERNAL_KINDS for c in _msg(world, r).citations or [])
    hdr = ds.login(api, "edu_admin")
    n = len(api.fake.chats)
    r = api.post(
        "/assistant/ask",
        headers=hdr,
        json={"question": "our stand", "scope": "case", "case": str(scene.a), "include_internal": True},
    )
    assert r.status_code == 422 and len(api.fake.chats) == n


def test_switching_off_starts_new_conversation(world, scene):
    on = ol.switch(world, "edu_admin", scene.a)
    conn = _conn(world)
    ol.ask(
        world,
        "edu_admin",
        "our stand on the quokka",
        "case",
        conn,
        case=scene.a,
        conversation_id=on["conversation_id"],
    )
    assert W["saved"] in conn.fake.sent_text()
    fresh = _conn(world)
    r = ol.ask(world, "edu_admin", "our stand on the quokka", "case", fresh, case=scene.a)
    assert r.conversation_id != on["conversation_id"]
    assert _conv(world, r.conversation_id).internal_included_at is None
    text = fresh.fake.sent_text()
    assert all(word not in text for word in INTERNAL_WORDS)
    assert len(fresh.fake.chats[0]["messages"]) == 2  # system and the question: no history of the other one
    with world.Session() as s:
        with pytest.raises(sa.exc.DBAPIError):
            s.execute(
                sa.text("UPDATE assistant_conversations SET internal_included_at = NULL WHERE id = :i"),
                {"i": on["conversation_id"]},
            )
        s.rollback()
        with pytest.raises(sa.exc.DBAPIError):
            s.execute(
                sa.text(
                    "UPDATE assistant_conversations SET internal_included_at = now() + interval '1 hour' WHERE id = :i"
                ),
                {"i": on["conversation_id"]},
            )
        s.rollback()
        mine = ol.ask(world, "edu_admin", "quokka scheme", "my_cases", _conn(world)).conversation_id
        with pytest.raises(sa.exc.IntegrityError):
            s.execute(
                sa.text("UPDATE assistant_conversations SET internal_included_at = now() WHERE id = :i"),
                {"i": mine},
            )
        s.rollback()


def test_switch_refused_in_other_modes_and_without_guard(world, scene):
    for mode in ("preview", "sourcetrace", "off"):
        with pytest.raises(svc.InternalUnavailable):
            ol.switch(world, "edu_admin", scene.a, mode=mode)
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        access.set_override(
            s,
            actor,
            root,
            world.membership(s, "edu_admin"),
            Permission.CASES_VIEW_SCOPE,
            PermissionEffect.DENY,
        )
        s.commit()
    with pytest.raises((svc.InternalNotPermitted, NotVisibleCase)):
        ol.switch(world, "edu_admin", scene.a)
    # nothing to include: a fresh case with no custody, note or document
    from tests.db import alerts_support as h
    from tests.db.world import make_case

    with world.Session() as s:
        bare = make_case(s, case_no="WP(C)/777/2026")
        h.claim(s, world, "health_admin", bare)
        s.execute(sa.delete(CustodyHistory).where(CustodyHistory.case_id == bare.id)) if False else None
        s.commit()
        bare_id = bare.id
    with world.Session() as s:
        legs = s.scalar(
            sa.select(sa.func.count()).select_from(CustodyHistory).where(CustodyHistory.case_id == bare_id)
        )
    if not legs:
        with pytest.raises(svc.NoInternalRecords):
            ol.switch(world, "health_admin", bare_id)
    assert _audits(world, "assistant.internal_included") == []


def test_question_racing_the_switch_sees_one_state(world, scene):
    conn = _conn(world)
    r = ol.ask(world, "edu_admin", "quokka scheme", "case", conn, case=scene.a)
    done = threading.Event()
    with world.Session() as holder:
        holder.execute(
            sa.select(AssistantConversation)
            .where(AssistantConversation.id == r.conversation_id)
            .with_for_update()
        )

        def run():
            ol.switch(world, "edu_admin", scene.a, r.conversation_id)
            done.set()

        t = threading.Thread(target=run)
        t.start()
        time.sleep(0.6)
        assert not done.is_set()  # the switch waits for the row lock transaction A takes
        holder.commit()
    t.join(10)
    assert done.is_set() and _conv(world, r.conversation_id).internal_included_at is not None


def test_suggestion_is_keyword_only_and_never_switches(world, scene):
    conn = _conn(world)
    r = ol.ask(world, "edu_admin", "who has the file on the quokka scheme?", "case", conn, case=scene.a)
    assert len(conn.fake.chats) == 1
    assert _msg(world, r).model_info["suggest_internal"] is True
    assert sup.read(world, "edu_admin", r)["suggest_internal"] is True
    assert _conv(world, r.conversation_id).internal_included_at is None
    r2 = ol.ask(world, "edu_admin", "what did the court say on the quokka scheme", "case", conn, case=scene.a)
    assert _msg(world, r2).model_info["suggest_internal"] is False
    other = ol.other_case(world)
    r3 = ol.ask(world, "health_admin", "who has the file", "case", _conn(world), case=other)
    with world.Session() as s:
        has = internal.visible_count(s, world.user(s, "health_admin"), s.get(Case, other))
    assert _msg(world, r3).model_info.get("suggest_internal") is bool(has)


def test_assistant_never_acts(world, scene):
    def counts():
        with world.Session() as s:
            return tuple(
                s.scalar(sa.select(sa.func.count()).select_from(t))
                for t in (CustodyHistory, CaseStage, CaseNote, Document, Custody)
            )

    before = counts()
    on = ol.switch(world, "edu_admin", scene.a)
    for scope, kw in (
        ("case", {"case": scene.a, "conversation_id": on["conversation_id"]}),
        ("my_cases", {}),
        ("research", {}),
    ):
        ol.ask(world, "edu_admin", "quokka scheme stand", scope, _conn(world), **kw)
    assert counts() == before


# ------------------------------------------------------------------------------------------------ internal records


def _switched_ask(world, key, case, question="our stand on the quokka scheme", conn=None):
    on = ol.switch(world, key, case)
    conn = conn or _conn(world)
    r = ol.ask(world, key, question, "case", conn, case=case, conversation_id=on["conversation_id"])
    return r, conn


def test_case_tab_reads_visible_internal_records_of_its_case(world, scene):
    with world.Session() as s:
        a = s.get(Case, scene.a)
        saved = s.scalar(
            sa.select(CaseNote).where(CaseNote.case_id == a.id, CaseNote.body.contains(W["saved"]))
        )
        actor, admin = world.actor(s, "edu_admin")
        notes.add_note(
            s,
            actor,
            admin,
            a,
            kind=None,
            body="Correction: we accept the numbat claim.",
            visibility_="case_scope",
            supersedes=saved.ref_no,
        )
        s.commit()
    r, conn = _switched_ask(world, "edu_admin", scene.a)
    text = conn.fake.sent_text()
    for word in (W["saved"], W["remark"], W["internal"]):
        assert word in text, word
    assert (
        "Note (Internal)" in text
        and "File Movement (Internal)" in text
        and "Department Document (Internal)" in text
    )
    assert "Corrected by Note" in text and "Corrects Note" in text
    assert "pending action" in text and "due date" in text
    msg = _msg(world, r)
    kinds = {c["source_kind"] for c in msg.citations}
    assert {"note", "file_movement", "department_document"} <= kinds
    stored = json.dumps(msg.citations)
    for word in (W["saved"], W["remark"], W["internal"]):
        assert word not in stored  # references, never text


def _page_readers(world, key, case_id):
    """What the case page's own readers return to `key`: notes, legs with or without remarks, internal documents."""
    with world.Session() as s:
        user = world.user(s, key)
        case = s.get(Case, case_id)
        try:
            ns = {n["id"] for n in notes.list_for_case(s, user, case, limit=200).items}
            hist = custody.history(s, user, case, limit=30, order="desc")
            docs = {
                d["id"] for d in documents_svc.list_for_case(s, user, case, group="internal", limit=200).items
            }
        except NotVisibleCase:
            return set(), None, set()
        return ns, hist["remarks_shown"], docs


@pytest.mark.parametrize("key", ["edu_admin", "dse_user", "edu_counsel", "oversight", "root"])
def test_internal_set_equals_case_page_readers(world, scene, key):
    with world.Session() as s:
        user = world.user(s, key)
        case = s.get(Case, scene.a)
        guard = internal.read_guard(s, user) and internal._allowed(s, user, case)
        rec = internal.gather(s, user, case, "quokka", budget_chars=100_000)
        s.rollback()
    ns, remarks, docs = _page_readers(world, key, scene.a)
    if not guard:
        assert rec.empty
        return
    assert {n.note_id for n in rec.notes} == ns
    assert (rec.file_movement.remarks if rec.file_movement else None) == remarks
    with world.Session() as s:
        clean_text = {d for d in docs if s.get(Document, d).virus_scan_status.value == "clean"}
    assert {d.document_id for d in rec.documents if d.kind == "department_document"} == clean_text


def _negative(world, key, case, word, question=None):
    r, conn = _switched_ask(world, key, case, question or "what do the records say about the quokka scheme")
    assert word not in conn.fake.sent_text()
    msg = _msg(world, r)
    assert word not in json.dumps(msg.citations or [])
    return r


def test_private_note_of_another_office_never_read(world, scene):
    ns, _r, _d = _page_readers(world, "dse_user", scene.a)
    with world.Session() as s:
        private = s.scalar(sa.select(CaseNote.id).where(CaseNote.body.contains(W["private"])))
    assert private not in ns  # the case page does not show it to the directorate
    _negative(world, "dse_user", scene.a, W["private"])


def test_directorate_restricted_document_never_read(world, scene):
    _ns, _r, docs = _page_readers(world, "dse_user", scene.a)
    assert scene.restricted_doc not in docs
    _negative(world, "dse_user", scene.a, W["restricted"])


def test_draft_never_read_even_own(world, scene):
    _negative(world, "dse_user", scene.a, W["draft"])  # the holder's own draft
    _negative(world, "edu_admin", scene.a, W["draft"])  # another holder's draft


def test_other_case_internal_never_read(world, scene):
    _negative(world, "edu_admin", scene.a, W["other"])


def test_remark_withheld_without_working_basis(world, scene):
    _ns, remarks, _d = _page_readers(world, "oversight", scene.a)
    assert remarks is False
    r, conn = _switched_ask(world, "oversight", scene.a, "who has the quokka file")
    text = conn.fake.sent_text()
    assert W["remark"] not in text and "File Movement (Internal)" in text


def test_no_internal_without_case_read_guard(world, scene):
    conn = _conn(world)
    r = ol.ask(world, "edu_admin", "quokka scheme", "case", conn, case=scene.a)
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        access.set_override(
            s,
            actor,
            root,
            world.membership(s, "edu_admin"),
            Permission.CASES_VIEW_SCOPE,
            PermissionEffect.DENY,
        )
        s.commit()
    with pytest.raises((svc.InternalNotPermitted, NotVisibleCase)):
        ol.switch(world, "edu_admin", scene.a, r.conversation_id)
    with world.Session() as s:
        user = world.user(s, "edu_admin")
        assert internal.gather(s, user, s.get(Case, scene.a), "quokka", budget_chars=10_000).empty


def test_assistant_page_cannot_request_internal(world, scene, api):
    hdr = ds.login(api, "edu_admin")
    n = len(api.fake.chats)
    for scope in ("research", "my_cases"):
        r = api.post(
            "/assistant/ask",
            headers=hdr,
            json={"question": "quokka", "scope": scope, "include_internal": True},
        )
        assert r.status_code == 422
    r = api.post(
        "/assistant/ask", headers=hdr, json={"question": "quokka", "scope": "research", "case": str(scene.a)}
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "scope_mismatch"
    assert len(api.fake.chats) == n
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(AssistantMessage)) == 0


def test_case_tab_conversation_cannot_change_case(world, scene):
    on = ol.switch(world, "edu_admin", scene.a)
    conn = _conn(world)
    with pytest.raises(svc.ScopeMismatch):
        ol.ask(
            world,
            "edu_admin",
            "koala quokka",
            "case",
            conn,
            case=scene.b,
            conversation_id=on["conversation_id"],
        )
    with pytest.raises(svc.ScopeMismatch):
        ol.ask(world, "edu_admin", "koala quokka", "research", conn, conversation_id=on["conversation_id"])
    assert conn.fake.chats == []
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(AssistantMessage)) == 0


def test_sourcetrace_and_preview_never_get_internal(world, scene):
    r = sup.ask(world, "edu_admin", "stand quokka", "case", case=scene.a)
    assert all(
        c["source_kind"] in ("court_order", "court_filing") for c in sup.answer(world, r).citations or []
    )
    fake = FakeSourceTrace()
    sup.ask(world, "edu_admin", "stand quokka", "case", case=scene.a, connector=fake)
    assert fake.asked and all(W["saved"] not in str(q) for q in fake.asked)


def test_internal_citation_from_connector_outside_rules_withholds(world, scene):
    with world.Session() as s:
        b_note = s.scalar(sa.select(CaseNote.id).where(CaseNote.case_id == scene.b))

    class Rogue(type(_conn(world))):
        async def ask_case(self, request, internal_, *, details=False):
            return Answer(
                text="It says so [S1].",
                citations=(
                    Citation(
                        reference="x",
                        label="S1",
                        source_kind="note",
                        record={"note_id": str(b_note), "chars": [0, 5]},
                    ),
                ),
            )

    rogue = Rogue(world.Session, ol.settings(), client=FakeOllama().client())
    on = ol.switch(world, "edu_admin", scene.a)
    r = ol.ask(
        world, "edu_admin", "quokka", "case", rogue, case=scene.a, conversation_id=on["conversation_id"]
    )
    msg = _msg(world, r)
    assert r.outcome == "failed" and msg.error_family == "scope"
    r2 = ol.ask(world, "edu_admin", "quokka", "case", rogue, case=scene.a)  # not switched on
    assert _msg(world, r2).error_family == "scope"


# ------------------------------------------------------------------------------------------------ reading back


def test_reread_hides_answer_when_internal_record_no_longer_visible(world, scene):
    r, _conn_ = _switched_ask(world, "edu_admin", scene.a, "the wallaby opinion on the quokka scheme")
    out = sup.read(world, "edu_admin", r)
    assert out["content"] and out["internal_used"] in (True, False)
    with world.Session() as s:
        doc = s.get(Document, scene.internal_doc)
        doc.archived_at = sa.func.now()
        doc.archive_reason = "test"
        s.commit()
    out = sup.read(world, "edu_admin", r)
    assert out["content"] is None and out["hidden_reason"] == svc.HIDDEN_INTERNAL
    gone = [c for c in out["citations"] if c["source_kind"] == "department_document"]
    assert any(c["available"] is False and c["document_id"] is None and c["context"] is None for c in gone)


def test_reread_hides_answer_when_remark_no_longer_shown(world, scene, monkeypatch):
    r, _c = _switched_ask(world, "edu_admin", scene.a, "who has the quokka file")
    assert sup.read(world, "edu_admin", r)["content"]
    monkeypatch.setattr(custody, "shows_remark", lambda *a, **k: False)
    out = sup.read(world, "edu_admin", r)
    assert out["content"] is None


def test_corrected_note_marked_on_reread(world, scene):
    r, _c = _switched_ask(world, "edu_admin", scene.a)
    with world.Session() as s:
        a = s.get(Case, scene.a)
        saved = s.scalar(
            sa.select(CaseNote).where(CaseNote.case_id == a.id, CaseNote.body.contains(W["saved"]))
        )
        actor, admin = world.actor(s, "edu_admin")
        later, _ = notes.add_note(
            s,
            actor,
            admin,
            a,
            kind=None,
            body="Correction: accepted.",
            visibility_="case_scope",
            supersedes=saved.ref_no,
        )
        s.commit()
        later_seq, saved_id = later.seq_no, saved.id
    out = sup.read(world, "edu_admin", r)
    cited = [c for c in out["citations"] if c["source_kind"] == "note" and c["note"]["id"] == saved_id]
    assert cited and cited[0]["note"]["corrected_by_seq_no"] == later_seq
    assert f"Corrected by Note {later_seq}" in cited[0]["context"]


def test_context_rerendered_not_stored_for_internal(world, scene):
    r, _c = _switched_ask(world, "edu_admin", scene.a)
    msg = _msg(world, r)
    assert all("context" not in c for c in msg.citations if c["source_kind"] in internal.INTERNAL_KINDS)
    out = sup.read(world, "edu_admin", r)
    notes_out = [c for c in out["citations"] if c["source_kind"] == "note"]
    assert notes_out and any(W["saved"] in (c["context"] or "") for c in notes_out)


def test_case_conversation_private_to_asker(world, scene, api):
    on = ol.switch(world, "edu_admin", scene.a)
    for key in ("edu_off1", "root"):
        hdr = ds.login(api, key)
        assert api.get(f"/assistant/conversations/{on['conversation_id']}", headers=hdr).status_code == 404
    hdr = ds.login(api, "edu_auditor")
    assert api.get(f"/assistant/conversations/{on['conversation_id']}", headers=hdr).status_code in (403, 404)


def test_history_never_crosses_conversations(world, scene):
    r, _c = _switched_ask(world, "edu_admin", scene.a)
    for scope, kw in (("my_cases", {}), ("case", {"case": scene.b})):
        conn = _conn(world)
        ol.ask(world, "edu_admin", "quokka koala", scope, conn, **kw)
        text = conn.fake.sent_text()
        assert W["saved"] not in text and W["remark"] not in text


def test_copy_to_note_preset_narrowest_visibility(world, scene):
    r, _c = _switched_ask(world, "edu_admin", scene.a)
    out = sup.read(world, "edu_admin", r)
    assert out["internal_used"] in (True, False)
    assert all("internal" in c for c in out["citations"])


# ------------------------------------------------------------------------------------------------ engine and records


def test_ollama_no_source_no_model_call(world, scene):
    conn = _conn(world)
    r = ol.ask(world, "edu_admin", "zanzibar xylophone", "research", conn)
    msg = _msg(world, r)
    assert r.outcome == "no_match" and msg.content == NO_MATCH_LINE and conn.fake.chats == []
    r2 = ol.ask(world, "edu_admin", "what is the", "research", conn)
    assert _msg(world, r2).model_info["reason"] == "stop_words" and conn.fake.chats == []


def test_ollama_invalid_marker_removed_and_recorded(world, scene):
    conn = _conn(world)
    conn.fake.replies.append(chat_reply("An affidavit is due [S1, S9]. Returnable on 12 April [S2][S7]."))
    r = ol.ask(world, "edu_admin", "affidavit quokka", "case", conn, case=scene.a, include_related=False)
    msg = _msg(world, r)
    assert r.outcome == "answered" and msg.model_info["invalid_markers"] == 2
    assert "[S9]" not in msg.content and "[S1]" in msg.content and "[S2]" in msg.content
    assert sup.read(world, "edu_admin", r)["checks"]["invalid_markers"] == 2


def test_ollama_answer_without_valid_citation_is_no_match(world, scene):
    conn = _conn(world)
    conn.fake.replies.append(chat_reply("The records found do not answer this question."))
    r = ol.ask(world, "edu_admin", "affidavit quokka", "case", conn, case=scene.a)
    msg = _msg(world, r)
    assert r.outcome == "no_match" and msg.content == NO_ANSWER_TEXT
    assert msg.response["message"]["content"] == "The records found do not answer this question."
    assert all(c["cited"] is False for c in msg.citations)


def test_ollama_cut_short_is_marked(world, scene):
    conn = _conn(world)
    conn.fake.replies.append(chat_reply("The affidavit is due [S1] and", done_reason="length"))
    r = ol.ask(world, "edu_admin", "affidavit quokka", "case", conn, case=scene.a)
    msg = _msg(world, r)
    assert msg.content.endswith(CUT_SHORT_LINE) and msg.model_info["cut_short"] is True


def test_ollama_over_long_prompt_is_protocol(world, scene):
    conn = _conn(world)
    conn.fake.replies.append(chat_reply("x [S1]", prompt_eval_count=16384))
    r = ol.ask(world, "edu_admin", "affidavit quokka", "case", conn, case=scene.a)
    assert _msg(world, r).error_family == "protocol"


def _count_messages(world) -> int:
    with world.Session() as s:
        return s.scalar(sa.select(sa.func.count()).select_from(AssistantMessage))


def test_ollama_loading_refused_503_nothing_stored_not_counted(world, scene, api):
    api.fake.loaded = False
    hdr = ds.login(api, "edu_admin")
    r = api.post("/assistant/ask", headers=hdr, json={"question": "quokka", "scope": "research"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "assistant_loading"
    assert r.headers["Retry-After"] == "30" and r.json()["detail"]["retry_after"] == 30
    assert _count_messages(world) == 0 and _audits(world, "assistant.asked") == []
    conn = api.app.state.assistant_connector
    if conn.load_thread is not None:
        conn.load_thread.join(5)
    assert api.fake.loads == 1
    st = api.get("/assistant/status", headers=hdr).json()
    assert st["engine"]["kind"] == "ollama"


def test_ollama_unavailable_refused_503(world, scene, api):
    api.fake.held = False
    api.fake.loaded = False
    hdr = ds.login(api, "edu_admin")
    r = api.post("/assistant/ask", headers=hdr, json={"question": "quokka", "scope": "research"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "assistant_unavailable"
    assert _count_messages(world) == 0


def test_ollama_busy_503(world, scene, api):
    conn = ol.connector(world, api.fake, assistant_ollama_slot_wait_seconds=0)
    api.app.state.assistant_connector = conn
    conn._slots.acquire()
    try:
        hdr = ds.login(api, "edu_admin")
        r = api.post("/assistant/ask", headers=hdr, json={"question": "quokka", "scope": "research"})
        assert r.status_code == 503 and r.json()["detail"]["code"] == "assistant_busy"
        assert r.headers["Retry-After"] == "5"
    finally:
        conn._slots.release()
    assert _count_messages(world) == 0


def test_ollama_unavailable_during_call_retried_once_then_failed(world, scene):
    conn = _conn(world)
    conn.fake.replies.extend(
        [httpx.Response(503, json={"error": "busy"}), httpx.Response(503, json={"error": "busy"})]
    )
    r = ol.ask(world, "edu_admin", "affidavit quokka", "case", conn, case=scene.a)
    msg = _msg(world, r)
    assert r.outcome == "failed" and msg.error_family == "unavailable" and len(conn.fake.chats) == 2
    assert msg.model_info["engine"] == "ollama"


def test_ollama_timeout_failed_timeout_request_cancelled(world, scene):
    conn = _conn(world)
    conn.fake.replies.append(Delay(30))
    started = time.monotonic()
    r = ol.ask(world, "edu_admin", "affidavit quokka", "case", conn, case=scene.a)
    assert time.monotonic() - started < 12
    assert _msg(world, r).error_family == "timeout"


def test_ollama_search_budget_spent_is_too_broad(world, scene):
    from tests.db.assistant_support import sa as _sa  # noqa: F401

    conn = _conn(world, assistant_preview_sql_ms=100)
    import aslms.services.assistant_ollama as mod

    plain = mod.search_passages

    def slow(s, *a, **k):
        a[1].arm(s)  # the budget sets the statement limit, as before every statement
        s.execute(sa.text("select pg_sleep(1)"))
        return plain(s, *a, **k)

    mod.search_passages = slow
    try:
        r = ol.ask(world, "edu_admin", "affidavit quokka", "case", conn, case=scene.a)
    finally:
        mod.search_passages = plain
    msg = _msg(world, r)
    assert msg.error_family == "timeout" and "too broad" in msg.content


def test_ollama_audit_counts_per_kind_without_text(world, scene):
    r, _c = _switched_ask(world, "edu_admin", scene.a)
    asked = _audits(world, "assistant.asked")[-1]
    answered = _audits(world, "assistant.answered")[-1]
    assert asked.after["internal"] is True
    assert set(asked.after["internal_supplied"]) == {"note", "file_movement", "department_document"}
    assert answered.after["model"] == "qwen3.5:4b" and "sources_supplied" in answered.after
    assert set(answered.after["cited"]) >= {"court_order", "note"}
    with world.Session() as s:
        dump = json.dumps([a.after for a in s.scalars(sa.select(AuditLog)).all()], default=str)
    for word in (*INTERNAL_WORDS, "our stand on the"):
        assert word not in dump


def test_ollama_logs_no_text(world, scene):
    lines: list[str] = []

    class Keep(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    handler = Keep(level=logging.DEBUG)
    loggers = [logging.getLogger(n) for n in ("aslms.services.assistant_ollama", "aslms.services.assistant")]
    for lg in loggers:
        lg.addHandler(handler)
        lg.setLevel(logging.DEBUG)
        lg.disabled = False  # alembic's fileConfig in the suite's migration disables loggers made before it
    try:
        _switched_ask(world, "edu_admin", scene.a)
    finally:
        for lg in loggers:
            lg.removeHandler(handler)
    text = " | ".join(lines)
    assert "ollama answer" in text
    for word in (*INTERNAL_WORDS, "our stand on the"):
        assert word not in text


def test_check_counts_zero_and_catch_planted_violations(world, scene):
    _switched_ask(world, "edu_admin", scene.a)
    with world.Session() as s:
        assert set(svc.check(s).values()) == {0}
    conn = _conn(world)
    r = ol.ask(world, "edu_admin", "quokka", "my_cases", conn)
    with world.Session() as s:
        b_note = s.scalar(sa.select(CaseNote.id).where(CaseNote.case_id == scene.b))
        s.execute(sa.text("ALTER TABLE assistant_messages DISABLE TRIGGER assistant_messages_append_only"))
        s.execute(
            sa.text("UPDATE assistant_messages SET citations = CAST(:c AS jsonb) WHERE id = :i"),
            {
                "c": json.dumps(
                    [
                        {"source_kind": "note", "note_id": str(b_note)},
                        {"source_kind": "mystery"},
                    ]
                ),
                "i": r.answer_id,
            },
        )
        s.execute(sa.text("ALTER TABLE assistant_messages ENABLE TRIGGER assistant_messages_append_only"))
        counts = svc.check(s)
        s.rollback()
    assert counts["internal_citations_out_of_reach"] == 1
    assert counts["internal_citations_of_another_case"] == 1  # a my-cases conversation has no case of its own
    assert counts["citations_of_unknown_kind"] == 1


@pytest.mark.migration_cycle
def test_migration_0032_mode_check_up_down(db_url, engine, world):
    """The downgrade stops while a conversation is switched on or an ollama answer exists; otherwise it drops the
    trigger, the CHECK and the column and restores the old mode CHECK; the upgrade brings them back."""
    cfg = alembic_config(db_url)
    with world.Session() as s:
        case = s.scalar(sa.select(Case.id).limit(1))
        if case is None:
            from tests.db.world import make_case

            case = make_case(s, case_no="WP(C)/321/2026").id
        conv = AssistantConversation(
            user_id=world.users["edu_admin"].id, scope=AssistantScope.CASE, case_id=case
        )
        s.add(conv)
        s.commit()
        conv_id = conv.id

    def scalar(sql: str, **kw):
        with engine.begin() as conn:
            return conn.execute(sa.text(sql), kw).scalar()

    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text("UPDATE assistant_conversations SET internal_included_at = now() WHERE id = :i"),
                {"i": conv_id},
            )
        with pytest.raises(RuntimeError, match="cannot downgrade 0032"):
            command.downgrade(cfg, "0030")
        with engine.begin() as conn:
            conn.execute(
                sa.text("SET session_replication_role = replica")
            )  # past the one-way trigger, for the test
            conn.execute(
                sa.text("UPDATE assistant_conversations SET internal_included_at = NULL WHERE id = :i"),
                {"i": conv_id},
            )
            q = conn.execute(
                sa.text(
                    "INSERT INTO assistant_messages (conversation_id, role, content) VALUES (:c, 'user', 'a question') RETURNING id"
                ),
                {"c": conv_id},
            ).scalar()
            conn.execute(
                sa.text(
                    "INSERT INTO assistant_messages (conversation_id, role, content, reply_to_id, mode, outcome) "
                    "VALUES (:c, 'assistant', 'an answer', :q, 'ollama', 'answered')"
                ),
                {"c": conv_id, "q": q},
            )
        with pytest.raises(RuntimeError, match="ollama answer"):
            command.downgrade(cfg, "0030")
        wipe_if_migrated(db_url)
        command.downgrade(cfg, "0030")
        assert (
            scalar(
                "select count(*) from information_schema.columns where table_name = 'assistant_conversations' "
                "and column_name = 'internal_included_at'"
            )
            == 0
        )
        assert (
            scalar("select count(*) from pg_trigger where tgname = 'assistant_conversations_internal_once'")
            == 0
        )
        assert "'ollama'" not in scalar(
            "select pg_get_constraintdef(oid) from pg_constraint where conname = 'ck_assistant_messages_role_shape'"
        )
        command.upgrade(cfg, "head")
        assert "'ollama'" in scalar(
            "select pg_get_constraintdef(oid) from pg_constraint where conname = 'ck_assistant_messages_role_shape'"
        )
        assert (
            scalar("select count(*) from pg_trigger where tgname = 'assistant_conversations_internal_once'")
            == 1
        )
        assert (
            scalar(
                "select count(*) from pg_constraint where conname = 'ck_assistant_conversations_internal_case'"
            )
            == 1
        )
    finally:
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            wipe(conn)
    # 0032 stays in the chain below the head (row 169's merge migration 0033 joins it with 0031)
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(cfg)
    assert "0032" in {r.revision for r in script.iterate_revisions(head_revision(), "base")}


def test_cli_warm_status_and_case_ask_with_fake(world, scene, monkeypatch):
    from aslms.cli import assistant as cli_mod
    from aslms.cli.main import app as cli_app

    fake = FakeOllama(loaded=False)
    settings = ol.settings(app_env="dev")
    monkeypatch.setattr(cli_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(cli_mod, "get_sessionmaker", lambda: world.Session)
    monkeypatch.setattr(cli_mod, "session_scope", _scope(world))
    import aslms.services.assistant_ollama as mod

    real = mod.OllamaClient
    monkeypatch.setattr(mod, "OllamaClient", lambda url, **k: fake.client())
    monkeypatch.setattr(cli_mod, "OllamaClient", lambda url, **k: fake.client())
    mod._connectors.clear()
    runner = CliRunner()
    out = runner.invoke(cli_app, ["assistant", "warm"])
    assert out.exit_code == 0, out.output
    assert fake.loads == 1 and "loaded=True" in out.output
    out = runner.invoke(cli_app, ["assistant", "status"])
    assert "engine: ollama" in out.output and "readiness: ready" in out.output
    out = runner.invoke(
        cli_app,
        ["assistant", "ask", "--user", "admin.edu@example.org", "--case", str(scene.a), "affidavit quokka"],
    )
    assert out.exit_code == 0, out.output
    assert "[S1] case_details" in out.output
    conv = out.output.split("conversation: ")[1].split()[0]
    out = runner.invoke(
        cli_app,
        [
            "assistant",
            "include-internal",
            "--user",
            "admin.edu@example.org",
            "--case",
            str(scene.a),
            "--conversation",
            conv,
        ],
    )
    assert out.exit_code == 0, out.output
    rows = _audits(world, "assistant.internal_included")
    assert len(rows) == 1 and rows[0].actor_name == "cli" and rows[0].after["as_user_id"]
    out = runner.invoke(cli_app, ["assistant", "check"])
    assert out.exit_code == 0, out.output
    mod._connectors.clear()
    del real


def _scope(world):
    from contextlib import contextmanager

    @contextmanager
    def scope():
        with world.Session() as s:
            yield s
            s.commit()

    return scope


# ------------------------------------------------------------------------------------------------ the API


def test_status_engine_internal_records_and_me_mode_ollama(world, api):
    hdr = ds.login(api, "edu_admin")
    st = api.get("/assistant/status", headers=hdr).json()
    assert st["mode"] == "ollama" and st["state"] == "ready" and st["internal_records"] == "switch"
    assert st["engine"] == {"kind": "ollama", "model": "qwen3.5:4b", "readiness": "ready", "reason": None}
    assert st["banner"] == svc.OLLAMA_BANNER
    me = api.get("/me", headers=hdr).json()
    assert me["assistant_mode"] == "ollama"


def test_ask_503_codes_with_retry_after(world, api):
    api.fake.reachable = False
    hdr = ds.login(api, "edu_admin")
    r = api.post("/assistant/ask", headers=hdr, json={"question": "quokka", "scope": "research"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "assistant_unavailable"


def test_ask_forbids_extra_fields(world, api):
    hdr = ds.login(api, "edu_admin")
    r = api.post(
        "/assistant/ask", headers=hdr, json={"question": "quokka", "scope": "research", "origin": "case_tab"}
    )
    assert r.status_code == 422


def test_message_out_kinds_labels_internal_used_suggest_internal(world, scene, api):
    hdr = ds.login(api, "edu_admin")
    on = api.post("/assistant/internal-records", headers=hdr, json={"case": scene.a_cnr}).json()
    assert on["new_conversation"] is True
    api.fake.replies.append(
        lambda body: chat_reply(
            "The court directed an affidavit [S1]. According to the department's note, we contest [S4]."
        )
    )
    r = api.post(
        "/assistant/ask",
        headers=hdr,
        json={
            "question": "our stand on the quokka",
            "scope": "case",
            "case": str(scene.a),
            "conversation_id": on["conversation_id"],
        },
    )
    assert r.status_code == 200, r.text
    ans = r.json()["answer"]
    assert ans["mode"] == "ollama" and ans["engine"]["model"] == "qwen3.5:4b"
    kinds = [c["source_kind"] for c in ans["citations"]]
    assert kinds[0] == "case_details" and "file_movement" in kinds
    assert all(c["label"] for c in ans["citations"])
    assert ans["suggest_internal"] is False


def test_internal_records_route_shapes_and_errors(world, scene, api):
    hdr = ds.login(api, "edu_admin")
    r = api.post("/assistant/internal-records", headers=hdr, json={"case": str(scene.a), "extra": 1})
    assert r.status_code == 422
    r = api.post("/assistant/internal-records", headers=hdr, json={"case": str(uuid.uuid4())})
    assert r.status_code == 404
    r = api.post(
        "/assistant/internal-records", headers=ds.login(api, "health_off"), json={"case": str(scene.a)}
    )
    assert r.status_code == 404
    r = api.post(
        "/assistant/internal-records",
        headers=hdr,
        json={"case": str(scene.a), "conversation_id": str(uuid.uuid4())},
    )
    assert r.status_code == 404
    api.app.state.assistant_connector = sup.preview(world)
    r = api.post("/assistant/internal-records", headers=hdr, json={"case": str(scene.a)})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "internal_unavailable"


def test_conversation_out_internal_included_at(world, scene, api):
    hdr = ds.login(api, "edu_admin")
    on = api.post("/assistant/internal-records", headers=hdr, json={"case": str(scene.a)}).json()
    items = api.get("/assistant/conversations", headers=hdr, params={"scope": "case"}).json()["items"]
    mine = [i for i in items if i["id"] == on["conversation_id"]]
    assert mine and mine[0]["internal_included_at"] == on["internal_included_at"]
    assert mine[0]["title"] == svc.NEW_TITLE and mine[0]["message_count"] == 0


def test_service_card_in_system_health(world, api):
    from aslms.services import service_checks

    hdr = ds.login(api, "root")
    probes = service_checks.default_probes()
    probes.assistant_model = lambda settings: api.fake.client().state_sync("qwen3.5:4b")
    probes.redis = lambda st: {"ping_ms": 1, "version": "7", "used": 1, "max": 0}
    api.app.state.service_probes = probes
    r = api.get("/admin/system-health/services", headers=hdr)
    assert r.status_code == 200, r.text
    card = [c for c in r.json()["services"] if c["key"] == "assistant_model"]
    assert card and card[0]["status"] == "ok" and card[0]["label"] == "Case Assistant Model"
    assert "127.0.0.1" not in json.dumps(card)


__all__ = ["MessageRole", "Visibility", "asyncio", "wipe_if_migrated", "Actor"]


# ------------------------------------------------------------------------------------------------ design assistant-polish


def copycat(body: dict) -> dict:
    """A 4B model at its worst: it echoes the last earlier answer it is sent, or (when it is sent none) a line built
    from the question, citing [S1]."""
    earlier = [m["content"] for m in body["messages"] if m["role"] == "assistant"]
    if earlier:
        return chat_reply(f"{earlier[-1]} [S1]")
    question = body["messages"][-1]["content"].rsplit("Question: ", 1)[1]
    return chat_reply(f"Asked about {question} here [S1].")


Q1 = "what did the court direct on the quokka scheme affidavit"
Q2 = "when is the affidavit on the quokka scheme returnable"


@pytest.mark.parametrize("history_answers", ["full", "none"])
def test_copycat_model_repeats_only_with_full_history(world, scene, history_answers):
    fake = FakeOllama(default=copycat)
    conn = ol.connector(world, fake, assistant_ollama_history_answers=history_answers)
    r1 = ol.ask(world, "edu_admin", Q1, "case", conn, case=scene.a)
    r2 = ol.ask(world, "edu_admin", Q2, "case", conn, case=scene.a, conversation_id=r1.conversation_id)
    first, second = _msg(world, r1), _msg(world, r2)
    assert first.outcome == second.outcome == "answered"
    assert first.model_info["overlap_prev"] is None
    assert second.model_info["history_answers"] == history_answers
    second_request = json.dumps(fake.chats[1])
    if history_answers == "full":
        assert second.model_info["overlap_prev"] >= 0.9
        assert "Asked about" in second_request
    else:
        assert "Asked about" not in second_request  # the earlier answer is never sent
        assert [m["role"] for m in fake.chats[1]["messages"]] == ["system", "user"]
        assert f"- {Q1}" in fake.chats[1]["messages"][1]["content"]
        assert second.model_info["overlap_prev"] < 0.5


@pytest.mark.parametrize("history_answers", ["full", "none"])
def test_no_match_turns_not_fed_back(world, scene, history_answers):
    fake = FakeOllama()
    fake.replies = [chat_reply("I could not find it.")]  # no valid marker: the fixed no-answer line
    conn = ol.connector(world, fake, assistant_ollama_history_answers=history_answers)
    r1 = ol.ask(world, "edu_admin", "unanswerable quokka puzzle", "case", conn, case=scene.a)
    assert _msg(world, r1).outcome == "no_match"
    ol.ask(world, "edu_admin", Q2, "case", conn, case=scene.a, conversation_id=r1.conversation_id)
    second = json.dumps(fake.chats[1])
    assert "unanswerable quokka puzzle" not in second and NO_ANSWER_TEXT not in second
    assert "Earlier questions" not in second
    assert len(fake.chats[1]["messages"]) == 2


def test_overlap_prev_recorded_and_audited(world, scene):
    fake = FakeOllama()
    fake.replies = [
        chat_reply("The respondents shall file an affidavit on the quokka scheme within four weeks [S2]."),
        chat_reply("The matter is returnable on 12 April 2026 as the order says [S2]."),
    ]
    conn = _conn(world)
    conn.client = fake.client()
    r1 = ol.ask(world, "edu_admin", Q1, "case", conn, case=scene.a)
    r2 = ol.ask(world, "edu_admin", Q2, "case", conn, case=scene.a, conversation_id=r1.conversation_id)
    m1, m2 = _msg(world, r1), _msg(world, r2)
    assert m1.model_info["overlap_prev"] is None and m1.model_info["history_answers"] == "none"
    assert isinstance(m2.model_info["overlap_prev"], float) and 0 <= m2.model_info["overlap_prev"] < 0.5
    rows = _audits(world, "assistant.answered")
    assert rows[-2].after["overlap_prev"] is None
    assert rows[-1].after["overlap_prev"] == m2.model_info["overlap_prev"]
    blob = json.dumps(rows[-1].after)
    assert "returnable" not in blob and "quokka" not in blob


REPEAT_ORDER = [
    "The court directs the respondents to file an affidavit in this whole case, a service matter. The recent order "
    "needs to be done next week by the department. The reason given for the adjournment is the absence of counsel. "
    "The earlier order is summarised in two sentences."
]


def _repeat_cli(world, monkeypatch, *, history_answers: str, app_env: str = "dev"):
    from aslms.cli import assistant as cli_mod

    fake = FakeOllama(default=copycat)
    settings = ol.settings(app_env=app_env, assistant_ollama_history_answers=history_answers)
    monkeypatch.setattr(cli_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(cli_mod, "get_sessionmaker", lambda: world.Session)
    import aslms.services.assistant_ollama as mod

    monkeypatch.setattr(mod, "OllamaClient", lambda url, **k: fake.client())
    mod._connectors.clear()
    return fake


def test_repeat_check_cli(world, scene, monkeypatch):
    from aslms.cli.main import app as cli_app

    with world.Session() as s:
        a = s.get(Case, scene.a)
        sup.order(s, scene.store, a, REPEAT_ORDER, order_no="6")
        s.commit()
    runner = CliRunner()
    # refused with APP_ENV=prod
    _repeat_cli(world, monkeypatch, history_answers="none", app_env="prod")
    out = runner.invoke(
        cli_app, ["assistant", "repeat-check", "--user", "admin.edu@example.org", "--case", str(scene.a)]
    )
    assert out.exit_code == 2, out.output
    # mode B, a copycat model with full history: fails
    fake = _repeat_cli(world, monkeypatch, history_answers="full")
    out = runner.invoke(
        cli_app, ["assistant", "repeat-check", "--user", "admin.edu@example.org", "--case", str(scene.a)]
    )
    assert out.exit_code == 1, out.output
    assert "FAIL" in out.output and out.output.count("case_record") == 2
    assert len(fake.chats) == 6  # 8 questions, two of them quick facts
    with world.Session() as s:
        convs = s.scalars(sa.select(AssistantConversation).order_by(AssistantConversation.created_at)).all()
        assert len(convs) == 1
        failing = convs[0].id
        n = s.scalar(
            sa.select(sa.func.count())
            .select_from(AssistantMessage)
            .where(AssistantMessage.conversation_id == failing, AssistantMessage.role == MessageRole.USER)
        )
        assert n == 8
    # mode B with questions only: passes
    _repeat_cli(world, monkeypatch, history_answers="none")
    out = runner.invoke(
        cli_app, ["assistant", "repeat-check", "--user", "admin.edu@example.org", "--case", str(scene.a)]
    )
    assert out.exit_code == 0, out.output
    assert "PASS" in out.output and out.output.count("case_record") == 2
    # mode A, stored: numbers only, never a question or an answer
    out = runner.invoke(
        cli_app,
        ["assistant", "repeat-check", "--user", "admin.edu@example.org", "--conversation", str(failing)],
    )
    assert out.exit_code == 1, out.output
    for planted in ("adjournment", "Asked about", "affidavit", "DINAR", "versus", "Summarise"):
        assert planted not in out.output, planted
    assert "maximum 1.00" in out.output
    # another user's conversation is refused
    out = runner.invoke(
        cli_app,
        ["assistant", "repeat-check", "--user", "admin.health@example.org", "--conversation", str(failing)],
    )
    assert out.exit_code == 2 and "Error" in out.output and "answer(s)" not in out.output
    import aslms.services.assistant_ollama as mod

    mod._connectors.clear()
