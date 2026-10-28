"""The personal dashboard headline (design `portal-ui-redesign`, decision 23 and API A7, "Tests, round 4"): each
headline figure against a hand-built fixture (claim counts only where `cases.claim` is held, hearings within 48
hours, due today, the oldest overdue days, the confirm count and null without the function), the order and limits
of `upcoming` and `attention`, visibility on every item, the existing fields unchanged, and nothing written."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from aslms.domain.org import PermissionEffect
from aslms.domain.ownership import ScoreBand
from aslms.domain.reference import Permission
from aslms.domain.workflow import Custody
from aslms.services import dashboard, my_cases, next_dates
from aslms.services.reporting_common import ReportConfig
from tests.db.alerts_support import recommend
from tests.db.report_support import claim, new_case, override, row_counts, today
from tests.db.workflow_support import send


def _sent(s, world, days: int | None, *, hearing: int | None = None, ago_hours: int = 0):
    """An EDU case allotted to edu_off1 and sent to edu_off2 with a pending action, due in `days` (None: no due
    date), received `ago_hours` ago, with a hearing in `hearing` days."""
    case = new_case(s, next_hearing=today() + timedelta(days=hearing) if hearing is not None else None)
    claim(s, world, case, officer="edu_off1")
    send(s, world, "edu_off1", case, "edu_off2", due_date=today() + timedelta(days=30))
    row = s.get(Custody, case.id)
    row.due_date = today() + timedelta(days=days) if days is not None else None
    row.since = datetime.now(UTC) - timedelta(hours=ago_hours)
    s.flush()
    return case


def _me(s, world, key: str, **kw) -> dict:
    return dashboard.me_block(s, world.user(s, key), **kw)


def _enter_item(s, case):
    """An order of the case that gives no clear next date: a date to enter (design next-date-direct, decision 2)."""
    from tests.db import next_dates_support as nds

    order = nds.order_with_text(
        s, case, "List the matter after the ensuing vacation.", order_date=today() - timedelta(days=1)
    )
    nds.read(s)
    return order


def test_headline_figures(world):
    with world.Session() as s:
        for band in (ScoreBand.HIGH, ScoreBand.HIGH, ScoreBand.MEDIUM):
            recommend(s, world, new_case(s), "EDU", band=band, score=0.9 if band == ScoreBand.HIGH else 0.6)
        recommend(s, world, new_case(s), "HEALTH", band=ScoreBand.HIGH, score=0.9)
        _sent(s, world, 0, hearing=1)  # due today, hearing tomorrow (within 48 h)
        _sent(s, world, -3, hearing=5)  # overdue 3 days, hearing this week
        _sent(s, world, -1, hearing=9)  # overdue 1 day, hearing beyond the week
        _sent(s, world, 6)
        nd_case = _sent(s, world, None)
        _enter_item(s, nd_case)
        off2 = world.user(s, "edu_off2")
        head = dashboard.me_block(s, off2)["headline"]
        assert head["to_claim"] is None  # an officer holds no cases.claim
        assert head["hearings_week"] == {"total": 2, "within_48h": 1}
        assert head["files_with_me"] == {"total": 5, "due_today": 1}
        assert head["files_with_me"]["total"] == my_cases.mine_counts(s, off2)["files"]
        assert head["overdue_actions"] == {"total": 2, "oldest_days": 3}
        assert head["next_dates_to_confirm"] == next_dates.queue_count(s, off2) == 1
        # the claim counts only where cases.claim is held, each department its own
        assert _me(s, world, "edu_admin")["headline"]["to_claim"] == {"high": 2, "medium": 1}
        assert _me(s, world, "health_admin")["headline"]["to_claim"] == {"high": 1, "medium": 0}
        # without next_dates.review the confirm figure is null and no confirm item is listed
        override(s, world, "edu_off2", Permission.NEXT_DATES_REVIEW, PermissionEffect.DENY)
        me = _me(s, world, "edu_off2")
        assert me["headline"]["next_dates_to_confirm"] is None
        assert all(i["kind"] != "confirm_next_date" for i in me["attention"])
        # nothing overdue: the oldest is null
        off1 = _me(s, world, "edu_off1")["headline"]
        assert off1["overdue_actions"] == {"total": 0, "oldest_days": None}
        assert off1["files_with_me"]["total"] == 0


def test_upcoming_lists_my_hearings_of_the_week_in_order(world):
    with world.Session() as s:
        late = _sent(s, world, None, hearing=6)
        soon = _sent(s, world, None, hearing=1)
        _sent(s, world, None, hearing=10)
        other = new_case(s, next_hearing=today() + timedelta(days=2))
        claim(s, world, other, by="health_admin")
        up = _me(s, world, "edu_off2")["upcoming"]
        assert [i["case"]["id"] for i in up] == [soon.id, late.id]
        assert [i["critical"] for i in up] == [True, False] and all(i["this_week"] for i in up)
        assert set(up[0]) == {
            "date",
            "case",
            "court_no",
            "item_no",
            "critical",
            "this_week",
            # design next-date-direct, decision 10
            "basis",
            "approximate",
            "basis_words",
            "order_date",
        }
        assert up[0]["basis"] == "court" and up[0]["approximate"] is False
        assert len(_me(s, world, "edu_off2", config=ReportConfig(list_size=1))["upcoming"]) == 1
        # another department's officer sees none of these
        assert _me(s, world, "health_off")["upcoming"] == []


def test_attention_order_and_limits(world):
    with world.Session() as s:
        old = _sent(s, world, -5, ago_hours=200)
        recent = _sent(s, world, -1, ago_hours=200)
        confirm_case = _sent(s, world, None, ago_hours=300)  # received 12.5 days ago: not "received" now
        _enter_item(s, confirm_case)
        due = _sent(s, world, 1, ago_hours=200)
        later = _sent(s, world, 20, ago_hours=5)  # due far ahead, received 5 hours ago
        newest = _sent(s, world, None, ago_hours=1)
        _sent(s, world, 25, ago_hours=24 * 8)  # received 8 days ago: not listed
        att = _me(s, world, "edu_off2")["attention"]
        assert [(i["kind"], i["case"]["id"]) for i in att] == [
            ("overdue_action", old.id),
            ("overdue_action", recent.id),
            ("confirm_next_date", confirm_case.id),
            ("due_soon", due.id),
            ("file_received", newest.id),
            ("file_received", later.id),
        ]
        assert att[0]["overdue_days"] == 5 and att[0]["detail"] == "Overdue 5 days"
        assert att[0]["title"] == "Parawise comments" and att[0]["date"] == today() - timedelta(days=5)
        assert att[1]["detail"] == "Overdue 1 day"
        assert att[2]["next_date_id"] is None and att[2]["date"] == today() + timedelta(days=29)
        assert att[2]["title"] == "Next date to enter" and att[2]["detail"] == "The order gives no clear date"
        assert att[2]["pending_action"] is None
        assert att[3]["detail"] == "Due tomorrow" and att[3]["overdue_days"] == 0
        sender = world.user(s, "edu_off1").full_name
        assert att[4]["detail"].startswith(f"From {sender}")
        for n in (1, 2, 3, 5):
            cut = _me(s, world, "edu_off2", config=ReportConfig(list_size=n))["attention"]
            assert [i["case"]["id"] for i in cut] == [i["case"]["id"] for i in att[:n]]
        # the person who sent the files does not see them as received (only the next date of a case allotted to
        # them, which they may review too); another department sees nothing
        off1 = _me(s, world, "edu_off1")["attention"]
        assert [(i["kind"], i["case"]["id"]) for i in off1] == [("confirm_next_date", confirm_case.id)]
        assert _me(s, world, "health_off")["attention"] == []


def test_headline_hides_merged_and_unseen_cases(world):
    with world.Session() as s:
        gone = _sent(s, world, -2, hearing=1)
        keep = _sent(s, world, None)
        gone.merged_into_case_id = keep.id
        s.flush()
        me = _me(s, world, "edu_off2")
        assert me["headline"]["overdue_actions"]["total"] == 0
        assert me["headline"]["files_with_me"]["total"] == 1
        assert me["headline"]["hearings_week"]["total"] == 0
        assert gone.id not in {i["case"]["id"] for i in me["attention"] + me["upcoming"]}
        # a State-wide reader without personal work: zeros and empty lists
        state = _me(s, world, "oversight")
        assert state["upcoming"] == [] and state["attention"] == []
        assert state["headline"]["files_with_me"] == {"total": 0, "due_today": 0}
        assert state["headline"]["to_claim"] is None


def test_existing_personal_fields_are_unchanged(world):
    with world.Session() as s:
        _sent(s, world, -1, hearing=2)
        me = _me(s, world, "edu_off2")
        assert set(me) == {
            "generated_at",
            "cases",
            "files",
            "alerts",
            "hearings",
            "drafts",
            "headline",
            "upcoming",
            "attention",
        }
        assert me["files"]["held"] == 1 and me["files"]["overdue"] == 1 and me["hearings"]["total"] == 1


def test_the_headline_writes_nothing(world):
    with world.Session() as s:
        _sent(s, world, -1, hearing=2)
        nd_case = _sent(s, world, None)
        _enter_item(s, nd_case)
        s.commit()
        before = row_counts(s)
        for key in ("edu_off2", "edu_admin", "oversight", "health_off"):
            _me(s, world, key)
        assert not s.new and not s.dirty and not s.deleted
        assert row_counts(s) == before
        assert (
            s.execute(sa.text("select count(*) from audit_log where action like 'dashboard%'")).scalar() == 0
        )


def test_the_api_answers_the_headline(world):
    from fastapi.testclient import TestClient

    from aslms.api.main import create_app
    from aslms.core.config import Settings
    from tests.db.workflow_support import login

    with world.Session() as s:
        _sent(s, world, -2, hearing=1)
        s.commit()
    settings = Settings(
        _env_file=None,
        aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters",
        aslms_access_token_minutes=5,
    )
    with TestClient(create_app(settings, world.Session)) as api:
        body = api.get("/dashboard/me", headers=login(api, "edu_off2")).json()
        mine = api.get("/inbox/mine/counts", headers=login(api, "edu_off2")).json()
    assert body["headline"]["files_with_me"]["total"] == mine["files"] == 1
    assert body["headline"]["overdue_actions"] == {"total": 1, "oldest_days": 2}
    assert body["headline"]["to_claim"] is None
    assert [i["kind"] for i in body["attention"]] == ["overdue_action"]
    assert body["upcoming"][0]["critical"] is True


# ------------------------------------------------------------------------ design portal-ui-polish, decision 13


def test_attention_lists_a_confirm_case_once(world):
    """A case with a next date to enter and a file received within 7 days gives one `confirm_next_date` row
    and no `file_received` row."""
    with world.Session() as s:
        case = _sent(s, world, None, ago_hours=2)
        _enter_item(s, case)
        att = [(i["kind"], i["case"]["id"]) for i in _me(s, world, "edu_off2")["attention"]]
        assert att == [("confirm_next_date", case.id)]


def test_attention_keeps_overdue_and_confirm_on_one_case(world):
    """An overdue file action and a next date to enter on the same case are two things to do: both stay; the
    file received on it gives way."""
    with world.Session() as s:
        case = _sent(s, world, -2, ago_hours=2)
        _enter_item(s, case)
        att = [(i["kind"], i["case"]["id"]) for i in _me(s, world, "edu_off2")["attention"]]
        assert att == [("overdue_action", case.id), ("confirm_next_date", case.id)]
