"""`GET /admin/users?status=` (design case-workspace-admin, decision 23): `active` (sign-in on, signed in at least once),
`not_signed_in` (on, never signed in) and `off` (sign-in turned off), each counted in `X-Total-Count`; the scope is
unchanged."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from aslms.domain.org import User
from tests.db import docs_support as ds
from tests.db import workflow_support as w
from tests.db.world import USERS


@pytest.fixture()
def api(world, tmp_path):
    with world.Session() as s:
        s.execute(sa.update(User).values(last_login_at=None))
        s.execute(sa.update(User).where(User.id == world.users["edu_off1"].id).values(is_active=False))
        s.execute(
            sa.update(User)
            .where(User.id == world.users["edu_off2"].id)
            .values(last_login_at=datetime.now(UTC))
        )
        s.commit()
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


def _get(api, h, status):
    r = api.get("/admin/users", params={"status": status}, headers=h)
    assert r.status_code == 200, r.text
    emails = {u["email"] for u in r.json()}
    assert r.headers["X-Total-Count"] == str(len(emails))
    return emails


def test_each_status(api):
    h = w.login(api, "root")  # signing in makes root active
    everyone = {e for e, _, _ in USERS.values()}
    off = _get(api, h, "off")
    active = _get(api, h, "active")
    waiting = _get(api, h, "not_signed_in")
    assert off == {USERS["edu_off1"][0]}
    assert active == {USERS["root"][0], USERS["edu_off2"][0]}
    assert waiting == everyone - off - active
    r = api.get("/admin/users", params={"status": "invited"}, headers=h)
    assert r.status_code == 422


def test_scope_is_unchanged(api):
    h = w.login(api, "edu_admin")
    edu = {USERS[k][0] for k, (_, _, code) in USERS.items() if code.startswith("EDU")}
    waiting = _get(api, h, "not_signed_in")
    assert waiting and waiting <= edu
    assert USERS["health_off"][0] not in waiting
    assert _get(api, h, "off") == {USERS["edu_off1"][0]}
    assert _get(api, h, "active") == {USERS["edu_admin"][0], USERS["edu_off2"][0]}
