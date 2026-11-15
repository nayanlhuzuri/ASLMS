"""Reading the offices workbook (design `offices-import`, decision 8): sheets and columns by their header text, not by
letter; a missing header, a non-zip or an oversized file refused; formula and remark columns never read; cells trimmed
with non-breaking spaces collapsed; a mobile typed as a number read as its digits; empty rows skipped. A stale stored
sheet dimension neither cuts rows or columns nor produces an empty tail (design `offices-import-followups`,
decision 1)."""

from __future__ import annotations

import pytest

from aslms.services import offices_import as imp
from tests.offices_workbook import build, dept, head, office, office_head, with_stale_dimension


def test_reads_sheets_by_header_text_not_letter():
    data = build(
        [dept("Transport", "TRANS", **head("Asha Das", "asha@example.gov.in"))],
        [office("Transport", "Directorate of Transport", "Directorate / Commissionerate", "TRANS-DOT")],
        insert_before_code="An Extra Column",
    )
    wb = imp.read_workbook(data)
    assert [(d.code, d.name, d.include) for d in wb.departments] == [("TRANS", "Transport", "Yes")]
    assert wb.departments[0].head.email == "asha@example.gov.in"
    assert [(o.code, o.parent, o.kind) for o in wb.offices] == [
        ("TRANS-DOT", "Transport", "Directorate / Commissionerate")
    ]
    assert wb.departments[0].row == 5 and wb.offices[0].row == 5


def test_missing_header_refuses_file():
    data = build([dept("Transport", "TRANS")], drop_header="Include?")
    with pytest.raises(imp.ImportFileError, match='"Include\\?"'):
        imp.read_workbook(data)


def test_refuses_non_zip_and_oversize():
    with pytest.raises(imp.ImportFileError, match="not an Excel workbook"):
        imp.read_workbook(b"No.,Code\n1,TRANS\n")
    with pytest.raises(imp.ImportFileError, match="5 MB"):
        imp.read_workbook(b"PK\x03\x04" + b"0" * imp.MAX_BYTES)
    with pytest.raises(imp.ImportFileError, match="cannot be read"):
        imp.read_workbook(b"PK\x03\x04 not really a zip")


def test_formula_columns_ignored():
    data = build([dept("Transport", "TRANS", remarks="please check")], formula_values=True)
    wb = imp.read_workbook(data)
    row = wb.departments[0]
    # the dataclass carries only the columns the import reads: no Code Check, People Check or remarks
    assert not hasattr(row, "code_check") and not hasattr(row, "remarks")
    assert row.code == "TRANS"


def test_mobile_number_cell_read_as_digits():
    data = build(
        [
            dept("Transport", "TRANS", **head("Asha Das", "asha@example.gov.in", mobile=9864012345)),
            dept("Tourism", "TOURISM", **head("Bina Roy", "bina@example.gov.in", mobile=9864012346.0)),
        ]
    )
    wb = imp.read_workbook(data)
    assert [d.head.mobile for d in wb.departments] == ["9864012345", "9864012346"]


def test_cells_trimmed_and_nbsp_collapsed():
    data = build(
        [dept("  Social Justice   and  Empowerment ", " sje ", include=" yes ")],
        [office("Social Justice and Empowerment", "Board  One", "Board / Corporation", "SJE-B1")],
    )
    wb = imp.read_workbook(data)
    assert wb.departments[0].name == "Social Justice and Empowerment"
    assert wb.departments[0].code == "sje"
    assert wb.departments[0].include == "yes"
    assert wb.offices[0].name == "Board One"
    assert imp.clean(" a  b \n c ") == "a b c"


def test_empty_rows_skipped():
    data = build(
        [dept("Transport", "TRANS"), {"head_name": "", "include": ""}],
        [office("Transport", "Directorate", "Unit", "TRANS-U1", include="")],
        blank_rows=5,
    )
    wb = imp.read_workbook(data)
    assert [d.code for d in wb.departments] == ["TRANS"]
    assert [o.code for o in wb.offices] == ["TRANS-U1"]


def test_missing_sheet_refused():
    import io

    import openpyxl

    book = openpyxl.Workbook()
    book.active.title = "Departments"
    book.active["A4"] = "No."
    buf = io.BytesIO()
    book.save(buf)
    with pytest.raises(imp.ImportFileError, match="Offices Under Departments|no column"):
        imp.read_workbook(buf.getvalue())


def test_office_head_type_column_read():
    data = build(
        [dept("Transport", "TRANS")],
        [
            office(
                "Transport",
                "Directorate of Transport",
                "Directorate / Commissionerate",
                "TRANS-DOT",
                **office_head("Chandan Bora", "chandan@example.gov.in", user_type="Department Officer"),
            )
        ],
    )
    wb = imp.read_workbook(data)
    assert wb.offices[0].head.user_type == "Department Officer"
    assert wb.offices[0].head.email == "chandan@example.gov.in"


def _stale_book(ref: str) -> bytes:
    data = build(
        [
            dept(
                f"Department {i}",
                f"DEPT{i}",
                website=f"https://d{i}.assam.gov.in",
                **head(f"P{i}", f"p{i}@x.in"),
            )
            for i in range(6)
        ],
        [
            office("Department 0", f"Office {i}", "Unit", f"DEPT0-U{i}", website=f"https://o{i}.assam.gov.in")
            for i in range(8)
        ],
        blank_rows=0,
    )
    data = with_stale_dimension(data, imp.DEPT_SHEET, ref)
    return with_stale_dimension(data, imp.OFFICE_SHEET, ref)


def test_stale_dimension_short_reads_every_row():
    import io

    import openpyxl

    data = _stale_book("A1:E5")
    # the helper did make the stored range short: without the reset openpyxl would stop at row 5, column E
    ws = openpyxl.load_workbook(io.BytesIO(data), read_only=True)[imp.DEPT_SHEET]
    assert (ws.max_row, ws.max_column) == (5, 5)
    wb = imp.read_workbook(data)
    assert [d.code for d in wb.departments] == [f"DEPT{i}" for i in range(6)]
    assert [d.website for d in wb.departments] == [f"https://d{i}.assam.gov.in" for i in range(6)]
    assert all(d.include == "Yes" and d.head.email for d in wb.departments)
    assert [o.code for o in wb.offices] == [f"DEPT0-U{i}" for i in range(8)]
    assert [o.website for o in wb.offices] == [f"https://o{i}.assam.gov.in" for i in range(8)]
    assert all(o.kind == "Unit" and o.include == "Yes" for o in wb.offices)


def test_stale_dimension_oversized_reads_only_real_rows(monkeypatch):
    data = _stale_book("A1:Z1048576")
    yielded = {imp.DEPT_SHEET: 0, imp.OFFICE_SHEET: 0}
    real_rows = imp._rows

    def counting(ws, sheet, columns):
        for item in real_rows(ws, sheet, columns):
            yielded[sheet] += 1
            yield item

    monkeypatch.setattr(imp, "_rows", counting)
    wb = imp.read_workbook(data)
    assert len(wb.departments) == 6 and len(wb.offices) == 8
    # the data rows below the header are the real rows only, not a million empty ones
    assert yielded == {imp.DEPT_SHEET: 6, imp.OFFICE_SHEET: 8}
