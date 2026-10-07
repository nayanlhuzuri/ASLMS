"""Attachments on permanent notes (design custody-workflow, decision 18): new files become internal `attachment`
documents with the note's visibility (never sent to SourceTrace); one infected file refuses the call and writes
nothing but its rejection audit row; the file count and size limits; a link never widens; the attachment's
visibility and archive follow the note (409); attachments stay out of the Documents tab."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.documents import DocGroup, DocKind, Document
from aslms.domain.workflow import CaseNote
from aslms.services.scanner import eicar_test_string
from tests import samplefiles as sf
from tests.db import docs_support as ds
from tests.db import workflow_support as w

MAX = 200_000


@pytest.fixture()
def api(world, tmp_path):
    w.widen(world)
    client = ds.make_api(world, tmp_path, upload_max_bytes=MAX)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture()
def case_id(api, world):
    """An EDU case held by off1; the EDU admin (not the holder) writes permanent notes."""
    with world.Session() as s:
        case = w.claimed_case(s, world)
        s.commit()
        return case.id


def _note(api, headers, case_id, files=(), **fields):
    data = {"kind": "general", "body": "see attached", "visibility": "case_scope", **fields}
    return api.post(
        f"/cases/{case_id}/notes",
        headers=headers,
        data=data,
        files=[("files", f) for f in files] or None,
    )


def test_files_become_internal_attachments(api, world, case_id):
    ha = w.login(api, "edu_admin")
    r = _note(
        api,
        ha,
        case_id,
        files=[("a.pdf", sf.text_pdf(["one"])), ("b.png", sf.png())],
        visibility="counsel_shared",
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["draft"] is False and len(body["attachments"]) == 2
    assert all(a["linked"] is False and a["doc_type"] == "correspondence" for a in body["attachments"])
    with world.Session() as s:
        docs = s.scalars(
            sa.select(Document).where(Document.ref_no.in_([a["ref_no"] for a in body["attachments"]]))
        ).all()
        assert {DocKind(d.kind) for d in docs} == {DocKind.ATTACHMENT}
        assert {DocGroup(d.doc_group) for d in docs} == {DocGroup.INTERNAL}
        assert {d.visibility.value for d in docs} == {"counsel_shared"}
        assert {d.sourcetrace_status.value for d in docs} == {"not_applicable"}
        assert len(w.audits(s, "document.uploaded", case_id)) == 2
    # absent from the Documents tab, present on the note
    tab = api.get(f"/cases/{case_id}/documents", headers=ha).json()
    assert {i["ref_no"] for i in tab["items"]}.isdisjoint({a["ref_no"] for a in body["attachments"]})
    assert len(api.get(f"/notes/{body['ref_no'].replace('/', '-')}", headers=ha).json()["attachments"]) == 2


def test_one_infected_file_refuses_the_call(api, world, case_id):
    ha = w.login(api, "edu_admin")
    r = _note(
        api,
        ha,
        case_id,
        files=[("a.pdf", sf.text_pdf(["ok"])), ("b.pdf", sf.text_pdf(["x"]) + eicar_test_string())],
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "infected"
    with world.Session() as s:
        assert not w.case_notes(s, case_id)
        assert not s.scalars(sa.select(Document).where(Document.case_id == case_id)).all()
        assert len(w.audits(s, "document.upload_rejected")) == 1
        assert not w.audits(s, "note.added", case_id)


def test_limits(api, world, case_id):
    ha = w.login(api, "edu_admin")
    six = [(f"{i}.png", sf.png()) for i in range(6)]
    r = _note(api, ha, case_id, files=six)
    assert r.status_code == 400
    big = sf.text_pdf(["big"]) + b"0" * (MAX + 10)
    r = _note(api, ha, case_id, files=[("big.pdf", big)])
    assert r.status_code == 413
    r = _note(api, ha, case_id, files=[("x.exe", sf.exe())])
    assert r.status_code == 415
    r = _note(api, ha, case_id, body="x" * 20_001)
    assert r.status_code == 400
    with world.Session() as s:
        assert not w.case_notes(s, case_id)


def test_a_link_never_widens(api, world, case_id):
    ha = w.login(api, "edu_admin")
    private = ds.upload(
        api,
        ha,
        case_id,
        sf.text_pdf(["private memo"]),
        doc_type="correspondence",
        visibility="private_to_office",
    ).json()
    r = _note(api, ha, case_id, document_refs=[private["ref_no"]], visibility="counsel_shared")
    assert r.status_code == 201, r.text
    assert [a["linked"] for a in r.json()["attachments"]] == [True]
    # the file goes to the counsel: they see the note but not the private document
    with world.Session() as s:
        from aslms.domain.cases import Case

        w.send(s, world, "edu_off1", s.get(Case, case_id), "edu_counsel")
        s.commit()
    hc = w.login(api, "edu_counsel")
    items = api.get(f"/cases/{case_id}/notes", headers=hc).json()["items"]
    assert len(items) == 1 and items[0]["attachments"] == []
    # a link to a document of another case or an unknown one is refused
    r = _note(api, ha, case_id, document_refs=["ASLMS-EDU-DOC-2026-999999"])
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_document_ref"


def test_attachment_follows_its_note(api, world, case_id):
    ha = w.login(api, "edu_admin")
    r = _note(api, ha, case_id, files=[("a.pdf", sf.text_pdf(["one"]))])
    ref = r.json()["attachments"][0]["ref_no"]
    with world.Session() as s:
        doc_id = s.scalar(sa.select(Document.id).where(Document.ref_no == ref))
        assert (
            s.scalar(sa.select(sa.func.count()).select_from(CaseNote).where(CaseNote.case_id == case_id)) == 1
        )
    r = api.patch(f"/documents/{doc_id}", headers=ha, json={"visibility": "private_to_office"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "attachment_follows_note"
    r = api.post(f"/documents/{doc_id}/archive", headers=ha, json={"reason": "not needed any more"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "attachment_follows_note"
