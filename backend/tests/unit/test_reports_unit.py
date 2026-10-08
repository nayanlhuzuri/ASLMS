"""Reports without a database (design `reports-dashboards`, "Tests", unit): the NJDG age bands at their
boundaries, the period checks, the catalogue scopes, the Excel and PDF exports and the file name."""

from __future__ import annotations

import io
import re
import zipfile
from datetime import UTC, date, datetime, timedelta

import pymupdf
import pytest

from aslms.services import report_export
from aslms.services.reporting_common import AGE_BANDS, AGE_UNKNOWN, ReportError, age_band, years_before
from aslms.services.reports import CATALOGUE, Column, Report, Section, check_period

TODAY = date(2026, 10, 8)


def test_age_band_boundaries():
    assert age_band(TODAY - timedelta(days=364), TODAY) == "age_lt_1"
    assert age_band(TODAY, TODAY) == "age_lt_1"
    # exactly N years belongs to the next band ([low, high) in whole years)
    expected = {1: "age_1_3", 3: "age_3_5", 5: "age_5_10", 10: "age_10_20", 20: "age_20_30", 30: "age_gt_30"}
    for years, key in expected.items():
        start = years_before(TODAY, years)
        assert age_band(start, TODAY) == key, years
        assert age_band(start + timedelta(days=1), TODAY) != key, years
    assert age_band(date(1950, 1, 1), TODAY) == "age_gt_30"
    assert age_band(None, TODAY) == AGE_UNKNOWN[0]
    # leap day: registered 29 Feb 2024, one year on 1 Mar 2025 (28 Feb 2025 is still under a year)
    assert years_before(date(2028, 2, 29), 1) == date(2027, 2, 28)
    assert age_band(date(2024, 2, 29), date(2025, 2, 28)) == "age_lt_1"
    assert age_band(date(2024, 2, 29), date(2025, 3, 1)) == "age_1_3"
    assert len(AGE_BANDS) == 7


def test_period_checks():
    d = date(2025, 1, 1)
    with pytest.raises(ReportError) as e:
        check_period(d, d - timedelta(days=1), 366, today=TODAY)
    assert e.value.code == "bad_period" and e.value.http_status == 422
    with pytest.raises(ReportError):
        check_period(d, d + timedelta(days=366), 366, today=TODAY)  # 367 days
    with pytest.raises(ReportError):
        check_period(TODAY + timedelta(days=1), TODAY + timedelta(days=2), 366, today=TODAY)
    with pytest.raises(ReportError):
        check_period(None, d, 366, today=TODAY)
    check_period(d, d + timedelta(days=365), 366, today=TODAY)  # 366 days accepted
    check_period(TODAY, TODAY + timedelta(days=5), 366, today=TODAY)  # a future `to` is allowed


def test_catalogue_scopes():
    assert set(CATALOGUE) == {"pending-cases", "hearings-disposals", "pending-actions", "data-health"}
    assert CATALOGUE["data-health"]["scopes"] == ("state",)
    for key in ("pending-cases", "hearings-disposals", "pending-actions"):
        assert set(CATALOGUE[key]["scopes"]) == {"state", "department"}


def _report(rows: int = 3, truncated: bool = False, office: str = "Office <A> & B") -> Report:
    cols = [
        Column("office", "Office"),
        Column("held", "Held", "int"),
        Column("due", "Due date", "date"),
        Column("late", "Days overdue", "days"),
    ]
    data = [
        {"office": f"{office} {i}", "held": i, "due": date(2026, 1, 1) + timedelta(days=i), "late": i * 2}
        for i in range(rows)
    ]
    return Report(
        key="pending-actions",
        title="Pending actions and overdue compliance by office",
        scope="department",
        department_code="EDU",
        params={"department": "EDU", "include_cases": True},
        generated_at=datetime(2026, 10, 8, 6, 0, tzinfo=UTC),
        generated_by={"name": "Asha Das", "designation": "Joint Secretary", "office_code": "EDU"},
        as_of_note="As they stand now.",
        sections=[
            Section(
                "by_holder",
                "By holder",
                cols,
                data,
                totals={"office": "Total", "held": sum(r["held"] for r in data), "due": None, "late": None},
            ),
            Section(
                "files",
                "Files with a pending action",
                cols,
                data,
                total_rows=rows + 5 if truncated else rows,
                truncated=truncated,
            ),
        ],
    )


def _sheets(content: bytes) -> dict[str, str]:
    z = zipfile.ZipFile(io.BytesIO(content))
    shared = z.read("xl/sharedStrings.xml").decode()
    strings = [re.sub(r"<[^>]+>", "", s) for s in re.findall(r"<si>(.*?)</si>", shared, re.S)]
    out = {}
    for name in z.namelist():
        if name.startswith("xl/worksheets/sheet"):
            xml = z.read(name).decode()

            def repl(m, strings=strings):
                return f"<v>{strings[int(m.group(1))]}</v>"

            out[name] = re.sub(r'<c r="[A-Z]+\d+"[^>]*t="s"[^>]*><v>(\d+)</v>', lambda m: repl(m), xml)
            out[name + ":raw"] = xml
    return out


def test_xlsx_export_shape():
    content = report_export.to_xlsx(_report(rows=3, truncated=True))
    sheets = _sheets(content)
    names = sorted(k for k in sheets if not k.endswith(":raw"))
    assert len(names) == 2  # one sheet per section
    first = sheets[names[0]]
    assert "Scope: Department EDU" in first
    assert "Asha Das, Joint Secretary, EDU" in first
    assert "Total" in first
    workbook = zipfile.ZipFile(io.BytesIO(content)).read("xl/styles.xml").decode()
    assert "dd-mm-yyyy" in workbook  # dates are written as Excel dates with a date format
    raw = sheets[names[0] + ":raw"]
    assert re.search(r'<c r="C\d+" s="\d+"><v>46023</v>', raw)  # 2026-01-01 as an Excel serial date
    second = sheets[names[1]]
    assert "First 3 of 8 rows." in second


def _text(content: bytes) -> tuple[int, str]:
    doc = pymupdf.open("pdf", content)
    return doc.page_count, "\n".join(p.get_text(flags=0) for p in doc)


def test_pdf_export_shape():
    content = report_export.to_pdf(_report(rows=200, truncated=True))
    pages, text = _text(content)
    assert pages >= 3
    assert "Pending actions and overdue compliance by office" in text
    assert "Office <A> & B 150" in text  # escaped in the HTML, shown as written
    assert "First 200 of 205 rows." in text
    assert f"Page 1 of {pages}" in text and f"Page {pages} of {pages}" in text
    doc = pymupdf.open("pdf", content)
    # the column headers repeat on every page of a table
    assert all("Days overdue" in p.get_text(flags=0) for p in doc)
    # markup in a value is never interpreted
    evil = report_export.to_pdf(_report(rows=1, office="<b>bold</b><script>x</script>"))
    assert "<b>bold</b><script>x</script> 0" in _text(evil)[1]


def test_filename_format():
    r = _report()
    assert report_export.filename(r, "xlsx") == "aslms-pending-actions-edu-20261008-1130.xlsx"
    r.department_code = None
    assert report_export.filename(r, "pdf", datetime(2026, 1, 2, 18, 45, tzinfo=UTC)) == (
        "aslms-pending-actions-state-20260103-0015.pdf"
    )
