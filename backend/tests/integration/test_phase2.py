"""Phase 2 through the API against Postgres: custody derived from claim / allotment / requests / hand-over,
referral scope, guided stages, the append-only notes trail, the Case Assistant's privacy, and SourceTrace
ingestion eligibility with a fake knowledge service."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.core.time import today_ist
from aslms.domain.alerts import Alert, AlertKind, NextDate, NextDateSource
from aslms.domain.cases import Case
from aslms.domain.documents import Document, DocumentKind, SourceTraceStatus
from aslms.domain.sourcetrace import SourceTraceIngestion
from tests.integration.helpers import auth, login


def _claimed_case(client: TestClient, edu: dict) -> str:
    case_id = client.get("/api/v1/inbox/recommended", headers=edu).json()["items"][0]["case"]["id"]
    assert client.post(f"/api/v1/cases/{case_id}/claim", json={}, headers=edu).status_code == 200
    return case_id


def test_custody_follows_claim_allotment_and_requests(client: TestClient, world, db: Session) -> None:
    from aslms.services import alerts

    edu = auth(login(client, "edu.admin@t.in"))
    health = auth(login(client, "health.admin@t.in"))
    dse = auth(login(client, "dse@t.in"))
    case_id = _claimed_case(client, edu)

    card = client.get(f"/api/v1/cases/{case_id}", headers=health).json()  # tracking card: custody is public
    assert card["in_scope"] is False and card["custody"]["holder_office"]["code"] == "EDU"
    assert card["custody"]["pending_action"].startswith("examine")

    client.post(f"/api/v1/cases/{case_id}/allot", json={"unit_office_id": str(world["dse"].id)}, headers=edu)
    assert (
        client.get(f"/api/v1/cases/{case_id}", headers=edu).json()["custody"]["holder_office"]["code"]
        == "DSE"
    )

    # EDU asks DSE for a report, due tomorrow → custody with DSE, alert to DSE users
    due = (today_ist() + timedelta(days=1)).isoformat()
    r = client.post(
        f"/api/v1/cases/{case_id}/requests",
        headers=edu,
        json={
            "kind": "report",
            "to_office_id": str(world["dse"].id),
            "subject": "Parawise comments",
            "due_date": due,
        },
    )
    assert r.status_code == 201, r.text
    req = r.json()
    cust = client.get(f"/api/v1/cases/{case_id}", headers=edu).json()["custody"]
    assert (
        cust["holder_office"]["code"] == "DSE"
        and cust["due_date"] == due
        and "Parawise" in cust["pending_action"]
    )
    inbox = client.get("/api/v1/requests?direction=incoming", headers=dse).json()
    assert inbox["total"] == 1 and inbox["items"][0]["subject"] == "Parawise comments"
    alerts.generate(db)
    db.commit()
    assert (
        db.scalar(select(sa.func.count()).select_from(Alert).where(Alert.kind == AlertKind.REQUEST_DUE)) == 1
    )
    assert client.get("/api/v1/alerts", headers=dse).json()["items"][0]["kind"] == "request_due"

    # only the receiving office answers; custody returns to the requester
    assert (
        client.post(f"/api/v1/requests/{req['id']}/answer", json={"body": "done"}, headers=health).status_code
        == 403
    )
    r = client.post(f"/api/v1/requests/{req['id']}/answer", json={"body": "Comments attached."}, headers=dse)
    assert r.status_code == 200 and r.json()["status"] == "answered" and r.json()["messages"][0]["is_answer"]
    assert (
        client.get(f"/api/v1/cases/{case_id}", headers=edu).json()["custody"]["holder_office"]["code"]
        == "EDU"
    )

    trail = client.get(f"/api/v1/cases/{case_id}/custody/history", headers=health).json()
    assert [t["reason"] for t in trail] == ["claim", "allot", "request_sent", "request_answered"]
    assert [t["seq_no"] for t in trail] == [1, 2, 3, 4]


def test_referral_request_opens_scope_to_the_other_department(client: TestClient, world) -> None:
    edu = auth(login(client, "edu.admin@t.in"))
    health = auth(login(client, "health.admin@t.in"))
    case_id = _claimed_case(client, edu)
    assert client.get(f"/api/v1/cases/{case_id}", headers=health).json()["in_scope"] is False
    r = client.post(
        f"/api/v1/cases/{case_id}/requests",
        headers=edu,
        json={"kind": "views", "to_office_id": str(world["health"].id), "subject": "Views of the department"},
    )
    assert r.status_code == 201
    assert client.get(f"/api/v1/cases/{case_id}", headers=health).json()["in_scope"] is True
    # the requester withdraws; custody comes back
    rid = r.json()["id"]
    assert (
        client.post(f"/api/v1/requests/{rid}/withdraw", json={"reason": "not needed"}, headers=edu).json()[
            "status"
        ]
        == "withdrawn"
    )
    assert (
        client.get(f"/api/v1/cases/{case_id}", headers=edu).json()["custody"]["holder_office"]["code"]
        == "EDU"
    )


def test_stages_are_guided_and_gaps_reported(client: TestClient, world) -> None:
    edu = auth(login(client, "edu.admin@t.in"))
    case_id = _claimed_case(client, edu)
    assert client.get("/api/v1/stages", headers=edu).json()[0] == "notice_received"
    r = client.post(f"/api/v1/cases/{case_id}/stages", json={"stage": "notice_received"}, headers=edu)
    assert r.status_code == 201 and r.json()["skipped"] == []
    r = client.post(
        f"/api/v1/cases/{case_id}/stages", json={"stage": "affidavit_filed", "note": "filed"}, headers=edu
    )
    assert "records_received" in r.json()["skipped"] and "instructions_sent" in r.json()["skipped"]
    assert client.get(f"/api/v1/cases/{case_id}", headers=edu).json()["stage"] == "affidavit_filed"
    cs = auth(login(client, "cs@t.in"))
    assert (
        client.post(f"/api/v1/cases/{case_id}/stages", json={"stage": "complied"}, headers=cs).status_code
        == 403
    )


def test_notes_trail_append_only_corrections_visibility(client: TestClient, world, db: Session) -> None:
    edu = auth(login(client, "edu.admin@t.in"))
    counsel = auth(login(client, "counsel@t.in"))
    case_id = _claimed_case(client, edu)

    r = client.post(
        f"/api/v1/cases/{case_id}/notes",
        headers=edu,
        data={"body": "Instructions sent to counsel.", "kind": "instruction", "visibility": "counsel_shared"},
    )
    assert r.status_code == 201, r.text
    n1 = r.json()
    assert n1["seq_no"] == 1 and n1["author_office"] == "EDU" and n1["custody_leg_seq"] == 1
    r = client.post(
        f"/api/v1/cases/{case_id}/notes",
        headers=edu,
        data={"body": "Internal view on the matter.", "kind": "opinion", "visibility": "private_to_office"},
        files=[("files", ("view.pdf", b"%PDF-1.4 internal view", "application/pdf"))],
    )
    n2 = r.json()
    assert n2["seq_no"] == 2 and n2["attachments"][0]["filename"] == "view.pdf"
    r = client.post(
        f"/api/v1/cases/{case_id}/notes",
        headers=edu,
        data={
            "body": "Correction: instructions sent on 25 Sep.",
            "kind": "instruction",
            "visibility": "counsel_shared",
            "supersedes_id": n1["id"],
        },
    )
    assert r.json()["supersedes_seq"] == 1

    mine = client.get(f"/api/v1/cases/{case_id}/notes", headers=edu).json()
    assert [n["seq_no"] for n in mine] == [1, 2, 3] and mine[0]["superseded_by"] == [3]
    theirs = client.get(f"/api/v1/cases/{case_id}/notes", headers=counsel).json()
    assert [n["seq_no"] for n in theirs] == [1, 3]  # the private note is not visible to counsel

    with pytest.raises(sa.exc.DBAPIError, match="append-only"):
        db.execute(sa.text("UPDATE case_notes SET body = 'tampered' WHERE id = :id"), {"id": n1["id"]})
    db.rollback()


def test_handover_writes_a_note_and_moves_custody(client: TestClient, world) -> None:
    edu = auth(login(client, "edu.admin@t.in"))
    case_id = _claimed_case(client, edu)
    r = client.post(
        f"/api/v1/cases/{case_id}/handover",
        headers=edu,
        json={
            "to_office_id": str(world["dse"].id),
            "note": "Please prepare the affidavit.",
            "pending_action": "draft affidavit",
        },
    )
    assert r.status_code == 201 and r.json()["kind"] == "handover"
    card = client.get(f"/api/v1/cases/{case_id}", headers=edu).json()
    assert (
        card["custody"]["holder_office"]["code"] == "DSE"
        and card["custody"]["pending_action"] == "draft affidavit"
    )
    r = client.post(
        f"/api/v1/cases/{case_id}/handover",
        headers=edu,
        json={"to_office_id": str(world["dse"].id), "note": " "},
    )
    assert r.status_code == 422


def test_assistant_conversations_are_private(client: TestClient, world) -> None:
    edu = auth(login(client, "edu.admin@t.in"))
    head_case = _claimed_case(client, edu)
    r = client.post(
        f"/api/v1/cases/{head_case}/assistant", json={"question": "What did the court direct?"}, headers=edu
    )
    assert r.status_code == 200
    conv = r.json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    assert "not connected" in conv["messages"][1]["content"]
    other = auth(login(client, "cs@t.in"))
    assert client.get(f"/api/v1/assistant/conversations/{conv['id']}", headers=other).status_code == 404
    assert client.get(f"/api/v1/cases/{head_case}/assistant", headers=other).json() == []
    # a "not connected" reply cannot become a note
    r = client.post(f"/api/v1/assistant/messages/{conv['messages'][1]['id']}/to-note", json={}, headers=edu)
    assert r.status_code == 403
    assert client.get("/api/v1/assistant/status", headers=edu).json()["connected"] is False


class FakeKnowledge:
    def __init__(self):
        self.sent: list[dict] = []

    async def ingest(self, *, document_id, content, mime, metadata):
        self.sent.append(metadata)
        return f"st-{document_id[:8]}"

    async def next_date(self, *, sourcetrace_ref, order_date):
        return {
            "next_date": (order_date + timedelta(days=14)).isoformat(),
            "confidence": 0.8,
            "evidence": "after two weeks",
        }

    async def ask(self, *, question, context):
        return {"answer": "stub", "citations": []}


def test_sourcetrace_sends_only_court_records_and_filings(client: TestClient, world, db: Session) -> None:
    from aslms.domain.documents import DocType
    from aslms.services import orders, sourcetrace, storage

    edu = auth(login(client, "edu.admin@t.in"))
    case_id = _claimed_case(client, edu)
    # an internal document and a note attachment: never eligible
    client.post(
        f"/api/v1/cases/{case_id}/documents",
        headers=edu,
        data={"doc_type": "parawise_comments"},
        files={"file": ("pc.pdf", b"%PDF-1.4 internal", "application/pdf")},
    )
    client.post(
        f"/api/v1/cases/{case_id}/notes",
        headers=edu,
        data={"body": "see attached"},
        files=[("files", ("att.pdf", b"%PDF-1.4 note attachment", "application/pdf"))],
    )
    # a court order with a period direction
    case = db.get(Case, case_id)
    from aslms.domain.documents import Order, OrderKind

    order = Order(case_id=case.id, order_no="1", order_date=date(2026, 9, 1), kind=OrderKind.INTERIM)
    db.add(order)
    db.flush()
    doc, _ = storage.store_system_document(
        db,
        b"%PDF-1.4 order: list after two weeks",
        kind=DocumentKind.COURT_ORDER,
        doc_type=DocType.ORDER,
        case_id=case.id,
        doc_date=order.order_date,
    )
    order.document_id = doc.id
    orders.apply_next_date_from_order(db, case, order, "Issue notice. List after two weeks.")
    db.commit()

    # mark eligible documents pending by hand (mark_candidates only runs when SOURCETRACE_ENABLED)
    db.execute(
        sa.update(Document)
        .where(sourcetrace.eligible_clause())
        .values(sourcetrace_status=SourceTraceStatus.PENDING)
    )
    ks = FakeKnowledge()
    out = sourcetrace.ingest_pending(db, ks)
    db.commit()
    assert out == {"ingested": 1, "failed": 0, "gave_up": 0}
    assert ks.sent[0]["cnr"] == case.cnr and ks.sent[0]["document_type"] == "order"
    assert db.scalar(select(sa.func.count()).select_from(SourceTraceIngestion)) == 1
    assert db.get(Document, doc.id).sourcetrace_status == SourceTraceStatus.INGESTED

    res = sourcetrace.read_period_next_dates(db, ks)
    db.commit()
    assert res["read"] == 1
    nd = db.scalar(
        select(NextDate).where(NextDate.case_id == case.id, NextDate.source == NextDateSource.ORDER_PERIOD)
    )
    assert nd.next_date == date(2026, 9, 15) and nd.needs_review is True  # advisory: a person confirms
