"""Draft notes of the holder (design custody-workflow, decisions 12, 13, 26): a draft has no `ref_no` and is seen
only by its author; the author edits and deletes it; drafts take links only; a send finalises every draft in
order in the send's transaction; a meanwhile-corrected target is retargeted; an edit racing a send gets 409
`draft_finalised`; at most `NOTE_DRAFTS_MAX` drafts."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.cases import Case
from aslms.domain.documents import Document
from aslms.domain.reference import EventType
from aslms.domain.workflow import CaseNoteAttachment, CaseNoteDraft, CustodyHistory
from aslms.services import custody, notes
from aslms.services.workflow_common import WorkflowError
from tests import samplefiles as sf
from tests.db import docs_support as ds
from tests.db import workflow_support as w


@pytest.fixture()
def api(world, tmp_path):
    w.widen(world)
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture()
def held(api, world):
    """An EDU case held by the HEALTH officer (sent by the EDU officer)."""
    with world.Session() as s:
        case = w.claimed_case(s, world)
        w.send(s, world, "edu_off1", case, "health_off")
        s.commit()
        return case.id


def _post_note(api, headers, case_id, body="a draft", **fields):
    data = {"kind": "general", "body": body, "visibility": "case_scope", **fields}
    return api.post(f"/cases/{case_id}/notes", headers=headers, data=data)


def test_holder_note_is_a_private_draft(api, world, held):
    hh = w.login(api, "health_off")
    r = _post_note(api, hh, held, body="my working draft")
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["draft"] is True and "ref_no" not in d
    for key in ("oversight", "edu_admin"):
        h = w.login(api, key)
        assert api.get(f"/cases/{held}/notes", headers=h).json()["total"] == 0
        if key == "edu_admin":
            assert api.get(f"/cases/{held}/notes/drafts", headers=h).json()["items"] == []
            assert api.patch(f"/notes/drafts/{d['id']}", headers=h, json={"body": "x"}).status_code == 404
            assert api.delete(f"/notes/drafts/{d['id']}", headers=h).status_code == 404
    mine = api.get(f"/cases/{held}/notes/drafts", headers=hh).json()["items"]
    assert [x["body"] for x in mine] == ["my working draft"]
    assert api.get(f"/cases/{held}", headers=hh).json()["counts"]["my_drafts"] == 1
    # the author edits, then deletes
    r = api.patch(f"/notes/drafts/{d['id']}", headers=hh, json={"body": "edited", "kind": "opinion"})
    assert r.status_code == 200 and r.json()["body"] == "edited" and r.json()["kind"] == "opinion"
    assert api.delete(f"/notes/drafts/{d['id']}", headers=hh).status_code == 204
    assert api.get(f"/cases/{held}/notes/drafts", headers=hh).json()["items"] == []
    with world.Session() as s:
        actions = [a.action for a in w.audits(s, "note.draft_saved", held)]
        actions += [a.action for a in w.audits(s, "note.draft_updated", held)]
        actions += [a.action for a in w.audits(s, "note.draft_deleted", held)]
        assert actions == ["note.draft_saved", "note.draft_updated", "note.draft_deleted"]
        assert all("edited" not in str(a.after) for a in w.audits(s, "note.draft_updated", held))
        assert not w.events(s, held, EventType.NOTE_ADDED)


def test_drafts_take_links_only(api, world, held):
    hh = w.login(api, "health_off")
    r = api.post(
        f"/cases/{held}/notes",
        headers=hh,
        data={"kind": "general", "body": "with a file", "visibility": "case_scope"},
        files={"files": ("x.pdf", sf.text_pdf(["x"]))},
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "drafts_take_links_only"
    doc = ds.upload(api, hh, held, sf.text_pdf(["reply"]), doc_type="correspondence").json()
    r = _post_note(api, hh, held, body="see the reply", document_refs=[doc["ref_no"]])
    assert r.status_code == 201 and [x["ref_no"] for x in r.json()["documents"]] == [doc["ref_no"]]


def test_send_finalises_every_draft_in_order(api, world, held):
    hh = w.login(api, "health_off")
    doc = ds.upload(api, hh, held, sf.text_pdf(["annexure"]), doc_type="correspondence").json()
    for i in range(3):
        refs = [doc["ref_no"]] if i == 1 else []
        assert _post_note(api, hh, held, body=f"draft {i}", document_refs=refs).status_code == 201
    with world.Session() as s:
        holder_leg = w.holder(s, s.get(Case, held)).current_leg_id
        target = world.membership(s, "fin_off").id
    r = api.post(
        f"/cases/{held}/custody/send",
        headers=hh,
        json={"to_membership": str(target), "pending_action": "report", "remark": "over to finance"},
    )
    assert r.status_code == 201, r.text
    refs = r.json()["finalised_notes"]
    assert len(refs) == 3
    with world.Session() as s:
        ns = w.case_notes(s, held)
        assert [n.body for n in ns] == ["draft 0", "draft 1", "draft 2"]
        assert [n.seq_no for n in ns] == [1, 2, 3] and [n.ref_no for n in ns] == refs
        assert all(n.ref_no.startswith("ASLMS/HEALTH/NOTE/") for n in ns)
        assert all(n.drafted_at is not None and n.custody_leg_id == holder_leg for n in ns)
        assert all(n.actor_user_id == w.uid(world, "health_off") for n in ns)
        att = s.scalars(sa.select(CaseNoteAttachment).where(CaseNoteAttachment.note_id == ns[1].id)).all()
        assert [a.document_id for a in att] == [
            s.scalar(sa.select(Document.id).where(Document.ref_no == doc["ref_no"]))
        ]
        assert not w.drafts(s, held)
        evs = [e for e in w.events(s, held, EventType.NOTE_ADDED)]
        assert len(evs) == 3 and all(e.payload["finalised"] is True for e in evs)
        assert len(w.audits(s, "note.finalised", held)) == 3
    # the EDU admin reads them now
    listed = api.get(f"/cases/{held}/notes", headers=w.login(api, "edu_admin")).json()
    assert [n["ref_no"] for n in listed["items"]] == refs
    assert all(n["drafted_at"] for n in listed["items"])


def test_a_failure_after_finalisation_rolls_back_both(world, held, monkeypatch):
    with world.Session() as s:
        w.note(s, world, "health_off", s.get(Case, held))
        s.commit()

    def boom(*a, **k):
        raise RuntimeError("forced")

    monkeypatch.setattr(custody, "emit_event", boom)
    with world.Session() as s:
        case = s.get(Case, held)
        n_legs = len(w.legs(s, case))
        with pytest.raises(RuntimeError):
            w.send(s, world, "health_off", case, "fin_off")
        s.rollback()
    with world.Session() as s:
        case = s.get(Case, held)
        assert len(w.drafts(s, held)) == 1 and not w.case_notes(s, held)
        assert len(w.legs(s, case)) == n_legs
        assert w.holder(s, case).holder_user_id == w.uid(world, "health_off")


def test_draft_correction_of_a_meanwhile_corrected_note_supersedes_the_latest(world, held):

    with world.Session() as s:
        case = s.get(Case, held)
        original, is_draft = w.note(s, world, "edu_admin", case, body="original")
        assert not is_draft
        # the holder drafts a correction of the original... only the author or a nodal officer may correct
        with pytest.raises(WorkflowError) as e:
            w.note(s, world, "health_off", case, body="fix", supersedes=str(original.id), kind=None)
        assert e.value.code == "not_author"
        # the EDU admin recalls and, as holder, drafts a correction
        w.recall(s, world, "edu_admin", case)
        corr_draft, is_draft = w.note(
            s, world, "edu_admin", case, body="correction draft", supersedes=str(original.id), kind=None
        )
        assert is_draft
        # meanwhile the EDU head (a whole-department membership, not the holder) corrects the original
        later, _ = w.note(
            s, world, "edu_head", case, body="head's correction", supersedes=str(original.id), kind=None
        )
        w.send(s, world, "edu_admin", case, "edu_off2")
        final = [n for n in w.case_notes(s, held) if n.body == "correction draft"][0]
        assert final.supersedes_id == later.id
        audit = [a for a in w.audits(s, "note.finalised", held) if a.entity_id == final.id][0]
        assert audit.after["supersedes_retargeted"] is True
        s.rollback()


def test_edit_racing_a_send_gets_draft_finalised(world, held):

    with world.Session() as s:
        draft, _ = w.note(s, world, "health_off", s.get(Case, held), body="racing")
        s.commit()
        draft_id = draft.id
    a = world.Session()
    try:
        seen = a.get(CaseNoteDraft, draft_id)  # session A has read the draft (kept: the identity map is weak)
        assert seen is not None
        with world.Session() as b:
            w.send(b, world, "health_off", b.get(Case, held), "fin_off")
            b.commit()
        actor, user = world.actor(a, "health_off")
        with pytest.raises(WorkflowError) as e:
            notes.update_draft(a, actor, user, draft_id, body="too late")
        assert e.value.code == "draft_finalised" and e.value.http_status == 409
        a.rollback()
    finally:
        a.close()


def test_too_many_drafts(world, held):

    with world.Session() as s:
        case = s.get(Case, held)
        w.note(s, world, "health_off", case, max_drafts=2)
        w.note(s, world, "health_off", case, max_drafts=2)
        with pytest.raises(WorkflowError) as e:
            w.note(s, world, "health_off", case, max_drafts=2)
        assert e.value.code == "too_many_drafts" and e.value.http_status == 409
        s.rollback()


def test_holder_leg_recorded_on_the_draft(world, held):

    with world.Session() as s:
        case = s.get(Case, held)
        draft, _ = w.note(s, world, "health_off", case)
        leg = s.get(CustodyHistory, draft.custody_leg_id)
        assert leg.reason == "sent" and leg.holder_user_id == w.uid(world, "health_off")
        assert (
            draft.membership_id == world.membership(s, "health_off").id and draft.ref_no
            if hasattr(draft, "ref_no")
            else True
        )
        s.rollback()


def test_the_exit_step_finalises_the_leavers_drafts(world):
    """`reassigned_on_exit` (owner review 2026-10-07): the leaver's drafts become permanent with the move."""
    from aslms.services import memberships

    with world.Session() as s:
        case = w.claimed_case(s, world)  # held by off1
        w.note(s, world, "edu_off1", case, body="leaver's draft")
        actor, admin = world.actor(s, "edu_admin")
        m = world.membership(s, "edu_off1")
        p = memberships.exit_preview(s, admin, m)
        assert p["counts"]["drafts"] == 1
        target = str(world.membership(s, "edu_off2").id)
        result = memberships.end(
            s,
            actor,
            admin,
            m,
            reason="transferred out",
            assignments=[{"key": i["key"], "to_membership": target} for i in p["items"]],
            items_fingerprint=p["items_fingerprint"],
        )
        assert result.counts["notes_finalised"] == 1
        assert not w.drafts(s, case.id)
        n = w.case_notes(s, case.id)[0]
        assert n.body == "leaver's draft" and n.actor_user_id == w.uid(world, "edu_off1")
        leg = w.legs(s, case)[-1]
        assert leg.reason == "reassigned_on_exit" and leg.remark
        assert leg.holder_membership_id == world.membership(s, "edu_off2").id
        s.rollback()
