"""Report exports (design `reports-dashboards`, decisions 12-13): the same content as the JSON report, as an Excel
workbook (XlsxWriter) or an A4 landscape PDF (PyMuPDF `Story`). Files are built in memory and streamed by the
caller; nothing is written to the document store. Each export is audited (`report.exported`) by the caller once
the file is built (`audit_export`)."""

from __future__ import annotations

import html
import io
import re
from datetime import date, datetime
from typing import Any

import pymupdf
import xlsxwriter
from sqlalchemy.orm import Session

from aslms.services.audit import Actor, write_audit
from aslms.services.refno import IST
from aslms.services.reports import Column, Report, Section

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MEDIA_TYPE = "application/pdf"
SHEET_BAD = re.compile(r"[\[\]:*?/\\]")
PAGE = pymupdf.paper_rect("a4-l")
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 36, 36, 48
WHERE = PAGE + (MARGIN_X, MARGIN_TOP, -MARGIN_X, -MARGIN_BOTTOM)
PDF_CSS = """
body { font-family: sans-serif; font-size: 8pt; }
h1 { font-size: 13pt; margin: 0 0 4pt 0; }
h2 { font-size: 10pt; margin: 6pt 0 3pt 0; }
p { margin: 0 0 2pt 0; }
p.note { font-style: italic; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 0.5pt solid #777; padding: 1.5pt 2pt; font-size: 7pt; vertical-align: top; }
th { background-color: #e6e6e6; font-weight: bold; }
td.n { text-align: right; }
tr.total td { font-weight: bold; background-color: #f2f2f2; }
"""


# ------------------------------------------------------------------------------------------------ shared


def _ist(dt: datetime) -> str:
    return dt.astimezone(IST).strftime("%d-%m-%Y %H:%M IST")


def scope_text(report: Report) -> str:
    return "State" if report.department_code is None else f"Department {report.department_code}"


def generated_by_text(report: Report) -> str:
    g = report.generated_by or {}
    parts = [g.get("name"), g.get("designation"), g.get("office_code")]
    return ", ".join(p for p in parts if p)


def params_text(report: Report) -> str:
    items = []
    for k, v in report.params.items():
        if v is None or v == "" or v is False:
            continue
        items.append(f"{k} {v.isoformat() if isinstance(v, date) else v}")
    return "; ".join(items) or "none"


def header_lines(report: Report) -> list[str]:
    return [
        f"Scope: {scope_text(report)}",
        f"Parameters: {params_text(report)}",
        f"Generated at {_ist(report.generated_at)} by {generated_by_text(report)}",
        report.as_of_note,
    ]


def section_note(section: Section) -> str | None:
    """The section note, with "first N of M rows" when the rows were capped."""
    note = section.note or ""
    cap = f"First {len(section.rows)} of {section.total_rows} rows."
    if section.truncated and cap not in note:
        note = f"{cap} {note}".strip()
    return note or None


def _cell_text(column: Column, value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(IST).strftime("%d-%m-%Y")
    if isinstance(value, date):
        return value.strftime("%d-%m-%Y")
    return str(value)


def filename(report: Report, ext: str, now: datetime | None = None) -> str:
    """Decision 12: `aslms-<report>-<scope>-<yyyymmdd-hhmm>.<ext>` (IST)."""
    now = now or report.generated_at
    scope = (report.department_code or "state").lower()
    scope = re.sub(r"[^a-z0-9_-]", "-", scope)
    return f"aslms-{report.key}-{scope}-{now.astimezone(IST).strftime('%Y%m%d-%H%M')}.{ext}"


# ------------------------------------------------------------------------------------------------ Excel


def _sheet_name(title: str, used: set[str]) -> str:
    base = SHEET_BAD.sub(" ", title).strip()[:31] or "Sheet"
    name, n = base, 2
    while name.lower() in used:
        suffix = f" ({n})"
        name = base[: 31 - len(suffix)] + suffix
        n += 1
    used.add(name.lower())
    return name


def to_xlsx(report: Report) -> bytes:
    """One sheet per section, each opening with the report header (title, scope, parameters, generated at and by,
    the as-of note), then the section title and note, the column headers (frozen), the rows and a bold totals row.
    Dates are Excel dates. Built in memory (`in_memory`: no temporary file holds case data)."""
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_numbers": False, "strings_to_urls": False})
    title_f = wb.add_format({"bold": True, "font_size": 13})
    bold = wb.add_format({"bold": True})
    italic = wb.add_format({"italic": True})
    head_f = wb.add_format({"bold": True, "bg_color": "#E6E6E6", "border": 1, "text_wrap": True})
    date_f = wb.add_format({"num_format": "dd-mm-yyyy"})
    total_f = wb.add_format({"bold": True, "bg_color": "#F2F2F2"})
    total_date_f = wb.add_format({"bold": True, "bg_color": "#F2F2F2", "num_format": "dd-mm-yyyy"})
    used: set[str] = set()
    for section in report.sections:
        ws = wb.add_worksheet(_sheet_name(section.title, used))
        r = 0
        ws.write_string(r, 0, report.title, title_f)
        r += 1
        for line in header_lines(report):
            ws.write_string(r, 0, line)
            r += 1
        ws.write_string(r, 0, section.title, bold)
        r += 1
        note = section_note(section)
        if note:
            ws.write_string(r, 0, note, italic)
            r += 1
        r += 1
        widths = [max(10, min(40, len(c.label) + 2)) for c in section.columns]
        for ci, col in enumerate(section.columns):
            ws.write_string(r, ci, col.label, head_f)
        ws.freeze_panes(r + 1, 0)
        r += 1
        for row in section.rows:
            _write_row(ws, r, section.columns, row, date_f, None, widths)
            r += 1
        if not section.rows:
            ws.write_string(r, 0, "No rows.", italic)
            r += 1
        if section.totals is not None:
            _write_row(ws, r, section.columns, section.totals, total_date_f, total_f, widths)
        for ci, w in enumerate(widths):
            ws.set_column(ci, ci, w)
    wb.close()
    return buf.getvalue()


def _write_row(
    ws, r: int, columns: list[Column], row: dict[str, Any], date_f, fmt, widths: list[int]
) -> None:
    for ci, col in enumerate(columns):
        value = row.get(col.key)
        if value is None:
            if fmt is not None:
                ws.write_blank(r, ci, None, fmt)
            continue
        if col.kind in ("int", "days") and isinstance(value, int | float):
            ws.write_number(r, ci, value, fmt)
        elif col.kind == "date" and isinstance(value, date):
            d = value.astimezone(IST).date() if isinstance(value, datetime) else value
            ws.write_datetime(r, ci, d, date_f)
        else:
            text = str(value)
            ws.write_string(r, ci, text, fmt)
            widths[ci] = max(widths[ci], min(60, len(text) + 2))


# ------------------------------------------------------------------------------------------------ PDF


def _header_html(report: Report) -> str:
    lines = "".join(f"<p>{html.escape(line)}</p>" for line in header_lines(report))
    return f"<h1>{html.escape(report.title)}</h1>{lines}"


def _row_html(columns: list[Column], row: dict[str, Any], idx: int, css: str = "") -> str:
    cells = []
    for col in columns:
        cls = ' class="n"' if col.kind in ("int", "days") else ""
        cells.append(f"<td{cls}>{html.escape(_cell_text(col, row.get(col.key)))}</td>")
    klass = f' class="{css}"' if css else ""
    return f'<tr id="r{idx}"{klass}>{"".join(cells)}</tr>'


def _table_html(columns: list[Column], rows_html: list[str]) -> str:
    head = "".join(f"<th>{html.escape(c.label)}</th>" for c in columns)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows_html)}</tbody></table>"


def _place(content: str, row_ids: list[str] | None = None) -> tuple[int, bool]:
    """Lays `content` out on a probe; returns how many of `row_ids` fit on one page and whether all did."""
    story = pymupdf.Story(html=content, user_css=PDF_CSS)
    more, _ = story.place(WHERE)
    if not row_ids:
        return 0, not more
    placed: set[str] = set()

    def seen(pos) -> None:
        if pos.id and pos.rect[3] <= WHERE.y1 + 0.5:
            placed.add(pos.id)

    story.element_positions(seen, {})
    n = 0
    for rid in row_ids:
        if rid not in placed:
            break
        n += 1
    return n, not more


def _draw(writer, content: str) -> None:
    story = pymupdf.Story(html=content, user_css=PDF_CSS)
    device = writer.begin_page(PAGE)
    story.place(WHERE)
    story.draw(device)
    writer.end_page()


def to_pdf(report: Report) -> bytes:
    """A4 landscape: the report header on page 1, one table per section (each section from a new page), the
    column headers repeated on every page of a table, totals in bold, "first N of M rows" on a capped section and
    "Page n of m" in the footer. Every value is HTML-escaped."""
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    first = True
    for section in report.sections:
        rows_html = [_row_html(section.columns, row, i) for i, row in enumerate(section.rows)]
        if section.totals is not None:
            rows_html.append(_row_html(section.columns, section.totals, len(rows_html), "total"))
        ids = [f"r{i}" for i in range(len(rows_html))]
        start, cont = 0, False
        while True:
            intro = _header_html(report) if first else ""
            title = html.escape(section.title + (" (continued)" if cont else ""))
            intro += f"<h2>{title}</h2>"
            note = section_note(section)
            if note and not cont:
                intro += f'<p class="note">{html.escape(note)}</p>'
            if not rows_html:
                _draw(writer, intro + "<p>No rows.</p>")
                first = False
                break
            remaining = rows_html[start:]
            content = intro + _table_html(section.columns, remaining)
            n, all_fit = _place(content, ids[start:])
            if all_fit and n >= len(remaining):
                _draw(writer, content)
                first = False
                break
            n = max(1, n)
            _draw(writer, intro + _table_html(section.columns, remaining[:n]))
            first = False
            start += n
            cont = True
            if start >= len(rows_html):
                break
    if not report.sections:
        _draw(writer, _header_html(report))
    writer.close()
    doc = pymupdf.open("pdf", buf.getvalue())
    total = doc.page_count
    footer_y = PAGE.y1 - MARGIN_BOTTOM / 2
    for page in doc:
        page.insert_text((MARGIN_X, footer_y), report.title, fontsize=7)
        label = f"Page {page.number + 1} of {total}"
        width = pymupdf.get_text_length(label, fontsize=7)
        page.insert_text((PAGE.x1 - MARGIN_X - width, footer_y), label, fontsize=7)
    out = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return out


# ------------------------------------------------------------------------------------------------ audit


def audit_export(session: Session, actor: Actor, report: Report, fmt: str) -> None:
    """Decision 13: one `report.exported` row (entity `report`, no id) per xlsx or pdf file."""
    write_audit(
        session,
        actor,
        "report.exported",
        "report",
        None,
        after={
            "report": report.key,
            "scope": report.scope,
            "department": report.department_code,
            "params": report.params,
            "format": fmt,
            "rows": report.rows,
            "truncated": report.truncated,
        },
    )
