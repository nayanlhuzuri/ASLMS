"""The supporting documents of a ticket (design `user-memberships`, decision 20): uploaded with the request or
attached while the ticket is open, checked and scanned before anything is written, never sent to SourceTrace,
never visible through the case document paths, readable by the panel's holders only, linked to the
memberships the ticket changed, archived but never deleted."""

from __future__ import annotations

import json

import pytest
import sqlalchemy as sa

from aslms.domain.documents import DocKind, Document
from aslms.domain.tickets import AdminTicket
from aslms.services import ownership as own
from tests import samplefiles as sf
from tests.db import docs_support as ds
from tests.db.docs_support import login, make_api
from tests.db.world import make_case


@pytest.fixture()
def api(world, tmp_path):
    return make_api(world, tmp_path)


def replace_request(world, remark=None, files_meta=None) -> dict:
    with world.Session() as s:
        mid = str(world.membership(s, "edu_off1").id)
    body = {
        "department": "EDU",
        "operation": "replace",
        "incoming": {"membership_id": mid},
        "outgoing": {"mode": "retype"},
    }
    if remark:
        body["request_remark"] = remark
    if files_meta is not None:
        body["files"] = files_meta
    return {"request": json.dumps(body)}


def ticket_count(world) -> int:
    with world.Session() as s:
        return s.scalar(sa.select(sa.func.count()).select_from(AdminTicket))


def test_documents_with_the_request_and_after_while_open(world, api):
    admin, root = login(api, "edu_admin"), login(api, "root")
    order = sf.text_pdf(["Government of Assam order appointing the head of Education"])
    r = api.post(
        "/admin/tickets/head-change",
        data=replace_request(
            world,
            files_meta=[{"doc_type": "government_order", "doc_date": "2026-10-01", "description": "GO 12"}],
        ),
        files=[("files", ("go.pdf", order, "application/pdf"))],
        headers=admin,
    )
    assert r.status_code == 202, r.text
    t = r.json()
    assert (
        t["status"] == "open"
        and len(t["documents"]) == 1
        and t["documents"][0]["doc_type"] == "government_order"
    )
    ref = t["ref_no"].replace("/", "-")
    detail = api.get(f"/admin/tickets/{ref}", headers=root).json()
    assert detail["documents"][0]["description"] == "GO 12" and detail["can_approve"] is True
    doc_id = detail["documents"][0]["id"]
    with world.Session() as s:
        doc = s.get(Document, doc_id)
        assert (
            doc.kind == DocKind.ADMIN
            and doc.case_id is None
            and doc.sourcetrace_status.value == "not_applicable"
        )
        assert doc.doc_group.value == "internal" and doc.visibility.value == "private_to_office"
        assert doc.ref_no.startswith("ASLMS/EDU/DOC/")
    # readable by the super admin and the EDU admin; not by an EDU officer or the HEALTH admin
    assert api.get(f"/admin/tickets/{ref}/documents/{doc_id}/file", headers=root).status_code == 200
    assert api.get(f"/admin/tickets/{ref}/documents/{doc_id}/file", headers=admin).content == order
    assert api.get(f"/admin/tickets/{ref}", headers=login(api, "edu_off1")).status_code == 403
    assert api.get(f"/admin/tickets/{ref}", headers=login(api, "health_admin")).status_code == 404
    # invisible through the case document paths
    assert api.get(f"/documents/{doc_id}", headers=root).status_code == 404
    assert api.get(f"/documents/{doc_id}", headers=admin).status_code == 404
    # a duplicate on the ticket → 409; another order while open → 201; another type → 400
    r = api.post(
        f"/admin/tickets/{ref}/documents",
        files={"file": ("go.pdf", order)},
        data={"doc_type": "government_order"},
        headers=admin,
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "duplicate"
    later = sf.text_pdf(["Corrigendum to the order"])
    r = api.post(
        f"/admin/tickets/{ref}/documents",
        files={"file": ("c.pdf", later)},
        data={"doc_type": "government_order"},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    later_id = r.json()["id"]
    r = api.post(
        f"/admin/tickets/{ref}/documents",
        files={"file": ("p.pdf", sf.text_pdf(["x"]))},
        data={"doc_type": "petition"},
        headers=admin,
    )
    assert r.status_code == 400
    # archive while open keeps the link
    r = api.post(
        f"/admin/tickets/{ref}/documents/{later_id}/archive", json={"reason": "superseded"}, headers=admin
    )
    assert r.status_code == 200 and r.json()["archived"] is True
    assert len(api.get(f"/admin/tickets/{ref}", headers=root).json()["documents"]) == 2
    # approval links the order to the memberships the ticket changed; attaching afterwards → 409
    assert api.post(f"/admin/tickets/{ref}/approve", json={}, headers=root).status_code == 200
    r = api.post(
        f"/admin/tickets/{ref}/documents", files={"file": ("n.pdf", sf.text_pdf(["new"]))}, headers=admin
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ticket_closed"
    with world.Session() as s:
        incoming = world.membership(s, "edu_off1")
        outgoing = world.membership(s, "edu_head")
        uid_in, uid_out = incoming.user_id, outgoing.user_id
        mid_in, mid_out = incoming.id, outgoing.id
    for uid, mid in ((uid_in, mid_in), (uid_out, mid_out)):
        listed = api.get(f"/admin/users/{uid}/memberships/{mid}/documents", headers=admin).json()
        assert [d["ticket_ref"] for d in listed] == [t["ref_no"]]  # the archived corrigendum is not linked
    assert (
        api.get(
            f"/admin/users/{uid_in}/memberships/{mid_in}/documents", headers=login(api, "health_admin")
        ).status_code
        == 404
    )


def test_a_request_without_documents_then_closed_tickets_refuse_attachments(world, api):
    admin, root = login(api, "edu_admin"), login(api, "root")
    for action, body in (("reject", {"remark": "no order"}), ("withdraw", {})):
        r = api.post("/admin/tickets/head-change", data=replace_request(world), headers=admin)
        assert r.status_code == 202 and r.json()["documents"] == []
        ref = r.json()["ref_no"].replace("/", "-")
        who = root if action == "reject" else admin
        assert api.post(f"/admin/tickets/{ref}/{action}", json=body, headers=who).status_code == 200
        r = api.post(
            f"/admin/tickets/{ref}/documents", files={"file": ("x.pdf", sf.text_pdf(["late"]))}, headers=admin
        )
        assert r.status_code == 409 and r.json()["detail"]["code"] == "ticket_closed"


def test_one_refused_file_refuses_the_whole_request(world, api):
    admin = login(api, "edu_admin")
    infected = sf.text_pdf(["order"]) + b"__ASLMS_INFECTED__"
    r = api.post(
        "/admin/tickets/head-change",
        data=replace_request(world),
        files=[("files", ("a.pdf", sf.text_pdf(["fine"]))), ("files", ("b.pdf", infected))],
        headers=admin,
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "infected"
    assert ticket_count(world) == 0
    with world.Session() as s:
        assert (
            s.scalar(sa.select(sa.func.count()).select_from(Document).where(Document.kind == DocKind.ADMIN))
            == 0
        )
        assert ds.audit_rows(s, "document.upload_rejected")[0].after["reason"] == "infected"
    r = api.post(
        "/admin/tickets/head-change",
        data=replace_request(world),
        files=[("files", ("x.exe", sf.exe()))],
        headers=admin,
    )
    assert r.status_code == 415 and ticket_count(world) == 0
    big = api.settings.upload_max_bytes + 1
    r = api.post(
        "/admin/tickets/head-change",
        data=replace_request(world),
        files=[("files", ("big.pdf", b"%PDF" + b"0" * big))],
        headers=admin,
    )
    assert r.status_code == 413 and ticket_count(world) == 0


def test_case_uploads_refuse_government_orders(world, api):
    with world.Session() as s:
        actor, admin_u = world.actor(s, "edu_admin")
        case = make_case(s)
        own.claim(s, actor, admin_u, case)
        s.commit()
        ref = case.ref_no.replace("/", "-")
    admin = login(api, "edu_admin")
    r = ds.upload(api, admin, ref, sf.text_pdf(["an order"]), doc_type="government_order")
    assert r.status_code == 400
    types = [t["code"] for t in api.get("/documents/types", headers=admin).json()["items"]]
    assert "government_order" not in types
