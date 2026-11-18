"""State Insights, the service (design `state-insights`, "Tests", database, `test_insights.py`): cross-filtering with
hand-counted numbers, the headline, State cases only, interlocutory applications, the three department bands, the
scopes and their visibility, the trend and outcomes, the accountability section, the case list's sorts and who has
each case, the readings waiting, the filters and chips, and the timeout. Nothing here writes."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa

from aslms.core.clock import today_ist
from aslms.domain.cases import CaseStatus
from aslms.domain.org import PermissionEffect
from aslms.domain.ownership import Recommendation
from aslms.domain.reference import Permission, Role
from aslms.services import insights
from aslms.services import insights_filters as F
from aslms.services import insights_scope as sc
from aslms.services.access import Forbidden
from tests.db import insights_support as ins
from tests.db.alerts_support import recommend
from tests.db.report_support import claim, compliance_alert, override, row_counts, set_due
from tests.db.workflow_support import send
from tests.db.world import add_membership

STATE = ("THE STATE OF ASSAM AND 2 ORS",)


def _view(s, user, scope="state", department=None, **params):
    scope_ = sc.resolve(s, user, scope, department)
    f = F.parse(s, scope_, today=today_ist(), **params)
    return insights.overview(s, user, f, scope_), scope_, f


def _world(s, world):
    """Seven cases (decision 22's fixture): the counts below are worked out by hand."""
    today = today_ist()
    c = {}
    c["claimed"] = ins.case(
        s, respondents=(*STATE, "THE SECRETARY, EDUCATION DEPARTMENT"), registration_date=date(2018, 1, 1)
    )
    claim(s, world, c["claimed"], officer="edu_off1")
    c["likely"] = ins.case(
        s,
        respondents=STATE,
        next_hearing=today + timedelta(days=3),
        registration_date=today - timedelta(days=10),
    )
    recommend(s, world, c["likely"], "EDU")
    c["contempt"] = ins.case(s, type_code=142, respondents=STATE, category=ins.CONTEMPT_CATEGORY)
    c["private"] = ins.case(s, respondents=("M/S PRIVATE LTD",))
    c["named"] = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
    c["ia"] = ins.case(s, type_code=220, respondents=STATE)
    ins.main_matter(s, c["ia"], c["claimed"])
    c["disposed"] = ins.case(
        s, respondents=STATE, status=CaseStatus.DISPOSED, disposal_date=today, disposal_type="Dismissed"
    )
    ins.build(s, *c.values())
    return c


def test_headline_counts_all_filters(world):
    with world.Session() as s:
        _world(s, world)
        out, _, _ = _view(s, world.user(s, "root"))
        h = out["headline"]
        assert (
            h["cases"],
            h["state_cases"],
            h["contempt"],
            h["over_5_years"],
            h["hearing_7_days"],
            h["not_claimed"],
        ) == (
            4,
            4,
            1,
            1,
            1,
            3,
        )
        out, _, _ = _view(s, world.user(s, "root"), kind="contempt")
        assert out["headline"]["cases"] == 1 and out["headline"]["contempt"] == 1
        assert [c["label"] for c in out["chips"]] == ["Kind: Contempt"]
        s.rollback()


def test_state_only_default_and_switch(world):
    with world.Session() as s:
        _world(s, world)
        out, _, f = _view(s, world.user(s, "root"))
        assert f.state_only and out["headline"]["cases"] == 4
        out, _, _ = _view(s, world.user(s, "root"), state_only="false")
        assert out["headline"]["cases"] == 5 and out["headline"]["state_cases"] == 4
        assert "All cases" in out["coverage"]["line"]
        s.rollback()


def test_cross_filter_each_chart_ignores_own_dimension(world):
    with world.Session() as s:
        _world(s, world)
        out, _, _ = _view(s, world.user(s, "root"), kind="contempt")
        kinds = {r["key"]: r["total"] for r in out["kind_by_age"]["rows"]}
        assert kinds["writ"] == 3 and kinds["contempt"] == 1  # the kind chart ignores the kind filter
        nxt = {r["key"]: r["count"] for r in out["next_hearing"]}
        assert nxt["none"] == 1 and nxt["days_2_7"] == 0  # every other chart applies it
        out, _, _ = _view(s, world.user(s, "root"), next="days_2_7")
        nxt = {r["key"]: r["count"] for r in out["next_hearing"]}
        assert nxt["days_2_7"] == 1 and nxt["none"] == 3 and out["headline"]["cases"] == 1
        ages = {r["key"]: r["count"] for r in out["age"]}
        assert ages["age_lt_1"] == 1 and sum(ages.values()) == 1
        out, _, _ = _view(s, world.user(s, "root"), age="over_5")
        assert out["headline"]["cases"] == 1
        assert {r["key"]: r["count"] for r in out["age"]}["age_5_10"] == 1
        filed = {r["key"]: r["count"] for r in out["filed"]}
        assert filed["earlier"] == 1 or filed[str(2018)] == 1
        subjects = {r["key"]: r["count"] for r in _view(s, world.user(s, "root"))[0]["subjects"]}
        assert subjects["service_state"] == 3 and subjects["contempt"] == 1
        s.rollback()


def test_ia_out_by_default_inside_main_and_switch(world):
    with world.Session() as s:
        c = _world(s, world)
        out, scope, f = _view(s, world.user(s, "root"))
        assert (
            out["headline"]["applications_inside"] == 1 and out["headline"]["applications_main_not_held"] == 0
        )
        assert "inside their main case" in out["coverage"]["line"]
        page = insights.case_page(s, world.user(s, "root"), f, scope)
        row = next(i for i in page["items"] if i["case"]["id"] == c["claimed"].id)
        assert row["applications_pending"] == 1
        out, _, _ = _view(s, world.user(s, "root"), include_ia="true")
        assert out["headline"]["cases"] == 5 and out["headline"]["applications_inside"] == 0
        s.rollback()


def test_department_bands_disjoint_never_summed(world):
    with world.Session() as s:
        _world(s, world)
        out, _, _ = _view(s, world.user(s, "root"))
        edu = next(d for d in out["departments"] if d["code"] == "EDU")
        assert (edu["claimed"], edu["likely"], edu["named"]) == (
            1,
            1,
            1,
        )  # the claimed case is also named: once
        assert "total" not in edu
        card = next(d for d in out["accountability"]["scorecard"] if d["code"] == "EDU")
        assert card["claimed"] == 1 and card["named_only"] == 1 and "total" not in card
        out, _, _ = _view(s, world.user(s, "root"), dept="EDU", band="likely")
        assert out["headline"]["cases"] == 1
        assert [ch["label"] for ch in out["chips"]] == ["Education · Recommended, Not Claimed"]
        edu = next(d for d in out["departments"] if d["code"] == "EDU")
        assert (edu["claimed"], edu["likely"], edu["named"]) == (
            1,
            1,
            1,
        )  # its own chart ignores the dept filter
        s.rollback()


def test_department_scope_bands_and_member_visibility(world):
    with world.Session() as s:
        c = _world(s, world)
        other = ins.case(s, respondents=STATE)
        claim(s, world, other, by="health_admin")
        ins.build(s, other)
        out, scope, f = _view(s, world.user(s, "edu_admin"), "department", "EDU")
        assert out["headline"]["cases"] == 3  # claimed, likely, named; never the plain pool or HEALTH's case
        assert out["department_bands"] == {"claimed": 1, "likely": 1, "named": 1}
        assert out["departments"] is None and out["accountability"]["scorecard"] is None
        ids = {i["case"]["id"] for i in insights.case_page(s, world.user(s, "edu_admin"), f, scope)["items"]}
        assert ids == {c["claimed"].id, c["likely"].id, c["named"].id}
        with pytest.raises(Forbidden) as exc:
            sc.resolve(s, world.user(s, "edu_admin"), "department", "HEALTH")
        assert exc.value.code == "department_not_yours"
        with pytest.raises(Forbidden) as exc:
            sc.resolve(s, world.user(s, "edu_off1"), "department", "EDU")
        assert exc.value.code == "no_insights_function"
        override(s, world, "edu_off1", Permission.INSIGHTS_DEPARTMENT, PermissionEffect.GRANT)
        out, _, _ = _view(s, world.user(s, "edu_off1"), "department", "EDU")
        assert out["headline"]["cases"] == 1  # an officer sees only what is assigned to them
        s.rollback()


def test_department_switch_several_memberships(world):
    with world.Session() as s:
        admin = world.user(s, "edu_admin")
        add_membership(s, admin, world.office(s, "HEALTH"), Role.DEPT_OFFICER)
        s.flush()
        assert [d["code"] for d in sc.available(s, admin)["departments"]] == [
            "EDU"
        ]  # no function in HEALTH yet
        override(
            s, world, "edu_admin", Permission.INSIGHTS_DEPARTMENT, PermissionEffect.GRANT, office="HEALTH"
        )
        av = sc.available(s, admin)
        assert av["state"] is False and [d["code"] for d in av["departments"]] == ["EDU", "HEALTH"]
        assert av["default"] == {"scope": "department", "department": "EDU"}
        assert sc.resolve(s, admin, None, None).department.code == "EDU"
        assert sc.resolve(s, admin, "department", "HEALTH").department.code == "HEALTH"
        s.rollback()


def test_state_scope_needs_state_wide_membership(world):
    with world.Session() as s:
        assert sc.resolve(s, world.user(s, "oversight"), "state", None).is_state
        with pytest.raises(Forbidden) as exc:
            sc.resolve(s, world.user(s, "edu_admin"), "state", None)
        assert exc.value.code == "no_insights_function"
        override(s, world, "edu_admin", Permission.INSIGHTS_STATE, PermissionEffect.GRANT)
        with pytest.raises(Forbidden) as exc:
            sc.resolve(s, world.user(s, "edu_admin"), "state", None)
        assert exc.value.code == "state_scope_not_state_wide"
        with pytest.raises(Forbidden) as exc:
            sc.resolve(s, world.user(s, "central_op"), "state", None)
        assert exc.value.code == "no_insights_function"
        s.rollback()


def test_state_wide_may_open_any_department_view(world):
    with world.Session() as s:
        _world(s, world)
        out, scope, _ = _view(s, world.user(s, "oversight"), "department", "EDU")
        assert scope.kind == "department" and out["headline"]["cases"] == 3
        assert out["scope"]["department"]["code"] == "EDU"
        s.rollback()


def test_trend_ignores_status_and_dates(world):
    with world.Session() as s:
        _world(s, world)
        month = today_ist().strftime("%Y-%m")
        out, _, _ = _view(
            s, world.user(s, "root"), date_of="disposal", **{"from": "2000-01-01", "to": "2000-12-31"}
        )
        assert out["headline"]["cases"] == 0
        trend = {t["month"]: t for t in out["trend"]}
        assert len(out["trend"]) == 12 and trend[month]["disposed"] == 1
        assert trend[(today_ist() - timedelta(days=10)).strftime("%Y-%m")]["registered"] >= 1
        s.rollback()


def test_outcomes_ignore_status(world):
    with world.Session() as s:
        _world(s, world)
        out, _, _ = _view(s, world.user(s, "root"))
        outcomes = {o["key"]: o["count"] for o in out["outcomes"]}
        assert outcomes["dismissed"] == 1 and sum(outcomes.values()) == 1
        out, _, _ = _view(s, world.user(s, "root"), outcome="dismissed", status="all")
        assert out["headline"]["cases"] == 1
        s.rollback()


def test_action_buckets_each_case_once(world):
    with world.Session() as s:
        _world(s, world)
        out, _, _ = _view(s, world.user(s, "root"))
        actions = {a["key"]: a["count"] for a in out["accountability"]["action"]}
        assert sum(actions.values()) == out["headline"]["cases"] == 4
        assert actions["not_claimed"] == 3 and actions["with_officer"] == 1
        labels = {a["key"]: a["label"] for a in out["accountability"]["action"]}
        assert labels["due_soon"] == "Due Soon (2 Days)"
        s.rollback()


def test_compliance_by_department_reuses_dashboard(world):
    with world.Session() as s:
        c = _world(s, world)
        compliance_alert(s, world, c["claimed"], today_ist() - timedelta(days=2))
        out, _, _ = _view(s, world.user(s, "root"))
        assert out["accountability"]["compliance"] == [
            {"code": "EDU", "name": "Education", "overdue": 1, "due_soon": 0}
        ]
        out, _, _ = _view(s, world.user(s, "root"), compliance="overdue")
        assert out["headline"]["cases"] == 1
        s.rollback()


def test_holders_click_sets_two_filters(world):
    with world.Session() as s:
        c = _world(s, world)
        send(s, world, "edu_off1", c["claimed"], "edu_off2", due_date=today_ist() + timedelta(days=5))
        set_due(s, c["claimed"], -3)
        out, _, _ = _view(s, world.user(s, "root"))
        assert out["accountability"]["holders"] == [{"code": "EDU", "name": "Education", "overdue": 1}]
        out, _, _ = _view(s, world.user(s, "root"), holder="EDU", action="overdue")
        assert out["headline"]["cases"] == 1
        assert [ch["param"] for ch in out["chips"]] == ["action", "holder"]
        s.rollback()


def test_scorecard_median_days_three_claims_minimum(world):
    with world.Session() as s:
        cases = []
        for days in (2, 4, 9):
            c = ins.case(s, respondents=STATE)
            rec = recommend(s, world, c, "HEALTH")
            s.execute(
                sa.update(Recommendation)
                .where(Recommendation.id == rec.id)
                .values(created_at=datetime.now(UTC) - timedelta(days=days))
            )
            claim(s, world, c, by="health_admin")
            cases.append(c)
        ins.build(s, *cases)
        out, _, _ = _view(s, world.user(s, "root"))
        card = {d["code"]: d for d in out["accountability"]["scorecard"]}
        assert card["HEALTH"]["median_days_to_claim"] == pytest.approx(4.0, abs=0.2)
        assert card["EDU"]["median_days_to_claim"] is None
        s.rollback()


def test_case_page_sort_orders(world):
    with world.Session() as s:
        c = _world(s, world)
        user = world.user(s, "root")
        scope = sc.resolve(s, user, "state", None)
        f = F.parse(s, scope, today=today_ist())
        page = insights.case_page(s, user, f, scope)
        ids = [i["case"]["id"] for i in page["items"]]
        assert ids[0] == c["likely"].id and page["total"] == 4 and page["page_size"] == 20
        page = insights.case_page(s, user, f, scope, sort="registered")
        assert page["items"][0]["case"]["id"] == c["claimed"].id
        with pytest.raises(F.InsightFilterError) as exc:
            insights.case_page(s, user, f, scope, sort="cnr")
        assert exc.value.code == "bad_sort"
        s.rollback()


def test_who_has_it_each_kind(world):
    with world.Session() as s:
        c = _world(s, world)
        office_held = ins.case(s, respondents=STATE)
        claim(s, world, office_held)
        scope = sc.resolve(s, world.user(s, "root"), "state", None)
        who = insights.who_has_it(
            s, [c["claimed"].id, office_held.id, c["likely"].id, c["contempt"].id], scope
        )
        assert who[c["claimed"].id]["kind"] == "officer" and who[c["claimed"].id]["text"].startswith(
            "With Edu Off1"
        )
        assert who[c["claimed"].id]["office_code"] == "EDU"
        assert who[office_held.id]["text"] == "With Education · Not Sent to an Officer"
        assert who[c["likely"].id]["text"] == "Not Claimed · Recommended to Education"
        assert who[c["contempt"].id]["text"] == "Not Claimed by Any Department"
        s.rollback()


def test_recommended_to_hidden_from_other_departments(world):
    with world.Session() as s:
        _world(s, world)
        both = ins.case(s, respondents=("THE SECRETARY, EDUCATION DEPARTMENT",))
        recommend(s, world, both, "HEALTH")
        ins.build(s, both)
        state = sc.resolve(s, world.user(s, "root"), "state", None)
        dept = sc.resolve(s, world.user(s, "edu_admin"), "department", "EDU")
        assert (
            insights.who_has_it(s, [both.id], state)[both.id]["text"] == "Not Claimed · Recommended to Health"
        )
        hidden = insights.who_has_it(s, [both.id], dept)[both.id]
        assert hidden["text"] == "Not Claimed" and hidden["recommended_to"] is None
        s.rollback()


def test_facts_waiting_counted_empty(world):
    with world.Session() as s:
        _world(s, world)
        ins.case(s, respondents=STATE)  # no fact row yet
        out, _, _ = _view(s, world.user(s, "root"))
        assert out["coverage"]["facts_waiting"] == 1 and out["headline"]["cases"] == 4
        out, _, _ = _view(s, world.user(s, "root"), state_only="false")
        assert out["headline"]["cases"] == 6
        s.rollback()


def test_filters_parse_and_errors(world):
    with world.Session() as s:
        ins.case_types(s)
        root = world.user(s, "root")
        scope = sc.resolve(s, root, "state", None)
        today = today_ist()
        bad = [
            ({"status": "open"}, "status"),
            ({"band": "likely"}, "band"),
            ({"dept": "EDU-DSE"}, "dept"),
            ({"unit": "EDU-DSE"}, "unit"),
            ({"kind": "nope"}, "kind"),
            ({"age": "old"}, "age"),
            ({"next": "soon"}, "next"),
            ({"filed": "1900"}, "filed"),
            ({"post": "king"}, "post"),
            ({"subject": "x"}, "subject"),
            ({"outcome": "won"}, "outcome"),
            ({"action": "late"}, "action"),
            ({"compliance": "x"}, "compliance"),
            ({"holder": "NOPE"}, "holder"),
            ({"from": "2026-01-01"}, "date_of"),
            ({"date_of": "registration", "from": "2026-13-01"}, "from"),
            ({"state_only": "maybe"}, "state_only"),
        ]
        for params, param in bad:
            with pytest.raises(F.InsightFilterError) as exc:
                F.parse(s, scope, today=today, **params)
            assert exc.value.code == "bad_filter" and exc.value.param == param, params
        with pytest.raises(F.InsightFilterError) as exc:
            F.parse(
                s, scope, today=today, date_of="registration", **{"from": "2026-02-01", "to": "2026-01-01"}
            )
        assert exc.value.code == "bad_dates"
        dept = sc.resolve(s, world.user(s, "edu_admin"), "department", "EDU")
        assert F.parse(s, dept, today=today, unit="EDU-DSE").unit == "EDU-DSE"
        with pytest.raises(F.InsightFilterError):
            F.parse(s, dept, today=today, unit="HEALTH")
        f = F.parse(s, scope, today=today, counsel="ga,assam", filed="earlier", dept="edu", band="named")
        assert f.counsel == "GA, ASSAM" and f.dept == "EDU"
        s.rollback()


def test_chips_labels(world):
    with world.Session() as s:
        ins.case_types(s)
        scope = sc.resolve(s, world.user(s, "root"), "state", None)
        today = today_ist()
        f = F.parse(
            s,
            scope,
            today=today,
            kind="contempt",
            age="over_5",
            next="within_7",
            filed=str(today.year),
            dept="EDU",
            post="dgp",
            subject="not_grouped",
            counsel="GA, ASSAM",
            outcome="allowed",
            action="overdue",
            compliance="due_soon",
            holder="EDU",
            date_of="registration",
            **{"from": "2026-01-01", "to": "2026-11-13"},
        )
        labels = [c["label"] for c in F.chips(s, f, today)]
        assert labels == [
            "Kind: Contempt",
            "Age: Over 5 Years",
            "Next Hearing: In the Next 7 Days",
            f"Filed: {today.year}",
            "Education",
            "Post: Director General of Police",
            "Subject: Not Grouped",
            "Counsel Code: GA, ASSAM",
            "Outcome: Allowed",
            "Action: Overdue",
            "Compliance: Due Soon",
            "Holder: Education",
            "Registered: 1 Jan 2026 to 13 Nov 2026",
        ]
        s.rollback()


def test_reads_write_nothing(world):
    with world.Session() as s:
        _world(s, world)
        s.commit()
    with world.Session() as s:
        before = row_counts(s)
        _view(s, world.user(s, "root"))
        scope = sc.resolve(s, world.user(s, "root"), "state", None)
        insights.case_page(s, world.user(s, "root"), F.parse(s, scope, today=today_ist()), scope)
        assert row_counts(s) == before
        assert not s.new and not s.dirty
        s.rollback()


def test_timeout_503(world, monkeypatch):
    with world.Session() as s:
        ins.case_types(s)
        user = world.user(s, "root")
        scope = sc.resolve(s, user, "state", None)
        f = F.parse(s, scope, today=today_ist())
        monkeypatch.setattr(insights, "_union", lambda b, scope, today: sa.select(sa.func.pg_sleep(3)))
        cfg = insights.InsightsConfig(statement_timeout_seconds=1)
        with pytest.raises(insights.InsightsTimeout):
            insights.overview(s, user, f, scope, cfg=cfg)
        s.rollback()


def test_refresh_then_counts_follow_a_new_claim(world):
    """The live columns are never stale: a claim counts at once, without a fact refresh."""
    with world.Session() as s:
        c = _world(s, world)
        claim(s, world, c["named"])
        out, _, _ = _view(s, world.user(s, "root"))
        edu = next(d for d in out["departments"] if d["code"] == "EDU")
        assert (edu["claimed"], edu["named"]) == (2, 0)
        s.rollback()
