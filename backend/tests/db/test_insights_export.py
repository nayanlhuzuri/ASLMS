"""The Insights export (design `state-insights`, decision 27, "Tests", `test_insights_export.py`): the About sheet with
the filters, who and when; the fields in order with the link column; the Excel cap; the PDF cap with the pointer to
Excel; only cases of the scope the viewer may open; one audit row after the build; 400 `bad_field`; never internal
records."""

from __future__ import annotations

import io

import openpyxl
import pymupdf
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from aslms.api.main import create_app
from aslms.core.config import Settings
from aslms.domain.cases import CaseStatus
from aslms.domain.events import AuditLog
from tests.db import insights_support as ins
from tests.db.report_support import claim
from tests.db.workflow_support import login, note, send

STATE = ("THE STATE OF ASSAM AND 2 ORS",)


def _api(world, **extra):
    settings = Settings(
        _env_file=None,
        aslms_jwt_secret="test-secret-of-at-least-thirty-two-characters",
        aslms_access_token_minutes=5,
        portal_base_url="https://aslms.example",
        **extra,
    )
    return TestClient(create_app(settings, world.Session))


@pytest.fixture()
def api(world):
    with _api(world) as client:
        yield client


def _cases(world, n: int = 3) -> list:
    with world.Session() as s:
        out = [ins.case(s, respondents=STATE, codes=("GA, ASSAM",)) for _ in range(n)]
        claim(s, world, out[0], officer="edu_off1")
        send(s, world, "edu_off1", out[0], "edu_off2", remark="SECRET REMARK TEXT")
        note(s, world, "edu_off2", out[0], body="SECRET NOTE TEXT")
        private = ins.case(s, respondents=("M/S PRIVATE LTD",))
        ins.build(s, *out, private)
        s.commit()
        return out


def _exports(world) -> list[AuditLog]:
    with world.Session() as s:
        return list(
            s.scalars(
                sa.select(AuditLog)
                .where(AuditLog.action == "insights.exported")
                .order_by(AuditLog.created_at)
            )
        )


def _sheets(content: bytes):
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
    return {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}


def test_xlsx_about_sheet_filters_who_when(api, world):
    _cases(world)
    root = login(api, "root")
    r = api.get("/insights/export?format=xlsx&kind=writ", headers=root)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert r.headers["cache-control"] == "no-store"
    disp = r.headers["content-disposition"]
    assert disp.startswith('attachment; filename="ASLMS_Insights_State_') and disp.endswith('.xlsx"')
    sheets = _sheets(r.content)
    assert list(sheets) == ["About This Export", "Cases"]
    about = {row[0]: row[1] for row in sheets["About This Export"] if row and row[0]}
    assert about["Scope"] == "State" and about["Filters"] == "Kind: Writ Petition"
    assert about["Exported By"].startswith("Root") and about["Exported At"].endswith("IST")
    assert about["Cases"] == "3" and "State cases (worked out)" in about["Covers"]


def test_xlsx_fields_in_order_and_link_column(api, world):
    cases = _cases(world)
    root = login(api, "root")
    r = api.get("/insights/export?format=xlsx&fields=link,cnr,case_no,state_case,with_officer", headers=root)
    rows = _sheets(r.content)["Cases"]
    assert rows[0] == [
        "Case Number",
        "CNR",
        "State Case",
        "With Officer",
        "Link to the Case Page",
        "Applications Pending",
    ]
    by_case = {row[0]: row for row in rows[1:]}
    first = by_case[cases[0].case_no_text]
    assert first[2] == "Yes (Parties, Counsel Code, Claimed)" and first[3].startswith("Edu Off2")
    assert first[4] == f"https://aslms.example/cases/{cases[0].ref_no.replace('/', '-')}"
    r = api.get("/insights/export?format=pdf&fields=link,cnr", headers=root)
    assert r.status_code == 200  # Link is for Excel only, silently left out of a PDF


def test_xlsx_cap_first_n_of_m(world):
    _cases(world, 4)
    with _api(world, insights_xlsx_max_rows=2) as api:
        r = api.get("/insights/export?format=xlsx", headers=login(api, "root"))
        sheets = _sheets(r.content)
        about = {row[0]: row[1] for row in sheets["About This Export"] if row and row[0]}
        assert about["Cases"] == "First 2 of 4" and len(sheets["Cases"]) == 3
    rows = _exports(world)
    assert (
        rows[-1].after["truncated"] is True and rows[-1].after["rows"] == 2 and rows[-1].after["total"] == 4
    )


def test_pdf_landscape_capped_with_excel_pointer(world):
    _cases(world, 4)
    with _api(world, insights_pdf_max_rows=3) as api:
        r = api.get("/insights/export?format=pdf", headers=login(api, "root"))
        assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
        doc = pymupdf.open("pdf", r.content)
        page = doc[0]
        assert page.rect.width > page.rect.height  # A4 landscape
        text_ = "".join(p.get_text() for p in doc)
        assert "First 3 of 4 cases. Export to Excel for every case." in text_
        assert "Page 1 of" in text_


def test_export_only_scope_and_visible_cases(api, world):
    cases = _cases(world)
    with world.Session() as s:
        other = ins.case(s, respondents=STATE)
        claim(s, world, other, by="health_admin")
        ins.build(s, other)
        s.commit()
    admin = login(api, "edu_admin")
    rows = _sheets(
        api.get("/insights/export?format=xlsx&scope=department&department=EDU", headers=admin).content
    )["Cases"]
    assert [row[0] for row in rows[1:]] == [cases[0].case_no_text]
    assert api.get("/insights/export?scope=department&department=HEALTH", headers=admin).status_code == 403
    assert api.get("/insights/export", headers=login(api, "edu_off1")).status_code == 403


def test_export_audited_once_after_build(api, world):
    _cases(world)
    root = login(api, "root")
    api.get("/insights", headers=root)
    api.get("/insights/cases", headers=root)
    assert _exports(world) == []  # reading is not audited
    api.get("/insights/export?format=pdf&next=none&fields=case_no,status", headers=root)
    (row,) = _exports(world)
    assert row.entity_type == "insights" and row.entity_id is None
    assert row.after["scope"] == "state" and row.after["department"] is None and row.after["format"] == "pdf"
    assert row.after["filters"]["next"] == "none" and row.after["fields"] == [
        "case_no",
        "status",
        "applications_pending",
    ]
    assert row.after["rows"] == 3 and row.after["truncated"] is False


def test_bad_field_400(api, world):
    root = login(api, "root")
    r = api.get("/insights/export?fields=case_no,notes", headers=root)
    assert (
        r.status_code == 400
        and r.json()["detail"]["code"] == "bad_field"
        and r.json()["detail"]["field"] == "notes"
    )
    assert _exports(world) == []


def test_never_exports_internal_records(api, world):
    _cases(world)
    root = login(api, "root")
    every = ",".join(f["key"] for f in api.get("/insights/fields", headers=root).json())
    content = api.get(f"/insights/export?format=xlsx&fields={every}", headers=root).content
    flat = " ".join(
        str(v) for rows in _sheets(content).values() for row in rows for v in row if v is not None
    )
    assert "SECRET REMARK TEXT" not in flat and "SECRET NOTE TEXT" not in flat
    assert "Pending" in flat and CaseStatus.PENDING
