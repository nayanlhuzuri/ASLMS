"""The Excel and PDF export of the Insights case list (design `state-insights`, decision 27).

- `FIELDS`: the owner's numbered fields in four groups, the defaults marked; `parse_fields` (400 `bad_field`).
- `rows`: the filtered list in the list's order, cases of the scope that the viewer may open only (the scope's
  condition in the SQL, decision 20), read by a server-side cursor in chunks of 2,000; never a note, a draft, a custody
  remark, a document or a document description.
- `to_xlsx`: XlsxWriter in `constant_memory` mode (its temporary files in a private directory removed after the
  build): the first sheet "About This Export" (title, scope, the filters in words, who exported and when in IST, the
  coverage line, the row count and "First N of M" above the cap), the second "Cases" with the rows; a cell is cut at
  32,000 characters with "…".
- `to_pdf`: A4 landscape on the reports' page frame (`report_export`'s page, margins, CSS and footer), the filters at
  the top, at most `INSIGHTS_PDF_MAX_ROWS` rows with "First 2,000 of N cases. Export to Excel for every case." above.
- `audit_export`: one `insights.exported` row (entity `insights`, no id) with the scope, department, filters, fields,
  format, rows and truncation, written by the caller after the file is built."""

from __future__ import annotations

import html
import io
import re
import tempfile
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pymupdf
import xlsxwriter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aslms.core.clock import today_ist
from aslms.domain.cases import Case, CaseAct, CaseParty, PartyRole
from aslms.domain.courts import CaseType
from aslms.domain.org import Office, User
from aslms.domain.ownership import CaseOwnership, OwnershipRole, OwnershipStatus
from aslms.domain.reference import RefCaseStage
from aslms.domain.workflow import CaseStage
from aslms.services import case_closure
from aslms.services import insights as I
from aslms.services import insights_filters as F
from aslms.services import insights_rules as R
from aslms.services.access import Member
from aslms.services.audit import Actor, write_audit
from aslms.services.insights_scope import FACTS, Scope
from aslms.services.refno import IST
from aslms.services.report_export import (
    MARGIN_BOTTOM,
    MARGIN_X,
    PAGE,
    PDF_CSS,
    PDF_MEDIA_TYPE,
    WHERE,
    XLSX_MEDIA_TYPE,
)

CHUNK = 2000
CELL_MAX = 32_000
PDF_PAGE_TRY = 60
TITLE = "ASLMS Insights: Cases"
GROUPS = (
    ("identity", "Case Identity"),
    ("parties", "Parties and Counsel"),
    ("court", "Court and Hearings"),
    ("work", "Ownership and Work in ASLMS"),
)
__all__ = ["PDF_MEDIA_TYPE", "XLSX_MEDIA_TYPE", "FIELDS", "parse_fields", "rows", "to_xlsx", "to_pdf"]


@dataclass(frozen=True)
class Field:
    key: str
    number: int | None
    label: str
    group: str
    default: bool = False
    excel_only: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "number": self.number,
            "label": self.label,
            "group": self.group,
            "default": self.default,
            "excel_only": self.excel_only,
        }


FIELDS: tuple[Field, ...] = (
    Field("case_no", 1, "Case Number", "identity", True),
    Field("cnr", 2, "CNR", "identity", True),
    Field("ref_no", 3, "ASLMS Reference Number", "identity"),
    Field("kind", 4, "Kind of Case", "identity", True),
    Field("case_type_code", 5, "Court's Case Type Code", "identity"),
    Field("subject", 6, "Subject (Court Category)", "identity", True),
    Field("filing_date", 7, "Filing Date", "identity"),
    Field("registration_date", 8, "Registration Date", "identity", True),
    Field("pending_for", 9, "Pending For (or Time Taken)", "identity", True),
    Field("petitioners", 10, "Petitioners", "parties", True),
    Field("respondents", 11, "Respondents", "parties", True),
    Field("state_case", 12, "State Case", "parties", True),
    Field("department_named", 13, "Department Named in the Cause Title", "parties", True),
    Field("posts", 14, "Posts Named", "parties"),
    Field("petitioner_advocate", 15, "Petitioner's Advocate", "parties"),
    Field("government_codes", 16, "Counsel Code for the Government", "parties", True),
    Field("acts", 17, "Acts and Sections", "parties"),
    Field("status", 18, "Status", "court", True),
    Field("next_hearing", 19, "Next Hearing", "court", True),
    Field("next_purpose", 20, "Next Hearing Purpose", "court"),
    Field("coram", 21, "Bench or Judges", "court"),
    Field("last_hearing_date", 22, "Last Hearing Date", "court"),
    Field("latest_order_date", 23, "Latest Order Date", "court", True),
    Field("orders_count", 24, "Number of Orders", "court"),
    Field("disposal", 25, "Disposal Date and Outcome", "court"),
    Field("original_writ", 26, "Original Writ (Contempt)", "court"),
    Field("owning_department", 27, "Owning Department", "work", True),
    Field("with_officer", 28, "With Officer", "work", True),
    Field("recommended_to", 29, "Recommended To", "work", True),
    Field("pending_action", 30, "Pending Action and Due Date", "work", True),
    Field("case_stage", 31, "Case Stage", "work"),
    Field("open_closed", 32, "Open or Closed in ASLMS", "work"),
    Field("link", 33, "Link to the Case Page", "work", excel_only=True),
)
APPLICATIONS = Field("applications_pending", None, "Applications Pending", "work")
BY_KEY = {f.key: f for f in FIELDS}
DEFAULT_KEYS = tuple(f.key for f in FIELDS if f.default)
DATE_KEYS = frozenset({"filing_date", "registration_date", "last_hearing_date", "latest_order_date"})
NUMBER_KEYS = frozenset({"case_type_code", "orders_count", "applications_pending"})


class BadField(ValueError):
    """An unknown export field (HTTP 400 `bad_field` naming it)."""

    code = "bad_field"

    def __init__(self, key: str) -> None:
        super().__init__(f"{key!r} is not an export field")
        self.key = key


def registry() -> list[dict[str, Any]]:
    """`GET /insights/fields`: the 33 numbered fields, then Applications Pending."""
    return [f.as_dict() for f in FIELDS] + [APPLICATIONS.as_dict()]


def parse_fields(value: str | None, fmt: str, f: F.InsightFilters) -> list[Field]:
    """The asked fields in the registry's order (the defaults when none is named); Link to the Case Page only for
    Excel; Applications Pending added whenever IAs are inside their main case."""
    if value is None or not value.strip():
        keys = list(DEFAULT_KEYS)
    else:
        keys = [k.strip() for k in value.split(",") if k.strip()]
        for k in keys:
            if k not in BY_KEY and k != APPLICATIONS.key:
                raise BadField(k)
    chosen = [fd for fd in FIELDS if fd.key in keys and not (fd.excel_only and fmt != "xlsx")]
    if not f.include_ia:
        chosen.append(APPLICATIONS)
    return chosen


# ------------------------------------------------------------------------------------------------ the rows


def _join(values: list[str]) -> str:
    return "; ".join(v for v in values if v)


def _day(d: date | None) -> str:
    return d.strftime("%d-%m-%Y") if d is not None else ""


def pending_for(start: date | None, end: date) -> str:
    """Years and months between two dates in words ("2 Years 3 Months"); blank without a start."""
    if start is None:
        return ""
    months = (end.year - start.year) * 12 + (end.month - start.month) - (1 if end.day < start.day else 0)
    months = max(0, months)
    y, m = divmod(months, 12)
    parts = []
    if y:
        parts.append(f"{y} Year{'s' if y != 1 else ''}")
    if m or not y:
        parts.append(f"{m} Month{'s' if m != 1 else ''}")
    return " ".join(parts)


def hearing_words(on: date | None, status: str, today: date) -> str:
    """Field 19: the date with its urgency in words ("Today", "In 5 Days", "Date Passed", "No Date Yet",
    "Disposed")."""
    band = R.hearing_band(on, status, today)
    if band == "disposed":
        return "Disposed"
    if band == "none":
        return "No Date Yet"
    words = {"today": "Today", "tomorrow": "Tomorrow", "passed": "Date Passed"}.get(band)
    if words is None:
        days = (on - today).days
        words = f"In {days} Day{'s' if days != 1 else ''}"
    return f"{_day(on)} ({words})"


def _details(
    session: Session,
    ids: list[uuid.UUID],
    scope: Scope,
    f: F.InsightFilters,
    today: date,
    keys: set[str],
    base_url: str,
) -> dict[uuid.UUID, dict[str, Any]]:
    items = {it["case"]["id"]: it for it in I.case_items(session, ids, scope, f, today=today)}
    cases: dict[uuid.UUID, tuple] = {}
    rows = session.execute(
        select(
            Case,
            FACTS.latest_order_on,
            FACTS.orders_count,
            FACTS.posts,
            FACTS.government_codes,
            FACTS.original_writ_text,
            CaseType.case_type_code,
        )
        .select_from(Case)
        .outerjoin(FACTS, FACTS.case_id == Case.id)
        .outerjoin(CaseType, CaseType.id == Case.case_type_id)
        .where(Case.id.in_(ids))
    ).all()
    for c, latest, n_orders, posts, gov, writ, type_code in rows:
        cases[c.id] = (c, latest, n_orders, posts or [], gov or [], writ, type_code)
    parties: dict[uuid.UUID, dict[str, list[str]]] = {}
    if keys & {"petitioners", "respondents"}:
        for cid, role, name in session.execute(
            select(CaseParty.case_id, CaseParty.role, CaseParty.name)
            .where(CaseParty.case_id.in_(ids), CaseParty.is_current.is_(True))
            .order_by(CaseParty.case_id, CaseParty.role, CaseParty.party_no)
        ).all():
            parties.setdefault(cid, {"petitioner": [], "respondent": []})[PartyRole(role).value].append(name)
    acts: dict[uuid.UUID, list[str]] = {}
    if "acts" in keys:
        for cid, act, section in session.execute(
            select(CaseAct.case_id, CaseAct.act_name_as_listed, CaseAct.section)
            .where(CaseAct.case_id.in_(ids))
            .order_by(CaseAct.case_id, CaseAct.act_name_as_listed, CaseAct.section)
        ).all():
            acts.setdefault(cid, []).append(f"{act} {section}".strip())
    owners: dict[uuid.UUID, str] = {}
    if keys & {"owning_department"}:
        for cid, name in session.execute(
            select(CaseOwnership.case_id, Office.name)
            .join(Office, Office.id == CaseOwnership.office_id)
            .where(
                CaseOwnership.case_id.in_(ids),
                CaseOwnership.status == OwnershipStatus.ACTIVE,
                CaseOwnership.role == OwnershipRole.PRIMARY,
            )
        ).all():
            owners[cid] = name
    custody: dict[uuid.UUID, Any] = {}
    if "pending_action" in keys:
        custody = {
            r.case_id: r
            for r in session.execute(
                select(F.CUSTODY.case_id, F.CUSTODY.pending_action, F.CUSTODY.due_date).where(
                    F.CUSTODY.case_id.in_(ids)
                )
            ).all()
        }
    stages: dict[uuid.UUID, str] = {}
    if "case_stage" in keys:
        latest = (
            select(
                CaseStage.case_id,
                CaseStage.stage,
                func.row_number()
                .over(partition_by=CaseStage.case_id, order_by=CaseStage.created_at.desc())
                .label("rn"),
            )
            .where(CaseStage.case_id.in_(ids))
            .subquery()
        )
        for cid, label in session.execute(
            select(latest.c.case_id, RefCaseStage.label)
            .join(RefCaseStage, RefCaseStage.code == latest.c.stage)
            .where(latest.c.rn == 1)
        ).all():
            stages[cid] = label
    closed: set[uuid.UUID] = set()
    if "open_closed" in keys:
        closed = set(
            session.scalars(
                select(Case.id).where(Case.id.in_(ids), case_closure.closed_condition(Case.id))
            ).all()
        )

    out: dict[uuid.UUID, dict[str, Any]] = {}
    for cid in ids:
        if cid not in cases or cid not in items:
            continue
        c, latest, n_orders, posts, gov, writ, type_code = cases[cid]
        it = items[cid]
        status = it["status"]
        start = c.registration_date or c.filing_date or c.date_first_list
        end = (c.disposal_date or today) if status == "disposed" else today
        ps = parties.get(cid, {"petitioner": [], "respondent": []})
        who = it["who"]
        named = [d["name"] for d in it["departments_named"]] or it["phrases_unmapped"]
        cu = custody.get(cid)
        action = I.pending_action_words(cu.pending_action) if cu is not None else None
        parsed = R.parse_category(c.category)
        values = {
            "case_no": c.case_no_text or "",
            "cnr": c.cnr or "",
            "ref_no": c.ref_no,
            "kind": it["kind"]["label"],
            "case_type_code": type_code,
            "subject": parsed[1] if parsed else (c.category or ""),
            "filing_date": c.filing_date,
            "registration_date": c.registration_date,
            "pending_for": pending_for(start, end),
            "petitioners": _join(ps["petitioner"]) or (c.petitioner_summary or ""),
            "respondents": _join(ps["respondent"]) or (c.respondent_summary or ""),
            "state_case": I.basis_words(it["state_basis"]),
            "department_named": _join(named),
            "posts": _join([R.POST_LABELS[p] for p in posts if p in R.POST_LABELS]),
            "petitioner_advocate": c.pet_advocate or "",
            "government_codes": _join(gov),
            "acts": _join(acts.get(cid, [])),
            "status": status.title(),
            "next_hearing": hearing_words(c.next_hearing_on, status, today),
            "next_purpose": c.next_purpose or "",
            "coram": c.coram or "",
            "last_hearing_date": c.last_hearing_date,
            "latest_order_date": latest,
            "orders_count": int(n_orders or 0),
            "disposal": (
                f"{_day(c.disposal_date)} · {dict(R.OUTCOMES)[R.outcome_key(c.disposal_type)]}"
                if status == "disposed"
                else ""
            ),
            "original_writ": writ or "",
            "owning_department": owners.get(cid, ""),
            "with_officer": (
                ", ".join(p for p in (who.get("officer_name"), who.get("designation")) if p)
                + (f" · {who['text'].split(' · ', 1)[1]}" if " · " in who["text"] else "")
                if who["kind"] == "officer"
                else ""
            ),
            "recommended_to": (
                who["text"].split("Recommended to ", 1)[1] if who["kind"] == "recommended" else ""
            ),
            "pending_action": (
                f"{action}" + (f" · Due {_day(cu.due_date)}" if cu.due_date else "") if action else ""
            ),
            "case_stage": stages.get(cid, ""),
            "open_closed": "Closed" if cid in closed else "Open",
            "link": f"{base_url}/cases/{c.ref_no.replace('/', '-')}"
            if base_url
            else f"/cases/{c.ref_no.replace('/', '-')}",
            "applications_pending": it["applications_pending"] or 0,
        }
        out[cid] = values
    return out


def count(session: Session, f: F.InsightFilters, scope: Scope, cfg: I.InsightsConfig, today: date) -> int:
    e = F.expressions(today, cfg.due_soon_days)
    stmt = I.filtered_ids(session, f, scope, e, cfg.due_soon_days, "next")
    return int(session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)


def rows(
    session: Session,
    user: User | Member,
    f: F.InsightFilters,
    scope: Scope,
    fields: list[Field],
    limit: int,
    *,
    sort: str = "next",
    cfg: I.InsightsConfig | None = None,
    today: date | None = None,
) -> Iterator[dict[str, Any]]:
    """The export's rows in the list's order, at most `limit`, read by a server-side cursor (`yield_per` 2,000)."""
    cfg = cfg or I.InsightsConfig.from_settings()
    today = today or today_ist()
    e = F.expressions(today, cfg.due_soon_days)
    stmt = I.filtered_ids(session, f, scope, e, cfg.due_soon_days, sort).limit(limit)
    keys = {fd.key for fd in fields}
    result = session.execute(stmt.execution_options(yield_per=CHUNK))
    for part in result.partitions(CHUNK):
        ids = [r[0] for r in part]
        details = _details(session, ids, scope, f, today, keys, cfg.portal_base_url)
        for cid in ids:
            if cid in details:
                yield {k: details[cid].get(k) for k in keys}


# ------------------------------------------------------------------------------------------------ the files


@dataclass
class ExportMeta:
    scope_words: str
    filters: list[str]
    exported_by: str
    exported_at: datetime
    coverage_line: str
    total: int
    written: int = 0

    @property
    def truncated(self) -> bool:
        return self.written < self.total


def _cell(value: Any) -> Any:
    if isinstance(value, str) and len(value) > CELL_MAX:
        return value[: CELL_MAX - 1] + "…"
    return value


def _ist(dt: datetime) -> str:
    return dt.astimezone(IST).strftime("%d-%m-%Y %H:%M IST")


def about_lines(meta: ExportMeta) -> list[tuple[str, str]]:
    shown = f"First {meta.written:,} of {meta.total:,}" if meta.truncated else f"{meta.written:,}"
    return [
        ("Scope", meta.scope_words),
        ("Filters", "; ".join(meta.filters) or "None"),
        ("Exported By", meta.exported_by),
        ("Exported At", _ist(meta.exported_at)),
        ("Covers", meta.coverage_line),
        ("Cases", shown),
    ]


def to_xlsx(meta: ExportMeta, fields: list[Field], data: Iterator[dict[str, Any]], max_rows: int) -> bytes:
    """Decision 27: "About This Export" then "Cases". The rows are buffered only as XlsxWriter's own streamed
    temporary files, in a private directory removed afterwards."""
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory(prefix="aslms-insights-") as tmp:
        wb = xlsxwriter.Workbook(
            buf,
            {"constant_memory": True, "tmpdir": tmp, "strings_to_numbers": False, "strings_to_urls": False},
        )
        bold = wb.add_format({"bold": True})
        title_f = wb.add_format({"bold": True, "font_size": 13})
        head_f = wb.add_format({"bold": True, "bg_color": "#E6E6E6", "border": 1, "text_wrap": True})
        date_f = wb.add_format({"num_format": "dd-mm-yyyy"})
        # the About sheet comes first in the file: it states the count the cap allows, then the rows stream
        meta.written = min(meta.total, max_rows)
        about = wb.add_worksheet("About This Export")
        about.write_string(0, 0, TITLE, title_f)
        for i, (k, v) in enumerate(about_lines(meta), start=2):
            about.write_string(i, 0, k, bold)
            about.write_string(i, 1, v)
        about.set_column(0, 0, 16)
        about.set_column(1, 1, 100)
        ws = wb.add_worksheet("Cases")
        for ci, fd in enumerate(fields):
            ws.write_string(0, ci, fd.label, head_f)
            ws.set_column(ci, ci, 14 if fd.key in DATE_KEYS else max(12, min(40, len(fd.label) + 4)))
        written = 0
        for row in data:
            if written >= max_rows:
                break
            written += 1
            ri = written
            for ci, fd in enumerate(fields):
                v = row.get(fd.key)
                if v is None or v == "":
                    continue
                if fd.key in DATE_KEYS and isinstance(v, date):
                    ws.write_datetime(ri, ci, datetime(v.year, v.month, v.day), date_f)
                elif fd.key in NUMBER_KEYS and isinstance(v, int):
                    ws.write_number(ri, ci, v)
                else:
                    ws.write_string(ri, ci, str(_cell(v)))
        meta.written = written
        wb.close()
    return buf.getvalue()


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return _day(value)
    return str(value)


def _pdf_rows_html(fields: list[Field], rows_: list[dict[str, Any]], start: int) -> list[str]:
    out = []
    for i, row in enumerate(rows_):
        cells = "".join(f"<td>{html.escape(_text(row.get(fd.key)))}</td>" for fd in fields)
        out.append(f'<tr id="r{start + i}">{cells}</tr>')
    return out


def _table(fields: list[Field], rows_html: list[str]) -> str:
    head = "".join(f"<th>{html.escape(fd.label)}</th>" for fd in fields)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows_html)}</tbody></table>"


def _fits(content: str, ids: list[str]) -> int:
    story = pymupdf.Story(html=content, user_css=PDF_CSS)
    story.place(WHERE)
    placed: set[str] = set()

    def seen(pos) -> None:
        if pos.id and pos.rect[3] <= WHERE.y1 + 0.5:
            placed.add(pos.id)

    story.element_positions(seen, {})
    n = 0
    for rid in ids:
        if rid not in placed:
            break
        n += 1
    return n


def _draw(writer, content: str) -> None:
    story = pymupdf.Story(html=content, user_css=PDF_CSS)
    device = writer.begin_page(PAGE)
    story.place(WHERE)
    story.draw(device)
    writer.end_page()


def to_pdf(meta: ExportMeta, fields: list[Field], data: Iterator[dict[str, Any]], max_rows: int) -> bytes:
    """Decision 27: A4 landscape, the filters at the top, at most `max_rows` rows; above the cap the line "First
    2,000 of N cases. Export to Excel for every case."; "Page n of m" in the footer. Each page lays out at most
    `PDF_PAGE_TRY` rows, so the build grows with the rows, not their square."""
    rows_list: list[dict[str, Any]] = []
    for row in data:
        if len(rows_list) >= max_rows:
            break
        rows_list.append(row)
    meta.written = len(rows_list)
    intro = f"<h1>{html.escape(TITLE)}</h1>" + "".join(
        f"<p><b>{html.escape(k)}:</b> {html.escape(v)}</p>" for k, v in about_lines(meta)
    )
    if meta.truncated:
        intro += f'<p class="note">First {meta.written:,} of {meta.total:,} cases. Export to Excel for every case.</p>'
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    start, first = 0, True
    if not rows_list:
        _draw(writer, intro + "<p>No case matches this selection.</p>")
    while start < len(rows_list):
        head = intro if first else f"<h2>{html.escape(TITLE)} (continued)</h2>"
        chunk = rows_list[start : start + PDF_PAGE_TRY]
        rows_html = _pdf_rows_html(fields, chunk, start)
        ids = [f"r{start + i}" for i in range(len(chunk))]
        n = max(1, _fits(head + _table(fields, rows_html), ids))
        _draw(writer, head + _table(fields, rows_html[:n]))
        start += n
        first = False
    writer.close()
    doc = pymupdf.open("pdf", buf.getvalue())
    total = doc.page_count
    footer_y = PAGE.y1 - MARGIN_BOTTOM / 2
    for page in doc:
        page.insert_text((MARGIN_X, footer_y), TITLE, fontsize=7)
        label = f"Page {page.number + 1} of {total}"
        width = pymupdf.get_text_length(label, fontsize=7)
        page.insert_text((PAGE.x1 - MARGIN_X - width, footer_y), label, fontsize=7)
    out = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return out


def filename(scope: Scope, ext: str, now: datetime) -> str:
    """`ASLMS_Insights_<scope>_<YYYY-MM-DD_HHMM>.<ext>` (IST)."""
    word = "State" if scope.is_state else re.sub(r"[^A-Za-z0-9_-]", "-", scope.department.code)
    return f"ASLMS_Insights_{word}_{now.astimezone(IST).strftime('%Y-%m-%d_%H%M')}.{ext}"


def exporter_words(member: Member) -> str:
    return ", ".join(p for p in (member.full_name, member.designation, member.office.name) if p)


def audit_export(
    session: Session,
    actor: Actor,
    scope: Scope,
    f: F.InsightFilters,
    fields: list[Field],
    fmt: str,
    meta: ExportMeta,
) -> None:
    """Decision 27: one `insights.exported` row (entity `insights`, no id), after the file is built."""
    write_audit(
        session,
        actor,
        "insights.exported",
        "insights",
        None,
        after={
            "scope": scope.kind,
            "department": scope.department.code if scope.department is not None else None,
            "filters": f.as_params(),
            "fields": [fd.key for fd in fields],
            "format": fmt,
            "rows": meta.written,
            "total": meta.total,
            "truncated": meta.truncated,
        },
    )
