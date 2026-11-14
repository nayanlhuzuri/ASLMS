"""My Work on the sidebar Assistant, against the database (design `assistant-ollama-work`, "Tests", database). Ollama is
`FakeOllama`; no test calls a real model. Every work question equals its screen's own service run as the asker; the
claim questions count as My Cases, the Department tab and the Recommended tab do; nothing private reaches a row, the
text, the fake, the audit or a log line; the model only chooses, and when it is loading, busy or down the keyword
table chooses at once; rows are snapshots re-checked at every read; audit, check and migration 0037."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest
import sqlalchemy as sa
from alembic import command

from aslms.core import clock
from aslms.domain.alerts import Alert, Notification
from aslms.domain.assistant import AssistantConversation, AssistantMessage, AssistantScope, MessageRole
from aslms.domain.cases import Case
from aslms.domain.events import AuditLog
from aslms.domain.org import Office
from aslms.domain.ownership import CaseOwnership, Recommendation, ScoreBand
from aslms.domain.reference import Role
from aslms.domain.workflow import Custody, PendingAction
from aslms.integration.sourcetrace.fake import FakeSourceTrace
from aslms.services import alerts, custody, dashboard, inbox, my_cases
from aslms.services import assistant as svc
from aslms.services import assistant_work as work
from aslms.services import ownership as own
from aslms.services.reporting_common import ReportConfig
from aslms.services.storage import LocalStore
from tests.db import alerts_support as h
from tests.db import assistant_support as sup
from tests.db import ollama_support as ol
from tests.db import workflow_support as w
from tests.db.conftest import alembic_config, head_revision
from tests.db.world import add_membership, make_case
from tests.fakes.ollama import FakeOllama, chat_reply, tool_reply

CONFIG = svc.AssistantConfig(timeout_seconds=10.0, retry_delay=0.01)
CLAIMED_Q = "how many cases were claimed by me?"


# ------------------------------------------------------------------------------------------------ helpers


def ask(world, key: str, question: str, conn, *, scope: str = "my_work", config=CONFIG, **kw):
    with world.Session() as s:
        actor, user = world.actor(s, key)
    return asyncio.run(
        svc.ask(
            world.Session, actor, user, question=question, scope=scope, connector=conn, config=config, **kw
        )
    )


def preview(world):
    return sup.preview(world, assistant_mode="preview")


def conn_of(world, fake: FakeOllama | None = None, **over):
    return ol.connector(world, fake or FakeOllama(), **over)


def msg_of(world, result) -> AssistantMessage:
    with world.Session() as s:
        m = s.get(AssistantMessage, result.answer_id)
        s.expunge(m)
        return m


def read(world, key: str, result) -> dict:
    with world.Session() as s:
        return svc.message(s, world.user(s, key), result.answer_id)


def run(world, key: str, qkey: str, params=None, *, rows_cap: int = 25) -> work.WorkAnswer:
    with world.Session() as s:
        user = world.user(s, key)
        s.expunge(user)
    q = work.BY_KEY[qkey]
    return work.answer(
        world.Session, user, qkey, params if params is not None else q.params(), rows_cap=rows_cap
    )


def ids_of(answer: work.WorkAnswer) -> list[str | None]:
    return [c["case_id"] for c in answer.citations or []]


def backdate(s, case: Case, office_code: str, when: datetime) -> None:
    office = s.scalar(sa.select(Office).where(Office.code == office_code))
    s.execute(
        sa.update(CaseOwnership)
        .where(
            CaseOwnership.case_id == case.id,
            CaseOwnership.office_id == office.id,
            CaseOwnership.status == "active",
        )
        .values(claimed_at=when)
    )
    s.flush()


def ago(days: int) -> datetime:
    return clock.now_utc() - timedelta(days=days)


def transfer(s, world, case: Case, from_key: str, to_code: str, decider: str):
    actor, user = world.actor(s, from_key)
    t = own.request_transfer(s, actor, user, case, to_office_code=to_code, reason="belongs there")
    actor2, user2 = world.actor(s, decider)
    own.decide_transfer(s, actor2, user2, t, accept=True)
    return t


def set_file(s, case: Case, *, action: str = "parawise_comments", due: date | None = None) -> None:
    row = s.get(Custody, case.id)
    row.pending_action = PendingAction(action)
    row.due_date = due
    s.flush()


@pytest.fixture()
def scene(world):
    """EDU: c1 (hearing in 2 days, held by off1, overdue action), c2 (held by off1, action due in 3 days), c3 (held
    by off1, no action), c4 (allotted to off1, sent by off1 to the DSE user, due in 5 days); a new-order alert and
    hearing alerts for off1; two recommendations to EDU (strong, possible); off2's own file and send."""
    today = clock.today_ist()
    with world.Session() as s:
        off1 = world.users["edu_off1"].id
        c1 = make_case(
            s, case_no="WP(C)/501/2026", next_hearing=today + timedelta(days=2), pet="Ram", res="State"
        )
        h.claim(s, world, "edu_admin", c1, officer_user_id=off1)
        c2 = make_case(s, case_no="WP(C)/502/2026", next_hearing=today + timedelta(days=1))
        h.claim(s, world, "edu_admin", c2, officer_user_id=off1)
        c3 = w.claimed_case(s, world, officer="edu_off1", case_no="WP(C)/503/2026")
        c4 = w.claimed_case(s, world, officer="edu_off1", case_no="WP(C)/504/2026")
        set_file(s, c1, due=today - timedelta(days=2))
        set_file(s, c2, due=today + timedelta(days=3))
        w.send(s, world, "edu_off1", c4, "dse_user", due_date=today + timedelta(days=5))
        # off2: a file of their own and a send of their own
        o1 = w.claimed_case(s, world, officer="edu_off2", case_no="WP(C)/601/2026")
        o2 = w.claimed_case(s, world, officer="edu_off2", case_no="WP(C)/602/2026")
        set_file(s, o1, due=today - timedelta(days=1))
        w.send(s, world, "edu_off2", o2, "dse_user")
        r1 = make_case(s, case_no="WP(C)/701/2026")
        r2 = make_case(s, case_no="WP(C)/702/2026")
        h.recommend(s, world, r1, "EDU", score=0.95, band=ScoreBand.HIGH)
        h.recommend(s, world, r2, "EDU", score=0.6, band=ScoreBand.MEDIUM)
        h.order_stored_event(s, c1, order_no="9", order_date=today - timedelta(days=1))
        h.order_stored_event(s, o1, order_no="9", order_date=today - timedelta(days=1))
        s.commit()
        alerts.scan_events(s, now=h.now_utc())
        alerts.sweep_dates(s, now=h.now_utc())
        s.commit()
        return {
            "c1": c1.id,
            "c2": c2.id,
            "c3": c3.id,
            "c4": c4.id,
            "o1": o1.id,
            "o2": o2.id,
            "r1": r1.id,
            "r2": r2.id,
        }


# ------------------------------------------------------------------------------------------------ the screens


VARIANTS: list[tuple[str, dict]] = [
    ("pending_actions", {"when": "overdue"}),
    ("pending_actions", {"when": "due_this_week"}),
    ("pending_actions", {"when": "all"}),
    ("cases_with_me", {}),
    *[
        ("sent_by_me", {"period": p, "still_out": so})
        for p in ("last_7_days", "last_30_days", "all")
        for so in (False, True)
    ],
    *[("my_hearings", {"range": r}) for r in ("today", "tomorrow", "this_week", "next_week")],
    ("listed_tomorrow", {}),
    *[("my_due_dates", {"range": r}) for r in ("today", "tomorrow", "this_week", "next_week")],
    ("unread_alerts", {"kind": "any"}),
    ("unread_alerts", {"kind": "hearing_due"}),
    *[("new_orders", {"days": d}) for d in (1, 7, 30)],
    ("needs_attention", {}),
    *[("claimed_by_me", {"period": p}) for p in ("last_7_days", "last_30_days", "all")],
    *[("department_claimed", {"period": p}) for p in ("last_7_days", "last_30_days", "all")],
    *[("awaiting_claim", {"band": b}) for b in ("strong", "possible", "any")],
]


def _ids(items, get=lambda i: i["case"]["id"]):
    return [str(get(i)) if get(i) else None for i in items]


def screen(s, u, key: str, p, today: date, now: datetime) -> tuple[list[str | None], int]:
    """What the screen's own service returns to the same asker with the same arguments."""
    if key == "pending_actions":
        if p.when == "overdue":
            page = custody.held(s, u, scope="me", overdue=True, limit=200)
            return _ids(page.items), page.total
        if p.when == "due_this_week":
            page = my_cases.mine(s, u, view="files", action="due_week", closure="open", limit=200)
            return _ids(page.items), page.total
        page = custody.held(s, u, scope="me", limit=200)
        items = [i for i in page.items if i["card"]["pending_action"] != "none"]
        return _ids(items), len(items)
    if key == "cases_with_me":
        page = custody.held(s, u, scope="me", limit=200)
        return _ids(page.items), page.total
    if key == "sent_by_me":
        page = custody.sent(s, u, still_out=p.still_out, since=work.period_start(p.period, today), limit=200)
        return _ids(page.items), page.total
    if key in ("my_hearings", "listed_tomorrow", "my_due_dates"):
        if key == "listed_tomorrow":
            start = end = today + timedelta(days=1)
        else:
            start, end = work.resolve_range(p, today)
        kinds = ("action_due", "confirm") if key == "my_due_dates" else ("hearing",)
        from aslms.services import calendar, next_dates

        items = [
            i
            for i in calendar.my_calendar(
                s, u, from_=start, to=end, now=now, review_cfg=next_dates.NextDateConfig.from_settings()
            )
            if i["kind"] in kinds
        ]
        return _ids(items), len(items)
    if key == "unread_alerts":
        kind = None if p.kind == "any" else p.kind
        page = alerts.list_for_user(s, u, unread=True, status="open", kind=kind, limit=200)
        return _ids(page.items, lambda i: (i["case"] or {}).get("id")), page.total
    if key == "new_orders":
        since = clock.ist_midnight(today - timedelta(days=p.days - 1))
        page = alerts.list_for_user(s, u, kind="new_order", status="all", limit=200)
        items = [i for i in page.items if i["notified_at"] >= since]
        return _ids(items, lambda i: (i["case"] or {}).get("id")), len(items)
    if key == "needs_attention":
        out = dashboard.personal_headline(
            s, u, now=now, cfg=replace(ReportConfig.from_settings(), list_size=work.WORK_SCAN_ROWS)
        )
        return _ids(out["attention"]), len(out["attention"])
    if key == "claimed_by_me":
        page = my_cases.claimed_by_me(s, u, since=work.period_start(p.period, today), limit=200)
        return _ids(page.items), page.total
    if key == "department_claimed":
        page = inbox.claimed(
            s, u, office="EDU", case_state="all", claimed_since=work.period_start(p.period, today), limit=200
        )
        return _ids(page.items), page.total
    band = {"strong": "high", "possible": "medium"}.get(p.band)
    page = inbox.recommended(s, u, office="EDU", band=band, limit=200)
    return _ids(page.items), page.total


@pytest.mark.parametrize("asker", ["edu_off1", "edu_admin"])
def test_each_work_question_equals_its_screen(world, scene, asker):
    today = clock.today_ist()
    for key, raw in VARIANTS:
        params = work.BY_KEY[key].params.model_validate(raw)
        got = run(world, asker, key, params)
        with world.Session() as s:
            u = world.user(s, asker)
            refusal = work.guard_refusal(s, u, work.BY_KEY[key])
            if refusal is not None:
                assert got.outcome == "no_match" and got.content == refusal and got.citations is None, key
                continue
            expected, total = screen(s, u, key, params, today, clock.now_utc())
            s.rollback()
        assert got.outcome == "answered", (key, raw, got.content)
        assert got.info["total"] == total, (key, raw, asker)
        assert ids_of(got) == expected[:25], (key, raw, asker)
        assert got.info["shown"] == min(total, 25)
        for c in got.citations or []:
            assert set(c["work"]["fields"]) <= set(work.FIELDS[key]), key
    # the scene gives each list something to compare for off1
    assert run(world, "edu_off1", "pending_actions").info["total"] == 2
    assert run(world, "edu_off1", "cases_with_me").info["total"] == 3
    assert run(world, "edu_off1", "sent_by_me").info["total"] == 1


# ------------------------------------------------------------------------------------------------ the claim questions


@pytest.fixture()
def claims(world):
    """edu_admin claims A (3 days ago) and B (20 days ago) and accepts Z's transfer from HEALTH (5 days ago); edu_head
    claims C; EDU watches W (HEALTH primary); edu_admin claims Y and HEALTH accepts its transfer away."""
    with world.Session() as s:
        a = make_case(s, case_no="WP(C)/801/2026")
        h.claim(s, world, "edu_admin", a)
        backdate(s, a, "EDU", ago(3))
        b = make_case(s, case_no="WP(C)/802/2026")
        h.claim(s, world, "edu_admin", b)
        backdate(s, b, "EDU", ago(20))
        z = make_case(s, case_no="WP(C)/803/2026")
        h.claim(s, world, "health_admin", z)
        transfer(s, world, z, "health_admin", "EDU", "edu_admin")
        backdate(s, z, "EDU", ago(5))
        c = make_case(s, case_no="WP(C)/804/2026")
        h.claim(s, world, "edu_head", c)
        wcase = make_case(s, case_no="WP(C)/805/2026")
        h.claim(s, world, "health_admin", wcase)
        h.recommend(s, world, wcase, "EDU")
        h.claim(s, world, "edu_admin", wcase)
        y = make_case(s, case_no="WP(C)/806/2026")
        h.claim(s, world, "edu_admin", y)
        transfer(s, world, y, "edu_admin", "HEALTH", "health_admin")
        s.commit()
        return {"a": a.id, "b": b.id, "z": z.id, "c": c.id, "w": wcase.id, "y": y.id}


def test_claimed_by_me_counts_claims_and_accepted_transfers_in_period(world, claims):
    week = run(world, "edu_admin", "claimed_by_me", work.ClaimPeriodParams(period="last_7_days"))
    month = run(world, "edu_admin", "claimed_by_me", work.ClaimPeriodParams(period="last_30_days"))
    every = run(world, "edu_admin", "claimed_by_me", work.ClaimPeriodParams(period="all"))
    assert week.info["total"] == 2 and month.info["total"] == 3 and every.info["total"] == 3
    assert set(ids_of(week)) == {str(claims["a"]), str(claims["z"])}
    assert set(ids_of(month)) == {str(claims["a"]), str(claims["b"]), str(claims["z"])}
    for never in ("c", "w", "y"):
        assert str(claims[never]) not in ids_of(every), never
    assert week.content.startswith("You claimed 2 cases in the last 7 days.")
    assert work.CLAIMED_BY_ME_NOTE in week.content.splitlines()
    via = {c["case_id"]: c["work"]["fields"]["via"] for c in every.citations}
    assert via[str(claims["z"])] == "Transfer Accepted" and via[str(claims["a"])] == "Claimed"
    assert ids_of(week)[0] == str(claims["a"])  # newest claim first
    head = run(world, "edu_head", "claimed_by_me")
    assert ids_of(head) == [str(claims["c"])]


def test_claimed_by_me_matches_my_cases_claimed_badge(world, claims):
    every = run(world, "edu_admin", "claimed_by_me")
    with world.Session() as s:
        page = my_cases.mine(s, world.user(s, "edu_admin"), view="all", limit=200)
        badge = {str(i["case"]["id"]) for i in page.items if "claimed" in i["reasons"]}
    assert set(ids_of(every)) == badge and len(badge) == 3


def test_period_boundaries_ist(world):
    today = clock.today_ist()
    six = datetime.combine(today - timedelta(days=6), datetime.min.time(), tzinfo=clock.IST).replace(
        hour=23, minute=59
    )
    seven = six - timedelta(days=1)
    with world.Session() as s:
        inside = make_case(s)
        h.claim(s, world, "edu_admin", inside)
        backdate(s, inside, "EDU", six)
        outside = make_case(s)
        h.claim(s, world, "edu_admin", outside)
        backdate(s, outside, "EDU", seven)
        s.commit()
    week = run(world, "edu_admin", "claimed_by_me", work.ClaimPeriodParams(period="last_7_days"))
    assert ids_of(week) == [str(inside.id)]


def test_department_claimed_whole_reader_and_directorate_officer(world):
    with world.Session() as s:
        unit_case = make_case(s, case_no="WP(C)/811/2026")
        h.claim(s, world, "edu_admin", unit_case, unit_code="EDU-DSE")
        plain = make_case(s, case_no="WP(C)/812/2026")
        h.claim(s, world, "edu_admin", plain)
        old = make_case(s, case_no="WP(C)/813/2026")
        h.claim(s, world, "edu_admin", old)
        backdate(s, old, "EDU", ago(40))
        s.commit()
    month = work.ClaimPeriodParams(period="last_30_days")
    admin = run(world, "edu_admin", "department_claimed", month)
    assert admin.info["total"] == 2 and set(ids_of(admin)) == {str(unit_case.id), str(plain.id)}
    assert admin.content.startswith("Education claimed 2 cases in the last 30 days.")
    assert admin.info["full_list_href"] == "/inbox/department?department=EDU"
    dse = run(world, "dse_user", "department_claimed", month)
    assert ids_of(dse) == [str(unit_case.id)]
    assert dse.content.startswith("Education claimed 1 case that you can see in the last 30 days.")
    assert dse.info["full_list_href"] == "/inbox/my-cases"
    root = run(world, "root", "department_claimed")
    assert root.outcome == "no_match" and root.content == work.NO_DEPARTMENT and root.citations is None


def _state(s) -> tuple:
    return (
        s.scalar(sa.select(sa.func.count()).select_from(CaseOwnership)),
        tuple(sorted(str(x) for x in s.scalars(sa.select(Recommendation.status)).all())),
        s.scalar(sa.select(sa.func.count()).select_from(Alert)),
        tuple(sorted((str(c.case_id), str(c.holder_user_id)) for c in s.scalars(sa.select(Custody)).all())),
    )


def test_awaiting_claim_needs_cases_claim_and_never_claims(world, scene):
    off1 = run(world, "edu_off1", "awaiting_claim")
    assert off1.outcome == "no_match" and off1.content == work.NO_LIST
    with world.Session() as s:
        before = _state(s)
    r = ask(world, "edu_admin", "Which cases are waiting to be claimed?", preview(world))
    m = msg_of(world, r)
    assert m.content.splitlines()[:2] == [
        "2 cases are recommended to Education and waiting to be claimed.",
        "1 strong and 1 possible.",
    ]
    bands = {c["case_id"]: c["work"]["fields"]["band"] for c in m.citations}
    assert bands == {str(scene["r1"]): "Strong", str(scene["r2"]): "Possible"}
    with world.Session() as s:
        assert _state(s) == before
    out = read(world, "edu_admin", r)
    for c in out["citations"]:
        assert c["open"]["kind"] == "claim"
        assert c["open"]["href"] == f"/claim/recommended?department=EDU&case={c['case']['id']}"
        assert not any("action" in k or k.startswith("can_") for k in c)
        assert "reason" not in json.dumps(c["work"]) and "score" not in json.dumps(c["work"])
    strong = run(world, "edu_admin", "awaiting_claim", work.BandParams(band="strong"))
    assert ids_of(strong) == [str(scene["r1"])]
    assert strong.info["full_list_href"] == "/claim/recommended?department=EDU&band=high"


def test_several_departments_summed_and_named(world):
    with world.Session() as s:
        admin = world.user(s, "edu_admin")
        add_membership(s, admin, world.office(s, "HEALTH"), Role.DEPT_OFFICER)
        s.commit()
        e1, e2 = make_case(s, case_no="WP(C)/821/2026"), make_case(s, case_no="WP(C)/822/2026")
        h.claim(s, world, "edu_admin", e1)
        h.claim(s, world, "edu_admin", e2)
        h1, h2 = make_case(s, case_no="WP(C)/823/2026"), make_case(s, case_no="WP(C)/824/2026")
        h.claim(s, world, "health_admin", h1, officer_user_id=admin.id)
        h.claim(s, world, "health_admin", h2)
        s.commit()
    got = run(world, "edu_admin", "department_claimed")
    assert got.info["total"] == 3 and got.info["departments"] == ["EDU", "HEALTH"]
    assert got.content.startswith(
        "Your departments have claimed 3 cases that you can see in all: Education 2, Health 1."
    )
    assert set(ids_of(got)[:2]) == {str(e1.id), str(e2.id)} and ids_of(got)[2] == str(h1.id)
    capped = run(world, "edu_admin", "department_claimed", rows_cap=2)
    assert capped.info["total"] == 3 and len(capped.citations) == 2
    assert "Showing the first 2 of 3." in capped.content


def test_other_officers_items_never_appear(world, scene):
    theirs = {str(scene["o1"]), str(scene["o2"])}
    for q in work.WORK_QUESTIONS:
        got = run(world, "edu_off1", q.key)
        assert not theirs & set(ids_of(got)), q.key


def test_private_remark_text_never_appears(world, scene, tmp_path, caplog):
    planted = ("zebrina", "quaggan", "okapix", "tapirus", "ibexia", "gazellon")
    with world.Session() as s:
        c1 = s.get(Case, scene["c1"])
        c3 = s.get(Case, scene["c3"])
        w.send(s, world, "edu_off1", c3, "dse_user", remark=f"own remark {planted[0]}")
        w.note(s, world, "edu_admin", c1, body=f"note {planted[1]}")
        w.note(s, world, "edu_admin", c1, body=f"private {planted[2]}", visibility_="private_to_office")
        from aslms.domain.documents import DocGroup
        from aslms.domain.reference import DocType

        sup.filing(
            s,
            LocalStore(tmp_path),
            c1,
            world.office(s, "EDU"),
            [f"internal {planted[3]}"],
            group=DocGroup.INTERNAL,
            doc_type=DocType.LEGAL_OPINION,
        )
        for a in s.scalars(sa.select(Alert)).all():
            a.body = f"{a.body or ''} {planted[4]}"
        for r in s.scalars(sa.select(Recommendation)).all():
            r.reason = planted[5]
        s.commit()
    fake = FakeOllama()
    conn = conn_of(world, fake)
    caplog.set_level(logging.DEBUG)
    results = []
    for key, question in (
        ("edu_off1", "what is with me?"),
        ("edu_off1", "files I sent in all"),
        ("edu_off1", "do I have unread alerts?"),
        ("edu_off1", "any new orders?"),
        ("edu_off1", "what needs my attention?"),
        ("edu_admin", "which cases are waiting to be claimed?"),
        ("edu_admin", "how many cases has my department claimed?"),
    ):
        fake.replies.append(chat_reply("no call"))
        results.append((key, ask(world, key, question, conn)))
    with world.Session() as s:
        stored = json.dumps(
            [
                [m.content, m.citations, m.model_info, m.response]
                for m in s.scalars(sa.select(AssistantMessage)).all()
            ],
            default=str,
        )
        audit = json.dumps([[a.after, a.before] for a in s.scalars(sa.select(AuditLog)).all()], default=str)
    reads = json.dumps([read(world, k, r) for k, r in results], default=str)
    for word in planted:
        assert word not in stored, word
        assert word not in fake.sent_text(), word
        assert word not in reads, word
        assert word not in caplog.text, word
    for word in planted[
        :4
    ]:  # alert bodies and reasons are in their own tables, not in any audit of the assistant
        assert word not in audit, word


# ------------------------------------------------------------------------------------------------ the choice


def test_tool_choice_valid_and_invalid(world, claims):
    fake = FakeOllama()
    conn = conn_of(world, fake)
    fake.replies.append(tool_reply(("claimed_by_me", {"period": "last_7_days"})))
    r = ask(world, "edu_admin", "how many?", conn)
    m = msg_of(world, r)
    assert m.model_info["chosen_by"] == "model" and m.model_info["choice_fallback"] is None
    assert m.model_info["question"] == "claimed_by_me" and m.model_info["params"] == {"period": "last_7_days"}
    assert m.model_info["model"] == "qwen3.5:4b" and m.connector == "work" and m.mode == "ollama"
    assert m.response["message"]["tool_calls"][0]["function"]["name"] == "claimed_by_me"
    body = fake.chats[0]
    assert len(body["tools"]) == 12 and body["think"] is False
    assert body["options"] == {"temperature": 0, "num_ctx": 4096, "num_predict": 200}
    assert body["messages"][0]["role"] == "system" and body["messages"][0]["content"].startswith(
        "Choose the one function"
    )
    assert body["messages"][1] == {"role": "user", "content": "how many?"}
    today = clock.today_ist().isoformat()
    for reply, fallback in (
        (chat_reply("I think you mean claims."), "no_call"),
        (tool_reply(("claimed_by_me", {}), ("new_orders", {})), "invalid"),
        (tool_reply(("count_everything", {})), "invalid"),
        (tool_reply(("claimed_by_me", {"period": "all", "office": "HEALTH"})), "invalid"),
        (
            tool_reply(("my_hearings", {"range": "dates", "from": "2099-01-01", "to": "2099-01-02"})),
            "invalid",
        ),
        (tool_reply(("my_hearings", {"range": "dates", "from": today, "to": "2099-01-02"})), "invalid"),
        (tool_reply(("new_orders", {"days": 999})), "invalid"),
        (tool_reply(("SELECT * FROM case_notes", {})), "invalid"),
    ):
        fake.replies.append(reply)
        r = ask(world, "edu_admin", CLAIMED_Q, conn)
        m = msg_of(world, r)
        assert m.model_info["chosen_by"] == "keyword", reply
        assert m.model_info["choice_fallback"] == fallback, reply
        assert m.model_info["question"] == "claimed_by_me" and m.outcome == "answered"
    for question in ("tell me a story about the weather", "sent alerts"):
        fake.replies.append(chat_reply("none"))
        r = ask(world, "edu_admin", question, conn)
        m = msg_of(world, r)
        assert m.model_info["chosen_by"] == "none" and m.outcome == "no_match"
        assert m.content == work.NO_MATCH_TEXT and m.citations is None and m.model_info["total"] == 0


def test_my_work_never_503_when_model_loading_busy_or_down(world, claims, monkeypatch):
    monkeypatch.setattr(work, "WORK_SLOT_WAIT_SECONDS", 0.05)
    loading = FakeOllama(loaded=False)
    busy = FakeOllama()
    down = FakeOllama(reachable=False)
    busy_conn = conn_of(world, busy)
    assert busy_conn._slots.acquire(blocking=False)
    for fake, conn, reason in (
        (loading, conn_of(world, loading), "loading"),
        (busy, busy_conn, "busy"),
        (down, conn_of(world, down), "unavailable"),
    ):
        r = ask(world, "edu_admin", CLAIMED_Q, conn)
        m = msg_of(world, r)
        assert m.outcome == "answered" and m.model_info["chosen_by"] == "keyword", reason
        assert m.model_info["choice_fallback"] == reason and m.model_info["model"] is None
        assert fake.chats == [], reason
    busy_conn._slots.release()


def test_answer_text_written_by_server_count_first(world, claims):
    fake = FakeOllama()
    conn = conn_of(world, fake)
    fake.replies.append(tool_reply(("claimed_by_me", {"period": "all"})))
    r = ask(world, "edu_admin", "my claims please", conn)
    m = msg_of(world, r)
    assert m.content.splitlines()[0] == "You have claimed 3 cases in all."
    assert m.content.splitlines()[-1] == "Showing all 3."
    assert len(fake.chats) == 1  # no wording call
    with world.Session() as s:
        numbers = [c.case_no_text for c in s.scalars(sa.select(Case)).all()]
    assert not any(n and n in m.content for n in numbers)


def test_zero_rows_sentence(world):
    got = run(world, "edu_admin", "claimed_by_me")
    assert got.outcome == "answered" and got.citations == []
    assert got.content == "You have claimed no cases in all.\n" + work.CLAIMED_BY_ME_NOTE
    assert run(world, "edu_off1", "listed_tomorrow").content.startswith(
        "None of your cases are on tomorrow's"
    )


def test_rows_capped_and_shown_line(world):
    with world.Session() as s:
        for i in range(41):
            h.recommend(s, world, make_case(s, case_no=f"WP(C)/9{i:02d}/2026"), "EDU", score=0.9)
        s.commit()
    got = run(world, "edu_admin", "awaiting_claim")
    assert got.info["total"] == 41 and len(got.citations) == 25 and got.info["shown"] == 25
    assert "Showing the first 25 of 41. Open the full list for the rest." in got.content
    assert [c["label"] for c in got.citations] == [f"S{i}" for i in range(1, 26)]


def test_scan_cap_says_at_least(world, scene, monkeypatch):
    monkeypatch.setattr(work, "WORK_SCAN_ROWS", 1)
    monkeypatch.setattr(work, "WORK_PAGE", 1)
    got = run(world, "edu_off1", "cases_with_me")
    assert got.info["scan_capped"] is True and got.info["total"] == 1
    lines = got.content.splitlines()
    assert lines[0] == "At least 1 case file is with you."
    assert lines[-1] == "Showing the first 1 of at least 1. Open the full list for the rest."


def test_services_unchanged_without_new_keywords(world, scene, claims):
    with world.Session() as s:
        for key in ("edu_off1", "edu_admin", "dse_user"):
            u = world.user(s, key)
            assert custody.sent(s, u, limit=200).items == custody.sent(s, u, since=None, limit=200).items
            a = inbox.claimed(s, u, office="EDU", case_state="all", limit=200) if key != "dse_user" else None
            b = (
                inbox.claimed(s, u, office="EDU", case_state="all", claimed_since=None, limit=200)
                if key != "dse_user"
                else None
            )
            assert (a.items if a else None) == (b.items if b else None)
            c1 = my_cases.my_conditions(s, u)
            c2 = my_cases.my_conditions(s, u, claimed_since=None)
            q1 = s.scalars(sa.select(Case.id).where(c1.claimed).order_by(Case.id)).all()
            q2 = s.scalars(sa.select(Case.id).where(c2.claimed).order_by(Case.id)).all()
            assert q1 == q2


def test_my_work_refused_with_case_in_sourcetrace_and_off(world, scene):
    def count(s):
        return s.scalar(sa.select(sa.func.count()).select_from(AssistantMessage))

    with world.Session() as s:
        before = count(s)
    with pytest.raises(svc.ScopeMismatch):
        ask(world, "edu_off1", CLAIMED_Q, preview(world), case=scene["c1"])
    with pytest.raises(svc.ScopeUnavailable) as exc:
        ask(world, "edu_off1", CLAIMED_Q, FakeSourceTrace())
    assert exc.value.code == "scope_unavailable" and exc.value.http_status == 422
    with pytest.raises(svc.AssistantOff):
        ask(world, "edu_off1", CLAIMED_Q, None)
    with world.Session() as s:
        assert count(s) == before


def test_my_work_in_preview_same_answer_as_ollama_keyword(world, claims):
    p = msg_of(world, ask(world, "edu_admin", CLAIMED_Q, preview(world)))
    o = msg_of(world, ask(world, "edu_admin", CLAIMED_Q, conn_of(world, FakeOllama(reachable=False))))
    assert p.mode == "preview" and o.mode == "ollama"
    assert p.content == o.content and p.model_info["chosen_by"] == "keyword"
    strip = [{**c, "work": {**c["work"], "as_of": None}} for c in p.citations]
    strip_o = [{**c, "work": {**c["work"], "as_of": None}} for c in o.citations]
    assert strip == strip_o
    assert p.response is None


def test_work_row_reread_hides_row_keeps_text(world, claims):
    r = ask(world, "edu_admin", CLAIMED_Q, preview(world))
    before = read(world, "edu_admin", r)
    assert all(c["available"] for c in before["citations"])
    with world.Session() as s:
        transfer(s, world, s.get(Case, claims["a"]), "edu_admin", "HEALTH", "health_admin")
        s.commit()
    after = read(world, "edu_admin", r)
    assert after["content"] == before["content"] and after["hidden_reason"] is None
    hidden = [c for c in after["citations"] if not c["available"]]
    assert len(hidden) == 1
    gone = hidden[0]
    assert gone["unavailable_reason"] == work.HIDDEN_ROW and gone["work"]["fields"] == {}
    assert (
        gone["case"] == {"id": None, "case_no_text": None, "cnr": None, "visible": False}
        and gone["open"] is None
    )
    assert sum(1 for c in after["citations"] if c["available"]) == 2
    assert after["work"]["question"] == "claimed_by_me" and after["work"]["total"] == 3


def test_suggest_work_on_court_scopes(world, claims):
    fake = FakeOllama()
    conn = conn_of(world, fake)
    r = ask(world, "edu_admin", CLAIMED_Q, conn, scope="my_cases")
    m = msg_of(world, r)
    assert m.connector == "ollama" and m.model_info["suggest_work"] is True
    assert fake.chats == []  # nothing found in the court records: no model call, and none for the suggestion
    assert read(world, "edu_admin", r)["suggest_work"] is True
    court = msg_of(
        world, ask(world, "edu_admin", "what did the court direct on the affidavit?", conn, scope="research")
    )
    assert court.model_info["suggest_work"] is False
    # a question the asker may not ask in My Work is not suggested
    pm = msg_of(
        world,
        ask(world, "edu_off1", "which cases are waiting to be claimed", preview(world), scope="my_cases"),
    )
    assert pm.model_info["suggest_work"] is False


def test_reading_alerts_through_my_work_marks_nothing_read(world, scene):
    with world.Session() as s:
        before = sorted(
            (str(n.id), str(n.status), n.read_at) for n in s.scalars(sa.select(Notification)).all()
        )
    r = ask(world, "edu_off1", "do I have unread alerts?", preview(world))
    assert msg_of(world, r).model_info["total"] > 0
    with world.Session() as s:
        after = sorted(
            (str(n.id), str(n.status), n.read_at) for n in s.scalars(sa.select(Notification)).all()
        )
    assert after == before


def test_work_session_is_read_only(world, scene, monkeypatch):
    def writer(ctx, params):
        ctx.session.execute(sa.text("UPDATE cases SET case_no_text = case_no_text"))
        return work.WorkResult()

    monkeypatch.setitem(work.BY_KEY, "cases_with_me", replace(work.BY_KEY["cases_with_me"], run=writer))
    with pytest.raises(sa.exc.DBAPIError, match="read-only"):
        run(world, "edu_off1", "cases_with_me")
    r = ask(world, "edu_off1", "Which case files are with me?", preview(world))
    m = msg_of(world, r)
    assert m.outcome == "failed" and m.error_family == "error" and m.content == work.ERROR_TEXT


def test_my_work_counts_toward_hourly_limit(world, scene):
    config = replace(CONFIG, questions_per_hour=2)
    ask(world, "edu_off1", "affidavit", preview(world), scope="research", config=config)
    ask(world, "edu_off1", "what is with me?", preview(world), config=config)
    with pytest.raises(svc.AssistantLimit):
        ask(world, "edu_off1", "what is with me?", preview(world), config=config)


def test_my_work_audit_keys_params_counts_no_text(world, claims):
    question = "how many cases were claimed by me in the past week?"
    r = ask(world, "edu_admin", question, preview(world))
    with world.Session() as s:
        asked = s.scalar(sa.select(AuditLog).where(AuditLog.entity_id == r.question_id))
        answered = s.scalar(sa.select(AuditLog).where(AuditLog.entity_id == r.answer_id))
    assert asked.action == "assistant.asked" and asked.after["scope"] == "my_work"
    assert "work_question" not in asked.after
    a = answered.after
    assert answered.action == "assistant.answered"
    assert a["work_question"] == "claimed_by_me" and a["work_params"] == {"period": "last_7_days"}
    assert a["chosen_by"] == "keyword" and a["choice_fallback"] is None
    assert a["work_rows"] == 2 and a["work_total"] == 2 and a["departments"] == []
    blob = json.dumps([asked.after, answered.after], default=str)
    assert question not in blob and "WP(C)" not in blob and "You claimed" not in blob


def test_check_counts_work_row_outside_my_work_or_extra_field(world, claims):
    ask(world, "edu_admin", CLAIMED_Q, preview(world))
    with world.Session() as s:
        assert set(svc.check(s).values()) == {0} and len(svc.check(s)) == 6
        conv = AssistantConversation(
            user_id=world.users["edu_admin"].id, scope=AssistantScope.MY_CASES, title="planted"
        )
        work_conv = AssistantConversation(
            user_id=world.users["edu_admin"].id, scope=AssistantScope.MY_WORK, title="planted"
        )
        s.add_all([conv, work_conv])
        s.flush()
        row = {
            "source_kind": "work_row",
            "label": "S1",
            "cited": True,
            "case_id": str(claims["a"]),
            "work": {
                "question": "claimed_by_me",
                "list_label": "x",
                "as_of": None,
                "fields": {"case_no": "x"},
            },
        }
        bad = {**row, "work": {**row["work"], "fields": {"case_no": "x", "remark": "y"}}}
        for c, cit in ((conv, row), (work_conv, bad)):
            q = AssistantMessage(conversation_id=c.id, role=MessageRole.USER, content="planted q")
            s.add(q)
            s.flush()
            s.add(
                AssistantMessage(
                    conversation_id=c.id,
                    role=MessageRole.ASSISTANT,
                    content="planted",
                    reply_to_id=q.id,
                    mode="preview",
                    connector="work",
                    outcome="answered",
                    citations=[cit],
                )
            )
        s.flush()
        counts = svc.check(s)
        s.rollback()
    assert counts["work_rows_out_of_rule"] == 2 and counts["citations_of_unknown_kind"] == 0


@pytest.mark.migration_cycle
def test_migration_0037_my_work_up_down(db_url, engine, world):
    cfg = alembic_config(db_url)
    with world.Session() as s:
        conv = AssistantConversation(
            user_id=world.users["edu_admin"].id, scope=AssistantScope.MY_WORK, title="x"
        )
        s.add(conv)
        s.commit()
        conv_id = conv.id
    try:
        with pytest.raises(RuntimeError, match="cannot downgrade 0037"):
            command.downgrade(cfg, "0036")
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM assistant_conversations WHERE id = :i"), {"i": conv_id})
        command.downgrade(cfg, "0036")
        with engine.begin() as conn:
            labels = conn.execute(sa.text("SELECT enum_range(NULL::assistant_scope)::text")).scalar()
        assert "my_work" in labels  # an enum value cannot be dropped; it stays unused
    finally:
        command.upgrade(cfg, "head")
    with engine.begin() as conn:
        assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == head_revision()


def test_lists_out_of_time_store_a_failed_timeout_answer(world, scene, monkeypatch):
    def slow(ctx, params):
        ctx.session.execute(sa.text("SELECT pg_sleep(2)"))
        return work.WorkResult()

    monkeypatch.setattr(work, "WORK_STATEMENT_MS", 50)
    monkeypatch.setitem(work.BY_KEY, "cases_with_me", replace(work.BY_KEY["cases_with_me"], run=slow))
    r = ask(world, "edu_off1", "Which case files are with me?", preview(world))
    m = msg_of(world, r)
    assert m.outcome == "failed" and m.error_family == "timeout" and m.content == work.TIMEOUT_TEXT
    assert m.citations is None and m.model_info["question"] == "cases_with_me"


def test_cli_ask_my_work_prints_choice_count_and_rows_and_check_six(world, claims, monkeypatch):
    import typer
    from typer.testing import CliRunner

    from aslms.cli import assistant as cli
    from aslms.core.config import Settings

    app = typer.Typer()
    app.add_typer(cli.assistant_app, name="assistant")
    runner = CliRunner()
    monkeypatch.setattr(
        cli, "get_settings", lambda: Settings(_env_file=None, app_env="prod", assistant_mode="preview")
    )
    r = runner.invoke(app, ["assistant", "ask", "--user", "admin.edu@example.org", "--my-work", CLAIMED_Q])
    assert r.exit_code == 2
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None, assistant_mode="preview"))
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: world.Session)
    r = runner.invoke(app, ["assistant", "ask", "--user", "admin.edu@example.org", "--my-work", CLAIMED_Q])
    assert r.exit_code == 0, r.output
    assert "question: claimed_by_me  params: period=all  chosen_by: keyword  choice_fallback: -" in r.output
    assert "You have claimed 3 cases in all." in r.output
    assert "[S1] WP(C)/" in r.output and "[S3] WP(C)/" in r.output
    r = runner.invoke(
        app, ["assistant", "ask", "--user", "admin.edu@example.org", "--my-work", "--research", CLAIMED_Q]
    )
    assert r.exit_code != 0  # one scope only
    monkeypatch.setattr(cli, "session_scope", lambda: world.Session.begin())
    r = runner.invoke(app, ["assistant", "check"])
    assert r.exit_code == 0, r.output
    assert (
        "work_rows_out_of_rule: 0" in r.output
        and len([ln for ln in r.output.splitlines() if ln.strip()]) == 6
    )
