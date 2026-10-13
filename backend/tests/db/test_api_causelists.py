"""`/causelists` (design `portal-causelist`): the read gates, the shapes, the PDF with its file functions and
errors (not audited), and a claim through the existing endpoint showing on the next read."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.events import AuditLog
from aslms.domain.ops import SourceFailure
from aslms.domain.org import PermissionEffect
from aslms.domain.reference import Permission
from aslms.services import access
from tests.db import docs_support as ds
from tests.db.causelist_support import D2, build, pdf_bytes


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    client.cl = build(world, client.store)
    yield client
    client.__exit__(None, None, None)


def deny(world, key: str, permission: Permission) -> None:
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        access.set_override(s, actor, root, world.user(s, key), permission, PermissionEffect.DENY)
        s.commit()


def audit_count(world) -> int:
    with world.Session() as s:
        return int(s.scalar(sa.select(sa.func.count()).select_from(AuditLog)) or 0)


def test_signed_out_401(api):
    for path in ("/causelists/dates", f"/causelists/{D2}", f"/causelists/{D2}/entries"):
        assert api.get(path).status_code == 401
    assert api.get(f"/causelists/lists/{api.cl.lists['daily']}/file").status_code == 401


def test_without_case_reading_403(api, world):
    deny(world, "edu_off1", Permission.CASES_VIEW_SCOPE)
    h = ds.login(api, "edu_off1")
    for path in (
        "/causelists/dates",
        f"/causelists/{D2}",
        f"/causelists/{D2}/entries",
        f"/causelists/lists/{api.cl.lists['daily']}/file",
    ):
        assert api.get(path, headers=h).status_code == 403, path


def test_dates_day_entries_shapes(api):
    h = ds.login(api, "edu_admin")
    r = api.get("/causelists/dates?from=2026-10-01&to=2026-10-31", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"from", "to", "today", "default_date", "items"}
    assert body["from"] == "2026-10-01"
    assert {i["date"] for i in body["items"]} == {"2026-10-12", "2026-10-13", "2026-10-20"}
    assert api.get("/causelists/dates?from=2026-10-31&to=2026-10-01", headers=h).status_code == 400
    r = api.get(f"/causelists/{D2}", headers=h)
    assert r.status_code == 200, r.text
    day = r.json()
    assert [b["bench_id"] for b in day["benches"]] == [777, 1854, 2048, 3000]
    assert day["previous_date"] == "2026-10-12" and day["next_date"] == "2026-10-20"
    assert set(day["benches"][1]["lists"][0]) == {
        "id",
        "list_type",
        "list_type_text",
        "label",
        "napix_causelist_id",
        "source",
        "entry_count",
        "entries_stored",
        "fetch_status",
        "parse_status",
        "has_pdf",
    }
    r = api.get(f"/causelists/{D2}/entries?bench_id=1854&only=claimable", headers=h)
    assert r.status_code == 200, r.text
    page = r.json()
    assert page["counts"]["entries"] == 7
    item = next(i for i in page["items"] if i["id"] == str(api.cl.entries["e_rec_both"]))
    assert item["recommendations"] == [{"office_code": "EDU", "band": "high", "score": 0.95}]
    assert item["case"]["id"] == str(api.cl.cases["rec_both"]) and item["visible"] is True
    assert item["claimable"] is True and item["in_pool"] is True and item["held_by_you"] is None
    for bad in (
        "only=x",
        "q=ab",
        "limit=0",
        "limit=501",
        "offset=-1",
        "list_type=x",
        f"bench_id=1&list_id={api.cl.lists['daily']}",
    ):
        assert api.get(f"/causelists/{D2}/entries?{bad}", headers=h).status_code == 400, bad
    assert api.get("/causelists/2026-10-18", headers=h).json()["state"] == "not_loaded"


def test_file_inline_needs_documents_view(api, world):
    url = f"/causelists/lists/{api.cl.lists['daily']}/file?disposition=inline"
    h = ds.login(api, "edu_off1")
    r = api.get(url, headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content == pdf_bytes("daily")
    assert r.headers["content-disposition"].startswith(
        'inline; filename="Causelist_2026-10-13_bench-1854_daily.pdf"'
    )
    deny(world, "edu_off1", Permission.DOCUMENTS_VIEW)
    h = ds.login(api, "edu_off1")
    assert api.get(url, headers=h).status_code == 403
    assert api.get(url.replace("inline", "attachment"), headers=h).status_code == 200


def test_file_attachment_needs_documents_download(api, world):
    url = f"/causelists/lists/{api.cl.lists['lawazima']}/file"
    h = ds.login(api, "dse_user")
    r = api.get(url, headers=h)
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment;")
    deny(world, "dse_user", Permission.DOCUMENTS_DOWNLOAD)
    h = ds.login(api, "dse_user")
    assert api.get(url, headers=h).status_code == 403
    assert api.get(url + "?disposition=inline", headers=h).status_code == 200


def test_file_no_pdf_404_with_fetch_status(api):
    h = ds.login(api, "edu_admin")
    r = api.get(f"/causelists/lists/{api.cl.lists['supp']}/file", headers=h)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "no_pdf"
    assert r.json()["detail"]["fetch_status"] == "not_available"


def test_file_missing_404_records_failure(api, world):
    with world.Session() as s:
        from aslms.domain.documents import Document

        doc = s.get(Document, api.cl.docs["court2"])
        api.store.path(doc.storage_key).unlink()
    h = ds.login(api, "edu_admin")
    r = api.get(f"/causelists/lists/{api.cl.lists['court2']}/file", headers=h)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "file_missing"
    with world.Session() as s:
        rows = s.scalars(
            sa.select(SourceFailure).where(SourceFailure.ref == str(api.cl.docs["court2"]))
        ).all()
        assert len(rows) == 1 and rows[0].kind == "document_missing"


def test_file_not_audited(api, world):
    h = ds.login(api, "edu_admin")
    before = audit_count(world)
    for disposition in ("inline", "attachment"):
        r = api.get(f"/causelists/lists/{api.cl.lists['daily']}/file?disposition={disposition}", headers=h)
        assert r.status_code == 200
    api.get(f"/causelists/{D2}/entries", headers=h)
    api.get(f"/causelists/{D2}", headers=h)
    api.get("/causelists/dates", headers=h)
    assert audit_count(world) == before


def test_unknown_list_404(api):
    h = ds.login(api, "edu_admin")
    r = api.get("/causelists/lists/01a00000-0000-7000-8000-000000000000/file", headers=h)
    assert r.status_code == 404 and r.json()["detail"] == "no such cause list"
    assert (
        api.get(
            f"/causelists/{D2}/entries?list_id=01a00000-0000-7000-8000-000000000000", headers=h
        ).status_code
        == 400
    )


def test_claim_from_entry_then_row_shows_owner(api, world):
    h = ds.login(api, "edu_admin")
    url = f"/causelists/{D2}/entries?bench_id=1854"

    def row():
        items = api.get(url, headers=h).json()["items"]
        return next(i for i in items if i["id"] == str(api.cl.entries["e_rec_both"]))

    before = row()
    assert before["claimable"] is True and before["owner_office_code"] is None
    ref = before["case"]["ref_no"].replace("/", "-")
    ownership = api.get(f"/cases/{ref}/ownership", headers=h).json()
    assert ownership["actions"]["claim_departments"] == ["EDU"]
    r = api.post(f"/cases/{ref}/claim", headers=h, json={"office_code": "EDU"})
    assert r.status_code in (200, 201), r.text
    after = row()
    assert after["owner_office_code"] == "EDU"
    assert after["held_by_you"] == "primary"
    assert after["claimable"] is False
    with world.Session() as s:
        n = s.scalar(
            sa.select(sa.func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "ownership.claim", AuditLog.case_id == api.cl.cases["rec_both"])
        )
        assert n == 1


def test_disabled_user_401(api, world):
    h = ds.login(api, "edu_off1")
    root = ds.login(api, "root")
    with world.Session() as s:
        uid = world.user(s, "edu_off1").id
    assert api.post(f"/admin/users/{uid}/disable", headers=root).status_code == 200
    for path in ("/causelists/dates", f"/causelists/{D2}", f"/causelists/{D2}/entries"):
        assert api.get(path, headers=h).status_code == 401, path


def test_bad_date_is_422_and_regex_characters_in_words_are_harmless(api):
    h = ds.login(api, "edu_admin")
    assert api.get("/causelists/not-a-date", headers=h).status_code == 422
    assert api.get("/causelists/dates?from=bad", headers=h).status_code == 422
    for q in ("(((", "a.*b[", "\m\M", "x'; DROP TABLE cases;--"):
        r = api.get(f"/causelists/{D2}/entries", params={"q": q}, headers=h)
        assert r.status_code in (200, 400), (q, r.text)
    assert api.get(f"/causelists/{D2}/entries", headers=h).status_code == 200
