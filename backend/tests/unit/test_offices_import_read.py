"""Reading the offices workbook (design `offices-import`, decision 8): sheets and columns by their header text, not by
letter; a missing header, a non-zip or an oversized file refused; formula and remark columns never read; cells trimmed
with non-breaking spaces collapsed; a mobile typed as a number read as its digits; empty rows skipped."""

from __future__ import annotations

import pytest

from aslms.services import offices_import as imp
from tests.offices_workbook import build, dept, head, office, office_head


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
