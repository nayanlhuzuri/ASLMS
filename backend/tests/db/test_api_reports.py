"""`/reports` end to end (design `reports-dashboards`, "Tests", API): the catalogue, JSON reports, the Excel and
PDF files with their headers and the `report.exported` audit row, the row caps, and the 4xx answers."""

from __future__ import annotations

import io
import zipfile
from datetime import timedelta

import pymupdf
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.events import AuditLog
from tests.db.report_support import claim, new_case, today
from tests.db.workflow_support import login, send


def _api(world, **extra):
    settings = Settings(
        _env_file=None,
        aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters",
        aslms_access_token_minutes=5,
        **extra,
    )
    return TestClient(create_app(settings, world.Session))


@pytest.fixture()
def api(world):
    with _api(world) as client:
        yield client


def _exports(world) -> list[AuditLog]:
    with world.Session() as s:
        return list(
            s.scalars(
                sa.select(AuditLog).where(AuditLog.action == "report.exported").order_by(AuditLog.created_at)
            )
        )


def _files(world, n: int) -> None:
    with world.Session() as s:
        for i in range(n):
            c = new_case(s)
            claim(s, world, c, officer="edu_off1")
            send(s, world, "edu_off1", c, "edu_off2", due_date=today() + timedelta(days=1 + i % 30))
        s.commit()


def test_catalogue_and_json_report(api, world):
    _files(world, 2)
    assert api.get("/reports").status_code == 401
    admin = login(api, "edu_admin")
    cat = api.get("/reports", headers=admin)
    assert cat.status_code == 200
    keys = {r["key"]: r for r in cat.json()["reports"]}
    assert set(keys) == {"pending-cases", "hearings-disposals", "pending-actions"}
    r = api.get("/reports/pending-actions?include_cases=true", headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "department" and body["department_code"] == "EDU"
    files = next(s for s in body["sections"] if s["key"] == "files")
    assert files["total_rows"] == 2 and files["columns"][0] == {
        "key": "case_no",
        "label": "Case number",
        "kind": "text",
    }
    assert body["generated_by"]["office_code"] == "EDU"
    assert _exports(world) == []  # reading JSON is not audited
    officer = login(api, "edu_off1")
    assert api.get("/reports", headers=officer).status_code == 403
    assert api.get("/reports/pending-cases", headers=officer).status_code == 403
    assert api.get("/reports/pending-cases?department=HEALTH", headers=admin).status_code == 403
    assert api.get("/reports/data-health", headers=admin).status_code == 403


def test_export_xlsx_and_pdf_headers_and_audit(api, world):
    _files(world, 3)
    admin = login(api, "edu_admin")
    r = api.get("/reports/pending-actions?format=xlsx&include_cases=true", headers=admin)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert r.headers["cache-control"] == "no-store"
    disp = r.headers["content-disposition"]
    assert disp.startswith('attachment; filename="aslms-pending-actions-edu-') and disp.endswith('.xlsx"')
    assert len(zipfile.ZipFile(io.BytesIO(r.content)).namelist()) > 3
    r = api.get("/reports/pending-cases?format=pdf", headers=admin)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].endswith('.pdf"')
    assert pymupdf.open("pdf", r.content).page_count >= 1
    rows = _exports(world)
    assert [a.after["format"] for a in rows] == ["xlsx", "pdf"]
    first = rows[0]
    assert first.entity_type == "report" and first.entity_id is None
    assert first.after["report"] == "pending-actions" and first.after["department"] == "EDU"
    assert first.after["params"]["include_cases"] is True and first.after["truncated"] is False
    assert first.after["rows"] >= 3 and first.actor_office_code == "EDU"


def test_export_caps_rows_and_says_so(world):
    _files(world, 4)
    with _api(world, report_xlsx_max_rows=3, report_pdf_max_rows=2) as api:
        admin = login(api, "edu_admin")
        js = api.get("/reports/pending-actions?include_cases=true", headers=admin).json()
        files = next(s for s in js["sections"] if s["key"] == "files")
        assert files["truncated"] is True and len(files["rows"]) == 3 and files["total_rows"] == 4
        pdf = api.get("/reports/pending-actions?include_cases=true&format=pdf", headers=admin)
        text = "".join(p.get_text(flags=0) for p in pymupdf.open("pdf", pdf.content))
        assert "First 2 of 4 rows." in text
        xlsx = api.get("/reports/pending-actions?include_cases=true&format=xlsx", headers=admin)
        z = zipfile.ZipFile(io.BytesIO(xlsx.content))
        assert "First 3 of 4 rows." in z.read("xl/sharedStrings.xml").decode()
        audits = _exports(world)
        assert [(a.after["format"], a.after["truncated"]) for a in audits] == [("pdf", True), ("xlsx", True)]


def test_bad_format_and_bad_period_are_4xx(api, world):
    oversight = login(api, "oversight")
    assert api.get("/reports/pending-cases?format=csv", headers=oversight).status_code == 422
    assert api.get("/reports/hearings-disposals", headers=oversight).status_code == 422  # from/to required
    r = api.get("/reports/hearings-disposals?from=2025-02-01&to=2025-01-01", headers=oversight)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_period"
    r = api.get("/reports/hearings-disposals?from=2024-01-01&to=2025-06-01", headers=oversight)
    assert r.status_code == 422
    r = api.get("/reports/data-health?department=EDU", headers=oversight)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "department_not_allowed"
    r = api.get("/reports/data-health", headers=oversight)
    assert r.status_code == 200 and len(r.json()["sections"][0]["rows"]) == 7
    r = api.get("/reports/pending-cases?department=EDU-DSE", headers=oversight)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_department"
    r = api.get("/reports/hearings-disposals?from=2025-01-01&to=2025-01-31&format=xlsx", headers=oversight)
    assert r.status_code == 200
    assert _exports(world)[0].after["params"]["from"] == "2025-01-01"
