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
