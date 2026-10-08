"""The alert, calendar and preference endpoints end to end (design alerts-notifications, "API" tests): 401
without a token; the list holds only the caller's own notifications and loses a case whose visibility was
lost; acknowledge by a non-recipient of another department → 404, by a referral reviewer without a working
basis → 404, by a recipient denied the function → 403, twice → 409, with one audit row; `POST /alerts/read`
touches only own rows; the case tab; the calendar's range, the State-wide reader with and without `office`;
preferences: defaults, SMS → 422, in-app off → 422, a change → audit row with before and after; the
document rule: a `new_document` alert is read only with its document (case tab, by reference, timeline,
list and counts); the office rule: an alert addressed to another department is hidden from the case's
owner in the case tab and 404 by reference, acknowledge and done, while its recipient and the State-wide
reader see it."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.documents import Document, Visibility
from aslms.domain.events import AuditLog, EventType
from aslms.domain.org import PermissionEffect
from aslms.domain.reference import AlertKind, Permission
from aslms.services import access, alerts
from aslms.services import alert_rules as rules
from aslms.services import ownership as own
from tests import samplefiles as sf
from tests.db import alerts_support as h
from tests.db import docs_support as ds
from tests.db.auth_support import bearer
from tests.db.world import PW, USERS, make_case

NOW = h.now_utc()
TODAY = rules.today_ist(NOW)


def d(n: int):
    return TODAY + timedelta(days=n)


@pytest.fixture()
def api(world):
    settings = Settings(
        _env_file=None,
        aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters",
        aslms_access_token_minutes=5,
    )
    app = create_app(settings, world.Session)
    with TestClient(app) as client:
        yield client


def login(api: TestClient, key: str) -> dict:
    return bearer(api, USERS[key][0], PW)


@pytest.fixture()
def alerted(world):
    """An EDU case allotted to off1 with a hearing in three days (one high alert to off1) and a HEALTH case
    allotted to the HEALTH officer with a hearing tomorrow (one alert to them; within the 48-hour critical
    window at any time of day, which a hearing in two days is not before the sitting time)."""
    with world.Session() as s:
        edu_case = make_case(s, next_hearing=d(3))
        h.claim(s, world, "edu_admin", edu_case, officer_user_id=world.users["edu_off1"].id)
        health_case = make_case(s, next_hearing=d(1))
        h.claim(s, world, "health_admin", health_case, officer_user_id=world.users["health_off"].id)
        s.commit()
        alerts.sweep_dates(s, now=NOW)
        s.commit()
        (edu_alert,) = h.alerts_of(s, edu_case)
        (health_alert,) = h.alerts_of(s, health_case)
        return {
            "edu_case": str(edu_case.id),
            "edu_case_ref": edu_case.ref_no.replace("/", "-"),
            "edu_alert": str(edu_alert.id),
            "edu_alert_ref": edu_alert.ref_no.replace("/", "-"),
            "health_case": str(health_case.id),
            "health_alert": str(health_alert.id),
        }


# ------------------------------------------------------------------------------------------------ list / counts / detail


def test_list_is_own_notifications_only(api, world, alerted):
    assert api.get("/alerts").status_code == 401
    off1 = login(api, "edu_off1")
    r = api.get("/alerts", headers=off1)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1 and [i["id"] for i in body["items"]] == [alerted["edu_alert"]]
    item = body["items"][0]
    assert (
        item["kind"] == "hearing_due" and item["kind_label"] == "Hearing due" and item["severity"] == "high"
    )
    assert item["case"]["id"] == alerted["edu_case"] and item["read_at"] is None and item["notified_at"]
    assert item["ref_no"].startswith("ASLMS/GOA/ALR/")
    counts = api.get("/alerts/counts", headers=off1).json()
    assert counts == {"unread": 1, "open": {"critical": 0, "high": 1, "normal": 0}}
    # the department admin was not a recipient (an officer holds the case): nothing in their list
    assert api.get("/alerts", headers=login(api, "edu_admin")).json()["total"] == 0
    # filters
    assert api.get("/alerts?kind=new_order", headers=off1).json()["total"] == 0
    assert api.get("/alerts?severity=high&unread=true", headers=off1).json()["total"] == 1
    assert api.get(f"/alerts?case={alerted['edu_case_ref']}", headers=off1).json()["total"] == 1
    assert api.get("/alerts?case=ASLMS-GOA-CASE-1999-999999", headers=off1).json()["total"] == 0
    assert api.get("/alerts?kind=nonsense", headers=off1).status_code == 400
    # detail by id and by ref_no; the other department's alert answers 404
    r = api.get(f"/alerts/{alerted['edu_alert_ref']}", headers=off1)
    assert r.status_code == 200 and r.json()["recipients_count"] == 1
    assert api.get(f"/alerts/{alerted['health_alert']}", headers=off1).status_code == 404
    assert api.get("/alerts/ASLMS-GOA-ALR-2026-999999", headers=off1).status_code == 404
    # a standing counsel has no read function at all → 403; the auditor (State-wide) has no notifications
    assert api.get("/alerts", headers=login(api, "edu_auditor")).json()["total"] == 0


def test_lost_visibility_drops_the_alert_from_the_list(api, world, alerted):
    off1 = login(api, "edu_off1")
    assert api.get("/alerts", headers=off1).json()["total"] == 1
    with world.Session() as s:
        actor, off2 = world.actor(s, "edu_off2")
        own.take_over(s, actor, off2, s.get(alerts.Case, alerted["edu_case"]), reason="leave")
        s.commit()
        alerts.scan_events(s, now=h.now_utc())
        s.commit()
    body = api.get("/alerts", headers=off1).json()
    # the hearing alert of a case off1 no longer sees is gone; the take-over notice is there, and (design
    # custody-workflow, decision 23b) the "file taken back" notice of the custody leg the take-over wrote
    assert sorted(i["kind"] for i in body["items"]) == ["ownership", "workflow"]
    taken = next(i for i in body["items"] if i["kind"] == "ownership")
    assert taken["data"]["event"] == "case_taken_over"
    recalled = next(i for i in body["items"] if i["kind"] == "workflow")
    assert (
        recalled["data"]["event"] == "file_recalled"
        and api.get(f"/alerts/{recalled['id']}", headers=off1).status_code == 200
    )
    assert api.get(f"/alerts/{alerted['edu_alert']}", headers=off1).status_code == 404
    r = api.post(f"/alerts/{taken['id']}/acknowledge", json={}, headers=off1)
    assert r.status_code == 200 and r.json()["status"] == "acknowledged"


# ------------------------------------------------------------------------------------------------ acknowledge / done


def test_acknowledge_rules_and_audit(api, world, alerted):
    alr = alerted["edu_alert"]
    # a non-recipient officer of another department → 404; a referral reviewer without a working basis → 404
    assert (
        api.post(f"/alerts/{alr}/acknowledge", json={}, headers=login(api, "health_off")).status_code == 404
    )
    assert (
        api.post(f"/alerts/{alr}/acknowledge", json={}, headers=login(api, "edu_reviewer")).status_code == 404
    )
    # a recipient denied the function → 403
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        access.set_override(
            s, actor, root, world.user(s, "edu_off1"), Permission.ALERTS_ACKNOWLEDGE, PermissionEffect.DENY
        )
        s.commit()
    off1 = login(api, "edu_off1")
    assert api.post(f"/alerts/{alr}/acknowledge", json={}, headers=off1).status_code == 403
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        access.set_override(s, actor, root, world.user(s, "edu_off1"), Permission.ALERTS_ACKNOWLEDGE, None)
        s.commit()
    assert api.post(f"/alerts/{alr}/acknowledge", json={"note": "x" * 501}, headers=off1).status_code == 422
    r = api.post(f"/alerts/{alr}/acknowledge", json={"note": "seen, counsel briefed"}, headers=off1)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "acknowledged" and body["acknowledged_by"]["full_name"] == "Edu Off1"
    assert body["acknowledged_at"]
    # twice → 409 not_open; the department admin (works on the case) may mark it done; done twice → 409
    r = api.post(f"/alerts/{alr}/acknowledge", json={}, headers=off1)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_open"
    admin = login(api, "edu_admin")
    r = api.post(f"/alerts/{alr}/done", json={"note": "listed and argued"}, headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "done" and r.json()["closed_at"]
    r = api.post(f"/alerts/{alr}/done", json={}, headers=admin)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "closed"
    assert api.post(f"/alerts/{alr}/acknowledge", json={}, headers=admin).status_code == 409
    with world.Session() as s:
        rows = s.scalars(
            sa.select(AuditLog)
            .where(AuditLog.entity_type == "alert", AuditLog.entity_id == alerted["edu_alert"])
            .order_by(AuditLog.created_at, AuditLog.id)
        ).all()
        assert [r.action for r in rows] == ["alert.acknowledged", "alert.done"]
        assert rows[0].before["status"] == "open" and rows[0].after["status"] == "acknowledged"
        assert (
            rows[0].after["note"] == "seen, counsel briefed" and str(rows[0].case_id) == alerted["edu_case"]
        )
        assert rows[1].after["status"] == "done" and rows[1].after["closed_at"]
    # closed alerts leave the default list but answer `status=all`
    assert api.get("/alerts", headers=off1).json()["total"] == 0
    assert api.get("/alerts?status=all", headers=off1).json()["total"] == 1
    assert api.get("/alerts?status=done", headers=off1).json()["total"] == 1


def test_mark_read_touches_only_own_rows(api, world, alerted):
    off1, hoff = login(api, "edu_off1"), login(api, "health_off")
    # off1 asks to mark the HEALTH officer's alert read: nothing happens to it
    r = api.post("/alerts/read", json={"alert_ids": [alerted["health_alert"]]}, headers=off1)
    assert r.status_code == 200 and r.json() == {"marked": 0}
    assert api.get("/alerts/counts", headers=hoff).json()["unread"] == 1
    r = api.post("/alerts/read", json={"alert_ids": [alerted["edu_alert"]]}, headers=off1)
    assert r.json() == {"marked": 1}
    assert api.get("/alerts/counts", headers=off1).json()["unread"] == 0
    assert api.get("/alerts", headers=off1).json()["items"][0]["read_at"]
    assert api.post("/alerts/read", json={"all": True}, headers=hoff).json() == {"marked": 1}
    assert api.post("/alerts/read", json={}, headers=hoff).json() == {"marked": 0}


# ------------------------------------------------------------------------------------------------ case tab


def test_case_alerts_tab(api, world, alerted):
    ref = alerted["edu_case_ref"]
    # the officer and the department admin work on the case; the auditor reads State-wide
    for key in ("edu_off1", "edu_admin", "edu_auditor"):
        r = api.get(f"/cases/{ref}/alerts", headers=login(api, key))
        assert r.status_code == 200 and r.json()["total"] == 1, key
    # a HEALTH user cannot see the case at all
    assert api.get(f"/cases/{ref}/alerts", headers=login(api, "health_off")).status_code == 404
    # a department that sees the case only through a recommendation gets an empty list
    with world.Session() as s:
        h.recommend(s, world, s.get(alerts.Case, alerted["edu_case"]), "HEALTH")
        s.commit()
    r = api.get(f"/cases/{ref}/alerts", headers=login(api, "health_admin"))
    assert r.status_code == 200 and r.json() == {"items": [], "total": 0}


# ------------------------------------------------------------------------------------------------ calendar


def test_calendar(api, world, alerted):
    off1 = login(api, "edu_off1")
    r = api.get("/calendar", headers=off1)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["case"]["id"] == alerted["edu_case"]
    assert items[0]["source"] == "current_status" and items[0]["this_week"] is True
    assert items[0]["critical"] is False and items[0]["date"] == str(d(3))
    assert api.get(f"/calendar?from={d(0)}&to={d(70)}", headers=off1).status_code == 422
    assert api.get(f"/calendar?from={d(5)}&to={d(1)}", headers=off1).status_code == 422
    assert api.get(f"/calendar?from={d(4)}&to={d(10)}", headers=off1).json()["items"] == []
    assert api.get("/calendar?office=HEALTH", headers=off1).status_code == 403
    # a State-wide reader needs an office; with one, that department's owned cases' hearings
    oversight = login(api, "oversight")
    assert api.get("/calendar", headers=oversight).json()["items"] == []
    health = api.get("/calendar?office=HEALTH", headers=oversight).json()["items"]
    assert [i["case"]["id"] for i in health] == [alerted["health_case"]] and health[0]["critical"] is True
    assert api.get("/calendar?office=NOPE", headers=oversight).status_code == 422
    # a HEALTH officer does not see EDU's hearing
    assert (
        api.get("/calendar", headers=login(api, "health_off")).json()["items"][0]["case"]["id"]
        == alerted["health_case"]
    )


# ------------------------------------------------------------------------------------------------ preferences


def test_notification_preferences(api, world):
    off1 = login(api, "edu_off1")
    r = api.get("/me/notification-preferences", headers=off1)
    assert r.status_code == 200 and r.json() == {
        "in_app": {"enabled": True},
        "email": {"enabled": True, "digest": "daily", "critical_only": False},
        "sms": {"available": False},
    }
    r = api.put("/me/notification-preferences", json={"sms": {"enabled": True}}, headers=off1)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "channel_not_available"
    r = api.put("/me/notification-preferences", json={"in_app": {"enabled": False}}, headers=off1)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "in_app_required"
    r = api.put(
        "/me/notification-preferences",
        json={"email": {"digest": "none", "critical_only": True}},
        headers=off1,
    )
    assert r.status_code == 200 and r.json()["email"] == {
        "enabled": True,
        "digest": "none",
        "critical_only": True,
    }
    assert api.get("/me/notification-preferences", headers=off1).json()["email"]["digest"] == "none"
    assert api.get("/me/notification-preferences").status_code == 401
    with world.Session() as s:
        rows = s.scalars(
            sa.select(AuditLog).where(AuditLog.action == "notification_preferences.changed")
        ).all()
        assert len(rows) == 1 and rows[0].before["email"]["digest"] == "daily"
        assert rows[0].after["email"] == {"enabled": True, "digest": "none", "critical_only": True}
        assert str(rows[0].actor_user_id) == str(world.users["edu_off1"].id)


# ------------------------------------------------------------------------------------------------ the document rule


def _claimed_dse_case(world) -> tuple[str, str]:
    """An EDU case allotted to the DSE unit and to off1; returns (id, ref)."""
    with world.Session() as s:
        case = make_case(s)
        h.claim(s, world, "edu_admin", case, unit_code="EDU-DSE", officer_user_id=world.users["edu_off1"].id)
        s.commit()
        return str(case.id), case.ref_no.replace("/", "-")


def _new_document_alert(world, case_id: str) -> tuple[str, str]:
    """Runs the event scan; returns (document_id named by the one `new_document` alert, its ALR ref)."""
    with world.Session() as s:
        alerts.scan_events(s, now=h.now_utc())
        s.commit()
        (alert,) = h.alerts_of(s, s.get(alerts.Case, case_id), AlertKind.NEW_DOCUMENT)
        return alert.data["document_id"], alert.ref_no.replace("/", "-")


def _new_document_rows(page: dict) -> list[dict]:
    return [i for i in page["items"] if i.get("kind") == "new_document"]


def _alert_raised_rows(timeline: dict) -> list[dict]:
    return [
        i
        for i in timeline["items"]
        if i["type"] == "alert_raised" and i["payload"].get("kind") == "new_document"
    ]


def test_new_document_alert_is_hidden_with_its_document(world, tmp_path):
    """Review of 2026-10-06 (deviation 12): the directorate uploads a `private_to_office` document; the
    department officer who works on the case cannot see the document, so they get neither the alert on the
    case tab, nor by reference, nor its `alert_raised` row on the timeline — none of the three reads names the
    document. The directorate's own user and the department admin (department-wide) see all three; the
    State-wide auditor sees every document (documents-uploads, decision 7) and so the tab and timeline rows,
    and 404 by reference as before (not a recipient, not working on the case)."""
    api = ds.make_api(world, tmp_path)
    case_id, ref = _claimed_dse_case(world)
    dse = ds.login(api, "dse_user")
    r = ds.upload(
        api,
        dse,
        case_id,
        sf.text_pdf(["Private affidavit of the directorate"]),
        visibility="private_to_office",
        doc_type="affidavit",
        description="Affidavit of the directorate",
    )
    assert r.status_code == 201, r.text
    doc_id, alr = _new_document_alert(world, case_id)
    assert doc_id == r.json()["id"]
    off1 = ds.login(api, "edu_off1")
    tab = api.get(f"/cases/{ref}/alerts?limit=100", headers=off1)
    assert tab.status_code == 200 and _new_document_rows(tab.json()) == []
    assert api.get(f"/alerts/{alr}", headers=off1).status_code == 404
    timeline = api.get(f"/cases/{ref}/timeline?limit=100", headers=off1)
    assert timeline.status_code == 200 and _alert_raised_rows(timeline.json()) == []
    assert doc_id not in tab.text + timeline.text
    assert "Affidavit" not in tab.text + timeline.text
    # the other alert of the case (the allotment notice) stays visible to the officer: the rule is per alert
    assert tab.json()["total"] == 1
    for key, by_ref in (("dse_user", 200), ("edu_admin", 200), ("edu_auditor", 404)):
        hdr = ds.login(api, key)
        (row,) = _new_document_rows(api.get(f"/cases/{ref}/alerts?limit=100", headers=hdr).json())
        assert row["ref_no"].replace("/", "-") == alr, key
        assert api.get(f"/alerts/{alr}", headers=hdr).status_code == by_ref, key
        (row,) = _alert_raised_rows(api.get(f"/cases/{ref}/timeline?limit=100", headers=hdr).json())
        assert row["payload"]["title"].startswith("New Affidavit"), key


def test_list_and_counts_drop_a_new_document_alert_whose_document_is_hidden(world, tmp_path):
    """The officer was notified of a `case_scope` document; once the document is no longer visible to them
    the notification leaves `GET /alerts`, `/alerts/counts` and `/alerts/{alr}` (deviation 12)."""
    api = ds.make_api(world, tmp_path)
    case_id, ref = _claimed_dse_case(world)
    r = ds.upload(
        api,
        ds.login(api, "dse_user"),
        case_id,
        sf.text_pdf(["Shared affidavit"]),
        visibility="case_scope",
        doc_type="affidavit",
    )
    assert r.status_code == 201, r.text
    doc_id, alr = _new_document_alert(world, case_id)
    off1 = ds.login(api, "edu_off1")
    assert api.get("/alerts?kind=new_document", headers=off1).json()["total"] == 1
    assert api.get(f"/alerts/{alr}", headers=off1).status_code == 200
    unread_before = api.get("/alerts/counts", headers=off1).json()["unread"]
    with world.Session() as s:
        d = s.get(Document, uuid.UUID(doc_id))
        d.visibility = Visibility.PRIVATE_TO_OFFICE
        d.sourcetrace_status = "not_applicable"  # ck_documents_private_not_sent (sourcetrace-connector)
        s.commit()
    assert api.get("/alerts?kind=new_document", headers=off1).json()["total"] == 0
    assert api.get(f"/alerts/{alr}", headers=off1).status_code == 404
    assert api.get("/alerts/counts", headers=off1).json()["unread"] == unread_before - 1
    assert api.get(f"/cases/{ref}/alerts", headers=off1).json()["total"] == 1  # the allotment notice only


# ------------------------------------------------------------------------------------ the addressed office


def _edu_recommendation_alert(world, case_id: str) -> str:
    """A strong EDU recommendation on an already claimed case, scanned into a `recommendation` alert
    addressed to EDU."""
    with world.Session() as s:
        case = s.get(alerts.Case, case_id)
        rec = h.recommend(s, world, case, "EDU")
        h.event(
            s,
            case,
            EventType.RECOMMENDATION_MADE,
            {
                "recommendation_id": str(rec.id),
                "office_code": "EDU",
                "score": float(rec.score),
                "band": rec.band.value,
            },
            scoped=True,
        )
        s.commit()
        alerts.scan_events(s, now=NOW)
        s.commit()
        (rec_alert,) = h.alerts_of(s, case, AlertKind.RECOMMENDATION)
        assert str(rec_alert.office_id) == str(world.offices["EDU"].id)
        return str(rec_alert.id)


def test_alert_addressed_to_another_department_is_hidden_from_the_owner(api, world, alerted):
    """HEALTH claimed the case; the scan raises a `recommendation` alert addressed to EDU. The HEALTH
    officer works on the case but neither reads nor acts on EDU's alert; the EDU admin (a recipient) and
    the auditor (State-wide) do; HEALTH's own hearing alert is unaffected."""
    rec_alert = _edu_recommendation_alert(world, alerted["health_case"])
    hoff = login(api, "health_off")
    r = api.get(f"/cases/{alerted['health_case']}/alerts", headers=hoff)
    assert r.status_code == 200
    seen = {i["id"]: i["kind"] for i in r.json()["items"]}
    # the scan also raised HEALTH's own `allotted` notice from the fixture's events; EDU's is not there
    assert alerted["health_alert"] in seen and rec_alert not in seen
    assert "recommendation" not in seen.values() and r.json()["total"] == len(seen)
    assert api.get(f"/alerts/{rec_alert}", headers=hoff).status_code == 404
    assert api.post(f"/alerts/{rec_alert}/acknowledge", json={}, headers=hoff).status_code == 404
    assert api.post(f"/alerts/{rec_alert}/done", json={}, headers=hoff).status_code == 404
    # the HEALTH admin works on the case too and is kept out the same way
    hadmin = login(api, "health_admin")
    r = api.get(f"/cases/{alerted['health_case']}/alerts", headers=hadmin)
    assert rec_alert not in {i["id"] for i in r.json()["items"]}
    assert api.post(f"/alerts/{rec_alert}/done", json={}, headers=hadmin).status_code == 404
    # the auditor reads State-wide: HEALTH's alerts and EDU's recommendation
    r = api.get(f"/cases/{alerted['health_case']}/alerts", headers=login(api, "edu_auditor"))
    assert r.status_code == 200 and r.json()["total"] == len(seen) + 1
    assert rec_alert in {i["id"] for i in r.json()["items"]}
    # the EDU admin was notified: reads it by reference, finds it in the list, and may close it
    eadmin = login(api, "edu_admin")
    r = api.get(f"/alerts/{rec_alert}", headers=eadmin)
    assert r.status_code == 200 and r.json()["kind"] == "recommendation" and r.json()["status"] == "open"
    assert rec_alert in {i["id"] for i in api.get("/alerts", headers=eadmin).json()["items"]}
    assert api.post(f"/alerts/{rec_alert}/done", json={}, headers=eadmin).status_code == 200
    # HEALTH's own alert stays readable and actionable by its officer
    assert api.get(f"/alerts/{alerted['health_alert']}", headers=hoff).status_code == 200
    assert (
        api.post(f"/alerts/{alerted['health_alert']}/acknowledge", json={}, headers=hoff).status_code == 200
    )
