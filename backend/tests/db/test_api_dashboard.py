"""`/dashboard` end to end (design `reports-dashboards`, "Tests", API): 401 unsigned, 403 without the functions,
400 with the candidates, and the shapes of the four answers."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.org import PermissionEffect
from aslms.domain.reference import Permission, Role
from tests.db.report_support import claim, new_case, override, today
from tests.db.workflow_support import login
from tests.db.world import add_membership


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


def test_dashboard_endpoints_status_codes(api, world):
    with world.Session() as s:
        claim(s, world, new_case(s, next_hearing=today() + timedelta(days=1)), officer="edu_off1")
        s.commit()
    for path in ("/dashboard", "/dashboard/me", "/dashboard/department", "/dashboard/state"):
        assert api.get(path).status_code == 401, path

    admin = login(api, "edu_admin")
    r = api.get("/dashboard", headers=admin)
    assert r.status_code == 200
    assert r.json() == {"me": True, "departments": [{"code": "EDU", "name": "Education"}], "state": False}
    r = api.get("/dashboard/department", headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body["department"]["code"] == "EDU" and body["cases"]["claimed_active"] == 1
    assert body["hearings"]["total"] == 1 and body["hearings"]["items"][0]["critical"] is True
    assert body["recommendations"] == {"high": 0, "medium": 0, "transfers_in_open": 0}
    assert body["pending_actions"]["held"] == 0 and body["pending_actions"]["items"] == []
    r = api.get("/dashboard/department?department=HEALTH", headers=admin)
    assert r.status_code == 403
    r = api.get("/dashboard/department?department=NOPE", headers=admin)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_department"
    assert api.get("/dashboard/state", headers=admin).status_code == 403

    officer = login(api, "edu_off1")
    me = api.get("/dashboard/me", headers=officer)
    assert me.status_code == 200
    body = me.json()
    assert body["cases"] == [
        {"department_code": "EDU", "allotted_active": 1, "allotted_disposed": 0, "counsel_active": None}
    ]
    assert body["files"]["held"] == 1 and body["hearings"]["total"] == 1
    assert set(body["alerts"]) == {"unread", "open", "items"} and isinstance(body["drafts"], int)
    r = api.get("/dashboard/department", headers=officer)
    assert r.status_code == 403
    assert api.get("/dashboard/state", headers=officer).status_code == 403

    oversight = login(api, "oversight")
    r = api.get("/dashboard/state", headers=oversight)
    assert r.status_code == 200
    body = r.json()
    assert {row["code"] for row in body["by_department"]} == {"EDU", "HEALTH", "CENTRAL"}
    assert body["hearings"]["total"] == 1 and body["not_claimed"]["active"] == 0
    r = api.get("/dashboard/department", headers=oversight)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "department_required"
    assert api.get("/dashboard/department?department=HEALTH", headers=oversight).status_code == 200

    with world.Session() as s:
        add_membership(s, world.user(s, "edu_admin"), world.office(s, "HEALTH"), Role.DEPT_OFFICER)
        s.flush()
        override(
            s, world, "edu_admin", Permission.REPORTS_DEPARTMENT, PermissionEffect.GRANT, office="HEALTH"
        )
        s.commit()
    r = api.get("/dashboard/department", headers=admin)
    assert r.status_code == 400
    assert r.json()["detail"] == {
        "code": "department_required",
        "message": "department is required: you may read EDU, HEALTH",
        "candidates": ["EDU", "HEALTH"],
    }

    with world.Session() as s:  # a login with neither case-reading function
        override(s, world, "edu_reviewer", Permission.CASES_VIEW_SCOPE, PermissionEffect.DENY)
        s.commit()
    reviewer = login(api, "edu_reviewer")
    for path in ("/dashboard", "/dashboard/me", "/dashboard/department"):
        assert api.get(path, headers=reviewer).status_code == 403, path


def test_personal_alert_items_carry_case_visible(api, world):
    """Design portal-files-alerts, decision 6: the personal block's alert items carry `case_visible`."""
    from aslms.services import alerts

    with world.Session() as s:
        claim(s, world, new_case(s, next_hearing=today() + timedelta(days=1)), officer="edu_off1")
        s.commit()
        alerts.sweep_dates(s)
        s.commit()
    body = api.get("/dashboard/me", headers=login(api, "edu_off1")).json()
    items = body["alerts"]["items"]
    assert items and all(i["case"] is not None and i["case_visible"] is True for i in items)
