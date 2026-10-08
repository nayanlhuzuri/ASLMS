"""The SourceTrace administration API (design `sourcetrace-connector`, "API"): `admin.sourcetrace` on every
endpoint, the failure list through the document visibility rule, the audited retry, `sourcetrace_ingested_at` on
the document detail, and the seeded function."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from aslms.domain.cases import Case
from aslms.domain.documents import Document
from aslms.domain.org import PermissionEffect, RolePermission
from aslms.domain.reference import Permission, Role
from aslms.integration.sourcetrace.fake import FakeSourceTrace
from aslms.services import access
from tests import samplefiles as sf
from tests.db import docs_support as ds
from tests.db import st_support as h
from tests.db import workflow_support as w
from tests.db.world import make_case


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture()
def scene(world, api):
    """A failed filing on an EDU case, a failed order on a HEALTH case, and a pending EDU order."""
    with world.Session() as s:
        edu = w.claimed_case(s, world)
        health = make_case(s, case_no="WP(C)/77/2025")
        actor, admin = world.actor(s, "health_admin")
        from aslms.services import ownership as own

        own.claim(s, actor, admin, health)
        edu_filing = h.upload_row(s, api.store, edu, world.office(s, "EDU"), text="edu filing")
        _o, health_order = ds.stored_order(s, api.store, health, sf.text_pdf(["health order"]))
        s.commit()
        ids = {"edu_case": edu.id, "health_case": health.id, "edu": edu_filing.id, "health": health_order.id}
    h.ingest(world, api.store, FakeSourceTrace().script("rejected", "rejected"))
    with world.Session() as s:
        _o, pending = ds.stored_order(
            s, api.store, s.get(Case, ids["edu_case"]), sf.text_pdf(["edu order"]), order_no="2"
        )
        s.commit()
        ids["pending"] = pending.id
    assert h.status_of(world, ids["edu"]) == h.status_of(world, ids["health"]) == "failed"
    return ids


def _grant(world, key: str) -> None:
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        access.set_override(
            s,
            actor,
            root,
            world.user(s, key),
            Permission.ADMIN_SOURCETRACE,
            PermissionEffect.GRANT,
            reason="test",
        )
        s.commit()


def test_status_requires_admin_sourcetrace(api, world, scene):
    assert api.get("/admin/sourcetrace/status", headers=ds.login(api, "edu_off1")).status_code == 403
    assert api.get("/admin/sourcetrace/status", headers=ds.login(api, "edu_admin")).status_code == 403
    for key in ("central_op", "root"):
        r = api.get("/admin/sourcetrace/status", headers=ds.login(api, key))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["state"] == "disabled" and body["connector"] is None
        assert body["counts"] == {"pending": 1, "ingested": 0, "failed": 2, "not_applicable": 0}
        assert body["due_now"] == 1 and body["waiting_cnr"] == 0 and body["oldest_pending_at"]
        assert body["last_run"] is None
    assert api.get("/admin/sourcetrace/failed", headers=ds.login(api, "edu_off1")).status_code == 403
    r = api.post(f"/admin/sourcetrace/documents/{scene['edu']}/retry", headers=ds.login(api, "edu_off1"))
    assert r.status_code == 403


def test_failed_list_respects_document_visibility(api, world, scene):
    r = api.get("/admin/sourcetrace/failed", headers=ds.login(api, "central_op"))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2 and {i["document_id"] for i in body["items"]} == {
        str(scene["edu"]),
        str(scene["health"]),
    }
    item = next(i for i in body["items"] if i["document_id"] == str(scene["edu"]))
    assert item["kind"] == "upload" and item["error_family"] == "rejected" and item["attempts"] == 1
    assert item["last_error"] and item["last_attempt_at"] and item["case"]["id"] == str(scene["edu_case"])
    _grant(world, "edu_admin")
    r = api.get("/admin/sourcetrace/failed", headers=ds.login(api, "edu_admin"))
    assert r.status_code == 200
    assert r.json()["total"] == 1 and [i["document_id"] for i in r.json()["items"]] == [str(scene["edu"])]
    r = api.get("/admin/sourcetrace/failed?limit=1&offset=1", headers=ds.login(api, "central_op"))
    assert r.json()["total"] == 2 and len(r.json()["items"]) == 1
    assert (
        api.get("/admin/sourcetrace/failed?limit=500", headers=ds.login(api, "central_op")).status_code == 422
    )


def test_retry_requeues_audits_and_refuses_ingested(api, world, scene):
    _grant(world, "edu_admin")
    hd = ds.login(api, "edu_admin")
    # a HEALTH document is not visible to the EDU admin: 404, nothing changes
    r = api.post(f"/admin/sourcetrace/documents/{scene['health']}/retry", headers=hd)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found"
    assert h.status_of(world, scene["health"]) == "failed"
    with world.Session() as s:
        ref_no = s.get(Document, scene["edu"]).ref_no
    r = api.post(f"/admin/sourcetrace/documents/{ref_no.replace('/', '-')}/retry", headers=hd)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "document_id": str(scene["edu"]),
        "sourcetrace_status": "pending",
        "sourcetrace_attempts": 0,
    }
    with world.Session() as s:
        (audit,) = ds.audit_rows(s, "sourcetrace.retry_requested", entity_id=scene["edu"])
        assert audit.case_id == scene["edu_case"] and audit.actor_user_id == world.users["edu_admin"].id
        assert audit.before == {"sourcetrace_status": "failed", "sourcetrace_attempts": 1}
        assert audit.after == {"sourcetrace_status": "pending", "sourcetrace_attempts": 0}
    # pending with no failed attempt: nothing to retry
    r = api.post(f"/admin/sourcetrace/documents/{scene['edu']}/retry", headers=hd)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_retryable"
    h.ingest(world, api.store, FakeSourceTrace())
    assert h.status_of(world, scene["edu"]) == "ingested"
    r = api.post(f"/admin/sourcetrace/documents/{scene['edu']}/retry", headers=hd)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_retryable"
    r = api.post(f"/admin/sourcetrace/documents/{uuid.uuid4()}/retry", headers=hd)
    assert r.status_code == 404


def test_document_detail_shows_ingested_at(api, world, scene):
    hd = ds.login(api, "edu_admin")
    r = api.get(f"/documents/{scene['pending']}", headers=hd)
    assert r.status_code == 200 and r.json()["sourcetrace_ingested_at"] is None
    assert r.json()["assistant_available"] is False
    h.ingest(world, api.store, FakeSourceTrace())
    body = api.get(f"/documents/{scene['pending']}", headers=hd).json()
    assert body["sourcetrace_status"] == "ingested" and body["sourcetrace_ingested_at"]
    assert body["assistant_available"] is True


def test_seed_adds_admin_sourcetrace(world):
    with world.Session() as s:
        assert s.scalar(sa.text("select count(*) from ref_permission")) == 50
        assert s.scalar(sa.text("select count(*) from ref_permission where is_active")) == 48
        label = s.scalar(sa.text("select label from ref_permission where code = 'admin.sourcetrace'"))
        assert label == "SourceTrace ingestion"
        rows = s.scalars(
            sa.select(RolePermission).where(RolePermission.permission == Permission.ADMIN_SOURCETRACE)
        ).all()
        enabled = {Role(r.role) for r in rows if r.is_enabled}
        assert enabled == {Role.CENTRAL_OPERATOR} and len(rows) == 9
        assert access.has(s, world.user(s, "root"), Permission.ADMIN_SOURCETRACE)
        assert access.has(s, world.user(s, "central_op"), Permission.ADMIN_SOURCETRACE)
        assert not access.has(s, world.user(s, "edu_admin"), Permission.ADMIN_SOURCETRACE)
