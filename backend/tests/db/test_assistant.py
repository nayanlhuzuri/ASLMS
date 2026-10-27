"""The Case Assistant against the database (design `assistant`, "Tests", database): the preview's passages, pages,
fallback and limits; the eligibility rule (court orders open to every assistant user, court filings under the
document visibility, nothing internal ever); the court-record view behind a citation; conversations private and
append-only; the hourly, in-flight and size limits; audit without text; re-reading; the SourceTrace path through the
fake; the CLI; the check; the merge rule; migration 0024."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import timedelta

import pytest
import sqlalchemy as sa
from alembic import command
from psycopg import errors as pg_errors
from typer.testing import CliRunner

from aslms.core.config import Settings
from aslms.domain.assistant import AssistantConversation, AssistantMessage, AssistantScope, MessageRole
from aslms.domain.cases import Case
from aslms.domain.documents import DocGroup, DocKind, Document, SourcetraceStatus, Visibility
from aslms.domain.events import AuditLog
from aslms.domain.ownership import CaseOwnership, CounselCode
from aslms.domain.reference import DocType
from aslms.domain.workflow import Custody
from aslms.integration.sourcetrace import Answer, Citation
from aslms.integration.sourcetrace.fake import FakeSourceTrace
from aslms.services import assistant as svc
from aslms.services import assistant_sources as src
from aslms.services import case_dedupe
from aslms.services.assistant_preview import PREVIEW_LINE, TOO_BROAD
from tests.db import alerts_support as h
from tests.db import assistant_support as sup
from tests.db import docs_support as ds
from tests.db import workflow_support as w
from tests.db.conftest import alembic_config, wipe, wipe_if_migrated
from tests.db.test_case_visibility import entry_with_codes
from tests.db.world import make_case


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path, assistant_mode="preview")
    client.app.state.assistant_config = sup.CONFIG
    yield client
    client.__exit__(None, None, None)


@pytest.fixture()
def scene(world, api):
    """Case A owned by EDU (allotted to edu_off1, who holds the file); case H owned by HEALTH. Each has one court
    order with stored text: A's names an affidavit on page 2, both name the quokka scheme."""
    store = api.store
    with world.Session() as s:
        a = w.claimed_case(s, world, officer="edu_off1", case_no="WP(C)/101/2026")
        hc = make_case(s, case_no="WP(C)/202/2026")
        h.claim(s, world, "health_admin", hc)
        o_a, d_a = sup.order(
            s,
            store,
            a,
            [
                "The petitioner seeks salary arrears for the period of service.",
                "The respondents shall file an affidavit within four weeks on the quokka scheme.",
            ],
            order_no="5",
        )
        o_h, d_h = sup.order(
            s,
            store,
            hc,
            [
                "Orders on regularisation of contractual teachers under the quokka scheme.",
                "List after four weeks.",
            ],
            order_no="2",
        )
        s.commit()
        return {
            "a": a.id,
            "a_cnr": a.cnr,
            "h": hc.id,
            "o_a": o_a.id,
            "d_a": d_a.id,
            "o_h": o_h.id,
            "d_h": d_h.id,
            "store": store,
        }


def _filing(world, scene, case_key, pages, office="EDU", **kw) -> uuid.UUID:
    with world.Session() as s:
        case = s.get(Case, scene[case_key])
        doc = sup.filing(s, scene["store"], case, world.office(s, office), pages, **kw)
        s.commit()
        return doc.id


def _doc(world, doc_id) -> Document:
    with world.Session() as s:
        return s.get(Document, doc_id)


# ------------------------------------------------------------------------------------------------ the preview


def test_preview_case_scope_returns_cited_passages_with_page(world, scene):
    r = sup.ask(world, "edu_off1", "affidavit quokka", "case", case=scene["a"], include_related=False)
    msg = sup.answer(world, r)
    assert r.outcome == "answered" and msg.mode == "preview" and msg.connector == "preview"
    assert msg.content.startswith(PREVIEW_LINE + "\n")
    assert "matched all of the words" in msg.content
    assert msg.model_info == {"engine": "postgresql_full_text", "match": "all"}
    assert [c["document_id"] for c in msg.citations] == [str(scene["d_a"])]
    c = msg.citations[0]
    assert c["page"] == 2 and "[[" in c["passage"] and "]]" in c["passage"]
    assert c["source_kind"] == "court_order" and c["order_id"] == str(scene["o_a"]) and c["related"] is False
    out = sup.read(world, "edu_off1", r)
    assert out["mode"] == "preview" and out["citations"][0]["open"]["kind"] == "document"
    assert (
        out["citations"][0]["open"]["href"]
        == f"/cases/{scene['a']}/orders/{scene['o_a']}/file?disposition=inline"
    )


def test_preview_falls_back_to_any_word_for_case_scope_only(world, scene):
    r = sup.ask(world, "edu_off1", "affidavit zanzibar", "case", case=scene["a"], include_related=False)
    msg = sup.answer(world, r)
    assert r.outcome == "answered" and msg.model_info["match"] == "any"
    assert "matched any of the words" in msg.content
    assert sup.cited_docs(world, r) == {str(scene["d_a"])}
    r2 = sup.ask(world, "health_off", "affidavit zanzibar", "research")
    assert r2.outcome == "no_match" and sup.cited_docs(world, r2) == set()


def test_preview_stop_word_question_is_no_match(world, scene):
    r = sup.ask(world, "edu_off1", "what is the", "case", case=scene["a"])
    msg = sup.answer(world, r)
    assert r.outcome == "no_match" and "Use more specific words" in msg.content and not msg.citations


def test_preview_never_reads_notes_attachments_internal_admin_or_causelists(world, scene):
    word = "wombat"
    with world.Session() as s:
        a = s.get(Case, scene["a"])
        edu = world.office(s, "EDU")
        w.note(s, world, "edu_off1", a, body=f"internal note about the {word} issue")
        sup.filing(
            s,
            scene["store"],
            a,
            edu,
            [f"note attachment {word}"],
            kind=DocKind.ATTACHMENT,
            group=DocGroup.INTERNAL,
            doc_type=DocType.LEGAL_OPINION,
        )
        sup.filing(
            s,
            scene["store"],
            a,
            edu,
            [f"internal upload {word}"],
            group=DocGroup.INTERNAL,
            doc_type=DocType.LEGAL_OPINION,
        )
        sup.filing(
            s,
            scene["store"],
            a,
            edu,
            [f"admin record {word}"],
            kind=DocKind.ADMIN,
            group=DocGroup.INTERNAL,
            visibility=Visibility.PRIVATE_TO_OFFICE,
            doc_type=DocType.GOVERNMENT_ORDER,
        )
        sup.causelist_doc(s, scene["store"], [f"daily cause list {word}"])
        s.commit()
    for key, scope, case in (
        ("edu_admin", "case", scene["a"]),
        ("edu_admin", "research", None),
        ("root", "research", None),
        ("edu_off1", "my_cases", None),
    ):
        r = sup.ask(world, key, word, scope, case=case)
        assert r.outcome == "no_match", (key, scope)
        assert sup.cited_docs(world, r) == set()


def test_private_filing_never_in_corpus_even_for_its_office(world, scene):
    doc_id = _filing(world, scene, "a", ["platypus petition"], visibility=Visibility.PRIVATE_TO_OFFICE)
    with world.Session() as s:
        from aslms.services import visibility

        assert visibility.can_view_document(s, world.user(s, "edu_admin"), doc_id)  # the office sees it
    for scope, case in (("case", scene["a"]), ("research", None)):
        r = sup.ask(world, "edu_admin", "platypus", scope, case=case)
        assert r.outcome == "no_match" and sup.cited_docs(world, r) == set()


def test_archived_order_and_filing_never_cited(world, scene):
    filing_id = _filing(world, scene, "a", ["echidna petition filed"])
    with world.Session() as s:
        a = s.get(Case, scene["a"])
        _o, order_doc = sup.order(s, scene["store"], a, ["echidna order"], order_no="9")
        for d in (s.get(Document, filing_id), order_doc):
            d.archived_at = sa.func.now()
            d.archive_reason = "test"
        s.commit()
    for key, scope, case in (("edu_admin", "case", scene["a"]), ("edu_admin", "research", None)):
        r = sup.ask(world, key, "echidna", scope, case=case)
        assert r.outcome == "no_match" and sup.cited_docs(world, r) == set()


def test_preview_sql_timeout_is_failed_timeout(world, scene):
    slow = sup.preview(world, assistant_preview_sql_ms=100)
    slow.before_search = lambda s: s.execute(sa.text("select pg_sleep(1)"))
    r = sup.ask(world, "edu_off1", "quokka", "research", connector=slow)
    msg = sup.answer(world, r)
    assert r.outcome == "failed" and msg.error_family == "timeout" and msg.content == TOO_BROAD
    assert msg.mode == "preview"


def test_related_orders_never_use_the_any_word_fallback(world, scene):
    # A's order has "quokka" but not "zanzibar": the focus falls back to any word; H's order has "quokka" too, but
    # the related orders are searched with every word only (review finding 4)
    r = sup.ask(world, "edu_off1", "quokka zanzibar", "case", case=scene["a"])
    msg = sup.answer(world, r)
    assert r.outcome == "answered" and msg.model_info == {"engine": "postgresql_full_text", "match": "any"}
    assert sup.cited_docs(world, r) == {str(scene["d_a"])}
    r = sup.ask(world, "edu_off1", "quokka", "case", case=scene["a"])
    assert sup.cited_docs(world, r) == {str(scene["d_a"]), str(scene["d_h"])}  # every word: related found


@pytest.mark.parametrize("fault", ["pg_sleep(1) IS NOT NULL", "(1 / (random() * 0)::int) = 1"])
def test_related_orders_failure_drops_only_the_related_section(world, scene, monkeypatch, fault):
    from aslms.services import assistant_preview as preview_mod

    plain = preview_mod.court_order_condition

    def faulty(**kw):
        cond = plain(**kw)
        return sa.and_(cond, sa.text(fault)) if kw.get("exclude_case_ids") else cond

    monkeypatch.setattr(preview_mod, "court_order_condition", faulty)
    conn = sup.preview(world, assistant_preview_sql_ms=300)
    r = sup.ask(world, "edu_off1", "quokka", "case", case=scene["a"], connector=conn)
    msg = sup.answer(world, r)
    assert r.outcome == "answered" and sup.cited_docs(world, r) == {str(scene["d_a"])}
    assert msg.model_info == {"engine": "postgresql_full_text", "match": "all", "related": "dropped"}


class _Statements:
    """Counts the preview's searches after the first statement (the hook runs after the budget is armed)."""

    def __init__(self, monkeypatch):
        from aslms.services.assistant_preview import PreviewConnector

        self.ranks = 0
        plain = PreviewConnector._rank

        def counted(conn, *a, **k):
            self.ranks += 1
            return plain(conn, *a, **k)

        monkeypatch.setattr(PreviewConnector, "_rank", counted)


def test_preview_whole_search_bounded_by_the_answer_limit(world, scene):
    import time as _time

    # per statement 60 s, but the answer limit of 3 s leaves a budget of 2.25 s for the whole search (finding 5)
    slow = sup.preview(world, assistant_preview_sql_ms=60_000, assistant_timeout_seconds=3)
    slow.before_search = lambda s: s.execute(sa.text("select pg_sleep(10)"))
    started = _time.monotonic()
    r = sup.ask(world, "edu_off1", "quokka", "research", connector=slow)
    took = _time.monotonic() - started
    msg = sup.answer(world, r)
    assert r.outcome == "failed" and msg.error_family == "timeout" and msg.content == TOO_BROAD
    assert took < 5, took


def test_preview_stops_between_statements_once_the_budget_is_spent(world, scene, monkeypatch):
    import time as _time

    seen = _Statements(monkeypatch)
    conn = sup.preview(world, assistant_timeout_seconds=1)  # a budget of 0.75 s
    conn.before_search = lambda s: _time.sleep(0.9)
    r = sup.ask(world, "edu_off1", "quokka", "research", connector=conn)
    assert sup.answer(world, r).error_family == "timeout" and seen.ranks == 0


def test_preview_stops_once_the_answer_has_failed(world, scene, monkeypatch):
    import time as _time

    seen = _Statements(monkeypatch)
    conn = sup.preview(world)  # its own budget is long; the service's answer limit is not
    conn.before_search = lambda s: _time.sleep(0.8)
    cfg = svc.AssistantConfig(timeout_seconds=0.2, retry_delay=0.01)
    r = sup.ask(world, "edu_off1", "quokka", "research", connector=conn, config=cfg)
    assert sup.answer(world, r).error_family == "timeout"
    _time.sleep(1.0)  # the search thread wakes after the answer was stored, and must not query again
    assert seen.ranks == 0


# ------------------------------------------------------------------------------------------------ court-public orders


def test_other_department_finds_and_opens_court_order_by_research(world, scene, api):
    hdr = ds.login(api, "health_off")
    r = api.post("/assistant/ask", headers=hdr, json={"question": "affidavit quokka", "scope": "research"})
    assert r.status_code == 200, r.text
    answer = r.json()["answer"]
    assert answer["outcome"] == "answered" and answer["mode"] == "preview"
    cited = [c for c in answer["citations"] if c["order_id"] == str(scene["o_a"])]
    assert cited and cited[0]["case"]["visible"] is False and cited[0]["case"]["id"] is None
    assert cited[0]["open"] == {
        "kind": "court_order",
        "href": f"/assistant/court-orders/{scene['o_a']}?message={answer['id']}",
    }
    v = api.get(f"/assistant/court-orders/{scene['o_a']}", headers=hdr, params={"message": answer["id"]})
    assert v.status_code == 200, v.text
    body = v.json()
    assert body["case_visible"] is False and body["order"]["order_no"] == "5"
    assert body["case"]["cnr"] == scene["a_cnr"] and body["case"]["case_no_text"] == "WP(C)/101/2026"
    f = api.get(f"/assistant/court-orders/{scene['o_a']}/file", headers=hdr, params={"message": answer["id"]})
    assert f.status_code == 200 and f.content.startswith(b"%PDF")
    assert (
        f.headers["content-security-policy"] == "sandbox" and f.headers["x-content-type-options"] == "nosniff"
    )
    with world.Session() as s:
        rows = ds.audit_rows(s, "assistant.court_order_opened")
    assert [r.after["what"] for r in rows] == ["facts", "file"]
    assert all(
        r.entity_type == "order" and r.entity_id == scene["o_a"] and r.case_id == scene["a"] for r in rows
    )
    assert all(r.after["case_visible"] is False and r.after["message_id"] == answer["id"] for r in rows)


def test_other_department_never_gets_notes_uploads_or_remarks(world, scene, api):
    word = "kangaroo"
    filing_id = _filing(world, scene, "a", [f"{word} petition as filed"])
    internal_id = _filing(
        world,
        scene,
        "a",
        [f"{word} internal opinion"],
        group=DocGroup.INTERNAL,
        doc_type=DocType.LEGAL_OPINION,
    )
    with world.Session() as s:
        a = s.get(Case, scene["a"])
        w.note(s, world, "edu_off1", a, body=f"the {word} note")
        w.send(s, world, "edu_off1", a, "dse_user", remark=f"see the {word} papers")
        _o, order_doc = sup.order(s, scene["store"], a, [f"the {word} direction of the court"], order_no="7")
        s.commit()
        order_doc_id = order_doc.id
    hdr = ds.login(api, "health_off")
    r = api.post("/assistant/ask", headers=hdr, json={"question": word, "scope": "research"})
    assert r.status_code == 200, r.text
    answer = r.json()["answer"]
    assert {c["document_id"] for c in answer["citations"]} == {str(order_doc_id)}
    assert all(c["source_kind"] == "court_order" for c in answer["citations"])
    for doc_id in (filing_id, internal_id):
        assert api.get(f"/documents/{doc_id}", headers=hdr).status_code == 404
        assert api.get(f"/documents/{doc_id}/file", headers=hdr).status_code == 404
    order_id = answer["citations"][0]["order_id"]
    v = api.get(f"/assistant/court-orders/{order_id}", headers=hdr, params={"message": answer["id"]}).json()
    assert set(v) == {"order", "case", "case_visible"}
    flat = json.dumps(v).lower()
    for banned in (
        "owner",
        "custody",
        "stage",
        "note",
        "documents",
        "ref_no",
        "recommend",
        "kangaroo papers",
    ):
        assert banned not in flat, banned
    assert api.get(f"/cases/{scene['a']}", headers=hdr).status_code == 404


def test_case_scope_related_orders_from_other_cases_marked_related(world, scene):
    r = sup.ask(world, "edu_off1", "quokka", "case", case=scene["a"])
    msg = sup.answer(world, r)
    by_doc = {c["document_id"]: c for c in msg.citations}
    assert set(by_doc) == {str(scene["d_a"]), str(scene["d_h"])}
    assert by_doc[str(scene["d_a"])]["related"] is False and by_doc[str(scene["d_h"])]["related"] is True
    out = {c["document_id"]: c for c in sup.read(world, "edu_off1", r)["citations"]}
    assert out[scene["d_h"]]["open"]["kind"] == "court_order"  # edu_off1 cannot open H
    assert out[scene["d_a"]]["open"]["kind"] == "document"
    r2 = sup.ask(world, "edu_off1", "quokka", "case", case=scene["a"], include_related=False)
    assert sup.cited_docs(world, r2) == {str(scene["d_a"])}


def test_court_filing_follows_document_visibility(world, scene):
    with world.Session() as s:
        s.add(CounselCode(code="SC, EDU", office_id=world.office(s, "EDU-SC").id))
        s.flush()
        entry_with_codes(s, s.get(Case, scene["a"]), ["SC, EDU"])
        s.commit()
    scoped = _filing(world, scene, "a", ["dingo petition for the department"])
    shared = _filing(
        world,
        scene,
        "a",
        ["dingo instructions to counsel"],
        visibility=Visibility.COUNSEL_SHARED,
        doc_type=DocType.INSTRUCTIONS_TO_COUNSEL,
    )
    r = sup.ask(world, "edu_counsel", "dingo", "case", case=scene["a"])
    assert sup.cited_docs(world, r) == {str(shared)}
    r = sup.ask(world, "edu_off1", "dingo", "case", case=scene["a"])
    assert sup.cited_docs(world, r) == {str(scoped), str(shared)}
    for key in ("health_off", "health_admin"):
        r = sup.ask(world, key, "dingo", "research")
        assert r.outcome == "no_match" and sup.cited_docs(world, r) == set(), key
    r = sup.ask(world, "edu_off1", "dingo", "research")
    assert sup.cited_docs(world, r) == {str(scoped), str(shared)}


def test_court_order_view_needs_a_citation_in_own_message(world, scene, api):
    hdr = ds.login(api, "health_off")
    mine = api.post("/assistant/ask", headers=hdr, json={"question": "affidavit quokka", "scope": "research"})
    mine_id = mine.json()["answer"]["id"]
    other = sup.ask(world, "edu_admin", "affidavit quokka", "research")
    blank = api.post("/assistant/ask", headers=hdr, json={"question": "the of and", "scope": "research"})
    url = f"/assistant/court-orders/{scene['o_a']}"
    assert api.get(url, headers=hdr).status_code == 404
    assert api.get(url, headers=hdr, params={"message": str(other.answer_id)}).status_code == 404
    assert api.get(url, headers=hdr, params={"message": blank.json()["answer"]["id"]}).status_code == 404
    assert api.get(url, headers=hdr, params={"message": mine.json()["question"]["id"]}).status_code == 404
    assert (
        api.get(
            f"/assistant/court-orders/{scene['o_h']}", headers=hdr, params={"message": mine_id}
        ).status_code
        == 404
    )  # H's order is not cited
    assert api.get(f"{url}/file", headers=hdr, params={"message": str(other.answer_id)}).status_code == 404
    assert api.get(url, headers=hdr, params={"message": mine_id}).status_code == 200


def test_case_scope_needs_case_sight(world, scene, api):
    with pytest.raises(svc.NotVisibleCase):
        sup.ask(world, "health_off", "quokka", "case", case=scene["a"])
    r = api.post(
        "/assistant/ask",
        headers=ds.login(api, "health_off"),
        json={"question": "quokka", "scope": "case", "case": str(scene["a"])},
    )
    assert r.status_code == 404
    with world.Session() as s:
        rec_case = make_case(s, case_no="WP(C)/303/2026")
        h.recommend(s, world, rec_case, "HEALTH")
        sup.order(s, scene["store"], rec_case, ["a numbat direction"], order_no="1")
        s.commit()
        rec_id = rec_case.id
    r = sup.ask(world, "health_admin", "numbat", "case", case=rec_id)
    assert r.outcome == "answered"
    with world.Session() as s:
        assert (
            s.scalar(
                sa.select(sa.func.count())
                .select_from(AssistantConversation)
                .where(AssistantConversation.case_id == scene["a"])
            )
            == 0
        )  # nothing stored for the refused question


def test_my_cases_scope_covers_allotted_file_and_claimed(world, scene):
    with world.Session() as s:
        f = w.claimed_case(s, world, officer="edu_off2", case_no="WP(C)/404/2026")
        w.send(s, world, "edu_off2", f, "edu_off1")
        other = w.claimed_case(s, world, officer="edu_off2", case_no="WP(C)/505/2026")
        sup.order(s, scene["store"], f, ["the bilby direction on file"], order_no="1")
        sup.order(s, scene["store"], other, ["the bilby direction elsewhere"], order_no="1")
        s.commit()
        f_id, other_id = f.id, other.id
    with world.Session() as s:
        ids, truncated = src.focus_cases(s, world.user(s, "edu_off1"), "my_cases", None)
        assert set(ids) == {scene["a"], f_id} and truncated is False
        ids, _ = src.focus_cases(s, world.user(s, "edu_admin"), "my_cases", None)
        assert {scene["a"], f_id, other_id} <= set(ids)  # claimed by the admin
        ids, truncated = src.focus_cases(s, world.user(s, "edu_admin"), "my_cases", None, limit=1)
        assert len(ids) == 1 and truncated is True
    r = sup.ask(world, "edu_off1", "bilby", "my_cases")
    msg = sup.answer(world, r)
    assert len(msg.citations) == 1 and msg.citations[0]["case_id"] == str(f_id)
    with world.Session() as s:
        q = s.get(AssistantMessage, r.question_id)
    assert q.scope_info["kind"] == "my_cases" and q.scope_info["focus_cases"] == 2


# ------------------------------------------------------------------------------------------------ audit, privacy


def test_question_and_answer_audited_without_text(world, scene):
    question = "affidavit quokka scheme"
    r = sup.ask(world, "edu_off1", question, "case", case=scene["a"])
    with world.Session() as s:
        asked = ds.audit_rows(s, "assistant.asked")
        answered = ds.audit_rows(s, "assistant.answered")
        assert len(asked) == 1 and len(answered) == 1
        a, b = asked[0], answered[0]
        assert (
            a.entity_type == "assistant_message" and a.entity_id == r.question_id and a.case_id == scene["a"]
        )
        assert a.after["question"]["length"] == len(question) and len(a.after["question"]["sha256"]) == 64
        assert (
            a.after["scope"] == "case"
            and a.after["mode"] == "preview"
            and a.after["new_conversation"] is True
        )
        assert a.after["conversation_id"] == str(r.conversation_id)
        assert b.entity_id == r.answer_id and b.after["question_id"] == str(r.question_id)
        assert b.after["outcome"] == "answered" and b.after["connector"] == "preview"
        assert {c["document_id"] for c in b.after["citations"]} >= {str(scene["d_a"])}
        assert a.actor_name and b.actor_user_id == world.users["edu_off1"].id
        leaked = s.scalar(
            sa.select(sa.func.count())
            .select_from(AuditLog)
            .where(
                sa.or_(
                    sa.cast(AuditLog.after, sa.Text).contains(question),
                    sa.cast(AuditLog.after, sa.Text).contains("[["),
                )
            )
        )
        assert leaked == 0


def test_conversation_private_to_its_user(world, scene, api):
    r = sup.ask(world, "edu_off1", "quokka", "case", case=scene["a"])
    url = f"/assistant/conversations/{r.conversation_id}"
    assert api.get(url, headers=ds.login(api, "edu_off1")).status_code == 200
    for key in ("edu_admin", "root"):
        hdr = ds.login(api, key)
        assert api.get(url, headers=hdr).status_code == 404, key
        assert api.get("/assistant/conversations", headers=hdr).json()["total"] == 0, key
        assert (
            api.post(
                "/assistant/ask",
                headers=hdr,
                json={
                    "question": "quokka again",
                    "scope": "case",
                    "case": str(scene["a"]),
                    "conversation_id": str(r.conversation_id),
                },
            ).status_code
            == 404
        ), key
    assert api.get(url, headers=ds.login(api, "edu_auditor")).status_code == 403


def test_messages_append_only(world, scene, engine):
    r = sup.ask(world, "edu_off1", "quokka", "case", case=scene["a"])
    with engine.connect() as conn:
        for sql in (
            "UPDATE assistant_messages SET content = 'x' WHERE id = :id",
            "DELETE FROM assistant_messages WHERE id = :id",
        ):
            with pytest.raises(sa.exc.DBAPIError):
                with conn.begin():
                    conn.execute(sa.text(sql), {"id": r.answer_id})
        with pytest.raises(sa.exc.ProgrammingError) as exc:
            with conn.begin():
                conn.execute(sa.text("SET LOCAL ROLE aslms_app"))
                conn.execute(
                    sa.text("DELETE FROM assistant_conversations WHERE id = :id"), {"id": r.conversation_id}
                )
        assert isinstance(exc.value.orig, pg_errors.InsufficientPrivilege)
        with pytest.raises(sa.exc.ProgrammingError):
            with conn.begin():
                conn.execute(sa.text("SET LOCAL ROLE aslms_app"))
                conn.execute(
                    sa.text("UPDATE assistant_messages SET content = 'x' WHERE id = :id"), {"id": r.answer_id}
                )


# ------------------------------------------------------------------------------------------------ limits


def test_rate_limit_429_with_retry_after(world, scene, api):
    api.app.state.assistant_config = svc.AssistantConfig(questions_per_hour=1, retry_delay=0.01)
    hdr = ds.login(api, "edu_off1")
    assert (
        api.post("/assistant/ask", headers=hdr, json={"question": "quokka", "scope": "research"}).status_code
        == 200
    )
    r = api.post("/assistant/ask", headers=hdr, json={"question": "quokka two", "scope": "research"})
    assert r.status_code == 429
    body = r.json()["detail"]
    assert body["code"] == "assistant_limit" and 3500 < body["retry_after"] <= 3600
    assert r.headers["retry-after"] == str(body["retry_after"])
    st = api.get("/assistant/status", headers=hdr).json()
    assert st["limits"]["used_last_hour"] == 1


def _user_questions(world, key) -> int:
    with world.Session() as s:
        return s.scalar(
            sa.select(sa.func.count())
            .select_from(AssistantMessage)
            .join(AssistantConversation, AssistantConversation.id == AssistantMessage.conversation_id)
            .where(
                AssistantConversation.user_id == world.users[key].id,
                AssistantMessage.role == MessageRole.USER,
            )
        )


def test_question_in_flight_409_across_conversations(world, scene, api):
    r = sup.ask(world, "edu_off1", "quokka", "research")
    with world.Session() as s:
        s.add(
            AssistantMessage(
                conversation_id=r.conversation_id, role=MessageRole.USER, content="unanswered one"
            )
        )
        s.commit()
    before = _user_questions(world, "edu_off1")
    with pytest.raises(svc.QuestionInFlight):
        sup.ask(world, "edu_off1", "quokka again", "research", conversation_id=r.conversation_id)
    # one unanswered question per user: a new conversation, in any scope, is refused too (review finding 3)
    with pytest.raises(svc.QuestionInFlight):
        sup.ask(world, "edu_off1", "quokka", "research")
    with pytest.raises(svc.QuestionInFlight):
        sup.ask(world, "edu_off1", "quokka", "case", case=scene["a"])
    resp = api.post(
        "/assistant/ask",
        headers=ds.login(api, "edu_off1"),
        json={"question": "quokka", "scope": "my_cases"},
    )
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "question_in_flight"
    assert _user_questions(world, "edu_off1") == before  # nothing stored
    assert (
        sup.ask(world, "edu_off2", "quokka", "research").outcome == "answered"
    )  # another user is not blocked


def test_unanswered_question_shows_no_answer_and_window_expires(world, scene):
    r = sup.ask(world, "edu_off1", "quokka", "research")
    with world.Session() as s:
        s.execute(
            sa.insert(AssistantMessage).values(
                conversation_id=r.conversation_id,
                role=MessageRole.USER,
                content="an old unanswered question",
                created_at=sa.func.now() - timedelta(minutes=5),
            )
        )
        s.commit()
    r2 = sup.ask(world, "edu_off1", "quokka again", "research", conversation_id=r.conversation_id)
    assert r2.outcome == "answered"
    with world.Session() as s:
        thread = svc.conversation(s, world.user(s, "edu_off1"), r.conversation_id)
    unanswered = [m for m in thread["messages"] if m["content"] == "an old unanswered question"]
    assert unanswered and not any(m["reply_to_id"] == unanswered[0]["id"] for m in thread["messages"])


def test_conversation_full_409(world, scene):
    cfg = svc.AssistantConfig(messages_per_conversation=4, retry_delay=0.01)
    r = sup.ask(world, "edu_off1", "quokka", "research", config=cfg)
    sup.ask(world, "edu_off1", "quokka two", "research", config=cfg, conversation_id=r.conversation_id)
    with pytest.raises(svc.ConversationFull):
        sup.ask(world, "edu_off1", "quokka three", "research", config=cfg, conversation_id=r.conversation_id)


def test_bad_question_length_422(world, scene, api):
    hdr = ds.login(api, "edu_off1")
    for q in ("hi", "  a ", "x" * 2001):
        r = api.post("/assistant/ask", headers=hdr, json={"question": q, "scope": "research"})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_question", q
    r = api.post("/assistant/ask", headers=hdr, json={"question": "quokka", "scope": "case"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_question"
    r = api.post(
        "/assistant/ask",
        headers=hdr,
        json={"question": "quokka", "scope": "research", "case": str(scene["a"])},
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "scope_mismatch"
    first = sup.ask(world, "edu_off1", "quokka", "research")
    r = api.post(
        "/assistant/ask",
        headers=hdr,
        json={
            "question": "quokka",
            "scope": "case",
            "case": str(scene["a"]),
            "conversation_id": str(first.conversation_id),
        },
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "scope_mismatch"


def test_case_outside_case_scope_refused_before_any_lookup(world, scene, api, monkeypatch):
    from aslms.api.routers import assistant as router

    def no_lookup(*_a, **_k):
        raise AssertionError("the case was looked up")

    monkeypatch.setattr(router, "resolve_case_ref", no_lookup)
    hdr = ds.login(api, "health_off")
    for ref in (str(scene["a"]), str(uuid.uuid4()), "NOPE", scene["a_cnr"]):
        for scope in ("research", "my_cases"):
            r = api.post(
                "/assistant/ask", headers=hdr, json={"question": "quokka", "scope": scope, "case": ref}
            )
            assert r.status_code == 422 and r.json()["detail"]["code"] == "scope_mismatch", (ref, scope)
    with pytest.raises(svc.ScopeMismatch):
        sup.ask(world, "health_off", "quokka", "research", case=uuid.uuid4())


def test_unknown_and_invisible_case_answer_alike(world, scene, api):
    hdr = ds.login(api, "health_off")
    bodies = set()
    for ref in (str(scene["a"]), scene["a_cnr"], str(uuid.uuid4()), "ASHC019999992026"):
        for question in ("quokka", "hi", "quo\u0000kka"):  # a bad question cannot tell them apart either
            r = api.post(
                "/assistant/ask", headers=hdr, json={"question": question, "scope": "case", "case": ref}
            )
            assert r.status_code == 404, (ref, question, r.text)
            bodies.add(json.dumps(r.json(), sort_keys=True))
    assert bodies == {
        json.dumps({"detail": {"code": "not_found", "message": "no such case"}}, sort_keys=True)
    }
    for case in (scene["a"], uuid.uuid4()):
        for question in ("quokka", "hi"):
            with pytest.raises(svc.NotVisibleCase, match="no such case"):
                sup.ask(world, "health_off", question, "case", case=case)


def test_question_with_control_characters_422(world, scene, api):
    hdr = ds.login(api, "edu_off1")
    for q in (
        "quo\u0000kka",
        "quokka \u0007 bell",
        "\u001b[31mquokka",
        "quokka\u007f",
        "quokka\u0085",
        "\u0000\u0000\u0000",
    ):
        r = api.post("/assistant/ask", headers=hdr, json={"question": q, "scope": "research"})
        assert r.status_code == 422, repr(q)
        assert r.json()["detail"] == {
            "code": "bad_question",
            "message": "a question may not contain control characters",
            "reason": "control_characters",
        }, repr(q)
    assert _user_questions(world, "edu_off1") == 0
    r = api.post(
        "/assistant/ask", headers=hdr, json={"question": "quokka\n\tscheme\r\n", "scope": "research"}
    )
    assert r.status_code == 200, r.text  # tab, line feed and carriage return are allowed


def test_off_mode_refuses_before_storing(world, scene, tmp_path):
    off = ds.make_api(world, tmp_path / "off")
    try:
        r = off.post(
            "/assistant/ask",
            headers=ds.login(off, "edu_off1"),
            json={"question": "quokka", "scope": "research"},
        )
        assert r.status_code == 503 and r.json()["detail"]["code"] == "assistant_off"
    finally:
        off.__exit__(None, None, None)
    with pytest.raises(svc.AssistantOff):
        asyncio.run(
            svc.ask(
                world.Session,
                None,
                world.users["edu_off1"],
                question="quokka",
                scope="research",
                connector=None,
                config=sup.CONFIG,
            )
        )
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(AssistantMessage)) == 0
        assert s.scalar(sa.select(sa.func.count()).select_from(AssistantConversation)) == 0
        assert ds.audit_rows(s, "assistant.asked") == []


# ------------------------------------------------------------------------------------------------ reading again


def test_reread_hides_answer_when_filing_no_longer_visible(world, scene):
    narrowed = _filing(world, scene, "a", ["wallaby petition one"])
    archived = _filing(world, scene, "a", ["wallaby petition two"])
    with world.Session() as s:
        sup.order(
            s, scene["store"], s.get(Case, scene["a"]), ["wallaby direction of the court"], order_no="8"
        )
        s.commit()
    r = sup.ask(world, "edu_off1", "wallaby", "case", case=scene["a"], include_related=False)
    assert {str(narrowed), str(archived)} <= sup.cited_docs(world, r)
    assert sup.read(world, "edu_off1", r)["content"] is not None
    with world.Session() as s:
        d = s.get(Document, narrowed)
        d.visibility = Visibility.PRIVATE_TO_OFFICE
        d.sourcetrace_status = SourcetraceStatus.NOT_APPLICABLE
        d.office_id = world.office(s, "EDU-DHE").id
        s.commit()
    out = sup.read(world, "edu_off1", r)
    assert out["content"] is None and out["hidden_reason"] == svc.HIDDEN_REASON
    gone = [c for c in out["citations"] if not c["available"]]
    assert gone == [GONE_FILING]  # nothing that names the filing (review finding 2)
    assert narrowed not in {c["document_id"] for c in out["citations"]}
    orders = [c for c in out["citations"] if c["source_kind"] == "court_order"]
    assert orders and all(c["available"] and c["passage"] for c in orders)
    r2 = sup.ask(world, "edu_off1", "wallaby two", "case", case=scene["a"], include_related=False)
    assert str(archived) in sup.cited_docs(world, r2)
    with world.Session() as s:
        d = s.get(Document, archived)
        d.archived_at = sa.func.now()
        d.archive_reason = "superseded"
        s.commit()
    assert sup.read(world, "edu_off1", r2)["content"] is None


GONE_FILING = {
    "document_id": None,
    "order_id": None,
    "case": {"id": None, "case_no_text": None, "cnr": None, "visible": False},
    "source_kind": "court_filing",
    "doc_type_label": None,
    "doc_date": None,
    "order_no": None,
    "page": None,
    "passage": None,
    "related": False,
    "available": False,
    "unavailable_reason": svc.UNAVAILABLE,
    "open": None,
    # design assistant-ollama: the extended citation shape, naming nothing either
    "label": None,
    "cited": True,
    "context": None,
    "note": None,
    "internal": False,
    "what": None,
    "visibility": None,
}


def test_reread_gone_filing_names_nothing_through_the_api(world, scene, api):
    filing_id = _filing(world, scene, "a", ["bandicoot petition as filed"])
    hdr = ds.login(api, "edu_off1")
    r = api.post(
        "/assistant/ask",
        headers=hdr,
        json={"question": "bandicoot", "scope": "case", "case": str(scene["a"]), "include_related": False},
    )
    assert r.status_code == 200, r.text
    conv_id = r.json()["conversation"]["id"]
    assert {c["document_id"] for c in r.json()["answer"]["citations"]} == {str(filing_id)}
    with world.Session() as s:
        d = s.get(Document, filing_id)
        d.visibility = Visibility.PRIVATE_TO_OFFICE
        d.sourcetrace_status = SourcetraceStatus.NOT_APPLICABLE
        d.office_id = world.office(s, "EDU-DHE").id
        s.commit()
        case = s.get(Case, scene["a"])
        cnr, case_no = case.cnr, case.case_no_text
    thread = api.get(f"/assistant/conversations/{conv_id}", headers=hdr)
    assert thread.status_code == 200
    answer = thread.json()["messages"][1]
    assert answer["content"] is None and answer["citations"] == [
        {**GONE_FILING, "unavailable_reason": svc.UNAVAILABLE}
    ]
    flat = json.dumps(answer)
    for leak in (str(filing_id), cnr, case_no, "Petition", "2026-02-01"):
        assert leak not in flat, leak


def test_reread_court_order_unavailable_once_out_of_corpus(world, scene):
    r = sup.ask(world, "health_off", "quokka", "research")
    cited = {c["document_id"]: c for c in sup.read(world, "health_off", r)["citations"]}
    assert cited[scene["d_a"]]["available"] and cited[scene["d_h"]]["available"]
    with world.Session() as s:
        d = s.get(Document, scene["d_a"])
        d.archived_at = sa.func.now()
        d.archive_reason = "test"
        s.commit()
    out = sup.read(world, "health_off", r)
    gone = [c for c in out["citations"] if not c["available"]]
    assert gone == [{**GONE_FILING, "source_kind": "court_order"}]
    assert out["content"] is not None  # an order out of the corpus does not hide the answer
    assert [c["document_id"] for c in out["citations"] if c["available"]] == [scene["d_h"]]
    with world.Session() as s:
        s.get(Case, scene["h"]).merged_into_case_id = scene["a"]
        s.commit()
    out = sup.read(world, "health_off", r)
    assert all(c == {**GONE_FILING, "source_kind": "court_order"} for c in out["citations"])
    assert len(out["citations"]) == 2


def test_order_link_follows_the_membership_that_sees_the_case(world, scene):
    from aslms.domain.org import PermissionEffect
    from aslms.domain.reference import Permission, Role
    from aslms.services import access
    from tests.db.world import add_membership

    r = sup.ask(world, "edu_off1", "affidavit quokka", "case", case=scene["a"], include_related=False)
    assert sup.read(world, "edu_off1", r)["citations"][0]["open"]["kind"] == "document"
    with world.Session() as s:
        add_membership(s, world.user(s, "edu_off1"), world.office(s, "HEALTH"), Role.DEPT_OFFICER)
        actor, root = world.actor(s, "root")
        access.set_override(
            s,
            actor,
            root,
            world.membership(s, "edu_off1", "EDU"),
            Permission.DOCUMENTS_VIEW,
            PermissionEffect.DENY,
        )
        s.commit()
        user = world.user(s, "edu_off1")
        assert access.has(s, user, Permission.DOCUMENTS_VIEW)  # the HEALTH membership holds it
    out = sup.read(world, "edu_off1", r)["citations"][0]
    assert out["available"] and out["case"]["visible"] is True
    assert out["open"] == {
        "kind": "court_order",
        "href": f"/assistant/court-orders/{scene['o_a']}?message={r.answer_id}",
    }


def test_case_conversation_unreadable_after_losing_case_sight(world, scene):
    r = sup.ask(world, "edu_off1", "quokka", "case", case=scene["a"])
    with world.Session() as s:
        other = world.user(s, "edu_off2")
        s.execute(
            sa.update(CaseOwnership)
            .where(CaseOwnership.case_id == scene["a"])
            .values(officer_user_id=other.id)
        )
        s.execute(
            sa.update(Custody)
            .where(Custody.case_id == scene["a"])
            .values(holder_user_id=other.id, holder_membership_id=world.membership(s, "edu_off2").id)
        )
        s.commit()
    with world.Session() as s:
        user = world.user(s, "edu_off1")
        assert not svc.visibility.can_view_case(s, user, scene["a"])
        with pytest.raises(svc.ConversationNotFound):
            svc.conversation(s, user, r.conversation_id)
        assert svc.conversations(s, user).total == 0
        with pytest.raises(svc.ConversationNotFound):
            svc.message(s, user, r.answer_id)


# ------------------------------------------------------------------------------------------------ the SourceTrace path


def _ingested_scene(world, scene):
    with world.Session() as s:
        sup.ingest(s, s.get(Document, scene["d_a"]), "st-order-a")
        sup.ingest(s, s.get(Document, scene["d_h"]), "st-order-h")
        s.commit()
    visible = _filing(world, scene, "a", ["the koala petition"], ingested_ref="st-filing-a")
    private = _filing(world, scene, "a", ["koala private"], visibility=Visibility.PRIVATE_TO_OFFICE)
    other = _filing(world, scene, "h", ["koala health filing"], office="HEALTH", ingested_ref="st-filing-h")
    not_ingested = _filing(world, scene, "a", ["koala not yet sent"])
    return visible, private, other, not_ingested


def test_sourcetrace_path_with_fake(world, scene):
    visible, _private, _other, _not_ingested = _ingested_scene(world, scene)
    with world.Session() as s:
        w.note(s, world, "edu_off1", s.get(Case, scene["a"]), body="secret note text never sent")
        s.commit()
    fake = FakeSourceTrace()
    fake.script_ask(
        Answer(
            text="The court directed an affidavit.",
            citations=(
                Citation(reference="st-filing-a", page=1, passage="koala"),
                Citation(reference="st-order-a", page=2, passage="affidavit", locator={"para": 3}),
                Citation(reference="st-order-h", page=1, passage="quokka"),
            ),
            info={"model": "sourcetrace-test"},
            raw={"id": "st-answer-1"},
        )
    )
    r = sup.ask(world, "edu_off1", "what did the court direct", "case", case=scene["a"], connector=fake)
    msg = sup.answer(world, r)
    assert r.outcome == "answered" and msg.mode == "sourcetrace" and msg.connector == "fake"
    assert msg.response == {"id": "st-answer-1"} and msg.model_info == {"model": "sourcetrace-test"}
    kinds = {c["document_id"]: (c["source_kind"], c["related"]) for c in msg.citations}
    assert kinds == {
        str(visible): ("court_filing", False),
        str(scene["d_a"]): ("court_order", False),
        str(scene["d_h"]): ("court_order", True),
    }
    assert next(c for c in msg.citations if c["document_id"] == str(scene["d_a"]))["locator"] == {"para": 3}
    sent = fake.asked[0]
    assert sent.request_id == r.question_id and sent.scope.kind == "case"
    assert sent.scope.orders == "focus_and_related"
    assert [f.reference for f in sent.scope.filings] == ["st-filing-a"]  # ingested, visible, of the case only
    assert [c.case_id for c in sent.scope.focus] == [scene["a"]] and sent.history == ()
    for _ in range(7):
        sup.ask(
            world,
            "edu_off1",
            "and then what happened",
            "case",
            case=scene["a"],
            connector=fake,
            conversation_id=r.conversation_id,
        )
    assert len(fake.asked[-1].history) == 6
    flat = repr(fake.asked)
    assert "secret note text" not in flat and "please act" not in flat


def test_sourcetrace_out_of_scope_citation_withholds_answer(world, scene):
    _visible, _private, _other, _not_ingested = _ingested_scene(world, scene)
    fake = FakeSourceTrace().script_ask(
        "out_of_scope",
        Answer(
            text="quoting the health filing", citations=(Citation(reference="st-filing-h"),), raw={"x": 1}
        ),
        Answer(text="quoting a related order", citations=(Citation(reference="st-order-h"),)),
    )
    r = sup.ask(world, "edu_off1", "what was filed", "case", case=scene["a"], connector=fake)
    msg = sup.answer(world, r)
    assert r.outcome == "failed" and msg.error_family == "scope" and msg.content == svc.WITHHELD
    assert msg.citations is None
    r = sup.ask(world, "edu_off1", "what was filed", "case", case=scene["a"], connector=fake)
    msg = sup.answer(world, r)
    assert msg.error_family == "scope" and msg.response == {"x": 1}
    # without related orders, another case's order is outside the scope too
    r = sup.ask(
        world, "edu_off1", "what was filed", "case", case=scene["a"], connector=fake, include_related=False
    )
    assert sup.answer(world, r).error_family == "scope"
    out = sup.read(world, "edu_off1", r)
    assert out["outcome"] == "failed" and out["error"] == {"family": "scope", "message": svc.WITHHELD}


def test_sourcetrace_unavailable_retried_once_timeout_not(world, scene):
    fake = FakeSourceTrace(timeout_sleep=2.0, cite="st-order-a").script_ask("unavailable")
    _ingested_scene(world, scene)
    r = sup.ask(world, "edu_off1", "quokka", "research", connector=fake)
    assert r.outcome == "answered" and len(fake.asked) == 2
    fake.script_ask("unavailable", "unavailable")
    r = sup.ask(world, "edu_off1", "quokka", "research", connector=fake)
    assert sup.answer(world, r).error_family == "unavailable" and len(fake.asked) == 4
    fake.script_ask("timeout")
    cfg = svc.AssistantConfig(timeout_seconds=0.3, retry_delay=0.01)
    r = sup.ask(world, "edu_off1", "quokka", "research", connector=fake, config=cfg)
    msg = sup.answer(world, r)
    assert msg.error_family == "timeout" and len(fake.asked) == 5 and msg.outcome == "failed"
    with world.Session() as s:
        row = ds.audit_rows(s, "assistant.answered")[-1]
    assert row.after["error_family"] == "timeout" and row.after["attempts"] == 1


def test_rejected_and_bad_answer_stored_as_failed(world, scene):
    fake = FakeSourceTrace().script_ask("rejected", "bad_answer", "error")
    families = []
    for _ in range(3):
        r = sup.ask(world, "edu_off1", "quokka", "research", connector=fake)
        msg = sup.answer(world, r)
        assert msg.outcome == "failed" and msg.content == svc.FAILURE_MESSAGES[msg.error_family]
        families.append(msg.error_family)
    assert families == ["rejected", "protocol", "error"] and len(fake.asked) == 3


def test_unexpected_connector_failure_logs_no_text(world, scene, caplog, monkeypatch):
    question = "what did the court say about the secret wombat"
    monkeypatch.setattr(svc.log, "disabled", False)  # alembic's fileConfig disables existing loggers

    class Leaky:
        name = "leaky"

        async def ask(self, request):
            raise RuntimeError(f"failed on {request.question!r} [parameters: {{'q': {request.question!r}}}]")

    with caplog.at_level("DEBUG", logger="aslms.services.assistant"):
        r = sup.ask(world, "edu_off1", question, "research", connector=Leaky())
    assert r.outcome == "failed" and sup.answer(world, r).error_family == "error"
    records = [x for x in caplog.records if x.name == "aslms.services.assistant"]
    assert len(records) == 1
    rec = records[0]
    assert rec.exc_info is None and rec.exc_text is None  # no traceback, which would carry the message
    line = rec.getMessage()
    assert "RuntimeError" in line and str(r.conversation_id) in line
    assert svc.digest(question)["sha256"] in line
    assert "wombat" not in caplog.text and "parameters" not in caplog.text


# ------------------------------------------------------------------------------------------------ CLI, check, merge


def test_cli_ask_refused_in_prod_and_prints_citations(world, scene, monkeypatch):
    import typer

    from aslms.cli import assistant as cli

    app = typer.Typer()
    app.add_typer(cli.assistant_app, name="assistant")
    runner = CliRunner()
    monkeypatch.setattr(
        cli, "get_settings", lambda: Settings(_env_file=None, app_env="prod", assistant_mode="preview")
    )
    r = runner.invoke(app, ["assistant", "ask", "--user", "off1.edu@example.org", "--research", "quokka"])
    assert r.exit_code == 2
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None, assistant_mode="preview"))
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: world.Session)
    r = runner.invoke(
        app,
        [
            "assistant",
            "ask",
            "--user",
            "off1.edu@example.org",
            "--case",
            scene["a_cnr"],
            "--no-related",
            "affidavit quokka",
        ],
    )
    assert r.exit_code == 0, r.output
    assert PREVIEW_LINE in r.output and "page 2" in r.output and "[[" in r.output
    r = runner.invoke(
        app, ["assistant", "ask", "--user", "off1.edu@example.org", "--research", "--json", "quokka"]
    )
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert out["answer"]["outcome"] == "answered"
    with world.Session() as s:
        rows = ds.audit_rows(s, "assistant.asked")
        assert rows and all(x.actor_name == "cli" and x.actor_user_id is None for x in rows)
        assert rows[0].after["as_user_id"] == str(world.users["edu_off1"].id)
        q = s.get(AssistantMessage, uuid.UUID(out["question"]["id"]))
        assert q.model_info == {"via": "cli"}
        conv = s.get(AssistantConversation, q.conversation_id)
        assert conv.user_id == world.users["edu_off1"].id
    r = runner.invoke(app, ["assistant", "ask", "--user", "off1.edu@example.org", "quokka"])
    assert r.exit_code != 0  # a scope is required


def test_check_counts_zero(world, scene, monkeypatch):
    sup.ask(world, "edu_off1", "quokka", "case", case=scene["a"])
    with world.Session() as s:
        assert svc.check(s) == {
            "citations_out_of_rule": 0,
            "case_conversations_without_case": 0,
            # design assistant-ollama, "Data": three more counts
            "internal_citations_out_of_reach": 0,
            "internal_citations_of_another_case": 0,
            "citations_of_unknown_kind": 0,
        }
    attachment = _filing(
        world,
        scene,
        "a",
        ["an attachment"],
        kind=DocKind.ATTACHMENT,
        group=DocGroup.INTERNAL,
        doc_type=DocType.LEGAL_OPINION,
    )
    r = sup.ask(world, "edu_off1", "quokka", "research")
    with world.Session() as s:
        forged_q = AssistantMessage(
            conversation_id=r.conversation_id, role=MessageRole.USER, content="forged q"
        )
        s.add(forged_q)
        s.flush()
        s.add(
            AssistantMessage(
                conversation_id=r.conversation_id,
                role=MessageRole.ASSISTANT,
                content="forged",
                reply_to_id=forged_q.id,
                mode="preview",
                outcome="answered",
                citations=[{"document_id": str(attachment), "source_kind": "court_filing"}],
            )
        )
        s.commit()
        assert svc.check(s)["citations_out_of_rule"] == 1
    import typer

    from aslms.cli import assistant as cli

    app = typer.Typer()
    app.add_typer(cli.assistant_app, name="assistant")

    def scope():
        from contextlib import contextmanager

        @contextmanager
        def _s():
            with world.Session() as s:
                yield s

        return _s()

    monkeypatch.setattr(cli, "session_scope", scope)
    assert CliRunner().invoke(app, ["assistant", "check"]).exit_code == 1


def test_merge_holds_back_a_provisional_case_with_conversations(world, scene):
    with world.Session() as s:
        holder = s.get(Case, scene["a"])
        p = make_case(s, cnr="", case_no="WP(C)/101/2026")
        p.cnr = None
        p.is_provisional = True
        s.flush()
        conv = AssistantConversation(
            user_id=world.users["edu_off1"].id,
            case_id=p.id,
            scope=AssistantScope.CASE,
            title="on the provisional row",
        )
        s.add(conv)
        s.flush()
        s.add(AssistantMessage(conversation_id=conv.id, role=MessageRole.USER, content="a question"))
        s.flush()
        assert "assistant_conversations" in case_dedupe.portal_records(s, p)
        result = case_dedupe.merge_provisional(s, p, holder)
        assert isinstance(result, case_dedupe.NeedsReview)
        s.commit()
        assert s.get(Case, p.id).merged_into_case_id is None
        assert s.get(AssistantConversation, conv.id).case_id == p.id


# ------------------------------------------------------------------------------------------------ migration 0024


@pytest.mark.migration_cycle
def test_migration_0024_guard_up_down(db_url, engine, world):
    cfg = alembic_config(db_url)
    with world.Session() as s:
        conv = AssistantConversation(user_id=world.users["edu_off1"].id, scope=AssistantScope.MY_CASES)
        s.add(conv)
        s.commit()
        conv_id = conv.id
    try:
        with pytest.raises(RuntimeError, match="my_cases"):
            command.downgrade(cfg, "0023")
        with engine.begin() as conn:
            conn.execute(
                sa.text("UPDATE assistant_conversations SET scope = 'research' WHERE id = :i"), {"i": conv_id}
            )
            conn.execute(
                sa.text(
                    "INSERT INTO assistant_messages (conversation_id, role, content) "
                    "VALUES (:c, 'user', 'a question')"
                ),
                {"c": conv_id},
            )
        with pytest.raises(RuntimeError, match="assistant_messages"):
            command.downgrade(cfg, "0023")
        wipe_if_migrated(db_url)
        command.downgrade(cfg, "0023")
        with engine.begin() as conn:
            assert (
                conn.execute(
                    sa.text("select count(*) from pg_trigger where tgname = 'assistant_messages_append_only'")
                ).scalar()
                == 0
            )
            assert (
                conn.execute(
                    sa.text("select has_table_privilege('aslms_app', 'assistant_messages', 'DELETE')")
                ).scalar()
                is True
            )
            assert (
                conn.execute(
                    sa.text(
                        "select count(*) from pg_enum e join pg_type t on t.oid = e.enumtypid "
                        "where t.typname = 'assistant_scope' and e.enumlabel = 'my_cases'"
                    )
                ).scalar()
                == 1
            )  # stays
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            assert (
                conn.execute(
                    sa.text("select has_table_privilege('aslms_app', 'assistant_messages', 'DELETE')")
                ).scalar()
                is False
            )
            assert (
                conn.execute(
                    sa.text("select count(*) from pg_trigger where tgname = 'assistant_messages_append_only'")
                ).scalar()
                == 1
            )
    finally:
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            wipe(conn)


@pytest.mark.migration_cycle
def test_migration_0024_upgrade_guard(db_url, engine):
    cfg = alembic_config(db_url)
    wipe_if_migrated(db_url)
    try:
        command.downgrade(cfg, "0023")
        with engine.begin() as conn:
            conn.execute(
                sa.text("SET session_replication_role = replica")
            )  # no user or conversation row needed
            conv = uuid.uuid4()
            conn.execute(
                sa.text(
                    "INSERT INTO assistant_conversations (id, user_id, scope) VALUES (:c, :u, 'research')"
                ),
                {"c": conv, "u": uuid.uuid4()},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO assistant_messages (conversation_id, role, content) "
                    "VALUES (:c, 'user', 'a question')"
                ),
                {"c": conv},
            )
            conn.execute(sa.text("SET session_replication_role = DEFAULT"))
        with pytest.raises(RuntimeError, match="0024"):
            command.upgrade(cfg, "head")
        wipe_if_migrated(db_url)
    finally:
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            wipe(conn)
