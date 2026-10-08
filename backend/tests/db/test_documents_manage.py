"""After upload only the visibility and the archive flag change (design documents-uploads, decision 13):
who may, the audit rows, the SourceTrace consequence, archiving, and no delete."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from aslms.domain.documents import Document
from aslms.services import custody
from aslms.services import ownership as own
from tests import samplefiles as sf
from tests.db import docs_support as ds
from tests.db.world import make_case


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture()
def scene(api, world):
    with world.Session() as s:
        case = make_case(s, case_no="WP(C)/400/2025")
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, case, officer_user_id=world.user(s, "edu_off1").id)
        # off2 (an EDU officer, not the uploader) sees the case because off1 sent them the file
        a1, off1 = world.actor(s, "edu_off1")
        custody.send(
            s,
            a1,
            off1,
            case,
            to_membership=world.membership(s, "edu_off2").id,
            pending_action_="examine",
            remark="for your examination",
        )
        order, order_doc = ds.stored_order(s, api.store, case, sf.text_pdf(["An order"]))
        s.commit()
        case_id, order_doc_id = case.id, order_doc.id
    filing = ds.upload(api, ds.login(api, "edu_off1"), case_id, sf.text_pdf(["filing"])).json()
    return {"case": case_id, "filing": filing["id"], "order": str(order_doc_id)}


def test_visibility_change_by_uploader_admin_and_super_admin(api, world, scene):
    doc = scene["filing"]
    r = api.patch(
        f"/documents/{doc}", headers=ds.login(api, "edu_off1"), json={"visibility": "private_to_office"}
    )
    assert r.status_code == 200 and r.json()["visibility"] == "private_to_office"
    assert r.json()["sourcetrace_status"] == "not_applicable"
    r = api.patch(f"/documents/{doc}", headers=ds.login(api, "edu_off2"), json={"visibility": "case_scope"})
    assert r.status_code == 403  # private to EDU: off2 (same office) sees it but may not change it
    r = api.patch(f"/documents/{doc}", headers=ds.login(api, "dse_user"), json={"visibility": "case_scope"})
    assert r.status_code == 404  # private to EDU: a directorate user does not see it at all
    r = api.patch(
        f"/documents/{doc}", headers=ds.login(api, "edu_admin"), json={"visibility": "counsel_shared"}
    )
    assert r.status_code == 200 and r.json()["sourcetrace_status"] == "pending"
    r = api.patch(f"/documents/{doc}", headers=ds.login(api, "edu_off2"), json={"visibility": "case_scope"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "forbidden"
    r = api.patch(
        f"/documents/{doc}", headers=ds.login(api, "edu_auditor"), json={"visibility": "case_scope"}
    )
    assert r.status_code == 403  # no documents.upload
    r = api.patch(f"/documents/{doc}", headers=ds.login(api, "root"), json={"visibility": "case_scope"})
    assert r.status_code == 200 and r.json()["visibility"] == "case_scope" and r.json()["can_manage"] is True
    r = api.patch(f"/documents/{doc}", headers=ds.login(api, "root"), json={"visibility": "case_scope"})
    assert r.status_code == 200  # unchanged: no audit row
    assert (
        api.patch(
            f"/documents/{doc}", headers=ds.login(api, "root"), json={"visibility": "public"}
        ).status_code
        == 422
    )
    with world.Session() as s:
        rows = ds.audit_rows(s, "document.visibility_changed", entity_id=uuid.UUID(doc))
        assert [(x.before["visibility"], x.after["visibility"]) for x in rows] == [
            ("case_scope", "private_to_office"),
            ("private_to_office", "counsel_shared"),
            ("counsel_shared", "case_scope"),
        ]
        assert (
            rows[0].before["sourcetrace_status"] == "pending"
            and rows[0].after["sourcetrace_status"] == "not_applicable"
        )
        assert (
            rows[0].actor_name == "Edu Off1"
            and rows[1].actor_name == "Edu Admin"
            and rows[0].case_id == scene["case"]
        )


def test_court_records_and_ingested_filings(api, world, scene):
    h = ds.login(api, "edu_admin")
    r = api.patch(f"/documents/{scene['order']}", headers=h, json={"visibility": "private_to_office"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_request"
    r = api.post(f"/documents/{scene['order']}/archive", headers=h, json={"reason": "not ours"})
    assert r.status_code == 400
    assert api.get(f"/documents/{scene['order']}", headers=h).json()["can_manage"] is False
    with world.Session() as s:
        doc = s.get(Document, uuid.UUID(scene["filing"]))
        doc.sourcetrace_status = "ingested"
        doc.sourcetrace_ref = "st-ref-1"  # ck_documents_sourcetrace_ingested (sourcetrace-connector)
        doc.sourcetrace_ingested_at = sa.func.now()
        s.commit()
    r = api.patch(f"/documents/{scene['filing']}", headers=h, json={"visibility": "private_to_office"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_ingested"
    r = api.patch(f"/documents/{scene['filing']}", headers=h, json={"visibility": "counsel_shared"})
    assert (
        r.status_code == 200
        and r.json()["sourcetrace_status"] == "ingested"
        and r.json()["assistant_available"] is True
    )


def test_archive_hides_keeps_and_audits(api, world, scene):
    h = ds.login(api, "edu_admin")
    doc = scene["filing"]
    r = api.post(f"/documents/{doc}/archive", headers=h, json={"reason": "uploaded to the wrong case"})
    assert (
        r.status_code == 200
        and r.json()["archived_at"]
        and r.json()["archive_reason"] == "uploaded to the wrong case"
    )
    tab = api.get(f"/cases/{scene['case']}/documents", headers=h).json()
    assert [i["id"] for i in tab["items"]] == [scene["order"]] and tab["total"] == 1
    with_archived = api.get(f"/cases/{scene['case']}/documents?include_archived=true", headers=h).json()
    assert {i["id"] for i in with_archived["items"]} == {scene["order"], doc} and with_archived["total"] == 2
    assert api.get(f"/cases/{scene['case']}", headers=h).json()["counts"]["documents"] == 1
    assert api.get(f"/documents/{doc}", headers=h).status_code == 200
    assert api.get(f"/documents/{doc}/file", headers=h).status_code == 200
    assert api.get(f"/documents/{doc}/file", headers=ds.login(api, "edu_off2")).status_code == 200
    r = api.post(f"/documents/{doc}/archive", headers=h, json={"reason": "again"})
    assert r.status_code == 400 and "already archived" in r.json()["detail"]["message"]
    assert api.post(f"/documents/{doc}/archive", headers=h, json={}).status_code == 422
    assert api.post(f"/documents/{doc}/archive", headers=h, json={"reason": "ab"}).status_code == 422
    assert (
        api.post(
            f"/documents/{doc}/archive", headers=ds.login(api, "edu_off2"), json={"reason": "not mine"}
        ).status_code
        == 403
    )
    with world.Session() as s:
        rows = ds.audit_rows(s, "document.archived", entity_id=uuid.UUID(doc))
        assert len(rows) == 1 and rows[0].after["reason"] == "uploaded to the wrong case"
        row = s.get(Document, uuid.UUID(doc))
        assert row.archived_at is not None and row.archive_reason
        with pytest.raises(sa.exc.IntegrityError, match="ck_documents_archive_reason"):
            row.archive_reason = None
            s.flush()
        s.rollback()


def test_no_endpoint_deletes(api, world, scene):
    h = ds.login(api, "root")
    assert api.delete(f"/documents/{scene['filing']}", headers=h).status_code == 405
    assert api.delete(f"/cases/{scene['case']}/documents", headers=h).status_code == 405
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Document)) == 2
