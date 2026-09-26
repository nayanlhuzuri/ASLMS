"""End-to-end through the HTTP API against Postgres: sign-in with OTP, ingestion of a real cause list,
recommend → claim, scope enforcement, watcher, transfer, allotment, documents, alerts, search, reports, audit,
refresh-token rotation and idempotency."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aslms.core.time import today_ist
from aslms.domain.alerts import Alert, AlertKind
from aslms.domain.cases import Case
from aslms.domain.causelists import CauseListSource
from aslms.domain.events import AuditLog, Event, EventType
from aslms.domain.ownership import Recommendation
from aslms.integration.antivirus import EICAR
from aslms.integration.email import ConsoleMailer
from tests.integration.helpers import PW, auth, login

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def test_ingestion_is_idempotent(world, db: Session) -> None:
    from aslms.services import causelists

    st = world["stats"]
    assert st.entries_new == 16 and st.cases_new == 16 and st.with_cnr == 16
    assert st.recommendations == world["n_rec"] >= 3
    again, _ = causelists.ingest_pdf(
        db,
        (FIX / "ghc_lawazima_01-09-2025.pdf").read_bytes(),
        source=CauseListSource.LOCAL_DIR,
        filename="Lawazima_01-09-2025.pdf",
    )
    db.commit()
    assert again.entries_new == 0 and again.cases_new == 0
    assert db.scalar(select(func.count()).select_from(Case)) == 16
    listed = db.scalar(select(func.count()).select_from(Event).where(Event.type == EventType.LISTED))
    assert listed == 16


def test_login_requires_otp_and_bad_password_fails(client: TestClient) -> None:
    r = client.post("/api/v1/auth/login", json={"email": "edu.admin@t.in", "password": "wrong-password-1"})
    assert r.status_code == 401 and r.json()["error"] == "unauthorized"
    assert client.get("/api/v1/me").status_code == 401
    tokens = login(client, "edu.admin@t.in")
    me = client.get("/api/v1/me", headers=auth(tokens)).json()
    assert me["role"] == "dept_admin" and me["department"]["code"] == "EDU" and me["can_claim"]


def test_wrong_otp_is_counted(client: TestClient) -> None:
    ConsoleMailer.sent.clear()
    cid = client.post("/api/v1/auth/login", json={"email": "edu.admin@t.in", "password": PW}).json()[
        "challenge_id"
    ]
    for _ in range(5):
        assert (
            client.post("/api/v1/auth/verify", json={"challenge_id": cid, "code": "000000"}).status_code
            == 401
        )
    code = re.search(r"\b(\d{6})\b", ConsoleMailer.sent[-1]["body"]).group(1)
    assert client.post("/api/v1/auth/verify", json={"challenge_id": cid, "code": code}).status_code == 401


def test_refresh_rotation_and_reuse_detection(client: TestClient) -> None:
    t1 = login(client, "edu.admin@t.in")
    t2 = client.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]}).json()
    assert t2["refresh_token"] != t1["refresh_token"]
    # presenting the rotated token again ends every session
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]}).status_code == 401


def test_recommend_claim_scope_watch_transfer(client: TestClient, world, db: Session) -> None:
    edu = auth(login(client, "edu.admin@t.in"))
    health = auth(login(client, "health.admin@t.in"))

    rec = client.get("/api/v1/inbox/recommended", headers=edu).json()
    assert rec["total"] == world["n_rec"]
    first = rec["items"][0]
    assert first["band"] == "high" and first["signals"][0]["kind"] == "counsel_code"
    assert first["listing"]["list_date"] == "2025-09-01" and first["listing"]["court_no"] == "111"
    case_id = first["case"]["id"]
    assert first["case"]["in_scope"] is False  # recommended is not owned

    # not owned yet: the tracking card only
    body = client.get(f"/api/v1/cases/{case_id}", headers=edu).json()
    assert body["in_scope"] is False and "parties" not in body
    assert client.get(f"/api/v1/cases/{case_id}/orders", headers=edu).status_code == 403

    # claim → primary owner, contents visible
    r = client.post(f"/api/v1/cases/{case_id}/claim", json={"reason": "our matter"}, headers=edu)
    assert r.status_code == 200 and r.json()[0]["role"] == "primary"
    detail = client.get(f"/api/v1/cases/{case_id}", headers=edu).json()
    assert (
        detail["in_scope"] is True
        and detail["is_tracked"] is True
        and detail["owners"]["primary"]["code"] == "EDU"
    )
    assert client.get("/api/v1/inbox/claimed", headers=edu).json()["total"] == 1
    assert client.get("/api/v1/inbox/recommended", headers=edu).json()["total"] == world["n_rec"] - 1
    assert client.post(f"/api/v1/cases/{case_id}/claim", json={}, headers=edu).status_code == 409

    # another department sees only the card; claiming makes it a watcher
    assert client.get(f"/api/v1/cases/{case_id}", headers=health).json()["in_scope"] is False
    r = client.post(f"/api/v1/cases/{case_id}/claim", json={}, headers=health)
    assert r.json()[1]["role"] == "watcher"
    assert client.get(f"/api/v1/cases/{case_id}", headers=health).json()["in_scope"] is True

    # transfer the primary role to HEALTH; only the receiving department can accept
    r = client.post(
        f"/api/v1/cases/{case_id}/transfer",
        json={"to_office_id": str(world["health"].id), "reason": "health matter"},
        headers=edu,
    )
    assert r.status_code == 200
    transfer_id = r.json()["detail"]
    assert client.post(f"/api/v1/transfers/{transfer_id}/accept", json={}, headers=edu).status_code == 403
    incoming = client.get("/api/v1/inbox/transfers", headers=health).json()
    assert incoming[0]["direction"] == "incoming" and incoming[0]["status"] == "requested"
    assert client.post(f"/api/v1/transfers/{transfer_id}/accept", json={}, headers=health).status_code == 200
    owners = client.get(f"/api/v1/cases/{case_id}", headers=health).json()["owners"]
    assert owners["primary"]["code"] == "HEALTH" and owners["watchers"] == []

    audit_actions = set(db.scalars(select(AuditLog.action).where(AuditLog.case_id == case_id)))
    assert {"case.claim", "transfer.request", "transfer.accept"} <= audit_actions


def test_dismiss_with_suggestion_and_allotment_scopes(client: TestClient, world, db: Session) -> None:
    edu = auth(login(client, "edu.admin@t.in"))
    items = client.get("/api/v1/inbox/recommended", headers=edu).json()["items"]
    a, b = items[0]["case"]["id"], items[1]["case"]["id"]

    r = client.post(
        f"/api/v1/cases/{a}/dismiss",
        json={"reason": "not ours", "suggest_office_id": str(world["health"].id)},
        headers=edu,
    )
    assert r.status_code == 200
    health = auth(login(client, "health.admin@t.in"))
    hrec = client.get("/api/v1/inbox/recommended", headers=health).json()["items"]
    assert [x["origin"] for x in hrec] == ["suggestion"]
    # the engine does not re-recommend a dismissed case to the same department
    from aslms.services import admin

    admin.rescore_all(db)
    db.commit()
    assert (
        db.scalar(
            select(func.count())
            .select_from(Recommendation)
            .where(
                Recommendation.case_id == a,
                Recommendation.office_id == world["edu"].id,
                Recommendation.status == "recommended",
            )
        )
        == 0
    )

    # claim b and allot it to the directorate and an officer: each sees it, others in the department do not
    client.post(f"/api/v1/cases/{b}/claim", json={}, headers=edu)
    officer = world["users"]["edu_officer"]
    officer_auth = auth(login(client, "edu.officer@t.in"))
    dse_auth = auth(login(client, "dse@t.in"))
    assert client.get(f"/api/v1/cases/{b}", headers=officer_auth).json()["in_scope"] is False
    r = client.post(
        f"/api/v1/cases/{b}/allot",
        json={"unit_office_id": str(world["dse"].id), "officer_user_id": str(officer.id)},
        headers=edu,
    )
    assert r.status_code == 200 and r.json()[0]["unit"]["code"] == "DSE"
    assert client.get(f"/api/v1/cases/{b}", headers=officer_auth).json()["in_scope"] is True
    assert client.get(f"/api/v1/cases/{b}", headers=dse_auth).json()["in_scope"] is True
    # an officer cannot claim
    assert client.post(f"/api/v1/cases/{a}/claim", json={}, headers=officer_auth).status_code == 403


def test_standing_counsel_and_state_scope(client: TestClient, world) -> None:
    counsel = auth(login(client, "counsel@t.in"))
    cs = auth(login(client, "cs@t.in"))
    case_id = client.get("/api/v1/search?q=NIZAM", headers=cs).json()["items"][0]["id"]
    # counsel sees cases where a code of their department appears (GA, ASSAM → EDU in this test)
    assert client.get(f"/api/v1/cases/{case_id}", headers=counsel).json()["in_scope"] is True
    # state oversight sees everything but cannot write
    assert client.get(f"/api/v1/cases/{case_id}", headers=cs).json()["in_scope"] is True
    r = client.post(
        f"/api/v1/cases/{case_id}/documents",
        headers=cs,
        data={"doc_type": "writ_petition"},
        files={"file": ("wp.pdf", b"%PDF-1.4 test", "application/pdf")},
    )
    assert r.status_code == 403


def test_documents_upload_visibility_and_virus_scan(client: TestClient, world) -> None:
    edu = auth(login(client, "edu.admin@t.in"))
    case_id = client.get("/api/v1/inbox/recommended", headers=edu).json()["items"][0]["case"]["id"]
    client.post(f"/api/v1/cases/{case_id}/claim", json={}, headers=edu)

    r = client.post(
        f"/api/v1/cases/{case_id}/documents",
        headers=edu,
        data={"doc_type": "parawise_comments", "visibility": "private_to_office", "description": "draft"},
        files={"file": ("comments.pdf", b"%PDF-1.4 parawise comments", "application/pdf")},
    )
    assert r.status_code == 201, r.text
    doc = r.json()
    assert (
        doc["doc_group"] == "internal"
        and doc["actor_office_code"] == "EDU"
        and doc["sourcetrace_status"] == "not_applicable"
    )
    assert client.get(f"/api/v1/documents/{doc['id']}/download", headers=edu).content.startswith(b"%PDF")

    # standing counsel cannot see a private internal document
    counsel = auth(login(client, "counsel@t.in"))
    assert client.get(f"/api/v1/cases/{case_id}/documents", headers=counsel).json() == []
    assert client.get(f"/api/v1/documents/{doc['id']}/download", headers=counsel).status_code == 404

    r = client.post(
        f"/api/v1/cases/{case_id}/documents",
        headers=edu,
        data={"doc_type": "writ_petition"},
        files={"file": ("virus.pdf", b"%PDF-1.4 " + EICAR, "application/pdf")},
    )
    assert r.status_code == 422 and "virus" in r.json()["message"]
    r = client.post(
        f"/api/v1/cases/{case_id}/documents",
        headers=edu,
        data={"doc_type": "writ_petition"},
        files={"file": ("tool.exe", b"MZ....", "application/octet-stream")},
    )
    assert r.status_code == 422


def test_alerts_notifications_calendar(client: TestClient, world, db: Session) -> None:
    from aslms.services import alerts

    edu = auth(login(client, "edu.admin@t.in"))
    case_id = client.get("/api/v1/inbox/recommended", headers=edu).json()["items"][0]["case"]["id"]
    client.post(f"/api/v1/cases/{case_id}/claim", json={}, headers=edu)
    case = db.get(Case, case_id)
    case.next_hearing_date = today_ist() + timedelta(days=1)
    db.commit()

    counts = alerts.generate(db)
    db.commit()
    assert counts["hearing"] == 1 and counts["unclaimed_followup"] == 0
    assert alerts.generate(db)["hearing"] == 0  # idempotent
    db.commit()
    delivered = alerts.deliver_pending(db)
    db.commit()
    assert delivered["email_sent"] >= 1

    items = client.get("/api/v1/alerts", headers=edu).json()["items"]
    assert items[0]["kind"] == "hearing" and items[0]["severity"] == "critical"
    assert client.post(f"/api/v1/alerts/{items[0]['id']}/ack", headers=edu).json()["status"] == "acknowledged"
    notes = client.get("/api/v1/notifications?unread=true", headers=edu).json()
    assert notes["total"] == 1 and notes["items"][0]["case_id"] == case_id
    client.post("/api/v1/notifications/read-all", headers=edu)
    assert client.get("/api/v1/notifications?unread=true", headers=edu).json()["total"] == 0
    cal = client.get("/api/v1/calendar", headers=edu).json()
    assert cal[0]["case"]["id"] == case_id and cal[0]["severity"] == "critical"
    dash = client.get("/api/v1/dashboard", headers=edu).json()
    assert dash["hearings_48h"] == 1 and dash["recommended_total"] == world["n_rec"] - 1
    assert db.scalar(select(func.count()).select_from(Alert).where(Alert.kind == AlertKind.HEARING)) == 1


def test_search_reports_audit_admin(client: TestClient, world) -> None:
    cs = auth(login(client, "cs@t.in"))
    edu = auth(login(client, "edu.admin@t.in"))
    cnr = world["parsed"].rows[0].cnr
    r = client.get(f"/api/v1/search?q={cnr}", headers=edu).json()
    assert r["total"] == 1 and r["items"][0]["cnr"] == cnr and r["live"] == {}
    assert client.get("/api/v1/search?q=WP(C)/7535/2017", headers=edu).json()["total"] == 1
    assert client.get("/api/v1/search?q=zzzz-no-such-party", headers=edu).json()["live"] == {
        "napix": "not configured"
    }

    cfg = client.get("/api/v1/config", headers=cs).json()
    assert (
        cfg["upload_max_mb"] == 25 and ".pdf" in cfg["allowed_upload_types"] and cfg["napix_enabled"] is False
    )
    assert client.get("/api/v1/reports/data-health", headers=cs).status_code == 200
    rep = client.get("/api/v1/reports/pending-by-department", headers=cs).json()
    assert rep["rows"][0]["department"] == "UNCLAIMED" and rep["rows"][0]["pending"] == 16
    x = client.get("/api/v1/reports/pending-by-department?format=xlsx", headers=cs)
    assert x.status_code == 200 and x.content[:2] == b"PK"

    # department admin manages their own department only
    r = client.post(
        "/api/v1/offices",
        headers=edu,
        json={
            "code": "EDU-LEGAL",
            "name": "Legal cell",
            "kind": "section",
            "parent_id": str(world["edu"].id),
        },
    )
    assert r.status_code == 201
    r = client.post(
        "/api/v1/offices",
        headers=edu,
        json={"code": "HX", "name": "x", "kind": "section", "parent_id": str(world["health"].id)},
    )
    assert r.status_code == 403
    r = client.post(
        "/api/v1/mapping/codes",
        headers=edu,
        json={"code": "sc,  sec. edu.", "office_id": str(world["edu"].id)},
    )
    assert r.status_code == 200 and r.json()["code"] == "SC, SEC. EDU."
    assert any(u["code"] == "GA, ASSAM" for u in client.get("/api/v1/mapping/codes", headers=edu).json())
    audit = client.get("/api/v1/audit?action=office", headers=cs).json()
    assert audit["total"] == 1 and audit["items"][0]["actor_office_code"] == "EDU"
    assert client.get("/api/v1/audit", headers=auth(login(client, "edu.officer@t.in"))).status_code == 403
    listings = client.get("/api/v1/causelists?date=2025-09-01", headers=edu).json()
    assert listings[0]["entry_count"] == 16
