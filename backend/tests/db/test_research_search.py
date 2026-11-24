"""Hybrid retrieval and the answer checks against the database (design `research-index`, "Tests", database; decisions
13, 15 to 21, 23 to 29 and 32). The chat and embedding models are `FakeOllama` (a bag of words hashed into 768 buckets
with synonyms; never a real model): the meaning list finds a reworded passage, the words list finds a case number, the
filters, unindexed orders, stale texts never cited, words only when the question cannot be embedded, citation fields
and `text_changed`, the passage endpoint, the checks in every scope (and not on My Work or quick facts), audit counts
without text, the status blocks, the preview unchanged and a model change."""

from __future__ import annotations

import json
from datetime import date

import pytest
import sqlalchemy as sa

from aslms.domain.cases import CaseParty, PartyRole
from aslms.domain.documents import DocumentText, OrderKind
from aslms.domain.events import AuditLog
from aslms.services import assistant as svc
from aslms.services import data_health, service_checks
from aslms.services import research_embed as remb
from aslms.services import research_search as rsearch
from aslms.services.assistant_ollama import NO_ANSWER_TEXT, OllamaConnector
from tests.db import assistant_support as sup
from tests.db import docs_support as ds
from tests.db import ollama_support as ol
from tests.db import research_support as rs
from tests.db import workflow_support as w
from tests.db.world import make_case
from tests.fakes.ollama import bag_vector, chat_reply

NUMBER_BODY = (
    "1.      Heard learned counsel for the parties.\n"
    "2.      The issue is squarely covered by the judgment in WP(C) 7013/2024 decided by this Court earlier, and the\n"
    "transfer order impugned is set aside.\n"
)


def _connector(world, fake, **over) -> OllamaConnector:
    conn = OllamaConnector(world.Session, rs.settings(**over), client=fake.client())
    conn.fake = fake  # type: ignore[attr-defined]
    return conn


@pytest.fixture()
def scene(world):
    """Case A (EDU, edu_off1's own) with a judgment on retiral benefits; case B (another department's) with a final
    order citing WP(C) 7013/2024; every reading cut and embedded."""
    fake = rs.fake()
    with world.Session() as s:
        a = w.claimed_case(s, world, officer="edu_off1", case_no="WP(C)/501/2025")
        b = make_case(s, case_no="WP(C)/777/2025")
        s.add(CaseParty(case_id=b.id, role=PartyRole.RESPONDENT, party_no=1, name="THE STATE OF ASSAM",
                        name_normalised="the state of assam"))  # fmt: skip
        oa = rs.court_order(s, a, body=rs.PENSION_BODY, heading="JUDGMENT", kind=OrderKind.JUDGMENT,
                            day=date(2025, 3, 12))  # fmt: skip
        ob = rs.court_order(
            s, b, body=NUMBER_BODY, heading="ORDER", kind=OrderKind.FINAL, day=date(2025, 4, 2)
        )
        rs.read_orders(s)
        s.execute(
            sa.update(DocumentText).values(
                search_vector=sa.func.to_tsvector("english", DocumentText.full_text)
            )
        )
        s.commit()
        ids = (a.id, b.id, oa.id, ob.id, oa.document_id, ob.document_id)
    remb.backfill(world.Session, fake.client(), rs.settings(), pause_ms=0, sleep=lambda _x: None)
    return {"a": ids[0], "b": ids[1], "oa": ids[2], "ob": ids[3], "da": ids[4], "db": ids[5], "fake": fake}


def _court(msg):
    return [c for c in (msg.citations or []) if c["source_kind"] == "court_order"]


def test_hybrid_research_finds_by_meaning_and_by_number(world, scene):
    fake = scene["fake"]
    fake.default = "The respondents must release the retiral benefits [S1]."
    conn = _connector(world, fake)
    r = ol.ask(world, "edu_off1", "When is the pension to be paid out?", "research", conn)
    msg = sup.answer(world, r)
    info = msg.model_info
    assert "retrieval" in info, (msg.outcome, msg.error_family, msg.content, msg.response)
    assert info["retrieval"]["kind"] == "hybrid" and info["retrieval"]["model_key"] == rs.KEY
    assert info["retrieval"]["lists"]["meaning"] >= 1
    court = {c["document_id"]: c for c in _court(msg)}
    mine = court[str(scene["da"])]  # no word of the question is in it: found by meaning
    assert mine["match"] == "meaning" and mine["model_key"] == rs.KEY
    assert "retiral benefits" in fake.sent_text()
    assert r.outcome == "answered" and info["checks"]["removed"]["uncited"] == 0
    # a case number is found by words
    fake.default = "The order follows WP(C) 7013/2024 [S1]."
    r2 = ol.ask(world, "edu_off1", "WP(C) 7013/2024", "research", conn)
    msg2 = sup.answer(world, r2)
    court2 = {c["document_id"]: c for c in _court(msg2)}
    assert str(scene["db"]) in court2 and court2[str(scene["db"])]["match"] in ("words", "both")
    assert msg2.model_info["retrieval"]["lists"]["words"] >= 1


def test_my_cases_exact_scan(world, scene, monkeypatch):
    seen = {}
    real = rsearch.ranked_meaning

    def spy(*a, **kw):
        seen["exact"] = kw["exact"]
        return real(*a, **kw)

    monkeypatch.setattr(rsearch, "ranked_meaning", spy)
    fake = scene["fake"]
    fake.default = "The benefits are to be released [S1]."
    r = ol.ask(world, "edu_off1", "pension of the teacher", "my_cases", _connector(world, fake))
    msg = sup.answer(world, r)
    assert seen["exact"] is True
    assert {c["document_id"] for c in _court(msg)} == {str(scene["da"])}  # only the asker's own case


def test_filters_cites_act_outcome_dates(world, scene):
    fake = scene["fake"]
    fake.default = "The transfer order was set aside [S1]."
    conn = _connector(world, fake)
    r = ol.ask(world, "edu_off1", "transfer order", "research", conn, filters={"forms": ["final"]})
    msg = sup.answer(world, r)
    assert {c["document_id"] for c in _court(msg)} <= {str(scene["db"])}
    with world.Session() as s:
        q = s.get(type(msg), r.question_id)
        assert q.scope_info["filters"] == {"forms": ["final"]}
    r = ol.ask(world, "edu_off1", "transfer order", "research", conn, filters={"forms": ["judgment"],
               "from": date(2025, 4, 1)})  # fmt: skip
    assert _court(sup.answer(world, r)) == []
    with pytest.raises(svc.BadFilter):
        ol.ask(world, "edu_off1", "transfer", "research", conn, filters={"outcomes": ["won"]})
    with pytest.raises(svc.BadFilter):
        ol.ask(world, "edu_off1", "transfer", "research", conn, filters={"act": "no such act"})
    with pytest.raises(svc.BadFilter):
        ol.ask(world, "edu_off1", "transfer", "research", conn,
               filters={"from": date(2025, 5, 1), "to": date(2025, 1, 1)})  # fmt: skip
    asked = [a for a in _audits(world, "assistant.asked") if (a.after or {}).get("filters")]
    assert asked and asked[0].after["filters"]["forms"] == ["final"]


def test_against_state_rule(world, scene):
    with world.Session() as s:
        b = s.get(
            type(s.get(CaseParty, s.scalar(sa.select(CaseParty.id)))), s.scalar(sa.select(CaseParty.id))
        )
        assert b is not None
    holder = rsearch.Holder(None, None, scene["ob"], scene["db"], scene["b"], "final", False, "allowed", 0)
    from aslms.services.assistant_preview import Budget

    with world.Session() as s:
        budget = Budget(10, 5000)
        assert rsearch.against_state_ok(s, budget, holder)  # allowed, the State a respondent
        holder.outcome = "dismissed"
        assert not rsearch.against_state_ok(s, budget, holder)  # the State is not a petitioner
        holder.outcome = "disposed_of"
        assert not rsearch.against_state_ok(s, budget, holder)


def test_filters_refused_for_case_and_my_work(world, scene):
    conn = _connector(world, scene["fake"])
    with pytest.raises(svc.FiltersNotAllowed):
        ol.ask(world, "edu_off1", "pension", "case", conn, case=scene["a"], filters={"forms": ["judgment"]})
    with pytest.raises(svc.FiltersNotAllowed):
        ol.ask(world, "edu_off1", "what is with me", "my_work", conn, filters={"forms": ["judgment"]})


def test_filters_refused_when_the_index_does_not_serve(world, scene):
    """Review fix (deviation 18): with `RESEARCH_INDEX_ENABLED` off, or in preview mode, the words search would ignore
    the filters, so they are refused with `filters_unavailable` before anything is stored or audited."""
    from aslms.domain.assistant import AssistantMessage

    def counts():
        with world.Session() as s:
            asked = s.scalar(
                sa.select(sa.func.count()).select_from(AuditLog).where(AuditLog.action == "assistant.asked")
            )
            return s.scalar(sa.select(sa.func.count()).select_from(AssistantMessage)), asked

    before = counts()
    off = _connector(world, scene["fake"], research_index_enabled=False)
    preview = sup.preview(world)
    for conn in (off, preview):
        for scope in ("research", "my_cases"):
            with pytest.raises(svc.FiltersUnavailable) as exc:
                ol.ask(world, "edu_off1", "pension", scope, conn,
                       filters={"forms": ["judgment"], "outcomes": ["dismissed"]})  # fmt: skip
            assert exc.value.code == "filters_unavailable" and exc.value.http_status == 400
    assert counts() == before
    # without filters the same connector is not refused (today's words search)
    assert ol.ask(world, "edu_off1", "pension release", "research", off).outcome in ("answered", "no_match")


def test_unindexed_order_still_found_by_words(world, scene):
    with world.Session() as s:
        c = make_case(s, case_no="WP(C)/888/2025")
        sup_order = rs.court_order(
            s, c, body="The wombat survey report shall be filed.\n", day=date(2025, 6, 1)
        )
        s.commit()  # no reading yet: not in the index
        doc = sup_order.document_id
        t = s.get(DocumentText, doc)
        t.search_vector = sa.func.to_tsvector("english", t.full_text)
        s.commit()
    fake = scene["fake"]
    fake.default = "A wombat survey report is to be filed [S1]."
    r = ol.ask(world, "edu_off1", "wombat survey", "research", _connector(world, fake))
    msg = sup.answer(world, r)
    assert str(doc) in {c["document_id"] for c in _court(msg)}
    assert msg.model_info["retrieval"]["lists"]["unindexed"] >= 1


def test_stale_text_never_cited(world, scene):
    with world.Session() as s:
        t = s.get(DocumentText, scene["da"])
        t.full_text = t.full_text + "\nA line added after the reading."
        s.commit()
    fake = scene["fake"]
    fake.default = "The retiral benefits are due [S1]."
    r = ol.ask(world, "edu_off1", "pension benefits withheld", "research", _connector(world, fake))
    msg = sup.answer(world, r)
    assert str(scene["da"]) not in {c["document_id"] for c in _court(msg) if c.get("chunk_id")}
    assert msg.model_info["retrieval"]["stale_dropped"] >= 1


def test_query_embed_failure_words_only(world, scene):
    import httpx

    fake = scene["fake"]
    fake.embed_replies.append(httpx.Response(500, json={"error": "boom"}))
    fake.default = "The order follows WP(C) 7013/2024 [S1]."
    r = ol.ask(world, "edu_off1", "WP(C) 7013/2024", "research", _connector(world, fake))
    msg = sup.answer(world, r)
    assert r.outcome == "answered"
    assert msg.model_info["retrieval"]["kind"] == "words_only"
    assert msg.model_info["retrieval"]["reason"] == "unavailable"


@pytest.mark.parametrize("kind", ["research", "related"])
def test_meaning_query_walks_the_hnsw_index(world, scene, kind):
    """Decision 15: the large-set meaning query is ordered by the index expression alone, so PostgreSQL walks
    `ix_research_embeddings_hnsw_768` (a second sort key such as `c.id` forces a scan and sort of every vector). The
    seq scan, the bitmap scan and the sort are priced out so the small test tables and whatever statistics earlier
    tests left behind cannot hide which plan is possible (with only the seq scan off, the planner chose a bitmap scan
    of `research_chunks` and a sort after a full suite run, 24 Nov 2026); the exact scan keeps its tie-break and uses
    no index."""
    from aslms.db.base import vector_literal

    scope = rsearch.Scope(kind=kind, focus=(scene["a"],) if kind == "related" else ())
    params = {"v": vector_literal([0.01] * 768), "key": rs.KEY, "n": 20}
    where = rsearch._chunk_scope(scope, params)
    with world.Session() as s:
        s.execute(sa.text("SET LOCAL enable_seqscan = off"))
        s.execute(sa.text("SET LOCAL enable_bitmapscan = off"))
        s.execute(sa.text("SET LOCAL enable_sort = off"))
        s.execute(sa.text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        plan = "\n".join(
            r[0]
            for r in s.execute(sa.text("EXPLAIN " + rsearch.meaning_sql(768, where, exact=False)), params)
        )
        assert "ix_research_embeddings_hnsw_768" in plan, plan
        exact = rsearch.meaning_sql(768, where, exact=True)
        assert "c.id" in exact.split("ORDER BY")[1]
        s.rollback()
    with world.Session() as s:  # the index path answers (the iterative scan keeps filtered rows coming)
        hits = rsearch.ranked_meaning(
            s, rsearch.Budget(8.0, 8000), bag_vector("retiral benefits teacher", synonyms=rs.SYNONYMS), rs.KEY,
            768, scope, 5, exact=False, ef_search=100,
        )  # fmt: skip
        s.rollback()
    assert hits


def test_model_key_change_ignores_old_vectors(world, scene):
    fake = scene["fake"]
    fake.embed_digest = "sha256:" + "e" * 64  # a re-pull: the old vectors are another key's
    fake.default = "The order follows WP(C) 7013/2024 [S1]."
    conn = _connector(world, fake)
    r = ol.ask(world, "edu_off1", "WP(C) 7013/2024", "research", conn)
    info = sup.answer(world, r).model_info["retrieval"]
    assert info["kind"] == "hybrid" and info["lists"]["meaning"] == 0  # no vector of the live key yet
    assert info["lists"]["words"] >= 1


def test_citation_fields_and_text_changed_on_read(world, scene):
    fake = scene["fake"]
    fake.default = 'The court directed "release the retiral benefits of the petitioner" [S1].'
    r = ol.ask(world, "edu_off1", "pension benefits release", "research", _connector(world, fake))
    out = sup.read(world, "edu_off1", r)
    court = [c for c in out["citations"] if c["source_kind"] == "court_order" and c.get("chunk_id")]
    assert court
    c = court[0]
    for key in ("chunk_id", "reading_id", "paragraphs", "src", "pdf_sha256", "text_sha256", "parser_version",
                "chunker_version", "match", "same_words_in"):  # fmt: skip
        assert c.get(key) is not None, key
    assert c["text_changed"] is False
    assert c["quotes"] and c["quotes"][0]["exact"] is True
    with world.Session() as s:
        full = s.get(DocumentText, scene["da"]).full_text
        a, b = c["quotes"][0]["src"]
        assert " ".join(full[a:b].split()) == "release the retiral benefits of the petitioner"
        s.get(DocumentText, scene["da"]).full_text = full + "\nchanged"
        s.commit()
    again = sup.read(world, "edu_off1", r)
    assert [x for x in again["citations"] if x.get("chunk_id")][0]["text_changed"] is True


def test_passage_endpoint_own_answer_only(world, scene, tmp_path):
    api = ds.make_api(world, tmp_path, assistant_mode="ollama", assistant_ollama_url="http://127.0.0.1:9",
                      research_index_enabled=True)  # fmt: skip
    try:
        api.app.state.assistant_config = ol.CONFIG
        fake = scene["fake"]
        fake.default = 'It says "release the retiral benefits" [S1].'
        api.app.state.assistant_connector = _connector(world, fake)
        h = ds.login(api, "edu_off1")
        resp = api.post(
            "/assistant/ask", headers=h, json={"question": "pension release", "scope": "research"}
        )
        assert resp.status_code == 200, resp.text
        answer = resp.json()["answer"]
        label = next(c["label"] for c in answer["citations"] if c.get("chunk_id"))
        got = api.get(f"/assistant/messages/{answer['id']}/sources/{label}/passage", headers=h)
        assert got.status_code == 200, got.text
        body = got.json()
        assert body["text_changed"] is False and body["page"] >= 1
        kinds = {x["kind"] for x in body["highlights"]}
        assert "passage" in kinds and "quote" in kinds
        q = next(x for x in body["highlights"] if x["kind"] == "quote")
        assert " ".join(body["page_text"][q["start"] : q["end"]].split()) == "release the retiral benefits"
        other = ds.login(api, "edu_admin")
        assert (
            api.get(f"/assistant/messages/{answer['id']}/sources/{label}/passage", headers=other).status_code
            == 404
        )
        assert (
            api.get(f"/assistant/messages/{answer['id']}/sources/S99/passage", headers=h).status_code == 404
        )
        # filters refused for another scope, and an unknown outcome refused, before anything is stored
        bad = api.post("/assistant/ask", headers=h, json={"question": "pension", "scope": "case",
                       "case": str(scene["a"]), "filters": {"forms": ["judgment"]}})  # fmt: skip
        assert bad.status_code == 400 and bad.json()["detail"]["code"] == "filters_not_allowed"
        bad = api.post("/assistant/ask", headers=h, json={"question": "pension", "scope": "research",
                       "filters": {"outcomes": ["won"]}})  # fmt: skip
        assert bad.status_code == 400 and bad.json()["detail"]["code"] == "bad_filter"
        api.app.state.assistant_connector = _connector(world, fake, research_index_enabled=False)
        bad = api.post("/assistant/ask", headers=h, json={"question": "pension", "scope": "research",
                       "filters": {"forms": ["judgment"]}})  # fmt: skip
        assert bad.status_code == 400 and bad.json()["detail"]["code"] == "filters_unavailable"
        api.app.state.assistant_connector = _connector(world, fake)
        st = api.get("/assistant/status", headers=h).json()
        assert st["research"]["state"] in ("ready", "building") and st["research"]["coverage"] is not None
    finally:
        api.__exit__(None, None, None)


def test_answer_checks_applied_case_scope_internal(world, tmp_path):
    api = ds.make_api(world, tmp_path, assistant_mode="ollama", assistant_ollama_url="http://127.0.0.1:9")
    try:
        sc = ol.build(world, api.store)
        conn = ol.connector(world)
        r0 = ol.ask(world, "edu_admin", "quokka affidavit", "case", conn, case=sc.a, include_related=False)
        ol.switch(world, "edu_admin", sc.a, conversation_id=r0.conversation_id)
        conn.fake.default = lambda body: chat_reply(
            "The note sets out the stand [S1]. The stand was taken on 03.03.2021 according to the note [S1]."
        )
        r = ol.ask(world, "edu_admin", "numbat stand", "case", conn, case=sc.a, conversation_id=r0.conversation_id,
                   include_related=False)  # fmt: skip
        msg = sup.answer(world, r)
        checks = msg.model_info["checks"]
        assert checks["removed"]["date"] == 1 or checks["withheld"] is not None
        assert "03.03.2021" not in msg.content
    finally:
        api.__exit__(None, None, None)


def test_my_work_and_facts_not_checked(world, scene):
    conn = _connector(world, scene["fake"])
    r = ol.ask(world, "edu_off1", "what is the next hearing date", "case", conn, case=scene["a"])
    msg = sup.answer(world, r)
    assert msg.connector != "ollama" or "checks" not in (msg.model_info or {})


def _audits(world, action):
    with world.Session() as s:
        return list(
            s.scalars(sa.select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)).all()
        )


def test_audit_counts_no_text(world, scene):
    fake = scene["fake"]
    fake.default = "The retiral benefits are to be released [S1]. Invented Person Kumar signed it [S1]."
    r = ol.ask(world, "edu_off1", "pension benefits", "research", _connector(world, fake))
    (row,) = [a for a in _audits(world, "assistant.answered") if a.entity_id == r.answer_id]
    assert row.after["retrieval"]["kind"] == "hybrid" and row.after["checks"]["removed"]["name"] == 1
    blob = json.dumps(row.after)
    assert "retiral" not in blob and "Kumar" not in blob and "pension" not in blob
    assert "[Removed by ASLMS: 1 sentence" in sup.answer(world, r).content


def test_withheld_answer_when_first_sentence_fails(world, scene):
    fake = scene["fake"]
    fake.default = "The benefits were paid on 01.01.2020 [S1]. The respondents shall release them [S1]."
    r = ol.ask(world, "edu_off1", "pension benefits", "research", _connector(world, fake))
    msg = sup.answer(world, r)
    assert msg.content == NO_ANSWER_TEXT and r.outcome == "no_match"
    assert msg.model_info["checks"]["withheld"] == "first_sentence"


def test_data_health_research_block_timeout_parts(world, scene, monkeypatch):
    with world.Session() as s:
        block = data_health.research_block(s, rs.settings(), client=scene["fake"].client())
        assert block["enabled"] and block["live_model_key"] == rs.KEY and block["readiness"] == "ready"
        assert block["coverage"] == 1.0 and block["timed_out"] == []
        from aslms.services import research_index

        def slow(session, key):
            session.execute(sa.text("SELECT pg_sleep(3)"))

        monkeypatch.setattr(research_index, "counts", slow)
        block = research_index.status(
            s, enabled=True, live_key=rs.KEY, readiness="ready", timeout_s=1, restore_s=30
        )
        assert block["timed_out"] == ["counts"] and block["coverage"] is None
        assert block["table_sizes"]["research_chunks"] > 0
        off = data_health.research_block(s, rs.settings(research_index_enabled=False))
        assert off["enabled"] is False and off["readiness"] == "off"


def test_system_health_research_model_check(world, scene):
    fake = scene["fake"]
    cfg = rs.settings()
    state = fake.client().state_sync(cfg.research_embed_model)
    ok = service_checks.check_research_model(cfg, state, None, 5, 1.0)
    assert ok.status == "ok" and ok.key == "research_model"
    assert service_checks.check_research_model(cfg, state, None, 5, 0.5).status == "warn"
    fake.embed_loaded = False
    cold = service_checks.check_research_model(
        cfg, fake.client().state_sync(cfg.research_embed_model), None, 5, 1.0
    )
    assert cold.status == "warn"
    assert service_checks.check_research_model(cfg, None, "ConnectError", 5, None).status == "down"
    assert service_checks.LABELS["research_model"] == "Research Index Model"
    with world.Session() as s:
        assert service_checks.research_coverage(s, cfg, state) == 1.0


def test_assistant_status_research_state(world, scene):
    with world.Session() as s:
        user = world.user(s, "edu_off1")
        conn = _connector(world, scene["fake"])
        svc._research_coverage.clear()
        st = svc.research_status(s, rs.settings(), conn)
        assert st == {"state": "ready", "coverage": 1.0}
        assert svc.research_status(s, rs.settings(research_index_enabled=False), conn)["state"] == "off"
        scene["fake"].embed_held = False
        conn2 = _connector(world, scene["fake"])
        assert svc.research_status(s, rs.settings(), conn2)["state"] == "unavailable"
        assert user is not None


def test_preview_mode_unchanged(world, scene):
    fake = scene["fake"]
    calls = len(fake.embeds)
    r = sup.ask(world, "edu_off1", "retiral benefits", "research")
    msg = sup.answer(world, r)
    assert msg.mode == "preview" and "retrieval" not in (msg.model_info or {})
    assert len(fake.embeds) == calls


def test_research_off_is_todays_search(world, scene):
    fake = scene["fake"]
    calls = len(fake.embeds)
    fake.default = "The respondents must release the retiral benefits [S1]."
    conn = _connector(world, fake, research_index_enabled=False)
    r = ol.ask(world, "edu_off1", "retiral benefits", "research", conn)
    msg = sup.answer(world, r)
    assert msg.model_info["retrieval"] == {"kind": "words"} and "checks" in msg.model_info
    assert len(fake.embeds) == calls and r.outcome == "answered"
