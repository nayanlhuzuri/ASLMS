"""`GET /admin/users` filters and paging (design `portal-shell`, decision 16b): `q`, `role`, `include_ended`,
`limit` / `offset` and `X-Total-Count`, inside the caller's scope (unchanged)."""

from __future__ import annotations

import pytest

from tests.db.portal_support import build_api, headers


@pytest.fixture()
def api(engine):
    with build_api(engine) as client:
        yield client


def _emails(r) -> list[str]:
    assert r.status_code == 200, r.text
    return [u["email"] for u in r.json()]


def test_q_matches_name_and_email(api):
    h = headers(api, "root@example.org")
    assert _emails(api.get("/admin/users", params={"q": "sharma"}, headers=h)) == ["anita.sharma@example.org"]
    by_mail = api.get("/admin/users", params={"q": "ADMIN.HEALTH@"}, headers=h)
    assert _emails(by_mail) == ["admin.health@example.org"]
    assert by_mail.headers["X-Total-Count"] == "1"
    # LIKE wildcards are literal
    assert _emails(api.get("/admin/users", params={"q": "a%"}, headers=h)) == []


def test_q_too_short_400(api):
    h = headers(api, "root@example.org")
    r = api.get("/admin/users", params={"q": " a "}, headers=h)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_field"


def test_role_filter(api):
    h = headers(api, "root@example.org")
    r = api.get("/admin/users", params={"role": "dept_admin"}, headers=h)
    assert _emails(r) == ["admin.edu@example.org", "admin.health@example.org"]
    assert api.get("/admin/users", params={"role": "nonsense"}, headers=h).status_code == 422


def test_limit_offset_and_total_header(api):
    h = headers(api, "root@example.org")
    everyone = _emails(api.get("/admin/users", headers=h))
    assert len(everyone) == 5  # the ended login is not listed by default
    page1 = api.get("/admin/users", params={"limit": 2}, headers=h)
    page2 = api.get("/admin/users", params={"limit": 2, "offset": 2}, headers=h)
    page3 = api.get("/admin/users", params={"limit": 2, "offset": 4}, headers=h)
    assert _emails(page1) + _emails(page2) + _emails(page3) == everyone
    assert {p.headers["X-Total-Count"] for p in (page1, page2, page3)} == {"5"}
    for bad in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
        r = api.get("/admin/users", params=bad, headers=h)
        assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_field", bad


def test_no_limit_answers_all_as_before(api):
    h = headers(api, "admin.edu@example.org")
    r = api.get("/admin/users", headers=h)
    assert _emails(r) == ["admin.edu@example.org", "anita.sharma@example.org"]
    assert r.headers["X-Total-Count"] == "2"
    assert [m["office"]["code"] for m in r.json()[1]["memberships"]] == ["EDU-DSE"]


def test_include_ended_super_admin_sees_logins_without_membership(api):
    h = headers(api, "root@example.org")
    r = api.get("/admin/users", params={"include_ended": "true"}, headers=h)
    emails = _emails(r)
    assert "gone.away@example.org" in emails and len(emails) == 6
    assert r.headers["X-Total-Count"] == "6"
    gone = next(u for u in r.json() if u["email"] == "gone.away@example.org")
    assert gone["memberships"] == []
    assert _emails(api.get("/admin/users", params={"include_ended": "true", "q": "gone"}, headers=h)) == [
        "gone.away@example.org"
    ]


def test_include_ended_department_admin_403(api):
    h = headers(api, "admin.edu@example.org")
    r = api.get("/admin/users", params={"include_ended": "true"}, headers=h)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "scope"


def test_filters_never_widen_scope(api):
    h = headers(api, "admin.edu@example.org")
    r = api.get("/admin/users", params={"q": "kumar"}, headers=h)
    assert _emails(r) == [] and r.headers["X-Total-Count"] == "0"
    r = api.get("/admin/users", params={"role": "dept_admin"}, headers=h)
    assert _emails(r) == ["admin.edu@example.org"]
    r = api.get("/admin/users", params={"office": "HEALTH"}, headers=h)
    assert _emails(r) == [] and r.headers["X-Total-Count"] == "0"
    # an officer without users.view gets nothing at all
    assert api.get("/admin/users", headers=headers(api, "anil.kumar@example.org")).status_code == 403
