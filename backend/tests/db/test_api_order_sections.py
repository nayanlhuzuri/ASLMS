"""The order-sections API (design `order-sections`, "API"): the Orders list's `reading`, "What the Order Says" with
its gates and errors, no audit row, the data-health block and the Order Reading Checks of Data Gaps, with no body or
title text in the administration blocks."""

from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa

from aslms.domain.documents import Document, DownloadStatus, Order, OrderKind, TextStatus
from aslms.domain.events import AuditLog
from aslms.domain.org import PermissionEffect
from aslms.domain.reference import Permission, Role
from aslms.services import access, source_failures, visibility
from aslms.services import order_sections as svc
from tests.db import docs_support as ds
from tests.db import next_dates_support as h
from tests.db import order_sections_support as o
from tests.db import workflow_support as w
from tests.db.report_support import override
from tests.db.world import add_membership, make_case

D = date(2026, 1, 28)
PHRASE = "Issue notice to the respondents. List this matter on 04.03.2026."


@pytest.fixture()
def api(world, tmp_path):
    client = ds.make_api(world, tmp_path)
    yield client
    client.__exit__(None, None, None)


def _read_order(s, world, *, body=o.BODY, heading="ORDER", cnr_printed=None, phrase=PHRASE, read=True):
    case = h.claimed(s, world)
    text = o.order_text(cnr=cnr_printed or case.cnr, case_no=case.case_no_text, heading=heading, body=body)
    order = h.order_with_text(s, case, text, order_date=D)
    order.next_date_phrase = phrase
    s.flush()
    if read:
        svc.read_batch(s, batch=50)
    return case, order


def test_orders_list_reading_brief_with_documents_view(api, world):
    with world.Session() as s:
        case, order = _read_order(s, world)
        _, judgment = _read_order(s, world, body=o.JUDGMENT_BODY, heading="JUDGMENT")
        s.commit()
    headers = w.login(api, "edu_admin")
    r = api.get(f"/cases/{case.id}/orders", headers=headers)
    assert r.status_code == 200, r.text
    (item,) = r.json()["items"]
    assert item["reading_state"] == "read"
    assert item["reading"] == {
        "layout": "template",
        "form": "interim",
        "procedural": True,
        "registrar": False,
        "outcome": None,
        "body_chars": item["reading"]["body_chars"],
        "parts": [],
        "has_compliance_directions": False,
        "common_order": False,
        "printed_case_no": None,
    }
    assert item["reading"]["body_chars"] > 50
    with world.Session() as s:
        jcase = s.get(Order, judgment.id).case_id
    j = api.get(f"/cases/{jcase}/orders", headers=headers).json()["items"][0]["reading"]
    assert j["form"] == "judgment" and j["outcome"] == "allowed" and j["has_compliance_directions"] is True
    assert j["parts"][0] == "opening" and "conclusion" in j["parts"]


def test_orders_list_reading_null_without_documents_view(api, world):
    with world.Session() as s:
        case, _ = _read_order(s, world)
        unread = h.order_with_text(
            s, case, o.order_text(cnr=case.cnr, case_no=case.case_no_text), order_no="u1"
        )
        override(s, world, "edu_admin", Permission.DOCUMENTS_VIEW, PermissionEffect.DENY)
        s.commit()
    items = api.get(f"/cases/{case.id}/orders", headers=w.login(api, "edu_admin")).json()["items"]
    assert len(items) == 2 and all(i["reading"] is None for i in items)
    with world.Session() as s:
        override(s, world, "edu_admin", Permission.DOCUMENTS_VIEW, None)
        s.commit()
    items = api.get(f"/cases/{case.id}/orders", headers=w.login(api, "edu_admin")).json()["items"]
    by_id = {i["id"]: i["reading"] for i in items}
    assert by_id[str(unread.id)] is None  # not read yet
    assert sum(1 for v in by_id.values() if v is not None) == 1


def test_sections_route_returns_body_parts_facts_and_next_date_span(api, world):
    with world.Session() as s:
        case, order = _read_order(s, world)
        jcase, judgment = _read_order(
            s,
            world,
            body=o.JUDGMENT_BODY,
            heading="JUDGMENT",
            phrase="release the arrears within 30 (thirty) days from the date of this order.",
        )
        s.commit()
    headers = w.login(api, "edu_admin")
    r = api.get(f"/cases/{case.id}/orders/{order.id}/sections", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["layout"] == "template" and body["form"] == "interim" and body["procedural"] is True
    assert body["body_text"].startswith("Heard Mr. Advocate A") and "PETITIONER" not in body["body_text"]
    assert body["parts"] == [] and body["outcome"] is None and body["printed_date"] == "2026-01-28"
    s0, s1 = body["next_date"]["txt"]
    assert body["body_text"][s0:s1].startswith("Issue notice to the respondents")
    assert body["next_date"]["phrase"] == PHRASE
    assert all("src" not in p for p in body["paragraphs"]) and body["paragraphs"][0]["page"] == 2
    assert body["made_from"]["parser_version"] >= 1 and len(body["made_from"]["pdf_sha256"]) == 64
    r = api.get(f"/cases/{jcase.id}/orders/{judgment.id}/sections", headers=headers)
    j = r.json()
    assert j["form"] == "judgment" and j["outcome"]["value"] == "allowed" and j["outcome"]["page"] == 2
    assert [p["part"] for p in j["parts"]] == ["opening", "facts", "petitioner_submissions", "conclusion"]
    (d,) = j["directions"]
    assert d["kind"] == "compliance" and d["period"]["from"] == "order_date" and d["due_on"] == "2026-02-27"
    assert j["body_text"][d["txt"][0] : d["txt"][1]] == d["text"]
    assert j["acts"][0]["act"] == "Assam Services (Pay) Act, 2017" and j["acts"][0]["provisions"] == ["3"]
    assert j["judgments"][0]["citation"] == "(2015) 4 SCC 123"
    assert j["next_date"]["txt"] is not None


def test_sections_route_404_for_invisible_case_other_case_order_or_no_document_rule(api, world):
    with world.Session() as s:
        case, order = _read_order(s, world)
        other_case, other_order = _read_order(s, world)
        s.commit()
    path = f"/cases/{case.id}/orders/{order.id}/sections"
    r = api.get(path, headers=w.login(api, "health_admin"))  # the case is not visible to HEALTH
    assert r.status_code == 404
    r = api.get(f"/cases/{case.id}/orders/{other_order.id}/sections", headers=w.login(api, "edu_admin"))
    assert r.status_code == 404  # an order of another case
    with world.Session() as s:
        override(s, world, "edu_admin", Permission.DOCUMENTS_VIEW, PermissionEffect.DENY)
        s.commit()
    r = api.get(path, headers=w.login(api, "edu_admin"))
    assert r.status_code == 404 and r.json()["detail"] == "no such case"
    del other_case


def test_sections_route_404_no_reading_with_text_status(api, world):
    with world.Session() as s:
        case, unread = _read_order(s, world, read=False)
        scanned = h.order_with_text(s, case, None, text_status=TextStatus.NONE, order_no="s1")
        s.commit()
    headers = w.login(api, "edu_admin")
    r = api.get(f"/cases/{case.id}/orders/{unread.id}/sections", headers=headers)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "no_reading" and r.json()["detail"]["text_status"] == "extracted"
    r = api.get(f"/cases/{case.id}/orders/{scanned.id}/sections", headers=headers)
    assert r.json()["detail"] == {
        "code": "no_reading",
        "message": "this order has not been read yet",
        "text_status": "none",
        "reading_state": "scanned",
    }


def test_sections_route_writes_no_audit_row(api, world):
    with world.Session() as s:
        case, order = _read_order(s, world)
        s.commit()
    headers = w.login(api, "edu_admin")
    with world.Session() as s:
        before = s.scalar(sa.select(sa.func.count()).select_from(AuditLog))
    assert api.get(f"/cases/{case.id}/orders/{order.id}/sections", headers=headers).status_code == 200
    assert api.get(f"/cases/{case.id}/orders", headers=headers).status_code == 200
    with world.Session() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(AuditLog)) == before


def test_data_health_has_order_sections_block(api, world):
    with world.Session() as s:
        _read_order(s, world)
        s.commit()
    r = api.get("/admin/data-health", headers=w.login(api, "root"))
    assert r.status_code == 200, r.text
    block = r.json()["order_sections"]
    assert block["read"] == 1 and block["orders_with_text"] == 1 and block["waiting"] == 0
    assert set(block["checks"]) == set(svc.CHECKS) and block["by_layout"]["template"] == 1


def test_gaps_order_checks_kind_and_bad_check_400(api, world):
    with world.Session() as s:
        case, order = _read_order(s, world, cnr_printed="GAHC010000992025")
        _read_order(s, world)
        s.commit()
    headers = w.login(api, "root")
    r = api.get("/admin/data-load/gaps", headers=headers, params={"kind": "order_checks"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "order_checks" and body["total"] == 1 and body["counts"]["cnr_differs"] == 1
    (item,) = body["items"]
    assert item["order_id"] == str(order.id) and item["checks"] == ["cnr_differs"]
    assert item["printed"]["cnr"] == "GAHC010000992025" and item["held"]["cnr"] == case.cnr
    assert body["order_sections"]["read"] == 2
    r = api.get(
        "/admin/data-load/gaps", headers=headers, params={"kind": "order_checks", "check": "cnr_differs"}
    )
    assert r.json()["total"] == 1
    r = api.get("/admin/data-load/gaps", headers=headers, params={"kind": "order_checks", "check": "bogus"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_input"
    r = api.get("/admin/data-load/gaps", headers=headers, params={"kind": "cases", "check": "cnr_differs"})
    assert r.status_code == 400
    assert (
        api.get(
            "/admin/data-load/gaps", headers=w.login(api, "edu_off1"), params={"kind": "order_checks"}
        ).status_code
        == 403
    )


def test_responses_carry_no_title_or_body_text_in_admin_blocks(api, world):
    with world.Session() as s:
        _read_order(s, world, cnr_printed="GAHC010000992025")
        make_case(s)
        s.commit()
    headers = w.login(api, "root")
    texts = [
        api.get("/admin/data-health", headers=headers).text,
        api.get("/admin/data-load/gaps", headers=headers, params={"kind": "order_checks"}).text,
    ]
    for t in texts:
        for word in ("PETITIONER", "PARENT A", "Advocate A", "Issue notice", "body_text", "MASKED"):
            assert word not in t, word


# ------------------------------------------------------------------------------------------------ version 2
# design `order-sections-review-advisories`, decisions 12, 13, 15 and 16


def _states(api, case, key="edu_admin") -> dict[str, tuple]:
    items = api.get(f"/cases/{case.id}/orders", headers=w.login(api, key)).json()["items"]
    return {i["id"]: (i["reading_state"], i["reading"]) for i in items}


def test_orders_list_reading_state_for_each_state(api, world):
    with world.Session() as s:
        case, read = _read_order(s, world)
        text = o.order_text(cnr=case.cnr, case_no=case.case_no_text)
        pending = h.order_with_text(s, case, text, text_status=TextStatus.PENDING, order_no="p1")
        unread = h.order_with_text(s, case, text, order_no="p2")
        scanned = h.order_with_text(s, case, None, text_status=TextStatus.NONE, order_no="p3")
        failed_text = h.order_with_text(s, case, None, text_status=TextStatus.FAILED, order_no="p4")
        failing = h.order_with_text(s, case, text, order_no="p5")
        source_failures.record(s, "order_parse", str(failing.id), "RuntimeError: reader bug")
        no_pdf = Order(
            case_id=case.id,
            order_no="p6",
            order_date=D,
            kind=OrderKind.INTERIM,
            download_status=DownloadStatus.NOT_AVAILABLE,
        )
        s.add(no_pdf)
        s.commit()
    got = _states(api, case)
    assert got[str(read.id)][0] == "read" and got[str(read.id)][1]["form"] == "interim"
    expected = {
        pending: "not_read_yet",
        unread: "not_read_yet",
        scanned: "scanned",
        failed_text: "text_failed",
        failing: "reading_failed",
        no_pdf: None,
    }
    for order, state in expected.items():
        assert got[str(order.id)] == (state, None), (order.order_no, got[str(order.id)])
    with world.Session() as s:  # a caller without `documents.view`: every stored order is withheld
        override(s, world, "edu_admin", Permission.DOCUMENTS_VIEW, PermissionEffect.DENY)
        s.commit()
    got = _states(api, case)
    assert {got[str(x.id)] for x in (read, pending, unread, scanned, failed_text, failing)} == {
        ("withheld", None)
    }
    assert got[str(no_pdf.id)] == (None, None)


def test_withheld_decided_before_text_states(api, world):
    with world.Session() as s:
        case, _ = _read_order(s, world, read=False)
        failed_text = h.order_with_text(s, case, None, text_status=TextStatus.FAILED, order_no="f1")
        failing = h.order_with_text(
            s, case, o.order_text(cnr=case.cnr, case_no=case.case_no_text), order_no="f2"
        )
        source_failures.record(s, "order_parse", str(failing.id), "RuntimeError: reader bug")
        override(s, world, "edu_admin", Permission.DOCUMENTS_VIEW, PermissionEffect.DENY)
        s.commit()
    got = _states(api, case)
    assert got[str(failed_text.id)] == ("withheld", None) and got[str(failing.id)] == ("withheld", None)
    r = api.get(f"/cases/{case.id}/orders/{failing.id}/sections", headers=w.login(api, "edu_admin"))
    assert r.status_code == 404 and r.json()["detail"] == "no such case"


def test_document_rule_denied_hides_reading_on_list_and_404_on_sections(api, world):
    """Decision 16: one login, two memberships. EDU sees the case and does not hold `documents.view`; HEALTH holds
    `documents.view` and does not see the case. `access.has` passes, `can_view_document` fails."""
    with world.Session() as s:
        case, order = _read_order(s, world)
        person = world.user(s, "edu_admin")
        add_membership(s, person, world.office(s, "HEALTH"), Role.DEPT_OFFICER)
        override(s, world, "edu_admin", Permission.DOCUMENTS_VIEW, PermissionEffect.DENY, office="EDU")
        s.flush()
        assert access.has(s, person, Permission.DOCUMENTS_VIEW)
        doc = s.get(Document, order.document_id)
        assert not visibility.can_view_document(s, person, doc)
        s.commit()
    headers = w.login(api, "edu_admin")
    r = api.get(f"/cases/{case.id}/orders", headers=headers)
    assert r.status_code == 200, r.text
    (item,) = r.json()["items"]
    assert item["reading"] is None and item["reading_state"] == "withheld"
    r = api.get(f"/cases/{case.id}/orders/{order.id}/sections", headers=headers)
    assert r.status_code == 404 and r.json()["detail"] == "no such case"
    assert "Heard" not in r.text and "reading_state" not in r.text


def test_no_reading_404_carries_reading_state(api, world):
    with world.Session() as s:
        case, unread = _read_order(s, world, read=False)
        failing = h.order_with_text(
            s, case, o.order_text(cnr=case.cnr, case_no=case.case_no_text), order_no="f1"
        )
        source_failures.record(s, "order_parse", str(failing.id), "RuntimeError: reader bug")
        failed_text = h.order_with_text(s, case, None, text_status=TextStatus.FAILED, order_no="f2")
        s.commit()
    headers = w.login(api, "edu_admin")
    for order, text_status, state in (
        (unread, "extracted", "not_read_yet"),
        (failing, "extracted", "reading_failed"),
        (failed_text, "failed", "text_failed"),
    ):
        r = api.get(f"/cases/{case.id}/orders/{order.id}/sections", headers=headers)
        assert r.status_code == 404
        assert r.json()["detail"] == {
            "code": "no_reading",
            "message": "this order has not been read yet",
            "text_status": text_status,
            "reading_state": state,
        }


def _slow_checks(monkeypatch, seconds: float = 2.0):
    real = svc.checks_pass

    def slow(session):
        session.execute(sa.text(f"SELECT pg_sleep({seconds})"))
        return real(session)

    monkeypatch.setattr(svc, "checks_pass", slow)


def test_data_health_answers_200_when_order_checks_time_out(world, tmp_path, monkeypatch):
    client = ds.make_api(world, tmp_path, order_sections_status_timeout_seconds=1)
    try:
        with world.Session() as s:
            _read_order(s, world)
            s.commit()
        _slow_checks(monkeypatch)
        r = client.get("/admin/data-health", headers=w.login(client, "root"))
        assert r.status_code == 200, r.text
        body = r.json()
        block = body["order_sections"]
        assert block["timed_out"] == ["checks"] and block["checks"] is None
        assert block["read"] == 1 and block["orders_with_text"] == 1 and block["by_layout"]["template"] == 1
        for key in ("napix", "queue", "jobs", "failures", "documents_text", "retention"):
            assert body[key] is not None, key
    finally:
        client.__exit__(None, None, None)


def test_gaps_order_checks_total_and_counts_from_one_pass(api, world, monkeypatch):
    with world.Session() as s:
        _read_order(s, world, cnr_printed="GAHC010000992025")
        _read_order(s, world)
        s.commit()
    passes: list[int] = []
    real = svc.checks_pass
    monkeypatch.setattr(svc, "checks_pass", lambda session: passes.append(1) or real(session))
    headers = w.login(api, "root")
    r = api.get("/admin/data-load/gaps", headers=headers, params={"kind": "order_checks"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(passes) == 1
    assert body["total"] == 1 and body["counts"]["cnr_differs"] == 1 and body["counts"]["no_cnr_line"] == 0
    assert body["order_sections"]["checks"]["cnr_differs"] == 1 and body["order_sections"]["read"] == 2
    assert body["order_sections"]["timed_out"] == []
    r = api.get(
        "/admin/data-load/gaps", headers=headers, params={"kind": "order_checks", "check": "common_order"}
    )
    assert r.json()["total"] == 0 and len(passes) == 2


def test_gaps_list_stands_when_block_counts_time_out(world, tmp_path, monkeypatch):
    client = ds.make_api(world, tmp_path, order_sections_status_timeout_seconds=1)
    try:
        with world.Session() as s:
            _read_order(s, world, cnr_printed="GAHC010000992025")
            s.commit()
        real = svc._counts_part

        def slow(session):
            session.execute(sa.text("SELECT pg_sleep(2)"))
            return real(session)

        monkeypatch.setattr(svc, "_counts_part", slow)
        r = client.get(
            "/admin/data-load/gaps", headers=w.login(client, "root"), params={"kind": "order_checks"}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 1 and len(body["items"]) == 1
        block = body["order_sections"]
        assert block["timed_out"] == ["counts"] and block["read"] is None and block["waiting"] is None
        assert block["checks"]["cnr_differs"] == 1
        assert body["documents_text"] is not None
    finally:
        client.__exit__(None, None, None)


def test_gaps_list_timeout_is_503_search_timeout_not_500(world, tmp_path, monkeypatch):
    client = ds.make_api(world, tmp_path, report_statement_timeout_seconds=1)
    try:
        with world.Session() as s:
            _read_order(s, world)
            s.commit()
        _slow_checks(monkeypatch)
        r = client.get(
            "/admin/data-load/gaps", headers=w.login(client, "root"), params={"kind": "order_checks"}
        )
        assert r.status_code == 503 and r.json()["detail"]["code"] == "search_timeout"
    finally:
        client.__exit__(None, None, None)
