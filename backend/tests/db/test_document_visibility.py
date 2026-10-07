"""The document visibility rule (design documents-uploads, decision 7) and file serving (decisions 11, 14):
case_scope, counsel_shared, court records and private_to_office for every kind of user; a department that
loses the case loses its documents; an order PDF shared by connected cases; the one-rule check over every
endpoint; inline and attachment controls and headers; order files."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import sqlalchemy as sa

from aslms.domain.cases import Case
from aslms.domain.documents import Document
from aslms.domain.org import PermissionEffect, User
from aslms.domain.ownership import CounselCode
from aslms.domain.reference import Permission, Role
from aslms.domain.workflow import Custody
from aslms.services import access
from aslms.services import ownership as own
from aslms.services import visibility as vis
from aslms.services.users import hash_password
from tests import samplefiles as sf
from tests.db import docs_support as ds
from tests.db.test_case_visibility import entry_with_codes
from tests.db.world import PW, USERS, add_membership, make_case


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture()
def scene(api, world):
    """A case EDU owns (allotted to off1 at EDU-DSE) whose cause-list entry carries `SC, EDU`, with DHE in
    custody; a stored order PDF; uploads of every visibility by several users."""
    with world.Session() as s:
        s.add(CounselCode(code="SC, EDU", office_id=world.office(s, "EDU-SC").id))
        s.flush()
        case = make_case(s, case_no="WP(C)/300/2025")
        entry_with_codes(s, case, ["SC, EDU"])
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, case, unit_code="EDU-DSE", officer_user_id=world.user(s, "edu_off1").id)
        custody = s.get(Custody, case.id)
        custody.holder_office_id = world.office(s, "EDU-DHE").id
        custody.holder_user_id = None
        dse2 = User(
            email="user2.dse@example.org",
            password_hash=hash_password(PW),
            full_name="Dse Two",
            role=Role.DIRECTORATE_USER,
            office_id=world.office(s, "EDU-DSE").id,
        )
        s.add(dse2)
        s.flush()
        add_membership(s, dse2, world.office(s, "EDU-DSE"), Role.DIRECTORATE_USER)
        order, order_doc = ds.stored_order(
            s, api.store, case, sf.text_pdf(["Foxtrot order of the court passed on the tenth of January."])
        )
        s.commit()
        case_id, order_id, order_doc_id, dse2_id = case.id, order.id, order_doc.id, dse2.id
    USERS["dse_user2"] = ("user2.dse@example.org", Role.DIRECTORATE_USER, "EDU-DSE")
    world.users["dse_user2"] = type("U", (), {"id": dse2_id})()
    docs = {}
    h = ds.login(api, "edu_admin")
    docs["case_scope"] = ds.upload(
        api,
        h,
        case_id,
        sf.text_pdf(["Alpha writ petition filed before the court in January."]),
        visibility="case_scope",
    ).json()["id"]
    docs["counsel_shared"] = ds.upload(
        api,
        h,
        case_id,
        sf.text_pdf(["Bravo instructions to the standing counsel for the hearing."]),
        doc_type="instructions_to_counsel",
        visibility="counsel_shared",
    ).json()["id"]
    docs["edu_private"] = ds.upload(
        api,
        ds.login(api, "edu_off1"),
        case_id,
        sf.text_pdf(["Charlie legal opinion of the department on the matter."]),
        doc_type="legal_opinion",
        visibility="private_to_office",
    ).json()["id"]
    docs["dse_private"] = ds.upload(
        api,
        ds.login(api, "dse_user"),
        case_id,
        sf.docx(["Delta parawise comments from the directorate."]),
        "dp.docx",
        doc_type="parawise_comments",
        visibility="private_to_office",
    ).json()["id"]
    docs["counsel_case_scope"] = ds.upload(
        api,
        ds.login(api, "edu_counsel"),
        case_id,
        sf.text_pdf(["Echo written submission of the standing counsel."]),
        doc_type="written_submission",
        visibility="case_scope",
    ).json()["id"]
    docs["order"] = str(order_doc_id)
    yield {"case": case_id, "order": order_id, "docs": {k: uuid.UUID(v) for k, v in docs.items()}}
    USERS.pop("dse_user2", None)
    world.users.pop("dse_user2", None)


def can(world, key, doc_id) -> bool:
    with world.Session() as s:
        return vis.can_view_document(s, world.user(s, key), doc_id)


# ------------------------------------------------------------------------------------------------ the rule


def test_case_scope_counsel_shared_and_court_records(world, scene):
    d = scene["docs"]
    for key in ("edu_admin", "edu_head", "edu_off1", "dse_user", "dse_user2", "dhe_user"):
        assert can(world, key, d["case_scope"]), key
        assert can(world, key, d["counsel_shared"]), key
        assert can(world, key, d["order"]), key
    assert not can(world, "edu_counsel", d["case_scope"])
    assert can(world, "edu_counsel", d["counsel_case_scope"])  # the uploader always
    assert can(world, "edu_counsel", d["counsel_shared"])
    assert can(world, "edu_counsel", d["order"])
    assert can(world, "dse_user", d["counsel_case_scope"]) and can(world, "dhe_user", d["counsel_case_scope"])
    # plain officers without an allotment, custody or request do not see the case at all
    assert not can(world, "edu_off2", d["case_scope"]) and not can(world, "edu_reviewer", d["order"])
    for key in ("health_admin", "health_off"):
        assert not any(can(world, key, x) for x in d.values()), key


def test_private_to_office_is_the_office_itself_plus_the_department_tier(world, scene):
    d = scene["docs"]
    for key in ("dse_user", "dse_user2", "edu_admin", "edu_head", "edu_auditor", "root", "oversight"):
        assert can(world, key, d["dse_private"]), key
    for key in ("edu_off1", "edu_off2", "dhe_user", "edu_counsel"):
        assert not can(world, key, d["dse_private"]), key
    assert can(world, "edu_off1", d["edu_private"])  # the uploader
    for key in ("edu_admin", "edu_head", "edu_auditor", "root"):
        assert can(world, key, d["edu_private"]), key
    for key in ("edu_off2", "dse_user", "dhe_user", "edu_counsel"):
        assert not can(world, key, d["edu_private"]), key


def test_a_department_that_loses_the_case_loses_its_documents(api, world, scene):
    d = scene["docs"]
    with world.Session() as s:
        case = s.get(Case, scene["case"])
        actor, admin = world.actor(s, "edu_admin")
        t = own.request_transfer(s, actor, admin, case, to_office_code="HEALTH", reason="their matter")
        actor_h, admin_h = world.actor(s, "health_admin")
        own.decide_transfer(s, actor_h, admin_h, t, accept=True)
        s.commit()
    for key in ("edu_admin", "edu_head", "edu_off1", "dse_user"):
        assert not can(world, key, d["case_scope"]), key
        assert not can(world, key, d["edu_private"]), key
    assert can(world, "health_admin", d["case_scope"]) and can(world, "health_admin", d["order"])
    assert not can(world, "health_admin", d["edu_private"])
    assert not can(world, "health_admin", d["dse_private"])
    assert can(world, "edu_auditor", d["edu_private"])
    assert api.get(f"/documents/{d['case_scope']}", headers=ds.login(api, "edu_admin")).status_code == 404
    assert api.get(f"/documents/{d['case_scope']}", headers=ds.login(api, "health_admin")).status_code == 200


def test_an_order_pdf_shared_by_connected_cases(api, world, scene):
    with world.Session() as s:
        second = make_case(s, case_no="WP(C)/301/2025")
        shared = s.get(Document, scene["docs"]["order"])
        order2, _ = ds.stored_order(
            s, api.store, second, b"", order_no="1", order_date=date(2025, 1, 10), document=shared
        )
        actor, admin = world.actor(s, "health_admin")
        own.claim(s, actor, admin, second)
        s.commit()
        second_id, order2_id = second.id, order2.id
    assert can(world, "health_admin", scene["docs"]["order"])
    h = ds.login(api, "health_admin")
    listed = api.get(f"/cases/{second_id}/documents", headers=h).json()
    assert [i["id"] for i in listed["items"]] == [str(scene["docs"]["order"])]
    assert listed["items"][0]["order"]["id"] == str(order2_id)
    assert listed["items"][0]["case"]["id"] == str(second_id)
    r = api.get(f"/cases/{second_id}/orders/{order2_id}/file", headers=h)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert api.get(f"/cases/{scene['case']}/documents", headers=h).status_code == 404


# ------------------------------------------------------------------------------------------------ one rule


def test_every_endpoint_agrees_with_can_view_document(api, world, scene):
    from aslms.services.storage import LocalStore
    from aslms.services.text_extract import extract_pending

    with world.Session() as s:
        counters = extract_pending(s, LocalStore(api.store.root), batch=100)
        s.commit()
    assert counters["failed"] == 0 and counters["extracted"] >= 5
    all_ids = set(scene["docs"].values())
    for key in USERS:
        expected = {i for i in all_ids if can(world, key, i)}
        h = ds.login(api, key)
        listed = api.get(f"/cases/{scene['case']}/documents?limit=100", headers=h)
        if listed.status_code == 404:
            assert expected == set(), key
            assert api.get(f"/cases/{scene['case']}/timeline", headers=h).status_code == 404
            continue
        assert listed.status_code == 200, (key, listed.text)
        assert {uuid.UUID(i["id"]) for i in listed.json()["items"]} == expected, key
        for doc_id in all_ids:
            detail = api.get(f"/documents/{doc_id}", headers=h).status_code
            attach = api.get(f"/documents/{doc_id}/file", headers=h).status_code
            inline = api.get(f"/documents/{doc_id}/file?disposition=inline", headers=h).status_code
            if doc_id in expected:
                assert detail == 200 and attach == 200 and inline in (200, 400), (key, doc_id)
            else:
                assert detail == 404 and attach == 404 and inline == 404, (key, doc_id)
        timeline = api.get(f"/cases/{scene['case']}/timeline?limit=100", headers=h).json()
        shown = {
            uuid.UUID(i["payload"]["document_id"])
            for i in timeline["items"]
            if i["type"] == "document_uploaded"
        }
        assert shown == {i for i in expected if i != scene["docs"]["order"]}, key
        found = set()
        for q in ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot"):
            r = api.get(f"/documents/search?q={q}", headers=h)
            assert r.status_code == 200, (key, r.text)
            found |= {uuid.UUID(i["document"]["id"]) for i in r.json()["items"]}
        assert found == expected, key


# ------------------------------------------------------------------------------------------------ files


def test_inline_and_attachment_controls_and_headers(api, world, scene):
    d = scene["docs"]
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        access.set_override(
            s, actor, root, world.user(s, "dhe_user"), Permission.DOCUMENTS_DOWNLOAD, PermissionEffect.DENY
        )
        s.commit()
    h = ds.login(api, "dhe_user")  # sees the case through custody; download denied by override
    r = api.get(f"/documents/{d['case_scope']}/file?disposition=inline", headers=h)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "private, no-store"
    assert r.headers["content-security-policy"] == "sandbox"
    assert r.headers["content-disposition"] == (
        "inline; filename=\"petition.pdf\"; filename*=UTF-8''petition.pdf"
    )
    assert int(r.headers["content-length"]) == len(r.content)
    r = api.get(f"/documents/{d['case_scope']}/file", headers=h)
    assert r.status_code == 403
    admin = ds.login(api, "edu_admin")
    assert (
        api.get(f"/documents/{d['case_scope']}/file?disposition=attachment", headers=admin).status_code == 200
    )
    r = api.get(f"/documents/{d['dse_private']}/file?disposition=inline", headers=admin)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "inline_not_supported"
    r = api.get(f"/documents/{d['dse_private']}/file", headers=admin)
    assert r.status_code == 200 and "content-security-policy" not in r.headers
    assert r.headers["content-disposition"].startswith('attachment; filename="dp.docx"')
    with world.Session() as s:
        rows = ds.audit_rows(s, "document.downloaded")
        assert [(x.entity_id, x.after["disposition"]) for x in rows] == [
            (d["case_scope"], "inline"),
            (d["case_scope"], "attachment"),
            (d["dse_private"], "attachment"),
        ]
    assert api.get(f"/documents/{d['order']}/file", headers=admin).status_code == 200
    assert api.get(f"/cases/{scene['case']}/orders/{scene['order']}/file", headers=admin).status_code == 200
    with world.Session() as s:
        assert len(ds.audit_rows(s, "document.downloaded")) == 3
    assert api.get(f"/documents/{d['case_scope']}/file?disposition=print", headers=admin).status_code == 422


def test_a_ref_no_in_the_url_and_a_missing_file(api, world, scene):
    h = ds.login(api, "edu_admin")
    body = api.get(f"/documents/{scene['docs']['case_scope']}", headers=h).json()
    # the dash form travels in a path segment (the slash form cannot, as for cases)
    assert api.get(f"/documents/{body['ref_no'].replace('/', '-')}", headers=h).status_code == 200
    assert api.get(f"/documents/{body['ref_no'].replace('/', '-').lower()}", headers=h).status_code == 200
    assert api.get(f"/documents/{uuid.uuid4()}", headers=h).status_code == 404
    assert api.get("/documents/ASLMS-EDU-DOC-2099-000001", headers=h).status_code == 404
    with world.Session() as s:
        doc = s.get(Document, scene["docs"]["case_scope"])
        api.store.path(doc.storage_key).unlink()
    r = api.get(f"/documents/{scene['docs']['case_scope']}/file", headers=h)
    assert r.status_code == 500 and r.json()["detail"]["code"] == "file_missing"
    with world.Session() as s:
        row = s.execute(
            sa.text("select kind, ref from source_failures where kind = 'document_missing'")
        ).one()
        assert row.ref == str(scene["docs"]["case_scope"])


def test_order_file_not_stored_and_other_case(api, world, scene):
    h = ds.login(api, "edu_admin")
    with world.Session() as s:
        case = s.get(Case, scene["case"])
        pending = ds.pending_order(s, case)
        other = make_case(s, case_no="WP(C)/302/2025")
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, other)
        s.commit()
        pending_id, other_id = pending.id, other.id
    r = api.get(f"/cases/{scene['case']}/orders/{scene['order']}/file", headers=h)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert r.headers["content-disposition"].startswith(
        'attachment; filename="WP(C)-300-2025_1_2025-01-10.pdf"'
    )
    r = api.get(f"/cases/{scene['case']}/orders/{pending_id}/file", headers=h)
    assert r.status_code == 404 and r.json()["detail"] == {
        "code": "not_stored",
        "message": "the order's PDF is not stored",
        "download_status": "not_available",
    }
    assert api.get(f"/cases/{other_id}/orders/{scene['order']}/file", headers=h).status_code == 404
    assert (
        api.get(
            f"/cases/{scene['case']}/orders/{scene['order']}/file", headers=ds.login(api, "health_off")
        ).status_code
        == 404
    )
    orders = api.get(f"/cases/{scene['case']}/orders", headers=h).json()["items"]
    by_no = {o["order_no"]: o for o in orders}
    assert by_no["1"]["text_status"] == "pending" and by_no["9"]["text_status"] is None
    overview = api.get(f"/cases/{scene['case']}", headers=h).json()
    assert overview["counts"]["documents"] == 6
    assert (
        api.get(f"/cases/{scene['case']}", headers=ds.login(api, "dhe_user")).json()["counts"]["documents"]
        == 4
    )


def test_counsel_rule_is_not_lifted_by_another_membership(world, scene):
    """Review of 2026-10-07 (blocking): the counsel who is also an officer of another department sees the case
    only through the counsel membership, so that membership's record rule applies — the officer membership,
    which cannot see the case, does not open its `case_scope` documents."""
    d = scene["docs"]
    with world.Session() as s:
        add_membership(s, world.user(s, "edu_counsel"), world.office(s, "HEALTH"), Role.DEPT_OFFICER)
        s.commit()
    with world.Session() as s:
        person = world.user(s, "edu_counsel")
        assert {m.department.code for m in access.members(s, person)} == {"EDU", "HEALTH"}
        assert vis.can_view_case(s, person, scene["case"])
        listed = set(
            s.scalars(
                sa.select(Document.id).where(
                    Document.case_id == scene["case"], vis.document_visible_condition(s, person)
                )
            )
        )
    assert d["case_scope"] not in listed and not can(world, "edu_counsel", d["case_scope"])
    assert not can(world, "edu_counsel", d["edu_private"]) and not can(world, "edu_counsel", d["dse_private"])
    assert can(world, "edu_counsel", d["counsel_shared"]) and can(
        world, "edu_counsel", d["counsel_case_scope"]
    )
    assert can(world, "edu_counsel", d["order"])
    assert {d["counsel_shared"], d["counsel_case_scope"]} <= listed
