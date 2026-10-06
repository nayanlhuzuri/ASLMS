"""Text extraction in the database (design documents-uploads, decisions 10, 15): the sweep over pending
documents, failures recorded and retried, `SKIP LOCKED` between two runs, and the content search under the
visibility rule."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from aslms.domain.documents import Document, DocumentText
from aslms.services import ownership as own
from aslms.services.storage import LocalStore
from aslms.services.text_extract import extract_pending
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
        case = make_case(s, case_no="WP(C)/500/2025")
        actor, admin = world.actor(s, "edu_admin")
        own.claim(s, actor, admin, case)
        other = make_case(s, case_no="WP(C)/501/2025")
        actor_h, admin_h = world.actor(s, "health_admin")
        own.claim(s, actor_h, admin_h, other)
        _, order_doc = ds.stored_order(
            s,
            api.store,
            case,
            sf.text_pdf(["The impugned notification is quashed.", "Costs waived."], pages=2),
        )
        _, scanned = ds.stored_order(s, api.store, case, sf.image_pdf(pages=3), order_no="2")
        _, health_doc = ds.stored_order(
            s, api.store, other, sf.text_pdf(["The notification stands and the petition is dismissed."])
        )
        s.commit()
        ids = {
            "order": order_doc.id,
            "scanned": scanned.id,
            "health": health_doc.id,
            "case": case.id,
            "other": other.id,
        }
    h = ds.login(api, "edu_admin")
    ids["docx"] = uuid.UUID(
        ds.upload(
            api,
            h,
            ids["case"],
            sf.docx(["Parawise comments on the notification."]),
            "pc.docx",
            doc_type="parawise_comments",
        ).json()["id"]
    )
    ids["png"] = uuid.UUID(
        ds.upload(api, h, ids["case"], sf.png(), "annex.png", doc_type="annexure").json()["id"]
    )
    ids["pdf"] = uuid.UUID(
        ds.upload(
            api,
            h,
            ids["case"],
            sf.text_pdf(["Reply affidavit of the respondent department."]),
            "reply.pdf",
            doc_type="reply",
        ).json()["id"]
    )
    return ids


def _status(world, doc_id) -> tuple[str, int | None, bool]:
    with world.Session() as s:
        d = s.get(Document, doc_id)
        t = s.get(DocumentText, doc_id)
        has_vector = bool(
            t is not None
            and s.scalar(sa.select(DocumentText.search_vector).where(DocumentText.document_id == doc_id))
        )
        return d.text_status.value, d.page_count, has_vector


def test_extract_pending_over_every_kind(api, world, scene):
    with world.Session() as s:
        doc = s.get(Document, scene["pdf"])
        api.store.path(doc.storage_key).write_bytes(b"%PDF-1.4 corrupt")  # a corrupt file in the store
        s.commit()
    store = LocalStore(api.store.root)
    with world.Session() as s:
        counters = extract_pending(s, store, batch=50)
        s.commit()
    assert counters == {"claimed": 5, "extracted": 3, "none": 1, "failed": 1}
    assert _status(world, scene["order"]) == ("extracted", 2, True)
    assert _status(world, scene["health"]) == ("extracted", 1, True)
    assert _status(world, scene["docx"]) == ("extracted", None, True)
    assert _status(world, scene["scanned"]) == ("none", 3, False)
    assert _status(world, scene["png"]) == ("none", None, False)
    assert _status(world, scene["pdf"]) == ("failed", None, False)
    with world.Session() as s:
        row = s.execute(
            sa.text("select ref, attempts, resolved_at from source_failures where kind='text_extraction'")
        ).one()
        assert row.ref == str(scene["pdf"]) and row.attempts == 1 and row.resolved_at is None
        assert s.get(DocumentText, scene["order"]).full_text.count("Costs waived") == 2
        assert s.get(Document, scene["order"]).text_extracted_at is not None
        counters = extract_pending(s, store, batch=50)
        assert counters["claimed"] == 0
        counters = extract_pending(s, store, batch=50, retry_failed=True)
        assert counters == {"claimed": 1, "extracted": 0, "none": 0, "failed": 1}
        s.commit()
        assert (
            s.execute(sa.text("select attempts from source_failures where kind='text_extraction'")).scalar()
            == 2
        )
        # the file repaired: the retry succeeds and resolves the failure
        doc = s.get(Document, scene["pdf"])
        api.store.path(doc.storage_key).write_bytes(
            sf.text_pdf(["Reply affidavit of the respondent department."])
        )
        counters = extract_pending(s, store, batch=50, retry_failed=True, document_id=scene["pdf"])
        assert counters["extracted"] == 1
        s.commit()
        assert (
            s.execute(
                sa.text("select resolved_at from source_failures where kind='text_extraction'")
            ).scalar()
            is not None
        )
    assert _status(world, scene["pdf"]) == ("extracted", 1, True)


def test_two_runs_never_share_a_document(api, world, scene):
    store = LocalStore(api.store.root)
    with world.Session() as first, world.Session() as second:
        a = extract_pending(first, store, batch=3)  # holds the locks until commit
        b = extract_pending(second, store, batch=50)
        assert a["claimed"] == 3 and b["claimed"] == 2
        first.commit()
        second.commit()
    with world.Session() as s:
        assert (
            s.scalar(
                sa.select(sa.func.count()).select_from(Document).where(Document.text_status == "pending")
            )
            == 0
        )


def test_search_respects_visibility_and_returns_snippets(api, world, scene):
    with world.Session() as s:
        extract_pending(s, LocalStore(api.store.root), batch=50)
        s.commit()
    h = ds.login(api, "edu_admin")
    r = api.get("/documents/search?q=notification", headers=h)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert {i["document"]["id"] for i in items} == {str(scene["order"]), str(scene["docx"])}
    assert r.json()["total"] == 2
    for i in items:
        assert "[[notification]]" in i["snippet"].lower() and i["rank"] > 0
        assert i["case"]["case_no_text"] == "WP(C)/500/2025"
    order_item = next(i for i in items if i["document"]["id"] == str(scene["order"]))
    assert order_item["document"]["order"]["order_no"] == "1" and order_item["document"]["page_count"] == 2
    r = api.get("/documents/search?q=notification&group=internal", headers=h)
    assert [i["document"]["id"] for i in r.json()["items"]] == [str(scene["docx"])]
    r = api.get(f"/documents/search?q=notification&case={scene['other']}", headers=h)
    assert r.json()["total"] == 0
    r = api.get("/documents/search?q=quashed&date_from=2025-01-01&date_to=2025-01-31", headers=h)
    assert r.json()["total"] == 1
    r = api.get("/documents/search?q=notification", headers=ds.login(api, "health_admin"))
    assert [i["document"]["id"] for i in r.json()["items"]] == [str(scene["health"])]
    r = api.get("/documents/search?q=notification", headers=ds.login(api, "edu_auditor"))
    assert r.json()["total"] == 3
    assert api.get("/documents/search?q=no", headers=h).status_code == 422
    r = api.get("/documents/search?q=notification&limit=1", headers=h)
    assert len(r.json()["items"]) == 1 and r.json()["total"] == 2
    r = api.get('/documents/search?q="costs waived"', headers=h)
    assert r.json()["total"] == 1
