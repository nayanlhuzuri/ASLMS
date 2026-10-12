"""`GET /custody/recipients` additions (design `portal-cases`, decision 14d): each membership row carries the
person's `user_id` (allot takes a user), and with `department` the response lists `units`, the active offices
strictly inside that department, so the claim and allot dialogs can offer them. Without `department` the
response is unchanged."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.org import Office
from aslms.domain.reference import OfficeKind
from tests.db.auth_support import bearer
from tests.db.world import PW, USERS


@pytest.fixture()
def api(world):
    settings = Settings(
        _env_file=None,
        aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters",
        aslms_access_token_minutes=5,
    )
    with TestClient(create_app(settings, world.Session)) as client:
        yield client


def login(api, key):
    return bearer(api, USERS[key][0], PW)


def test_recipients_carry_user_id(api, world):
    r = api.get("/custody/recipients?department=EDU", headers=login(api, "edu_admin"))
    assert r.status_code == 200, r.text
    by_name = {p["full_name"]: p for p in r.json()["items"]}
    assert by_name["Edu Off1"]["user_id"] == str(world.users["edu_off1"].id)
    assert all(p["user_id"] and p["membership_id"] for p in r.json()["items"])


def test_units_are_active_offices_inside_the_department(api, world):
    with world.Session() as s:
        edu = world.office(s, "EDU")
        dse = world.office(s, "EDU-DSE")
        s.add(
            Office(
                code="EDU-DSE-X",
                name="Old Cell",
                kind=OfficeKind.UNIT,
                parent_id=dse.id,
                path=f"{dse.path}/EDU-DSE-X",
                is_active=False,
            )
        )
        s.add(
            Office(
                code="EDU-DSE-A",
                name="Accounts Cell",
                kind=OfficeKind.UNIT,
                parent_id=dse.id,
                path=f"{dse.path}/EDU-DSE-A",
            )
        )
        s.commit()
        assert edu.path
    body = api.get("/custody/recipients?department=EDU", headers=login(api, "edu_admin")).json()
    codes = [u["code"] for u in body["units"]]
    assert codes == ["EDU-DHE", "EDU-DSE", "EDU-DSE-A", "EDU-SC"]  # by path; no EDU itself, no inactive
    assert body["units"][1] == {"code": "EDU-DSE", "name": "Secondary Education"}
    health = api.get("/custody/recipients?department=HEALTH", headers=login(api, "edu_admin")).json()
    assert health["units"] == []


def test_no_units_without_department(api, world):
    body = api.get("/custody/recipients", headers=login(api, "edu_admin")).json()
    assert body["units"] == [] and body["items"] == []
    assert {"EDU", "HEALTH"} <= {d["code"] for d in body["departments"]}
