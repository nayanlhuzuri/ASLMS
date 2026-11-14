"""Workbooks in the layout of the owner's offices workbook (design `offices-import`, "Context"), built in memory with
made-up people (`@example.gov.in`) for the import tests. No spreadsheet is committed (decision 20)."""

from __future__ import annotations

import io
from typing import Any

DEPT_HEADERS = [
    "No.",
    "Department Name (as on the site)",
    "Website",
    "Code",
    "Code Check",
    "Include?",
    "Head: Full Name",
    "Head: Designation",
    "Head: Login E-mail",
    "Head: Mobile (10 digits)",
    "Head Already Has an ASLMS Login?",
    "Admin: Full Name",
    "Admin: Designation",
    "Admin: Login E-mail",
    "Admin: Mobile (10 digits)",
    "Admin Already Has an ASLMS Login?",
    "People Check",
    "In ASLMS Now",
    "Note From the Check",
    "Your Remarks",
]
OFFICE_HEADERS = [
    "No.",
    "Parent Department",
    "Office Name",
    "Website",
    "Office Type",
    "Code",
    "Code Check",
    "Include?",
    "Office Head: Full Name",
    "Office Head: Designation",
    "Office Head: Login E-mail",
    "Office Head: Mobile (10 digits)",
    "Office Head: User Type",
    "Already Has an ASLMS Login?",
    "People Check",
    "Source",
    "In ASLMS Now",
    "Note From the Check",
    "Your Remarks",
]
# keys a test row may give -> header
DEPT_KEYS = {
    "name": "Department Name (as on the site)",
    "website": "Website",
    "code": "Code",
    "include": "Include?",
    "head_name": "Head: Full Name",
    "head_designation": "Head: Designation",
    "head_email": "Head: Login E-mail",
    "head_mobile": "Head: Mobile (10 digits)",
    "head_has_login": "Head Already Has an ASLMS Login?",
    "admin_name": "Admin: Full Name",
    "admin_designation": "Admin: Designation",
    "admin_email": "Admin: Login E-mail",
    "admin_mobile": "Admin: Mobile (10 digits)",
    "admin_has_login": "Admin Already Has an ASLMS Login?",
    "remarks": "Your Remarks",
}
OFFICE_KEYS = {
    "parent": "Parent Department",
    "name": "Office Name",
    "website": "Website",
    "kind": "Office Type",
    "code": "Code",
    "include": "Include?",
    "head_name": "Office Head: Full Name",
    "head_designation": "Office Head: Designation",
    "head_email": "Office Head: Login E-mail",
    "head_mobile": "Office Head: Mobile (10 digits)",
    "head_type": "Office Head: User Type",
    "head_has_login": "Already Has an ASLMS Login?",
    "remarks": "Your Remarks",
}


def dept(name: str, code: str, include: str = "Yes", **people: Any) -> dict:
    return {"name": name, "code": code, "include": include, **people}


def head(
    name: str, email: str, designation: str = "Secretary", mobile: Any = "", has_login: str = ""
) -> dict:
    return {
        "head_name": name,
        "head_email": email,
        "head_designation": designation,
        "head_mobile": mobile,
        "head_has_login": has_login,
    }


def admin(
    name: str, email: str, designation: str = "Deputy Secretary", mobile: Any = "", has_login: str = ""
) -> dict:
    return {
        "admin_name": name,
        "admin_email": email,
        "admin_designation": designation,
        "admin_mobile": mobile,
        "admin_has_login": has_login,
    }


def office(parent: str, name: str, kind: str, code: str, include: str = "Yes", **people: Any) -> dict:
    return {"parent": parent, "name": name, "kind": kind, "code": code, "include": include, **people}


def office_head(
    name: str,
    email: str,
    user_type: str = "Directorate User",
    designation: str = "Director",
    mobile: Any = "",
    has_login: str = "",
) -> dict:
    return {
        "head_name": name,
        "head_email": email,
        "head_designation": designation,
        "head_mobile": mobile,
        "head_type": user_type,
        "head_has_login": has_login,
    }


def build(
    departments: list[dict],
    offices: list[dict] | None = None,
    *,
    insert_before_code: str | None = None,
    drop_header: str | None = None,
    blank_rows: int = 3,
    formula_values: bool = True,
) -> bytes:
    """The workbook as bytes: Read Me, Departments (header on row 4), Offices Under Departments (header on row 4),
    Lists. `insert_before_code` adds a column with that header before Code on both sheets; `drop_header` leaves one
    header out."""
    import openpyxl

    wb = openpyxl.Workbook()
    rm = wb.active
    rm.title = "Read Me"
    rm["A1"] = "ASLMS Offices and Their Heads, From the Assam State Portal"
    rm["A5"] = "Summary"
    rm["B5"] = "=COUNTA(Departments!B5:B100)"

    def sheet(title: str, headers: list[str], keys: dict[str, str], rows: list[dict]) -> None:
        ws = wb.create_sheet(title)
        ws["A1"] = title
        ws["A2"] = "From https://assam.gov.in/departments-list (test copy)."
        ws["G3"] = "Department Head"
        hs = list(headers)
        if insert_before_code:
            hs.insert(hs.index("Code"), insert_before_code)
        if drop_header:
            hs = [h for h in hs if h != drop_header]
        for c, h in enumerate(hs, start=1):
            ws.cell(4, c, h)
        col = {h: c for c, h in enumerate(hs, start=1)}
        r = 5
        for i, row in enumerate(rows, start=1):
            ws.cell(r, col["No."], i)
            for k, v in row.items():
                h = keys[k]
                if h in col and v not in (None, ""):
                    ws.cell(r, col[h], v)
            if formula_values and "Code Check" in col:
                ws.cell(r, col["Code Check"], f'=IF(D{r}="","Missing","OK")')
            if "People Check" in col:
                ws.cell(r, col["People Check"], "Head OK")
            if insert_before_code:
                ws.cell(r, col[insert_before_code], "extra")
            r += 1
        for _ in range(blank_rows):
            ws.cell(r, col["No."], r - 4)
            r += 1

    sheet("Departments", DEPT_HEADERS, DEPT_KEYS, departments)
    sheet("Offices Under Departments", OFFICE_HEADERS, OFFICE_KEYS, offices or [])
    ls = wb.create_sheet("Lists")
    ls["A1"], ls["B1"] = "Office Type", "What It Covers"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
