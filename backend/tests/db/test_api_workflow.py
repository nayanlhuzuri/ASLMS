"""The workflow API (design custody-workflow, "API"): function checks (403), an invisible case (404), the response
shapes, the remark hidden from a recommended-department reader, the size guard on the notes path (413), the
held / sent / summary views and audit rows without note or remark text."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aslms.domain.events import AuditLog
from tests import samplefiles as sf
from tests.db import alerts_support as h
from tests.db import docs_support as ds
from tests.db import workflow_support as w

MAX = 10_000
REMARK = "remark text that must stay out of the audit"
BODY = "note text that must stay out of the audit"


@pytest.fixture()
def api(world, tmp_path):
    w.widen(world)
    client = ds.make_api(world, tmp_path, upload_max_bytes=MAX)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture()
def case_id(api, world):
    """An EDU case allotted to off1 and recommended to HEALTH (HEALTH sees it as a recommended reader)."""
    with world.Session() as s:
        case = w.claimed_case(s, world)
        h.recommend(s, world, case, "HEALTH")
        s.commit()
        return case.id


def _send(api, headers, case_id, world, to, **extra):
    with world.Session() as s:
        target = world.membership(s, to).id
    body = {"to_membership": str(target), "pending_action": "report", "remark": REMARK, **extra}
    return api.post(f"/cases/{case_id}/custody/send", headers=headers, json=body)


def test_codes(api):
    r = api.get("/workflow/codes", headers=w.login(api, "edu_off1"))
    assert r.status_code == 200
    body = r.json()
    kinds = {k["code"]: k["selectable"] for k in body["note_kinds"]}
    assert kinds["hand_over"] and kinds["opinion"] and kinds["counsel_advice"] and not kinds["correction"]
    actions = {a["code"]: a for a in body["pending_actions"]}
    assert actions["parawise_comments"]["label"] == "Parawise comments" and not actions["none"]["sendable"]
    assert len(body["stages"]) == 17
    assert {r["code"] for r in body["custody_reasons"]} >= {"sent", "recalled", "reassigned_on_exit"}
    labels = {k["code"]: k["label"] for k in body["note_kinds"]}
    assert labels["hearing"] == "Hearing note"


def test_send_recall_and_the_custody_tab(api, world, case_id):
    h1 = w.login(api, "edu_off1")
    r = _send(api, h1, case_id, world, "fin_off", due_date=str(w.in_days(5)))
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["leg"]["reason"] == "sent" and out["leg"]["remark"] == REMARK
    assert out["leg"]["holder_designation"] == "Under Secretary"
    assert out["leg"]["pending_action_label"] == "Report"
    tab = api.get(f"/cases/{case_id}/custody", headers=h1).json()
    assert tab["total"] == 3 and [l["reason"] for l in tab["legs"]] == ["claimed", "allotted", "sent"]
    assert tab["card"]["holder_office"]["code"] == "FIN" and tab["card"]["remark"] == REMARK
    assert tab["card"]["sent_by"]["office_code"] == "EDU" and tab["card"]["leg_seq_no"] == 3
    # the recommended HEALTH admin sees the legs but not the remark
    hh = w.login(api, "health_admin")
    tab = api.get(f"/cases/{case_id}/custody", headers=hh).json()
    assert tab["card"]["remark"] is None and all(l["remark"] is None for l in tab["legs"])
    assert api.get(f"/cases/{case_id}", headers=hh).json()["custody"]["remark"] is None
    # recall by the EDU admin
    ha = w.login(api, "edu_admin")
    r = api.post(f"/cases/{case_id}/custody/recall", headers=ha, json={"remark": REMARK})
    assert r.status_code == 201 and r.json()["card"]["holder_user"]["id"] == str(w.uid(world, "edu_admin"))
    r = api.post(f"/cases/{case_id}/custody/recall", headers=ha, json={"remark": REMARK})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "unchanged"
    # errors carry {code, message}
    r = _send(api, ha, case_id, world, "root")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_target"
    r = _send(api, h1, case_id, world, "health_dir")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "not_in_control"
    sent = api.get("/custody/sent", headers=h1).json()
    assert sent["total"] == 1 and sent["items"][0]["case"]["id"] == str(case_id)


def test_invisible_case_is_404(api, world, case_id):
    hf = w.login(api, "fin_off")
    for path in ("custody", "stages", "notes"):
        assert api.get(f"/cases/{case_id}/{path}", headers=hf).status_code == 404
    assert _send(api, hf, case_id, world, "edu_off2").status_code == 404
    assert (
        api.post(f"/cases/{case_id}/custody/recall", headers=hf, json={"remark": "mine"}).status_code == 404
    )
    assert api.post(f"/cases/{case_id}/stages", headers=hf, json={"stage": "closed"}).status_code == 404
    r = api.post(
        f"/cases/{case_id}/notes",
        headers=hf,
        data={"kind": "general", "body": "x", "visibility": "case_scope"},
    )
    assert r.status_code == 404
    assert api.get("/cases/ASLMS-GOA-CASE-2099-000001/custody", headers=hf).status_code == 404


def test_function_checks(api, world, case_id):
    hc = w.login(api, "edu_counsel")  # no stages.set, no custody.track
    assert api.post(f"/cases/{case_id}/stages", headers=hc, json={"stage": "closed"}).status_code == 403
    assert api.get("/custody/summary", headers=hc).status_code == 403
    assert api.get("/custody/held?scope=owned", headers=w.login(api, "edu_off1")).status_code == 403
    ho = w.login(api, "oversight")  # no notes.add
    r = api.post(
        f"/cases/{case_id}/notes",
        headers=ho,
        data={"kind": "general", "body": "x", "visibility": "case_scope"},
    )
    assert r.status_code == 403
    assert api.get(f"/cases/{case_id}/notes/drafts", headers=ho).status_code == 403
    r = api.post(
        f"/cases/{case_id}/custody/recall", headers=w.login(api, "edu_off2"), json={"remark": "mine"}
    )
    assert r.status_code in (403, 404)


def test_held_and_summary(api, world, case_id):
    h1 = w.login(api, "edu_off1")
    me = api.get("/custody/held?scope=me", headers=h1).json()
    assert me["total"] == 1 and me["items"][0]["card"]["holder_user"]["id"] == str(w.uid(world, "edu_off1"))
    assert _send(api, h1, case_id, world, "health_off", due_date=str(w.in_days(1))).status_code == 201
    assert api.get("/custody/held?scope=me", headers=h1).json()["total"] == 0
    hh = w.login(api, "health_off")
    assert api.get("/custody/held?scope=me", headers=hh).json()["total"] == 1
    assert api.get("/custody/held?scope=office", headers=w.login(api, "health_admin")).json()["total"] == 1
    ha = w.login(api, "edu_admin")
    owned = api.get("/custody/held?scope=owned", headers=ha).json()
    assert owned["total"] == 1 and owned["items"][0]["card"]["holder_office"]["code"] == "HEALTH"
    assert api.get("/custody/held?scope=owned&holder_department=FIN", headers=ha).json()["total"] == 0
    assert api.get("/custody/held?scope=owned&overdue=true", headers=ha).json()["total"] == 0
    summary = api.get("/custody/summary", headers=ha).json()
    edu = next(d for d in summary["departments"] if d["code"] == "EDU")
    assert edu["held"] == 1 and edu["due_soon"] == 1 and edu["overdue"] == 0
    assert edu["by_holder_department"] == [{"code": "HEALTH", "held": 1, "due_soon": 1, "overdue": 0}]
    assert edu["by_holder"][0]["office_code"] == "HEALTH"
    assert api.get("/custody/summary?department=HEALTH", headers=ha).status_code == 403
    rec = api.get("/custody/recipients", headers=h1).json()
    assert {"EDU", "HEALTH", "FIN"} <= {d["code"] for d in rec["departments"]}
    people = api.get("/custody/recipients?department=HEALTH", headers=h1).json()
    names = {p["full_name"] for p in people["items"]}
    assert {"Health Off", "Health Admin", "Health Dir"} <= names
    assert api.get("/custody/recipients?department=GOA", headers=h1).status_code == 400
    q = api.get("/custody/recipients?department=HEALTH&q=Deputy", headers=h1).json()
    assert [p["full_name"] for p in q["items"]] == ["Health Dir"]


def test_notes_endpoints_and_audit_without_text(api, world, case_id):
    ha = w.login(api, "edu_admin")
    r = api.post(
        f"/cases/{case_id}/notes",
        headers=ha,
        data={"kind": "decision", "body": BODY, "visibility": "case_scope"},
    )
    assert r.status_code == 201 and r.json()["draft"] is False
    note = r.json()
    assert note["author"]["office_code"] == "EDU" and note["kind_label"]
    got = api.get(f"/notes/{note['ref_no'].replace('/', '-')}", headers=ha)
    assert got.status_code == 200 and got.json()["body"] == BODY
    assert api.get(f"/notes/{note['id']}", headers=w.login(api, "fin_off")).status_code == 404
    assert api.get(f"/cases/{case_id}/notes?kind=decision", headers=ha).json()["total"] == 1
    assert api.get(f"/cases/{case_id}/notes?kind=general", headers=ha).json()["total"] == 0
    assert api.get(f"/cases/{case_id}", headers=ha).json()["counts"]["notes"] == 1
    assert _send(api, w.login(api, "edu_off1"), case_id, world, "health_off").status_code == 201
    hh = w.login(api, "health_off")
    d = api.post(
        f"/cases/{case_id}/notes",
        headers=hh,
        data={"kind": "general", "body": BODY, "visibility": "case_scope"},
    ).json()
    assert api.patch(f"/notes/drafts/{d['id']}", headers=hh, json={"body": BODY + "!"}).status_code == 200
    assert _send(api, hh, case_id, world, "fin_off").json()["finalised_notes"]
    with world.Session() as s:
        rows = s.scalars(sa.select(AuditLog).where(AuditLog.case_id == case_id)).all()
        actions = {r.action for r in rows}
        assert {
            "note.added",
            "note.draft_saved",
            "note.draft_updated",
            "note.finalised",
            "custody.sent",
        } <= actions
        for r in rows:
            text = str(r.before) + str(r.after)
            assert BODY not in text and REMARK not in text


def test_size_guard_on_the_notes_path(api, world, case_id):
    ha = w.login(api, "edu_admin")
    huge = sf.text_pdf(["x"]) + b"0" * (5 * MAX + 70_000)
    r = api.post(
        f"/cases/{case_id}/notes",
        headers=ha,
        data={"kind": "general", "body": "big", "visibility": "case_scope"},
        files={"files": ("big.pdf", huge)},
    )
    assert r.status_code == 413 and r.json()["detail"]["code"] == "too_large"
