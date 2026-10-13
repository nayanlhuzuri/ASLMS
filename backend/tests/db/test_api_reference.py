"""`GET /reference/labels` (design `portal-shell`, decision 16a): the database's labels of user types, office kinds
and ticket kinds; each user type with `assignable` for the caller; reachable during the first-sign-in steps."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.reference import OfficeKind, RefRole, Role, TicketKind
from aslms.services.access import DELEGABLE_ROLES
from tests.db.portal_support import build_api, headers


@pytest.fixture()
def api(engine):
    with build_api(engine) as client:
        yield client


def _labels(api, email):
    r = api.get("/reference/labels", headers=headers(api, email))
    assert r.status_code == 200, r.text
    return r.json()


def test_labels_lists_every_user_type_with_its_label(api):
    body = _labels(api, "root@example.org")
    with api.app.state.session_factory() as s:
        expected = {r.code: r.label for r in s.scalars(sa.select(RefRole).where(RefRole.is_active.is_(True)))}
    assert {t["code"]: t["label"] for t in body["user_types"]} == expected
    assert set(expected) == {r.value for r in Role}
    assert all(t["label"] and "description" in t for t in body["user_types"])


def test_labels_office_and_ticket_kinds(api):
    body = _labels(api, "anita.sharma@example.org")
    assert {k["code"] for k in body["office_kinds"]} == {k.value for k in OfficeKind}
    assert {k["code"] for k in body["ticket_kinds"]} == {k.value for k in TicketKind}
    assert all(k["label"] for k in body["office_kinds"] + body["ticket_kinds"])


def test_assignable_super_admin_every_type_but_super_admin(api):
    body = _labels(api, "root@example.org")
    assignable = {t["code"] for t in body["user_types"] if t["assignable"]}
    assert assignable == {r.value for r in Role} - {"super_admin"}


def test_assignable_delegated_holder_only_delegable_types(api):
    body = _labels(api, "admin.edu@example.org")
    assignable = {t["code"] for t in body["user_types"] if t["assignable"]}
    assert assignable == {r.value for r in DELEGABLE_ROLES}


def test_assignable_officer_none(api):
    body = _labels(api, "anil.kumar@example.org")
    assert not any(t["assignable"] for t in body["user_types"])
    assert len(body["user_types"]) == len(Role)


def test_labels_signed_out_401(api):
    assert api.get("/reference/labels").status_code == 401
    assert api.get("/reference/labels", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_labels_answer_during_first_sign_in_gate(api):
    h = headers(api, "anita.sharma@example.org")
    with api.app.state.session_factory() as s:
        s.execute(
            sa.text("UPDATE users SET must_confirm_profile = true WHERE email = 'anita.sharma@example.org'")
        )
        s.commit()
    gated = api.get("/dashboard", headers=h)
    assert gated.status_code == 403 and gated.json()["detail"]["code"] == "profile_confirmation_required"
    r = api.get("/reference/labels", headers=h)
    assert r.status_code == 200 and r.json()["user_types"]


# ------------------------------------------------------------------------------------------------ case types (portal-cases 14e)


def _add_case_types(api) -> None:
    from aslms.domain.courts import CaseType, Court

    with api.app.state.session_factory() as s:
        court = s.scalar(sa.select(Court).where(Court.est_code == "GAHC01"))
        s.execute(sa.update(CaseType).where(CaseType.court_id == court.id).values(is_active=False))
        s.add_all(
            [
                CaseType(
                    court_id=court.id,
                    case_type_code=9001,
                    type_name="WP(C)",
                    short_name="WP(C)",
                    full_name="Writ Petition (Civil)",
                ),
                CaseType(
                    court_id=court.id,
                    case_type_code=9002,
                    type_name="CRL.A",
                    short_name="Crl.A.",
                    full_name="Criminal Appeal",
                ),
                CaseType(
                    court_id=court.id,
                    case_type_code=9003,
                    type_name="OLD",
                    short_name="AAA",
                    full_name="Retired type",
                    is_active=False,
                ),
                CaseType(court_id=court.id, case_type_code=9004, type_name="NO SHORT NAME"),
            ]
        )
        s.commit()


def test_case_types_active_only_sorted(api):
    _add_case_types(api)
    r = api.get("/reference/case-types", headers=headers(api, "anil.kumar@example.org"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert [t["case_type_code"] for t in body] == [9002, 9001, 9004]
    assert body[1] == {
        "case_type_code": 9001,
        "short_name": "WP(C)",
        "full_name": "Writ Petition (Civil)",
        "type_name": "WP(C)",
    }
    # the same list for every case reader
    assert api.get("/reference/case-types", headers=headers(api, "root@example.org")).json() == body


def test_case_types_need_case_reading(api):
    from aslms.domain.org import PermissionEffect, User
    from aslms.domain.reference import Permission
    from aslms.services import access

    with api.app.state.session_factory() as s:
        root = s.scalar(sa.select(User).where(User.email == "root@example.org"))
        officer = s.scalar(sa.select(User).where(User.email == "anil.kumar@example.org"))
        actor = access.actor_for(root)
        for perm in (Permission.CASES_VIEW_SCOPE, Permission.CASES_VIEW_ALL):
            access.set_override(s, actor, root, officer, perm, PermissionEffect.DENY, reason="test")
        s.commit()
    r = api.get("/reference/case-types", headers=headers(api, "anil.kumar@example.org"))
    assert r.status_code == 403


def test_case_types_signed_out_401(api):
    assert api.get("/reference/case-types").status_code == 401


def test_labels_carry_active_alert_kinds(api):
    """Design portal-workflow, decision 20f: active `ref_alert_kind` rows; the retired `request_due` is absent."""
    from aslms.domain.reference import AlertKind, RefAlertKind

    body = _labels(api, "anita.sharma@example.org")
    codes = {k["code"] for k in body["alert_kinds"]}
    with api.app.state.session_factory() as s:
        active = set(s.scalars(sa.select(RefAlertKind.code).where(RefAlertKind.is_active.is_(True))).all())
    assert codes == active and AlertKind.REQUEST_DUE.value not in codes
    assert AlertKind.HEARING_DUE.value in codes
    assert all(k["label"] for k in body["alert_kinds"])


# ------------------------------------------------------------------------------------------------ benches (portal-filters 12)


def _add_listings(api) -> None:
    from datetime import timedelta

    from aslms.services.reporting_common import today_ist
    from tests.db.world import add_listing, make_case

    today = today_ist()
    with api.app.state.session_factory() as s:
        case = make_case(s)
        add_listing(s, case, today, court_no="10", bench="HONOURABLE MR. JUSTICE A")
        add_listing(s, case, today, court_no="2", bench="HONOURABLE  MR. JUSTICE A ")  # same bench, spaced
        add_listing(s, case, today - timedelta(days=10), court_no="111", bench="HONOURABLE MR. JUSTICE B")
        add_listing(s, case, today - timedelta(days=10), court_no=" 2 ", bench=None)
        add_listing(s, case, today - timedelta(days=89), court_no="ANNEX", bench="honourable mr. justice c")
        add_listing(s, case, today - timedelta(days=90), court_no="7", bench="HONOURABLE MR. JUSTICE OLD")
        add_listing(s, case, today + timedelta(days=1), court_no="8", bench="HONOURABLE MR. JUSTICE FUTURE")
        s.commit()


def test_benches_window_counts_and_order(api):
    from datetime import timedelta

    from aslms.services.reporting_common import today_ist

    _add_listings(api)
    today = today_ist()
    r = api.get("/reference/benches", headers=headers(api, "anil.kumar@example.org"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["from"] == str(today - timedelta(days=89)) and body["to"] == str(today)
    assert [c["court_no"] for c in body["court_numbers"]] == ["2", "10", "111", "ANNEX"]
    two = body["court_numbers"][0]
    assert two == {"court_no": "2", "last_listed": str(today), "entries": 2}
    assert [b["text"] for b in body["benches"]] == [
        "HONOURABLE MR. JUSTICE A",
        "HONOURABLE MR. JUSTICE B",
        "HONOURABLE MR. JUSTICE C",
    ]
    assert body["benches"][0]["entries"] == 2
    # a wider window reaches the older list; the same answer for every reader
    wide = api.get("/reference/benches?days=91", headers=headers(api, "root@example.org")).json()
    assert "7" in [c["court_no"] for c in wide["court_numbers"]]
    assert api.get("/reference/benches", headers=headers(api, "root@example.org")).json() == body


def test_benches_days_bounds_400(api):
    h = headers(api, "anil.kumar@example.org")
    for days in (0, 401, -5):
        r = api.get(f"/reference/benches?days={days}", headers=h)
        assert r.status_code == 400 and r.json()["detail"] == "days is between 1 and 400", days
    for days in (1, 400):
        assert api.get(f"/reference/benches?days={days}", headers=h).status_code == 200


def test_benches_need_case_reading(api):
    from aslms.domain.org import PermissionEffect, User
    from aslms.domain.reference import Permission
    from aslms.services import access

    with api.app.state.session_factory() as s:
        root = s.scalar(sa.select(User).where(User.email == "root@example.org"))
        officer = s.scalar(sa.select(User).where(User.email == "anil.kumar@example.org"))
        actor = access.actor_for(root)
        for perm in (Permission.CASES_VIEW_SCOPE, Permission.CASES_VIEW_ALL):
            access.set_override(s, actor, root, officer, perm, PermissionEffect.DENY, reason="test")
        s.commit()
    assert api.get("/reference/benches", headers=headers(api, "anil.kumar@example.org")).status_code == 403


def test_benches_signed_out_401(api):
    assert api.get("/reference/benches").status_code == 401
