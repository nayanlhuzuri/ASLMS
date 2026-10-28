"""Quick facts from the case record, against the database (design `assistant-polish`, decisions 10 to 15, "Tests"):
answered on the case tab's This case scope without any model in every mode, stored and audited like other answers
with the connector `facts`, behind the case page's read guard, counted against the hourly limit, never fed back to the
model, re-read under the reader's sight, and stating the same next-hearing values as the case page. Ollama is
`FakeOllama`; no test calls a real model."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

import pytest
import sqlalchemy as sa

from aslms.core import clock
from aslms.domain.alerts import NextDate, NextDateSource, ReviewStatus
from aslms.domain.assistant import AssistantConversation, AssistantMessage, AssistantScope, MessageRole
from aslms.domain.cases import Case, CaseParty, CaseStatus, PartyRole
from aslms.domain.documents import Order
from aslms.domain.events import AuditLog
from aslms.domain.org import PermissionEffect
from aslms.domain.reference import Permission
from aslms.integration.sourcetrace.fake import FakeSourceTrace
from aslms.services import access, case_detail
from aslms.services import assistant as svc
from aslms.services import assistant_facts as af
from aslms.services.visibility import NotVisibleCase
from tests.db import assistant_support as sup
from tests.db import ollama_support as ol
from tests.db import workflow_support as w
from tests.fakes.ollama import FakeOllama

PET, RES = "DINAR AHMED AND 3 ORS", "THE STATE OF ASSAM AND 4 ORS"


@pytest.fixture()
def store(tmp_path):
    from aslms.services.storage import LocalStore

    return LocalStore(tmp_path / "store")


@pytest.fixture()
def case_id(world, store):
    """An EDU case claimed by the EDU admin with printed parties and advocates, party rows, a coram and one order."""
    with world.Session() as s:
        c = w.claimed_case(s, world, officer="edu_off1", case_no="WP(C)/2615/2026")
        c.petitioner_summary, c.respondent_summary = PET, RES
        c.pet_advocate, c.res_advocate = "MR. S BANIK, SR. ADV.", "SC, SEC. EDU."
        c.coram = "HON'BLE MR. JUSTICE QUOKKA"
        for role, n in ((PartyRole.PETITIONER, 4), (PartyRole.RESPONDENT, 5)):
            for i in range(1, n + 1):
                s.add(
                    CaseParty(
                        case_id=c.id, role=role, party_no=i, name=f"{role} {i}", name_normalised=f"{role} {i}"
                    )
                )
        sup.order(s, store, c, ["let all these matters be listed on 05.11.2026"], order_no="4")
        s.commit()
        return c.id


def _conn(world, **kw):
    return ol.connector(world, FakeOllama(**kw))


def _ask(world, key, question, case_id, conn, scope="case", **kw):
    return ol.ask(world, key, question, scope, conn, case=case_id if scope == "case" else None, **kw)


def _audits(world, action):
    with world.Session() as s:
        return list(
            s.scalars(sa.select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)).all()
        )


def _count(world) -> int:
    with world.Session() as s:
        return int(s.scalar(sa.select(sa.func.count()).select_from(AssistantMessage)) or 0)


def _model_calls(fake: FakeOllama) -> list[str]:
    return [p for _m, p, _b in fake.requests if p in ("/api/chat", "/api/generate")]


def test_quick_fact_answered_without_model(world, case_id):
    conn = _conn(world, loaded=False)  # the model path would refuse with assistant_loading
    r = _ask(world, "edu_admin", "Who are the parties?", case_id, conn)
    assert r.outcome == "answered"
    assert _model_calls(conn.fake) == [] and conn.fake.requests == []
    msg = sup.answer(world, r)
    assert (msg.connector, msg.mode, msg.outcome) == ("facts", "ollama", "answered")
    assert msg.citations == [
        {
            "source_kind": "case_details",
            "label": "S1",
            "cited": True,
            "case_id": str(case_id),
            "hearings": 0,
            "listings": 0,
            "compact": False,
        }
    ]
    assert msg.model_info == {"engine": "case_record", "facts": ["parties"], "facts_version": 1}
    assert msg.response is None
    assert msg.content == (
        f"{PET} versus {RES} [S1]. 4 petitioners and 5 respondents are listed on the Parties tab [S1]."
    )
    out = sup.read(world, "edu_admin", r)
    assert out["engine"] == {"kind": "case_record", "model": None}
    assert out["checks"] is None and out["suggest_internal"] is False
    assert [c["source_kind"] for c in out["citations"]] == ["case_details"]
    assert out["citations"][0]["label"] == "S1" and out["citations"][0]["available"] is True


def test_quick_fact_two_facts_in_order(world, case_id):
    r = _ask(world, "edu_admin", "who is the judge and when was the last order passed", case_id, _conn(world))
    text = sup.answer(world, r).content
    first, second = text.split("\n\n")
    assert first == "Before HON'BLE MR. JUSTICE QUOKKA [S1]."
    assert second == "The last order is dated 12 Mar 2026 (No. 4) [S1]."


def test_quick_fact_in_preview_and_sourcetrace_modes(world, case_id):
    r = _ask(world, "edu_admin", "who are the advocates", case_id, sup.preview(world))
    msg = sup.answer(world, r)
    assert (msg.mode, msg.connector, msg.outcome) == ("preview", "facts", "answered")
    assert (
        msg.content == "For the petitioners: MR. S BANIK, SR. ADV.. For the respondents: SC, SEC. EDU. [S1]."
    )
    fake = FakeSourceTrace()
    r2 = _ask(world, "edu_admin", "who are the advocates", case_id, fake)
    msg2 = sup.answer(world, r2)
    assert (msg2.mode, msg2.connector) == ("sourcetrace", "facts") and msg2.content == msg.content
    assert fake.asked == []
    out = sup.read(world, "edu_admin", r2)
    assert out["engine"] == {"kind": "case_record", "model": None}


def test_quick_fact_audit(world, case_id):
    r = _ask(world, "edu_admin", "who are the parties", case_id, _conn(world))
    asked = _audits(world, "assistant.asked")[-1]
    answered = _audits(world, "assistant.answered")[-1]
    assert asked.after["quick_fact"] == ["parties"] and "internal" not in asked.after
    assert answered.after["connector"] == "facts" and answered.after["facts"] == ["parties"]
    assert answered.after["outcome"] == "answered" and answered.after["citations"] == []
    assert answered.entity_id == r.answer_id and answered.case_id == case_id
    for row in (asked, answered):
        blob = json.dumps(row.after)
        assert "who are the parties" not in blob and "DINAR" not in blob and "versus" not in blob


def _deny(world, key, *perms):
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        for p in perms:
            access.set_override(s, actor, root, world.membership(s, key), p, PermissionEffect.DENY)
        s.commit()


def test_quick_fact_needs_read_guard(world, case_id):
    """Without the case page's read guard the quick fact is not answered; in this world the case is then out of
    sight as well, so the question is refused as today and nothing is stored or sent."""
    _deny(world, "edu_admin", Permission.CASES_VIEW_SCOPE, Permission.CASES_VIEW_ALL)
    conn = _conn(world)
    with pytest.raises(NotVisibleCase):
        _ask(world, "edu_admin", "who are the parties", case_id, conn)
    assert _count(world) == 0 and _model_calls(conn.fake) == []
    assert conn.fake.requests, "the ordinary path checked the model's readiness first"


def test_quick_fact_needs_read_guard_ordinary_path(world, case_id, monkeypatch):
    """The same question takes the connector path when the guard does not hold (the guard alone decides)."""
    from aslms.services import assistant_internal

    monkeypatch.setattr(assistant_internal, "read_guard", lambda s, u: False)
    conn = _conn(world)
    r = _ask(world, "edu_admin", "who are the parties", case_id, conn)
    msg = sup.answer(world, r)
    assert msg.connector == "ollama" and len(conn.fake.chats) <= 1
    assert "quick_fact" not in _audits(world, "assistant.asked")[-1].after


@pytest.mark.parametrize("scope", ["my_cases", "research"])
def test_quick_fact_case_scope_only(world, case_id, scope):
    conn = _conn(world)
    r = _ask(world, "edu_admin", "who are the parties", case_id, conn, scope=scope)
    assert sup.answer(world, r).connector == "ollama"
    assert "quick_fact" not in _audits(world, "assistant.asked")[-1].after


def test_quick_fact_case_not_visible(world, case_id):
    conn = _conn(world)
    with pytest.raises(NotVisibleCase):
        _ask(world, "health_off", "who are the parties", case_id, conn)
    assert _count(world) == 0 and conn.fake.requests == []


def test_quick_fact_counts_and_in_flight(world, case_id):
    conn = _conn(world)
    one = svc.AssistantConfig(timeout_seconds=10.0, retry_delay=0.01, questions_per_hour=1)
    with world.Session() as s:
        actor, user = world.actor(s, "edu_admin")
    import asyncio

    def ask(question, config=one):
        return asyncio.run(
            svc.ask(
                world.Session,
                actor,
                user,
                question=question,
                scope="case",
                case=case_id,
                connector=conn,
                config=config,
            )
        )

    ask("who are the parties")
    with pytest.raises(svc.AssistantLimit):
        ask("what is the status")
    # the in-flight rule: an unanswered question of the user blocks a quick fact too
    with world.Session() as s:
        conv = AssistantConversation(user_id=user.id, case_id=case_id, scope=AssistantScope.CASE, title="t")
        s.add(conv)
        s.flush()
        s.add(AssistantMessage(conversation_id=conv.id, role=MessageRole.USER, content="waiting question"))
        s.commit()
    with pytest.raises(svc.QuestionInFlight):
        ask("what is the status", config=sup.CONFIG)


def _next_date(s, case, when, source, *, order=None, ref=None):
    row = NextDate(
        case_id=case.id,
        next_date=when,
        source=source,
        order_id=order.id if order is not None else None,
        needs_review=False,
        review_status=ReviewStatus.NOT_NEEDED,
        ref_no=ref,
    )
    s.add(row)
    s.flush()
    return row


def test_quick_fact_equals_case_page(world, case_id, store):
    today = clock.today_ist()
    with world.Session() as s:
        cases = {}
        c1 = w.claimed_case(s, world, officer=None)
        c1.next_hearing_date = today + timedelta(days=6)
        cases["court only"] = c1.id
        c2 = w.claimed_case(s, world, officer=None)
        c2.next_hearing_date = today - timedelta(days=13)
        o2, _ = sup.order(s, store, c2, ["list on a later date"], order_date=today - timedelta(days=13))
        _next_date(s, c2, today + timedelta(days=8), NextDateSource.ORDER_SPECIFIC, order=o2)
        cases["order date"] = c2.id
        c3 = w.claimed_case(s, world, officer=None)
        _next_date(
            s, c3, today + timedelta(days=12), NextDateSource.MANUAL, ref=f"T/NXT/{uuid.uuid4().hex[:10]}"
        )
        cases["manual"] = c3.id
        c4 = w.claimed_case(s, world, officer=None)
        c4.next_hearing_date = today + timedelta(days=2)
        o4, _ = sup.order(s, store, c4, ["list again"], order_date=today - timedelta(days=3))
        _next_date(s, c4, today + timedelta(days=9), NextDateSource.ORDER_PERIOD, order=o4)
        cases["both"] = c4.id
        c5 = w.claimed_case(s, world, officer=None)
        c5.status, c5.disposal_date = CaseStatus.DISPOSED, today - timedelta(days=30)
        cases["disposed"] = c5.id
        s.commit()
    for name, cid in cases.items():
        r = _ask(world, "edu_admin", "when is the next date", cid, _conn(world))
        text = sup.answer(world, r).content
        with world.Session() as s:
            user = world.user(s, "edu_admin")
            case = s.get(Case, cid)
            page = case_detail.overview(s, user, case)
            nh = af.next_hearing(s, case, today=today)
        court = page["status"]["next_hearing_date"]
        from_orders = (page["next_date_from_orders"] or {}).get("next_date")
        assert nh.court_date == court, name
        assert nh.next_date == from_orders, name
        if name == "disposed":
            assert af.plain_date(case.disposal_date) in text, (name, text)
            continue
        for d in (court, from_orders):
            if d is not None:
                assert af.plain_date(d) in text, (name, text)
        assert text.endswith("[S1]."), text


def test_quick_fact_not_in_history(world, case_id):
    conn = _conn(world)
    r = _ask(world, "edu_admin", "who are the parties", case_id, conn)
    _ask(
        world,
        "edu_admin",
        "what did the court direct on these matters",
        case_id,
        conn,
        conversation_id=r.conversation_id,
    )
    sent = conn.fake.sent_text()
    assert conn.fake.chats, "the second question goes to the model"
    assert "who are the parties" not in sent and "versus" not in sent and "Earlier questions" not in sent


def test_quick_fact_rereads_under_reader(world, case_id):
    r = _ask(world, "edu_admin", "who is the judge", case_id, _conn(world))
    out = sup.read(world, "edu_admin", r)
    assert "Coram: HON'BLE MR. JUSTICE QUOKKA" in out["citations"][0]["context"]
    with world.Session() as s:
        s.get(Case, case_id).coram = "HON'BLE MR. JUSTICE NUMBAT"
        s.commit()
    out = sup.read(world, "edu_admin", r)
    assert "Coram: HON'BLE MR. JUSTICE NUMBAT" in out["citations"][0]["context"]
    assert out["content"] == "Before HON'BLE MR. JUSTICE QUOKKA [S1]."  # the stored answer is never rewritten
    with world.Session() as s:
        s.get(Case, case_id).merged_into_case_id = w.claimed_case(s, world, officer=None).id
        s.commit()
    out = sup.read(world, "edu_admin", r)
    assert out["citations"][0]["available"] is False and out["citations"][0]["context"] is None


def test_order_next_date_given_to_the_model_never_manual(world, case_id, store):
    today = clock.today_ist()
    with world.Session() as s:
        case = s.get(Case, case_id)
        case.next_hearing_date = today - timedelta(days=13)
        order = s.scalar(sa.select(Order).where(Order.case_id == case_id))
        _next_date(
            s,
            case,
            today + timedelta(days=8),
            NextDateSource.ORDER_SPECIFIC,
            order=order,
        )
        s.commit()
        expected = af.plain_date(af.next_hearing(s, case, today=today).next_date)
    conn = _conn(world)
    _ask(world, "edu_admin", "what did the court direct on these matters", case_id, conn)
    sent = conn.fake.chats[0]["messages"][-1]["content"]
    assert f"Next date from the order of 12 Mar 2026: {expected}" in sent
    assert "Coram: HON'BLE MR. JUSTICE QUOKKA" in sent
    # a manual date is an officer's entry: never given to the model
    with world.Session() as s:
        case = s.get(Case, case_id)
        _next_date(
            s, case, today + timedelta(days=40), NextDateSource.MANUAL, ref=f"T/NXT/{uuid.uuid4().hex[:10]}"
        )
        s.commit()
        manual = af.plain_date(today + timedelta(days=40))
    conn2 = _conn(world)
    _ask(world, "edu_admin", "what did the court direct on these matters", case_id, conn2)
    sent2 = conn2.fake.chats[0]["messages"][-1]["content"]
    assert manual not in sent2 and "entered in ASLMS" not in sent2 and "Next date from the order" not in sent2
